"""Observe R7 and reconcile the canonical 288-slot Combined execution path."""
from __future__ import annotations

import asyncio
from datetime import timedelta, datetime, timezone
from copy import deepcopy
from typing import Any, Callable

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .combined_anker_bridge import CombinedAnkerBridge
from .execution_controller import ExecutionController
from .execution_anker_adapter import AnkerExecutionAdapter
from .alpha84_prestart_validator import AnkerEmsPreStartValidator
from .alpha84_safety_guard import AnkerEmsSafetyGuard
from .final_revalidation import DOEMSFinalRevalidation
from .execution_common_safety import common_prestart_blockers
from .execution_energy_meter import sample_energy, planned_energy_reached


class DOEMSCombinedExecutionShadowRuntime:
    def __init__(self, hass: Any, scheduler: Any, store: Any, *, entities=None, authority=False, planner=None, battery=None) -> None:
        self.hass = hass
        self._doems_prestart = AnkerEmsPreStartValidator()
        self._doems_safety_guard = AnkerEmsSafetyGuard()
        self._doems_final_revalidation = DOEMSFinalRevalidation()
        self.scheduler = scheduler
        self.store = store
        self._authority = bool(authority)
        # Master permission is OFF on every startup; it never grants authority.
        self._master_enabled = False
        self._exclusive_claimed = False
        self._combined_bridge = None
        self._combined_last_result: dict[str, Any] = {"bridge": "startup", "physical_execution_enabled": False}
        self.adapter = AnkerExecutionAdapter(hass, entities or {}, authority=self._authority)
        self.controller = ExecutionController(self.adapter, authorized=self._combined_authorized, revalidate=self._identity_current)
        if planner is not None:
            self._combined_bridge = CombinedAnkerBridge(
                planner, self.adapter, battery=battery,
                authority=False, exclusive=False, controller=self.controller,
                master_enabled=lambda: self._master_enabled,
            )
        self._active_plan = None
        self._active_slot = None
        self._started = set()
        self.last_result: dict[str, Any] = {"status": "startup", "physical_execution_enabled": False}
        self._unsubs: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []
        self._task: asyncio.Task | None = None
        self._dirty = False
        self._shutdown = False
        self._restart_reconciled = False
        self._last_stop_blockers = []
        self._active_energy_sample = {}

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return remove

    @property
    def master_enabled(self) -> bool:
        return self._master_enabled

    def claim_exclusive_authority(self) -> bool:
        """Explicit, non-actuating claim. Never grant from a UI master toggle."""
        self._exclusive_claimed = False
        self._authority = False
        self.adapter.authority = False
        if (self._shutdown or self._master_enabled
                or self.controller.session is not None
                or self.controller.reconciliation_required):
            return False
        if not all(self.adapter.entities.get(name) for name in
                   ("operating_mode", "action_direction", "power_setpoint")):
            return False
        if self.adapter._state("operating_mode") != "self_consumption":
            return False
        # One existing DOEMS R8 controller owns all starts; R9's separate
        # planner bridge is kept permanently non-actuating.
        # R8 and the Combined bridge must share the same single-writer claim.
        self._exclusive_claimed = True
        self._authority = True
        self.adapter.authority = True
        return True

    async def async_set_master_enabled(self, enabled: bool) -> None:
        """Master gate: switching off also fences in-flight execution."""
        if enabled:
            # The operator's existing master switch can request a verified
            # standalone claim; it never bypasses live single-writer checks.
            if not self._exclusive_claimed and not self.claim_exclusive_authority():
                raise ValueError("Physical execution unavailable: exclusive DOEMS control not verified")
            # Never present the master switch as armed while the proven
            # legacy-to-DOEMS single-writer authority handoff is absent.
            # Physical authority and exclusive ownership must be established
            # and validated independently; the UI switch cannot grant them.
            if not (
                self._authority
                and self.adapter.authority
                and self._combined_bridge is not None
                and self._exclusive_claimed
            ):
                raise ValueError("Physical execution unavailable: verified exclusive authority handoff required")
            if self._shutdown:
                raise ValueError("Cannot enable a stopped execution runtime")
            if self.controller.session is not None or self.controller.reconciliation_required:
                raise ValueError("Cannot enable while execution or reconciliation is active")
            self._master_enabled = True
        else:
            # Revoke permission before any asynchronous stop attempt.
            self._master_enabled = False
            try:
                if self.controller.session is not None or self.controller.reconciliation_required:
                    await self.controller.stop()
            finally:
                for listener in tuple(self._listeners):
                    listener()
                self.refresh()
            return
        for listener in tuple(self._listeners):
            listener()
        self.refresh()

    def _combined_authorized(self) -> bool:
        return bool(self._master_enabled and self._exclusive_claimed
                    and self._authority and self.adapter.authority
                    and self._combined_bridge is not None
                    and self.controller is self._combined_bridge.controller)

    def _combined_identity_current(self, identity: tuple) -> bool:
        return bool(self._combined_bridge is not None and self._combined_bridge._still_current(identity))

    def _automatic_final_safe(self, identity: tuple) -> bool:
        """Rebuild final Alpha84 evidence from current DOEMS state for every write."""
        try:
            decision = self.scheduler.last_result
            slot = decision.get("selected_slot")
            if type(slot) is not int or slot not in (1, 2, 3):
                return False
            plan = self.store.get_plan(slot)
            if plan.get("origin") != "automatic_72h_planner" or self._identity(slot, plan) != identity:
                return False
            if (decision.get("selected_lifecycle") != "pending"
                    or decision.get("safety_status") != "safe"
                    or decision.get("safety_blockers")):
                return False
            snapshot = self.scheduler.battery.snapshot() if self.scheduler.battery else {}
            bundle = self.scheduler.planner.bundle_snapshot()
            settings = self.scheduler._manual_safety_limits()
            reader = getattr(self.scheduler.bridge, "verified_published_candidate", None)
            proof = reader(plan) if callable(reader) else None
            if not isinstance(proof, dict):
                return False
            evidence = {
                "scheduler_selected_slot": slot,
                "scheduler_slots": {slot: dict(plan)},
                "scheduler_ready": True,
                "soc": snapshot.get("soc_percent"),
                "max_charge_power_w": settings.get("max_charge_power_w"),
                "max_discharge_power_w": settings.get("max_discharge_power_w"),
                "forecast_ready": (
                    self.scheduler._sources_fresh(dt_util.utcnow(), snapshot)
                    and bundle.get("status") == "ready"
                ),
                "auto_plan_72h_valid": bundle.get("valid") is True,
                "auto_plan_72h_execution_buffer_safe": (
                    (bundle.get("automatic") or {}).get("execution_buffer_safe") is True
                ),
                "auto_bridge_valid": True,
                "auto_bridge_invalid_candidate_count": 0,
                "auto_bridge_candidates": [proof],
                "control_path_configured": all(
                    self.adapter.entities.get(k) and self.adapter._state(k) is not None
                    for k in ("operating_mode", "action_direction", "power_setpoint")
                ),
                "physical_test_active": False,
                "execution_active": self.controller.session is not None,
                "operating_mode": self.adapter._state("operating_mode"),
                "charge_power_w": snapshot.get("charge_power_w"),
                "discharge_power_w": snapshot.get("discharge_power_w"),
                "auto_execution_handoff_selected_slot": slot,
                "auto_execution_handoff_required": True,
                "auto_execution_handoff_planner_identity": plan.get("planner_identity"),
            }
            prestart = self._doems_prestart.evaluate(evidence)
            evidence.update(prestart)
            guard = self._doems_safety_guard.evaluate_automatic_handoff(evidence)
            evidence.update(guard)
            evidence["auto_execution_handoff_ready"] = (
                prestart.get("auto_prestart_safe") is True
                and guard.get("auto_safety_handoff_safe") is True
            )
            final = self._doems_final_revalidation.evaluate_final_revalidation(evidence)
            return final.get("auto_final_revalidation_safe") is True
        except (TypeError, ValueError, KeyError, AttributeError):
            return False

    def _identity_current(self, identity: tuple) -> bool:
        """Verify that R7 still selects exactly the same pending slot revision."""
        decision = self.scheduler.last_result
        slot = decision.get("selected_slot")
        if type(slot) is not int or slot not in (1, 2, 3):
            return False
        plan = self.store.get_plan(slot)
        actual = (
            slot, plan.get("lifecycle_updated_at"), plan.get("origin"),
            plan.get("planner_identity"), plan.get("planner_signature"),
            plan.get("action"), plan.get("power_w"),
            plan.get("target_soc"), plan.get("max_runtime_h"),
        )
        local = self.last_result.get("doems_alpha84_safety") or {}
        snapshot = self.scheduler.battery.snapshot() if self.scheduler.battery else {}
        common_safe = not common_prestart_blockers(
            plan, snapshot, self.scheduler._manual_safety_limits(),
            sources_fresh=self.scheduler._sources_fresh(dt_util.utcnow(), snapshot),
        )
        checks_pass = (
            plan.get("origin") == "manual"
            or ((local.get("prestart") or {}).get("auto_prestart_safe") is True
                and (local.get("safety_guard") or {}).get("auto_safety_handoff_safe") is True)
        )
        return (
            identity == actual
            and common_safe
            and checks_pass
            and (plan.get("origin") != "automatic_72h_planner" or self._automatic_final_safe(identity))
            and not self.last_result.get("blockers")
            and self._master_enabled
            and self._combined_authorized()
            and plan.get("lifecycle_status") in ("pending", "actief")
            and (plan.get("lifecycle_status") == "actief" or decision.get("selected_lifecycle") == "pending")
            and (plan.get("lifecycle_status") == "actief" or decision.get("safety_status") == "safe")
            and (plan.get("lifecycle_status") == "actief" or not decision.get("safety_blockers"))
            and self.adapter.authority
            and all(self.adapter.entities.get(key) for key in
                    ("operating_mode", "action_direction", "power_setpoint"))
        )

    async def async_setup(self) -> None:
        self._unsubs.append(self.scheduler.async_add_listener(self.refresh))
        self._unsubs.append(self.store.add_listener(self.refresh))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=5)))
        self.refresh()

    def _tick(self, _now: Any) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Thread-safe entry point for scheduler/store notifications."""
        self.hass.loop.call_soon_threadsafe(self._refresh_on_loop)

    @callback
    def _refresh_on_loop(self) -> None:
        """Only the event loop may mutate the observer task and dirty flag."""
        if self._shutdown:
            return
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._drain(), "DOEMS three-slot execution observer")

    async def _drain(self) -> None:
        while self._dirty and not self._shutdown:
            self._dirty = False
            try:
                await self._evaluate()
                if (self.controller.session is not None
                        or self.controller.reconciliation_required
                        or self._combined_authorized()):
                    await self._execute_or_monitor()
            except Exception as exc:
                self.last_result = {
                    "status": "blocked", "reason": "slot_observer_error",
                    "error_type": type(exc).__name__, "physical_execution_enabled": False,
                }
            for listener in tuple(self._listeners):
                try:
                    listener()
                except Exception:
                    # A faulty UI listener must not terminate the observer drain.
                    continue

    async def _evaluate(self) -> None:
        # The separate R9 bridge is an observer, never a second writer.
        # Its async_reconcile() may stop a shared controller when the bridge
        # lacks authority; it must NOT be called by the canonical R8 runtime.
        self._combined_last_result = {
            "bridge": "non_actuating_r9",
            "physical_execution_enabled": False,
            "execution_performed": False,
        }
        decision = dict(self.scheduler.last_result)
        slot = decision.get("selected_slot")
        if type(slot) is not int or slot not in (1, 2, 3):
            self.last_result = {
                "status": "idle", "selected_slot": None,
                "scheduler_status": decision.get("status"),
                "physical_execution_enabled": bool(self.controller.session),
                "combined_handoff": deepcopy(self._combined_last_result),
                "original_safety_observation": {
                    "status": "not_required_no_selected_plan",
                    "prestart": "not_evaluated",
                    "safety_guard": "not_evaluated",
                    "final_revalidation": "not_evaluated",
                    "physical_execution_enabled": False,
                },
            }
            return
        plan = self.store.get_plan(slot)
        blockers = list(decision.get("safety_blockers") or [])
        if plan.get("lifecycle_status") != "pending":
            blockers.append("plan_not_pending")
        if decision.get("selected_lifecycle") != plan.get("lifecycle_status"):
            blockers.append("scheduler_selection_stale")
        if plan.get("action") not in ("laden", "ontladen"):
            blockers.append("action_invalid")
        if decision.get("selected_action") != plan.get("action"):
            blockers.append("selected_action_changed")
        if decision.get("safety_status") != "safe":
            blockers.append("r7_safety_not_safe")
        # Shadow mode must report planning readiness independently of
        # physical authority. Never imply that the battery is being controlled.
        planning_ready = not blockers
        # Alpha84 guard code now runs locally on DOEMS state below.
        # No live Anker EMS coordinator is consulted for these decisions.
        alpha84_original_controller_link = {
            "status": "not_required_standalone_doems",
            "physical_execution_enabled": False,
        }
        alpha84_handoff = None
        original_safety_observation = {
            "status": "superseded_by_doems_local_guards",
            "physical_execution_enabled": False,
        }
        # Run the exact ported Alpha84 read-only guards against DOEMS R7
        # state. Missing evidence is deliberately FALSE, never invented.
        independent_safety = {"status": "blocked", "physical_execution_enabled": False}
        self._last_alpha84_evidence = None
        if planning_ready:
            snapshot = self.scheduler.battery.snapshot() if self.scheduler.battery else {}
            bundle = self.scheduler.planner.bundle_snapshot()
            fresh = self.scheduler._sources_fresh(dt_util.utcnow(), snapshot)
            settings = self.scheduler._manual_safety_limits()
            proof = None
            if plan.get("origin") == "automatic_72h_planner":
                reader = getattr(self.scheduler.bridge, "verified_published_candidate", None)
                proof = reader(plan) if callable(reader) else None
            detail = dict(plan)
            evidence = {
                "scheduler_selected_slot": slot,
                "scheduler_slots": {slot: detail},
                "scheduler_ready": decision.get("selected_slot") == slot
                                   and decision.get("safety_status") == "safe",
                "soc": snapshot.get("soc_percent"),
                "max_charge_power_w": settings.get("max_charge_power_w"),
                "max_discharge_power_w": settings.get("max_discharge_power_w"),
                "forecast_ready": fresh and bundle.get("status") == "ready",
                "auto_plan_72h_valid": bundle.get("valid") is True,
                "auto_plan_72h_execution_buffer_safe": (
                    (bundle.get("automatic") or {}).get("execution_buffer_safe") is True
                ),
                "auto_bridge_valid": proof is not None,
                "auto_bridge_invalid_candidate_count": (
                    0 if proof is not None else 1
                ),
                "auto_bridge_candidates": [proof] if proof else [],
                "control_path_configured": all(
                    self.adapter.entities.get(key)
                    and self.adapter._state(key) is not None
                    for key in ("operating_mode", "action_direction", "power_setpoint")
                ),
                # This DOEMS runtime has no physical-test controller. Its only
                # writer is the R8 ExecutionController, checked separately.
                "physical_test_active": False,
                "execution_active": self.controller.session is not None,
                "operating_mode": self.adapter._state("operating_mode"),
                "charge_power_w": snapshot.get("charge_power_w"),
                "discharge_power_w": snapshot.get("discharge_power_w"),
                "plan_identity_tuple": self._identity(slot, plan),
                "auto_execution_handoff_selected_slot": slot,
                "auto_execution_handoff_required": plan.get("origin") == "automatic_72h_planner",
                "auto_execution_handoff_planner_identity": plan.get("planner_identity"),
            }
            try:
                prestart = self._doems_prestart.evaluate(evidence)
                evidence.update(prestart)
                guard = self._doems_safety_guard.evaluate_automatic_handoff(evidence)
                evidence.update(guard)
                evidence["auto_execution_handoff_ready"] = (
                    prestart.get("auto_prestart_safe") is True
                    and guard.get("auto_safety_handoff_safe") is True
                )
                final = self._doems_final_revalidation.evaluate_final_revalidation(evidence)
                independent_safety = {
                    "final_revalidation": final,
                    "status": "evaluated",
                    "prestart": prestart,
                    "safety_guard": guard,
                    "physical_execution_enabled": False,
                }
            except (TypeError, ValueError, KeyError, AttributeError) as err:
                independent_safety = {
                    "status": "blocked", "reason": type(err).__name__,
                    "physical_execution_enabled": False,
                }
        if planning_ready and plan.get("origin") == "automatic_72h_planner":
            if (independent_safety.get("prestart") or {}).get("auto_prestart_safe") is not True:
                blockers.append("doems_alpha84_prestart_blocked")
            if (independent_safety.get("safety_guard") or {}).get("auto_safety_handoff_safe") is not True:
                blockers.append("doems_alpha84_safety_guard_blocked")
            if (independent_safety.get("final_revalidation") or {}).get("auto_final_revalidation_safe") is not True:
                blockers.append("doems_alpha84_final_revalidation_blocked")
        if not self._master_enabled:
            blockers.append("master_execution_disabled")
        if not self._authority:
            blockers.append("physical_authority_disabled")
        self.last_result = {
            "status": ("slot_ready_observe" if not blockers else "blocked"),
            "selected_slot": slot,
            "origin": plan.get("origin"),
            "action": plan.get("action"),
            "power_w": plan.get("power_w"),
            "target_soc": plan.get("target_soc"),
            "max_runtime_h": plan.get("max_runtime_h"),
            "lifecycle_status": plan.get("lifecycle_status"),
            "planner_identity": plan.get("planner_identity"),
            "scheduler_status": decision.get("status"),
            "blockers": blockers,
            "observed_at": dt_util.utcnow().isoformat(),
            "physical_execution_enabled": bool(self.controller.session),
            "execution_authorized": self._combined_authorized(),
            "reconciliation_required": self.controller.reconciliation_required,
            "last_stop_blockers": list(self._last_stop_blockers),
            "combined_handoff": deepcopy(self._combined_last_result),
            "alpha84_handoff": deepcopy(alpha84_handoff),
            "original_safety_observation": original_safety_observation,
            "alpha84_original_controller_link": deepcopy(alpha84_original_controller_link),
            "doems_alpha84_safety": independent_safety,
        }

    def _identity(self, slot, plan):
        return (
            slot, plan.get("lifecycle_updated_at"), plan.get("origin"),
            plan.get("planner_identity"), plan.get("planner_signature"),
            plan.get("action"), plan.get("power_w"),
            plan.get("target_soc"), plan.get("max_runtime_h"),
        )

    @staticmethod
    def _valid_battery_power(value: Any) -> bool:
        try:
            from math import isfinite
            power = float(value)
            return isfinite(power) and power >= 0
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _non_conflicting_power(value: Any) -> bool:
        """Unavailable, invalid or non-finite battery observations fail closed."""
        try:
            from math import isfinite
            power = float(value)
            return isfinite(power) and 0 <= power <= 100
        except (TypeError, ValueError, OverflowError):
            return False

    async def _execute_or_monitor(self) -> None:
        """Use the one existing controller for both Manual and Automatic slots."""
        now = dt_util.utcnow()
        if not self._restart_reconciled:
            mode = self.adapter._state("operating_mode")
            if mode is None or mode not in ("self_consumption", "third_party_control"):
                return
            if mode == "third_party_control":
                self.controller.require_restart_reconciliation()
                await self.controller.stop()
                self._restart_reconciled = True
                return
            self._restart_reconciled = True
        if self.controller.session is not None or self.controller.reconciliation_required:
            session = self.controller.session
            snapshot = self.scheduler.battery.snapshot() if self.scheduler.battery else {}
            slot = self._active_slot
            plan = self.store.get_plan(slot) if slot in (1, 2, 3) else {}
            same_plan = bool(
                session and self._active_plan
                and plan.get("lifecycle_status") == "actief"
                and all(plan.get(key) == self._active_plan.get(key)
                        for key in ("origin", "planner_identity", "planner_signature",
                                    "action", "power_w", "target_soc", "max_runtime_h"))
            )
            if session and same_plan and plan.get("origin") == "automatic_72h_planner":
                measured = snapshot.get(
                    "charge_power_w" if session["action"] == "laden"
                    else "discharge_power_w"
                )
                self._active_energy_sample = sample_energy(
                    self._active_energy_sample, now, measured
                )
                if planned_energy_reached(
                    self._active_energy_sample, plan.get("planned_energy_kwh")
                ):
                    try:
                        await self.controller.stop()
                        await self.store.async_mark_lifecycle(
                            slot, "voltooid", "planned_energy_reached",
                            expected_plan=plan)
                        self._active_plan = None
                        self._active_slot = None
                        self._active_energy_sample = {}
                    except Exception:
                        self.controller.reconciliation_required = True
                    return
            # Alpha84 parity: the Solarbank may reduce Number.max after
            # a deep-discharge charge has already started. Never increase
            # an existing setpoint automatically; lower it with readback,
            # or stop safely if the live cap cannot be honored.
            if session and session["action"] == "laden":
                try:
                    live_limit = self.adapter._live_charge_power_decision(
                        int(session["planned_power_w"]))
                    if live_limit.applied_w < session["power_w"]:
                        # Serialize this nonzero correction against safe-stop.
                        # Master OFF revokes new writes before taking the lock.
                        async with self.adapter._lock:
                            if (not self._combined_authorized()
                                    or self.controller.session is None):
                                raise ValueError("Execution disarmed during charge-limit update")
                            applied = await self.adapter._write_charge_power(
                                int(session["planned_power_w"]))
                            if not self.adapter._power_matches(applied):
                                raise ValueError("Reduced charge setpoint not acknowledged")
                            self.controller.session["power_w"] = applied
                            session = dict(self.controller.session)
                except Exception:
                    self._last_stop_blockers = ["battery_charge_limit_invalid"]
                    try:
                        await self.controller.stop()
                        if same_plan:
                            await self.store.async_mark_lifecycle(
                                slot, "fout", "battery_charge_limit_invalid",
                                expected_plan=plan)
                        self._active_plan = None
                        self._active_slot = None
                        self._active_energy_sample = {}
                    except Exception:
                        self.controller.reconciliation_required = True
                    return
            soc = snapshot.get("soc_percent")
            try:
                soc = float(soc)
            except (TypeError, ValueError):
                soc = None
            try:
                outcome = await self.controller.monitor(
                    now=now, soc_percent=soc,
                    sources_fresh=self.scheduler._sources_fresh(now, snapshot),
                    controller_exclusive=self._authority,
                    command_acknowledged=bool(
                        session
                        and self.adapter._power_matches(session["power_w"])
                        and self.adapter._state("operating_mode") == "third_party_control"
                        and self.adapter._state("action_direction") ==
                            ("charge" if session["action"] == "laden" else "discharge")
                    ),
                    plan_identity_matches=same_plan,
                    safety_clear=bool(
                        same_plan and snapshot.get("status") == "ready"
                        and self._valid_battery_power(snapshot.get("charge_power_w"))
                        and self._valid_battery_power(snapshot.get("discharge_power_w"))
                        and (
                            (session["action"] == "laden"
                             and self._non_conflicting_power(snapshot.get("discharge_power_w")))
                            or
                            (session["action"] == "ontladen"
                             and self._non_conflicting_power(snapshot.get("charge_power_w")))
                        )
                    ),
                )
                if outcome.get("decision") == "stop":
                    blockers = list(outcome.get("blockers") or [])
                    self._last_stop_blockers = blockers
                    normal = bool(blockers) and all(
                        b in ("target_reached", "runtime_elapsed") for b in blockers
                    )
                    if same_plan:
                        await self.store.async_mark_lifecycle(
                            slot, "voltooid" if normal else "fout",
                            "execution_completed" if normal else "execution_safety_stopped",
                            expected_plan=plan)
                    self._active_plan = None
                    self._active_slot = None
                    self._active_energy_sample = {}
            except Exception:
                # Keep the controller reconciliation fence raised on uncertain stop.
                self.controller.reconciliation_required = True
            return

        decision = self.scheduler.last_result
        slot = decision.get("selected_slot")
        if type(slot) is not int or slot not in (1, 2, 3):
            return
        plan = self.store.get_plan(slot)
        identity = self._identity(slot, plan)
        if identity in self._started or not self._identity_current(identity):
            return
        power = plan.get("power_w")
        target = plan.get("target_soc")
        runtime = plan.get("max_runtime_h")
        if type(power) not in (int, float) or not 100 <= power <= 3500 or int(power) != power:
            return
        power = int(power)
        if type(target) not in (int, float) or not 5 <= target <= 100:
            return
        if type(runtime) not in (int, float) or not 0.25 <= runtime <= 12:
            return
        self._started.add(identity)
        try:
            await self.controller.start(
                identity=identity, action=plan["action"], power_w=power,
                target_soc=target, max_runtime_h=runtime, now=now)
            if await self.store.async_mark_lifecycle(
                slot, "actief", "r7_execution_started", expected_plan=plan):
                self._active_slot = slot
                self._active_plan = self.store.get_plan(slot)
                self._active_energy_sample = {}
            else:
                await self.controller.stop()
        except Exception:
            # Never retry an ambiguous start; the controller owns safe cleanup.
            if not self.controller.reconciliation_required:
                await self.store.async_mark_lifecycle(
                    slot, "fout", "execution_start_failed", expected_plan=plan)

    async def async_shutdown(self) -> None:
        self._master_enabled = False
        self._shutdown = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._task is not None:
            await self._task
        if self.controller.session is not None or self.controller.reconciliation_required:
            await self.controller.stop()
        self._listeners.clear()

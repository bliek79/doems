"""Step 12.5 non-actuating Execution Controller shadow.

Models the automatic execution lifecycle, runtime safety, safe-return and audit
without making Home Assistant service calls or claiming physical authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_POWER_TOLERANCE_W = 10.0
_PLANNED_ENERGY_TOLERANCE_KWH = 0.002
_RUN_HISTORY_LIMIT = 20
_TRACE_LIMIT = 40
_EXTERNAL_MODE = "third_party_control"
_SELF_MODE = "self_consumption"
_PERSISTENCE_SCHEMA_VERSION = 1


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


class DOEMSExecutionControllerShadow:
    """Stateful shadow of the future automatic Execution Controller."""

    def __init__(self) -> None:
        self._active = False
        self._status = "idle"
        self._reason = "Geen shadow-uitvoering actief"
        self._frozen: dict[str, Any] = {}
        self._started_at: datetime | None = None
        self._last_sample_at: datetime | None = None
        self._previous_actual_power_w: float | None = None
        self._sample_count = 0
        self._power_sum_w = 0.0
        self._actual_energy_wh = 0.0
        self._trace: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._handled_identities: list[str] = []
        self._run_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._last_summary: dict[str, Any] = {}
        self._safe_return: dict[str, Any] = self._safe_return_preview(False, None)
        self._recovery_pending = False
        self._recovery_status = "not_required"
        self._recovery_reason: str | None = None
        self._recovery_interrupted_run = False
        self._recovery_identity: str | None = None
        self._recovery_slot: int | str | None = None
        self._persistence_revision = 0

    @property
    def active(self) -> bool:
        return self._active

    @property
    def persistence_revision(self) -> int:
        """Monotonic revision for persisted shadow lifecycle state."""
        return self._persistence_revision

    def _mark_persistence_changed(self) -> None:
        self._persistence_revision += 1

    def export_persistence(self) -> dict[str, Any]:
        """Return the compact restart-safe Step 12.6 persistence payload."""
        return {
            "schema_version": _PERSISTENCE_SCHEMA_VERSION,
            "active": self._active,
            "status": self._status,
            "reason": self._reason,
            "frozen": dict(self._frozen),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "last_sample_at": self._last_sample_at.isoformat() if self._last_sample_at else None,
            "previous_actual_power_w": self._previous_actual_power_w,
            "sample_count": self._sample_count,
            "power_sum_w": self._power_sum_w,
            "actual_energy_wh": self._actual_energy_wh,
            "trace": list(self._trace[-_TRACE_LIMIT:]),
            "history": list(self._history[-_RUN_HISTORY_LIMIT:]),
            "handled_identities": list(self._handled_identities[-50:]),
            "run_count": self._run_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "last_summary": dict(self._last_summary),
            "safe_return": dict(self._safe_return),
            "recovery_status": self._recovery_status,
            "recovery_reason": self._recovery_reason,
            "recovery_interrupted_run": self._recovery_interrupted_run,
            "recovery_identity": self._recovery_identity,
            "recovery_slot": self._recovery_slot,
        }

    def restore_persistence(self, payload: Any) -> str:
        """Load persistent audit state without ever restoring an active run."""
        self._recovery_pending = False
        if payload is None:
            return "empty"
        if not isinstance(payload, dict):
            return "invalid_payload"
        if payload.get("schema_version") != _PERSISTENCE_SCHEMA_VERSION:
            return "invalid_schema"

        history = payload.get("history")
        handled = payload.get("handled_identities")
        trace = payload.get("trace")
        self._history = list(history)[-_RUN_HISTORY_LIMIT:] if isinstance(history, list) else []
        self._handled_identities = list(handled)[-50:] if isinstance(handled, list) else []
        self._trace = list(trace)[-_TRACE_LIMIT:] if isinstance(trace, list) else []
        self._last_summary = _mapping(payload.get("last_summary"))
        self._run_count = _nonnegative_int(payload.get("run_count"))
        self._success_count = _nonnegative_int(payload.get("success_count"))
        self._failure_count = _nonnegative_int(payload.get("failure_count"))
        persisted_safe_return = _mapping(payload.get("safe_return"))
        self._safe_return = (
            persisted_safe_return
            if persisted_safe_return
            else self._safe_return_preview(False, None)
        )
        self._recovery_status = str(payload.get("recovery_status") or "not_required")
        self._recovery_reason = payload.get("recovery_reason")
        self._recovery_interrupted_run = bool(payload.get("recovery_interrupted_run"))
        self._recovery_identity = payload.get("recovery_identity")
        self._recovery_slot = payload.get("recovery_slot")

        self._frozen = _mapping(payload.get("frozen"))
        self._started_at = _parse_time(payload.get("started_at"))
        self._last_sample_at = _parse_time(payload.get("last_sample_at"))
        self._previous_actual_power_w = _number(payload.get("previous_actual_power_w"))
        self._sample_count = _nonnegative_int(payload.get("sample_count"))
        self._power_sum_w = max(0.0, _number(payload.get("power_sum_w")) or 0.0)
        self._actual_energy_wh = max(0.0, _number(payload.get("actual_energy_wh")) or 0.0)
        self._persistence_revision = 0

        if payload.get("active") is True:
            self._active = False
            self._status = "restart_recovery_pending"
            self._reason = "Persisted active shadow-run requires fail-safe restart recovery"
            self._recovery_pending = True
            self._recovery_status = "pending"
            self._recovery_reason = "restart_recovery"
            self._recovery_interrupted_run = True
            self._recovery_identity = self._frozen.get("planner_identity")
            self._recovery_slot = self._frozen.get("slot")
            self._safe_return = self._safe_return_preview(True, "restart_recovery")
        else:
            self._active = False
            persisted_status = str(payload.get("status") or "idle")
            if persisted_status in {
                "idle",
                "blocked",
                "completed_shadow",
                "emergency_stopped_shadow",
                "recovered_interrupted_shadow",
            }:
                self._status = persisted_status
                self._reason = str(payload.get("reason") or self._reason)
            else:
                self._status = "idle"
                self._reason = "Persisted inactive shadow state normalized to idle"
        return "loaded"

    def _finish_restart_recovery(
        self, data: dict[str, Any], now: datetime
    ) -> None:
        """Fail-safe one persisted active shadow-run without physical recovery writes."""
        self._recovery_pending = False
        # Reuse the normal audit finalizer with the persisted frozen/sample state.
        # The temporary active flag is internal only; no public physical authority exists.
        self._active = True
        self._finish(data, now, "restart_recovery", emergency=True)
        self._status = "recovered_interrupted_shadow"
        self._reason = "restart_recovery"
        self._recovery_status = "recovered_interrupted"
        self._recovery_reason = "restart_recovery"
        self._recovery_interrupted_run = True
        self._recovery_identity = self._frozen.get("planner_identity")
        self._recovery_slot = self._frozen.get("slot")
        if self._last_summary:
            self._last_summary["result"] = "recovered_interrupted_shadow"
            self._last_summary["reason"] = "restart_recovery"
            if self._history:
                self._history[-1] = dict(self._last_summary)
        self._safe_return = self._safe_return_preview(True, "restart_recovery")
        self._mark_persistence_changed()

    def _trace_event(self, now: datetime, stage: str, detail: str | None = None) -> None:
        item: dict[str, Any] = {"time": now.isoformat(), "stage": stage}
        if detail:
            item["detail"] = str(detail)[:240]
        self._trace.append(item)
        self._trace = self._trace[-_TRACE_LIMIT:]

    @staticmethod
    def _safe_return_preview(required: bool, reason: str | None) -> dict[str, Any]:
        return {
            "required": required,
            "status": "preview_ready" if required else "not_required",
            "reason": reason,
            "steps": [
                {
                    "sequence": 1,
                    "operation": "set_power_zero",
                    "requested_value": 0,
                    "physical": False,
                },
                {
                    "sequence": 2,
                    "operation": "wait",
                    "seconds": 1,
                    "physical": False,
                },
                {
                    "sequence": 3,
                    "operation": "switch_self_consumption",
                    "requested_value": _SELF_MODE,
                    "physical": False,
                },
            ],
            "performed": False,
            "service_calls_performed": False,
            "physical_execution_authority": False,
        }

    def _transaction(self) -> list[dict[str, Any]]:
        action = self._frozen.get("action")
        return [
            {"sequence": 1, "operation": "freeze_execution_identity", "physical": False},
            {
                "sequence": 2,
                "operation": "zero_power_guard",
                "requested_value": 0,
                "physical": False,
            },
            {
                "sequence": 3,
                "operation": "switch_external_mode",
                "requested_value": _EXTERNAL_MODE,
                "required": bool(self._frozen.get("mode_switch_required")),
                "physical": False,
            },
            {
                "sequence": 4,
                "operation": "verify_external_controls",
                "required_stable_seconds": 60,
                "physical": False,
            },
            {
                "sequence": 5,
                "operation": "post_mode_final_revalidation",
                "expected": "safe",
                "physical": False,
            },
            {
                "sequence": 6,
                "operation": "set_direction",
                "requested_value": "charge" if action == "laden" else "discharge",
                "physical": False,
            },
            {
                "sequence": 7,
                "operation": "set_power",
                "requested_value": self._frozen.get("requested_power_w"),
                "physical": False,
            },
            {
                "sequence": 8,
                "operation": "mark_execution_running",
                "physical": False,
            },
            {
                "sequence": 9,
                "operation": "start_runtime_monitor",
                "interval_seconds": 5,
                "physical": False,
            },
        ]

    def _start(self, data: dict[str, Any], now: datetime) -> None:
        slot = data.get("auto_execution_gate_selected_slot")
        slots = data.get("scheduler_slots") or {}
        detail = slots.get(slot) or slots.get(str(slot)) or {}
        identity = data.get("auto_execution_gate_planner_identity")
        action = detail.get("action")
        planned_energy = _number(detail.get("planned_energy_kwh"))
        self._frozen = {
            "slot": slot,
            "planner_identity": identity,
            "planner_signature": detail.get("planner_signature"),
            "action": action,
            "purpose": detail.get("purpose"),
            "requested_power_w": _number(detail.get("power_w")),
            "target_soc": _number(detail.get("target_soc")),
            "max_runtime_h": _number(detail.get("max_runtime_h")),
            "planned_start_time": detail.get("start_time"),
            "planned_end_time": detail.get("planned_end_time"),
            "planned_energy_kwh": planned_energy,
            "start_soc": _number(data.get("soc")),
            "expected_mode": _EXTERNAL_MODE,
            "expected_direction": "charge" if action == "laden" else "discharge",
            "mode_switch_required": bool(data.get("auto_mode_switch_preview_switch_required")),
            "already_external": bool(data.get("auto_mode_switch_preview_already_external")),
        }
        self._active = True
        self._status = "running_shadow"
        self._reason = "Execution Controller shadow volgt de door Step 12.4 vrijgegeven actie"
        self._started_at = now
        self._last_sample_at = None
        self._previous_actual_power_w = None
        self._sample_count = 0
        self._power_sum_w = 0.0
        self._actual_energy_wh = 0.0
        self._trace = []
        self._safe_return = self._safe_return_preview(False, None)
        self._trace_event(now, "selected", f"slot={slot}; identity={identity}")
        self._trace_event(now, "armed_shadow", "Step 12.4 gate=armed_ready")
        self._trace_event(now, "starting_shadow", "transaction preview accepted")
        self._trace_event(
            now,
            "running_shadow",
            f"action={action}; requested={self._frozen.get('requested_power_w')}W",
        )
        self._mark_persistence_changed()

    def _sample_energy(self, data: dict[str, Any], now: datetime) -> float | None:
        action = self._frozen.get("action")
        actual_power = _number(
            data.get("charge_power_w") if action == "laden" else data.get("discharge_power_w")
        )
        if actual_power is None:
            return None
        if self._last_sample_at is not None and self._previous_actual_power_w is not None:
            elapsed_s = max(0.0, (now - self._last_sample_at).total_seconds())
            average_w = (self._previous_actual_power_w + actual_power) / 2.0
            self._actual_energy_wh += average_w * elapsed_s / 3600.0
        self._last_sample_at = now
        self._previous_actual_power_w = actual_power
        self._sample_count += 1
        self._power_sum_w += actual_power
        return actual_power

    def _runtime_checks(self, data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        checks: list[dict[str, Any]] = []
        blockers: list[str] = []
        warnings: list[str] = []

        def add(name: str, passed: bool, detail: str, blocker: str | None = None, warning: str | None = None) -> None:
            severity = "ok" if passed else ("warning" if warning else "blocker")
            checks.append({"check": name, "passed": bool(passed), "severity": severity, "detail": detail})
            if not passed:
                if warning:
                    warnings.append(warning)
                elif blocker:
                    blockers.append(blocker)

        identity = self._frozen.get("planner_identity")
        current_gate_identity = data.get("auto_execution_gate_planner_identity")
        identity_conflict = bool(
            identity
            and current_gate_identity
            and str(current_gate_identity) != str(identity)
        )
        add(
            "runtime_identity_stable",
            not identity_conflict,
            f"frozen={identity}; current_gate={current_gate_identity}",
            "runtime_identity_changed",
        )
        if identity and not current_gate_identity:
            warnings.append("planner_identity_no_longer_selected_runtime_frozen")

        already_external = bool(self._frozen.get("already_external"))
        mode = data.get("operating_mode")
        if already_external:
            add(
                "operating_mode_expected",
                mode == _EXTERNAL_MODE,
                f"expected={_EXTERNAL_MODE}; actual={mode}",
                "operating_mode_changed",
            )
            expected_direction = self._frozen.get("expected_direction")
            actual_direction = data.get("action_direction")
            add(
                "direction_expected",
                actual_direction == expected_direction,
                f"expected={expected_direction}; actual={actual_direction}",
                "direction_changed",
            )
            expected_power = _number(self._frozen.get("requested_power_w"))
            actual_setpoint = _number(data.get("power_setpoint_w"))
            add(
                "power_setpoint_available",
                actual_setpoint is not None,
                f"actual={actual_setpoint}",
                "power_setpoint_unavailable",
            )
            if actual_setpoint is not None and expected_power is not None:
                add(
                    "power_setpoint_expected",
                    abs(actual_setpoint - expected_power) <= _POWER_TOLERANCE_W,
                    f"expected={expected_power}; actual={actual_setpoint}; tolerance={_POWER_TOLERANCE_W}W",
                    "power_setpoint_changed",
                )
        else:
            add(
                "physical_post_handoff_state",
                False,
                "Mode-switch is preview-only; live post-handoff mode/direction/setpoint cannot be enforced yet",
                warning="physical_state_not_transitioned_shadow",
            )

        action = self._frozen.get("action")
        charge = _number(data.get("charge_power_w"))
        discharge = _number(data.get("discharge_power_w"))
        if action == "laden":
            add(
                "no_unexpected_discharge",
                discharge is not None and discharge <= 100,
                f"discharge={discharge}",
                "unexpected_discharge_detected",
            )
        elif action == "ontladen":
            add(
                "no_unexpected_charge",
                charge is not None and charge <= 100,
                f"charge={charge}",
                "unexpected_charge_detected",
            )

        add(
            "battery_power_sources_available",
            charge is not None and discharge is not None,
            f"charge={charge}; discharge={discharge}",
            "battery_power_source_unavailable",
        )
        soc = _number(data.get("soc"))
        add("soc_available", soc is not None, f"soc={soc}", "soc_unavailable")
        if soc is not None:
            add("soc_valid", 0 <= soc <= 100, f"soc={soc}", "invalid_soc")

        if "device_status" in data:
            add(
                "device_status_available",
                data.get("device_status") is not None,
                f"device_status={data.get('device_status')}",
                "device_status_unavailable",
            )
        else:
            warnings.append("device_status_source_not_configured")

        return checks, list(dict.fromkeys(blockers)), list(dict.fromkeys(warnings))

    def _normal_completion_reason(self, data: dict[str, Any], now: datetime) -> str | None:
        action = self._frozen.get("action")
        soc = _number(data.get("soc"))
        target = _number(self._frozen.get("target_soc"))
        if soc is not None and target is not None:
            if action == "laden" and soc >= target:
                return "target_soc_reached"
            if action == "ontladen":
                if soc <= 5:
                    return "minimum_soc_reached"
                if soc <= target:
                    return "target_soc_reached"

        planned_energy = _number(self._frozen.get("planned_energy_kwh"))
        actual_kwh = self._actual_energy_wh / 1000.0
        if (
            planned_energy is not None
            and planned_energy > 0
            and actual_kwh + _PLANNED_ENERGY_TOLERANCE_KWH >= planned_energy
        ):
            return "planned_energy_reached"

        planned_end = _parse_time(self._frozen.get("planned_end_time"))
        if planned_end is not None and now >= planned_end:
            return "planned_window_ended"

        runtime_h = _number(self._frozen.get("max_runtime_h"))
        if runtime_h is not None and self._started_at is not None:
            if now >= self._started_at + timedelta(hours=runtime_h):
                return "max_runtime_reached"
        return None

    def _finish(self, data: dict[str, Any], now: datetime, reason: str, *, emergency: bool) -> None:
        self._active = False
        self._status = "emergency_stopped_shadow" if emergency else "completed_shadow"
        self._reason = reason
        self._safe_return = self._safe_return_preview(True, reason)
        self._trace_event(now, "stop_requested", f"reason={reason}; emergency={emergency}")
        self._trace_event(now, "safe_return_preview", "0W -> wait 1s -> self_consumption")
        self._trace_event(now, "finished", self._status)

        identity = str(self._frozen.get("planner_identity") or "")
        if identity:
            self._handled_identities.append(identity)
            self._handled_identities = self._handled_identities[-50:]

        started = self._started_at
        duration_s = max(0, int((now - started).total_seconds())) if started else None
        actual_energy_kwh = (
            round(self._actual_energy_wh / 1000.0, 3) if self._sample_count > 1 else None
        )
        energy_source = "power_samples" if actual_energy_kwh is not None else "unavailable"
        start_soc = _number(self._frozen.get("start_soc"))
        end_soc = _number(data.get("soc"))
        soc_delta = (
            round(end_soc - start_soc, 2)
            if start_soc is not None and end_soc is not None
            else None
        )
        planned_energy = _number(self._frozen.get("planned_energy_kwh"))
        energy_delta = (
            round(actual_energy_kwh - planned_energy, 3)
            if actual_energy_kwh is not None and planned_energy is not None
            else None
        )
        planned_start = _parse_time(self._frozen.get("planned_start_time"))
        planned_end = _parse_time(self._frozen.get("planned_end_time"))
        planned_duration_s = (
            max(0, int((planned_end - planned_start).total_seconds()))
            if planned_start and planned_end
            else None
        )
        duration_delta = (
            duration_s - planned_duration_s
            if duration_s is not None and planned_duration_s is not None
            else None
        )
        target = _number(self._frozen.get("target_soc"))
        target_error = (
            round(end_soc - target, 2)
            if end_soc is not None and target is not None
            else None
        )
        avg_power = (
            round(self._power_sum_w / self._sample_count, 1)
            if self._sample_count
            else None
        )
        summary = {
            "identity": self._frozen.get("planner_identity"),
            "slot": self._frozen.get("slot"),
            "action": self._frozen.get("action"),
            "purpose": self._frozen.get("purpose"),
            "requested_power_w": self._frozen.get("requested_power_w"),
            "average_actual_power_w": avg_power,
            "planned_start_time": self._frozen.get("planned_start_time"),
            "planned_end_time": self._frozen.get("planned_end_time"),
            "planned_duration_s": planned_duration_s,
            "planned_energy_kwh": planned_energy,
            "actual_started_at": started.isoformat() if started else None,
            "actual_finished_at": now.isoformat(),
            "actual_duration_s": duration_s,
            "duration_delta_s": duration_delta,
            "actual_energy_kwh": actual_energy_kwh,
            "actual_energy_source": energy_source,
            "power_sample_count": self._sample_count,
            "energy_delta_kwh": energy_delta,
            "target_soc": target,
            "start_soc": start_soc,
            "end_soc": end_soc,
            "soc_delta": soc_delta,
            "target_error_soc": target_error,
            "result": self._status,
            "reason": reason,
        }
        self._last_summary = summary
        self._history.append(summary)
        self._history = self._history[-_RUN_HISTORY_LIMIT:]
        self._run_count += 1
        if emergency:
            self._failure_count += 1
        else:
            self._success_count += 1
        self._mark_persistence_changed()

    def evaluate(self, data: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        """Advance one read-only execution-shadow iteration."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        if self._recovery_pending:
            self._finish_restart_recovery(data, current)

        gate_permitted = data.get("auto_execution_gate_execution_permitted") is True
        gate_status = data.get("auto_execution_gate_status")
        armed = data.get("auto_execution_gate_armed") is True
        identity = data.get("auto_execution_gate_planner_identity")

        if self._active and not armed:
            self._finish(data, current, "automatic_execution_disarmed", emergency=False)

        if self._active:
            actual_power = self._sample_energy(data, current)
            checks, blockers, warnings = self._runtime_checks(data)
            if blockers:
                self._finish(data, current, blockers[0], emergency=True)
            else:
                completion = self._normal_completion_reason(data, current)
                if completion:
                    self._finish(data, current, completion, emergency=False)
        else:
            checks = []
            blockers = []
            warnings = []
            actual_power = None
            if (
                gate_permitted
                and gate_status == "armed_ready"
                and identity
                and str(identity) not in self._handled_identities
            ):
                self._status = "armed_shadow"
                self._reason = "Step 12.4 heeft één automatic execution vrijgegeven"
                self._start(data, current)
                actual_power = self._sample_energy(data, current)
                checks, blockers, warnings = self._runtime_checks(data)
                if blockers:
                    self._finish(data, current, blockers[0], emergency=True)
            elif gate_status == "blocked":
                self._status = "blocked"
                self._reason = "Step 12.4 gate is blocked"
            elif self._status not in {
                "completed_shadow",
                "emergency_stopped_shadow",
                "recovered_interrupted_shadow",
            }:
                self._status = "idle"
                self._reason = "Geen nieuwe armed_ready execution identity"

        frozen = dict(self._frozen)
        actual_energy_kwh = round(self._actual_energy_wh / 1000.0, 4)
        planned_energy = _number(frozen.get("planned_energy_kwh"))
        remaining_energy = (
            round(max(0.0, planned_energy - actual_energy_kwh), 4)
            if planned_energy is not None
            else None
        )
        avg_power = (
            round(self._power_sum_w / self._sample_count, 1)
            if self._sample_count
            else None
        )
        runtime_safe = bool(self._active and not blockers)
        return {
            "execution_shadow_enabled": True,
            "execution_shadow_status": self._status,
            "execution_shadow_active": self._active,
            "execution_shadow_reason": self._reason,
            "execution_shadow_persistence_schema_version": _PERSISTENCE_SCHEMA_VERSION,
            "execution_shadow_recovery_status": self._recovery_status,
            "execution_shadow_recovery_reason": self._recovery_reason,
            "execution_shadow_recovery_interrupted_run": self._recovery_interrupted_run,
            "execution_shadow_recovery_identity": self._recovery_identity,
            "execution_shadow_recovery_slot": self._recovery_slot,
            "execution_shadow_identity": frozen.get("planner_identity"),
            "execution_shadow_slot": frozen.get("slot"),
            "execution_shadow_action": frozen.get("action"),
            "execution_shadow_purpose": frozen.get("purpose"),
            "execution_shadow_requested_power_w": frozen.get("requested_power_w"),
            "execution_shadow_target_soc": frozen.get("target_soc"),
            "execution_shadow_max_runtime_h": frozen.get("max_runtime_h"),
            "execution_shadow_planned_start_time": frozen.get("planned_start_time"),
            "execution_shadow_planned_end_time": frozen.get("planned_end_time"),
            "execution_shadow_planned_energy_kwh": planned_energy,
            "execution_shadow_start_soc": frozen.get("start_soc"),
            "execution_shadow_expected_mode": frozen.get("expected_mode"),
            "execution_shadow_expected_direction": frozen.get("expected_direction"),
            "execution_shadow_transaction": self._transaction() if frozen else [],
            "runtime_safety_safe": runtime_safe,
            "runtime_safety_reason": "running_safe" if runtime_safe else self._reason,
            "runtime_safety_blockers": blockers,
            "runtime_safety_warnings": warnings,
            "runtime_safety_checks": checks,
            "runtime_current_soc": _number(data.get("soc")),
            "runtime_actual_power_w": actual_power,
            "runtime_average_actual_power_w": avg_power,
            "runtime_sample_count": self._sample_count,
            "runtime_actual_energy_kwh": actual_energy_kwh,
            "runtime_actual_energy_source": "power_samples" if self._sample_count > 1 else "unavailable",
            "runtime_remaining_energy_kwh": remaining_energy,
            "safe_return_required": self._safe_return.get("required", False),
            "safe_return_status": self._safe_return.get("status"),
            "safe_return_reason": self._safe_return.get("reason"),
            "safe_return_steps": self._safe_return.get("steps", []),
            "safe_return_performed": False,
            "automatic_run_count": self._run_count,
            "automatic_success_count": self._success_count,
            "automatic_failure_count": self._failure_count,
            "automatic_last_run": dict(self._last_summary),
            "execution_shadow_trace": list(self._trace),
            "execution_shadow_run_history": list(self._history),
            "execution_controller_invoked": False,
            "mode_switch_performed": False,
            "direction_written": False,
            "power_setpoint_written": False,
            "safe_return_performed": False,
            "service_calls_performed": False,
            "physical_execution_authority": False,
        }

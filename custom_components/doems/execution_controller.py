"""R8 execution controller. No implicit grant of physical authority."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from homeassistant.exceptions import HomeAssistantError
from .execution_watchdog import evaluate_session
from .execution_status_reset import check_execution_status_reset


class ExecutionController:
    def __init__(self, adapter, *, authorized, revalidate):
        self.adapter = adapter
        self.authorized = authorized
        self.revalidate = revalidate
        self.session = None
        self.reconciliation_required = False
        self._lock = asyncio.Lock()
        self.emergency_status = {'active': False, 'status': 'idle', 'reason': None, 'stop_at': None, 'last_result': None, 'automatic_run_history': []}

    def _permitted(self, identity):
        return bool(self.authorized() and self.revalidate(identity))

    async def start(self, *, identity, action, power_w, target_soc, max_runtime_h, now):
        async with self._lock:
            if self.session is not None or self.reconciliation_required:
                raise HomeAssistantError("Existing or unreconciled session")
            if not self._permitted(identity):
                raise HomeAssistantError("Execution authority or plan validation missing")
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise HomeAssistantError("Invalid start timestamp")
            self.reconciliation_required = True
            try:
                acknowledged = await self.adapter.start(
                    action=action, power_w=power_w,
                    revalidate=lambda: self._permitted(identity))
                if acknowledged is not True:
                    raise HomeAssistantError("Start acknowledgement not confirmed")
                if not self._permitted(identity):
                    raise HomeAssistantError("Authority or selected plan changed during start")
                applied_w = getattr(self.adapter, "_last_commanded_setpoint", None)
                if action == "laden" and hasattr(self.adapter, "_last_commanded_setpoint"):
                    if type(applied_w) is not int or not 100 <= applied_w <= power_w:
                        raise HomeAssistantError("Invalid applied charge power")
                else:
                    applied_w = power_w
            except BaseException:
                # A failed or cancelled start may already have reached the device.
                # Keep the reconciliation fence raised until a separate verified stop.
                # Await cleanup to completion even if the start task is cancelled.
                cleanup = asyncio.create_task(self.adapter.stop())
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    try:
                        await cleanup
                    except BaseException:
                        pass
                except BaseException:
                    pass
                self.emergency_status.update(status='emergency_stopped', reason='execution_start_failed', last_result='emergency_stopped')
                raise
            self.session = dict(identity=identity, action=action, power_w=applied_w,
                                planned_power_w=power_w,
                                target_soc=target_soc, max_runtime_h=max_runtime_h,
                                started_at=now.astimezone(timezone.utc).isoformat())
            self.reconciliation_required = False
            return dict(self.session)

    async def stop(self):
        async with self._lock:
            if self.session is None and not self.reconciliation_required:
                return True
            self.reconciliation_required = True
            stopped = await self.adapter.stop()
            if stopped is not True:
                raise HomeAssistantError("Device stop not confirmed")
            self.session = None
            self.reconciliation_required = False
            return True

    async def monitor(self, *, now, soc_percent, sources_fresh,
                      controller_exclusive, command_acknowledged,
                      plan_identity_matches, safety_clear):
        if self.reconciliation_required:
            await self.stop()
            return {"decision": "stop", "blockers": ["reconciliation_required"]}
        if self.session is None:
            return {"decision": "idle", "blockers": []}
        session = dict(self.session)
        result = evaluate_session(
            now=now, started_at=session["started_at"], action=session["action"],
            target_soc=session["target_soc"], max_runtime_h=session["max_runtime_h"],
            soc_percent=soc_percent, sources_fresh=sources_fresh,
            controller_exclusive=controller_exclusive and self.authorized(),
            command_acknowledged=command_acknowledged,
            plan_identity_matches=plan_identity_matches and self.revalidate(session["identity"]),
            safety_clear=safety_clear)
        if result["decision"] == "stop":
            await self.stop()
        return result

    async def async_reset_emergency_status(self, *, automatic_armed=False, physical_test=None):
        """Non-actuating Alpha82 emergency acknowledgement; retain historical audit."""
        async with self._lock:
            if self.session is not None or self.reconciliation_required:
                raise HomeAssistantError("Noodstopreset geblokkeerd: uitvoering of reconciliatie actief")
            blocker = check_execution_status_reset(
                {**self.emergency_status, "active": False, "auto_mode_switch_active": False},
                physical_test if physical_test is not None else {"active": False},
                automatic_armed=automatic_armed,
                operating_mode=self.adapter._state("operating_mode"),
                power_state=self.adapter._state("power_setpoint"),
            )
            if blocker is not None:
                raise HomeAssistantError(f"Noodstopreset geblokkeerd: {blocker}")
            self.emergency_status.update(
                emergency_acknowledged_at=datetime.now(timezone.utc).isoformat(),
                emergency_acknowledged_reason=self.emergency_status.get("reason"),
                emergency_acknowledged_stop_at=self.emergency_status.get("stop_at"),
                active=False, status="idle",
                reason="Noodstop bevestigd; geen EMS-uitvoering actief",
                stop_at=None,
            )

    def require_restart_reconciliation(self):
        self.session = None
        self.reconciliation_required = True

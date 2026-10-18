"""Fail-closed Anker Solarbank command adapter.

Not wired into the supervisor: battery actuation remains separately gated.
The adapter encapsulates the historical three-entity control sequence and
cannot be used without explicit configured authority.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .execution_control_path import EXTERNAL_MODE, SELF_MODE, observe_control_path


class AnkerExecutionAdapter:
    def __init__(self, hass: Any, entities: Mapping[str, str], *, authority: bool = False) -> None:
        self.hass = hass
        self.entities = dict(entities)
        self.authority = authority
        self._lock = asyncio.Lock()

    def _require_authority(self) -> None:
        if not self.authority:
            raise HomeAssistantError("Physical battery control not authorized")

    def _state(self, key: str) -> str | None:
        entity_id = self.entities.get(key)
        state = self.hass.states.get(entity_id) if entity_id else None
        return None if state is None or state.state in ("unknown", "unavailable") else state.state

    async def _call(self, domain: str, service: str, entity: str, data: dict[str, Any]) -> None:
        self._require_authority()
        entity_id = self.entities.get(entity)
        if not entity_id or not entity_id.startswith(domain + "."):
            raise HomeAssistantError(f"Invalid {entity} control entity")
        await self.hass.services.async_call(domain, service, data, target={"entity_id": entity_id}, blocking=True)

    async def _wait(self, predicate: Callable[[], bool], timeout: int = 45) -> None:
        deadline = dt_util.utcnow() + timedelta(seconds=timeout)
        while dt_util.utcnow() < deadline:
            if predicate():
                return
            await asyncio.sleep(1)
        raise HomeAssistantError("Battery control acknowledgement timeout")

    async def safe_return(self) -> bool:
        """Attempt 0 W then self-consumption, verify both; never mask failure."""
        self._require_authority()
        async with self._lock:
            errors: list[str] = []
            if self._state("power_setpoint") is not None:
                try:
                    await self._call("number", "set_value", "power_setpoint", {"value": 0})
                    await self._wait(lambda: self._power_zero(), timeout=15)
                except Exception as err:
                    errors.append(f"zero_setpoint: {err}")
            try:
                await self._call("select", "select_option", "operating_mode", {"option": SELF_MODE})
                await self._wait(lambda: self._state("operating_mode") == SELF_MODE)
            except Exception as err:
                errors.append(f"self_consumption: {err}")
            if errors:
                raise HomeAssistantError("; ".join(errors))
            return self._state("operating_mode") == SELF_MODE

    def _power_zero(self) -> bool:
        try:
            return abs(float(self._state("power_setpoint"))) <= 1
        except (ValueError, TypeError):
            return False

    async def start(self, *, action: str, power_w: int, revalidate: Callable[[], bool]) -> bool:
        """Two-stage mode switch, zero guard, 60s stable controls, final gate."""
        self._require_authority()
        if action not in ("laden", "ontladen") or type(power_w) is not int or not 100 <= power_w <= 3500:
            raise HomeAssistantError("Invalid action or setpoint")
        if not revalidate():
            raise HomeAssistantError("Final revalidation failed before mode switch")
        async with self._lock:
            try:
                if self._state("power_setpoint") is not None:
                    await self._call("number", "set_value", "power_setpoint", {"value": 0})
                await self._call("select", "select_option", "operating_mode", {"option": EXTERNAL_MODE})
                await self._wait(lambda: self._state("operating_mode") == EXTERNAL_MODE)
                await self._wait(lambda: self._state("power_setpoint") is not None and
                                 self._state("action_direction") is not None)
                await self._call("number", "set_value", "power_setpoint", {"value": 0})
                await self._wait(self._power_zero, timeout=15)
                await self._wait(lambda: observe_control_path(
                    self.hass, self.entities, dt_util.utcnow()).get("post_mode_ready") is True, timeout=150)
                if not revalidate():
                    raise HomeAssistantError("Final revalidation failed after mode switch")
                await self._call("select", "select_option", "action_direction",
                                 {"option": "charge" if action == "laden" else "discharge"})
                await self._wait(lambda: self._state("action_direction") ==
                                 ("charge" if action == "laden" else "discharge"))
                if not revalidate():
                    raise HomeAssistantError("Final revalidation failed before nonzero setpoint")
                await self._call("number", "set_value", "power_setpoint", {"value": power_w})
                await self._wait(lambda: self._state("power_setpoint") is not None and
                                 abs(float(self._state("power_setpoint")) - power_w) <= 1)
                return True
            except BaseException:
                # Always attempt safe return on failures, including cancellation.
                try:
                    if self._state("power_setpoint") is not None:
                        await self._call("number", "set_value", "power_setpoint", {"value": 0})
                    await self._call("select", "select_option", "operating_mode", {"option": SELF_MODE})
                finally:
                    raise

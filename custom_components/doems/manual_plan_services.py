"""Manual Plan Store services for DOEMS R2."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .manual_plan_store import DOEMSManualPlanStore

SERVICE_SCHEDULE_PLAN = "schedule_plan"
SERVICE_CANCEL_PLAN = "cancel_plan"
SERVICE_CLEAR_PLAN = "clear_plan"

_SLOT_SCHEMA = vol.All(vol.Coerce(int), vol.Range(min=1, max=3))


async def async_register_manual_plan_services(
    hass: HomeAssistant,
    store: DOEMSManualPlanStore,
) -> None:
    """Register manual-only Plan Store services."""

    async def _schedule(call: ServiceCall) -> None:
        slot = int(call.data["slot"])
        try:
            await store.async_schedule(slot)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def _cancel(call: ServiceCall) -> None:
        slot = int(call.data["slot"])
        try:
            await store.async_cancel(slot)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def _clear(call: ServiceCall) -> None:
        slot = int(call.data["slot"])
        try:
            await store.async_clear(slot)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    for service, handler in (
        (SERVICE_SCHEDULE_PLAN, _schedule),
        (SERVICE_CANCEL_PLAN, _cancel),
        (SERVICE_CLEAR_PLAN, _clear),
    ):
        if hass.services.has_service("doems", service):
            hass.services.async_remove("doems", service)
        hass.services.async_register(
            "doems",
            service,
            handler,
            schema=vol.Schema({vol.Required("slot"): _SLOT_SCHEMA}),
        )


async def async_unregister_manual_plan_services(hass: HomeAssistant) -> None:
    """Remove R2 manual Plan Store services."""
    for service in (
        SERVICE_SCHEDULE_PLAN,
        SERVICE_CANCEL_PLAN,
        SERVICE_CLEAR_PLAN,
    ):
        if hass.services.has_service("doems", service):
            hass.services.async_remove("doems", service)

"""Manual persistent lifecycle services, deliberately without device dispatch."""
import voluptuous as vol
from .const import DOMAIN

SCHEMA = vol.Schema({vol.Required('config_entry_id'): str, vol.Required('slot'): vol.In([1, 2, 3])})


def register_plan_store_services(hass):
    for service, method in (('plan_store_schedule', 'async_schedule_manual_plan'),
                            ('plan_store_cancel', 'async_cancel_plan')):
        if hass.services.has_service(DOMAIN, service):
            continue
        async def handle(call, method=method):
            data = hass.data.get(DOMAIN, {}).get(call.data['config_entry_id'])
            if not data or data.get('plan_store') is None:
                raise ValueError('plan_store_entry_unavailable')
            await getattr(data['plan_store'], method)(call.data['slot'])
        hass.services.async_register(DOMAIN, service, handle, schema=SCHEMA)

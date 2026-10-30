"""Persistent slot start-time editors."""
from .const import DOMAIN
from .plan_slot_entities import SlotStart

async def async_setup_entry(hass, entry, async_add_entities):
    store = hass.data[DOMAIN][entry.entry_id]['plan_store']
    async_add_entities([SlotStart(entry, store, slot, 'start_time') for slot in range(1, 4)])

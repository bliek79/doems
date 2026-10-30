"""Persistent slot numeric editors."""
from .const import DOMAIN
from .plan_slot_entities import NUMBERS, SlotNumber

async def async_setup_entry(hass, entry, async_add_entities):
    store = hass.data[DOMAIN][entry.entry_id]['plan_store']
    async_add_entities([SlotNumber(entry, store, slot, field)
                        for slot in range(1, 4) for field in NUMBERS])

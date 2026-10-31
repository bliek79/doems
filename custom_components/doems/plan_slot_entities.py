"""Chapter 7 slot editor contract. No entity can dispatch a battery command."""
from datetime import datetime
from math import isfinite

from homeassistant.const import EntityCategory
from homeassistant.components.datetime import DateTimeEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import DOMAIN, DEVICE_IDENTIFIER, NAME

SELECTS = {'action': ['geen', 'laden', 'ontladen'], 'execution_mode': ['direct', 'gepland']}
NUMBERS = {
    'power_w': (100, 3500, 100, 'W'),
    'target_soc': (5, 100, 1, '%'),
    'max_runtime_h': (.25, 12, .25, 'h'),
    'max_start_delay_min': (1, 120, 1, 'min'),
}
DIAGNOSTICS = ('status', 'revision', 'reason', 'generation', 'fingerprint', 'overflow')


def entity_register(entry_id):
    rows = []
    for slot in range(1, 4):
        for domain, fields in (('select', SELECTS), ('number', NUMBERS),
                               ('datetime', ('start_time',)), ('sensor', ('status',))):
            for field in fields:
                rows.append((f'{domain}.doems_slot_{slot}_{field}', f'{entry_id}_slot_{slot}_{field}'))
    rows.extend((f'sensor.doems_plan_store_{field}', f'{entry_id}_plan_store_{field}')
                for field in DIAGNOSTICS)
    return tuple(rows)


class SlotEntity:
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, entry, store, slot, field):
        self.store, self.slot, self.field = store, slot, field
        self._attr_unique_id = f'{entry.entry_id}_slot_{slot}_{field}'
        self._attr_suggested_object_id = f'doems_slot_{slot}_{field}'
        self._attr_name = f'DOEMS Slot {slot} {field.replace("_", " ")}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, DEVICE_IDENTIFIER)}, name=NAME)
        self._remove_listener = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = self.store.add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self):
        plan = self.store.get_plan(self.slot)
        return {**plan, 'storage_revision': self.store.revision,
                'physical_execution_authority': False, 'execution_enabled': False}


class SlotSelect(SlotEntity, SelectEntity):
    def __init__(self, entry, store, slot, field):
        super().__init__(entry, store, slot, field)
        self._attr_options = SELECTS[field]

    @property
    def current_option(self):
        return self.store.get_value(self.slot, self.field)

    async def async_select_option(self, option):
        if option not in self._attr_options:
            raise ValueError('invalid_slot_option')
        await self.store.async_set_value(self.slot, self.field, option)


class SlotNumber(SlotEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, entry, store, slot, field):
        super().__init__(entry, store, slot, field)
        (self._attr_native_min_value, self._attr_native_max_value,
         self._attr_native_step, self._attr_native_unit_of_measurement) = NUMBERS[field]

    @property
    def native_value(self):
        return self.store.get_value(self.slot, self.field)

    async def async_set_native_value(self, value):
        if not isfinite(value) or not self._attr_native_min_value <= value <= self._attr_native_max_value:
            raise ValueError('invalid_slot_number')
        await self.store.async_set_value(self.slot, self.field, value)


class SlotStart(SlotEntity, DateTimeEntity):
    @property
    def native_value(self):
        raw = self.store.get_value(self.slot, self.field)
        return dt_util.parse_datetime(raw) if raw else None

    async def async_set_value(self, value: datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('timezone_required')
        await self.store.async_set_value(self.slot, self.field, value)


class SlotStatus(SlotEntity, SensorEntity):
    @property
    def native_value(self):
        return self.store.plan_status(self.slot)


class StoreDiagnostic(SlotEntity, SensorEntity):
    def __init__(self, entry, store, writer, field):
        super().__init__(entry, store, 1, field)
        self.writer = writer
        self._attr_unique_id = f'{entry.entry_id}_plan_store_{field}'
        self._attr_suggested_object_id = f'doems_plan_store_{field}'
        self._attr_name = f'DOEMS Plan Store {field}'
        self._attr_should_poll = True
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        if self.field == 'revision': return self.store.revision
        if self.writer is None: return 'disabled' if self.field == 'status' else None
        if self.field == 'status': return self.writer.status
        if self.field == 'reason': return self.writer.last_reason
        return self.writer.diagnostics.get(self.field)

    @property
    def extra_state_attributes(self):
        return {'physical_execution_authority': False, 'execution_enabled': False,
                'storage_revision': self.store.revision}

"""One-time planner identity and option migration for DOEMS."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_OPTION_MIGRATIONS = {
    "r5_1_software_reserve_percent": "planner_software_reserve_percent",
    "r5_1_max_charge_power_w": "planner_max_charge_power_w",
    "r5_1_max_discharge_power_w": "planner_max_discharge_power_w",
    "r5_1_minimum_trade_margin_eur_per_kwh": (
        "planner_minimum_trade_margin_eur_per_kwh"
    ),
}

_ENTITY_MIGRATIONS = (
    (
        "doems_manual_soc_projection",
        "doems_manual_planner",
        "sensor.doems_manual_planner",
    ),
    (
        "doems_r5_1_automatic_base_preview",
        "doems_automatic_planner",
        "sensor.doems_automatic_planner",
    ),
    (
        "doems_r5_1_automatic_base_soc_timeline",
        "doems_automatic_soc_projection_timeline",
        "sensor.doems_automatic_soc_projection_timeline",
    ),
    (
        "doems_r5_1_combined_preview",
        "doems_combined_planner",
        "sensor.doems_combined_planner",
    ),
    (
        "doems_r5_1_combined_soc_timeline",
        "doems_combined_soc_projection_timeline",
        "sensor.doems_combined_soc_projection_timeline",
    ),
)

_RETIRED_UNIQUE_IDS = (
    "doems_ems_plan72_hours",
)


def _migrate_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    options = dict(entry.options)
    changed = False
    for old_key, new_key in _OPTION_MIGRATIONS.items():
        if new_key not in options and old_key in options:
            options[new_key] = options[old_key]
            changed = True
        if old_key in options:
            options.pop(old_key, None)
            changed = True
    if changed:
        hass.config_entries.async_update_entry(entry, options=options)


def _migrate_entity(
    registry: er.EntityRegistry,
    *,
    old_unique_id: str,
    new_unique_id: str,
    new_entity_id: str,
) -> None:
    old_entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, old_unique_id
    )
    if old_entity_id is None:
        return

    target_unique_entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, new_unique_id
    )
    if (
        target_unique_entity_id is not None
        and target_unique_entity_id != old_entity_id
    ):
        raise RuntimeError(
            "DOEMS planner identity migration collision for "
            f"{new_unique_id}: {target_unique_entity_id}"
        )

    target_entity = registry.async_get(new_entity_id)
    if (
        target_entity is not None
        and target_entity.entity_id != old_entity_id
    ):
        raise RuntimeError(
            "DOEMS planner entity-id migration collision for "
            f"{new_entity_id}"
        )

    registry.async_update_entity(
        old_entity_id,
        new_unique_id=new_unique_id,
        new_entity_id=new_entity_id,
    )
    _LOGGER.info(
        "Migrated DOEMS planner entity %s to %s",
        old_entity_id,
        new_entity_id,
    )


def _retire_entity(
    registry: er.EntityRegistry,
    *,
    unique_id: str,
) -> None:
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, unique_id
    )
    if entity_id is None:
        return
    registry.async_remove(entity_id)
    _LOGGER.info("Retired legacy DOEMS planner entity %s", entity_id)


async def async_migrate_planner_architecture(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Migrate alpha.7 planner identities to the permanent architecture."""
    _migrate_options(hass, entry)
    registry = er.async_get(hass)
    for old_unique_id, new_unique_id, new_entity_id in _ENTITY_MIGRATIONS:
        _migrate_entity(
            registry,
            old_unique_id=old_unique_id,
            new_unique_id=new_unique_id,
            new_entity_id=new_entity_id,
        )
    for unique_id in _RETIRED_UNIQUE_IDS:
        _retire_entity(registry, unique_id=unique_id)

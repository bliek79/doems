"""Constants for DOEMS."""

from __future__ import annotations

DOMAIN = "doems"
NAME = "DOEMS"
VERSION = "0.1.0-alpha.7"

CONF_INSTANCE_NAME = "instance_name"
DEFAULT_INSTANCE_NAME = NAME

CONF_ENERGY_FORECAST_ENABLED = "energy_forecast_enabled"
CONF_ENERGY_SOURCE_MODE = "energy_source_mode"
CONF_ENERGY_START_PROFILE = "energy_start_profile"
CONF_HOME_POWER_ENTITY = "home_power_entity"
CONF_GRID_NET_POWER_ENTITY = "grid_net_power_entity"
CONF_GRID_SIGN_CONVENTION = "grid_sign_convention"
CONF_SOLAR_POWER_ENTITY = "solar_power_entity"
CONF_BATTERY_PRESENT = "battery_present"
CONF_BATTERY_CHARGE_POWER_ENTITY = "battery_charge_power_entity"
CONF_BATTERY_DISCHARGE_POWER_ENTITY = "battery_discharge_power_entity"

ENERGY_SOURCE_DIRECT = "direct_home_power"
ENERGY_SOURCE_BALANCE = "power_balance"
ENERGY_SOURCE_MODES = [ENERGY_SOURCE_DIRECT, ENERGY_SOURCE_BALANCE]

GRID_SIGN_POSITIVE_IMPORT = "positive_import_negative_export"
GRID_SIGN_POSITIVE_EXPORT = "positive_export_negative_import"
GRID_SIGN_OPTIONS = [GRID_SIGN_POSITIVE_IMPORT, GRID_SIGN_POSITIVE_EXPORT]

PROFILE_CONTRACT_VERSION = 1
PROFILE_NORMAL = "normal"
PROFILE_AWAY = "away"
PROFILE_UNCLASSIFIED = "unclassified"
PROFILE_MIXED = "mixed"
PROFILE_LEARNING_OPTIONS = [PROFILE_NORMAL, PROFILE_AWAY]
PROFILE_OPTIONS = [PROFILE_NORMAL, PROFILE_AWAY, PROFILE_UNCLASSIFIED]

# Solar P3 Foundation/install contract.
CONF_SOLAR_FOUNDATION_ENABLED = "solar_foundation_enabled"
CONF_SOLAR_LOCATION_SOURCE = "solar_location_source"
CONF_SOLAR_LATITUDE = "solar_latitude"
CONF_SOLAR_LONGITUDE = "solar_longitude"
CONF_SOLAR_INVERTER_GROUP_COUNT = "solar_inverter_group_count"
CONF_SOLAR_ARRAY_COUNT = "solar_array_count"
CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY = "solar_total_actual_power_entity"
CONF_SOLAR_INVERTER_GROUPS = "solar_inverter_groups"
CONF_SOLAR_ARRAYS = "solar_arrays"
SOLAR_LOCATION_HOME_ASSISTANT = "home_assistant"
SOLAR_LOCATION_OVERRIDE = "override"
SOLAR_PROVIDER = "open_meteo"
SOLAR_FOUNDATION_SCHEMA_VERSION = 1
SOLAR_FOUNDATION_STORAGE_VERSION = 1
SOLAR_FOUNDATION_STORAGE_KEY = f"{DOMAIN}.solar_foundation"
SOLAR_MAX_INVERTER_GROUPS = 8
SOLAR_MAX_ARRAYS = 32

# Prices P4 install/runtime contract.
CONF_PRICES_ENABLED = "prices_enabled"
CONF_PRICES_RESOLUTION_PREFERENCE = "prices_resolution_preference"
PRICES_RESOLUTION_AUTO = "auto"
PRICES_RESOLUTION_15_MIN = "15_min"
PRICES_RESOLUTION_60_MIN = "60_min"
PRICES_RESOLUTION_OPTIONS = [
    PRICES_RESOLUTION_AUTO,
    PRICES_RESOLUTION_15_MIN,
    PRICES_RESOLUTION_60_MIN,
]
CONF_TARIFF_PROFILE_ID = "tariff_profile_id"
CONF_TARIFF_SUPPLIER = "tariff_supplier"
CONF_TARIFF_VALID_FROM = "tariff_valid_from"
CONF_VAT_PERCENT = "vat_percent"
CONF_ELECTRICITY_IMPORT_SUPPLIER = "electricity_import_supplier_incl_vat"
CONF_ELECTRICITY_IMPORT_TAX = "electricity_import_tax_incl_vat"
CONF_ELECTRICITY_EXPORT_SUPPLIER = "electricity_export_supplier_incl_vat"
CONF_ELECTRICITY_EXPORT_TAX = "electricity_export_tax_incl_vat"
CONF_ELECTRICITY_FIXED_SUPPLY_PER_DAY = "electricity_fixed_supply_per_day"
CONF_ELECTRICITY_GRID_PER_DAY = "electricity_grid_per_day"
CONF_ELECTRICITY_TAX_CREDIT_PER_DAY = "electricity_tax_credit_per_day"
CONF_GAS_PRICES_ENABLED = "gas_prices_enabled"
CONF_GAS_MARKET_ENTITY = "gas_market_entity"
CONF_GAS_SUPPLIER = "gas_supplier_incl_vat"
CONF_GAS_TAX = "gas_tax_incl_vat"
CONF_GAS_FIXED_SUPPLY_PER_DAY = "gas_fixed_supply_per_day"
CONF_GAS_GRID_PER_DAY = "gas_grid_per_day"
PRICES_PROVIDER = "stroomvoorspeller"
PRICES_SOURCE_ATTRIBUTION = "Data provided by Stroomvoorspeller.nl (CC BY 4.0)"
PRICE_BUFFER_HOURS = 76
PRICE_BUFFER_SLOT_COUNT = PRICE_BUFFER_HOURS * 4

QUARTER_MINUTES = 15
QUARTER_SECONDS = QUARTER_MINUTES * 60
QUARTERS_PER_DAY = 96
FORECAST_HORIZON_HOURS = 72
FORECAST_SLOTS = FORECAST_HORIZON_HOURS * 60 // QUARTER_MINUTES
RECENCY_HALF_LIFE_DAYS = 28.0
MAX_HISTORY_DAYS = 400
MIN_VALID_COVERAGE = 0.90

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.energy_forecast"
ENERGY_STORE_SCHEMA_VERSION = 1
SOLAR_REFERENCE_FREEZE_STORAGE_VERSION = 1
SOLAR_REFERENCE_FREEZE_STORAGE_KEY = f"{DOMAIN}.solar_reference_freeze"

PLATFORMS = ["sensor", "select", "binary_sensor", "button"]
DEVICE_IDENTIFIER = "main"
FOUNDATION_PHASE = "solar_p3_0_foundation"
CANONICAL_HOME_POWER_ENTITY = "sensor.doems_source_home_power"

PUBLIC_OBJECT_ID_PREFIX = "doems_"

"""Constants for DOEMS."""

from __future__ import annotations

DOMAIN = "doems"
NAME = "DOEMS"
VERSION = "0.1.0-alpha.15"

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

# G6 EMS configuration contract - Steps 3A/3B/3C.
CONF_EMS_ENABLED = "ems_enabled"
CONF_SOC_ENTITY = "soc_entity"
CONF_BATTERY_CAPACITY_KWH = "battery_capacity_kwh"
CONF_TECHNICAL_MIN_SOC_PERCENT = "technical_min_soc_percent"
CONF_MAX_SOC_PERCENT = "max_soc_percent"
CONF_MAX_CHARGE_POWER_W = "max_charge_power_w"
CONF_MAX_DISCHARGE_POWER_W = "max_discharge_power_w"
CONF_SOFTWARE_RESERVE_PERCENT = "software_reserve_percent"
CONF_CHARGE_EFFICIENCY_PERCENT = "charge_efficiency_percent"
CONF_DISCHARGE_EFFICIENCY_PERCENT = "discharge_efficiency_percent"
CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH = "minimum_trade_margin_eur_per_kwh"
CONF_STARTUP_DELAY_SECONDS = "startup_delay_seconds"

# Step 12.1 read-only battery control-path mappings.
CONF_OPERATING_MODE_ENTITY = "operating_mode_entity"
CONF_ACTION_DIRECTION_ENTITY = "action_direction_entity"
CONF_POWER_SETPOINT_ENTITY = "power_setpoint_entity"
CONTROL_PATH_STABLE_SECONDS = 60
CONTROL_PATH_OBSERVER_INTERVAL_SECONDS = 10

# Legacy Alpha7.10-7.12 Away Options keys. Kept only for one-time migration into
# the runtime PresenceStore; they are no longer exposed as Options.
CONF_AWAY_SCHEDULE_ENABLED = "away_schedule_enabled"
CONF_AWAY_START = "away_start"
CONF_AWAY_END = "away_end"

DEFAULT_BATTERY_CAPACITY_KWH = 7.2
DEFAULT_TECHNICAL_MIN_SOC_PERCENT = 5
DEFAULT_MAX_SOC_PERCENT = 100
DEFAULT_MAX_CHARGE_POWER_W = 3200
DEFAULT_MAX_DISCHARGE_POWER_W = 3200
DEFAULT_SOFTWARE_RESERVE_PERCENT = 7.0
DEFAULT_CHARGE_EFFICIENCY_PERCENT = 92.0
DEFAULT_DISCHARGE_EFFICIENCY_PERCENT = 92.0
DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH = 0.10
DEFAULT_STARTUP_DELAY_SECONDS = 30
DEFAULT_AWAY_SCHEDULE_ENABLED = False
EMS_MIN_STARTUP_DELAY_SECONDS = 30
EMS_MAX_STARTUP_DELAY_SECONDS = 300
EMS_MAX_POWER_W = 3500
PLAN_SLOT_COUNT = 3
SERVICE_SCHEDULE_PLAN = "schedule_plan"
SERVICE_CANCEL_PLAN = "cancel_plan"

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

# Shared DOEMS Presence/Away runtime contract.
PRESENCE_STORAGE_VERSION = 1
PRESENCE_STORAGE_KEY = f"{DOMAIN}.presence"

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
CONF_GAS_SOURCE_MODE = "gas_source_mode"
GAS_SOURCE_HOME_ASSISTANT_ENTITY = "home_assistant_entity"
GAS_SOURCE_ENERGYZERO_MARKET_ACTION = "energyzero_market_action"
GAS_SOURCE_MODES = [
    GAS_SOURCE_HOME_ASSISTANT_ENTITY,
    GAS_SOURCE_ENERGYZERO_MARKET_ACTION,
]
CONF_GAS_MARKET_ENTITY = "gas_market_entity"
CONF_GAS_ENERGYZERO_CONFIG_ENTRY = "gas_energyzero_config_entry"
CONF_GAS_SUPPLIER = "gas_supplier_incl_vat"
CONF_GAS_TAX = "gas_tax_incl_vat"
CONF_GAS_FIXED_SUPPLY_PER_DAY = "gas_fixed_supply_per_day"
CONF_GAS_GRID_PER_DAY = "gas_grid_per_day"
GAS_HIGHER_HEATING_VALUE_KWH_M3 = 9.77
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
PLATFORMS = ["sensor", "select", "number", "binary_sensor", "switch", "datetime"]
DEVICE_IDENTIFIER = "main"
FOUNDATION_PHASE = "solar_p3_0_foundation"
CANONICAL_HOME_POWER_ENTITY = "sensor.doems_source_home_power"

PUBLIC_OBJECT_ID_PREFIX = "doems_"

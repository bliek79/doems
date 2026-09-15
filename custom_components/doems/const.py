"""Constants for DOEMS."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "doems"
NAME = "DOEMS"
VERSION = "0.1.0-alpha.1"

CONF_INSTANCE_NAME = "instance_name"
DEFAULT_INSTANCE_NAME = NAME

PLATFORMS: list[Platform] = [Platform.SENSOR]

DEVICE_IDENTIFIER = "main"
STORAGE_PREFIX = DOMAIN
FOUNDATION_PHASE = "step0_clean_foundation"

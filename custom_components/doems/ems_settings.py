"""Typed immutable G6 EMS settings snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .const import (
    CONF_BATTERY_CAPACITY_KWH,
    CONF_CHARGE_EFFICIENCY_PERCENT,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_MAX_CHARGE_POWER_W,
    CONF_MAX_DISCHARGE_POWER_W,
    CONF_MAX_SOC_PERCENT,
    CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    CONF_SOFTWARE_RESERVE_PERCENT,
    CONF_STARTUP_DELAY_SECONDS,
    CONF_TECHNICAL_MIN_SOC_PERCENT,
    DEFAULT_BATTERY_CAPACITY_KWH,
    DEFAULT_CHARGE_EFFICIENCY_PERCENT,
    DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
    DEFAULT_MAX_CHARGE_POWER_W,
    DEFAULT_MAX_DISCHARGE_POWER_W,
    DEFAULT_MAX_SOC_PERCENT,
    DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    DEFAULT_SOFTWARE_RESERVE_PERCENT,
    DEFAULT_STARTUP_DELAY_SECONDS,
    DEFAULT_TECHNICAL_MIN_SOC_PERCENT,
)


@dataclass(frozen=True, slots=True)
class EMSSettings:
    """Single validated settings snapshot consumed by the frozen EMS core."""

    battery_capacity_kwh: float
    technical_min_soc_percent: int
    max_soc_percent: int
    max_charge_power_w: int
    max_discharge_power_w: int
    software_reserve_percent: float
    charge_efficiency_percent: float
    discharge_efficiency_percent: float
    minimum_trade_margin_eur_per_kwh: float
    startup_delay_seconds: int

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> "EMSSettings":
        """Build one immutable snapshot from already validated config-entry Options."""
        return cls(
            battery_capacity_kwh=float(
                options.get(CONF_BATTERY_CAPACITY_KWH, DEFAULT_BATTERY_CAPACITY_KWH)
            ),
            technical_min_soc_percent=int(
                options.get(
                    CONF_TECHNICAL_MIN_SOC_PERCENT,
                    DEFAULT_TECHNICAL_MIN_SOC_PERCENT,
                )
            ),
            max_soc_percent=int(
                options.get(CONF_MAX_SOC_PERCENT, DEFAULT_MAX_SOC_PERCENT)
            ),
            max_charge_power_w=int(
                options.get(CONF_MAX_CHARGE_POWER_W, DEFAULT_MAX_CHARGE_POWER_W)
            ),
            max_discharge_power_w=int(
                options.get(
                    CONF_MAX_DISCHARGE_POWER_W,
                    DEFAULT_MAX_DISCHARGE_POWER_W,
                )
            ),
            software_reserve_percent=float(
                options.get(
                    CONF_SOFTWARE_RESERVE_PERCENT,
                    DEFAULT_SOFTWARE_RESERVE_PERCENT,
                )
            ),
            charge_efficiency_percent=float(
                options.get(
                    CONF_CHARGE_EFFICIENCY_PERCENT,
                    DEFAULT_CHARGE_EFFICIENCY_PERCENT,
                )
            ),
            discharge_efficiency_percent=float(
                options.get(
                    CONF_DISCHARGE_EFFICIENCY_PERCENT,
                    DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
                )
            ),
            minimum_trade_margin_eur_per_kwh=float(
                options.get(
                    CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
                    DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
                )
            ),
            startup_delay_seconds=int(
                options.get(
                    CONF_STARTUP_DELAY_SECONDS,
                    DEFAULT_STARTUP_DELAY_SECONDS,
                )
            ),
        )

    def as_contract(self) -> dict[str, int | float]:
        """Return a stable diagnostics/test representation without HA objects."""
        return {
            CONF_BATTERY_CAPACITY_KWH: self.battery_capacity_kwh,
            CONF_TECHNICAL_MIN_SOC_PERCENT: self.technical_min_soc_percent,
            CONF_MAX_SOC_PERCENT: self.max_soc_percent,
            CONF_MAX_CHARGE_POWER_W: self.max_charge_power_w,
            CONF_MAX_DISCHARGE_POWER_W: self.max_discharge_power_w,
            CONF_SOFTWARE_RESERVE_PERCENT: self.software_reserve_percent,
            CONF_CHARGE_EFFICIENCY_PERCENT: self.charge_efficiency_percent,
            CONF_DISCHARGE_EFFICIENCY_PERCENT: self.discharge_efficiency_percent,
            CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH: self.minimum_trade_margin_eur_per_kwh,
            CONF_STARTUP_DELAY_SECONDS: self.startup_delay_seconds,
        }

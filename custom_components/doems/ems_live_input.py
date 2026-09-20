"""Read-only assembly of the existing DOEMS forecast into the Alpha41 EMS input contract."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .ems_input_contract import build_alpha41_transport_input
from .energy_forecast import ceil_quarter

def build_live_ems_input(
    *,
    coordinator: Any,
    solar_forecast: Any,
    prices: Any,
    reference: datetime,
) -> dict[str, Any]:
    """Use the already-built DOEMS Energy, Solar and Prices forecasts as EMS input.

    This function is data-only. It does not read SOC, run the Alpha76 planner,
    mutate a plan store, call services or obtain physical execution authority.
    """
    window_start = ceil_quarter(reference)
    energy = coordinator.forecast(now=reference)
    energy_slots = [
        {"start": item.start, "energy_kwh": item.energy_kwh}
        for item in energy
    ]
    solar_slots = [
        {"start": item.start, "total_kwh": item.total_kwh}
        for item in solar_forecast.points
    ]
    price_slots = [
        {
            "time": item.get("time"),
            "import_all_in": item.get("import_all_in"),
            "export_all_in": item.get("export_all_in"),
            "kind": item.get("kind"),
        }
        for item in prices.timeline_slots
    ]
    result = build_alpha41_transport_input(
        window_start=window_start,
        energy_slots=energy_slots,
        solar_slots=solar_slots,
        price_slots=price_slots,
    )
    result.update({
        "input_source": "existing_doems_forecast",
        "energy_source": "doems_energy_forecast",
        "solar_source": "doems_solar_forecast",
        "prices_source": "doems_prices",
        "planner_runtime_active": False,
        "service_calls_performed": False,
        "physical_execution_authority": False,
    })
    return result

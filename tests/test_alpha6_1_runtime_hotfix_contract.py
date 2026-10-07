from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load(name: str):
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module(f"custom_components.doems.{name}")


def _history(start: datetime) -> list[dict]:
    records = []
    for index in range(14 * 96):
        slot = start - timedelta(days=14) + timedelta(minutes=15 * index)
        records.append(
            {
                "start": slot.isoformat(),
                "end": (slot + timedelta(minutes=15)).isoformat(),
                "energy_kwh": 0.05,
                "coverage": 1.0,
                "profile": "normal",
                "measurement_valid": True,
                "learning_valid": True,
                "learning_blocker": None,
                "valid": True,
            }
        )
    return records


def _solar_and_prices(reference: datetime):
    energy_model = _load("energy_forecast")
    start = energy_model.ceil_quarter(reference)
    solar = []
    prices = {}
    for index in range(288):
        slot = start + timedelta(minutes=15 * index)
        solar.append({"start": slot.isoformat(), "solar_kwh": 0.0})
        prices[slot.isoformat()] = {
            "time": slot.isoformat(),
            "import_all_in": 0.30,
            "export_all_in": 0.10,
            "kind": "known_15m",
        }
    return solar, prices


def _settings():
    return {
        "software_reserve_percent": 5.0,
        "max_charge_power_w": 3500.0,
        "max_discharge_power_w": 3500.0,
        "minimum_trade_margin_eur_per_kwh": 0.10,
        "peak_sale_threshold_eur_per_kwh": 0.50,
    }


def test_alpha61_native_quarter_request_signature_is_stable_and_sensitive() -> None:
    runtime = _load("automatic_planner_runtime")
    start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    base = dict(
        source_markers={"energy": {"count": 100}, "solar": {"generation": "a"}},
        plans=[],
        start_soc_percent=50,
        capacity_kwh=7.1,
        settings=_settings(),
    )
    a = runtime.planner_request_signature(reference=start + timedelta(minutes=1), **base)
    b = runtime.planner_request_signature(reference=start + timedelta(minutes=14, seconds=59), **base)
    c = runtime.planner_request_signature(reference=start + timedelta(minutes=15), **base)
    d = runtime.planner_request_signature(
        reference=start + timedelta(minutes=1),
        **{**base, "capacity_kwh": 14.2},
    )
    assert a == b
    assert a != c
    assert a != d
    assert runtime.planner_cycle_id(start + timedelta(minutes=1)).endswith("12:00:00+00:00")


def test_alpha61_executor_wrapper_preserves_alpha6_policy_result() -> None:
    runtime = _load("automatic_planner_runtime")
    policy = _load("automatic_planner_model")
    energy_model = _load("energy_forecast")

    reference = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    records = _history(reference)
    solar, prices = _solar_and_prices(reference)
    settings = _settings()
    plans = []

    wrapped = runtime.compute_automatic_planner_snapshot(
        reference=reference,
        energy_records=records,
        energy_profile="normal",
        local_timezone=timezone.utc,
        solar_slots=solar,
        plans=plans,
        start_soc_percent=50,
        capacity_kwh=7.1,
        price_by_start=prices,
        settings=settings,
    )
    forecast = energy_model.EnergyBaselineForecast(
        records, local_timezone=timezone.utc
    ).build("normal", now=reference)
    energy_slots = [
        {
            "start": slot.start.isoformat(),
            "end": slot.end.isoformat(),
            "home_kwh": slot.energy_kwh,
        }
        for slot in forecast
    ]
    direct = policy.build_automatic_plan(
        energy_slots=energy_slots,
        solar_slots=solar,
        plans=plans,
        start_soc_percent=50,
        capacity_kwh=7.1,
        price_by_start=prices,
        software_reserve_percent=5.0,
        max_charge_power_w=3500.0,
        max_discharge_power_w=3500.0,
        minimum_trade_margin_eur_per_kwh=0.10,
        peak_sale_threshold_eur_per_kwh=0.50,
    )
    stripped = dict(wrapped)
    for key in (
        "runtime_version",
        "planner_policy_version",
        "planner_cycle_id",
        "planner_reference",
        "planner_input_signature",
        "timeline_points",
    ):
        stripped.pop(key, None)
    assert stripped == direct
    assert wrapped["native_slot_count"] == 288
    assert len(wrapped["timeline_points"]) == 288


def test_alpha61_runtime_source_is_cache_only_and_executor_backed() -> None:
    runtime = (INTEGRATION / "automatic_planner.py").read_text(encoding="utf-8")
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    policy = (INTEGRATION / "automatic_planner_model.py").read_text(encoding="utf-8")

    assert "async_add_executor_job" in runtime
    assert "_cached_snapshot" in runtime
    assert "_pending_request" in runtime
    assert "generation != self._generation" in runtime
    assert '"native_quarter_plus_events"' in runtime
    assert "battery_capacity_changed" in runtime
    assert "ordinary SOC/power ticks" in runtime
    assert "build_automatic_plan(" not in runtime
    assert "return self._cached_snapshot" in runtime
    assert 'snapshot.get("timeline_points")' in sensor
    assert "automatic_planner_active" in policy
    assert "async_call(" not in runtime
    assert "third_party_control" not in runtime
    assert "DOEMSScheduler" not in runtime


def test_alpha61_version_contract() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    manifest = (INTEGRATION / "manifest.json").read_text(encoding="utf-8")
    assert 'VERSION = "0.2.0-alpha.6.2"' in const
    assert '"version": "0.2.0-alpha.6.2"' in manifest

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


def _axis(
    *,
    start: datetime | None = None,
    home_kwh: float = 0.0,
    solar_kwh: float = 0.0,
):
    start = start or datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)
    energy = []
    solar = []
    for index in range(288):
        slot_start = start + timedelta(minutes=15 * index)
        slot_end = slot_start + timedelta(minutes=15)
        energy.append(
            {
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
                "home_kwh": home_kwh,
            }
        )
        solar.append(
            {
                "start": slot_start.isoformat(),
                "solar_kwh": solar_kwh,
            }
        )
    return energy, solar


def _prices(
    energy,
    *,
    import_price: float = 0.20,
    export_price: float = 0.20,
):
    result = {}
    for index, row in enumerate(energy):
        kind = "known_pt15m" if index < 4 else "forecast_hour"
        result[row["start"]] = {
            "time": row["start"],
            "import_all_in": import_price,
            "export_all_in": export_price,
            "kind": kind,
            "source_resolution_minutes": 15 if index < 4 else 60,
        }
    return result


def _plan(
    *,
    action: str,
    start: datetime,
    target_soc: float,
    power_w: float = 3500.0,
    runtime_h: float = 2.0,
    slot: int = 1,
):
    return {
        "slot": slot,
        "action": action,
        "execution_mode": "gepland",
        "start_time": start.isoformat(),
        "power_w": power_w,
        "target_soc": target_soc,
        "max_runtime_h": runtime_h,
        "max_start_delay_min": 15.0,
        "lifecycle_status": "pending",
        "origin": "manual",
    }


def _bundle(*, plans=(), start_soc=50.0):
    model = _load("automatic_combined_planner_model")
    energy, solar = _axis()
    return model.build_planner_bundle(
        energy_slots=energy,
        solar_slots=solar,
        plans=list(plans),
        start_soc_percent=start_soc,
        capacity_kwh=7.1,
        price_by_start=_prices(energy),
    )


def test_alpha7_1_public_planner_architecture_is_exact() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    required = (
        "doems_manual_planner",
        "doems_manual_soc_projection_timeline",
        "doems_automatic_planner",
        "doems_automatic_soc_projection_timeline",
        "doems_combined_planner",
        "doems_combined_soc_projection_timeline",
    )
    for unique_id in required:
        assert unique_id in sensor

    assert "doems_ems_plan72_hours" not in sensor
    assert "doems_r5_1_" not in sensor
    assert "observational_only" not in sensor
    assert "shadow_only" not in sensor


def test_alpha7_1_exact_288_and_default_floor_is_10_percent() -> None:
    bundle = _bundle()
    automatic = bundle["automatic"]
    combined = bundle["combined"]

    assert bundle["valid"] is True
    assert automatic["native_slot_count"] == 288
    assert combined["native_slot_count"] == 288
    assert automatic["planner_floor_soc_percent"] == 10.0
    assert combined["planner_floor_soc_percent"] == 10.0
    assert automatic["software_reserve_percent"] == 5.0
    assert automatic["technical_min_soc_percent"] == 5.0
    assert automatic["max_charge_power_w"] == 3500.0
    assert automatic["max_discharge_power_w"] == 3500.0
    assert automatic["minimum_trade_margin_eur_per_kwh"] == 0.10


def test_alpha7_1_no_manual_plan_combined_route_equals_automatic() -> None:
    bundle = _bundle(start_soc=55.0)
    automatic = bundle["automatic"]
    combined = bundle["combined"]

    assert automatic["manual_commitment_count"] == 0
    assert combined["manual_commitment_count"] == 0
    assert combined["native_slots"] == automatic["native_slots"]
    assert combined["end_soc_percent"] == automatic["end_soc_percent"]


def test_alpha7_1_manual_charge_only_changes_combined_and_target_clamps() -> None:
    start = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)
    bundle = _bundle(
        plans=[
            _plan(
                action="laden",
                start=start,
                target_soc=60.0,
                runtime_h=2.0,
            )
        ],
        start_soc=50.0,
    )
    automatic = bundle["automatic"]
    combined = bundle["combined"]

    assert automatic["manual_commitment_count"] == 0
    assert combined["manual_commitment_count"] == 1
    assert combined["manual_commitment_slots"] == [1]
    assert all(
        float(row["manual_charge_kwh"]) == 0.0
        for row in automatic["native_slots"]
    )
    assert combined["native_slots"][4]["manual_charge_kwh"] > 0.0
    assert combined["native_slots"][4]["manual_slots"] == [1]
    assert combined["native_slots"][4]["end_soc_percent"] == 60.0
    assert max(
        float(row["end_soc_percent"])
        for row in combined["native_slots"]
    ) <= 60.0


def test_alpha7_1_manual_discharge_only_changes_combined_and_target_clamps() -> None:
    start = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)
    bundle = _bundle(
        plans=[
            _plan(
                action="ontladen",
                start=start,
                target_soc=30.0,
                runtime_h=12.0,
            )
        ],
        start_soc=80.0,
    )
    automatic = bundle["automatic"]
    combined = bundle["combined"]

    assert all(
        float(row["manual_discharge_kwh"]) == 0.0
        for row in automatic["native_slots"]
    )
    assert any(
        float(row["manual_discharge_kwh"]) > 0.0
        for row in combined["native_slots"]
    )
    assert combined["end_soc_percent"] == 30.0
    assert min(
        float(row["end_soc_percent"])
        for row in combined["native_slots"]
    ) >= 30.0


def test_alpha7_1_price_provenance_survives_hourly_combined_output() -> None:
    bundle = _bundle()
    combined = bundle["combined"]
    rows = combined["native_slots"]
    hours = combined["hourly_plan"]

    assert rows[0]["price_source"] == "known"
    assert rows[0]["price_kind"] == "known_pt15m"
    assert rows[4]["price_source"] == "forecast"
    assert rows[4]["price_kind"] == "forecast_hour"
    assert hours[0]["price_source"] == "known"
    assert hours[0]["price_kind"] == "known_pt15m"
    assert hours[1]["price_source"] == "forecast"
    assert hours[1]["price_kind"] == "forecast_hour"


def test_alpha7_1_hourly_output_carries_dynamic_reserve_for_dashboard() -> None:
    bundle = _bundle()
    first = bundle["combined"]["hourly_plan"][0]
    assert "dynamic_reserve_floor_start_soc_percent" in first
    assert "dynamic_reserve_floor_end_soc_percent" in first


def test_alpha7_1_usable_solar_is_two_consecutive_full_clock_hours() -> None:
    model = _load("automatic_combined_planner_model")
    energy, solar = _axis(home_kwh=0.10, solar_kwh=0.0)
    for index in range(4, 12):
        solar[index]["solar_kwh"] = 0.10

    axis, blockers = model._validate_time_axis(energy, solar)
    assert blockers == []
    pairs = model._usable_solar_pairs(axis)

    assert len(pairs) >= 1
    assert pairs[0]["start"].isoformat() == "2026-10-07T01:00:00+00:00"
    assert pairs[0]["first_index"] == 4


def test_alpha7_1_dynamic_reserve_falls_back_to_base_without_proven_solar() -> None:
    model = _load("automatic_combined_planner_model")
    energy, solar = _axis(home_kwh=0.10, solar_kwh=0.0)
    axis, blockers = model._validate_time_axis(energy, solar)
    assert blockers == []

    profile, pairs = model._dynamic_reserve_profile(
        axis, 7.1, 10.0, 0.92
    )
    assert pairs == []
    assert all(
        round(float(item["floor_soc"]), 6) == 10.0
        for item in profile
    )


def test_alpha7_1_peak_sale_stays_disabled() -> None:
    bundle = _bundle()
    for key in ("automatic", "combined"):
        planner = bundle[key]
        assert planner["peak_sale_enabled"] is False
        assert all(
            "piek" not in str(item.get("type", "")).lower()
            for item in planner["candidates"]
        )


def test_alpha7_1_planners_have_no_execution_authority() -> None:
    bundle = _bundle()
    for key in ("automatic", "combined"):
        planner = bundle[key]
        assert planner["plan_store_writes_enabled"] is False
        assert planner["scheduler_enabled"] is False
        assert planner["safety_prestart_enabled"] is False
        assert planner["execution_enabled"] is False
        assert planner["physical_execution_enabled"] is False


def test_alpha7_1_runtime_is_cached_executor_and_sensor_reads_do_not_compute() -> None:
    runtime = (INTEGRATION / "automatic_combined_planner.py").read_text(
        encoding="utf-8"
    )
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")

    assert "async_add_executor_job" in runtime
    assert "self._cached_bundle" in runtime
    assert "def snapshot(" in runtime
    assert "compute_planner_bundle" not in sensor
    assert "build_planner_bundle" not in sensor


def test_alpha7_1_prices_planner_window_remains_read_only_exact_288() -> None:
    prices = (INTEGRATION / "prices.py").read_text(encoding="utf-8")

    assert "def planner_timeline_slots(self, reference: datetime)" in prices
    assert "self._price_buffer_by_start" in prices
    assert "slot_count=FORECAST_SLOTS" in prices
    assert '"kind": "missing"' in prices


def test_alpha7_1_permanent_option_defaults_and_version() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    manifest = (INTEGRATION / "manifest.json").read_text(encoding="utf-8")

    assert 'VERSION = "0.2.0-alpha.7.1.1"' in const
    assert '"version": "0.2.0-alpha.7.1.1"' in manifest
    assert 'DEFAULT_PLANNER_SOFTWARE_RESERVE_PERCENT = 5.0' in const
    assert 'DEFAULT_PLANNER_MAX_CHARGE_POWER_W = 3500.0' in const
    assert 'DEFAULT_PLANNER_MAX_DISCHARGE_POWER_W = 3500.0' in const
    assert (
        'DEFAULT_PLANNER_MINIMUM_TRADE_MARGIN_EUR_PER_KWH = 0.10'
        in const
    )


def test_alpha7_1_temporary_planner_modules_are_retired() -> None:
    assert not (INTEGRATION / "r5_preview.py").exists()
    assert not (INTEGRATION / "r5_preview_runtime.py").exists()
    assert not (INTEGRATION / "r5_preview_model.py").exists()

    active = "".join(
        (INTEGRATION / name).read_text(encoding="utf-8")
        for name in (
            "sensor.py",
            "automatic_combined_planner.py",
            "automatic_combined_planner_runtime.py",
            "automatic_combined_planner_model.py",
        )
    ).lower()
    assert "shadow_only" not in active
    assert "observational_only" not in active
    assert "doems_r5_1_" not in active


def test_alpha7_1_1_registry_migration_keeps_existing_permanent_target() -> None:
    migration = (INTEGRATION / "planner_migration.py").read_text(encoding="utf-8")
    assert "registry.async_remove(old_entity_id)" in migration
    assert "permanent target" in migration
    assert "raise RuntimeError(\n            \"DOEMS planner identity migration collision" not in migration


def test_alpha7_1_1_dashboard_header_is_not_entity_bound() -> None:
    dashboard = (ROOT / "examples" / "doems_planner_dashboard.yaml").read_text(
        encoding="utf-8"
    )
    header = dashboard.split("  - type: custom:button-card", 2)[1]
    assert "entity: sensor.doems_combined_planner\n    triggers_update:" not in header
    assert "const combinedEntity = hass.states['sensor.doems_combined_planner'];" in header
    assert "Niet beschikbaar" in header

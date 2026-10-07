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
    out = {}
    for index, row in enumerate(energy):
        kind = "known_pt15m" if index < 4 else "forecast_hour"
        out[row["start"]] = {
            "time": row["start"],
            "import_all_in": import_price,
            "export_all_in": export_price,
            "kind": kind,
            "source_resolution_minutes": 15 if index < 4 else 60,
        }
    return out


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
    model = _load("r5_preview_model")
    energy, solar = _axis()
    return model.build_r5_preview_bundle(
        energy_slots=energy,
        solar_slots=solar,
        plans=list(plans),
        start_soc_percent=start_soc,
        capacity_kwh=7.1,
        price_by_start=_prices(energy),
    )


def test_alpha7_r0_r4_plan72_producer_is_unchanged_and_r5_is_separate() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    r5_files = "".join(
        (INTEGRATION / name).read_text(encoding="utf-8")
        for name in (
            "r5_preview.py",
            "r5_preview_model.py",
            "r5_preview_runtime.py",
        )
    )

    assert (
        "DOEMSManualPlan72HoursCompatSensor(entry, manual_soc_projection)"
        in sensor
    )
    assert sensor.count(
        '_attr_unique_id = "doems_ems_plan72_hours"'
    ) == 1
    assert "DOEMSAutomaticPlan72HoursCompatSensor" not in sensor
    assert "doems_ems_plan72_hours" not in r5_files
    assert '"manual_soc_projection": manual_soc_projection' in init
    assert '"r5_preview": r5_preview' in init
    assert "DOEMSManualSOCProjection" in init
    assert "DOEMSR5PreviewManager" in init


def test_alpha7_base_and_combined_are_exact_288_and_default_floor_is_10() -> None:
    bundle = _bundle()
    base = bundle["automatic_base"]
    combined = bundle["combined"]

    assert bundle["valid"] is True
    assert base["native_slot_count"] == 288
    assert combined["native_slot_count"] == 288
    assert base["planner_floor_soc_percent"] == 10.0
    assert combined["planner_floor_soc_percent"] == 10.0
    assert base["software_reserve_percent"] == 5.0
    assert base["technical_min_soc_percent"] == 5.0
    assert base["max_charge_power_w"] == 3500.0
    assert base["max_discharge_power_w"] == 3500.0
    assert base["minimum_trade_margin_eur_per_kwh"] == 0.10


def test_alpha7_no_manual_plan_combined_native_route_equals_base() -> None:
    bundle = _bundle(start_soc=55.0)
    base = bundle["automatic_base"]
    combined = bundle["combined"]

    assert base["manual_commitment_count"] == 0
    assert combined["manual_commitment_count"] == 0
    assert combined["native_slots"] == base["native_slots"]
    assert combined["end_soc_percent"] == base["end_soc_percent"]


def test_alpha7_manual_charge_is_only_in_combined_and_target_clamped() -> None:
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
    base = bundle["automatic_base"]
    combined = bundle["combined"]

    assert base["manual_commitment_count"] == 0
    assert combined["manual_commitment_count"] == 1
    assert combined["manual_commitment_slots"] == [1]
    assert all(
        float(row["manual_charge_kwh"]) == 0.0
        for row in base["native_slots"]
    )
    assert combined["native_slots"][4]["manual_charge_kwh"] > 0.0
    assert combined["native_slots"][4]["manual_slots"] == [1]
    assert combined["native_slots"][4]["end_soc_percent"] == 60.0
    assert max(
        float(row["end_soc_percent"])
        for row in combined["native_slots"]
    ) <= 60.0


def test_alpha7_manual_discharge_is_only_in_combined_and_target_clamped() -> None:
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
    base = bundle["automatic_base"]
    combined = bundle["combined"]

    assert all(
        float(row["manual_discharge_kwh"]) == 0.0
        for row in base["native_slots"]
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


def test_alpha7_price_provenance_survives_native_and_hourly_combined_output() -> None:
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


def test_alpha7_usable_solar_requires_two_consecutive_complete_clock_hours() -> None:
    model = _load("r5_preview_model")
    energy, solar = _axis(home_kwh=0.10, solar_kwh=0.0)
    for index in range(4, 12):
        solar[index]["solar_kwh"] = 0.10

    axis, blockers = model._validate_time_axis(energy, solar)
    assert blockers == []
    pairs = model._usable_solar_pairs(axis)

    assert len(pairs) >= 1
    assert pairs[0]["start"].isoformat() == "2026-10-07T01:00:00+00:00"
    assert pairs[0]["first_index"] == 4


def test_alpha7_dynamic_reserve_falls_back_to_base_floor_without_proven_solar() -> None:
    model = _load("r5_preview_model")
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
    assert all(
        item["next_usable_solar"] is None for item in profile
    )


def test_alpha7_peak_sale_is_deferred_and_no_peak_candidates_exist() -> None:
    bundle = _bundle()
    for key in ("automatic_base", "combined"):
        preview = bundle[key]
        assert preview["peak_sale_active"] is False
        assert preview["peak_sale_deferred_to"] == "R5.2"
        assert all(
            "piek" not in str(item.get("type", "")).lower()
            for item in preview["candidates"]
        )


def test_alpha7_control_path_is_hard_read_only() -> None:
    bundle = _bundle()
    for key in ("automatic_base", "combined"):
        preview = bundle[key]
        assert preview["automatic_plan_store_writes"] is False
        assert preview["scheduler_active"] is False
        assert preview["safety_prestart_active"] is False
        assert preview["execution_enabled"] is False
        assert preview["physical_execution_authority"] is False

    r5_text = "".join(
        (INTEGRATION / name).read_text(encoding="utf-8")
        for name in (
            "r5_preview.py",
            "r5_preview_model.py",
            "r5_preview_runtime.py",
        )
    )
    assert "async_call(" not in r5_text
    assert "third_party_control" not in r5_text


def test_alpha7_runtime_is_cached_executor_and_sensor_reads_do_not_compute() -> None:
    runtime = (INTEGRATION / "r5_preview.py").read_text(
        encoding="utf-8"
    )
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")

    assert "async_add_executor_job" in runtime
    assert "self._cached_bundle" in runtime
    assert "def snapshot(" in runtime
    assert "compute_r5_preview_bundle" not in sensor
    assert "build_r5_preview_bundle" not in sensor


def test_alpha7_prices_planner_window_is_read_only_exact_288_selector() -> None:
    prices = (INTEGRATION / "prices.py").read_text(encoding="utf-8")

    assert "def planner_timeline_slots(self, reference: datetime)" in prices
    assert "self._price_buffer_by_start" in prices
    assert "slot_count=FORECAST_SLOTS" in prices
    assert '"kind": "missing"' in prices


def test_alpha7_version_and_new_entity_ids_are_isolated() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    manifest = (INTEGRATION / "manifest.json").read_text(encoding="utf-8")
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")

    assert 'VERSION = "0.2.0-alpha.7"' in const
    assert '"version": "0.2.0-alpha.7"' in manifest
    for entity_id in (
        "doems_r5_1_automatic_base_preview",
        "doems_r5_1_automatic_base_soc_timeline",
        "doems_r5_1_combined_preview",
        "doems_r5_1_combined_soc_timeline",
    ):
        assert entity_id in sensor

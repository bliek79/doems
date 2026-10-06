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


def _plan(
    *,
    slot: int = 1,
    action: str = "laden",
    start: datetime | None = None,
    power_w: float = 3000,
    target_soc: float = 80,
    runtime_h: float = 2,
    lifecycle: str = "pending",
):
    start = start or datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)
    return {
        "slot": slot,
        "action": action,
        "execution_mode": "gepland",
        "start_time": start.isoformat(),
        "power_w": power_w,
        "target_soc": target_soc,
        "max_runtime_h": runtime_h,
        "max_start_delay_min": 15,
        "lifecycle_status": lifecycle,
        "origin": "manual",
    }


def test_alpha4_native_axis_is_exact_288_slots_and_72_hours() -> None:
    m = _load("manual_soc_projection_model")
    energy, solar = _axis()
    result = m.project_manual_soc(
        energy_slots=energy,
        solar_slots=solar,
        plans=[],
        start_soc_percent=50,
        capacity_kwh=7.1,
    )
    assert result["status"] == "ready"
    assert result["valid"] is True
    assert result["native_slot_count"] == 288
    assert result["start"] == "2026-10-07T00:00:00+00:00"
    assert result["end"] == "2026-10-10T00:00:00+00:00"
    assert result["start_soc_percent"] == 50
    assert result["end_soc_percent"] == 50
    assert result["manual_commitment_count"] == 0
    assert result["mode"] == "manual_projection_only"
    assert result["automatic_planner_active"] is False
    assert result["scheduler_active"] is False
    assert result["physical_execution_authority"] is False


def test_alpha4_manual_charge_changes_soc_from_its_start_and_respects_target() -> None:
    m = _load("manual_soc_projection_model")
    energy, solar = _axis()
    start = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)
    result = m.project_manual_soc(
        energy_slots=energy,
        solar_slots=solar,
        plans=[_plan(start=start, action="laden", target_soc=25, power_w=3000)],
        start_soc_percent=20,
        capacity_kwh=7.1,
    )
    assert result["status"] == "ready"
    rows = result["native_slots"]
    assert rows[3]["end_soc_percent"] == 20
    assert rows[4]["start_soc_percent"] == 20
    assert rows[4]["end_soc_percent"] == 25
    assert rows[4]["manual_charge_kwh"] > 0
    assert rows[4]["manual_slots"] == [1]
    assert all(row["end_soc_percent"] == 25 for row in rows[4:])


def test_alpha4_manual_discharge_never_crosses_target_or_technical_minimum() -> None:
    m = _load("manual_soc_projection_model")
    energy, solar = _axis()
    result = m.project_manual_soc(
        energy_slots=energy,
        solar_slots=solar,
        plans=[
            _plan(
                action="ontladen",
                start=datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc),
                target_soc=20,
                power_w=3500,
                runtime_h=12,
            )
        ],
        start_soc_percent=80,
        capacity_kwh=7.1,
    )
    assert result["status"] == "ready"
    assert result["end_soc_percent"] == 20
    assert min(row["end_soc_percent"] for row in result["native_slots"]) >= 20
    assert min(row["end_soc_percent"] for row in result["native_slots"]) >= 5


def test_alpha4_cancelled_concept_and_cleared_plans_do_not_affect_projection() -> None:
    m = _load("manual_soc_projection_model")
    energy, solar = _axis()
    plans = [
        _plan(slot=1, lifecycle="geannuleerd"),
        _plan(slot=2, lifecycle="concept"),
        {
            "slot": 3,
            "action": "geen",
            "execution_mode": "direct",
            "start_time": None,
            "power_w": 100,
            "target_soc": 80,
            "max_runtime_h": 2,
            "max_start_delay_min": 15,
            "lifecycle_status": "concept",
            "origin": "manual",
        },
    ]
    result = m.project_manual_soc(
        energy_slots=energy,
        solar_slots=solar,
        plans=plans,
        start_soc_percent=40,
        capacity_kwh=7.1,
    )
    assert result["status"] == "ready"
    assert result["manual_commitment_count"] == 0
    assert result["end_soc_percent"] == 40


def test_alpha4_later_solar_is_reused_after_manual_discharge_creates_headroom() -> None:
    m = _load("manual_soc_projection_model")
    energy, solar = _axis()
    # One later quarter has 0.8 kWh PV and no home demand.
    solar[1]["solar_kwh"] = 0.8
    plan = _plan(
        action="ontladen",
        start=datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc),
        power_w=3500,
        target_soc=50,
        runtime_h=0.5,
    )
    result = m.project_manual_soc(
        energy_slots=energy,
        solar_slots=solar,
        plans=[plan],
        start_soc_percent=100,
        capacity_kwh=7.1,
    )
    assert result["status"] == "ready"
    rows = result["native_slots"]
    assert rows[0]["manual_discharge_kwh"] > 0
    assert rows[1]["charge_from_solar_kwh"] > 0
    assert rows[1]["end_soc_percent"] > rows[1]["start_soc_percent"]


def test_alpha4_partial_clock_hour_window_can_yield_73_presentation_buckets() -> None:
    m = _load("manual_soc_projection_model")
    energy, solar = _axis(
        start=datetime(2026, 10, 7, 0, 15, tzinfo=timezone.utc)
    )
    result = m.project_manual_soc(
        energy_slots=energy,
        solar_slots=solar,
        plans=[],
        start_soc_percent=50,
        capacity_kwh=7.1,
    )
    assert result["native_slot_count"] == 288
    assert result["clock_hour_bucket_count"] == 73
    assert result["hourly_plan"][0]["slot_count"] == 3
    assert result["hourly_plan"][-1]["slot_count"] == 1


def test_alpha4_misaligned_forecast_axis_blocks_fail_closed() -> None:
    m = _load("manual_soc_projection_model")
    energy, solar = _axis()
    solar[10]["start"] = (
        datetime.fromisoformat(solar[10]["start"]) + timedelta(minutes=15)
    ).isoformat()
    result = m.project_manual_soc(
        energy_slots=energy,
        solar_slots=solar,
        plans=[],
        start_soc_percent=50,
        capacity_kwh=7.1,
    )
    assert result["status"] == "blocked"
    assert result["valid"] is False
    assert any("solar_alignment_missing" in blocker for blocker in result["blockers"])


def test_alpha4_overlapping_manual_commitments_block_fail_closed() -> None:
    m = _load("manual_soc_projection_model")
    energy, solar = _axis()
    first = _plan(slot=1, start=datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc))
    second = _plan(slot=2, start=datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc))
    result = m.project_manual_soc(
        energy_slots=energy,
        solar_slots=solar,
        plans=[first, second],
        start_soc_percent=50,
        capacity_kwh=7.1,
    )
    assert result["status"] == "blocked"
    assert "manual_plan_overlap:1:2" in result["blockers"]


def test_alpha4_uses_proven_92_percent_efficiencies_and_5_percent_floor() -> None:
    m = _load("manual_soc_projection_model")
    assert m.CHARGE_EFFICIENCY == 0.92
    assert m.DISCHARGE_EFFICIENCY == 0.92
    assert m.MIN_SOC_PERCENT == 5.0
    assert m.MAX_PROJECTION_POWER_W == 3500.0


def test_alpha4_public_surfaces_reuse_plan72_hours_identity_and_are_read_only() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "manual_soc_projection.py").read_text(encoding="utf-8")
    model = (INTEGRATION / "manual_soc_projection_model.py").read_text(encoding="utf-8")

    assert 'doems_manual_soc_projection' in sensor
    assert 'doems_manual_soc_projection_timeline' in sensor
    assert 'doems_ems_plan72_hours' in sensor
    assert '"manual_projection_only"' in model
    assert '"automatic_planner_active": False' in model
    assert '"scheduler_active": False' in model
    assert '"physical_execution_authority": False' in model

    active = runtime + model
    assert "async_call(" not in active
    assert "third_party_control" not in active
    assert "automatic_72h_planner" not in active
    assert "DOEMSScheduler" not in active

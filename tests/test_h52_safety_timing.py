"""H5.2: prove Alpha84 executable safety timing, not just allocation totals."""
from datetime import datetime, timedelta

from test_alpha84_bridge_port import bridge, bridge_data
from test_alpha84_safety_chain_parity import _verify
from test_alpha84_planning_oracle import oracle


def test_safety_valley_executable_window_start_end_match_frozen_alpha84():
    original, soc = _verify.scenarios()["safety_valley"]
    report = _verify.compare_case(original, soc)
    frozen = report["alpha84"]["bridge_candidates"]
    quarter = report["source_quarter"]["bridge_candidates"]
    actual = report["native_plan72"]["plan"]["action_windows"]

    assert len(frozen) == len(quarter) == len(actual) == 2
    for original_action, source_action, physical_action in zip(
        frozen, quarter, actual
    ):
        for field in ("start_time", "planned_end_time", "action", "purpose"):
            if field == "purpose":
                assert original_action[field] == source_action[field]
            elif field == "action":
                assert original_action[field] == source_action[field]
            else:
                assert source_action[field] == original_action[field]
                assert physical_action[field] == original_action[field]
        hours = (datetime.fromisoformat(source_action["planned_end_time"])
                 - datetime.fromisoformat(source_action["start_time"])).total_seconds() / 3600
        assert 0 < hours <= 12
        assert abs(source_action["max_runtime_h"] - hours) < 1e-9
        assert physical_action["power_start_time"] == (
            datetime.fromisoformat(source_action["start_time"]) +
            timedelta(minutes=2)).isoformat()

    assert frozen[0]["start_time"] == "2026-11-15T18:00:00+00:00"
    assert frozen[1]["start_time"] == "2026-11-17T12:00:00+00:00"
    assert report["native_plan72"]["plan"]["reserve_satisfied"] is True
    assert report["native_plan72"]["plan"]["execution_enabled"] is False


def test_hour_equivalent_preview_retains_small_source_hour_but_bridge_does_not_start_early():
    # Original Alpha84 hour 00 is 0.046 kWh (<0.10), hour 01 is 0.18 kWh.
    # The original Bridge starts at 01, rather than promoting hour 00 by
    # treating both hours as one contiguous 0.226-kWh candidate.
    rows = [
        dict(time=(oracle.NOW + timedelta(minutes=15*q)).isoformat(),
             soc_start=30, soc_end=40,
             charge_from_grid_safety_kwh=.0115 if q < 4 else .045,
             charge_from_grid_trade_kwh=0, price=.15, price_source="known")
        for q in range(8)
    ]
    base = bridge_data(dict(
        auto_plan_72h_plan=rows, auto_plan_72h_valid=True,
        auto_plan_72h_execution_buffer_safe=True,
    ))
    frozen_hour_equivalent = bridge.build_planner_action_bridge(
        dict(base, alpha84_hour_equivalent_safety=True),
        now=oracle.NOW, interval_minutes=15)
    native_quarters = bridge.build_planner_action_bridge(
        base, now=oracle.NOW, interval_minutes=15)
    assert frozen_hour_equivalent["auto_bridge_candidate_count"] == 1
    action = frozen_hour_equivalent["auto_bridge_candidates"][0]
    assert action["start_time"] == (oracle.NOW + timedelta(hours=1)).isoformat()
    assert action["planned_end_time"] == (oracle.NOW + timedelta(hours=2)).isoformat()
    assert abs(action["requested_energy_kwh"] - .18) < 1e-9
    assert abs(frozen_hour_equivalent["auto_bridge_suppressed_safety_charge_kwh"] - .046) < 1e-9
    # Genuine native quarter runs may still use an eligible cross-hour
    # contiguous safety prefix; this is not globally banned.
    assert native_quarters["auto_bridge_candidates"][0]["start_time"] == oracle.NOW.isoformat()


def test_native_contiguous_safety_above_twelve_hours_is_split_at_real_runtime_limit():
    rows = [
        dict(time=(oracle.NOW + timedelta(minutes=15*q)).isoformat(),
             soc_start=20, soc_end=35,
             charge_from_grid_safety_kwh=.025,
             charge_from_grid_trade_kwh=0, price=.2, price_source="known")
        for q in range(52)  # 13 hours of actionable safety energy
    ]
    result = bridge.build_planner_action_bridge(
        bridge_data(dict(auto_plan_72h_plan=rows, auto_plan_72h_valid=True,
                         auto_plan_72h_execution_buffer_safe=True)),
        now=oracle.NOW, interval_minutes=15)
    candidates = result["auto_bridge_candidates"]
    assert len(candidates) == 2
    assert candidates[0]["start_time"] == oracle.NOW.isoformat()
    assert candidates[0]["planned_end_time"] == (
        oracle.NOW + timedelta(hours=12)).isoformat()
    assert candidates[1]["start_time"] == candidates[0]["planned_end_time"]
    assert candidates[1]["planned_end_time"] == (
        oracle.NOW + timedelta(hours=13)).isoformat()
    assert candidates[0]["max_runtime_h"] == 12
    assert candidates[1]["max_runtime_h"] == 1
    assert all(candidate["valid"] for candidate in candidates)
    assert abs(sum(c["requested_energy_kwh"] for c in candidates) - 1.3) < 1e-9

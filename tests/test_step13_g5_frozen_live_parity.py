from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _install_import_stubs() -> None:
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    if "custom_components.doems.ems_alpha76" not in sys.modules:
        package = types.ModuleType("custom_components.doems.ems_alpha76")
        package.__path__ = [str(INTEGRATION / "ems_alpha76")]
        sys.modules["custom_components.doems.ems_alpha76"] = package

    homeassistant = types.ModuleType("homeassistant")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")
    dt.UTC = timezone.utc
    dt.DEFAULT_TIME_ZONE = timezone.utc
    dt.utcnow = lambda: datetime.now(timezone.utc)

    def parse_datetime(value: str):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return parsed

    dt.parse_datetime = parse_datetime
    util.dt = dt
    homeassistant.util = util
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.util", util)
    sys.modules.setdefault("homeassistant.util.dt", dt)


def _parity_module():
    _install_import_stubs()
    return importlib.import_module("custom_components.doems.ems_g5_live_parity")


def _input_contract_module():
    _install_import_stubs()
    return importlib.import_module("custom_components.doems.ems_input_contract")


def _snapshot() -> dict:
    contract = _input_contract_module()
    start = datetime(2026, 9, 23, 19, 15, tzinfo=timezone.utc)
    energy = []
    solar = []
    prices = []
    for index in range(288):
        t = start + timedelta(minutes=15 * index)
        energy.append({"start": t, "energy_kwh": 0.075})
        # Two or more consecutive transport hours are immediately usable.
        solar.append({"start": t, "total_kwh": 0.100})
        prices.append(
            {
                "time": t,
                "import_all_in": 0.25,
                "export_all_in": 0.25,
                "kind": "known_pt15m",
            }
        )
    input_result = contract.build_alpha41_transport_input(
        window_start=start,
        energy_slots=energy,
        solar_slots=solar,
        price_slots=prices,
    )
    slots = {
        slot: {
            "slot": slot,
            "status": "leeg",
            "action": "geen",
            "purpose": None,
            "origin": "manual",
            "lifecycle_status": "concept",
            "start_time": None,
            "planned_end_time": None,
            "planner_identity": None,
            "planner_signature": None,
        }
        for slot in range(1, 4)
    }
    return {
        "schema_version": 1,
        "captured_at": start.isoformat(),
        "input_result": input_result,
        "time_contract": deepcopy(input_result["time_contract"]),
        "soc_source_entity": "sensor.test_soc",
        "measured_soc_percent": 60.0,
        "planner_start_soc_percent": 60.0,
        "profile": "normal",
        "scheduler_slots": slots,
        "config": {
            "battery_capacity_kwh": 7.2,
            "technical_min_soc_percent": 5,
            "max_soc_percent": 100,
            "max_charge_power_w": 3200,
            "max_discharge_power_w": 3200,
            "software_reserve_percent": 7.0,
            "charge_efficiency_percent": 92.0,
            "discharge_efficiency_percent": 92.0,
            "minimum_trade_margin_eur_per_kwh": 0.10,
            "startup_delay_seconds": 30,
        },
        "shadow_only": True,
        "service_calls_performed": False,
        "plan_store_mutated_by_capture": False,
        "physical_execution_authority": False,
    }


def test_step13_same_frozen_input_is_exact_policy_baseline_match() -> None:
    parity = _parity_module()
    result = parity.compare_frozen_live_snapshot(_snapshot())
    assert result["status"] == "pass"
    assert result["exact_match"] is True
    assert result["difference_count"] == 0
    assert result["differences"] == []
    assert result["policy_version"] == "alpha76_baseline_v1"
    assert result["golden_decision"] == result["doems_decision"]
    assert result["shadow_only"] is True
    assert result["service_calls_performed"] is False
    assert result["plan_store_mutated"] is False
    assert result["physical_execution_authority"] is False
    assert result["cutover_permitted"] is False


def test_step13_snapshot_fingerprint_is_deterministic_and_sensitive() -> None:
    parity = _parity_module()
    first = _snapshot()
    second = deepcopy(first)
    assert parity.snapshot_fingerprint(first) == parity.snapshot_fingerprint(second)
    second["input_result"]["slots"][0]["home_kwh"] = 0.076
    assert parity.snapshot_fingerprint(first) != parity.snapshot_fingerprint(second)


def test_step13_incomplete_native_input_blocks_fail_closed() -> None:
    parity = _parity_module()
    snapshot = _snapshot()
    snapshot["input_result"]["slots"][5]["valid"] = False
    snapshot["input_result"]["native_valid_slot_count"] = 287
    result = parity.compare_frozen_live_snapshot(snapshot)
    assert result["status"] == "blocked"
    assert result["exact_match"] is False
    assert "input_native_slots_not_fully_valid" in result["blockers"]
    assert "input_native_valid_slot_count_not_288" in result["blockers"]


def test_step13_mismatch_reports_total_and_compact_paths(monkeypatch) -> None:
    parity = _parity_module()
    original = parity._doems_chain

    def altered(*args, **kwargs):
        bundle = deepcopy(original(*args, **kwargs))
        bundle["plan72"]["auto_plan_72h_reason"] = "forced_g5_test_difference"
        return bundle

    monkeypatch.setattr(parity, "_doems_chain", altered)
    result = parity.compare_frozen_live_snapshot(_snapshot())
    assert result["status"] == "mismatch"
    assert result["exact_match"] is False
    assert result["difference_count"] >= 1
    assert any("auto_plan_72h_reason" in item for item in result["differences"])


def test_step13_runtime_surface_is_persistent_and_non_actuating() -> None:
    parity = (INTEGRATION / "ems_g5_live_parity.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "ems_g5_live_parity_runtime.py").read_text(encoding="utf-8")
    sensor = (INTEGRATION / "ems_g5_live_parity_sensor.py").read_text(encoding="utf-8")
    button = (INTEGRATION / "button.py").read_text(encoding="utf-8")
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")

    assert "POLICY_VERSION = \"alpha76_baseline_v1\"" in parity
    assert "g5_frozen_live_parity" in runtime
    assert "Store[dict[str, Any]]" in runtime
    assert "DOEMS G5 Frozen Live Parity" in sensor
    assert "DOEMS G5 Capture Frozen Live Parity" in button
    assert '\"button\"' in const

    combined = "\n".join((parity, runtime, sensor, button))
    assert ".services.async_call(" not in combined
    assert "select.select_option" not in combined
    assert "number.set_value" not in combined
    assert '\"service_calls_performed\": False' in combined
    assert '\"physical_execution_authority\": False' in combined
    assert '\"cutover_permitted\": False' in combined

from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
RECORDER_BUDGET_BYTES = 10 * 1024


def _source(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def _compile_function(path: str, class_name: str | None, function_name: str):
    tree = ast.parse(_source(path))
    scope: list[ast.stmt] = tree.body
    if class_name is not None:
        cls = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        scope = cls.body
    fn = next(
        deepcopy(node) for node in scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    assert isinstance(fn, ast.FunctionDef)
    fn.name = "_contract_under_test"
    fn.decorator_list = []
    module = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, Any] = {
        "Any": Any,
        "DOMAIN": "doems",
    }
    exec(compile(module, f"<{path}:{function_name}>", "exec"), namespace)
    return namespace["_contract_under_test"]


def _class_unrecorded_attributes(path: str, class_name: str) -> frozenset[str]:
    tree = ast.parse(_source(path))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    for node in cls.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "_unrecorded_attributes" for target in node.targets):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
            and value.args
        ):
            return frozenset(ast.literal_eval(value.args[0]))
        return frozenset(ast.literal_eval(value))
    return frozenset()


def _recorder_bytes(attributes: dict[str, Any], unrecorded: frozenset[str]) -> tuple[int, bytes]:
    recorder_bound = {
        key: value
        for key, value in attributes.items()
        if key not in unrecorded
    }
    encoded = json.dumps(
        recorder_bound,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
        sort_keys=True,
    ).encode("utf-8")
    return len(encoded), encoded


class _SyntheticMap(dict[str, Any]):
    """Representative high-information mapping for the public runtime contract."""

    _BOOL_HINTS = (
        "valid",
        "ready",
        "safe",
        "enabled",
        "invoked",
        "configured",
        "available",
        "permitted",
        "control",
        "active",
        "required",
        "match",
        "complete",
        "selected",
        "armed",
    )

    def get(self, key: str, default: Any = None) -> Any:
        if key in self:
            return super().get(key, default)

        if key == "time_contract":
            return _SyntheticMap()
        if key in {"energy_need", "planner_preview", "plan72"}:
            return _SyntheticMap()
        if key == "entities":
            return {
                "operating_mode": _SyntheticMap(
                    entity_id="select.anker_operating_mode",
                    state="self_consumption",
                    available=True,
                ),
                "action_direction": _SyntheticMap(
                    entity_id="select.anker_action_direction",
                    state="charge",
                    available=True,
                ),
                "power_setpoint": _SyntheticMap(
                    entity_id="number.anker_power_setpoint",
                    state="0",
                    available=True,
                ),
            }
        if key == "scheduler_slots":
            return {
                slot: {
                    "status": "pending",
                    "action": "laden",
                    "purpose": "veiligheidsladen",
                    "origin": "automatic_72h_planner",
                    "lifecycle_status": "pending",
                    "start_time": f"2026-09-25T0{slot}:00:00+00:00",
                    "planned_end_time": f"2026-09-25T0{slot + 1}:00:00+00:00",
                    "power_w": 3200,
                    "planned_energy_kwh": 1.234,
                    "target_soc": 80,
                    "selected": slot == 1,
                    "planner_identity": f"identity-{slot}-" + "x" * 48,
                    "planner_signature": f"signature-{slot}-" + "x" * 48,
                }
                for slot in range(1, 4)
            }

        if key.endswith(("_reasons", "_warnings", "_blockers")):
            return [f"{key}-{index}-" + "x" * 48 for index in range(3)]
        if key.endswith("_checks"):
            return [
                {
                    "check": f"check_{index}",
                    "passed": True,
                    "severity": "ok",
                    "detail": "x" * 72,
                }
                for index in range(8)
            ]
        if key.endswith(("_slots", "_prices", "_sources")):
            return ["x" * 48 for _ in range(3)]
        if any(hint in key for hint in self._BOOL_HINTS):
            return True
        if key.endswith(("_count", "_hours", "_percent", "_soc", "_w", "_kwh", "_seconds")):
            return 123.456
        if key.endswith(("_at", "_time", "_start", "_end")):
            return "2026-09-25T06:00:00+00:00"
        return "value-" + "x" * 32


class _SyntheticPlanStore:
    def get_plan(self, slot: int) -> dict[str, Any]:
        return {
            "slot": slot,
            "status": "pending",
            "action": "laden",
            "purpose": "veiligheidsladen",
            "origin": "automatic_72h_planner",
            "lifecycle_status": "pending",
            "start_time": f"2026-09-25T0{slot}:00:00+00:00",
            "planned_end_time": f"2026-09-25T0{slot + 1}:00:00+00:00",
            "power_w": 3200,
            "planned_energy_kwh": 1.234,
            "target_soc": 80,
            "selected": slot == 1,
        }

    def plan_status(self, slot: int) -> str:
        return "pending"


class _SyntheticRuntime:
    def __init__(self) -> None:
        self.input_result = _SyntheticMap()
        self.planner_result = _SyntheticMap()
        self.bridge_result = _SyntheticMap()
        self.scheduler_result = _SyntheticMap()
        self.prestart_result = _SyntheticMap()
        self.safety_result = _SyntheticMap()
        self.execution_handoff_result = _SyntheticMap()
        self.final_revalidation_result = _SyntheticMap()
        self.mode_switch_preview_result = _SyntheticMap()
        self.automatic_execution_gate_result = _SyntheticMap()
        self.execution_shadow_result = {
            "execution_shadow_status": "running_shadow",
            "execution_shadow_active": True,
            "execution_shadow_identity": "identity-" + "x" * 64,
            "execution_shadow_transaction": [
                {"operation": "observe", "physical": False, "detail": "x" * 80}
                for _ in range(8)
            ],
            "runtime_safety_safe": True,
            "runtime_safety_reasons": ["x" * 64 for _ in range(3)],
            "runtime_safety_warnings": ["x" * 64 for _ in range(3)],
            "runtime_safety_checks": [
                {"check": f"runtime_{i}", "passed": True, "detail": "x" * 80}
                for i in range(8)
            ],
            "safe_return_steps": [
                {"operation": "set_power_zero", "physical": False, "detail": "x" * 80},
                {"operation": "wait", "physical": False, "detail": "x" * 80},
                {"operation": "switch_self_consumption", "physical": False, "detail": "x" * 80},
            ],
            "execution_shadow_trace": [
                {"at": "2026-09-25T06:00:00+00:00", "event": "x" * 80}
                for _ in range(12)
            ],
            "execution_shadow_run_history": [
                {"result": "success", "detail": "x" * 96}
                for _ in range(6)
            ],
            "automatic_run_count": 10,
            "automatic_success_count": 9,
            "automatic_failure_count": 1,
        }
        self.legacy_safety_result = _SyntheticMap()
        self.action_controller_result = _SyntheticMap()
        self.control_path_result = _SyntheticMap()
        self.soc_entity_id = "sensor.battery_soc"
        self.soc_source_status = "ok"
        self.soc_percent = 68.0
        self.soc_last_updated = "2026-09-25T06:00:00+00:00"
        self.last_refresh = datetime(2026, 9, 25, 6, 0, tzinfo=timezone.utc)
        self.last_trigger = "test_fixture"
        self.refresh_count = 12345
        self.last_error = None
        self.plan_store = _SyntheticPlanStore()
        self.entry = SimpleNamespace(entry_id="test_entry")
        self.execution_shadow_store_status = "loaded"
        self.execution_shadow_store_error = None
        self.execution_shadow_store_last_saved_at = "2026-09-25T06:00:00+00:00"
        self._automatic_execution_armed = False


def test_doems_ems_recorder_payload_stays_below_10_kib() -> None:
    snapshot = _compile_function("ems_runtime.py", "DOEMSEMSRuntime", "snapshot")
    attributes = snapshot(_SyntheticRuntime())
    unrecorded = _class_unrecorded_attributes("sensor.py", "DOEMSEMSStatusSensor")

    size, encoded = _recorder_bytes(attributes, unrecorded)

    assert size <= RECORDER_BUDGET_BYTES, (
        f"sensor.doems_ems Recorder payload is {size} bytes, "
        f"budget is {RECORDER_BUDGET_BYTES} bytes. "
        "Move large arrays/checks/traces to _unrecorded_attributes or split "
        f"diagnostics before adding more recorded attributes. Payload prefix: {encoded[:300]!r}"
    )


def test_plan72_hours_recorder_payload_excludes_full_72h_plan_and_stays_below_10_kib() -> None:
    summary = _compile_function("sensor.py", None, "_plan72_summary_attrs")
    plan72 = _SyntheticMap()
    attributes = summary(plan72)
    attributes["plan"] = [
        {
            "time": f"2026-09-{25 + (hour // 24):02d}T{hour % 24:02d}:00:00+00:00",
            "price": 0.2345,
            "solar_kwh": 0.456,
            "home_consumption_kwh": 0.321,
            "charge_from_solar_kwh": 0.111,
            "charge_from_grid_safety_kwh": 0.222,
            "charge_from_grid_trade_kwh": 0.0,
            "discharge_to_home_kwh": 0.123,
            "discharge_to_grid_kwh": 0.0,
            "soc_start": 68.0,
            "soc_end": 69.0,
            "reserve_floor_soc": 14.0,
            "execution_reserve_floor_soc": 16.0,
            "action": "veiligheidsladen",
        }
        for hour in range(72)
    ]
    unrecorded = _class_unrecorded_attributes("sensor.py", "DOEMSEMSPlan72Sensor")

    assert "plan" in unrecorded
    size, _ = _recorder_bytes(attributes, unrecorded)
    assert size <= RECORDER_BUDGET_BYTES, (
        f"sensor.doems_ems_plan72_hours Recorder payload is {size} bytes, "
        f"budget is {RECORDER_BUDGET_BYTES} bytes"
    )


def test_g5_large_parity_evidence_remains_unrecorded() -> None:
    unrecorded = _class_unrecorded_attributes(
        "ems_g5_live_parity_sensor.py",
        "DOEMSG5LiveParitySensor",
    )
    assert {
        "differences",
        "golden_decision",
        "doems_decision",
    } <= unrecorded


def test_recorder_budget_is_intentionally_below_home_assistant_hard_limit() -> None:
    assert RECORDER_BUDGET_BYTES == 10_240
    assert RECORDER_BUDGET_BYTES < 16_384

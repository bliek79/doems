"""Executable R7 -> Alpha76 handoff tests with an inert battery fake.

These tests execute production handoff code extracted from the runtime AST.
They never import Home Assistant or call physical services.
"""
import ast
import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"
SOURCE = (ROOT / "ems_runtime.py").read_text()


class HomeAssistantError(Exception):
    pass


def _method(name):
    tree = ast.parse(SOURCE)
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DOEMSEMSRuntime")
    fn = next(n for n in owner.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    ns = {"HomeAssistantError": HomeAssistantError}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "<production-runtime>", "exec"), ns)
    return ns[name]


class InertAlpha76:
    def __init__(self, power=500):
        self.power = power
        self.commands = []
        self.data = {"power_w": power, "active": False}

    async def async_execute_selected_plan(self):
        self.commands.append("manual_start")

    async def async_execute_automatic_plan(self, identity):
        self.commands.append(("automatic_start", identity))
        return True

    async def async_stop(self, reason, *, emergency=False):
        self.commands.append(("stop", reason, emergency))


class ManualHarness:
    def __init__(self, valid=True, power=500):
        self.data = {"scheduler_selected_slot": 2, "scheduler_slots": {2: {"power_w": power}}}
        self.execution = InertAlpha76(power)
        self.valid = valid
        self._setpoint_handoff_observed_w = power if valid else 0
        self.verified = []

    async def _async_verify_platform_setpoint_handoff(self, power):
        self.verified.append(power)
        return self.valid


@pytest.mark.asyncio
async def test_manual_plan_executes_and_confirms_readback():
    h = ManualHarness()
    await _method("async_execute_selected_plan_verified_handoff")(h)
    assert h.execution.commands == ["manual_start"]
    assert h.verified == [500.0]


@pytest.mark.asyncio
async def test_manual_plan_mismatch_emergency_stops():
    h = ManualHarness(valid=False)
    with pytest.raises(HomeAssistantError, match="platform_setpoint_handoff_not_confirmed"):
        await _method("async_execute_selected_plan_verified_handoff")(h)
    assert h.execution.commands[0] == "manual_start"
    assert h.execution.commands[1][0] == "stop"
    assert h.execution.commands[1][2] is True


@pytest.mark.asyncio
async def test_manual_invalid_power_never_issues_battery_command():
    h = ManualHarness(power="bad")
    with pytest.raises(HomeAssistantError, match="expected_power_invalid"):
        await _method("async_execute_selected_plan_verified_handoff")(h)
    assert h.execution.commands == []


class AutomaticHarness:
    def __init__(self, valid=True, power=500):
        self.execution = InertAlpha76(power)
        self.valid = valid
        self.verified = []
        self._setpoint_handoff_observed_w = power if valid else 0
        self._automatic_execution_task = object()
        self._shutdown = False
        self.refresh_reasons = []

    async def _async_verify_platform_setpoint_handoff(self, power):
        self.verified.append(power)
        return self.valid

    def _request_fast_refresh(self, reason):
        self.refresh_reasons.append(reason)


@pytest.mark.asyncio
async def test_automatic_plan_executes_and_confirms_readback():
    h = AutomaticHarness()
    await _run_automatic_bound(h, "planner-1")
    assert h.execution.commands == [("automatic_start", "planner-1")]
    assert h.verified == [500.0]
    assert h.refresh_reasons == ["automatic_execution_terminal"]


async def _run_automatic_bound(h, identity):
    # The production nested coroutine closes over self and planner identity.
    # Bind those closure names by rebuilding it in a tiny outer function.
    source = ast.parse(SOURCE)
    owner = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "DOEMSEMSRuntime")
    parent = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == "_schedule_manual_physical_start")
    inner = next(n for n in ast.walk(parent) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_automatic")
    outer = ast.FunctionDef(
        name="make", args=ast.arguments(posonlyargs=[], args=[ast.arg(arg="self"), ast.arg(arg="identity")], vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
        body=[inner, ast.Return(value=ast.Name(id="_run_automatic", ctx=ast.Load()))], decorator_list=[]
    )
    ns = {"asyncio": asyncio, "HomeAssistantError": HomeAssistantError,
          "_LOGGER": type("Logger", (), {"warning": staticmethod(lambda *a: None), "exception": staticmethod(lambda *a: None)})()}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[outer], type_ignores=[])), "<automatic-production>", "exec"), ns)
    await ns["make"](h, identity)()


@pytest.mark.asyncio
async def test_automatic_mismatch_uses_existing_alpha76_emergency_stop():
    h = AutomaticHarness(valid=False)
    await _run_automatic_bound(h, "planner-2")
    assert h.execution.commands[0] == ("automatic_start", "planner-2")
    assert h.execution.commands[1][0] == "stop"
    assert h.execution.commands[1][2] is True
    assert h.refresh_reasons == ["automatic_execution_terminal"]

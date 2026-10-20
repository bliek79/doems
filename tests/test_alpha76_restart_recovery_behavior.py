"""Behavioral restart recovery tests against the existing Alpha76 method.

No mock Home Assistant module imports are required; the real recovery method
is compiled from its AST and called with an inert execution-state probe.
"""
import ast
import asyncio
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "custom_components" / "doems" / "ems_execution.py").read_text()


def _production_recovery():
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DOEMSExecutionController")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_recover_if_needed")
    class Logger:
        @staticmethod
        def warning(*args):
            pass
    ns = {"_LOGGER": Logger()}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "<alpha76-recovery>", "exec"), ns)
    return ns[fn.name]


class InertExecution:
    def __init__(self, *, active=False, arming=False):
        self._state = {"active": active, "auto_mode_switch_active": arming}
        self.calls = []

    async def async_stop(self, reason, *, emergency=False):
        self.calls.append(("stop", reason, emergency))

    async def async_abort_automatic_arming(self, reason):
        self.calls.append(("abort_arming", reason))


def test_interrupted_execution_uses_emergency_stop():
    probe = InertExecution(active=True)
    asyncio.run(_production_recovery()(probe))
    assert probe.calls == [("stop", "restart_recovery", True)]


def test_interrupted_automatic_arming_is_aborted():
    probe = InertExecution(arming=True)
    asyncio.run(_production_recovery()(probe))
    assert probe.calls == [("abort_arming", "restart_recovery")]


def test_idle_restart_does_not_trigger_stop():
    probe = InertExecution()
    asyncio.run(_production_recovery()(probe))
    assert probe.calls == []


def test_active_state_takes_precedence_over_arming():
    probe = InertExecution(active=True, arming=True)
    asyncio.run(_production_recovery()(probe))
    assert probe.calls == [("stop", "restart_recovery", True)]

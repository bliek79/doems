"""Exercise the real DOEMS setpoint verifier without physical HA services.

Extract only the method under test from the runtime module; no Home Assistant
imports, battery commands or live entity registry are required.
"""
import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"


def _verifier():
    source = (ROOT / "ems_runtime.py").read_text()
    tree = ast.parse(source)
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DOEMSEMSRuntime")
    method = next(n for n in owner.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_async_verify_platform_setpoint_handoff")
    method.decorator_list = []
    namespace = {
        "asyncio": asyncio,
        "dt_util": type("DT", (), {"now": staticmethod(lambda: datetime.now(timezone.utc))}),
        "_PLATFORM_SETPOINT_HANDOFF_SETTLE_SECONDS": 0,
        "_PLATFORM_SETPOINT_HANDOFF_SAMPLE_COUNT": 3,
        "_PLATFORM_SETPOINT_HANDOFF_SAMPLE_SECONDS": 0,
        "_PLATFORM_SETPOINT_HANDOFF_TOLERANCE_W": 10,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), "<readback>", "exec"), namespace)
    return namespace[method.name]


class _Probe:
    def __init__(self, samples):
        self.samples = iter(samples)
        self._setpoint_handoff_failure_count = 0

    def _read_control_power_setpoint(self):
        return next(self.samples)


def _run(samples, expected=500):
    probe = _Probe(samples)
    accepted = asyncio.run(_verifier()(probe, expected))
    return accepted, probe


def test_matching_three_samples_are_accepted():
    accepted, probe = _run([500, 505, 490])
    assert accepted is True
    assert probe._setpoint_handoff_status == "confirmed"
    assert probe._setpoint_handoff_failure_count == 0


def test_one_bad_sample_rejects_handoff():
    accepted, probe = _run([500, 512, 500])
    assert accepted is False
    assert probe._setpoint_handoff_status == "rejected"
    assert probe._setpoint_handoff_failure_count == 1


def test_unavailable_setpoint_rejects_handoff():
    accepted, probe = _run([500, None, 500])
    assert accepted is False
    assert probe._setpoint_handoff_status == "rejected"


def test_persistent_wrong_setpoint_rejects_handoff():
    accepted, probe = _run([0, 0, 0])
    assert accepted is False
    assert probe._setpoint_handoff_samples == [0, 0, 0]

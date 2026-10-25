"""R8 execution controller: gate and session lifecycle tests."""
from datetime import datetime, timedelta, timezone
import pytest
import asyncio
import functools
import inspect

def run_async(fn):
    """Run isolated async regression cases in CI without pytest-asyncio."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    wrapper.__signature__ = inspect.signature(fn)
    return wrapper
# Load the isolated R8 modules without importing the full integration package.
import importlib.util
import pathlib
import sys
import types

# Main's full pytest job intentionally does not install Home Assistant.
# Only the exception type is needed by the isolated controller unit tests.
try:
    from homeassistant.exceptions import HomeAssistantError
except ModuleNotFoundError as exc:
    if exc.name != "homeassistant":
        raise
    _ha = types.ModuleType("homeassistant")
    _ha.__path__ = []
    _ha_exceptions = types.ModuleType("homeassistant.exceptions")
    class HomeAssistantError(Exception):
        pass
    _ha_exceptions.HomeAssistantError = HomeAssistantError
    _ha.exceptions = _ha_exceptions
    sys.modules["homeassistant"] = _ha
    sys.modules["homeassistant.exceptions"] = _ha_exceptions

_COMPONENTS = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "doems"
for _pkg, _path in (("custom_components", _COMPONENTS.parent),
                    ("custom_components.doems", _COMPONENTS)):
    if _pkg not in sys.modules:
        _module = types.ModuleType(_pkg)
        _module.__path__ = [str(_path)]
        sys.modules[_pkg] = _module

_spec = importlib.util.spec_from_file_location(
    "custom_components.doems.execution_controller", _COMPONENTS / "execution_controller.py")
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
ExecutionController = _module.ExecutionController


class FakeAdapter:
    def __init__(self):
        self.starts = []
        self.stops = 0

    async def start(self, **kwargs):
        self.starts.append(kwargs)
        if not kwargs["revalidate"]():
            raise HomeAssistantError("Validation failed")
        return True

    async def stop(self):
        self.stops += 1
        return True


def build(authorized=lambda: True, revalidate=lambda _: True):
    adapter = FakeAdapter()
    return ExecutionController(adapter, authorized=authorized, revalidate=revalidate), adapter


@run_async
async def test_denied_authority_never_starts():
    controller, adapter = build(authorized=lambda: False)
    with pytest.raises(HomeAssistantError):
        await controller.start(identity="plan-1", action="laden", power_w=500,
                               target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc))
    assert not adapter.starts


@run_async
async def test_start_and_target_stop():
    controller, adapter = build()
    now = datetime.now(timezone.utc)
    await controller.start(identity="plan-1", action="laden", power_w=500,
                           target_soc=80, max_runtime_h=1, now=now)
    assert len(adapter.starts) == 1
    verdict = await controller.monitor(
        now=now + timedelta(minutes=5), soc_percent=80,
        sources_fresh=True, controller_exclusive=True,
        command_acknowledged=True, plan_identity_matches=True, safety_clear=True)
    assert verdict["decision"] == "stop"
    assert adapter.stops == 1
    assert controller.session is None


@run_async
async def test_restart_requires_verified_stop():
    controller, adapter = build()
    controller.require_restart_reconciliation()
    with pytest.raises(HomeAssistantError):
        await controller.start(identity="plan-1", action="laden", power_w=500,
                               target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc))
    await controller.stop()
    assert adapter.stops == 1
    assert controller.reconciliation_required is False


@run_async
async def test_lost_authority_triggers_stop():
    authority = {"enabled": True}
    controller, adapter = build(authorized=lambda: authority["enabled"])
    now = datetime.now(timezone.utc)
    await controller.start(identity="plan-1", action="laden", power_w=500,
                           target_soc=80, max_runtime_h=1, now=now)
    authority["enabled"] = False
    verdict = await controller.monitor(
        now=now + timedelta(minutes=5), soc_percent=60,
        sources_fresh=True, controller_exclusive=False,
        command_acknowledged=True, plan_identity_matches=True, safety_clear=True)
    assert verdict["decision"] == "stop"
    assert adapter.stops == 1


@run_async
async def test_authority_lost_during_start_stops_and_blocks_reuse():
    authority = {"enabled": True}
    controller, adapter = build(authorized=lambda: authority["enabled"])

    async def start_then_revoke(**kwargs):
        adapter.starts.append(kwargs)
        authority["enabled"] = False
        return True

    adapter.start = start_then_revoke
    with pytest.raises(HomeAssistantError, match="changed during start"):
        await controller.start(identity="plan-1", action="laden", power_w=500,
                               target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc))
    assert adapter.stops == 1
    assert controller.session is None
    assert controller.reconciliation_required is True


@run_async
async def test_unconfirmed_stop_keeps_session_and_reconciliation():
    controller, adapter = build()
    now = datetime.now(timezone.utc)
    await controller.start(identity="plan-1", action="laden", power_w=500,
                           target_soc=80, max_runtime_h=1, now=now)

    async def unconfirmed_stop():
        adapter.stops += 1
        return False

    adapter.stop = unconfirmed_stop
    with pytest.raises(HomeAssistantError, match="stop not confirmed"):
        await controller.stop()
    assert controller.session is not None
    assert controller.reconciliation_required is True


@run_async
@pytest.mark.parametrize("ack", [False, None])
async def test_unconfirmed_start_attempts_stop_and_blocks_reuse(ack):
    controller, adapter = build()

    async def start_without_ack(**kwargs):
        adapter.starts.append(kwargs)
        return ack

    adapter.start = start_without_ack
    with pytest.raises(HomeAssistantError, match="Start acknowledgement"):
        await controller.start(identity="plan-1", action="laden", power_w=500,
                               target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc))
    assert adapter.stops == 1
    assert controller.session is None
    assert controller.reconciliation_required is True


@run_async
async def test_start_exception_attempts_stop_and_blocks_reuse():
    controller, adapter = build()

    async def failed_start(**kwargs):
        adapter.starts.append(kwargs)
        raise HomeAssistantError("Device did not respond")

    adapter.start = failed_start
    with pytest.raises(HomeAssistantError, match="Device did not respond"):
        await controller.start(identity="plan-1", action="laden", power_w=500,
                               target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc))
    assert adapter.stops == 1
    assert controller.reconciliation_required is True


@run_async
async def test_cancelled_start_attempts_stop_and_blocks_reuse():
    import asyncio
    controller, adapter = build()

    async def cancelled_start(**kwargs):
        adapter.starts.append(kwargs)
        raise asyncio.CancelledError()

    adapter.start = cancelled_start
    with pytest.raises(asyncio.CancelledError):
        await controller.start(identity="plan-1", action="laden", power_w=500,
                               target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc))
    assert adapter.stops == 1
    assert controller.reconciliation_required is True


@run_async
async def test_failed_start_cleanup_does_not_clear_reconciliation():
    controller, adapter = build()

    async def failed_start(**kwargs):
        raise HomeAssistantError("Start failed")

    async def failed_cleanup():
        adapter.stops += 1
        raise HomeAssistantError("Stop failed")

    adapter.start = failed_start
    adapter.stop = failed_cleanup
    with pytest.raises(HomeAssistantError, match="Start failed"):
        await controller.start(identity="plan-1", action="laden", power_w=500,
                               target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc))
    assert adapter.stops == 1
    assert controller.reconciliation_required is True


@run_async
async def test_cancelled_start_waits_for_cleanup_completion():
    import asyncio
    controller, adapter = build()
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def cancelled_start(**kwargs):
        raise asyncio.CancelledError()

    async def delayed_stop():
        adapter.stops += 1
        cleanup_started.set()
        await cleanup_release.wait()
        cleanup_finished.set()
        return True

    adapter.start = cancelled_start
    adapter.stop = delayed_stop
    task = asyncio.create_task(controller.start(
        identity="plan-1", action="laden", power_w=500,
        target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc)))
    await asyncio.wait_for(cleanup_started.wait(), timeout=2)
    assert not task.done()
    assert controller.reconciliation_required is True
    cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert cleanup_finished.is_set()
    assert adapter.stops == 1
    assert controller.session is None
    assert controller.reconciliation_required is True


@run_async
async def test_p2_emergency_acknowledgement_preserves_audit():
    controller, adapter = build()
    controller.emergency_status.update(status="emergency_stopped", reason="old_failure",
                                       last_result="emergency_stopped",
                                       automatic_run_history=[{"result": "emergency_stopped"}])
    adapter._state = lambda key: "self_consumption" if key == "operating_mode" else "0"
    await controller.async_reset_emergency_status(automatic_armed=False, physical_test={"active": False})
    assert controller.emergency_status["status"] == "idle"
    assert controller.emergency_status["emergency_acknowledged_reason"] == "old_failure"
    assert controller.emergency_status["last_result"] == "emergency_stopped"
    assert controller.emergency_status["automatic_run_history"] == [{"result": "emergency_stopped"}]
    assert adapter.stops == 0


@run_async
async def test_p2_emergency_acknowledgement_denied_while_armed():
    controller, adapter = build()
    controller.emergency_status["status"] = "emergency_stopped"
    adapter._state = lambda key: "self_consumption" if key == "operating_mode" else "0"
    with pytest.raises(HomeAssistantError):
        await controller.async_reset_emergency_status(automatic_armed=True)
    assert controller.emergency_status["status"] == "emergency_stopped"

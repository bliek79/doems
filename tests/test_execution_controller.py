"""R8 execution controller: gate and session lifecycle tests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.doems.execution_controller import ExecutionController


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


@pytest.mark.asyncio
async def test_denied_authority_never_starts():
    controller, adapter = build(authorized=lambda: False)
    with pytest.raises(HomeAssistantError):
        await controller.start(identity="plan-1", action="laden", power_w=500,
                               target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc))
    assert not adapter.starts


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_restart_requires_verified_stop():
    controller, adapter = build()
    controller.require_restart_reconciliation()
    with pytest.raises(HomeAssistantError):
        await controller.start(identity="plan-1", action="laden", power_w=500,
                               target_soc=80, max_runtime_h=1, now=datetime.now(timezone.utc))
    await controller.stop()
    assert adapter.stops == 1
    assert controller.reconciliation_required is False


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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

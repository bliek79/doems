"""Regression tests for cross-thread R7/R9 notification scheduling."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from test_r7_runtime_boundary import load_runtime


def test_r7_worker_thread_notifications_schedule_once(monkeypatch):
    Runtime = load_runtime(monkeypatch)

    async def run():
        loop = asyncio.get_running_loop()
        calls = []
        hass = SimpleNamespace(loop=loop, async_create_task=lambda coro, name=None: asyncio.create_task(coro))
        scheduler = Runtime(hass, None, None, None, None)

        async def evaluate():
            calls.append("evaluate")
            await asyncio.sleep(0)

        scheduler.async_evaluate = evaluate
        with ThreadPoolExecutor(max_workers=2) as pool:
            await asyncio.gather(*[
                loop.run_in_executor(pool, scheduler._queue_evaluate)
                for _ in range(20)
            ])
        await asyncio.sleep(0.05)
        assert calls
        assert scheduler._task is not None
        await scheduler.async_shutdown()

    asyncio.run(run())


def test_r9_worker_thread_refresh_deduplicates_and_shutdown(monkeypatch):
    import importlib.util
    import sys
    import types
    from pathlib import Path

    def mod(name, **values):
        module = types.ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)

    mod("homeassistant", __path__=[])
    mod("homeassistant.core", callback=lambda func: func)
    mod("homeassistant.helpers", __path__=[])
    mod("homeassistant.helpers.event", async_track_time_interval=lambda *a: (lambda: None))
    mod("homeassistant.util", __path__=[])
    mod("homeassistant.util.dt", utcnow=lambda: None)
    mod("custom_components", __path__=[])
    mod("custom_components.doems", __path__=[str(Path(__file__).resolve().parents[1] / "custom_components/doems")])
    mod("custom_components.doems.execution_controller", ExecutionController=lambda *a, **k: SimpleNamespace(session=None, reconciliation_required=False))
    mod("custom_components.doems.execution_anker_adapter", AnkerExecutionAdapter=lambda *a, **k: SimpleNamespace())

    path = Path(__file__).resolve().parents[1] / "custom_components/doems/combined_execution_shadow_runtime.py"
    spec = importlib.util.spec_from_file_location("custom_components.doems.combined_execution_shadow_runtime_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def run():
        loop = asyncio.get_running_loop()
        tasks = []
        def create(coro, name=None):
            task = asyncio.create_task(coro, name=name)
            tasks.append(task)
            return task

        hass = SimpleNamespace(loop=loop, async_create_task=create)
        observer = module.DOEMSCombinedExecutionShadowRuntime(hass, SimpleNamespace(), SimpleNamespace())
        evaluations = []
        entered = asyncio.Event()
        release = asyncio.Event()
        async def evaluate():
            evaluations.append(1)
            entered.set()
            await release.wait()
        observer._evaluate = evaluate
        with ThreadPoolExecutor(max_workers=2) as pool:
            await asyncio.gather(*[loop.run_in_executor(pool, observer.refresh) for _ in range(20)])
        await asyncio.wait_for(entered.wait(), 1)
        assert len(tasks) == 1  # A burst during one active drain must not spawn another.
        release.set()
        await asyncio.sleep(0.05)
        assert evaluations
        await observer.async_shutdown()
        observer.refresh()
        await asyncio.sleep(0)
        assert len(tasks) == 1

    asyncio.run(run())

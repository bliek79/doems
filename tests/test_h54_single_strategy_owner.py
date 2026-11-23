"""H5.4: production has one economic owner, the frozen Anker Alpha84 bundle.

Historical Alpha52 pure numerical and practical solvers remain importable for
frozen tests only; changing the HA worker path to use them must fail closed.
This test never sends a battery command or mutates Home Assistant.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from test_alpha84_worker_entrypoint_parity import environment, make_inputs


ROOT = Path(__file__).resolve().parents[1]


def _argument_names_in_worker_source():
    tree = ast.parse((ROOT / "custom_components/doems/planner_72h_runtime.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_evaluate")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "calculate_plan72"]
    assert len(calls) == 1
    return {item.arg:item.value for item in calls[0].keywords}


def test_actual_worker_statically_requires_original_strategy_owner():
    keywords = _argument_names_in_worker_source()
    assert isinstance(keywords["strategy_factory"], ast.Name)
    assert keywords["strategy_factory"].id == "compute_strategy_bundle"
    assert isinstance(keywords["practical_windows"], ast.Constant)
    assert keywords["practical_windows"].value is True
    # The HA runtime must not import or call historical economics.
    runtime = (ROOT / "custom_components/doems/planner_72h_runtime.py").read_text()
    assert "_safety_schedule(" not in runtime
    assert "_trade_schedule(" not in runtime
    assert "_safety_windows(" not in runtime
    assert "_trade_windows(" not in runtime
    assert 'globals().get("compute_strategy_bundle") is not alpha84_owner' in runtime


def _source_and_kwargs(env):
    source = make_inputs(env, buy=range(4), sell=range(48, 52))
    home = [{"start":t, "energy_kwh":value} for t,value in source.home]
    solar = [{"start":t, "energy_kwh":value} for t,value in source.solar]
    prices = [{"start":t, "import_all_in":buy, "export_all_in":sell, "kind":kind}
              for t,buy,sell,kind,_minutes in source.prices]
    kwargs = dict(source.parameters)
    kwargs["now"] = source.now
    kwargs["practical_windows"] = True
    return source, home, solar, prices, kwargs


def test_production_worker_fails_closed_when_source_owner_missing_or_replaced(
    environment, monkeypatch
):
    source = make_inputs(environment, buy=range(4), sell=range(48, 52))
    original = environment.runtime.compute_strategy_bundle

    for factory in (None, lambda *a, **kw: {"fake": "alternate_strategy"}):
        monkeypatch.setattr(environment.runtime, "compute_strategy_bundle", factory)
        result = environment.runtime._evaluate(source)
        assert result["valid"] is False
        assert result["reason"] == "alpha84_strategy_source_required"
        assert result["execution_enabled"] is False
        assert result["physical_execution_authority"] is False
        assert result["timeline"] == []

    monkeypatch.delattr(environment.runtime, "compute_strategy_bundle")
    result = environment.runtime._evaluate(source)
    assert result["valid"] is False
    assert result["reason"] == "alpha84_strategy_source_required"
    monkeypatch.setattr(environment.runtime, "compute_strategy_bundle", original)


def test_approved_calculator_is_still_byte_equal_to_installed_alpha_8_10():
    original = (ROOT / "custom_components/doems/planner_72h.py").read_bytes()
    git_sha = hashlib.sha1(
        b"blob " + str(len(original)).encode() + b"\0" + original
    ).hexdigest()
    # Chapter 7 previously approved hash; H5.4 may guard the HA worker,
    # but may never rewrite the older approved numerical/model algorithms.
    assert git_sha == "751ae0ac98b454c6f7290700a2d783e571ae7c51"


def test_actual_home_assistant_worker_never_calls_retired_economic_search(
    environment, monkeypatch
):
    runtime = environment.runtime
    original_function = runtime.calculate_plan72
    model = __import__(original_function.__module__, fromlist=["calculate_plan72"])

    def forbidden(*_args, **_kwargs):
        raise AssertionError("H5.4 regression: retired DOEMS strategy was reached")

    for name in ("_safety_schedule", "_trade_schedule",
                 "_safety_windows", "_trade_windows"):
        monkeypatch.setattr(model, name, forbidden)

    source, home, solar, prices, kwargs = _source_and_kwargs(environment)
    result = runtime._evaluate(source)
    assert result["valid"] is True, result["reason"]
    assert result["action_window_search"]["method"] == (
        "alpha84_energy_allocation_then_grouping")
    assert result["trade"]["search_method"] == "alpha84_best_pair"
    assert result["action_window_search"]["source_candidate_count"] == 2
    assert result["slot_count"] == 288
    assert result["execution_enabled"] is False
    assert result["physical_execution_authority"] is False
    # The pure calculator remains unchanged for historical tests; the
    # Home Assistant boundary is the mandatory Alpha84-only guard.
    raw = original_function(
        home, solar, prices,
        strategy_factory=runtime.compute_strategy_bundle,
        **kwargs
    )
    assert raw["valid"] is True
    assert raw["action_window_search"]["method"] == (
        "alpha84_energy_allocation_then_grouping")

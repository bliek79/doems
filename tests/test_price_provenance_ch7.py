"""Real Plan72 quarters -> Bridge -> writer -> durable slot price provenance."""
import asyncio
from copy import deepcopy
import importlib
from types import SimpleNamespace

import pytest

from test_action_bridge import fixture_plan, build
from test_plan72_model import NOW
from test_plan_store_persistence_ch7 import store_module


def candidate_for(labels):
    plan = fixture_plan(kinds=['safety_charge'] * 2, duration_minutes=15 * len(labels))
    # The second action starts two hours later. Neighbouring rows must not
    # contaminate its metadata, including the row immediately at its hard end.
    for row in plan['timeline']:
        row['kind'] = 'unrelated'
    for row, label in zip(plan['timeline'][8:], labels):
        row['kind'] = label
    before = deepcopy(plan)
    result = build(plan)
    assert result['valid'] and result['candidates'][1]['valid']
    assert plan == before
    return plan, result['candidates'][1]


@pytest.mark.parametrize('labels,expected,known', [
    (['known'], ['known'], True),
    (['known_pt15m'] * 3, ['known_pt15m'], True),
    (['forecast_hour'] * 3, ['forecast_hour'], False),
    (['known_pt15m', 'forecast_hour', 'known_pt15m'], ['known_pt15m', 'forecast_hour'], False),
    (['known_hourly_fallback', 'known_pt15m'], ['known_hourly_fallback', 'known_pt15m'], True),
    ([None, ''], ['missing'], False),
    (['unclassified'], ['unclassified'], False),
])
def test_actual_source_labels_survive_writer_reconciliation_and_restart(store_module, monkeypatch,
                                                                      labels, expected, known):
    async def scenario():
        monkeypatch.setattr(store_module.dt_util, 'now', lambda: NOW)
        monkeypatch.setattr(store_module.dt_util, 'utcnow', lambda: NOW)
        plan, candidate = candidate_for(labels)
        assert candidate['price_sources'] == expected
        assert candidate['all_prices_known'] is known
        writer_module = importlib.import_module('store_ch7_test.plan_store_writer')
        bridge = SimpleNamespace(snapshot=dict(valid=True, status="ready", source_plan_generation=1,
            source_input_fingerprint='a' * 64, eligible_candidates=[candidate]))
        store = store_module.AnkerEmsPlanStore(None, 'id')
        writer = writer_module.PlanStoreWriter(None, store, SimpleNamespace(snapshot=plan), bridge)
        await writer._sync()
        assert writer.status == 'ready', writer.last_reason
        saved = store.get_plan(1)
        assert saved['price_sources'] == expected
        assert saved['all_prices_known'] is known
        revision = store.revision
        await writer._sync()
        assert store.revision == revision
        # Mutating a caller's candidate must not mutate the persisted slot.
        candidate['price_sources'].append('caller_mutation')
        assert store.get_plan(1)['price_sources'] == expected
        restored = store_module.AnkerEmsPlanStore(None, 'id')
        restored._store.data = deepcopy(store._store.data)
        await restored.async_load()
        assert restored.get_plan(1) == saved
    asyncio.run(scenario())


def test_price_only_revision_updates_existing_automatic_slot(store_module, monkeypatch):
    async def scenario():
        monkeypatch.setattr(store_module.dt_util, 'now', lambda: NOW)
        monkeypatch.setattr(store_module.dt_util, 'utcnow', lambda: NOW)
        writer_module = importlib.import_module('store_ch7_test.plan_store_writer')
        plan, first = candidate_for(['forecast_hour'])
        _, second = candidate_for(['known_pt15m'])
        assert first['planner_identity'] == second['planner_identity']
        assert first['planner_signature'] != second['planner_signature']
        store = store_module.AnkerEmsPlanStore(None, 'id')
        bridge = SimpleNamespace(snapshot=dict(valid=True, status="ready", source_plan_generation=1,
            source_input_fingerprint='a' * 64, eligible_candidates=[first]))
        writer = writer_module.PlanStoreWriter(None, store, SimpleNamespace(snapshot=plan), bridge)
        await writer._sync()
        revision = store.revision
        bridge.snapshot['eligible_candidates'] = [second]
        await writer._sync()
        assert store.revision > revision
        assert store.get_value(1, 'price_sources') == ['known_pt15m']
        assert store.get_value(1, 'all_prices_known') is True
    asyncio.run(scenario())

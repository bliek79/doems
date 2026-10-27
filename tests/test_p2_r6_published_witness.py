"""Non-actuating provenance tests for published, genuine R6 candidates."""
from types import SimpleNamespace

from custom_components.doems.automatic_slot_bridge import DOEMSAutoSlotBridge


def bridge_with_published_proposal():
    proposal = {
        "planner_identity": "r6:slot", "planner_signature": "generation-12",
        "origin": "automatic_72h_planner", "action": "laden",
        "power_w": 500.0, "target_soc": 80.0,
        "start_time": "2026-10-27T12:00:00+00:00",
        "planned_end_time": "2026-10-27T12:15:00+00:00",
    }
    bundle = {"planner_published_generation": 12}
    planner = SimpleNamespace(bundle_snapshot=lambda: bundle, _generation=12)
    bridge = object.__new__(DOEMSAutoSlotBridge)
    bridge.planner = planner
    bridge._shutdown = False
    bridge._manual_pending = False
    bridge._manual_serial = 3
    bridge._published_serial = 3
    bridge._published_bundle = bundle
    bridge._published_proposals = (proposal,)
    bridge.last_result = {"status": "ready"}
    return bridge, planner, proposal


def test_exact_published_r6_identity_is_read_only_witness():
    bridge, planner, proposal = bridge_with_published_proposal()
    witness = bridge.verified_published_candidate(dict(proposal))
    assert witness == proposal
    assert witness is not proposal
    witness["power_w"] = 999
    assert bridge.verified_published_candidate(dict(proposal))["power_w"] == 500.0


def test_published_generation_superseded_revokes_witness():
    bridge, planner, proposal = bridge_with_published_proposal()
    planner._generation = 13
    assert bridge.verified_published_candidate(dict(proposal)) is None


def test_manual_edit_revokes_published_witness():
    bridge, planner, proposal = bridge_with_published_proposal()
    bridge._manual_serial = 4
    assert bridge.verified_published_candidate(dict(proposal)) is None


def test_candidate_replacement_blocks_stale_identity():
    bridge, planner, proposal = bridge_with_published_proposal()
    altered = {**proposal, "planner_signature": "changed"}
    assert bridge.verified_published_candidate(altered) is None


def test_duplicate_published_identity_not_accepted():
    bridge, planner, proposal = bridge_with_published_proposal()
    bridge._published_proposals = (proposal, dict(proposal))
    assert bridge.verified_published_candidate(dict(proposal)) is None


def test_source_bundle_replacement_revokes_witness():
    bridge, planner, proposal = bridge_with_published_proposal()
    bridge.planner = SimpleNamespace(
        bundle_snapshot=lambda: {"planner_published_generation": 12}, _generation=12
    )
    assert bridge.verified_published_candidate(dict(proposal)) is None

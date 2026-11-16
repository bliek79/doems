# DOEMS 3.0 — hoofdstuk 8 / Alpha84 planner parity: verified recovery checkpoint
Date: 2026-11-16. Status: **INCOMPLETE — DO NOT RELEASE**.

## Source identities independently verified
- DOEMS released code: tag `v0.3.0-alpha.8.4` at commit `95cc001d99b5951a02ca199dcbc34f13a7ff17d2`.
- Original Anker EMS source: tag `0.0.1-alpha.84` at commit `6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d`.
- Recovery branch: `doems3-alpha84-planner-parity-recovery-20261116`, created from the released DOEMS Alpha 8.4 commit. It is NOT the previous local repair branch.
- CI source-bundle run `43861096913`: successful. Artifact `14221984561` (`doems3-parity-recovery-source`) contains both source trees, with reference commit verified. Artifact expires after 7 days.
- Previous **local-only** commits `d5b0c52`, `46833e4`, `c5524a3`, `c0291e8`, and `da07656` were not found on GitHub. No claim is made that these changes were reconstructed.

## Proven unresolved strategy mismatch
The released Plan72 runtime's `_evaluate` calls `calculate_energy_need`, then `calculate_plan72(..., practical_windows=True)`. That route invokes `_safety_windows` then `_trade_windows`, and only subsequently `_group_action_windows`. The frozen original Alpha84 uses safety-energy allocation before action-window construction and selects a single best chronological trade pair in its Preview. Grouping quarters afterward is not proof of equivalent decisions.

The previous document's same-input synthetic comparison remains unclosed:
- Safety: Alpha84 2 candidates / 8.847 kWh; DOEMS Alpha 8.4 17 candidates / 7.719833 kWh.
- Trading: Alpha84 buy/sell 3.2 kWh; DOEMS buy 0 and sell 2.647667 kWh.
These are historical synthetic fixtures, not live forecasts. They were not rerun against a completed repair in this recovery.

## Verified gates on current recoverable baseline
- Original released Alpha 8.4 validation run `43603336758`: success; publication run `43603613484`: success.
- Original release asset `doems.zip` SHA256 `fae2ecb978c34088b83378fadce6a25290ed9674ce15d1d7d82c691433207000`.
- The original CI Python 3.13 artifact reports 876 passes (baseline **only**).
- Targeted local baseline tests: `pytest -q tests/test_alpha84_safety_strategy.py tests/test_alpha84_full_chain_grouping.py`: 8 passed.
- The complete local test collection is blocked by unavailable `voluptuous`; Python 3.12 is not installed in the recovery runner.
- No functional full-chain parity gate, new Python 3.12/3.13 matrix, release package verification, or live validation has passed for the intended repair.

## Unresolved acceptance scope
Keep **all H8-01 through H8-19 OPEN** pending criterion-specific evidence. In particular, protected manual/due/active plan energy must be included *before* automatic allocation; mixed-purpose safety/trade contract must be resolved; responsibilities of original projection, DOEMS simulator and Bridge must be proven on the active worker/factory route; all 288 quarter-specific prices, equal-price volumes, tie-breaks, partial quarters and execution buffer must be checked. Keep Plan72 as the only full SOC route and preserve identity/signature/generation/fingerprint/revision checks, timing and hard ends. Scheduler's original order is due scheduled first, oldest start, then slot number; manual slot protection belongs to Store.

Do not silently turn red functional checks green by changing expected output or source hashes. Review freeze hashes only after approved code changes and passing strategy comparisons. Preserve all existing entity IDs/unique IDs, three persistent slots, and the dashboard name DOEMS Planner. `physical_execution_authority=false`; `execution_enabled=false`; no Home Assistant or main-branch modifications.

Gas-price source failure, accepted trade-route diagnosis, Anker capacity `state_class` issue and unproven B.R.I.C.K. involvement remain separately OPEN.

## Recovery required
To resume **exactly** from the prior point, provide a Git bundle/archive of the prior local-only repair branch at `da07656` (including uncommitted changes, if any). Without it, the planner changes must be independently recreated and full-chain verified from the two checked-out source trees. Never publish a repair release before the entire functionality gate and the Python 3.12/3.13 release gates are green. No new installable version has been issued.

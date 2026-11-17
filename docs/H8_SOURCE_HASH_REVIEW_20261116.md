# H8 review — reviewed source fingerprint changes, 16 November 2026

## Decision and scope

Reviewed implementation: local recovered source `491e6e9e1aab80c06d85840ee4b77b4f88ff1e46`, descended from immutable published Alpha 8.4 `95cc001d99b5951a02ca199dcbc34f13a7ff17d2`. New release candidate version: `0.3.0-alpha.8.5` (not tagged, not published).

These are Git blob SHA-1 identifiers **of source**, not safety or forecast hashes. The three failing tests did not show three distinct functional bugs. On the original candidate, 32 paths were protected: exactly 6 deliberately changed and 26 stayed byte-identical. In `tests/test_ch7_algorithm_regression.py`, 4 guarded AST nodes changed while 15 remained equal; `_Model.simulate` was previously unguarded and is now separately frozen following inspection.

**Crucial project requirement:** original Anker EMS and DOEMS use different live forecast inputs; identical physical forecasts, SOC predictions, energy totals and exact live actions are NOT a required cross-project comparison. The shared requirement is **same strategy/role division**, tested with normalized same-input fixtures while accounting for 60-minute/15-minute resolution and the 2-minute execution preparation time. No forecast-equality gate was added.

## Protected source fingerprint diff

| Source | Published alpha.8.4 SHA-1 | Reviewed H8 candidate SHA-1 | Reviewed change |
|---|---|---|---|
| `custom_components/doems/planner_72h.py` | `4ec0b7ab854d068ad82fa0f8ef73a492ef494233` | `4ee35d293f9eb664539e3cbfb8b5d0213a36c639` | Use Alpha84 strategy factory on active 288-quarter Plan72; protected allocation; mixed-source accounting; safe projection; target limits. |
| `custom_components/doems/planner_72h_runtime.py` | `2aefbc82546946af556f4740b2387a2dfbd88675` | `f9a23be93ad239c9a17fb58fd619ca9628688c80` | Connect unchanged Plan72 worker entrypoint to reviewed Alpha84 strategy bundle. |
| `custom_components/doems/planner_action_bridge.py` | `e365e4f413c0fea4868a0c8835fefdebdfc5bf92` | `79cfbc8053710e0108f02407811fcea083f39df1` | Accept mixed charge purpose; independent attribution; do not wrongly block valid follow-on actions. |
| `custom_components/doems/plan_store.py` | `d8400b8006f1857023a37aec4fd18c034456dd09` | `b6dfec3b0b5a2070167a7d107acaa6320a76c6a8` | Persist and reset mixed safety-quarter metadata without new public entities. |
| `custom_components/doems/plan_store_writer.py` | `2528beca1092d5eb2056c05dea34d0396179bc99` | `44b6cda5e07f04957f4958d3ef08df92ec29e037` | Transfer mixed source-safety allocation into the three persistent slots. |
| `custom_components/doems/plan_store_adapter.py` | `6a4f429f432c7771803dde65d16ebf4f414c7b52` | `d4b4ae38cd309c5cb8538e89477cfb941da580d7` | Replay stored mixed sources and protect due and active command energy. |

Other 26 locked source files retain their exact original blob hashes. Entity-defining files, `manifest`/`const` except new candidate version and existing Scheduler code are unchanged. This review does not certify live installation or resolve unrelated open points.

## Independent evidence and lifecycle controls

- GitHub CI run `43914837429`: 917 functional tests passed on Python 3.12 and 917 on Python 3.13; three older fingerprint/release gates failed before this review.
- Tests cover frozen exact Alpha84 60-minute port, original best chronological pair with equal and varying quarter prices, grouping complete safety chain, handoff/energy limits, active `Plan72Inputs` worker route, mixed flows across persistent Store, manual priority and no physical authority.
- Safety fixture: two candidate windows, reserve satisfied, zero remaining safety need; genuinely bounded first command remains `limited` and second candidate survives. Hourly Alpha84 and quarter DOEMS energy/SOC timelines may differ by resolution; this is not evidence of a different live forecast bug.
- `tests/test_ch7_algorithm_regression.py` keeps 15 identical reviewed node digests and freezes 4 changed reviewed ones. `_Model.simulate` has its own reviewed AST hash now.
- Every published Alpha8.4 tag and release remains immutable. The reviewed source fingerprints and incremented candidate version belong **only** to potential Alpha8.5, never retrospectively to Alpha8.4.

## Publication state

These candidate hashes are approval of the **identified source changes**, not a substitute for the full CI/package verification or production live acceptance. Do not release until both Python versions complete cleanly under the new candidate, the package SHA/provenance check matches its source commit, and all applicable H8 acceptance criteria and non-strategy release gates are reviewed.

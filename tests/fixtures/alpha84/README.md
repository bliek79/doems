# Frozen Alpha84 strategy oracle

`planner_preview.py` is byte-for-byte from
`bliek79/dummy-os-anker-ems`, tag `0.0.1-alpha.84`, commit
`6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d`.
SHA-256: `f7f453c6f48dd72514604e2367c69cdefc4fdadad6c7004d5f38647aecb3eb38`.
The upstream LICENSE is included unchanged.

This is a test-only oracle, excluded from the integration release archive.
Tests supply the same battery capacity, technical minimum and reserve to both
implementations. Only HA time utilities and relative configuration imports are
replaced during isolated loading. The strategy code is executed unchanged.

The earlier selected-decision checks do NOT establish planner equivalence.
The full-chain differential check must also compare energy, SOC and all action
candidates. Hourly inputs can be divided uniformly into quarters to avoid
confounding input resolution with strategy. Deviations are failures to
investigate, not automatically excused by the different internal resolution.

## Scheduler oracle (chapter 8)

`scheduler.py` is also byte-for-byte from the same Alpha84 commit.
Git blob: `e95a7354cab59464a573f20b154fbc63fbd9de11`.
SHA-256: `d8b05058215667e33f721e2a3ee362318e9bd2ccfdbdddfcb5253422e500faf7`.
Only HA time utilities and the Store/constant imports are supplied by test doubles.
The entire evaluator is executed unchanged; its unused slot_status helper is not called.

## Full-chain grouping oracle (Alpha 8.4)

`planner_action_bridge.py` is byte-for-byte from the same Alpha84 commit.
SHA-256: `17488870d97fbebb8cb9611da171df6bac2b16d2b7f0030cf649f64c05c47162`.
The complete Bridge runs with only HA utilities and configuration constants
supplied by the test. The comparison precedes its three-slot preview and checks
duration, rounded power, allocated energy and command target at source precision.

## Complete planning-chain oracle (2026-11-15)

The following additional files are unchanged from the same Alpha84 commit:

- `energy_need.py`: SHA-256 `9d7dd824a0f9e5cb3835705326b4037b1ef45e9b549a17d138bb859cd99e9864`.
- `planner_72h.py`: SHA-256 `71f6247a898ec8c1ffcf765534c83d485c6386fe8ccbdfcc465efa75c632be34`.

Run `python scripts/compare_alpha84_planners.py --output build/alpha84-planner-parity.json`.
Exit 1 means the implementations differ. Passing the harness unit tests does
not override that result. The frozen source supplies the expected result;
DOEMS output must never be used to rewrite that expected result.

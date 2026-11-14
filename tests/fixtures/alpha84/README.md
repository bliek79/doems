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

Compare decisions (solar priority, cheapest feasible charging, chronological
reserve deadlines and inability to borrow energy from the future), not exact
hourly/quarterly trajectories: DOEMS retains its required 288 quarters, disjoint
physical flows, two-minute preparation and integer 10 W command setpoints.

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

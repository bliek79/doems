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

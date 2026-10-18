# DOEMS R8: independent execution acceptance contract

Status: implementation work branch; **not permission to actuate the battery**.

## Source of truth
- Preserve the July Home Assistant packages' functional behavior (notably package 34, manual actions and downstream planning).
- Anker EMS is built on those packages; inspect it for technical command and recovery patterns, not as an alternative functional specification.
- Preserve R7 Manual, Automatic and Combined behavior and native 15-minute / 72-hour / 288-slot timelines.
- Do not create a second planner.

## Existing release evidence (0.2.0-alpha.8.0.5)
- `execution_runtime.py`: read-only supervisor, `_physical_adapter=None`, `_control_entities={}`, `physical_execution_enabled=False`, `execution_authority=False`.
- `execution_anker_adapter.py`: gated start and safe_return operations, not wired into the supervisor.
- `execution_control_path.py`: observation only; does not grant authority.
- `execution_model.py`: fail-closed lifecycle evaluation.

## Implementation acceptance requirements
1. Independently identify and validate actual Home Assistant Anker command entities, accepted option strings, direction conventions and acknowledgements. Never infer command entities from measurement sensors.
2. Provide exclusive control ownership fencing against the existing Anker EMS; no concurrent command sources.
3. Final-revalidate R7 selection, planner identity, lifecycle, start window, safety, battery SOC and source freshness immediately before each potentially energizing command.
4. Add bounded start, mode/readback confirmation, monitoring, target/runtime stop, failure stop, safe return and durable restart reconciliation.
5. Ensure command retries cannot replay an outdated or expired plan; fail closed on missing acknowledgement or controller conflict.
6. Exercise regression tests for all three manual actions, Manual precedence, Automatic promotion, Combined, restart, stale inputs, loss of connection, target reached and safe return.
7. Keep physical authority **disabled by default**. A software release is not authorization to turn on battery actuation in a user's installation.
8. Publish only after tests/CI pass; record tag/commit and live-validation status in the routebaseline.

## Release gate
No physical execution release may claim completion until the battery-specific command contract is verified and the tests demonstrate start, stop, acknowledgement, fault recovery and exclusive ownership. An open implementation branch is not a release.

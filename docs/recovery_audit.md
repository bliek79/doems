# DOEMS recovery audit 24 October 2026

## Scope and provenance

Recovery starts from PR #105, head 86affccd8823d453ef071a067e3eb436547e79a1.
Main was 4384d90c7c9c4b26808edb239ada3baf7d17a6b1. The canonical Combined
P0 source is 8cdb84f9d658b2cd6bb6648ef3d61d68a6f34038.

The five gates in PR #105 are branch/conflict review, regression and safety
tests, release/HACS provenance, preservation of published tags with a new patch
version, and routebaseline followed by dashboard work only when needed.
No Home Assistant configuration, services or live device state are changed.

## Branch and conflict disposition

The complete remote inventory is in recovery_branch_audit.json: 181 actual
branches (symbolic origin/HEAD excluded), 77 covered by the ancestry of main,
recovery or P0 and 104 historical or alternative tips retained without merging.
Every entry records its SHA, ahead/behind counts, differing file count and a
SHA256 of its file-difference inventory. This is a repository history and file
inventory, not a claim that every historical variant has been behavior-tested.
Existing branches and 110 pre-existing tag refs are retained.

Main and recovery diverged by 231 and 299 commits. A local merge exposed 20
conflicting paths after P0 integration. Resolution keeps the reset R9 entry
points, plan store, entities, selectors, translations and controller adapter.
The historical Alpha76 EMS runtime, its separate planner bridge and its
version-pinned historical tests are superseded by reset R9, rather than wired
alongside Combined. Their original content remains in main history, branches
and published tags. This intentionally does not restore the old second EMS
controller or its public entities into the reset runtime.

Main-only fixes reviewed against the reset implementation:

- Solar's quarter-roll notification is ported exactly: publish cached rolling
  data each quarter without additional Open-Meteo requests.
- Main's twelve execution-controller tests are retained and pass against the
  reset controller. The P0 adapter adds the self_consumption start guard.
- Main's R8 Manual/Automatic/Combined entity restoration is superseded by the
  reset planner entities and migration contracts, exercised by R3/R5/R6/R7 tests.
- Main's legacy presence/away EMS surface and historical Alpha76 planner
  variants remain historical; they are not dependencies of reset R9.
- Recovery's Prices DST estimate and EnergyZero startup-retry cancellation,
  per-array Solar performance and actual-quarter validation remain present.

P0 is included with one shared controller, Combined-only physical plan
validation, configured actuator mapping and default-disabled authority.
Dynamic power caps remain deferred under the 23 October routebaseline decision.

## Executed local checks

Python 3.13.16 with Home Assistant 2026.2.3: 289 tests passed. The complete
suite covers Manual/Automatic/Combined, manual priority, quarter contracts,
three-slot synchronization, persistence, promotion, expiry, source blocking,
SOC policy, thread notifications, controller authorization and reconciliation.

Seventeen added behavioral tests execute Combined -> real ExecutionController
-> real AnkerExecutionAdapter against simulated Home Assistant services. They
verify charge/discharge, 60-second control stability, command/direction/power
readback, one start per active session, disabled/nonexclusive authority,
missing SOC, reserve floor, blocked planner, power above 3500 W, rejected
setpoint, missing acknowledgement, quarter rollover, slot revision, lost
readback, authority revocation, restart cleanup and stop failure fencing.
These tests are not live battery measurements.

Five added release-contract tests reject version drift, wrong release tags,
stale archives and unexpected archive contents, and verify deterministic ZIPs.
Integration setup, config_flow, sensor, binary_sensor, number, select and
datetime modules import successfully with the stated Home Assistant package.
Compile checks cover integration and release scripts.

## Release controls

Version 0.2.0-alpha.9.5 is consistent in manifest and const. A new validated
workflow runs the full suite on pull requests and main. Publishing is limited
to a successful push to main after validation. Existing tags and releases are
refused. The release points to the tested commit. The approved icon hash is
checked. The HACS asset contains only the integration, at ZIP root, byte-matched
to tested source. SHA256SUMS is verified before publication and after download;
post-publication checks also compare the tag target with the tested SHA.

The old standalone R9 publisher is removed to prevent bypass of the full
suite. HACS uses doems.zip and hides default-branch installation. Older release
objects and tag refs are not edited.

## Verification limits

No Home Assistant instance is installed, restarted or reconfigured. Live HACS
installation provenance and physical charge/discharge remain unverified.
No physical authority is enabled by this recovery. The disarmed release is
not evidence that P0 live activation or every historical branch is validated.
Repository publication and remote CI results must be recorded separately after
they have completed; local checks alone do not establish those results.

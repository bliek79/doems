# DOEMS v0.3.0-alpha.8.5 — Chapter 8 Alpha84 strategy restoration (candidate)

**STATUS: Candidate only. No public release is created by this file.**

## Goal
Bring DOEMS's planning decision rules and responsibilities into line with the original Anker EMS `0.0.1-alpha.84` while preserving DOEMS's own forecast and distinct 15-minute prices. Different live forecasts may and should lead to different actions.

## Changed
- Original Alpha84 energy need, Preview and 72-hour strategy integrated with the active DOEMS Plan72 factory.
- Manual/due/active commitments incorporated ahead of automatic source allocation.
- Full contiguous quarter safety allocation grouped before selection for three slots; no hourly price averaging.
- Mixed safety/trade charge represented by one physical command while keeping independent energy attribution across Plan Store restoration.
- Native projection respects the original 2-minute preparation buffer, reprojects command SOC targets, and reports bounded commands truthfully.
- Original scheduler and Store priority responsibilities preserved; identical scheduler status does not trigger new planning.

## Unchanged
- 72-hour horizon / 288 quarters; persistent 3 slots; existing entity IDs and unique IDs.
- `physical_execution_authority=false` and `execution_enabled=false`. No Home Assistant modification.
- Published `v0.3.0-alpha.8.4` tag, checksum and source remain immutable.

## Validation scope before any release
- Frozen original Alpha84 source comparisons and independent native/worker/Bridge/Store tests.
- Exact reviewed H8 Python source and AST SHA values (see `docs/H8_SOURCE_HASH_REVIEW_20261116.md`).
- Full Python 3.12/3.13 matrix, full package/provenance checks, CI and release approval.
- Live Home Assistant checks remain required after installation; no live pass claimed here.

Non-planner defects (EnergyZero gas source, Anker battery-capacity `state_class`, B.R.I.C.K. hypothesis) remain separate and unresolved.

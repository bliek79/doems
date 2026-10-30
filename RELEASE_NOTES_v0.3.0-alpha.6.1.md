# DOEMS 3.0 — v0.3.0-alpha.6.1 — Automatic Action Bridge

Chapter 6 translates the existing Alpha 5.3 Plan72 action windows into validated automatic action candidates. It remains observational.

## Added
- Three sensors: Action Bridge Status, Action Candidates and Action Slot Preview; one binary sensor: Action Bridge Valid. Created with Plan72 enabled; no extra configuration required.
- Exact `quarter_windows_v1` adaptation: preparation, power, times, energy and reached target SOC are retained from the same Plan72 calculation. No second preparation deduction or route calculation.
- Per-candidate validation against source segments, source signature, bounds, AC energy and battery SOC. Total battery AC energy remains separate from grid/PV/home contributions.
- Alpha84 chronological prefix: a valid bounded charge discloses its shortfall without automatically blocking successors; a truly invalid candidate holds its tail while preserving earlier eligible candidates.
- Stable candidate identity separate from revision signature and Plan72 generation/input fingerprint/calculation timestamp.
- Complete candidate list and overflow; preview of the first three eligible actions assuming free capacity. This preview does not assign persistent slots.
- Automatic invalidation when Plan72 recalculates or loses valid input. Limited source routes expose safety recovery candidates while holding economic actions.

## Preserved
Energy Need, both Plan72 modules, forecasts, prices, configuration and all 74 existing entities retain their Alpha 5.3 implementation. Four entities are added, bringing the expected enabled development monitor total to 78. Physical execution authority is false.

Persistent slots, manual plan management, Scheduler, safety/start authorization and physical commands belong to later chapters. No main merge or existing tag replacement is part of this release.

## Validation
The release workflow runs the full test suite on Python 3.12 and 3.13 before publication. Source protection checks freeze all Alpha 5.3 component files except the three entity/runtime registration files and public version declarations. Targeted regressions include real safety/trading windows, full-route command replay, preparation, bounded-charge third-candidate recovery, invalid chronology, mixed energy, provenance, stale input and runtime lifecycle.

`doems.zip`, `SHA256SUMS.txt` and `RELEASE_PROVENANCE.json` identify the exact tested commit. Installation and Home Assistant live validation remain to be performed after publication; no physical validation is claimed.

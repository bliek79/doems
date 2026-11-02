# DOEMS 3.0 alpha.7.5 — Plan Store price provenance

The live chapter-7 slot check showed empty `price_sources` and
`all_prices_known: false` for every automatic plan. The Action Bridge did not
derive these fields from the Plan72 source quarters, and the slot writer did
not forward them to the persistent store.

## Fixed

- Derive price provenance from the validated quarters belonging to each exact
  action window, including windows covering multiple quarters.
- Preserve the native source labels and their first-occurrence order, without
  duplicates. Known PT15M and known hourly-fallback labels remain distinguishable.
- `all_prices_known` is true only for a nonempty set of exclusively `known` or
  `known_*` labels. Forecast, missing and unclassified sources remain false.
- Missing/empty source labels are explicitly reported as `missing`; they are
  never silently treated as forecast or known prices.
- Forward both fields through the writer to the existing persistent slot fields.
- Include metadata in the existing Bridge signature so a change of price source
  refreshes a revisable automatic slot even when its action identity is unchanged.

## Verification

Eight additional executable integration scenarios cover known, forecast, mixed,
missing and unclassified sources, exclusion of neighbouring quarters, actual
Bridge-to-writer-to-store propagation, reconciliation without redundant writes,
price-only updates, caller isolation and restoration after restart.
The release validator freezes the reviewed Bridge source and updates the writer
blob digest. Existing Plan72 algorithm digests and source hashes are unchanged.
Publication requires the complete Python 3.12 and 3.13 suites and release checks
in GitHub Actions to pass.

## Scope

This is a price-metadata repair only. It does not change action selection,
small-action filtering, powers, energy flows, SOC calculations, slot ownership,
entity IDs, unique IDs, dashboards or physical execution authority. Existing
tags are retained. No Home Assistant installation is modified.

After installation, repeat chapter-7 test 2 and inspect `price_sources` and
`all_prices_known` on the refreshed automatic slots. Live validation is still
open; the separate Alpha84 small-action threshold remains outside this release.

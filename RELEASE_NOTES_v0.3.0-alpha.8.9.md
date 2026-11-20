# DOEMS v0.3.0-alpha.8.9 - H5.1 Alpha84 safety selection repair

**Observer-only pre-release.** Based on the immutable, published
v0.3.0-alpha.8.8 commit 041924b875e75a561defb0858df350b0ebe14b63.

## Fixed - chapter 5.1
- Restore exact Anker EMS Alpha84 cheapest-feasible **hourly safety energy
  selection** when the 288 native input quarters are lossless expansions
  of 72 equal hourly energy and import price observations.
- Transfer the original hour's requested stored battery energy into its
  four quarters without modifying the frozen 60-minute strategy.
- Maintain native separate 15-minute tariff prices and previously reviewed
  continuous physical windows whenever there is genuine intra-hour input
  variation; do not average different quarter tariffs.
- Preserve six decimals of native quarter safety energy at the Preview ->
  Plan72 boundary and exclude causally irrelevant future tariff changes
  from already-required safety choices.

## Verified development baseline
The byte-verified original Alpha84 versus identical-source comparison
for safety_valley changed from 15 mismatching safety allocation fields
to **zero**; all 72-hour choices are checked against frozen source code.
Full CI at development commit 9e635c988121ccb8b8dcee5974181c79dfb49ba8
passed 947 tests on each of Python 3.12, 3.13 and 3.14. The release
branch separately reruns the full suite, H5.1 hard parity gate and
package-source provenance before publication.

## Preserved
- Already published alpha.8.8 Solar Forecast Remaining Today sensor.
- Existing Forecast, Prices, Action Bridge, Plan Store, Scheduler,
  public entity IDs, three-slot model and manual priorities.
- Historical releases/tags and GitHub main.

## Not approved by this release
- Remaining H5.2/H5.3/H5.6 and H6-H8 differences or live acceptance.
- Equality of all physical SOC/time projections: two SOC field
  differences remain in the controlled source comparison.
- Firing actual battery commands; physical_execution_authority and
  execution_enabled remain false.
- Changes to Home Assistant settings or installed integration.

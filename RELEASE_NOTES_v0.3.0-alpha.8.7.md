# DOEMS v0.3.0-alpha.8.7 — Contiguous safety-window planning (candidate)

**Status: development candidate; no published release and no Home Assistant update.**

## What actually changes
Alpha 8.6 corrected a physical reserve shortfall *after* source safety decisions.
However, the 15-minute source adapter could still allocate scattered cheap
quarters and only then try to group them. Alternating tariffs that differ by
EUR 0.005/kWh generated three distinct grid-charge commands, even though the
same safety demand had a feasible single continuous window.

In the 15-minute Alpha84 safety allocation itself, the cheapest-feasible-window
decision now evaluates complete contiguous executable windows **before**
emitting source quarters or three Store slots:

- Candidate windows can start/end on any of 288 quarter boundaries; no invented
  fixed minimum 30- or 60-minute action duration.
- Every distinct import price enters the actual candidate window energy cost;
  prices are **not** converted to average hourly market prices.
- Existing 2-minute physical start preparation, 100W minimum and existing
  12-hour hard runtime bound are respected.
- Earliest breach is a hard deadline; an action after it cannot supply it.
- Protected manual/due/active quarters are excluded before allocation.
- If no complete feasible window exists, retain the original cheapest-quarter
  fallback and truthful limited/shortfall reporting.
- Original Alpha84 60-minute decision behavior, one best chronological
  trade pair, Plan72 SOC authority, Bridge and Store contracts are unchanged.

## Evidence and limitations
A constructed same-input 288-quarter fixture with alternating EUR 0.100 and
EUR 0.105 prices now yields **one** 2h45m safety candidate and physical window
instead of three disjoint candidates. Reserve-breach count and remaining
charge need remain zero. Independent frozen original-hourly oracle tests,
different quarter prices, manual protection, price deadlines and energy balance
regressions must also pass on Python 3.12/3.13.

A source-requested charge that reaches the battery's SOC/capacity early may
still legitimately be reported `limited`; do not hide differences between
requested source energy and actually charged AC energy. Distinct live Anker
and DOEMS forecasts are expected to produce different SOC curves and action
times. This release does not guarantee an identical visual graph; it corrects
the identifiable source window-selection strategy.

Live validation after installation is required before closing H8. No new
entities/IDs, no UI changes, no direct Home Assistant modifications.
`physical_execution_authority=false`, `execution_enabled=false`.

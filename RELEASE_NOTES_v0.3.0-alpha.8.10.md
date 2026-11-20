# DOEMS v0.3.0-alpha.8.10 — Anker Alpha84 H5.2 + H5.3

Standalone **observer-only** pre-release from published DOEMS Alpha 8.9
(commit `86810c70e380004c31bf13cfa9a12951cb64bf7a`).
Restores H5.2 and signs off the *classified* H5.3 numerical source discrepancy.
This release does NOT claim full H5.6 physical energy/SOC parity.

## H5.2 — original executable safety timing, corrected

- The frozen original Alpha84 has two executable safety windows in
  `safety_valley`, starting **15 November 18:00Z** and **17 November 12:00Z**.
- DOEMS previously merged a **0.046 kWh**, sub-actionable original hour
  at 11:00Z into the second window, making a **13h** candidate incorrectly
  advertised as `max_runtime_h=12`.
- The Alpha84 Preview now propagates a true source-hour-equivalent flag.
  Only in that exact source-equivalent path, the Bridge applies Alpha84's
  original **0.10 kWh-per-hour actionability threshold**.
- Genuinely different 15-minute input prices still use native quarter
  contiguous-window logic without tariff averaging.
- Native Bridge candidates are split at the pre-existing 12-hour maximum
  execution window instead of exceeding it while under-reporting runtime.
- Frozen upstream Bridge decisions and native physical command start and
  end now match in the reference `safety_valley` fixture; the 2-minute
  hardware handoff remains represented.

## H5.3 — exact SOC difference investigated; no speculative policy patch

- Source SOC differences at hours 26 and 57 (84.1/84.2%, 13.9/14.0%)
  arise from a precisely measured **0.000130434783 kWh** difference in
  stored energy, introduced at hour 20 and constant thereafter.
- The original hourly sequence fills the battery to its capacity before
  the full hour household load, and caps AC safety energy to
  0.274858223062 kWh. Four native quarters interleave household use,
  permitting 0.275 kWh safety energy and freeing headroom between charges.
- This is the expected **sub-Wh physical time-resolution consequence**,
  not a different charging-price decision or accumulating SOC error.
- Original 60-minute reference code and native 15-minute physical SOC
  projection remain unchanged. No display-rounding hack or invented
  strategy limitation was introduced.
- New frozen-source forensic regression proves the stored energy
  difference equals additional actual grid AC input × charging
  efficiency and that it does not accumulate.

## Preserved / still open

- H5.1 original safety allocation and all three persistent manual slots.
- Solar Forecast Remaining Today from Alpha 8.8, prices, forecast,
  Scheduler, Bridge entities, HACS entity IDs and prior release tags.
- No physical battery execution. `physical_execution_authority=false`
  and `execution_enabled=false`.
- H5.6: native physical Plan72 actual 2-minute handoff, partial
  first charge, physical energy reconciliation and residual source
  differences remain open; H6-H8 architecture and live tests remain open.
- No Home Assistant configuration or `main` branch modification.

Pre-release publication is gated by full pytest on Python 3.12/3.13/3.14,
frozen Alpha84 oracle checks, explicit H5.1–H5.3 regression, source
blob hash verification, clean exact-commit ZIP, SHA256 and provenance.

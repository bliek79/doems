# H8 Alpha 8.7 — actual candidate-window selection before Bridge

## Source decision
The frozen Alpha84 hourly code chooses the cheapest feasible safety *hour*
before a reserve deadline; adjacent allocations form one command before the
original three-slot preview. DOEMS Alpha 8.6 scaled that decision down to
individual 15-minute ticks, then grouped only matching adjacent selections.
This was the wrong resolution boundary for a physical action: very small
quarter-price variations could trigger extra start/stop commands.

**Approved adaptation target:** Under native quarter mode only, evaluate
complete contiguous physically executable command windows while comparing
the *sum* of their individual quarter price × allocated AC energy. Do not
average tariff inputs to hourly prices. Keep the 60-minute Alpha84 oracle
identical, including its safety-first and tie-break decision logic.

## Exact reviewed source
- Frozen Anker original: 0.0.1-alpha.84 / 6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d
- Parent DOEMS tag: v0.3.0-alpha.8.6 / 6363d7fd59875d64806c8238c2e649f5891147f4
- Changed production file: custom_components/doems/alpha84_planning.py
- Old Git blob SHA1: 752bb397e2134d51dab969f8ab59df90e21d9d32
- Reviewed new Git blob SHA1: 3a8b4a28f77c23161565e9a081a42efd97752f1e
- No changes to native Plan72, Scheduler, Plan Store, Bridge, entity IDs, dashboards, battery controls or solar forecast.

## Reproduction
Same-input constructed 288-quarter forecast:
- 7.2kWh battery, 60% start SOC; home 0.18kWh per first 52 quarters
- Between quarter indices 16 and 26, import costs alternate EUR 0.100
  and EUR 0.105/kWh; all other price points EUR 0.270/kWh
- Alpha8.6: three noncontiguous physical safety commands, no reserve breach
- New source: one continuous 16:00–18:45 UTC safety command, with 288 original
  price points unchanged, no reserve breach or remaining charge need
- Some safety commands are capacity/target-limited; do not falsify that
  diagnosis just to make a green status.

## Checks and remaining risks
Run complete Python 3.12/3.13 suite, fixed hour-original oracle, native
288-quarter worker, manual constraint, separate quarterly import/export
prices, source hashes and release package checks. No source output
forecast-equality gate: Anker and DOEMS use different **live** forecasts.

Cost-ranked continuous windows cannot and must not be forced to match another
product's live timestamps or its three selected preview cards. On the
installed Home Assistant forecast, still check if the *source* and *physical*
windows are contiguous and if 3 Store slots are the first eligible groups.
Physical action execution remains switched off. H8 live acceptance is still
open until separately verified.

# DOEMS v0.3.0-alpha.8.6 — Native physical safety reconciliation (release candidate)

**STATUS: Developer candidate. Do not install before successful CI, reviewed package, and published pre-release.**

## Source problem discovered in Alpha 8.5 live assessment
DOEMS follows Alpha84's source priority and keeps separate 15-minute prices. However,
a safety charge chosen at the end of a cheap source quarter can begin *after* the
native 2-minute preparation handoff and therefore leave a physically avoidable
reserve breach. The prior source-to-command bridge could report
`remaining_physical_shortfall` without applying the original cheapest-feasible
safety choice to earlier **physically executable** quarters.

## Correction (Plan72 only)
- Retain the original frozen Alpha84 source forecast, safety-first planning
  decision, latest-on-equal-price tie-break and one best chronological trade pair.
- Recheck a genuine native SOC reserve shortfall **after** the first complete
  physical replay, not by inflating a forecast or relaxing reserve tolerances.
- If an earlier quarter is actually available, choose the cheapest feasible
  quarter *before the breach deadline* using the same Alpha84 price ordering,
  model the 2-minute preparation and the real power/SOC limits, and replay.
- Regroup **all** contiguous same-purpose actions before passing a three-slot
  preview downstream. Do not cross manual/due/active protected plans or an
  existing different-purpose charge/discharge window.
- Keep infeasible breaches visible and preserve any genuinely bounded source
  command as `limited`; no fictitious energy credit.
- Publish the physical-repair selection and unresolved deadline count in the
  existing Plan72 timeline `action_window_search` diagnostics; no new HA
  entity, unique ID, UI layout, color, or control authority.

## Verification requirements
- Regression fixture demonstrating the pre-handoff reserve violation and
  prevention with a real 288-quarter, distinct-price forecast.
- Regression protection for manual commitments, future cheap-but-late quarters,
  source-safe unchanged behavior, impossible initial reserve shortfall, and AC
  energy conservation.
- Existing full Python 3.12/3.13, original Alpha84 source parity,
  Scheduler/Store/Bridge, reviewed hash and release-package checks.
- Same-planning-strategy acceptance; **different live Anker/DOEMS forecasts
  are expected to generate different physical plans**.
- Post-install Home Assistant diagnostics must confirm the actual current
  72h route; these cannot be signed off by synthetic fixtures.

## Unchanged
- 72 hours / 288 individual quarter prices, 3 persistent slots, existing
  entity IDs, 2-minute preparation, 2% execution buffer, manual precedence,
  hard end times, SOC target separation, and original scheduler selection order.
- `physical_execution_authority=false` and `execution_enabled=false`.
- No direct Home Assistant edits. Existing Alpha 8.5 release and tags unchanged.

Gas/Anker state_class/B.R.I.C.K. matters remain separate open diagnostics.

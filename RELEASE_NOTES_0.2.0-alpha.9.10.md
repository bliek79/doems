# DOEMS 0.2.0-alpha.9.10 — standalone execution safety candidate

This prerelease contains the independently implemented DOEMS R7/R8 battery execution path. The original Anker EMS Alpha84 implementation was used as a source-code reference only. DOEMS does not require a running Anker EMS coordinator for its execution decisions.

## Included

- Existing DOEMS Manual, Automatic and Combined scheduling, 3-slot plan store and R7 scheduler remain in place.
- Standalone DOEMS R8 execution controller and local Anker Solarbank adapter for controlled mode switching, charging/discharging setpoints, stop and reconciliation.
- Locally ported Alpha84 Pre-Start Validator and Safety Guard.
- Locally ported Alpha84 Final Revalidation, with current plan identity, scheduler evidence, battery SOC, planner candidate, forecasts, power-limit settings and control entities refreshed before controller actions.
- Master gate defaults OFF and requires local DOEMS authorization; safety failures block action.
- Removed runtime registration/authority dependence on the separate Anker EMS integration.

## Validation and limitations

- Python 3.13 / Home Assistant 2026.2.3 and Python 3.14 / Home Assistant 2026.9.3 are validated by the release workflow before publication.
- This is a prerelease for controlled Home Assistant evaluation, **not a verified production battery-control release**.
- No physical battery charge/discharge, emergency-stop or restart-recovery tests have been performed as part of this publication.
- The maximum operational charge/discharge limits are provided by DOEMS configuration; the user's current configuration is 3200 W in each direction.
- Do not enable the DOEMS master control until the operator has verified the exclusive battery writer, connected control entities, correct limits, and a safe test window. Do not run two integrations commanding the same battery.
- No changes are made to Home Assistant or the physical battery by publishing this GitHub release.

Existing releases and tags must not be overwritten.

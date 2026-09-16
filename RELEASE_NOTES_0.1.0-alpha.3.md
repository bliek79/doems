# DOEMS 0.1.0-alpha.3 - P2.1 Live Green Maintenance

## Scope

This is a narrow maintenance release after the live and restart/storage acceptance of P2.1 Energy Forecast.

## Changes

- Adds local Home Assistant brand assets under `custom_components/doems/brand/` (light/dark icon and logo, including `@2x` variants).
- Fixes the observed post-restart `Energy History Status` lag by refreshing quarter-driven diagnostics as soon as the configured Home Power source becomes available again.
- Keeps the Energy Forecast model, native 15-minute / 72-hour / 288-slot contract, source signature, storage schema and learning logic unchanged.
- Version bumped to `0.1.0-alpha.3`.

## Live acceptance carried forward

- Home Power parity with the Alpha41 reference: PASS.
- Native timeline: 288 slots: PASS.
- Own `doems.energy_forecast` history: PASS.
- Restart/storage persistence: PASS.
- No DOEMS runtime errors during the observed multi-hour run: PASS.

## Safety

- EMS remains disabled.
- Physical execution authority remains false.
- No physical Home Assistant service calls are introduced.

## Release channel

Published as a normal GitHub Release (not a GitHub prerelease) while retaining the alpha semantic version, so HACS version handling can be verified without changing forecast behaviour.

# DOEMS 0.1.0-alpha.2 - P2.1 Energy Forecast

This prerelease adds the first functional DOEMS component while preserving the clean Step 0 identity.

## Added

- Energy Forecast at native 15-minute resolution with a fixed 72-hour / 288-slot horizon.
- Clean `doems.energy_forecast` storage for component-owned learning history.
- Direct Home Power and Power Balance installation routes.
- Explicit grid sign-convention normalization.
- Optional battery charge/discharge inputs only when a battery participates in the local power balance.
- Normal/Away profile selection with profile-safe quarter learning.
- Canonical `sensor.doems_source_home_power` input surface.
- Forecast total, timeline, next quarter, history, coverage and confidence entities.
- Source-signature protection: incompatible source changes do not reuse prior learning history.
- CI release gate requiring every public DOEMS entity object ID/unique ID to start with `doems_`.

## Preserved from the proven Energy Forecast baseline

- history-driven hierarchy: weekday+quarter -> day-type+quarter -> quarter-of-day -> profile mean;
- 28-day recency half-life;
- no cross-profile borrowing;
- 90% minimum valid quarter coverage;
- 400-day history limit;
- exact quarter-aligned native forecast window.

## Safety

- EMS remains disabled.
- Physical execution authority remains false.
- No physical service calls are introduced.
- Solar Forecast, Prices, Weather/Degree Days and EMS remain outside this release.

## Upgrade note

Existing `0.1.0-alpha.1` installations keep their DOEMS config entry. After restart, open DOEMS **Configure**, enable Energy Forecast and provide only the selected source-route fields plus the initial learning profile.

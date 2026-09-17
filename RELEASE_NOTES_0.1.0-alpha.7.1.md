# DOEMS 0.1.0-alpha.7.1 - Prices Config Flow Hotfix

This hotfix repairs the Home Assistant Options Flow transition from the final Solar array into Prices P4.

## Fixed
- Prices tariff fields now use Home Assistant's supported free-precision NumberSelector mode (`step: any`) instead of unsupported sub-0.001 numeric steps.
- Solar location override fields use the same supported free-precision mode.
- Completing the final configured Solar array no longer advances the internal array cursor beyond the configured array count while transitioning to Prices.
- A downstream form-render failure can therefore no longer expose a phantom `PV-array 3 of 2` screen.

## Root cause
Home Assistant validates NumberSelector numeric `step` values at a minimum of 0.001. Alpha7 used 0.00001 for tariff fields and 0.000001 for location overrides. When Solar array 2 of 2 completed, the flow entered Prices and failed while constructing that form. Because the Solar cursor had already advanced, the retained form state could present array 3 of 2.

## Scope
No Energy forecast logic, Solar forecast calculations, Prices normalization, tariff formulas, 76h/304 buffer logic, 72h/288 public timeline, import/export separation, dashboard contract, or physical execution authority is changed.

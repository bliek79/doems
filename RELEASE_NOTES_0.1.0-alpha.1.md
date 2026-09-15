# DOEMS 0.1.0-alpha.1 - Step 0 Clean Foundation

This prerelease establishes the new, clean DOEMS Home Assistant identity.

Included:
- `custom_components/doems` as the only active package namespace;
- Home Assistant domain `doems`;
- config flow with no required installation-specific fields in Step 0;
- options flow with only an optional display name;
- foundation status entity;
- identity-purity contract tests;
- MIT license retained;
- no forecast logic;
- no EMS decision logic;
- no physical battery control.

Safety contract:
- physical execution authority is false;
- forecast functionality is disabled;
- EMS functionality is disabled.

This release is the clean base for the component-by-component replatform. Energy Forecast is the next planned component.

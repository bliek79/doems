# DOEMS

DOEMS is a clean Home Assistant Energy Management System integration built as a new technical identity.

## Current stage

`0.1.0-alpha.1` is **Step 0 - Clean Foundation**.

This release intentionally contains only:

- the new Home Assistant domain `doems`;
- a clean config entry and optional display-name setting;
- a foundation status sensor;
- no forecast logic yet;
- no EMS decision logic yet;
- no physical battery control.

Step 0 requires **no installation-specific input**. Each future component is reviewed separately before it is added, so third-party users are only asked for data that component actually needs.

## Installation

1. Install the repository as a custom integration (manual installation or as a custom HACS repository during alpha development).
2. Restart Home Assistant.
3. Open **Settings > Devices & services > Add integration**.
4. Search for **DOEMS**.
5. Confirm setup. No functional fields are required in Step 0.

After setup, DOEMS creates a foundation status entity. Its safety attributes must show that forecast and EMS functionality are disabled and that physical execution authority is false.

## Identity contract

The active integration uses only the new technical identity:

- package: `custom_components/doems`
- Home Assistant domain: `doems`
- logger namespace: `custom_components.doems.*`
- storage namespace prefix: `doems.*`
- device identity: `doems`

Legacy implementation identities are not allowed in the active integration runtime.

## Development order

DOEMS is rebuilt component by component. The planned order starts with:

1. clean foundation;
2. Energy Forecast;
3. Solar Forecast;
4. Prices;
5. supporting forecast data and validation;
6. planner input and time contract;
7. EMS decision and execution chain in shadow mode;
8. parity and live shadow validation before any physical cutover.

## Safety

Alpha releases are development builds. Step 0 cannot send commands to a battery or other physical equipment.

## License

DOEMS is released under the MIT License. See [LICENSE](LICENSE).

# DOEMS 0.1.0-alpha.30 - Safety + Trade Parity Restore

## Scope
Alpha30 restores intended planner parity only. It does not introduce a new trading policy.

## Restored behavior
- Safety charging remains first priority.
- A required safety charge no longer disables an independently profitable trade.
- After solar and safety use their required charging headroom, existing trade charging may use only the remaining physical power and battery capacity.
- Trade charging still requires the existing roundtrip-efficiency and minimum-trade-margin profitability check.
- Solar Charge Delay remains in force.
- Trade discharge remains limited by the existing requested trade output, remaining discharge power and energy above the execution reserve.
- Safety and trade can therefore coexist in one 72-hour plan and, where they fall in the same planning interval, in the combined action `veiligheidsladen+handelsladen`.

## Regression protection
Alpha30 adds explicit tests for:
- simultaneous safety charge and profitable trade;
- preservation of later grid trade discharge;
- safety-only behavior when trade is not profitable;
- existing physical and reserve constraints remaining authoritative.

## Unchanged
- Native 15-minute / 72-hour / 288-slot architecture.
- Manual priority.
- Automatic execution safety gates.
- Physical transaction and safe-return sequence.
- Existing price, reserve, SOC and efficiency configuration.

## Version
`0.1.0-alpha.30`

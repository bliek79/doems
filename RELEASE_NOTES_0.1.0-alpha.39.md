# DOEMS 0.1.0-alpha.39 - Plan Store Commitment Replay

Alpha39 restores the required planner contract that accepted Plan Store actions affect the projected SOC and every later safety/trade decision.

## Restored behavior
- Manual pending/active Plan Store actions inside the 72-hour horizon are hard planner commitments.
- Committed charge/discharge energy is replayed through the projected battery SOC before later optimization.
- Plan72 rows expose `planstore_charge_kwh`, `planstore_discharge_kwh` and commitment metadata for dashboard visualization.
- Automatic planner proposals remain revisable until due/active, avoiding self-reinforcing proposal loops.

## Safety correction
- Alpha38 Design C separation is completed: future `safety_target_soc` no longer becomes a hidden hard hold floor through precharge reachability.
- The 2% execution buffer is removed.
- Operational reserve and execution reserve are both 12% with the current 5% technical minimum + 7% software reserve contract.
- Future safety need remains a planning target and is charged at appropriate planned moments instead of forcing the battery to remain nearly full.

## Preserved contracts
- Native DOEMS transport remains 15 minutes / 72 hours / 288 slots.
- Alpha37 non-blocking Home Assistant startup behavior remains intact.
- Physical execution authority remains disabled for DOEMS during shadow validation.
- Frozen Alpha76 parity guards and Alpha33/34/35 adapters remain protected.

## Validation
Alpha39 adds regression coverage for manual charge/discharge SOC impact, commitment-aware downstream planning, zero execution buffer, fixed 12% reserve semantics, and existing planner/scheduler/safety/foundation contracts.

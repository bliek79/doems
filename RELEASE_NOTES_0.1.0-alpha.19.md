# DOEMS 0.1.0-alpha.19 - Physical Self-Consumption Planner

## Scope

Alpha19 is the first explicit post-G5 planner-policy change. It corrects the
low-solar behavior where demand until the next usable solar block could become a
100% reserve floor even though the physical battery remained in
`self_consumption` and would continue supplying the home.

Native architecture remains exactly 15 minutes / 72 hours / 288 slots.

## Production policy change

Production EMS decisions now use a new versioned policy package:
`ems_policy_v2` with policy identity `self_consumption_physical_v2`.

The production runtime is routed through `ems_policy_adapter.py`.

The frozen `ems_alpha76` package and `ems_alpha76_adapter.py` remain
unchanged and continue to serve as historical Step 13 / G5 parity evidence.

## New self-consumption semantics

- Forecast household demand until usable solar remains planning context.
- Normal household demand is projected as physical self-consumption and may
  discharge the battery to the configured technical minimum SOC.
- A calculated planning reserve is not treated as physically enforceable while
  the device remains in `self_consumption`.
- Energy Need separates unavoidable direct grid import from optional earlier
  stored-energy support.
- If later direct grid import is unavoidable, the planner searches for an
  earlier charge window.
- Earlier charging is selected only when delivered battery energy after charge
  and discharge losses is cheaper than direct future household import.
- The explicit action purpose is `zelfconsumptie_bijladen`.
- Trade reservation can no longer suppress normal household discharge.

## Plan72 observability

Plan72 now publishes:
- `charge_from_grid_support_kwh` per hour;
- total `auto_plan_72h_grid_support_charge_kwh`;
- physical self-consumption floor and headroom;
- separate control-reserve headroom;
- planning-need SOC equivalent for diagnostics;
- explicit `reserve_enforceable_in_self_consumption=false`.

The existing 72-hour public compatibility view remains derived from the native
288-slot forecast architecture.

## Safety and authority

Unchanged:
- Step14/G6 remains closed;
- DOEMS still has no physical battery authority;
- no new Home Assistant service calls are introduced;
- the existing read-only execution/safety chain remains non-actuating;
- the frozen G5 baseline remains reproducible;
- Tab 1 / Tab 2 Google Sheets logging remains observer-only and is never planner input.

## Regression coverage

Alpha19 proves:
1. low solar plus demand above battery capacity no longer creates a fictitious
   100% self-consumption hold floor;
2. with no cheaper earlier charge window, SOC may naturally project to the
   configured 5% minimum and later demand becomes grid import;
3. a genuinely cheaper earlier window creates a limited support charge;
4. production runtime uses policy v2 while G5 still references frozen Alpha76;
5. the Action Bridge recognizes support charge but normal household discharge
   remains a self-consumption flow.

## Live acceptance after installation

After installing Alpha19:
- let Tab 2 continue collecting Decision Snapshot rows;
- confirm Plan72 SOC follows natural self-consumption during the evening;
- confirm the reserve line no longer pins the projected SOC at 100%;
- when a cheaper earlier charge window exists, confirm a compact
  `zelfconsumptie_bijladen` candidate appears;
- when it does not, confirm Plan72 accepts depletion toward minimum SOC;
- keep Step14/G6 closed.

### Version
`0.1.0-alpha.19`

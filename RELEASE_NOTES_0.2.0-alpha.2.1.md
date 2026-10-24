# DOEMS 0.2.0-alpha.2.1 - Battery Input Flow Fix

## Purpose

This hotfix closes the live R1 configuration issue found during Home Assistant validation of 0.2.0-alpha.2.

When Energy Forecast used Power Balance with a battery, charge and discharge power sources were already selected in the existing Battery Power step. Battery Observation then requested those exact same two sources a second time.

## Fixed

- Battery Observation now reuses valid charge and discharge power sources already selected by Energy Forecast.
- In that path Battery Observation asks only for:
  - battery SOC;
  - battery capacity;
  - battery device status.
- If no reusable charge/discharge sources exist, for example with Direct Home Power, Battery Observation still asks for all five required sources.
- Existing read-only battery contract semantics are unchanged.

## Safety boundary

No physical battery control is introduced.

- no service calls;
- no mode switching;
- no setpoints;
- no Plan Store;
- no Scheduler;
- no automatic planner;
- physical_execution_authority=false.

## Preserved architecture

Energy, Solar and Prices Forecast remain unchanged on the native 15-minute / 72-hour / 288-slot architecture.

## Validation

- Python compile;
- full pytest suite;
- battery input contract regression tests;
- dedicated flow-reuse regression;
- JSON validation;
- release archive verification.

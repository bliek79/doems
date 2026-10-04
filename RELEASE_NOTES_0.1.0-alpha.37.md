# DOEMS 0.1.0-alpha.37 - Startup Hotfix

## Purpose

Alpha37 is a focused hotfix for the live Home Assistant startup regression found after Alpha36 was enabled.

Alpha36's planner policy remains unchanged. The native 15-minute / 72-hour / 288-slot contract, Alpha80/81 cheapest-energy policy, DOEMS Alpha35 sequential safety authority, Plan Store, Scheduler, Prestart, Safety Guard and physical execution semantics remain unchanged.

## Fix

- Home Assistant config-entry startup no longer waits for a complete heavy Alpha36 planner cycle to become idle.
- The initial planner generation is queued through the existing single-flight/coalescing pipeline and completes in the background.
- Runtime starts with status `starting` until the first valid planner publication.
- `start_critical` replanning is suppressed during the first startup planner publication, preventing recursive planner work during bootstrap.
- After the first planner publication, normal `start_critical` behavior is restored.

## Regression coverage

Alpha37 adds guards that require:

- startup to use `_request_planner_refresh("startup")`;
- startup not to use `await self.async_refresh("startup")`;
- first-publication `start_critical` gating to be present;
- the startup-complete flag to be set only after planner publication.

All existing Alpha36 planner/safety tests and the complete DOEMS regression suite remain release gates.

## Live validation

Install Alpha37 over the restored `custom_components/doems` directory and perform one controlled Home Assistant restart.

First gate: Home Assistant must return normally and remain responsive while the planner completes in the background.

Only after that gate is green should normal Alpha36/Alpha37 planner validation continue. Physical DOEMS execution remains outside this startup hotfix scope.

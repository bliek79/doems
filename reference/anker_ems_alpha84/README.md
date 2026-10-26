# P2 Step 1: immutable working reference — Anker EMS Alpha84

Reference repository: `bliek79/dummy-os-anker-ems`, release tag `0.0.1-alpha.84`.
The eight `.py` files in this directory are byte-for-byte source text copies
from `custom_components/anker_ems/` at that tag. They are **not imported** by
DOEMS and do **not** grant physical authority.

## Captured reference core

| Source | Purpose | Dependencies / integration surface |
| --- | --- | --- |
| `execution.py` | Proven execution controller, automatic mode switching, charge/discharge commands, monitor, stop, persisted audit and restart recovery | `const`, `charge_power_limit`, `execution_status_reset`; coordinator: `control_entity_ids`, `max_charge_power_w`, `authority_fence`, `async_refresh`, `physical_test`, `auto_execution_armed`, `data`, `plan_store` |
| `physical_test.py` | Bounded physical charge/discharge tests, stop and restart recovery | coordinator: `control_entity_ids`, `execution`, `async_refresh`, `data`, `authority_fence`; test bounds from `const.py` |
| `authority_fence.py` | Persistent single-writer OPEN/CLOSING/CLOSED fence, in-flight calls and safe-return rules | HA `Store`, HA services, `DOMAIN` constant; legacy entry-id storage key |
| `prestart_validator.py` | Independent pre-start eligibility checks | `MIN_SOC_PERCENT`, `MAX_SOC_PERCENT`; assembled coordinator data |
| `safety_guard.py` | Safety check and automatic handoff gate | `MIN_SOC_PERCENT`, `MAX_SOC_PERCENT`; assembled coordinator data |
| `execution_status_reset.py` | Pure emergency-status-reset policy | Pure Python; no external local imports |
| `charge_power_limit.py` | Pure dynamic Anker charge-limit selection and retry policy | Pure Python; no external local imports |
| `action_controller.py` | Pure selected-plan action decision | Pure Python; no external local imports |

## Actual dependency contract

The active Alpha84 `execution.py` and `physical_test.py` **cannot safely be
dropped into DOEMS unchanged as live modules**: they expect the existing
Anker EMS coordinator, entity mappings, `plan_store`, persistence paths,
authority fence, state provider and Home Assistant service lifecycle. Their
relative imports and domain also differ. This is an adapter/dependency
problem, **not permission to rewrite proven algorithms**.

The pure `execution_status_reset.py` and `charge_power_limit.py` already have
counterparts in DOEMS. Compare behavior, not merely file presence.

## Step 1 acceptance and next-step fence

1. Reference source captured outside the active HA integration: **done**.
2. Key cross-module dependencies identified: **done**.
3. Proven code preserved without rewriting: **done**, for the reference copy.
4. Live integration of original controller, physical-test controller and
   authority fence: **not done**.
5. Handoff, rollback, diagnostics/service compatibility and scenario parity:
   **not done**.
6. Physical end-to-end validation: **not done**.

For Step 2, provide the old execution controller with an explicit,
testable compatibility façade that adapts the DOEMS Combined-selected plan
to the original coordinator contract. Preserve original timing, readback,
error and safe-return logic. Wire no actuation without a verified
single-writer handoff; no implicit fallback authorization.

Do not change DOEMS forecasts or Manual/Automatic/Combined planning
algorithms. Do not merge or publish until the parity matrix and hardware
validation gates are satisfied.


## Step 2 progress — original controller boundary (2026-10-26)

The pure Combined-plan projection is connected to the active **observational**
DOEMS runtime and is published as an attribute of its existing execution
status sensor. A separate `alpha84_controller_link.inspect_alpha84_controller`
adapter is now tested against the **original Alpha84
`evaluate_final_revalidation` method signature**. It does not duplicate
or replace that validator and it never starts execution.

**Critical outstanding dependency:** the live original Alpha84 controller
instance is **not registered** in the DOEMS runtime. The current runtime
explicitly reports `original_alpha84_controller_not_registered`; the
interface tests use an isolated method-compatible test double, not a live
Alpha84 instance. Full integration is therefore **NOT COMPLETE**.

Next, install the original controller under a safely namespaced DOEMS
compatibility coordinator (preserving state storage, callbacks, fence and
startup-stop behavior), supply independently refreshed legacy safety
evidence, and run original Alpha84 safety gates unchanged. Only after
exclusive writer handoff and rollback pass hardware validation may
physical authority be considered for enablement.

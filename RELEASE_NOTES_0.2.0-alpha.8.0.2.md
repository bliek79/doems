# DOEMS 0.2.0-alpha.8.0.2 — R8-A isolated validation candidate

Base: 0.2.0-alpha.7.1.16 (commit a89efb2697e01995556a215a4a79e5eed3ff2334).

## Scope
- Adds an isolated, pure Python R8-A readiness evaluator and tests.
- No runtime wiring, sensor registration, plan-store writes, planner selection, lifecycle mutations, battery service calls or physical control.
- Manual, automatic 72h, combined planner and R7 scheduler code are unchanged.
- Manifest and const release versions updated to 0.2.0-alpha.8.0.2.

## Critical limits
- R8-A remains **not operational in Home Assistant**; it is packaged but not invoked.
- R7 has no published atomic plan revision evidence, final revalidation evidence or execution handoff evidence. The validator correctly reports NOT_VALIDATED when these are missing.
- This is a technical candidate, **not live-accepted** and must not be interpreted as R8-B authorization.
- Previous R8-A release 0.2.0-alpha.8.0.1 is rejected.

## Validation
The release workflow requires full repository pytest suite, compilation, JSON checks, frozen runtime file diff, and archive inspection before publishing. Manual, automatic, combined planner live acceptance remains a separate user-side check after installation.

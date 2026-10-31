# DOEMS v0.3.0-alpha.7.2 — Home Assistant registration and timer hotfix

The supplied Home Assistant log identified two defects in Alpha 7.1: six diagnostic sensors used a string entity category, rejected by the registry, and the periodic Plan Store writer used an unmarked synchronous timer lambda that Home Assistant ran in an executor.

The diagnostics now use EntityCategory.DIAGNOSTIC. The timer uses a named @callback handler, keeping task creation on the event loop. Regression checks validate all six diagnostic categories and exercise the actual timer registration and repeated invocation.

Entity-ID and unique-ID formulas remain unchanged. No planner, storage schema or physical execution authority is added. Existing tags are preserved. Publication requires the full Python 3.12 and 3.13 suites and release/archive validation. This release does not change the user's Home Assistant installation remotely.

# DOEMS 0.2.0-alpha.8.0.5

This release provides a tested, installable execution-supervision update.

- Preserves the frozen 15-minute / 72-hour / 288-slot planner architecture.
- Evaluates selected plans against SOC, source freshness, safety, start windows and plan identity.
- Persists execution supervision events and blocks unresolved restart reconciliation.
- Observes the Anker three-entity control path and its 60-second stability condition.
- Includes an isolated Anker command adapter with fail-closed authorization.
- Physical battery actuation is **not enabled**; the adapter is not granted authority by the integration.
- This is not a validated automatic physical execution release.

Installation: install via HACS custom repository or unpack the supplied ZIP into the Home Assistant configuration directory and restart Home Assistant. Existing configuration is preserved.

Release package is published only after the complete automated test suite passes.

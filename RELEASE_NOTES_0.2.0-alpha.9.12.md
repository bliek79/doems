# DOEMS 0.2.0-alpha.9.12

Safety parity release candidate based on 0.2.0-alpha.9.11.

- Shared fail-closed physical prestart gates for Manual and Automatic slots.
- Preserve one canonical R8 writer. Keep separate R9 Combined bridge permanently non-actuating, including stop isolation.
- Match historical safe mode switch: best-effort pre-mode 0 W when available, required post-mode 0 W with acknowledgement and 60-second stability before a nonzero command.
- Do not reuse pending-only start validation for active session watchdog; verify active plan identity against the active plan store.
- Monitor command mode, direction, both battery power observations, plan identity, available sources, SOC and time bounds.
- Re-evaluate live charge power cap during operation; lower command with acknowledgement or stop and mark fault.
- Stop automatic sessions when measured planned energy is reached.
- Add regression checks for safety parity, active monitoring, energy integration and single writer boundaries.

This is a candidate only until tests and PR review pass. Home Assistant/battery physical behaviour is not certified by repository CI. Keep DOEMS Automatic Execution OFF until installation review and supervised physical tests.

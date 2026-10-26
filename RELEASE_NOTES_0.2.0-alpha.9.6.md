# DOEMS 0.2.0-alpha.9.6 — P2/P3 HACS validation prerelease

This prerelease builds on the validated R9.5 base and includes the P2
Anker-specific execution safeguards and P3 Alpha83/84 planning compatibility.

## P2: safeguards
- Charge-power restrictions derived from Anker live Number limits (min/max/step).
- A single strictly lower power retry if the first charge attempt is rejected.
- Default-OFF EMS master execution switch.
- Emergency acknowledgement button and status sensor using read-only legacy
  EMS arm/execution/physical-test/mode-switch safety sources.
- Fail-closed reconciliation and emergency reset requirements.

## P3: planning
- Bounded partial safety charging with the original price window less two
  minutes for mode switching; never extend the requested window.
- Explicit requested, feasible/planned, and shortfall energy attributes on
  the existing automatic plan status sensors.
- Chronological invalid-candidate cutoff without blocking individually valid
  candidates solely because a preceding safety charge was partially feasible.
- Reserve active and pending automatic slot identities; fill a genuinely free
  third slot, without replacing user-owned manual slots.
- Preserve native 15-minute, 72-hour, 288-slot planning.

## Safety and installation scope
- Physical battery authority is **not enabled by installing this prerelease**.
  The DOEMS EMS master permission starts OFF, and legacy EMS authority remains
  separately gated. Do not enable two battery controllers simultaneously.
- No physical battery test or installation-specific Home Assistant validation
  is claimed by automated CI. Start P4 with observation/validation only.
- No Home Assistant configuration, existing tags, or historical releases are
  modified by this prerelease.

CI validates the full test suite against both supported workflow environments,
checks the HACS archive and publishes a checksum-verifiable `doems.zip`.

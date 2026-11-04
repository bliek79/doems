# DOEMS 3.0 — v0.3.0-alpha.8.1 — Scheduler

## Nieuw
- Observerende Scheduler voor de drie persistente slots: verschuldigd gepland
  vóór direct, oudste starttijd en slotnummer als deterministische tie-breaks.
- Vier diagnose-entiteiten voor status, geselecteerd slot, reden en startklaar.
- Lichte tijdcontroles en gerichte callbacks zonder extra Plan72-berekeningen.
- Revisie-/snapshotcontrole en zichtbare bron- en planidentiteit voor hoofdstuk 9.

## Contractaansluiting
- Automatische nulmarge uit hoofdstuk 7 wordt geaccepteerd zonder verlenging.
  Een callback na het exacte startmoment ziet een verlopen venster; geen realtime
  garantie. Handmatige marges blijven ongewijzigd.
- Tijdzonebewuste tijden, harde eindtijd en afzonderlijke command_target_soc en
  projected_end_soc blijven behouden.

## Afbakening
- physical_execution_authority: false; execution_enabled: false.
- Geen Pre-Start Validator, Safety Guard, Final Revalidation of Execution Controller.
- Plan72, Bridge, Plan Store, handmatige bescherming en kwartierbeleid behouden.
- Dashboard en Home Assistant-installatie niet gewijzigd; geen main-merge.

## Validatie
- Vergelijking met de ongewijzigde Alpha84 Scheduler in 512 slotcombinaties.
- Grens-, lifecycle-, bronuitval-, persistentie-, race- en runtime-regressietests.
- Volledige testmatrix en releasepakket worden door de hoofdstuk-8-CI gecontroleerd.
- Observerende livechecks staan in docs/DOEMS3_CHAPTER8_SCHEDULER.md en zijn nog open.

Dit bestand bereidt Alpha 8.1 voor; de aanwezigheid ervan bewijst geen publicatie.

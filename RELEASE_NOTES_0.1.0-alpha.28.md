# DOEMS 0.1.0-alpha.28 - Beta Phase 2 Signature Gate Fail-Closed Hotfix

## Doel

Alpha28 corrigeert uitsluitend de live gevonden inconsistentie tussen de
Automatic Execution Gate en de fysieke beta-fase-2 executor. Een gewijzigde
Plan72 planner-signature mag niet langer als arm-ready worden gepresenteerd.

De native 15 minuten / 72 uur / 288 slots architectuur, plannerpolicy,
Plan Store, Safety, Prestart, physical transaction, manual priority en safe
return blijven ongewijzigd.

## Live aanleiding

Tijdens de eerste natuurlijke beta-fase-2 pre-arm op 2 oktober 2026 was:

- Scheduler: `startklaar`;
- origin: `automatic_72h_planner`;
- Prestart/Safety/Final Revalidation/Mode Switch Preview: groen;
- planner identity: gelijk;
- planner signature: gewijzigd na due;
- Automatic Gate: ten onrechte `ready_disarmed` met
  `technical_ready=true`;
- fysieke DOEMS-uitvoering: niet gestart; arm bleef OFF.

De fysieke runtime/executor had al een harde signature-check en zou de run
fail-closed weigeren. De fout zat dus in de publieke gate-semantiek.

## Gewijzigd

- `planner_revision_changed` is in de Automatic Execution Gate nu een
  **blocker** in plaats van een warning.
- Bij signature mismatch publiceert de gate:
  - `status=blocked`;
  - `technical_ready=false`;
  - `execution_permitted=false`;
  - blocker `planner_revision_changed`.
- `ready_disarmed` blijft alleen mogelijk wanneer de actuele planner-signature
  volledig overeenkomt met het geselecteerde planslot.
- De fysieke runtime- en executor-signaturefences blijven ongewijzigd en hard.
- De beta-fase-2 dashboardkaart toont nu ook signature match, technical ready,
  blockers en warnings.

## Niet gewijzigd

- Geen plannerpolicywijziging.
- Geen aanpassing van forecast, prijzen, SOC of reserve om een actie te forceren.
- Geen wijziging van Plan72 timing/resolutie.
- Geen realtime 0-W/PD-controller.
- Geen fase-3 cleanup.
- Geen verwijdering van Anker EMS.

## Live vervolg

Na installatie van alpha28:

1. DOEMS Automatic Execution OFF.
2. Anker EMS OFF/quiescent voor de cutover.
3. Batterij in `self_consumption`.
4. Wachten op een natuurlijke `automatic_72h_planner` selectie.
5. Bij signature mismatch moet de gate nu `blocked` tonen.
6. Alleen bij signature match + `ready_disarmed` + geen blockers bewust armen.
7. Eerste fysieke automatic run volgen tot terminale stop en
   `0 W -> self_consumption` safe return.

# DOEMS 0.1.0-alpha.27 - Beta Phase 2 Automatic Plan72 Physical Cutover

## Doel

Alpha27 opent uitsluitend de fysieke route voor een door de Scheduler geselecteerde
`origin=automatic_72h_planner` actie. De plannerpolicy, native 15 minuten / 72 uur /
288 slots architectuur en het bewezen fysieke transactiepad blijven ongewijzigd.

Beta fase 1 blijft geaccepteerd en gesloten. Handmatig laden, de
opposite-direction safety-block, handmatig ontladen en safe return naar
`self_consumption` worden niet opnieuw ontworpen.

## Gewijzigd

- De bestaande `DOEMSManualPhysicalExecution` blijft de enige fysieke writer.
- Een automatische Plan72-actie mag dezelfde writer alleen bereiken wanneer:
  - Scheduler exact één startklare geplande actie selecteert;
  - `origin=automatic_72h_planner`;
  - Automatic Execution expliciet ON staat;
  - de bestaande Automatic Execution Gate `armed_ready` is;
  - `execution_permitted=true`;
  - selected slot, planner identity, planner signature, action, power,
    target SOC en max runtime overeenkomen.
- Na de mode-switch naar `third_party_control` wordt dezelfde automatic gate
  opnieuw gevalideerd voordat direction en power worden geschreven.
- Runtime-safety en stopgedrag blijven hetzelfde bewezen pad gebruiken:
  opposite-direction bewaking, mode/direction/setpoint bewaking en
  `0 W -> self_consumption` safe return.
- Restart/reload herstelt de arm niet en hervat geen fysieke run automatisch.
- Nieuwe compacte observability maakt origin, physical status, planner identity,
  direction/setpoint en safe return zichtbaar.
- Een minimale dashboardkaart is toegevoegd in
  `examples/beta2_automatic_plan72_cutover_card.yaml`.

## Niet gewijzigd

- Geen nieuwe plannerpolicy.
- Geen realtime 0-W/PD-controller.
- Geen wijziging van 15m / 72h / 288.
- Geen cleanup van validatie-entiteiten of Plan72-observability.
- Geen verwijdering van Anker EMS.
- Manual priority blijft hoger dan automatic.
- De bestaande non-actuating automatic shadow controller en gate blijven
  non-actuating; alleen de bewezen fysieke writer voert servicecalls uit.

## Live cutovercontract

Voor de eerste automatische fysieke run:
1. Anker EMS OFF/quiescent.
2. Batterij in `self_consumption`.
3. Automatic Execution OFF bij preflight.
4. Wachten op één natuurlijke `automatic_72h_planner` selectie; plannerinput
   of forecast niet manipuleren.
5. Alleen bij complete gate/readiness bewust armen.
6. Tijdens de run richting, setpoint en werkelijk batterijvermogen controleren.
7. Terminale stop moet `0 W -> self_consumption`, lifecycle en safe return
   aantoonbaar afronden.
8. Automatic Execution daarna OFF.
9. Geen automatische resume na restart/reload.

Een safety-block is positief safetybewijs maar sluit fase 2 niet af als
geslaagde automatische fysieke run.

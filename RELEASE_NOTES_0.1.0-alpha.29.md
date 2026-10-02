# DOEMS 0.1.0-alpha.29 - Beta Phase 2 Signature Warning Physical Parity

## Doel

Alpha29 herstelt de reeds vastgelegde Plan72-semantiek voor planner revisions:
`planner_identity` is bindend; `planner_signature` is revision-observability.
Een gewijzigde signature na due blokkeert daarom niet zelfstandig een verder
stabiele frozen automatic action.

De native 15 minuten / 72 uur / 288 slots architectuur, plannerpolicy,
Plan Store, Safety, Final Revalidation, manual priority en het fysieke
transactiepad blijven ongewijzigd.

## Live aanleiding

Alpha28 bewees live dat de nieuwe fail-closed gate technisch werkte, maar
routebaseline-reconciliatie toonde dat die nieuwe blocker strijdig was met het
bestaande Prestart/Execution-Handoff/Final-Revalidation contract. Bij een
stabiele planner identity kan de rolling planner na due een nieuwe revision
signature tonen terwijl het startklare Plan Store-slot juist bevroren blijft.

## Gewijzigd

- `planner_revision_changed` is in de Automatic Execution Gate weer een warning.
- Bij signature mismatch met stabiele identity kan de gate, als alle overige
  checks groen zijn, opnieuw `ready_disarmed` / `armed_ready` bereiken.
- De runtime-startselectie blokkeert niet meer uitsluitend op
  `prestart_signature_match=false`.
- De fysieke writer blokkeert niet meer uitsluitend op rolling signature
  mismatch, maar bewaart de frozen signature wel voor audit.
- Harde fysieke binding blijft bestaan op selected slot, origin, lifecycle,
  planner identity, action, power, target SOC en max runtime.
- Na mode-switch worden dezelfde identity en frozen command-velden opnieuw
  gevalideerd voordat direction en setpoint worden geschreven.
- Dashboard toont signature match als revision-observability en houdt blockers
  en warnings zichtbaar.

## Niet gewijzigd

- Geen plannerpolicywijziging.
- Geen forecast-, prijs-, reserve- of SOC-manipulatie.
- Geen wijziging van Plan72 tijdarchitectuur.
- Geen realtime 0-W/PD-controller.
- Geen fase-3 cleanup.
- Geen wijziging aan safe return: 0 W -> self_consumption.

## Live vervolg

1. DOEMS Automatic Execution OFF bij preflight.
2. Anker EMS OFF/quiescent voor DOEMS-cutover.
3. Batterij in self_consumption.
4. Wachten op een natuurlijke automatic_72h_planner selectie.
5. Stable identity + volledige safety/readiness + gate ready_disarmed +
   blockers=[] is arm-ready; planner revision mismatch mag alleen warning zijn.
6. Bewust armen.
7. Eerste fysieke automatic run volgen tot terminale stop en safe return.

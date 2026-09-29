# DOEMS 0.1.0-alpha.26 - Step15A Manual Physical Execution

## Doel

Alpha26 opent na afronding van Step 14 / G6 de eerste gecontroleerde fysieke DOEMS-proef. De bestaande plannerarchitectuur blijft native 15 minuten / 72 uur / 288 slots. Deze release geeft uitsluitend **handmatig geplande planslots** fysieke uitvoeringsbevoegdheid wanneer de gebruiker **DOEMS Automatic Execution** expliciet inschakelt.

Automatic Plan72-acties blijven in alpha26 niet-actuerend.

## Fysieke Step15A-route

Een handmatig planslot blijft de bestaande route gebruiken:

Plan Store -> Scheduler -> third_party_control -> Safety Guard / Action Controller revalidatie -> richting -> vermogen -> lifecycle actief -> runtime monitoring -> 0 W -> self_consumption.

De fysieke overdracht start alleen wanneer:
- het plan handmatig is;
- execution mode `gepland` is;
- Scheduler het slot `startklaar` selecteert;
- actie `laden` of `ontladen` is;
- DOEMS Automatic Execution expliciet ON staat;
- SOC, vermogen, control-path en de bestaande veiligheidscontrole geldig zijn.

## Fail-safe arm

`switch.doems_automatic_execution` wordt in Step15A de expliciete fysieke arm:
- na setup/reload/restart altijd OFF;
- geen RestoreEntity;
- OFF start geen nieuwe fysieke actie;
- uitschakelen tijdens een DOEMS-run forceert safe return;
- automatische planneracties krijgen nog geen fysieke authority.

## Safe return

Iedere normale of foutstop probeert vast:
1. power setpoint naar 0 W;
2. korte settle;
3. operating mode terug naar `self_consumption`.

Een onderbroken DOEMS-eigen fysieke transactie wordt na herstel niet hervat; de integratie voert eerst fail-safe return uit en blijft disarmed.

## Safety-bronnen

Alpha26 voegt de batterij-apparaatstatussensor toe aan de EMS-configuratie zodat de bestaande gekopieerde manual Safety Guard dezelfde observatiebron kan gebruiken als de bewezen Anker EMS-route.

## Single-controller proef

Voor live-validatie blijft gelden:
- Anker EMS eerst fysiek uitschakelen/quiescent maken;
- batterij bevestigen in `self_consumption`;
- pas daarna DOEMS Automatic Execution inschakelen;
- nooit twee fysieke controllers tegelijk laten schrijven.

De eerste acceptatievolgorde is:
1. één handmatig geplande laadactie;
2. één handmatig geplande ontlaadactie;
3. beide moeten volledig terugkeren naar `self_consumption`.

Pas na afzonderlijke beoordeling daarvan kan een volgende Step-15-fase automatische Plan72-acties fysieke authority geven.

## Niet gewijzigd

- Geen realtime PD-/0-W-regelaar toegevoegd.
- Geen Solar Forecast-optimalisatie naar DOEMS overgenomen.
- Geen wijziging van de native 15 min / 72 uur / 288 slots architectuur.
- Anker EMS wordt niet verwijderd.
- Automatic Plan72 physical execution blijft gesloten.

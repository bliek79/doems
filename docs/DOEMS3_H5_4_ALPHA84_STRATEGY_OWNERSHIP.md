# DOEMS 3.0 — H5.4 strategie-eigenaarschap versus originele Anker EMS Alpha84

**Bron:** originele `bliek79/dummy-os-anker-ems`,
tag `0.0.1-alpha.84`, commit
`6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d`.

**Bestaande installatiebasis:** DOEMS `v0.3.0-alpha.8.10`,
commit `8cea175c287b77198c4886671392a8f55ce8f124`.

**Herstelopdracht:** géén eigen DOEMS-batterijstrategie. De oorspronkelijke
Alpha84-volgorde, veiligheidsprioriteit, eerste chronologische handelscombinatie,
fysieke verantwoordelijkheden en volledige bron-naar-uitvoerketen zijn leidend;
de native 15-minutenprijzen en aaneengesloten laadvensters blijven behouden.
Dit is een afbakening van de enige productieaanroep, geen nieuw ontwerp.

## Rechstreekse vergelijking met origineel

De originele Alpha84-repository bevat:
- `custom_components/anker_ems/planner_multirate.py`: enige coördinator
  van `build_energy_need_analysis`, `build_planner_preview`,
  `build_72h_plan_preview`. In de bron staat expliciet dat dit
  uitsluitend orchestratie is, geen strategieaanpassing.
- `custom_components/anker_ems/energy_need.py`: energiebehoefte en
  eerstvolgende twee opeenvolgende bruikbare zonne-uren.
- `custom_components/anker_ems/planner_preview.py`: Alpha80
  goedkoopste haalbare veiligheidslading en enkele beste
  chronologische koop/verkoopcombinatie.
- `custom_components/anker_ems/planner_72h.py`: opeenvolgende
  SOC-projectie met solar eerst, safety vóór trade en
  zelfverbruik boven technisch minimum.
- `custom_components/anker_ems/planner_action_bridge.py`: voltooide
  bronactievensters groeperen vóór de keuze van drie Store-slots.

De overeenkomstige originele vier beslisbestanden zijn in de DOEMS-tests
ongewijzigd en per SHA256 beschermd via
`tests/fixtures/alpha84/{energy_need,planner_preview,planner_72h,planner_action_bridge}.py`.
De DOEMS 15-minutenadapter staat in
`alpha84_planning.py` / `alpha84_action_bridge.py` /
`alpha84_bundle.py` en gebruikt dezelfde beleidsketen. De uurroute
wordt in de bestaande regressietests byte-voor-byte vergeleken.

## Actieve Home Assistant uitvoerroute (vastgesteld)

1. `__init__.py` verifieert **vóór alle Home Assistant-subscripties** dat de echte `planner_72h_runtime` de originele `compute_strategy_bundle` gebruikt; pas daarna wordt `Plan72Runtime` aangemaakt wanneer Plan72 actief is.
2. `planner_72h_runtime._evaluate` controleert uitsluitend complete
   native brongegevens met `calculate_energy_need`.
   Die beschrijvende kwartierfunctie heeft **geen bevoegdheid**
   om handel of laadmomenten te kiezen.
3. Dezelfde `_evaluate` roept **exact eenmaal**
   `planner_72h.calculate_plan72` aan met:
   - `practical_windows=True`;
   - `strategy_factory=compute_strategy_bundle` (Alpha84);
   - géén extra H5.4-argument: de eerder goedgekeurde worker en
     calculator blijven beide bytegelijk.
4. `alpha84_bundle` bouwt ongewijzigd de volledige
   Energy Need -> Preview -> Plan72 -> source Action Bridge keten,
   in die volgorde op één bron-snapshot. Forecast per 15 minuten,
   losse import/exporttarieven en beschermde handmatige tijdvakken
   worden zonder verborgen prijsaggregatie doorgegeven.
5. `planner_72h` projecteert die door de bron geselecteerde
   acties met fysieke batterijlimieten en exact kwartier-SOC.
   **Geen tweede economische handelskeuze** vindt plaats.
   Fysieke gevolgen van de twee minuten opdrachtvoorbereiding,
   inclusief eventuele safety-repair, blijven apart onderwerp H5.6.
6. `planner_action_bridge_runtime` consumeert uitsluitend de
   gepubliceerde Plan72-generatie en dient géén alternatieve
   prijzen- of veiligheidsstrategie toe.
   `plan_store_writer` en Scheduler beheren lifecycle en prioriteit;
   deze worden in H6–H8 opnieuw live geverifieerd.

## Historische eigen DOEMS-routes en actuele bevinding

Het bestand `planner_72h.py` bevatte nog oudere, afwijkende strategieën:

- `_safety_schedule`: een zelfstandige numerieke veiligheidsplanner.
- `_trade_schedule`: bounded sequential trading met eigen
  kosten-/risicofilters en meerdere mogelijke trades.
- `_safety_windows`: zelfstandige 10-W kwartierzoeker.
- `_trade_windows`: fysieke routeoptimalisatie anders dan Alpha84's
  enkele beste chronologische handelspaar.

Dit zijn **wel echte implementatieverschillen** met de oorspronkelijke
Anker EMS; ze waren al niet actief in de `Plan72Runtime` van Alpha 8.10,
maar via `calculate_plan72` zonder juiste factory nog wel
aanroepbaar. In H5.4 wordt de productiegrens expliciet gezekerd:

- De in hoofdstuk 7 afgetekende bestanden zijn **allebei bytegelijk**
  aan de geïnstalleerde Alpha 8.10-bron:
  `planner_72h.py`, Git-blob
  `751ae0ac98b454c6f7290700a2d783e571ae7c51`,
  en `planner_72h_runtime.py`, Git-blob
  `f9a23be93ad239c9a17fb58fd619ca9628688c80`.
  Er is geen nieuwe parameter of algoritmeaanpassing aangebracht.
- De integratie-opstart `async_setup_entry` in `__init__.py`
  controleert vóór de eerste bron-subscriptie, Store-wijziging of
  Scheduler-start of `planner_72h_runtime.compute_strategy_bundle`
  exact verwijst naar de originele `alpha84_bundle.compute_strategy_bundle`.
- De nieuwe kleine en **beleidsloze** helper
  `alpha84_strategy_guard.original_alpha84_owner_present`
  doet uitsluitend die referentiecontrole. Ontbreekt de originele functie
  of is deze vervangen door een andere, dan retourneert het opstartpunt
  `False`: er wordt **geen Plan72Runtime gestart** en er zijn
  geen automatische acties of batterijcommando's.
- De bestaande productieaanroep blijft bytegelijk:
  `practical_windows=True, strategy_factory=compute_strategy_bundle`.
  Er is geen productieroute naar de alternatieve eigen algoritmen.
- De releasevalidator controleert de `_evaluate`-AST op de
  oorspronkelijke bronselectie én bevestigt dat de opstartgate vóór
  de initialisatie van Home Assistant-componenten staat.
- De regressietests vervangen alle vier oude strategiefuncties
  tijdelijk door foutproducerende functies; de **werkelijke**
  worker blijft correct via Alpha84 werken. Een aparte test bewijst
  dat de opstartgate zowel ontbrekende als alternatieve functies afwijst.
  De twee originele goedgekeurde Git-blobs worden afzonderlijk
  exact gecontroleerd.

Hiermee wordt de resterende mogelijkheid tot **stilzwijgende
terugval in de Home Assistant-productieplanner** weggenomen,
zonder originele Alpha84-beleidsregels te herschrijven.

## Reikwijdte / verdere open punten

- Eerdere H5.1/5.2-correcties en H5.3-resolutieverklaring blijven leidend.
- Fysieke herplanning bij ontoereikende uitvoering en de verschillen
  tussen bron-SOC en echt fysiek SOC worden **niet** stilzwijgend
  afgetekend: H5.6 is daarvoor open.
- Volledige lifecycle, Bridge-selectie, Store en Scheduler en live
  Home Assistant-controles zijn afzonderlijk H6, H7 en H8.
- Geen configuratie-, entiteits-ID-, strategie-/tijdbeleid- of
  hardwarewijziging en geen nieuwe economische beperking.
- Geen `main`-merge, batterijactivatie of release zolang de complete
  3.12 / 3.13 / 3.14 regressie en hashcontrole niet groen zijn.

**H5.4-acceptatiebewijs** wordt geregistreerd onder
`tests/test_h54_single_strategy_owner.py` en de CI-workflow
`doems-h54-alpha84-only.yml`.

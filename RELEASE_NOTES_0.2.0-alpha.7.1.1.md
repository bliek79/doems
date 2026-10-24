# DOEMS 0.2.0-alpha.7.1.1 - Planner Migration Hotfix

## Doel

Deze hotfix herstelt uitsluitend de Home Assistant entity-registrymigratie en de zichtbaarheid van de dashboardheader na de live regressie van alpha.7.1. Plannerbeleid en rekenlogica blijven ongewijzigd.

## Live regressie alpha.7.1

Na installatie van 0.2.0-alpha.7.1 stopte DOEMS tijdens setup met een RuntimeError op doems_automatic_planner. De permanente Automatic Planner entity uit een eerdere alpha.6.x testlijn stond nog geldig in de Home Assistant entity registry. De alpha.7.1 migratie behandelde dat als een fatale collision.

## Migratiefix

Wanneer een definitieve planner unique-id al bestaat, blijft die permanente DOEMS entity behouden en wordt alleen de tijdelijke alpha.7 bronentity verwijderd. Wanneer de definitieve target nog niet bestaat, wordt de tijdelijke entity normaal naar de definitieve identity gemigreerd.

Hierdoor is de migratie idempotent en kan een geldige historische Automatic Planner of Automatic SOC Projection Timeline de DOEMS setup niet meer blokkeren.

Een werkelijk conflicterende entity-id die niet bij dezelfde DOEMS permanente identity hoort blijft wel hard blokkeren; die wordt niet stil overschreven.

## Dashboardheader

De header van examples/doems_planner_dashboard.yaml is niet langer als button-card gebonden aan sensor.doems_combined_planner. De header leest die state rechtstreeks via hass.states en blijft daardoor zichtbaar tijdens startup, unavailable of een integratiefout. In dat geval toont hij Niet beschikbaar in plaats van volledig te verdwijnen.

Grafiek en dagbalans blijven sensor.doems_combined_planner als databron gebruiken.

## Ongewijzigd

- Manual Planner + Automatic Planner -> Combined Planner
- native 15 minuten / 72 uur / 288 slots
- technisch minimum 5% + software-reserve 5% = 10% standaard plannerfloor
- 92% laad- en ontlaadrendement
- manual priority en target clamp
- bruikbare-zonregel en dynamische reserve
- safety charge en normale handel
- exact 288 prijzen uit de bestaande pricebuffer
- geen automatische Plan Store writes
- Scheduler uit
- Safety/Prestart execution uit
- fysieke uitvoering uit
- peak-sale blijft gesloten.

## Live gate

Na installatie en herstart moet DOEMS zonder config-entry setup error laden. Daarna worden de zes definitieve plannerentiteiten, 288 slots/punten, known/forecast prijzen, Manual/Automatic/Combined gedrag en het dashboard live gecontroleerd. Deze hotfix is geen R5 live groen en opent R5.2 of R6 niet.

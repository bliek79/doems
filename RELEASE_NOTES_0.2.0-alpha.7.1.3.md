# DOEMS 0.2.0-alpha.7.1.3 – R5 Planner Runtime Performance & Recovery Fix

## Aanleiding
Bij alpha.7.1.2 bleef de 288-slot Automatic/Combined worker in Home Assistant op executorwerk wachten (14:04:25 op 8 oktober 2026). Live: battery-input herstelde naar ready, maar planners bleven blocked, worker_active=true, published_generation=0.

## Gerichte R5-herstelwerkzaamheden
- Verminder onbeperkte/zeer dure toekomstige-tekort x laadkandidaat x simulatiezoeklussen tot deterministisch op prijs gesorteerde laadvensters, met maximaal twee full-route kandidaatproeven per native laadslot (maximaal 576 per Automatic of Combined).
- Accepteer economische thuisvoorlading alleen wanneer de doorgerekende totale voorspelde import-/exportkosten daadwerkelijk afnemen, rekening houdend met rendement en latere gratis zon.
- Houd normale harde SOC-floor gescheiden van de informatieve need-until-solar forecast (technisch 5% + ingestelde software-reserve, gewoonlijk 5%).
- Houd Automatic zelfstandig, Combined als opnieuw berekende route met harde Manual-commitments. Geen handmatige actie = identieke Automatic/Combined-routes.
- Voeg interrupt-checkpoints toe in de native 288-slot simulatie. Nieuwe of ongeldige inputs maken lopende generatie coöperatief ongeldig; alleen nieuwste valide generatie mag atomair publiceren.
- Zorg voor maximaal één serial executor-worker en één pending latest-wins verzoek. Herstel battery unready -> ready mag een oude actieve signature niet onterecht overslaan.
- Begrens werkelijk executor-rekenwerk op 20 seconden per complete Automatic+Combined-bundel. Bij budgetoverschrijding fail-closed met `planner_compute_budget_exceeded`, nooit een verzonnen of verouderde actieve planning.
- Publiceer diagnostische counters voor simulaties, economische proefroutes, annuleringen en rekentijd om de live-test te ondersteunen.

## Vaste grenzen (niet gewijzigd)
- Native 15 minuten / rolling 72 uur / 288 slots; dezelfde openbare entiteitsnamen, dashboard en Apex.
- Manual Planner R0-R4 volledig onveranderd, drie persistente slots/lifecycle/handmatige SOC-lijn.
- Bestaande HA-options, vermogenslimieten, tarieven/provenance, dynamische-zonmarker, arbeidsverdeling Manual/Automatic/Combined.
- Geen extra helper, uitvoering, Scheduler, Safety/Prestart, peak-sale, mode-switch of fysieke batterijaansturing.

## Acceptatie en live stop
- GitHub Actions: compileall, alle pytest-contracten inclusief R5-performance/recovery/simulatiegrenzen en checksums voor bevroren modules, packaging en release-artifacts.
- **R5 blijft RED na publicatie.** Na installatie eerst in Home Assistant controleren: battery-input ready; Automatic en Combined ready + 288 slots; worker_active=false; nieuwe generatie gepubliceerd; bestaande Apex toont realistische SOC en goedkope laadmomenten.
- Pas na expliciet akkoord van gebruiker R5 live groen verklaren en de gecombineerde manual-priority scenario's live valideren. R5.2 en R6 blijven dicht.

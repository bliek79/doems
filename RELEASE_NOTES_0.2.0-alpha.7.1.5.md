# DOEMS 0.2.0-alpha.7.1.5 - R5 Sequential Automatic and Combined Planner

## Probleem in alpha.7.1.4
De Automatic en Combined Planner gebruikten één executor-berekening met één gezamenlijke 20-secondenrekengrens. Bij een overschrijding werden beide routes met planner_compute_budget_exceeded geblokkeerd, ondanks geldige Battery Input. Manual Plan Store-events veroorzaakten opnieuw de hele Automatic+Combined-berekening. De bestaande Apex-Combined-kaart bleef leeg.

## R5.1.5 gerichte reparatie
- Bij een nieuw kwartier (:00, :15, :30, :45) of relevant gewijzigde Energy/Solar/Prices/Battery-contractbron draait eerst de Automatic Planner met de volledige native rolling 72 uur / 288 slots. Pas na afronding volgt de Combined Planner.
- Automatic is geheel onafhankelijk van R2-R4. Na een geslaagde Automatic-berekening wordt de eigen 288-slotroute meteen beschikbaar en als vaste basis voor Combined in de worker-cache bewaard.
- Combined gebruikt exact dezelfde bevroren Energy/Solar/Prices/SOC-bronnen en hetzelfde Automatic-resultaat; bij **geen actieve handmatige commitments** wordt de automatische route zonder tweede economische optimalisatie overgenomen.
- Handmatig plan toevoegen/wijzigen/annuleren/vrijgeven leidt uitsluitend tot een nieuwe Combined-berekening met de laatste drie manual slots. Een in-flight Automatic-berekening wordt niet onderbroken of opnieuw gestart door zulke plan-events.
- Met één of meer actieve handmatige acties herberekent Combined vanaf dezelfde basis de automatische planning rondom de harde tijd-, vermogen- en doel-SOC-beperkingen. Handmatige acties hebben absolute prioriteit.
- Beide executorfasen behouden elk een eigen coöperatief budget van 20 seconden; een Combined-timeout mag de reeds voltooide Automatic-sensor nooit wissen. Bij een bronfout blijft fail-closed gedrag gelden voor beide.
- Single-flight executor / newest-wins events: een forecast/batterijverandering kan oudere automatische berekening vervangen, een manual event kan alleen een oudere Combined-fase vervangen. Stale output wordt nooit op een nieuwe generatie gepubliceerd.
- De sensoridentiteiten, 288 native slots, bestaande dashboard/Apex, prijsprovenance, reservebeleid uit alpha.7.1.4 en alle gebruikerinstellingen blijven behouden.
- Aanvullende bestaande sensor-attributen: Automatic/Combined stage compute counts, duur, auto published generation, manual revision, active stage en combined pending voor gecontroleerde livevalidatie.

## Freeze en scope
R0-R4 blijven byte-identiek, inclusief drie persistente handmatige planslots, lifecycle en eigen SOC-projectie. Geen physical execution, Scheduler, Safety/Prestart-uitvoering, piekverkoop, entiteitshernoeming of dashboardaanpassing.

## CI en acceptatie
Nieuwe regressies bewaken stage-indeling, nieuw kwartier, handmatige events, Automatic zonder manual, hergebruik bij Combined zonder manual, Combined met alle drie manual slots, geen hardwired handmatige prioriteit in Automatic en bestaande native schema/identity/prijscontracten. CI compileert en draait alle tests, valideert bevroren bestands-hashes en publiceert ZIP, SHA256SUMS en release notes.

**R5 blijft LIVE RED na release** totdat de gebruiker op Home Assistant aantoont dat Automatic en Combined ieder 288 slots publiceren, samen in het bestaande Combined Apex-dashboard zichtbaar zijn, iedere 15 minuten vernieuwen, handmatige wijzigingen de automatische basis niet herberekenen, en de SOC/goedkoopste-laadlogica tegen oude Anker EMS inhoudelijk klopt. R5.2/R6 blijven gesloten.

# DOEMS 0.2.0-alpha.7.1.15 - R6 to R7 Quarter-Hour Integration Fix

**Definitieve geteste R7-integratiecorrectie.** Deze release vervangt de voortijdig gepubliceerde alpha.7.1.14-tag. Installeer alpha.7.1.15, niet alpha.7.1.14. Gepubliceerde tags worden niet herschreven.

## Correctie
- De bevroren R6 Automatic/Combined-planner maakt geldige automatische kwartierplannen vanaf 0,25 uur. De gedeelde Manual-validatie en R7 Prestart legden onterecht de Manual-grens van 0,50 uur op.
- De Plan Store en R7 gebruiken nu een gezamenlijk, alleen-automatisch validatiecontract voor origin=automatic_72h_planner: 0,25 tot 12 uur, kwartierstappen, consistente start/eindtijd, actie, vermogen, doel-SOC en startmarge.
- R7 promoveert uitsluitend binnen de bestaande R7-D2-startmarge na een actuele Safety- en Prestart-goedkeuring naar softwarematig pending. Manual houdt altijd voorrang en behoudt de minimumduur van 0,50 uur en expliciete Inplannen-bediening.
- R6-optimalisatie, prijzen, native 15 minuten / 72 uur / 288 slots, de drie slots, herplanning, identiteit, R6-expiry en audit blijven ongewijzigd.
- Geen nieuwe publieke entiteiten, sensoren, helpers of dashboards. De permanente sensor blijft sensor.doems_scheduler_status. Geen fysieke batterijcommando's, R8 blijft gesloten.

## Tests en publicatie
De volledige CI controleert minimaal R6 Automatic 0,25/0,50/0,75 uur -> 3-slot Plan Store -> Scheduler/Safety/Prestart -> bewaakte software-pending -> persistentie -> R6 expiry met dezelfde planner_identity; daarnaast ongeldige duur/eindtijd, Manual-prioriteit en fysieke uitvoering UIT.

## Status en installatie
Na het installeren van alpha.7.1.15 controleert de gebruiker een automatisch voorstel van 15 minuten via de bestaande sensor.doems_plan_1_status (of 2/3) en sensor.doems_scheduler_status. Geen max_runtime_out_of_range, origine/identity correct, Safety/Prestart-gate volgens contract. Publicatie is NIET dezelfde status als R7 LIVE GROEN: daarvoor blijft Home Assistant-livevalidatie en expliciet gebruikersakkoord nodig.
R0-R6 blijven definitief LIVE GROEN, R7 LIVE VALIDATIE OPEN, R8 niet vrijgegeven, fysieke batterijbesturing uitgeschakeld.

# DOEMS 0.2.0-alpha.7.1.4 – R5 Automatic Reserve & Cheapest-Energy Policy Fix

## Waarom deze release
Alpha.7.1.3 maakte de 72-uursberekening sneller, maar de Automatic Planner projecteerde de woningontlading kunstmatig tot de 10%-planningsreserve. Daardoor kwam het voorspelde SOC nooit onder de reserve en activeerde de veiligheidsvoorlading niet. Bovendien werd de 0,10 EUR/kWh handelsmarge ten onrechte toegepast op toekomstige woninginkoop.

## Gerichte herstelwijzigingen
- Normale woningontlading mag in de fysieke simulatie dalen tot de technische 5%-ondergrens. Alleen expliciete (niet-handmatige) export-/handelsontlading gebruikt de hogere planningvloer.
- Toekomstige onderschrijding van 5% + bestaande software reserve (standaard 10%) wordt nu zichtbaar en leidt tot veiligheidsvoorlading in het goedkoopste haalbare eerdere laadslot, met herberekening van de volledige 288-slot SOC-route.
- Behoefte tot eerstvolgende bruikbare zon blijft forecastcontext en creëert nooit een 100%-hold of extra harde reserve. Zon blijft eerst, prijshorizon blijft 72 uur.
- Gewone economische voorlading voor toekomstige duurdere woningafname gebruikt batterij-roundtripverlies en werkelijke gesimuleerde nettoenergiekosten. De bestaande instelbare handelsmarge blijft uitsluitend de drempel voor optionele verkoop naar het net; instellingen zelf worden niet gewijzigd.
- Volgorde en verantwoordelijkheden: Manual R2-R4 onveranderd; Automatic onafhankelijk van handmatige acties; Combined plant opnieuw rond harde handmatige afspraken.
- Nieuwe R5-regressietests: 5% fysieke ontladingsgrens versus 10% reserveregel, goedkoopste laadslot in economisch haalbaar venster, safety onafhankelijk van handelsmarge, solar-marker stopt geen 72-uursoptimalisatie en drie handmatige planslots hebben uitsluitend in Combined prioriteit.

## Bewust niet gewijzigd
- Native forecast 15 minuten / 72 uur / 288 slots, prijzen/provenance, maximaal vermogen, efficiënties, contract/opties, dashboard, Apex, publieke entity IDs.
- R0-R4 gefixeerde modules, dataopslag en Manual Planner; geen Scheduler, Safety/Prestart uitvoering, piekverkoop, fysieke batterijbediening of nieuwe functies.
- Performance/recoveryfix alpha.7.1.3 blijft actief: gebudgetteerde executor, coöperatieve annulering, latest-wins generatievalidatie.

## Validatie en STOP
- CI: compileall, gehele pytest-suite inclusief beleids-/prestatie-/identiteitstests, JSON-validatie, bevestiging bevroren R0-R4 Git-blob-hashes, versiecontrole en packaging.
- Na publicatie blijft R5 **RED** totdat gebruiker na installatie in Home Assistant eerst Automatic vergelijkt met oude Anker EMS in de bestaande Apex, en vervolgens Combined met/zonder manual bevestigt. Geen voortgang naar R5.2 of R6 zonder expliciet live groen.

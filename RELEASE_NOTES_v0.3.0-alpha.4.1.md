# DOEMS 3.0 - Hoofdstuk 4: Energy Need

Pre-release: `v0.3.0-alpha.4.1`

## Herkomst
- Historische basis: `0.1.0-alpha.7.7` (commit `eb01911a40e01c5f01264e2a4d5e297a8ea3870d`)
- Energy Need-ontwikkeling: `doems3-energy-need-alpha77`, commit `a0ac26412d9a7837c5229d0dac9ae3f744e7939a`
- Architectuurdocument: DOEMS 3.0, hoofdstuk 4 - Energy Need

## Inhoud
- Alleen-lezen Energy Need berekening op basis van de bestaande Energy en Solar Forecast, 72 uur en 288 kwartieren.
- Configuratie voor SOC-bronentiteit, batterijcapaciteit, minimum-SOC, veiligheidsreserve en rendementen.
- Tien sensoren en een binaire geldigheidssensor met `doems_ems_` prefix.
- De module is standaard uitgeschakeld tot expliciete configuratie.
- Geen fysieke batterijcommando's of Plan72-uitvoering.

## Controle en beperking
- Broncode- en contracttests op de ontwikkelbranch geslaagd: 57 tests.
- Deze pre-release is bedoeld voor live-validatie in Home Assistant. Live werking en correcte entiteitregistratie zijn nog niet aangetoond.
- Controleer eerst de bestaande forecastentiteiten en activeer pas dan Energy Need in de DOEMS opties.
- Niet gebruiken voor fysieke batterijaansturing.

## Testpunten Home Assistant
1. Energy Forecast Timeline en Solar Forecast Timeline leveren beide 288 kwartieren.
2. Stel SOC-entiteit, batterijcapaciteit, minimum-SOC, reserve en beide rendementen expliciet in.
3. Controleer alle elf `doems_ems_` entiteiten en hun unieke ID's.
4. Wijzigingen in SOC en forecastbronnen werken door in de uitkomsten.
5. Bij verouderde of onvolledige forecast wordt `Energy Need Valid` onwaar.
6. Controleer afwijkende situaties en vergelijk de resultaten met de prognose.

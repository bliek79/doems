# DOEMS 3.0 Alpha 5.1 Plan72

Deze releasekandidaat voegt hoofdstuk 5 toe: een observerende planner die de energiestromen en batterij-SOC voor **72 uur in 288 kwartieren** berekent. De ontwikkelbasis is `v0.3.0-alpha.4.3`, commit `75516b5aa99282b03b91c1f5b534c02b7b07ce82`. De bestaande forecasts en elf Energy Need-entiteiten blijven behouden.

Publicatie volgt uitsluitend via de automatische releasecontroles. De livevalidatie van Plan72 in Home Assistant staat nog open.

## Wat is toegevoegd

- Eén opeenvolgende projectie van woningvraag, PV, batterij-inhoud, netafname en netexport, met afzonderlijke laad-/ontlaadstromen en omzettingsverliezen.
- Begrenzing op dynamische capaciteit, SOC, hardwareminimum, extra reserve en expliciet ingestelde laad-/ontlaadvermogens.
- Noodzakelijke netlaadmomenten vóór verwachte tekorten en een afzonderlijke, begrensde beoordeling van handelsmogelijkheden.
- Bescherming van voorziene PV-batterijlading tegen verdringing door automatische handel.
- Behoud van afzonderlijke import-/exporttarieven, bekende-prijsvoorrang en de oorspronkelijke prijsresolutie per kwartier.
- 32 nieuwe sensoren en drie binaire sensoren met de prefix `doems_ems_plan72_`.
- Herberekening via één worker, samenvoegen van identieke invoer en verwerpen van achterhaalde uitkomsten.
- Een optionele [validatiekaart](examples/plan72_validation_card.yaml) met standaard Home Assistant-kaarten.

Plan72 berekent alleen. Het wijzigt geen batterijmodus of hardwareinstelling, vult geen planslots en voert geen batterijcommando's uit. De pure rekenmodule ondersteunt handmatige constraints; aansluiting op de HA-planslots volgt in hoofdstuk 7.

## Installeren en instellen na publicatie

1. Selecteer in HACS voor DOEMS expliciet **`v0.3.0-alpha.5.1`** zodra deze pre-release beschikbaar is. Werk de integratie bij en herstart Home Assistant.
2. Open **Instellingen → Apparaten en diensten → DOEMS → Configureren**.
3. Behoud of activeer **Energy Forecast, Solar Foundation, Prices Forecast en Energy Need**. Schakel ook **Plan72** in. Plan72 staat na een upgrade standaard uit zolang het niet eerder is geconfigureerd.
4. Controleer de bestaande Energy Need-bronnen voor SOC, accucapaciteit en hardware-ontladingslimiet, plus de gewenste extra reserve en het roundtrip-rendement.
5. Vul voor Plan72 de daadwerkelijk toegestane laad- en ontlaadgrenzen in watt in. Gebruik per richting de laagste grens van batterij en installatie. Voor de eerder besproken installatie was 3.200 W per richting afgesproken; deze waarden worden niet automatisch door de software ingevuld.
6. De standaard minimale handelsmarge is **0,10 EUR per extra geëxporteerde AC-kWh**. **Handelsmogelijkheden berekenen** staat standaard aan binnen Plan72. Dit geeft geen uitvoeringsbevoegdheid.
7. Rond alle configuratiestappen af. Controleer daarna de bestaande Energy Need-entiteiten en de 35 nieuwe Plan72-entiteiten. De optionele validatiekaart kan als afzonderlijke kaart worden toegevoegd; een bestaand dashboard hoeft niet vervangen te worden.

## Uitkomsten lezen

`ready` betekent dat het model een geldige route zonder de vastgestelde beperkingen heeft berekend. `limited` kan eveneens een geldige berekening zijn: de tijdlijn toont dan bijvoorbeeld een reserveonderschrijding, resterend fysiek tekort of beperkte handmatige actie. **Plan72 Valid** zegt uitsluitend iets over de berekening; uitvoering blijft uitgeschakeld.

**Plan72 Reserve** is hardwareminimum plus extra reserve in batterij-kWh. **Reserve Satisfied** beoordeelt de hele route, inclusief de begin-SOC en het laagste punt binnen kwartieren. Een aan het begin aanwezige onderschrijding blijft zichtbaar als die later wordt hersteld.

**Remaining Charge Need** is een diagnoseschatting, geen laadopdracht. **Grid Import** betreft resterende woningafname; de batterijlaadstromen staan apart. Alle stromen zijn AC-kWh, terwijl reserve en opgeslagen inhoud batterij-kWh zijn.

Wanneer geen handel is geaccepteerd, kunnen beste handelstijden en -prijzen onbekend blijven bij een geldige planning. De beste handelsvelden beschrijven de werkelijk geaccepteerde modelroute met de hoogste berekende marge, niet simpelweg de goedkoopste en duurste losse prijs.

De horizon begint op het eerstvolgende volledige kwartier. De meest recente gemeten SOC wordt daarvoor als begin-SOC aangenomen. `timeline.sources` toont het SOC-meettijdstip indien beschikbaar, deze aanname en het aantal niet-gemodelleerde beginminuten.

## Resterende validatie en modelgrenzen

De volledige route werkt met gelijkmatige vermogens binnen een kwartier en een eindige horizon van 72 uur. De handelszoeker is begrensd; een globaal optimale opbrengst wordt niet geclaimd. Een bronfout of ongeldige waarde moet een ongeldige projectie opleveren in plaats van een oude geldige tijdlijn.

Controleer in Home Assistant de bronwaarden, 288 tijdslots, reservebetekenis, natuurlijke SOC-herberekening en verklaringen bij `limited`/`invalid`. Livewerking en uitvalgedrag worden afzonderlijk vastgelegd. Hoofdstuk 5 geeft geen vrijgave voor fysieke uitvoering.

De volledige technische beschrijving en alle entity-ID's staan in [DOEMS 3.0 hoofdstuk 5 Plan72](docs/DOEMS3_CHAPTER5_PLAN72.md).

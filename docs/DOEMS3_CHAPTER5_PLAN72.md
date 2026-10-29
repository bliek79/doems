# DOEMS 3.0 hoofdstuk 5 Plan72

Plan72 berekent de energiestromen en batterij-SOC voor de volgende 72 uur. Dit hoofdstuk voegt één observerende rekenmodule aan de bestaande forecastbasis en Energy Need toe. Het resultaat beschrijft een mogelijke route; fysieke uitvoering, planslotbeheer en de uitvoeringsveiligheidsketen behoren tot latere hoofdstukken.

De code is bestemd voor `v0.3.0-alpha.5.2`, de gerichte tolerantiecorrectie op Alpha 5.1. De basis is de functioneel gevalideerde hoofdstuk-4-release [`v0.3.0-alpha.4.3`](https://github.com/bliek79/doems/releases/tag/v0.3.0-alpha.4.3), commit [`75516b5aa99282b03b91c1f5b534c02b7b07ce82`](https://github.com/bliek79/doems/commit/75516b5aa99282b03b91c1f5b534c02b7b07ce82). De historische Alpha7.7-basis wordt niet opnieuw gestart. De bestaande elf Energy Need-entiteiten blijven behouden.

Publicatie wordt door automatische controles bewaakt. Eerste livewaarnemingen van Alpha 5.1 leidden tot de met synthetische scenario's gereproduceerde correctie hieronder. De livehercontrole van Alpha 5.2 en de volledige functionele aftekening van hoofdstuk 5 staan nog open.

## 1 Verantwoordelijkheden

| Onderdeel | Verantwoordelijkheid |
| --- | --- |
| Energy Need, hoofdstuk 4 | Huishoudelijke behoefte, extra reserve, beschikbare batterijenergie en theoretische tekorten berekenen. |
| Plan72, hoofdstuk 5 | Eén opeenvolgende 288-kwartierenroute met fysiek begrensde energiestromen, SOC, verklaringen en handelsafwegingen berekenen. |
| Automatic Action Bridge, hoofdstuk 6 | Later geschikte expliciete acties vertalen naar concrete uitvoeringsvensters. |
| Persistent Plan Store, hoofdstuk 7 | Later de drie persistente planslots beheren en handmatige invoer aan de keten verbinden. |
| Scheduler en veiligheidsketen, hoofdstukken 8 tot en met 11 | Later startmomenten, bevoegdheid en actuele veiligheid beoordelen. |
| Execution Controller, hoofdstuk 12 | Later exclusieve fysieke aansturing en uitvoeringsbewaking verzorgen. |

Plan72 introduceert geen tweede controller, geen diensten voor batterijaansturing en geen writes naar planslots. De uitvoer draagt `observational_only: true`, `execution_enabled: false` en in de runtime ook `physical_execution_authority: false`.

## 2 Bestanden

| Bestand | Functie |
| --- | --- |
| `custom_components/doems/planner_72h.py` | Pure deterministische rekenmodule, inclusief gesegmenteerde simulatie en handmatige invoer. |
| `custom_components/doems/planner_72h_runtime.py` | Bronkopie, validatie, workerbeheer, herberekening en 35 HA-entiteiten. |
| `custom_components/doems/prices.py` | Alleen-lezende selectie van een exact prijsvenster uit de bestaande buffer. |
| `custom_components/doems/solar_forecast.py` | Alleen-lezende selectie van een exact zonneforecastvenster. |
| `custom_components/doems/config_flow.py` | Activering, bronafhankelijkheden en expliciete plannerinstellingen. |
| `examples/plan72_validation_card.yaml` | Optionele controlekaart met standaard Home Assistant-kaarten. |

`__init__.py`, `sensor.py` en `binary_sensor.py` verbinden de module met de bestaande integratie. De hoofdstuk-4-rekenfunctie en bestaande entiteits-ID's worden niet hernoemd of vervangen.

## 3 Configuratie

Plan72 staat standaard uit. Voor activering moeten Energy Forecast, Solar Foundation, Prices Forecast en Energy Need zijn ingeschakeld. De configuratie bewaart bestaande opties en vraagt de toegestane vermogensgrenzen expliciet uit.

| Optie | Eenheid | Standaard of vereiste |
| --- | --- | --- |
| `plan72_enabled` | boolean | `false`; gebruiker schakelt Plan72 in. |
| `plan72_max_charge_power_w` | W | Verplicht bij activering, groter dan nul; geen geraden standaardwaarde. |
| `plan72_max_discharge_power_w` | W | Verplicht bij activering, groter dan nul; geen geraden standaardwaarde. |
| `plan72_minimum_trade_margin` | EUR/kWh | `0.10` per extra aan het net geleverde AC-kWh. |
| `plan72_trade_enabled` | boolean | `true`; betreft het berekenen van handelsmogelijkheden. |

Gebruik per richting de laagste toegestane vermogensgrens van batterij en installatie. De opties zijn rekenlimieten: het opslaan ervan wijzigt geen instelling van de Anker. De eerder besproken installatiegrenzen van 3.200 W per richting worden alleen gebruikt als de gebruiker die expliciet invult; ze zijn geen ingebouwde defaults.

De volgende hoofdstuk-4-opties worden hergebruikt:

- `energy_need_soc_entity`: actuele SOC-bron in procenten;
- `energy_need_capacity_entity`: actuele capaciteit in kWh;
- `energy_need_min_soc_entity`: hardware-ontladingslimiet in procenten;
- `energy_need_reserve_percent`: extra reserve boven het hardwareminimum;
- `energy_need_roundtrip_efficiency`: volledige-cyclusrendement in procenten.

Het ingestelde roundtrip-rendement wordt symmetrisch verdeeld: `eta_laden = eta_ontladen = sqrt(roundtrip / 100)`. Bij 84,64% levert dat 92% per richting op. Capaciteit en ondergrens worden uit de gekozen bronnen gelezen en niet als vaste 7,2 kWh of 5% in de planner ingebouwd.

Een oudere configuratie zonder nieuwe planneropties laat de bestaande integratie bruikbaar. Wanneer Plan72 wel is aangezet maar invoer ontbreekt, publiceert de runtime een ongeldige berekening met een reden.

## 4 Tijdlijn en broncontract

De horizon bestaat uit 288 opeenvolgende kwartieren van 0,25 uur. Starttijden zijn timezone-aware en worden in UTC gekoppeld. Bij een exact kwartier begint de horizon op die grens; anders op de eerstvolgende volledige kwartiergrens. UTC maakt de tijdstappen ook tijdens een zomer-/wintertijdwisseling uniek. Home Assistant kan de tijdstippen lokaal weergeven.

| Invoer | Bestaande broninterface | Gebruikte grootheden |
| --- | --- | --- |
| Woning | `DOEMSEnergyCoordinator.forecast(now=...)` | `start`, `energy_kwh` per kwartier. |
| Zon | `SolarForecastManager.forecast_window(start=..., slot_count=288)` | `start`, `total_kwh` per kwartier. |
| Prijzen | `DOEMSPricesManager.forecast_window(start=..., slot_count=288)` | `start`, `import_all_in`, `export_all_in`, `kind`, `source_resolution_minutes`. |
| Batterij | Geselecteerde HA-statebronnen | SOC, capaciteit, hardwareminimum en bron-eenheden. |
| Energy Need | De bestaande pure `calculate_energy_need()` | Berekening tegen dezelfde bevroren invoer als Plan72. |

De publieke prijslijst is een snapshot van de laatste providerrefresh. Daarom gebruikt Plan72 de bestaande buffer van maximaal 304 kwartieren en zoekt ieder gewenst tijdstip exact op. Drie lijsten met elk 288 items worden niet op positie aan elkaar gekoppeld. Een ontbrekende prijs of zonneforecastwaarde wordt niet vervangen door de waarde van een buurkwartier of een verzonnen nul.

Bekende prijzen houden hun bestaande voorrang op voorspellingen. Een uurprijs kan vier kwartieren bestrijken, maar blijft herkenbaar als bron met `source_resolution_minutes: 60`. Plan72 berekent geen nieuwe import-/exporttoeslagen. Het gebruikt de afzonderlijke bestaande all-in tarieven. Negatieve eindige prijzen zijn geldige invoer.

De runtime vereist de bestaande zonnebronstatus `ok`, prijsstatus `ok` en prijsfreshness `fresh`. De geldigheids- en verouderingsregels van de bronmanagers worden daarmee gebruikt; er wordt geen nieuwe confidence-drempel verzonnen. De rekenketen controleert daarnaast onder meer ontbrekende waarden, dubbele/afwijkende tijdstippen, niet-eindige getallen en onmogelijke batterijparameters.

### Aanname tussen meting en eerste volledige kwartier

De laatste gemeten SOC wordt als begin-SOC bij de volgende volledige kwartiergrens gebruikt. Het onvolledige huidige kwartier wordt niet met synthetische energie aangevuld. Bij een berekening om 10:16 begint de route bijvoorbeeld om 10:30; de 14 tussenliggende minuten zijn niet gemodelleerd.

De tijdlijnattributen leggen dit vast:

- `input_captured_at`: moment waarop de invoer is vastgelegd;
- `calculated_at`: moment waarop het resultaat is gepubliceerd;
- `sources.soc_observed_at`: `last_updated` van de SOC-state indien beschikbaar;
- `sources.horizon_start_assumption`: `latest_measured_soc_at_next_complete_quarter`;
- `sources.unmodelled_start_minutes`: lengte van de niet-gemodelleerde beginperiode;
- `input_fingerprint` en `plan_generation`: koppeling tussen invoer en resultaat.

Dit is een zichtbare beperking van de observerende projectie. De latere pre-start- en uitvoeringsketen moet opnieuw actuele gegevens beoordelen.

## 5 Rekenregels en energiebasis

Alle energiestromen tussen woning, net, PV en batterijomvormer zijn AC-kWh. `stored_start_kwh`, `stored_end_kwh`, batterijbeschikbaarheid en reservering zijn batterij-inhoud in kWh. Deze grootheden mogen niet zonder rendementscorrectie bij elkaar worden opgeteld.

```text
begininhoud = capaciteit × SOC / 100
hardwareminimum = capaciteit × minimum_SOC / 100
extra_reserve = capaciteit × extra_reservepercentage / 100
reservetarget = hardwareminimum + extra_reserve

eindinhoud = begininhoud
            + AC_laadenergie × eta_laden
            - AC_ontlaadenergie / eta_ontladen

maximale_AC_energie_binnen_segment = maximaal_vermogen_in_kW × segmentduur_in_uren
```

PV voorziet eerst de woning. De resterende PV kan de batterij laden voor zover capaciteit, beschikbare laadruimte en gezamenlijk laadvermogen dit toelaten. Normale ontlading levert energie aan de woning tot het hardwareminimum. Dit model volgt normale `self_consumption`; de extra software-reserve is een plandoel, geen verondersteld fysiek vasthoudcommando.

Noodzakelijke netlaadvensters worden vóór de betreffende tekorten gezocht en op prijs gerangschikt. Iedere voorgestelde wijziging wordt in de opeenvolgende route doorgerekend. Energie die later wordt geladen, kan geen eerder tekort dekken. Laden stopt bij haalbare laadruimte; ontladen wordt door beschikbare inhoud en de geldende ondergrens begrensd. Een te grote theoretische Energy Need wordt daardoor over meerdere haalbare momenten verdeeld of als resterend tekort zichtbaar.

De simulatie onderscheidt passieve zonne-/woningstromen van expliciete veiligheidslading, handelslading/-ontlading en aangeleverde handmatige acties. Expliciete acties en de passieve rest van een kwartier hebben afzonderlijke tijdsegmenten. Bij gecombineerd PV- en netladen geldt één totale batterijvermogensgrens.

### Reserve en beperkte routes

`Plan72 Reserve` is de totale inhoud bij hardwareminimum plus extra reserve. Het bestaande hoofdstuk-4-veld `Safety Reserve` blijft alleen de extra reserve betekenen. Er wordt geen aanvullende vaste uitvoeringsbuffer toegevoegd.

`reserve_breach_count` telt kwartieren waarin de laagste inhoud onder het reservetarget komt, inclusief de werkelijk aangeleverde begin-SOC. Een onderschrijding die later binnen hetzelfde kwartier wordt hersteld, blijft daarmee zichtbaar. `reserve_satisfied` is alleen waar wanneer de volledige geprojecteerde route geen dergelijke onderschrijding bevat.

De pure rekenuitkomst bevat daarnaast `reserve_end_breach_count` en `deadline_reserve_satisfied` voor de eindstanden van kwartieren. Tijdlijnregels bevatten zowel `reserve_min_gap_kwh` als `reserve_gap_kwh`. Deze onderscheiden een tussentijdse onderschrijding van een tekort dat aan het kwartiereinde blijft bestaan.

`remaining_charge_need_kwh` is een diagnoseschatting in benodigde AC-laadenergie: de grootste resterende reserveafstand aan een kwartiereinde gedeeld door het laadrendement, plus het relevante ongedekte woningdeel gedeeld door het roundtrip-rendement. Dit betreft een tekort in de batterijdekking; resterende woningvraag verschijnt als netafname en wordt niet als stroomuitval gemodelleerd. Het is geen direct laadcommando en geen garantie dat dit volume in een beschikbaar venster past. Een herstelde beginonderschrijding kan tot `limited` leiden terwijl deze resterende behoefte nul is.

Alpha 5.2 corrigeert twee samenhangende numerieke fouten: opeenvolgende handelsstappen konden telkens opnieuw tolerantie toestaan ten opzichte van de vorige route, en status en reden vergeleken batterij- en AC-energie met dezelfde numerieke grens. De handelscontrole bewaakt nu de vaste route vóór de handelsstappen én de gezamenlijke resterende behoefte over de horizon. Een reeds aanwezige kleine restwaarde krijgt geen tweede tolerantie bovenop de oorspronkelijke grens.

De batterijzijdige tolerantie blijft **0,00001 kWh (0,01 Wh)**; zij is niet vergroot. `remaining_charge_need_tolerance_kwh` is die tolerantie omgerekend naar AC-kWh door te delen door het laadrendement; de HA-sensor toont haar als attribuut `numerical_tolerance_kwh`. De ruwe AC-restwaarde blijft ook onder deze bijbehorende AC-grens zichtbaar. Status en reden gebruiken dezelfde batterijzijdige tekorttoets. Een tekort boven de toepasselijke grens blijft `limited`, ook als de weergave op twee decimalen `0.00 kWh` toont. Werkelijke reserveonderschrijdingen en handmatige beperkingen houden hun afzonderlijke betekenis.

### Handel

Handel is een tweede rekenstap na de huishoudelijke route. De planner vergelijkt een kandidaat met de volledige voorafgaande route. De werkelijke verandering van importkosten en exportopbrengsten, inclusief omzettingsverliezen en verdrongen stromen, bepaalt de gerealiseerde modelmarge per extra geëxporteerde AC-kWh.

```text
effectieve_netlaadkosten = importprijs / (eta_laden × eta_ontladen)
modelmarge = verbetering_van_totale_horizonkosten / extra_geëxporteerde_AC_kWh
```

Alleen een kandidaat die de beschermde huishoudelijke route, reservering en reeds haalbare handmatige doelen respecteert, mag worden geaccepteerd. Automatische handel mag bovendien geen PV-batterijlading uit de beschermde referentieroute verdringen. Daarmee blijft laadruimte voor de al voorziene eigen zonnestroom beschermd. De ingestelde minimale marge geldt voor die daadwerkelijke routeverbetering. Bewuste batterijexport bij een negatieve all-in exportprijs wordt geblokkeerd. Rechtstreekse PV-export kan in de projectie nog voorkomen; deze module regelt of begrenst de omvormer niet.

De handelszoeker onderzoekt een begrensde selectie kandidaten. `globally_optimal` is `false`; `trade.search_limited`, `evaluated_count` en `candidate_count` maken het onderscheid tussen kandidaten en onderzochte routes zichtbaar. De beste handelsvelden beschrijven de geaccepteerde route met de hoogste berekende modelmarge. Het zijn geen losstaande laagste/hoogste prijzen uit de hele horizon. De `trade`-attributen bevatten ook de totale gemodelleerde kostenverbetering en gewogen gezamenlijke marge.

Wanneer geen handel wordt geaccepteerd, blijven beste handelstijden en -prijzen `unknown`/`None`. Dat maakt een verder geldige Plan72-projectie niet ongeldig. Bij verkoop van al beschikbaar overschot zonder bijbehorende netlaadactie kan ook alleen de beste laadtijd/-prijs ontbreken.

## 6 Status en Home Assistant-entiteiten

| Status | Betekenis |
| --- | --- |
| `calculating` | Nieuwe invoer wordt doorgerekend; `valid` is uit en een eerdere tijdlijn wordt niet als actueel getoond. |
| `ready` | Geldige route zonder de door het model vastgestelde beperkingen. |
| `limited` | Geldige route met een zichtbare reserveonderschrijding, resterend fysiek tekort of begrensde handmatige actie. |
| `invalid` | Vereiste invoer ontbreekt/is ongeldig of de berekening is mislukt; geen geldige tijdlijn. |

`valid: true` betekent uitsluitend dat de berekening geldig is. Het is geen vrijgave voor uitvoering. Bij `invalid` worden numerieke voorspellingen onbekend; er worden geen fictieve nul-kWh-resultaten getoond.

Er zijn **32 nieuwe sensoren en drie binaire sensoren**. Onderstaande IDs zijn de voorgestelde object-ID's en unique-ID-conventie van de implementatie. Een bestaande registratie, naamconflict of handmatig hernoemde HA-entiteit kan lokaal een ander entity-ID opleveren. De 35 unique IDs blijven in Alpha 5.2 gelijk.

| Entiteit-ID | Eenheid | Betekenis |
| --- | --- | --- |
| `sensor.doems_ems_plan72_status` | tekst | Berekeningsstatus. |
| `sensor.doems_ems_plan72_reason` | tekst | Reden voor de huidige status. |
| `sensor.doems_ems_plan72_hours` | h | Horizon van een geldige berekening, 72 uur. |
| `sensor.doems_ems_plan72_timeline` | aantal | 288 kwartieren; de volledige route en herkomst staan in attributen. |
| `sensor.doems_ems_plan72_start_soc` | % | Aangeleverde gemeten SOC die als begin-SOC wordt gebruikt. |
| `sensor.doems_ems_plan72_end_soc` | % | Verwachte SOC aan het einde van de horizon. |
| `sensor.doems_ems_plan72_minimum_soc` | % | Laagste geprojecteerde SOC, inclusief begin en segmenten. |
| `sensor.doems_ems_plan72_maximum_soc` | % | Hoogste geprojecteerde SOC. |
| `sensor.doems_ems_plan72_reserve_target_soc` | % | Hardwareminimum plus extra reservepercentage. |
| `sensor.doems_ems_plan72_reserve` | kWh batterij | Totale reserve-inhoud bij dat SOC-target. |
| `sensor.doems_ems_plan72_reserve_breaches` | aantal | Kwartieren met een reserveonderschrijding op enig moment. |
| `sensor.doems_ems_plan72_remaining_charge_need` | kWh AC | Resterende laadbehoeftediagnose; geen uitvoerbaar opdrachtvolume. |
| `sensor.doems_ems_plan72_solar_charge` | kWh AC | PV-energie naar de batterij vóór laadverliezen. |
| `sensor.doems_ems_plan72_safety_charge` | kWh AC | Netlading voor huishoudelijke behoefte en reservering. |
| `sensor.doems_ems_plan72_trade_charge` | kWh AC | Netlading voor geaccepteerde handel. |
| `sensor.doems_ems_plan72_manual_charge` | kWh AC | Netlaaddeel van aangeleverde handmatige acties; HA-invoer is in dit hoofdstuk nog leeg. |
| `sensor.doems_ems_plan72_home_discharge` | kWh AC | Batterij-energie aan de woning na ontlaadverliezen. |
| `sensor.doems_ems_plan72_grid_discharge` | kWh AC | Batterij-export naar het net, exclusief rechtstreekse PV-export. |
| `sensor.doems_ems_plan72_manual_grid_discharge` | kWh AC | Netexportdeel van handmatige batterijontlading. |
| `sensor.doems_ems_plan72_grid_import` | kWh AC | Resterende netafname voor de woning; batterijlaadstromen staan apart. |
| `sensor.doems_ems_plan72_solar_export` | kWh AC | Rechtstreekse PV-export na woningvraag en haalbaar batterijladen. |
| `sensor.doems_ems_plan72_losses` | kWh | Gemodelleerde laad- en ontlaadverliezen samen. |
| `sensor.doems_ems_plan72_best_charge_time` | tijdstip | Laadmoment van de beste geaccepteerde handelsroute, indien aanwezig. |
| `sensor.doems_ems_plan72_best_discharge_time` | tijdstip | Verkoopmoment van de beste geaccepteerde handelsroute. |
| `sensor.doems_ems_plan72_best_charge_price` | EUR/kWh | All-in importprijs van die handelsroute, indien aanwezig. |
| `sensor.doems_ems_plan72_best_discharge_price` | EUR/kWh | All-in exportprijs van die handelsroute. |
| `sensor.doems_ems_plan72_effective_charge_cost` | EUR/kWh | Importprijs van die route gedeeld door roundtrip-rendement. |
| `sensor.doems_ems_plan72_expected_trade_margin` | EUR/kWh | Hoogste geaccepteerde modelmarge per extra geëxporteerde AC-kWh. |
| `sensor.doems_ems_plan72_trade_candidates` | aantal | Theoretische handelskandidaten vóór de begrensde routetoets. |
| `sensor.doems_ems_plan72_trade_accepted` | aantal | Geaccepteerde handelsverbeteringen. |
| `sensor.doems_ems_plan72_manual_plans` | aantal | Geaccepteerde aangeleverde handmatige plannen; HA-runtime levert nu nul aan. |
| `sensor.doems_ems_plan72_replan_reason` | tekst | Gebeurtenis die tot de huidige berekening leidde. |
| `binary_sensor.doems_ems_plan72_valid` | aan/uit | Geldigheid van de berekening; nooit uitvoeringsbevoegdheid. |
| `binary_sensor.doems_ems_plan72_reserve_satisfied` | aan/uit | Volledige geprojecteerde route blijft boven het reservetarget. |
| `binary_sensor.doems_ems_plan72_trade_profitable` | aan/uit | Er is minimaal één geaccepteerde handelsverbetering. |

De attributen van `timeline` bevatten de kwartierregels, `energy_need` voor dezelfde invoer, `sources`, `trade` en `manual`. De grote attributen worden niet in Recorder-historie opgenomen. Tijdstipsensoren gebruiken echte timezone-aware datetime-waarden. De validatiekaart is een optioneel voorbeeld; bestaande dashboards worden niet gewijzigd.

### Bestaande entiteitsregistraties en kaartbindingen

Een oude registratie kan als `unavailable` met `restored: true` aanwezig blijven terwijl de actuele entiteit onder een ID met een nummerachtervoegsel bestaat. Controleer bij een ontbrekende kaartwaarde eerst de werkelijke IDs, states en `plan_generation` in Ontwikkelaarstools. Verbind de lokale kaart met de actieve entiteit. Achtervoegsels zoals `_2` zijn installatiespecifiek en worden daarom niet in het generieke voorbeeld opgenomen. Alpha 5.2 hernoemt of verwijdert geen registry-items automatisch.

## 7 Handmatige invoer en toekomstige aansluiting

De pure functie `calculate_plan72(..., manual_plans=...)` kan handmatige plannen als constraints ontvangen. Een plan bevat een unieke `id`, `action` (`charge` of `discharge`), timezone-aware `start_time`, positief `max_runtime_h`, positief `power_w` en `target_soc`. `enabled` en `lifecycle_status`/`lifecycle` bepalen mede of een plan wordt meegenomen.

Overlappende of ongeldige uitvoerbare handmatige plannen maken de invoer ongeldig. Inactieve, verlopen of reeds gemiste plannen krijgen een diagnostische reden. Een actieve voortzetting start vanuit de aangeleverde SOC en telt geen reeds verstreken energie opnieuw mee. Deelkwartieren worden naar hun werkelijke duur gesimuleerd. Een eenmaal bereikt doel wordt binnen dezelfde handmatige actie niet opnieuw gestart doordat de passieve SOC later verandert.

Handmatige acties hebben in de rekenmodule voorrang op automatische kandidaten binnen hun tijdvensters. Zij blijven aan fysieke grenzen en exportbeperkingen gebonden. Een vermogensbegrenzing of het niet bereiken van een target binnen de maximale duur blijft zichtbaar als beperking.

De Home Assistant-runtime levert in dit hoofdstuk bewust `manual_plans=()`. De drie persistente slots worden niet gelezen, aangemaakt of ingevuld. De koppeling met die slots hoort bij hoofdstuk 7; de aanwezigheid van de pure API bewijst geen live handmatige uitvoeringsketen.

## 8 Runtime en herberekening

De eventloop leest bronnen en instellingen en maakt een eigen onveranderlijke invoerkopie. Eén executorworker doet de zuivere berekening. HA-states worden niet vanuit die worker gelezen. Het resultaat bevat geen verwijzingen naar veranderlijke HA-objecten.

De runtime reageert op woning-/zonneforecast, prijzen, Energy Need, de drie batterijbronnen en de kwartiergrens. Identieke invoer wordt via een fingerprint samengevoegd; een gas-only melding van de prijsmanager veroorzaakt dus geen nieuwe elektriciteitsberekening zolang de relevante invoer gelijk blijft.

Bij nieuwe invoer wordt een oude berekening direct ongeldig. Tijdens een lopende worker wordt alleen de nieuwste opvolgende invoer bewaard. Een uitkomst van een inmiddels achterhaalde generatie wordt niet gepubliceerd. Bij afronding worden ook de kwartiergrens en de actuele bronstatussen gecontroleerd. Bij unload worden eerst Plan72-listeners en publicatie gestopt voordat afhankelijke managers verdwijnen.

## 9 Controles en livevalidatie

De repository bevat tests voor de rekenmodule, handmatige constraints, adversariële energie-/vermogensscenario's, configuratiemigratie, runtimegebeurtenissen en publicatiecontroles. De release moet aan de automatische controles voldoen. De definitieve CI-run, commit en release-identificatie horen bij de daadwerkelijke publicatie en worden niet uit alleen deze tekst afgeleid.

De volledige lokale testset voor de Alpha 5.2-correctie telt **171 geslaagde tests**. De aanvullende regressies gebruiken synthetische invoer en controleren herhaald tolerantiegebruik bij handel, een reeds aanwezige kleine restwaarde, de omzetting tussen batterij- en AC-kWh, behoud van de ruwe restwaarde en optelling van kleine woningtekorten over de horizon. Private HA-bronwaarden zijn geen onderdeel van deze fixtures. De hercontrole van Alpha 5.2 in Home Assistant staat nog open.

Na installatie in Home Assistant moeten afzonderlijk worden gecontroleerd:

1. De bestaande elf Energy Need-entiteiten blijven beschikbaar en werken zoals in hoofdstuk 4.
2. Activering van Plan72 maakt de 35 nieuwe entiteiten beschikbaar.
3. Een geldige route heeft 288 kwartieren en 72 uur, met identieke tijdstippen voor vraag, PV en tarieven.
4. SOC, capaciteit, hardwareminimum, extra reserve, rendement en gekozen vermogenslimieten komen overeen met de bedoelde invoer.
5. Een natuurlijke SOC-verandering verschijnt in de volgende projectie; herkomst en generatie zijn zichtbaar.
6. `limited` en reserveonderschrijdingen worden inhoudelijk bekeken. Onbekende beste handelstijden zonder geaccepteerde handel zijn op zichzelf geen storing.
7. Ontbrekende/ongeldige bronnen mogen geen oude geldige tijdlijn laten staan. Niet reeds in de praktijk waargenomen uitvalsituaties blijven open livevalidatiepunten.
8. Het observerende karakter blijft zichtbaar; dit hoofdstuk introduceert geen fysieke laad-/ontlaadproef.

## 10 Grenzen van het model

- Vraag en PV worden binnen ieder kwartier als gelijkmatige vermogens behandeld. De segmentberekening modelleert geen niet-gemeten pieken binnen dat kwartier.
- De begin-SOC bij de eerstvolgende volledige kwartiergrens is een expliciete aanname; het tussenliggende tijdsdeel wordt niet voorspeld.
- De berekening heeft een eindige horizon van 72 uur. Zij bewijst niet dat huishoudelijke behoefte of reservering buiten die horizon gedekt is.
- De handelszoeker is begrensd en deterministisch; een wereldwijd optimaal of maximaal winstgevend plan wordt niet geclaimd.
- Forecasts blijven verwachtingen. Plan72 kan de kwaliteit van toekomstige vraag, zon of prijs niet afdwingen en introduceert geen aansturing of garantie voorbij de horizon.
- De ingestelde vermogensgrenzen zijn scenario-invoer. Latere uitvoeringsonderdelen moeten actuele toestelgrenzen en exclusieve besturingsbevoegdheid opnieuw controleren.
- Fysieke uitvoering, slotbeheer, startvertraging, onafhankelijke veiligheidslagen en livevalidatie daarvan zijn met hoofdstuk 5 niet gerealiseerd of goedgekeurd.

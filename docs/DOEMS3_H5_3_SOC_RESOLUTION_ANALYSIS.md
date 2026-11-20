# DOEMS 3.0 — H5.3 SOC-bronvergelijking met originele Anker Alpha84

## Referentie en besluit

- Bevroren originele Anker EMS: `bliek79/dummy-os-anker-ems`,
  tag `0.0.1-alpha.84`, commit `6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d`.
- Uitgangspunt: DOEMS Alpha 8.9 met de H5.2-regressies van PR #117.
- **Conclusie:** de twee zichtbare bron-SOC-afwijkingen zijn geen andere
  prijs-, veiligheid- of reserveregel. Ze worden veroorzaakt door een
  expliciet vastgesteld verschil in fysieke tijdsresolutie van de energie-
  uitwisseling *binnen* het laatste eerste veiligheidslaaduur.
- **Geen strategiewijziging of correctie van getoonde SOC naar het origineel.**
  Het terugzetten van de kwartierreplay naar een uurmodel zou echte
  kwartierinformatie vernietigen en de rekenkundige energiebehoudsgarantie
  beschadigen.

## Reproduceerbare feitelijke oorzaak

Frozen Alpha84 en native DOEMS ontvangen de identieke uurforecast, exact
verdeeld over kwartieren. Gegevens en uitvoer komen uit
`scripts/diagnose_h53_soc.py`, dat voor elk algoritme de exacte
`soc_end` vóór afronding inspecteert door een **in-memory instrumenteerde
kopie** te compileren. De opgeslagen broncode wordt niet gewijzigd.
De tool controleert dat alle gewone bronuitvoervelden identiek blijven.

In uur 20 (15 november 2026, 20:00 UTC) geldt:

| Meetpunt | Origineel Alpha84 (60 min) | DOEMS (4 kwartieren) |
| --- | ---: | ---: |
| Voor bronpagina afgeronde veiligheidslaadenergie | 0,275 kWh | 0,275 kWh |
| Exacte netlaadenergie vóór afronding | 0,2748582230623821 kWh | 0,2750000000000000 kWh |
| Exacte opgeslagen energie aan het eind | 7,036956521739131 kWh | 7,037086956521740 kWh |
| Exacte SOC aan het eind | 97,73550724637681% | 97,73731884057972% |

De originele **uurstap** laadt de batterij vóór de gehele
huishoudelijke afname op. Bij laden raakt het opslagvat kort de maximale
capaciteit; daardoor wordt de laatste 0,000141777 kWh netenergie
niet geladen. DOEMS laat per kwartier 0,0375 kWh huishoudelijke
afname tussentijds plaatsvinden, waarna een volgend kwartier iets
meer accu-headroom heeft. Daarom accepteert DOEMS die nog ontbrekende
0,000141777 kWh wél.

Het verschil opgeslagen energie bedraagt exact circa
**0,000130434783 kWh = 0,1304 Wh** (na 92% laad-efficiëntie),
of **0,0018115942 procentpunt SOC** bij 7,2 kWh capaciteit.
Daarna blijft het verschil constant — geen verder groeiende drift.

De gepubliceerde SOC-afronding op één decimaal maakt twee
zichtbare verschillen in `safety_valley`:

- Uur 26: Alpha84 raw 84,1485507246% → 84,1%; DOEMS raw
  84,1503623188% → 84,2%.
- Uur 57: Alpha84 raw 13,9492753623% → 13,9%; DOEMS raw
  13,9510869565% → 14,0%.

De andere twee bevroren synthetische scenario's
(`passive_control`, `repeated_trade_opportunities`) hebben
geen bron-SOC-veldverschillen en de onafgeronde SOC-verschillen
zijn daar alleen floating-point-ruis.

## Acceptatiegrens en veiligheid

`tests/test_h53_soc_resolution.py` bewijst expliciet:
1. De raw SOC-routes zijn vóór uur 20 numeriek gelijk.
2. Het verschil start in uur 20 en is exact verklaarbaar door de
   gemeten verschil-netlaadenergie × 92% laadefficiëntie.
3. Het verschil blijft na uur 20 constant zonder accumulatie.
4. Uitsluitend uur 26 en uur 57 vallen over de publicatie-
   afrondingsgrens. Er zijn geen andere bron-SOC-verschillen.
5. De echte fysieke Plan72-projectie wordt **niet** gelijkgesteld
   aan de bronplanner en blijft als H5.6 open controlepunt.

Er worden geen tolerantiegrenzen in een productalgoritme verruimd.
De oorspronkelijke Alpha84-uurlogica blijft bytegelijk, de echte
kwartierprijsbehandeling en batterij-aansluiting blijven ongewijzigd.
`physical_execution_authority=False` en
`execution_enabled=False`.

**H5.3 kan in deze gecontroleerde scenario's worden afgetekend als
verklaarde resolutie-afwijking, niet als programmeerreparatie.**
Live-SOC verificatie, externe tijdsgegevens en de 100 resterende
bron-naar-fysiek vergelijkingsvelden horen bij H5.6 en zijn met
dit bewijs niet afgetekend.

## Publicatie-afbakening

De gezamenlijke H5.2/H5.3-kandidaat voor Alpha 8.10 bestaat uit:
- H5.2 herstel van exacte Alpha84 uitvoerbare vensterstart en
  oorspronkelijke veiligheidsdrempel, maximaal 12 uur per opdracht.
- H5.3 verificatie van onafgeronde bron-SOC-waarden, zonder extra
  productstrategie of afrondingshack.
- Oorspronkelijke Solar Remaining Today functionaliteit uit 8.8
  en H5.1 safety-keuze uit 8.9 behouden.
- Geen wijzigingen aan hoofdstuk 7/8-algoritmes en geen live acties.

De release mag pas gepubliceerd worden nadat de laatste
Python 3.12/3.13/3.14 CI, alle H5.1–H5.3-acceptatiegates
en het exact-hash-vergrendelde pakket zijn geslaagd.

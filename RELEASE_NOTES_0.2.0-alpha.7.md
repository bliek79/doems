# DOEMS 0.2.0-alpha.7 - R5.1 Rebuild Testbuild

## Doel

Deze release bouwt R5 opnieuw op vanaf de bewezen functionele basis
DOEMS 0.2.0-alpha.5. R0-R4 blijven de regressiebasis.

R5.1 vervangt geen bestaande manual/Plan72-producer. De automatische laag
wordt uitsluitend additief en shadow/read-only toegevoegd zodat de bestaande
bediening en het bestaande dashboard ongewijzigd live kunnen worden getest.

## Bestaande R0-R4 route blijft intact

Ongewijzigd blijven onder andere:

- de drie persistente manual Plan Store-slots;
- de R3 Manual SOC Projection;
- de R3 Manual SOC Projection Timeline;
- sensor.doems_ems_plan72_hours als bestaande manual Plan72-compatibiliteitslaag;
- R4 lifecycle/expiry;
- de bestaande Apex-card en zijn known/forecast-prijscontract.

R5.1 registreert geen tweede producer met de identity
doems_ems_plan72_hours.

## Nieuwe R5.1 shadow-uitgangen

Deze release voegt vier afzonderlijke testuitgangen toe:

- sensor.doems_r5_1_automatic_base_preview
- sensor.doems_r5_1_automatic_base_soc_timeline
- sensor.doems_r5_1_combined_preview
- sensor.doems_r5_1_combined_soc_timeline

De Automatic Base Preview rekent de automatische route zonder manual overlay.

De Combined Preview leest de bestaande manual commitments read-only en rekent
dezelfde automatische policy opnieuw met manual als harde voorwaarde. Een
manual overlap neemt eerst tijd/capaciteit uit het kwartier weg, de manual actie
wordt target-begrensd toegepast en de resterende horizon wordt vanaf de
resulterende SOC opnieuw berekend.

## Plannerregels R5.1

R5.1 gebruikt native 15 minuten / 72 uur / exact 288 slots.

- technische minimum-SOC: 5%;
- software-reserve default: 5%;
- normale base floor: 10%;
- laad- en ontlaadrendement: 92% / 92%;
- live batterijcapaciteit uit het R1-contract, zonder vaste fallback;
- maximaal automatisch laden/ontladen default 3500 W, harde bovengrens 3500 W;
- normale handelsmarge default 0,10 EUR/kWh.

Bruikbare zon wordt functioneel volgens de historische regel bepaald: uitsluitend
voor deze beslissing worden complete klokuren uit vier native kwartieren
samengesteld. Het bruikbare-zonpunt is het eerste van twee opeenvolgende
volledige klokuren waarin totale solar minimaal totale home is.

De dynamische reserve beschermt de base floor plus het verwachte netto
woningtekort tot het eerstvolgende aantoonbare bruikbare-zonblok. Zonder
aantoonbaar volgend zonneblok valt de planner terug op de base floor; hij
beschermt niet automatisch de volledige onbekende rest van de 72 uur.

Safety charging voegt alleen de energie toe die nodig is om een toekomstige
reservebreuk te voorkomen. Daarna kan de resterende vrije route nog op gewone
arbitrage worden beoordeeld.

## Peak-sale

Peak-sale is bewust niet onderdeel van R5.1. De eerder besproken 0,50 EUR/kWh
regel is uitgesteld naar R5.2 en blijft gesloten totdat R5.1 live groen is.

## Prices en runtime

De bestaande publieke Prices-timeline blijft ongewijzigd.

R5.1 selecteert read-only zijn eigen exact 288 kwartieren uit de reeds bestaande
304-slot / 76-uurs price buffer met dezelfde plannerreferentie. Ontbrekende
bronkwartieren blijven expliciet missing; er wordt niets ingevuld of
geforward-filled.

De zware automatic/combined berekening draait via een cached single-flight
executor buiten de Home Assistant MainThread. Sensors lezen uitsluitend de
gepubliceerde cache.

## Geisoleerde R5.1 opties

R5.1 gebruikt nieuwe, versiegebonden option keys. Daardoor worden eerder
opgeslagen alpha.6.x waarden zoals 7% reserve of 3200 W niet stil overgenomen.

Defaults voor deze testbuild:

- software reserve 5%;
- maximum automatisch laadvermogen 3500 W;
- maximum automatisch ontlaadvermogen 3500 W;
- minimum handelsmarge 0,10 EUR/kWh.

## Harde control-path grens

R5.1 blijft uitsluitend observationeel:

- automatic_plan_store_writes=false
- scheduler_active=false
- safety_prestart_active=false
- execution_enabled=false
- physical_execution_authority=false

Er worden geen batterijmoduswissels of fysieke laad-/ontlaadcommando's
uitgevoerd.

## Live acceptatie

CI groen is geen live groen.

Na installatie moet in Home Assistant worden bewezen dat:

1. de bestaande SOC/Plan72-route en Apex-prijsweergave intact zijn;
2. manual laden en ontladen nog exact in de bestaande route zichtbaar zijn;
3. dezelfde manual actie ook in de Combined Preview zichtbaar is;
4. manual bij overlap altijd wint en automatic eromheen herplant;
5. known/forecast price_source en price_kind behouden blijven;
6. beide R5.1 previews exact 288 native slots en 288 SOC-punten publiceren;
7. er geen Plan Store-write, Scheduler, Safety/Prestart execution of fysieke
   authority ontstaat;
8. er geen zware R5.1 MainThread plannerwarning optreedt.

R5.2 en R6 blijven geblokkeerd totdat de gebruiker R5.1 expliciet live groen
verklaart.

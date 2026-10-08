# DOEMS 0.2.0-alpha.7.1 - Planner Naming and Dashboard Migration

## Doel

Deze release maakt de publieke plannerarchitectuur definitief voordat de R5-live acceptatie wordt uitgevoerd. De functionele basis blijft 0.2.0-alpha.7; deze release verandert geen plannerbeleid, reserveberekening, manual-priorityregel, prijslogica, SOC-simulatie of uitvoeringsbevoegdheid.

De vaste architectuur is:

**Manual Planner + Automatic Planner -> Combined Planner**

De Combined Planner is de geplande route die het dashboard gebruikt. Manual en Automatic blijven daarnaast afzonderlijk beschikbaar voor diagnose en validatie.

## Definitieve publieke entiteiten

- sensor.doems_manual_planner
- sensor.doems_manual_soc_projection_timeline
- sensor.doems_automatic_planner
- sensor.doems_automatic_soc_projection_timeline
- sensor.doems_combined_planner
- sensor.doems_combined_soc_projection_timeline

De oude Plan72-compatibiliteitsentiteit wordt niet als permanente laag meegenomen. De entity registry wordt bij de upgrade gericht naar de definitieve identiteiten gemigreerd zodat geen tweede set plannerentiteiten hoort te ontstaan.

## Plannerinstellingen

Ook de tijdelijke option-namen uit alpha.7 worden bij de upgrade naar vaste planneropties gemigreerd. De bestaande alpha.7-waarden blijven behouden.

De defaults blijven ongewijzigd:

- technische minimum-SOC: 5%;
- software-reserve: 5%;
- normale plannerfloor: 10%;
- laad- en ontlaadrendement: 92% / 92%;
- maximum laadvermogen: 3500 W;
- maximum ontlaadvermogen: 3500 W;
- minimale handelsmarge: 0,10 EUR/kWh.

## Automatic en Combined Planner

De Automatic Planner berekent de autonome route over exact 288 kwartieren.

De Combined Planner gebruikt dezelfde planning, maar leest de bestaande drie Manual Plan Store-slots en behandelt geldige handmatige commitments als harde voorwaarde. Manual heeft dus altijd voorrang en de resterende route wordt vanaf de gewijzigde SOC opnieuw berekend.

De historische bruikbare-zonregel blijft ongewijzigd: voor deze beslissing worden vier native kwartieren tot volledige klokuren geaggregeerd en het eerste van twee opeenvolgende volledige uren met totale solar >= totale home is het bruikbare zonnepunt.

Ook dynamische reserve, noodzakelijke safety charge en normale handel blijven inhoudelijk gelijk aan alpha.7.

Peak-sale blijft uitgeschakeld en hoort niet bij deze release.

## Runtime

De zware 288-slot berekening blijft via de bestaande cached single-flight executor buiten de Home Assistant MainThread draaien. Sensors lezen alleen de gepubliceerde cache.

De prijsroute blijft exact 288 kwartieren read-only selecteren uit de bestaande 304-slot / 76-uurs pricebuffer. Ontbrekende bronkwartieren blijven expliciet missing.

## Dashboard

examples/doems_planner_dashboard.yaml is aangepast naar sensor.doems_combined_planner.

De kaart:

- gebruikt Combined Planner als hoofdbron;
- gebruikt de drie bestaande manual planslots voor de eerstvolgende handmatige actie;
- toont automatische eerstvolgende actie wanneer geen manual actie voorrang heeft;
- toont handmatig laden en ontladen als afzonderlijke energiereeksen;
- houdt known en forecast prijzen gescheiden via price_source;
- gebruikt de dynamische reserve uit de Combined Planner;
- bevat geen execution-reservelijn zolang die uitvoeringslaag nog niet is geopend;
- laat de bestaande dagbalans vrij van onterechte bron/bestemmingstoewijzing van handmatige energie.

## Uitvoeringsgrens

De plannerlaag blijft in deze release nog niet gekoppeld aan fysieke uitvoering:

- plan_store_writes_enabled=false voor Automatic/Combined;
- scheduler_enabled=false;
- safety_prestart_enabled=false;
- execution_enabled=false;
- physical_execution_enabled=false.

Dit zijn concrete uitvoeringsstatussen; ze veranderen de identiteit van de planner niet.

## Live acceptatie

CI groen is geen live groen. Na installatie van alpha.7.1 wordt juist de definitieve architectuur live getest:

1. de zes definitieve entiteiten bestaan zonder dubbele tijdelijke planner-ID's;
2. Manual Planner reageert op laden, annuleren en ontladen zoals R3/R4 bewezen;
3. Combined Planner neemt dezelfde manual commitments over en herplant eromheen;
4. Automatic Planner blijft afzonderlijk beschikbaar;
5. de Combined Planner publiceert exact 288 native slots en de SOC-timeline exact 288 punten;
6. known/forecast prijsreeksen blijven zichtbaar;
7. het dashboard toont Combined Planner, manual energiereeksen en dynamische reserve correct;
8. de runtime veroorzaakt geen zware MainThread plannerwarning;
9. Scheduler en fysieke uitvoering blijven uit.

R5.2 en R6 blijven gesloten totdat de gebruiker deze live test expliciet groen verklaart.

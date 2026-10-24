# DOEMS 0.2.0-alpha.7.1.11 - Solar Actual Quarter Restore

## Doel en oorzaak

Deze gerichte herstelrelease brengt uitsluitend de eerder bewezen **Solar Actual Quarter-validatie** uit DOEMS 0.1.0-alpha.24 terug in de actieve 0.2.0-resetlijn.

De 0.2.0-reset begon bewust vanaf de oudere forecast-only baseline 0.1.0-alpha.7.7. Daardoor ontbrak de later in Alpha24 gebouwde `sensor.doems_solar_actual_quarter` volledig. De bestaande Google Sheets-validatie bleef de negen Alpha24-velden wel uitlezen, waardoor vanaf de reset `Actual quarter ... = unknown` en `Actual quarter valid = false` werden geschreven.

## Hersteld contract

- `custom_components/doems/solar_actual.py` met `SolarActualQuarterManager` en `SolarQuarterResult`.
- Integratie van het geconfigureerde totale actuele Solar-vermogen over ieder volledig native 15-minutenkwartier.
- Minimaal 90% meetdekking voor een geldig actual quarter.
- Forecast voor exact het startende kwartier wordt op de natuurlijke 00/15/30/45-grens uit de bestaande Solar-cache vastgezet.
- Geen extra Open-Meteo-call en geen hindsight-herberekening.
- Publieke entity `sensor.doems_solar_actual_quarter` met period_start, period_end, coverage, measurement_valid, status, source_entity, forecast_kwh, forecast_captured_at, forecast_locked_at_start en forecast-errorvelden.
- Exacte cached-slot lookup `forecast_point_for_start()` is teruggebracht in de bestaande Solar forecast manager.
- Runtime setup/shutdown en sensorplatform publiceren de herstelde manager en entity opnieuw.

## Bewust ongewijzigd

- Per-array Solar performancefactor blijft exact zoals hersteld in 0.2.0-alpha.7.1.10: Noord/Zuid afzonderlijk instelbaar, 0.90 fallback, `mixed` diagnostiek.
- Solar Foundation schema 2 en de bestaande 15 minuten / 72 uur / 288 slots architectuur blijven ongewijzigd.
- Open-Meteo forecastberekening, invertergroep-/AC-cap en arraygeometrie blijven inhoudelijk ongewijzigd.
- R5 Automatic/Combined planner blijft inhoudelijk ongewijzigd.
- R6 automatische drie-slotvoorstellen blijven inhoudelijk ongewijzigd.
- Manual Plan Store, SOC-projectie, lifecycle, Prices, Battery Input, safety/execution en fysieke batterijbesturing worden niet gewijzigd.
- Google Sheets-structuur en Home Assistant Sheets-automation worden niet gewijzigd; die zijn al voorbereid op de bestaande negen Alpha24-velden.

## Validatie

De bestaande Alpha24 Solar Actual Quarter-regressietests zijn teruggebracht. De functionele herstel-PR is volledig groen door:
- Python compile;
- volledige huidige pytest-regressieset;
- JSON-validatie;
- Foundation Regression CI;
- bestaande 0.2.0 releasecontractchecks.

Na installatie in Home Assistant is de live gate:
1. `sensor.doems_solar_actual_quarter` bestaat;
2. na één volledig natuurlijk kwartier is `measurement_valid=true` bij voldoende coverage;
3. `forecast_locked_at_start=true` en forecast/error-attributen zijn gevuld;
4. de eerstvolgende DOEMS Solar Forecast-Sheetwrite vult de negen bestaande Actual Quarter-kolommen weer;
5. Solar blijft 288/288 en de per-array factoren blijven Noord 0.82 / Zuid 0.67.

Geen andere functionele wijziging valt binnen deze release.

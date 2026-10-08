# DOEMS 0.2.0-alpha.7.1.2 - Automatic SOC and Economic Policy Fix

## Gerichte R5-fix
- Forecastbehoefte tot bruikbare zon blijft diagnostische planninginput, wordt niet meer opgeteld bij de harde SOC-reserve.
- Normale harde basisfloor blijft 5% technisch + 5% software = 10% (werkelijke opties blijven leidend).
- Automatic Planner beoordeelt de volledige native 288-slot horizon om goedkoop technisch haalbaar voor te laden voor latere duurdere woningafname, zon eerst.
- Onvermijdbare woningnetafname wordt apart zichtbaar als unavailable/unavoidable grid import; economische reserve wordt afzonderlijk gerapporteerd.
- Bruikbare zon is geen economische horizonstop; geen geforceerd 100%-SOC plateau.

## Bewust ongewijzigd
R0-R4 bestanden, Manual Planner, drie Plan Store-slots, registry/entities, dashboard/Apex, source/price-provenance, fysieke uitvoering, Scheduler, Safety/Prestart en gebruikerinstellingen.

## Technische gate
Regressietests + volledige CI. Daarna LIVE STOP: vergelijk Automatic SOC met oude Anker EMS in bestaande Apex. Combined/manual-priority alleen na expliciet live groen; R5.2 en R6 gesloten.

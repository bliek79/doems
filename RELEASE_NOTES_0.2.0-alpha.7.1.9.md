# DOEMS 0.2.0-alpha.7.1.9 - Solar Per-Array Performance Factor Restore

## Doel en herkomst

Herstelt uitsluitend de eerder bewezen Alpha25-configuratie van de **statische performancefactor per PV-array**, die bij de 0.2.0-reset verloren is gegaan. Gebaseerd op PR #85 en de oorspronkelijke Alpha25-commit `2a26b72`.

## Zichtbare Solar-instellingen

De Solar Options tonen opnieuw **Performancefactor / statische opbrengstfactor (%)** per array. De gebruiker kan Noord en Zuid afzonderlijk instellen.

- Noord: 2,96 kWp, 32 graden, DOEMS-azimut 0 graden; **82% / 0.82 is de gebruikte validatiewaarde**.
- Zuid: 1,48 kWp, 25 graden, DOEMS-azimut 180 graden; **67% / 0.67 is de gebruikte validatiewaarde**.
- **Backwards-compatible standaard blijft 90% / 0.90 per array** bij ontbrekende instellingen. 82%/67% zijn nadrukkelijk geen hardcoded standaardwaarden.

## Werking

Voor iedere array geldt: `GTI / 1000 x array_dc_kwp x array_performance_factor`.
Daarna past DOEMS de **bestaande** invertergroep-/AC-cap en proportionele verdeling toe; deze groep- en caplogica is niet gewijzigd.

Solar Foundation schema 2 bevat de individuele factor per stabiel array-ID, de genormaliseerde Foundation-snapshot en de reproduceerbare topologiesignatuur. De bestaande Options- en Foundation-opslag bewaren deze informatie ook na een reload/herstart.

De Solar-modeldiagnostiek publiceert `performance_factor: mixed` wanneer factoren verschillen, daarnaast `array_performance_factors` met de exacte waarden en `performance_factor_semantics: static_per_array_before_group_ac_cap`.

**Native tijdcontract onveranderd: 15 minuten / 72 uur / 288 slots.**

## Afbakening en veiligheid

- Geen wijzigingen in Automatic/Combined planner, manual planning, safety, execution, battery control of het R6-ontwerp.
- Geen Local Shading of Partial Shading; statische performance en fysieke/geleerde schaduw zijn verschillende lagen.
- Fysieke automatische uitvoering blijft uitgeschakeld.
- R5 blijft LIVE GROEN; R6 blijft gepauzeerd tot Solar-livevalidatie en expliciet akkoord.

## Validatie

De herstel-PR is gecontroleerd met **135 geslaagde repositorytests** en **3 geslaagde Foundation-regressietests**, inclusief 0.90-fallback, 0.82/0.67, AC-cap, topologiesignatuur, percentageveld, diagnostiek en 288 kwartieren.

Na installatie in Home Assistant moet nog worden bevestigd: Noord 82% en Zuid 67% daadwerkelijk instelbaar, persistent na reload/herstart, in Solar-model zichtbaar als `mixed` met exacte factoren, en nieuwe forecast/Sheets-validatie correct. Deze livecontrole is **niet** door de release alleen afgerond.

## GitHub

- PR: https://github.com/bliek79/doems/pull/85
- Herstelbasis: `0.2.0-alpha.7.1.8`
- Nieuwe release: `0.2.0-alpha.7.1.9` — eigen immutable tag; de vorige release blijft intact.

# DOEMS 3.0 Alpha 5.2 Plan72 — tolerantiecorrectie

Deze gerichte correctie op Alpha 5.1 herstelt de numerieke beoordeling van reserve en resterende laadbehoefte. Hoofdstuk 5 blijft een observerende planner voor 72 uur in 288 kwartieren. De bestaande forecasts, elf Energy Need-entiteiten en 35 Plan72 unique IDs blijven behouden.

## Wat is gecorrigeerd

- Opeenvolgende geaccepteerde handelsstappen konden telkens opnieuw een kleine afwijking toestaan ten opzichte van de vorige route. Die afwijkingen konden samen een reserveonderschrijding veroorzaken. Iedere stap wordt nu ook getoetst aan de vaste route vóór handel en de gezamenlijke resterende behoefte over de horizon.
- Een al aanwezige kleine restwaarde krijgt geen extra tolerantie bovenop de oorspronkelijke grens. De batterijzijdige rekentolerantie blijft **0,00001 kWh (0,01 Wh)**; zij is niet vergroot.
- Status en reden gebruiken nu dezelfde toets in batterij-kWh. Daarmee verdwijnt de mogelijkheid dat verschillende energiebases een tegenstrijdige `ready` en `remaining_physical_shortfall` opleveren.
- **Remaining Charge Need** bewaart de ruwe AC-restwaarde en toont het nieuwe attribuut `numerical_tolerance_kwh`: de batterijzijdige tolerantie gedeeld door het laadrendement. De pure API noemt dit `remaining_charge_need_tolerance_kwh`.

Een weergave van `0.00 kWh` kan een klein positief getal afronden. Een tekort boven de rekentolerantie blijft zichtbaar als `limited`; echte reserveonderschrijdingen worden niet weggefilterd. Deze versie voegt geen batterijcommando's of planslotbeheer toe.

## Bestaande entiteiten en dashboards

De unique IDs veranderen niet. Een oude HA-registratie kan `unavailable` en `restored: true` blijven terwijl de actieve entiteit een ID met een nummerachtervoegsel heeft. Controleer in Ontwikkelaarstools de werkelijke entity IDs, states en `plan_generation` en verbind de lokale kaart met de actieve entiteiten. Achtervoegsels zoals `_2` zijn installatiespecifiek. Het [generieke kaartvoorbeeld](examples/plan72_validation_card.yaml) behoudt daarom zijn oorspronkelijke IDs. De update hernoemt of verwijdert geen registraties automatisch.

## Installeren en opnieuw controleren

1. Selecteer na publicatie in HACS expliciet **`v0.3.0-alpha.5.2`**, werk DOEMS bij en herstart Home Assistant.
2. Controleer de bestaande bronnen en plannerinstellingen, de elf Energy Need-entiteiten en de actieve 35 Plan72-entiteiten.
3. Bekijk na een nieuwe berekening status, reden, reserveonderschrijdingen en de ongeronde Remaining Charge Need met `numerical_tolerance_kwh`. Een geldige tijdlijn bevat 288 kwartieren en 72 uur.
4. Controleer de lokale kaartbindingen wanneer een kaartregel onbeschikbaar blijft terwijl een actieve variant bestaat.

De volledige lokale suite heeft **171 geslaagde tests**. De nieuwe regressies reproduceren de fouten met synthetische invoer; private HA-bronwaarden zijn niet opgenomen. Publicatie volgt na de automatische releasecontroles. De livehercontrole van Alpha 5.2 in Home Assistant staat nog open.

Zie de [hoofdstuk-5-specificatie](docs/DOEMS3_CHAPTER5_PLAN72.md) voor de energiebasis, alle entiteiten en modelgrenzen.

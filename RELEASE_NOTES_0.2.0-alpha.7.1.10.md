# DOEMS 0.2.0-alpha.7.1.10 - R6 Automatic Three-Slot Proposals

## Gebruikersbesluit en doel
R6 is uitsluitend de automatische slotafstemming op de drie bestaande DOEMS-planslots. De al geaccepteerde R5 Automatic/Combined-planner blijft inhoudelijk ongewijzigd en **R5 blijft LIVE GROEN**.

- Automatic kan **slot 1, 2 en 3** vullen met automatisch gegenereerde *concept*acties.
- De gebruiker kan ieder automatisch gevuld slot **direct met Manual overschrijven**; ook een handmatig concept heeft volledige prioriteit.
- Automatic overschrijft nooit een Manual-slot. Geen extra helpers, nieuwe slotentiteiten of dashboardstructuur.
- Bij handmatige annulering of `clear_plan` is een slot bij een latere geldige plannerrevisie opnieuw bruikbaar. Er is **geen** permanente annuleer-blacklist ontworpen.

## Technische werking
Een nieuwe R6-brug leest alleen een **volledig gepubliceerde geldige R5 Combined-berekening** met exact 288 native kwartieren (en geldige Automatic-bron). De R5-rekenregels, het SOC-simulatiemodel, veiligheid, prijzen en Solar zijn niet aangepast.

De brug vertaalt uitsluitend expliciete netacties:
- `charge_from_grid_safety_kwh` -> veiligheidsladen;
- `charge_from_grid_trade_kwh` -> handelsladen;
- `trade_discharge_to_grid_kwh` -> handel_ontladen.

PV-laden en normale ontlading naar het huis zijn geen expliciete batterijcommando's. Aaneengesloten kwartieren van dezelfde actierichting en doel worden als een voorstelvenster gevormd, met native start-/eindtijd, energie, vermogen, doel-SOC vanuit de actuele sensorcapaciteit en R5-rendementen. Niet vertaalbare kandidaten worden met reden overgeslagen; de bronplanning wordt niet aangepast.

### Slotbeheer en herstart
- `automatic_72h_planner` markeert alleen R6-eigen conceptvoorstellen, naast de ongewijzigde `manual`-herkomst.
- Stabiele `planner_identity` en `planner_signature` verhinderen duplicatie en nutteloze opslagwrites. Overblijvende voorstellen behouden hun bestaande slot, ook als een andere actie handmatig wordt overgenomen.
- Automatische voorstellen blijven persistent na HA-herstart. Legacy Manual-plannen blijven Manual.
- Lopende of reeds gestarte voorstellen worden niet op basis van een nieuwe forecast herschreven. Na de complete starttijdmarge vervalt een ongebruikt automatisch voorstel automatisch, óók bij ontbrekende forecast.
- Directe gebruikerswijziging claimt het slot als Manual en wist alleen automatische metadata. Automatische opslagupdates wekken geen nieuwe R5/Manual-rekenlus op.
- De R6-runtime weigert ongeldige, halfgepubliceerde of achterhaalde Combined-generations, inclusief vlak na Manual-wijzigingen.

## Architectuur en veiligheid
- **Native: 15 minuten / 72 uur / 288 slots.**
- De drie bestaande `sensor.doems_plan_{1,2,3}_status` en bestaande planbediening blijven bestaan; extra attributen tonen automatische provenance, identity, purpose en geplande energie.
- `lifecycle_status=concept`: R6 voert geen Scheduler-handoff, prestart/safety-gate of batterijactie uit.
- **Fysieke automatische uitvoering blijft uit.** R7/R8 zijn niet vrijgegeven. R5.2 peak-sale blijft uitgesteld.
- Het aparte Solar per-array-herstel uit 0.2.0-alpha.7.1.9 blijft behouden en ongewijzigd.

## Tests en status
De ontwikkel-PR #86 is gebouwd vanaf de vorige resetrelease. De complete repository-CI was groen met **152 geslaagde tests** plus de Foundation-regressie, waaronder R6-regressies voor:
1. drie automatische plannen uit kwartieracties;
2. Manual-voorrang en directe slotclaim;
3. rolling identity/revisies en deduplicatie;
4. cancel, clear, startvenster-expiry en audit;
5. legacy/manual- en automatische herstartpersistentie;
6. native 288 kwartieren en veldmapping;
7. fail-closed bij ongeldige/stale Combined, inclusief Manual-race;
8. ongewijzigde R0-R5-plannerberekeningen en geen fysieke calls.

De release-CI valideert de definitieve publicatie opnieuw. GitHub-CI bevestigt **geen Home Assistant-livevalidatie**. Na installatie moeten zichtbaarheid, herstart, Manual-overschrijving en afloop van automatische voorstellen live worden gecontroleerd. **R6 wordt daardoor niet automatisch LIVE GROEN verklaard.**

## GitHub
- PR: https://github.com/bliek79/doems/pull/86
- Vorige onveranderde release: `0.2.0-alpha.7.1.9`
- Nieuwe prerelease: `0.2.0-alpha.7.1.10`
- Geen wijziging van fysieke batterijbesturing.

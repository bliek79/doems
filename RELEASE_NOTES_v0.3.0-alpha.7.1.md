# DOEMS 3.0 — v0.3.0-alpha.7.1 — Persistent Plan Store

Hoofdstuk 7 verbindt de Alpha84-driesslotopslag met de bestaande Plan72-route (72 uur, 288 kwartieren) en Action Bridge. Er is geen fysieke batterijaansturing en er wordt niets op de Home Assistant-installatie van de gebruiker uitgevoerd vanuit deze publicatie.

## Wijzigingen

- Werkende automatische vulling van lege slots, stabiele toewijzing binnen de chronologische kandidaten, overflow en reconciliatie.
- Persistente opslagrevisies, geserialiseerde opslag, terugzetten bij schrijffouten en bron-/generatie-/fingerprintcontroles tegen verouderde mutaties.
- Handmatige eigendom, vijf minuten standaard startvertraging en opslagacties voor plannen en annuleren.
- Gedeelde SOC-projectie voor handmatige en beschermde automatische acties, met behoud van energieherkomst, twee minuten voorbereiding en harde eindtijd.
- 24 slotentiteiten en zes centrale diagnose-entiteiten volgens het op 30 oktober 2026 goedgekeurde register.
- Regressiebescherming blijft bestaan: bevroren gereviewde blobs, oorspronkelijke ongewijzigde Alpha53-strategiefuncties en nieuwe uitvoeringstests.

De volledige registertabel, unique-ID-formules en opslag-/lifecyclevoorwaarden staan in [het hoofdstuk-7-document](docs/DOEMS3_CHAPTER7_PLAN_STORE.md). Bestaande entiteiten en release-tags worden niet hernoemd of vervangen. Registry-conflicten in een bestaande Home Assistant-installatie kunnen een lokaal suffix opleveren; de integratie hernoemt die registry niet.

## Verificatie en publicatie

De implementatiecommit `3e858afb90770bdaaf8c180f18024da6789bae38` is lokaal geverifieerd met 271 geslaagde tests op Python 3.12 en 271 op Python 3.13. De releasecommit wordt opnieuw volledig getest op beide versies. Publicatie wacht op beide groene GitHub Actions-jobs, releasecontractvalidatie en controle van het verpakte archief. De verificatie gebruikt de echte modulecode met afgeschermde Home Assistant-randen; er is geen live batterijtest uitgevoerd.

`doems.zip`, `SHA256SUMS.txt` en `RELEASE_PROVENANCE.json` koppelen het archief aan de geteste commit. Een bestaande tag of release mag niet worden vervangen.

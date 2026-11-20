# DOEMS 3.0 - H5.2 herstel timing veiligheidsladen

Referentie: originele Anker EMS `bliek79/dummy-os-anker-ems`,
tag `0.0.1-alpha.84`, commit
`6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d`.
Uitgangspunt: gepubliceerde DOEMS `v0.3.0-alpha.8.9`.
Dit document is een herstelregistratie van een **niet-gepubliceerde branch**.

## Bewezen afwijking in safety_valley

Voor exact dezelfde 72 uur aan prijzen en verbruik, uitgebreid naar
288 gelijkwaardige kwartieren:

| Uitvoerbaar veiligheidvenster | Origineel Alpha84 | DOEMS Alpha 8.9 |
| --- | --- | --- |
| Eerste | 2026-11-15 18:00Z t/m 21:00Z | hetzelfde |
| Tweede | 2026-11-17 12:00Z t/m 2026-11-18 00:00Z | 2026-11-17 11:00Z t/m 00:00Z |
| Tweede looptijd | 12 uur | 13 uur, onjuist gemarkeerd als 12 uur |

De oorspronkelijke bronplanning heeft in het uur vanaf 11:00Z ongeveer
0,046 kWh veiligheidsenergie. In originele Alpha84 is de minimale fysiek
uitvoerbare veiligheidseenheid 0,10 kWh **per origineel uur**. De originele
Bridge verwerpt dat kleine uur, maar de native DOEMS Bridge telde het
door een aaneengesloten segment bij de volgende 12 uur op. Daardoor
begon het echte laadvenster één uur te vroeg. Afzonderlijk bleek de
native Bridge een aaneengesloten venster van 13 uur onterecht als
`max_runtime_h: 12` te presenteren.

## Herstel in deze branch

1. De Alpha84 Preview geeft uitsluitend in native kwartiermodus door
   wanneer zij daadwerkelijk de originele uurroute gebruikt omdat er
   voor de relevante horizon geen afwijkende kwartierinformatie bestaat.
   Het originele 60-minutenresultaat blijft ongewijzigd.
2. De bundel draagt dit provenance-signaal naar de bron-Bridge over.
   Alleen voor **die aantoonbaar uur-equivalente modus** wordt de
   oorspronkelijke 0,10-kWh-per-uurgrens gehanteerd. Voor echte
   kwartierdata blijft het bestaande aaneengesloten-kwartiergedrag
   behouden, inclusief geprijsde deelkwartieren en uurgrensoverschrijding.
3. Aaneengesloten native Bridge-opdrachten worden gesplitst zodra ze
   de reeds bestaande maximale looptijd van 12 uur zouden overschrijden;
   het opgegeven runtimeveld stemt daarmee overeen met de daadwerkelijke
   begin- en eindtijd. Geen nieuwe economisch-strategische limiet.
4. Regressietests vergelijken start en einde van *alle uitvoerbare*
   veiligheidvensters met het bevroren originele Alpha84 Bridge-resultaat,
   niet met kleine niet-uitvoerbare Preview-residuen. Afzonderlijke
   tests bewaken de echte kwartieruitvoer en de 12-uursgrens.

## Aangetoond na gerichte regressie

De oorspronkelijke en de DOEMS-kandidaat hebben beide:
- Eerste opdracht: 2026-11-15 18:00Z tot 21:00Z.
- Tweede opdracht: 2026-11-17 12:00Z tot 2026-11-18 00:00Z.
- Native fysieke voorbereiding: +2 minuten, dus 12:02Z bij tweede opdracht.
- Geen nieuw herstelvenster door de fysieke reconciliatie in deze fixture.
- `reserve_satisfied: true` en fysieke uitvoeringsbevoegdheid blijft uit.
- De gerichte testserie in GitHub run 44767694962: 20 tests geslaagd.

De eerste opdracht heeft in de fysieke simulatie nog een zichtbaar
capaciteitsverschil van circa 0,355 kWh AC: bronvraag 6,675 kWh versus
daadwerkelijk circa 6,320 kWh. Dit is niet verborgen of als volledige
energieovereenkomst goedgekeurd.

De diagnose bevat nog 2 bron-SOC veldverschillen en 100 bron-naar-fysiek
energie/SOC veldvergelijkingsverschillen in de safety_valley-case. Deze
zijn **niet** automatisch programmeerfouten, en horen bij H5.3/H5.6.
Regressies bewijzen nog geen livewerking in Home Assistant.

## Volgende acceptatie

- Volledige Python 3.12 / 3.13 / 3.14 tests en beschermde bronhashcontrole
  moeten slagen op de exacte eindcommit.
- Geen release, merge naar main of wijziging aan Home Assistant door
  deze branch.
- Pas H5.2 aftekenen binnen de gecontroleerde scenario's wanneer de
  volledige regressie groen is; H5.3, H5.4, H5.6 en H6-H8 blijven open.

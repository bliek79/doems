# DOEMS 3.0 — Hoofdstuk 8: Scheduler

## Basis, toestemming en scope

Implementatie en het hieronder opgenomen entiteitenregister zijn door de gebruiker
goedgekeurd op 4 november 2026: “dan heb je mijn goedkeuring om dit in zijn geheel te bouwen.”

- Exacte basis: `bc348852c8254eba51d159ca84f1a0d2fbecf736`, tag `v0.3.0-alpha.7.8`.
- Ontwikkelbranch: `doems3-ch8-scheduler-implementation`.
- Gereserveerde versie: `v0.3.0-alpha.8.1`.
- Referentie: `bliek79/dummy-os-anker-ems`, `0.0.1-alpha.84`,
  commit `6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d`.
- De Scheduler leest drie persistente slots, selecteert maximaal één kandidaat en
  levert diagnose. Hij wijzigt geen slot, plant geen energie en roept geen
  batterijservice aan. `observational_only: true`,
  `physical_execution_authority: false`, `execution_enabled: false`.
- Pre-Start, Safety Guard, Final Revalidation en Execution Controller blijven
  hoofdstukken 9–12. Geen merge naar main, installatie of releasepublicatie is
  onderdeel van de bouwopdracht. CI bouwt uitsluitend controleerbare artifacts.

## Gecontroleerde Alpha84-route

`scheduler.py` sorteert op `(gepland voor direct, ready_since, slotnummer)`.
Voor gepland is ready_since de oorspronkelijke starttijd; voor direct hebben alle
kandidaten dezelfde evaluatietijd. Verschuldigde geplande acties gaan dus voor,
oudste start eerst; gelijke tijden en directe acties gebruiken slotvolgorde.
Er is geen extra manual-, prijs-, laad- of ontlaadprioriteit.

Concept, actief, voltooid, geannuleerd en fout zijn niet selecteerbaar. Een actief
slot onderdrukt niet de selectie van een ander slot; exclusieve fysieke uitvoering
wordt in Alpha84 door de latere uitvoeringsketen afgedwongen. De bestaande Store
beschermt handmatige en actieve plannen tegen automatische toewijzing.

De Alpha84-coordinator evalueert rondom opruimen/synchroniseren van de Store.
DOEMS bereikt dit met listeners op dezelfde Store en bronpublicaties. Opruimen,
annuleren, historie en handoff naar pending blijven bij de bestaande Store/writer.
De Scheduler promoveert nooit naar actief.

## Bewuste contractaansluitingen

1. DOEMS automatische plannen gebruiken nul minuten marge. De referentie-evaluator
   accepteert minimaal één minuut. DOEMS accepteert nul uitsluitend voor automatisch;
   handmatige invoer behoudt 1–120 minuten en standaard vijf minuten.
2. `start <= now <= start + marge`; de eindgrens is inclusief. Nul betekent exact
   het starttijdstip. Een vertraagde callback gebruikt de werkelijke huidige tijd,
   nooit een teruggedateerde evaluatie. Ook één microseconde te laat is verlopen.
   Gerichte callbacks kunnen geen realtime garantie bieden. Dit is een expliciete
   beperking voor de latere uitvoeringsfase en geen vrijbrief voor een verborgen marge.
3. Tijdstippen moeten een tijdzone hebben en worden als UTC-instant vergeleken,
   ook tijdens de zomer-/wintertijdwissel. Ongeldige numerieke invoer, booleans,
   NaN en oneindigheid worden geweigerd. Richtingslimieten komen uit bestaande
   Plan72-configuratie; een hard gepland einde mag niet worden verlengd.
4. `command_target_soc` en `projected_end_soc` blijven afzonderlijke velden.
   `start_time`, `power_start_time` en `planned_end_time` blijven afzonderlijk.
5. Ontbrekende/ongeldige Plan72- of Bridge-publicaties blokkeren een startklaar
   resultaat. Generatie en fingerprint van beide actuele publicaties moeten
   overeenkomen. De Scheduler doet geen nieuwe inhoudelijke SOC-/reservecontrole.
6. Een beschermd slot kan een oudere brongeneratie/signatuur hebben. Deze afwijking
   wordt zichtbaar gemeld, maar is geen automatische afwijzing of herschrijving.
   De Alpha84 Pre-Start maakt eveneens onderscheid tussen stabiele identiteit en
   revisiesignatuur. Inhoudelijke actualiteitsbeoordeling blijft hoofdstuk 9.

## Runtime en consistentie

- Eén synchrone evaluatie leest drie kopieën en de opslagrevisie plus de actuele
  Plan72-/Bridge-snapshots. Vóór publicatie worden revisie, slotinhoud en
  snapshotidentiteit opnieuw vergeleken. Bij wijziging wordt selectie geblokkeerd
  met `superseded_snapshot` en volgt een nieuwe evaluatie.
- Store- en broncallbacks worden tot de volgende event-loopbeurt samengevoegd,
  zodat geen half opgeslagen transactie wordt gelezen.
- Gerichte callbacks op start/einde/startmarge plus een lichte 10-secondencontrole.
  Expiratie volgt één microseconde na de inclusieve margegrens.
- Geen call van de Scheduler naar Plan72.refresh of berekenfuncties. Het bestaande
  kwartierbeleid en de kritieke uitzonderingen zijn byte-identiek behouden.
- Setup/unload beheert listeners, geplande callback en intervaltimer. Na unload
  wordt niet meer gepubliceerd. De Scheduler heeft geen eigen persistente opslag;
  na herstart volgt een nieuwe beoordeling van de herstelde slots.

## Goedgekeurd entiteitenregister

| Entity ID | Unique ID | Functie |
|---|---|---|
| `sensor.doems_scheduler_status` | `{entry_id}_scheduler_status` | Centrale status en drie slotdiagnoses |
| `sensor.doems_scheduler_selected_plan` | `{entry_id}_scheduler_selected_plan` | `slot_1`, `slot_2`, `slot_3` of `geen` |
| `sensor.doems_scheduler_reason` | `{entry_id}_scheduler_reason` | Selectie-, wacht- of blokkeerreden |
| `binary_sensor.doems_scheduler_ready` | `{entry_id}_scheduler_ready` | Kandidaat voor latere validatie, geen startbevoegdheid |

`{entry_id}` is de werkelijke config-entry-ID. De voorgestelde object-ID's zijn
expliciet in de registratie gezet. Een al bestaand HA-register kan een afwijkend
entity_id behouden of bij een conflict een suffix gebruiken. Controleer daarom
bij de eerste livecheck de vier werkelijke IDs; geen bestaande entiteiten worden
stilzwijgend hernoemd of verwijderd. De dertig hoofdstuk-7-entiteiten blijven intact.

Alle vier lezen dezelfde atomair gepubliceerde snapshot, inclusief opslagrevisie,
evaluatietijd, volgende grens, gekozen slot en slotredenen, herkomst, beide SOC-velden,
bronidentiteit, generatie, fingerprint, signatuur en bevoegdheidsvlaggen.
Grote slotdiagnose en klokvelden zijn uitgesloten van recorder-attributen.
Er zijn geen nieuwe services, helpers of bedieningsschakelaars.

## Validatie en livecheckplan

De geautomatiseerde tests omvatten 512 combinaties tegen de ongewijzigde Alpha84
Scheduler, grensmomenten, tijdzones/DST, ongeldige getallen en bronvelden, harde
endtijd, lifecycle, nulmarge, vertraagde callback, annuleren/rollback, herstart,
handmatige bescherming, bronuitval/herstel, snapshotraces en entiteitslifecycle.
Een integratietest gebruikt de echte Plan72-/Bridge-runtime: 100 Scheduler-ticks
veroorzaken geen extra berekening, SOC-uitval blokkeert en herstel rekent opnieuw.
De bestaande strategiebewaking blijft gelden; releaseversietests volgen Alpha 8.1.

Na afzonderlijk vrijgegeven publicatie/installatie:

1. Controleer vier nieuwe IDs/unique-IDs, bestaande dertig entiteiten en beide false-vlaggen.
2. Controleer gepland voor direct, oudste start en slotnummer bij gelijke start.
3. Controleer handmatige marge, verlopen venster en nulmarge zonder verlenging.
4. Controleer annuleren en opnieuw vullen, zonder achterblijvende oude selectie.
5. Controleer herstart en behoud van handmatige invoer, historie en slotidentiteit.
6. Controleer SOC-uitval, calculating en coherent herstel.
7. Controleer dat tijdcontroles calculation_count niet verhogen.
8. Controleer dat geen batterijcommando of lifecycle-promotie naar actief plaatsvindt.

Status: gebouwd en geautomatiseerd te verifiëren; livevalidatie en fysieke
uitvoering zijn niet afgetekend. Dashboardkleuren, teksten, indeling en
uurweergave zijn niet gewijzigd. De zichtbare plannernaam blijft DOEMS Planner.

## Alpha 8.2 correction — supersedes Alpha 8.1 source gating and zero margin

Reference: Alpha84 commit 6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d.
Base: DOEMS Alpha 8.1 commit 67786036bb2b92f30f693dee1754db32bac5c028.

Plan72 retains its coherent published generation during a background replacement.
Its source validity is still invalidated on real source loss. Scheduler selection
is independent of source readiness; `source_blocker` and `source_consistent` are
separate diagnostics for later validation. No execution authority is granted.
Automatic writer margin is 10 minutes, with the original hard end time unchanged.
Cached Bridge horizons survive a quarter boundary until superseded or expired;
new assignments still exclude already-due windows and protect active plans.

Existing entity register and unique IDs are unchanged. Additional attributes on
`sensor.doems_ems_plan72_status` (and the other Plan72 entities):
`calculation_in_progress`, `calculation_started_at`,
`calculation_duration_seconds`, `pending_replan_reason`,
`requested_generation`, `stale_discard_count`.
Published timestamps/generation remain those of the published result.

No public dashboard edits. The quarterly cadence has explicit content-change,
source-recovery, effective manual/limit change, reserve-crossing and one-shot
near/due automatic-start exceptions. Repeated unchanged store notifications and
Scheduler time ticks do not initiate heavy recomputation.

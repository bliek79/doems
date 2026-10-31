# DOEMS 3.0 — Hoofdstuk 7: Persistent Plan Store

Status: entiteitenregister door de gebruiker goedgekeurd op 30 oktober 2026. Releasekandidaat `v0.3.0-alpha.7.3`; publicatie uitsluitend na volledige groene verificatie.

## Referentie en scope

Functionele referentie: `bliek79/dummy-os-anker-ems`, tag `0.0.1-alpha.84`, commit `6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d`.
De bestaande Alpha84-opslag blijft het enige persistente driesslotsysteem. Plan72 blijft de enige SOC-route (72 uur, 288 kwartieren); de bestaande Action Bridge levert automatische kandidaten. Er wordt geen Scheduler of batterij-executor toegevoegd.

Alle dertien bestaande hoofdstuk-7-commits van `f15bad0` tot en met `4932998` zijn beoordeeld via hun gezamenlijke wijziging en de betrokken modules. De uitgangssituatie had onder meer geen slotplatformen en accepteerde in de toewijzing lege handmatige slots die de opslag vervolgens weigerde.

## Werking en herstel

- Drie slots worden duurzaam opgeslagen onder `doems.<config_entry_id>.plans`. Oude opslag zonder revisie wordt als revisie 0 gelezen. Bestaande slots en lifecyclevelden worden behouden; er wordt geen Home Assistant-opslag buiten deze component gewijzigd.
- Elke succesvolle opslagmutatie verhoogt de persistente revisie. Schrijvers worden geserialiseerd; lezers zien tijdens opslag de vorige bevestigde toestand. Een mislukte opslag herstelt die toestand zonder wijzigingsmelding.
- Automatische schrijfacties controleren Plan72/Bridge-generation, fingerprint, kandidaatbron, actuele kwartiergrens en de verwachte opslagrevisie. De bron wordt opnieuw gecontroleerd nadat de opslaglock is verkregen.
- Handmatige edits claimen het slot, wissen automatische metadata en zetten de lifecycle terug op concept. Actieve slots zijn niet bewerkbaar.
- Eerst worden de chronologisch eerste beschikbare kandidaten geselecteerd; daarna blijven de bijbehorende bestaande slotidentiteiten behouden. Een overloopkandidaat mag een eerdere kandidaat niet verdringen. Beschermde identiteiten worden nooit nogmaals in een vrij slot gezet.
- Toekomstige automatische pending-acties blijven herzienbaar. Due/actieve acties zijn beschermd. Verlopen automatische pending-slots worden onafhankelijk van een geldige nieuwe forecast vrijgegeven. Er is een controle iedere 30 seconden en bij bron-/opslagwijzigingen.
- Handmatige concepten met geplande start, pending-acties en actieve vervolgen worden als onveranderlijke invoer in dezelfde Plan72-worker opgenomen. Toekomstige herzienbare automatische acties worden niet als extra energie ingevoerd. Beschermde automatische acties behouden safety/trade-herkomst, voorbereiding, commandodoel en harde eindtijd.
- Actieve vervolgen beginnen bij de actuele gemeten SOC; eerder uitgevoerde energie wordt niet nogmaals toegevoegd. Overlap en ongeldige invoer blijven via de bestaande Plan72-validatie geblokkeerd.
- Automatische voorstellen worden alleen in opslag pending gemaakt. Deze status verleent geen uitvoeringsbevoegdheid. Een actieve toestand wordt door dit hoofdstuk nooit zelfstandig gestart of als fysiek voltooid verklaard.
- Standaard startvertraging handmatig: vijf minuten. De bestaande instelbaarheid van 1–120 minuten blijft behouden. Automatische acties behouden hun exacte venster zonder startuitstel.

## Handmatige opslagacties

`doems.plan_store_schedule` en `doems.plan_store_cancel` ontvangen `config_entry_id` en `slot` (1–3).
Schedule markeert een geldig handmatig slot pending; bij modus direct wordt het opslagmoment de starttijd. Cancel annuleert een inactief slot. Geen van beide acties roept apparaatservices aan. Een actieve uitvoering annuleren vereist de latere uitvoeringshoofdstukken en wordt hier geweigerd.

## Goedgekeurd definitief entiteitenregister

`<entry_id>` is de bestaande Home Assistant-configuratie-entry-ID; deze wordt letterlijk ingevuld in de unique-ID. De object-ID's hieronder zijn de voorgestelde eerste entity-ID's. Home Assistant behoudt bestaande registry-toewijzingen en kan bij een reeds bezette naam een suffix toevoegen; deze implementatie hernoemt geen bestaande registry-entiteiten.

| Entity-ID | Unique-ID |
|---|---|
| `select.doems_slot_1_action` | `<entry_id>_slot_1_action` |
| `select.doems_slot_1_execution_mode` | `<entry_id>_slot_1_execution_mode` |
| `number.doems_slot_1_power_w` | `<entry_id>_slot_1_power_w` |
| `number.doems_slot_1_target_soc` | `<entry_id>_slot_1_target_soc` |
| `number.doems_slot_1_max_runtime_h` | `<entry_id>_slot_1_max_runtime_h` |
| `number.doems_slot_1_max_start_delay_min` | `<entry_id>_slot_1_max_start_delay_min` |
| `datetime.doems_slot_1_start_time` | `<entry_id>_slot_1_start_time` |
| `sensor.doems_slot_1_status` | `<entry_id>_slot_1_status` |
| `select.doems_slot_2_action` | `<entry_id>_slot_2_action` |
| `select.doems_slot_2_execution_mode` | `<entry_id>_slot_2_execution_mode` |
| `number.doems_slot_2_power_w` | `<entry_id>_slot_2_power_w` |
| `number.doems_slot_2_target_soc` | `<entry_id>_slot_2_target_soc` |
| `number.doems_slot_2_max_runtime_h` | `<entry_id>_slot_2_max_runtime_h` |
| `number.doems_slot_2_max_start_delay_min` | `<entry_id>_slot_2_max_start_delay_min` |
| `datetime.doems_slot_2_start_time` | `<entry_id>_slot_2_start_time` |
| `sensor.doems_slot_2_status` | `<entry_id>_slot_2_status` |
| `select.doems_slot_3_action` | `<entry_id>_slot_3_action` |
| `select.doems_slot_3_execution_mode` | `<entry_id>_slot_3_execution_mode` |
| `number.doems_slot_3_power_w` | `<entry_id>_slot_3_power_w` |
| `number.doems_slot_3_target_soc` | `<entry_id>_slot_3_target_soc` |
| `number.doems_slot_3_max_runtime_h` | `<entry_id>_slot_3_max_runtime_h` |
| `number.doems_slot_3_max_start_delay_min` | `<entry_id>_slot_3_max_start_delay_min` |
| `datetime.doems_slot_3_start_time` | `<entry_id>_slot_3_start_time` |
| `sensor.doems_slot_3_status` | `<entry_id>_slot_3_status` |
| `sensor.doems_plan_store_status` | `<entry_id>_plan_store_status` |
| `sensor.doems_plan_store_revision` | `<entry_id>_plan_store_revision` |
| `sensor.doems_plan_store_reason` | `<entry_id>_plan_store_reason` |
| `sensor.doems_plan_store_generation` | `<entry_id>_plan_store_generation` |
| `sensor.doems_plan_store_fingerprint` | `<entry_id>_plan_store_fingerprint` |
| `sensor.doems_plan_store_overflow` | `<entry_id>_plan_store_overflow` |

Totaal: 24 slotentiteiten en zes centrale diagnose-entiteiten. Er worden geen bestaande Plan72-, Bridge-, Energy Need-, prijs-, solar- of forecast-ID's gewijzigd.

## Regressiebescherming en verificatie

Run `41098892444` is onderzocht: beide Python-jobs faalden uitsluitend op de oude bevroren SHA van `planner_72h_runtime.py` (249 geslaagd, één fout). De toenmalige runtimewijziging verbond onveranderlijke handmatige slotinvoer met worker en fingerprint.

De blobcontroles blijven bestaan. De twee hoofdstuk-7-wijzigingen aan runtime en calculator zijn opnieuw bevroren. Aanvullend worden alle ongewijzigde Alpha53-strategiefuncties en modelmethoden afzonderlijk vergeleken met hun oorspronkelijke AST-hashes via een Python-versie-onafhankelijke representatie. De beperkte calculatoruitbreiding betreft constraint-herkomst en voorbereiding; de veiligheids-/handelsselectie is niet vervangen. Bestaande scenariotests blijven aanwezig.

Nieuwe uitvoeringstests gebruiken de echte opslag-, schrijver-, adapter-, entiteit- en runtimecode, met afgeschermde Home Assistant-randen. Ze oefenen slotvulling, reconciliatie, overflow, handmatige overname, herstart, opslagfalen, bron/revisieraces, voorbereiding en gedeelde energietelling. Dit is geen live verificatie op de Home Assistant-installatie of fysieke batterij.

Publicatie blijft geblokkeerd totdat beide volledige Python-suites en de GitHub Actions-jobs groen zijn én de geregistreerde goedkeuring van dit register aanwezig is. Bestaande release-tags blijven ongewijzigd.

## Correctie Alpha 7.3 — verlopen handmatige startvensters

Verlopen handmatige pending-plannen worden afgesloten en geven hun slot vrij. Bestaande foutplannen met exact `manual_start_window_expired` worden eveneens vrijgegeven zodra hun startvenster aantoonbaar voorbij is. Toekomstige plannen, actieve plannen, concepten en andere foutredenen blijven beschermd. De laatste afgesloten handmatige actie per slot wordt apart persistent bewaard en is zichtbaar als `last_closed_plan`, ook na automatische hervulling en herstart. Opslagfalen draait zowel de vrijgave als het archief terug. De oorspronkelijke herkomst van de door de gebruiker getoonde actie van 6 oktober is hiermee niet vastgesteld.

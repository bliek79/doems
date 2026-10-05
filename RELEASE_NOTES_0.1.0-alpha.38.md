# DOEMS 0.1.0-alpha.38 - Design C Split Reserve Safety

## Doel

Alpha38 corrigeert de live gevonden koppeling tussen toekomstige woningbehoefte en de operationele reservevloer. De planner blijft native 15 minuten / 72 uur / 288 slots en blijft zonder fysieke DOEMS-uitvoeringsautoriteit.

## Design C

- De operationele reserve blijft technische minimum-SOC plus software-reserve (standaard 12%).
- De execution floor blijft de operationele reserve plus de bestaande execution buffer (standaard 14%).
- Toekomstige woningbehoefte tot het volgende bruikbare zonneblok wordt apart gepubliceerd als safety target.
- Backward reachability blijft bepalen hoeveel SOC nu beschermd moet worden om een toekomstige safety-deadline nog te kunnen halen.
- Safety-precharge blijft de goedkoopste technisch haalbare laadvensters vóór de deadline gebruiken.
- Een safety target mag 100% worden zonder dat reserve_floor_soc daardoor 100% wordt.
- Sequentiële replay blijft fail-closed wanneer een safety-deadline niet haalbaar is.

## Observability

Plan72-rijen publiceren nu afzonderlijk:
- reserve_floor_soc
- execution_reserve_floor_soc
- precharge_protection_soc
- safety_target_soc
- safety_target_start_soc

Plan72 publiceert daarnaast de policies:
- fixed_operational_reserve_v1
- split_reserve_safety_reachability_v1

## Ongewijzigde grenzen

- native 15 minuten / 72 uur / 288 slots
- Alpha80 cheapest-energy economische basis
- solar-first en laad-/ontlaadlimieten
- Plan Store, Scheduler, Prestart, Safety Guard en Execution-semantiek
- Alpha33 serialization en Alpha34 verified setpoint handoff
- fysieke DOEMS-uitvoeringsautoriteit blijft uit
- Alpha37 non-blocking Home Assistant startup blijft behouden

## Live vervolg

Na installatie eerst shadow-validatie tegen de oude EMS-planner uitvoeren. Controleer vooral vaste 12% reserve, bewegende precharge protection, safety targets, safety-charge kWh, trade en infeasible status voordat fysieke cutover opnieuw wordt overwogen.

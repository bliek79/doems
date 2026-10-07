"""R5 shadow automatic planner on the native DOEMS quarter route."""
from __future__ import annotations
from collections import defaultdict
from typing import Any, Mapping, Sequence

from .manual_soc_projection_model import (
    FORECAST_SLOTS, SLOT_SECONDS, MIN_SOC_PERCENT, MAX_SOC_PERCENT,
    CHARGE_EFFICIENCY, DISCHARGE_EFFICIENCY, _manual_commitments,
    _slot_price, _validate_time_axis,
)

DEFAULT_SOFTWARE_RESERVE_PERCENT = 5.0
DEFAULT_MAX_CHARGE_POWER_W = 3500.0
DEFAULT_MAX_DISCHARGE_POWER_W = 3500.0
DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH = 0.10
DEFAULT_PEAK_SALE_THRESHOLD_EUR_PER_KWH = 0.50
_EPS = 0.0005


def _simulate(axis, commitments, start_soc, capacity, ce, de, max_c, max_d,
              safety=None, trade_c=None, trade_d=None, peak_d=None):
    safety, trade_c, trade_d, peak_d = safety or {}, trade_c or {}, trade_d or {}, peak_d or {}
    soc = max(MIN_SOC_PERCENT, min(MAX_SOC_PERCENT, float(start_soc)))
    rows=[]
    for slot in axis:
        i=slot['index']; start=slot['start']; end=slot['end']
        active=[]
        for p in commitments:
            overlap=max(0.0,(min(end,p['end'])-max(start,p['start'])).total_seconds())
            if overlap>0: active.append((p,overlap))
        manual_seconds=sum(v for _,v in active); auto_seconds=max(0.0,SLOT_SECONDS-manual_seconds)
        frac=auto_seconds/SLOT_SECONDS; home=float(slot['home_kwh'])*frac; solar=float(slot['solar_kwh'])*frac
        home_total=float(slot['home_kwh']); solar_total=float(slot['solar_kwh']); soc_start=soc
        s2h=min(home,solar); surplus=max(0.0,solar-s2h); deficit=max(0.0,home-s2h)
        c_limit=max_c/1000*auto_seconds/3600; d_limit=max_d/1000*auto_seconds/3600
        head=max(0.0,(100-soc)/100*capacity/ce); solar_c=min(surplus,c_limit,head)
        soc += solar_c*ce/capacity*100; c_left=c_limit-solar_c
        def charge(req):
            nonlocal soc,c_left
            head=max(0.0,(100-soc)/100*capacity/ce); val=min(max(0.0,req),c_left,head)
            soc += val*ce/capacity*100; c_left-=val; return val
        safety_c=charge(float(safety.get(i,0))); trade_charge=charge(float(trade_c.get(i,0)))
        avail=max(0.0,(soc-MIN_SOC_PERCENT)/100*capacity*de); home_d=min(deficit,d_limit,avail)
        soc -= home_d/de/capacity*100; d_left=d_limit-home_d
        def discharge(req):
            nonlocal soc,d_left
            avail=max(0.0,(soc-MIN_SOC_PERCENT)/100*capacity*de); val=min(max(0.0,req),d_left,avail)
            soc -= val/de/capacity*100; d_left-=val; return val
        trade_dis=discharge(float(trade_d.get(i,0))); peak_dis=discharge(float(peak_d.get(i,0)))
        man_c=man_d=0.0; man_slots=[]
        for p,seconds in active:
            req=min(float(p['power_w']),3500.0)/1000*seconds/3600; target=max(MIN_SOC_PERCENT,min(100,float(p['target_soc'])))
            if p['action']=='laden':
                need=max(0.0,(target-soc)/100*capacity/ce); val=min(req,need); soc+=val*ce/capacity*100; man_c+=val
            else:
                avail=max(0.0,(soc-target)/100*capacity*de); val=min(req,avail); soc-=val/de/capacity*100; man_d+=val
            man_slots.append(int(p['slot']))
        soc=max(MIN_SOC_PERCENT,min(100,soc)); prices=slot['prices']
        acts=[]
        if safety_c>_EPS: acts.append('veiligheidsladen')
        if trade_charge>_EPS: acts.append('handelsladen')
        if trade_dis>_EPS: acts.append('handel_ontladen')
        if peak_dis>_EPS: acts.append('piek_ontladen')
        rows.append({
            'index':i,'start':start.isoformat(),'end':end.isoformat(),'home_kwh':round(home_total,6),
            'home_consumption_kwh':round(home_total,6),'solar_kwh':round(solar_total,6),**prices,
            'start_soc_percent':round(soc_start,6),'end_soc_percent':round(soc,6),'soc_end':round(soc,6),
            'solar_to_home_kwh':round(s2h,6),'charge_from_solar_kwh':round(solar_c,6),
            'charge_from_grid_safety_kwh':round(safety_c,6),'charge_from_grid_trade_kwh':round(trade_charge,6),
            'charge_from_grid_kwh':round(safety_c+trade_charge,6),'discharge_to_home_kwh':round(home_d,6),
            'trade_discharge_to_grid_kwh':round(trade_dis,6),'peak_sale_to_grid_kwh':round(peak_dis,6),
            'discharge_to_grid_kwh':round(trade_dis+peak_dis,6),'grid_to_home_kwh':round(max(0,deficit-home_d),6),
            'grid_import_for_home_kwh':round(max(0,deficit-home_d),6),'solar_to_grid_kwh':round(max(0,surplus-solar_c),6),
            'solar_export_kwh':round(max(0,surplus-solar_c),6),'manual_charge_kwh':round(man_c,6),
            'manual_discharge_kwh':round(man_d,6),'manual_slots':sorted(set(man_slots)),
            'automatic_action':'+'.join(acts) if acts else 'geen_actie','automatic_candidate':bool(acts),
            'charge_headroom_kwh':round(min(c_left,max(0,(100-soc)/100*capacity/ce)),6),
            'discharge_headroom_kwh':round(min(d_left,max(0,(soc-MIN_SOC_PERCENT)/100*capacity*de)),6),
            'observational_only':True,
        })
    return rows


def _usable_solar(axis,start=0):
    for i in range(max(0,start),len(axis)-7):
        if all(float(axis[j]['solar_kwh'])>0 and float(axis[j]['solar_kwh'])>=float(axis[j]['home_kwh']) for j in range(i,i+8)):
            return i
    return None


def _hours(rows):
    groups=defaultdict(list)
    from datetime import datetime
    for r in rows:
        t=datetime.fromisoformat(r['start']); groups[t.replace(minute=0,second=0,microsecond=0)].append(r)
    sums=('solar_kwh','home_consumption_kwh','solar_to_home_kwh','charge_from_solar_kwh','charge_from_grid_safety_kwh',
          'charge_from_grid_trade_kwh','charge_from_grid_kwh','discharge_to_home_kwh','discharge_to_grid_kwh',
          'trade_discharge_to_grid_kwh','peak_sale_to_grid_kwh','grid_import_for_home_kwh','solar_export_kwh','manual_charge_kwh','manual_discharge_kwh')
    out=[]
    for t in sorted(groups):
        a=groups[t]; x={'time':t.isoformat(),'slot_count':len(a),'soc_start':a[0]['start_soc_percent'],'soc_end':a[-1]['end_soc_percent'],
                       'manual_slots':sorted({s for r in a for s in r['manual_slots']}),'replanned':True,'automatic_planner_shadow':True}
        for k in sums: x[k]=round(sum(float(r.get(k) or 0) for r in a),6)
        ip=[r['import_price'] for r in a if r.get('import_price') is not None]; ep=[r['export_price'] for r in a if r.get('export_price') is not None]
        if ip: x['price']=x['import_price']=round(sum(ip)/len(ip),8)
        if ep: x['export_price']=round(sum(ep)/len(ep),8)
        out.append(x)
    return out


def build_automatic_plan(*,energy_slots:Sequence[Mapping[str,Any]],solar_slots:Sequence[Mapping[str,Any]],plans:Sequence[Mapping[str,Any]],
                         start_soc_percent:float,capacity_kwh:float,price_by_start:Mapping[str,Mapping[str,Any]]|None,
                         software_reserve_percent:float=DEFAULT_SOFTWARE_RESERVE_PERCENT,charge_efficiency:float=CHARGE_EFFICIENCY,
                         discharge_efficiency:float=DISCHARGE_EFFICIENCY,max_charge_power_w:float=DEFAULT_MAX_CHARGE_POWER_W,
                         max_discharge_power_w:float=DEFAULT_MAX_DISCHARGE_POWER_W,minimum_trade_margin_eur_per_kwh:float=DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
                         peak_sale_threshold_eur_per_kwh:float=DEFAULT_PEAK_SALE_THRESHOLD_EUR_PER_KWH)->dict[str,Any]:
    blockers=[]
    try:
        soc=float(start_soc_percent); cap=float(capacity_kwh); reserve=float(software_reserve_percent); ce=float(charge_efficiency); de=float(discharge_efficiency)
        max_c=float(max_charge_power_w); max_d=float(max_discharge_power_w); margin=float(minimum_trade_margin_eur_per_kwh); peak=float(peak_sale_threshold_eur_per_kwh)
    except (TypeError,ValueError):
        return {'status':'blocked','valid':False,'blockers':['planner_setting_invalid'],'physical_execution_authority':False}
    if not 0<=soc<=100: blockers.append('start_soc_invalid')
    if cap<=0: blockers.append('capacity_invalid')
    if not 0<=reserve<=30 or MIN_SOC_PERCENT+reserve>100: blockers.append('software_reserve_invalid')
    if not .5<=ce<=1: blockers.append('charge_efficiency_invalid')
    if not .5<=de<=1: blockers.append('discharge_efficiency_invalid')
    if not 100<=max_c<=3500: blockers.append('max_charge_power_invalid')
    if not 100<=max_d<=3500: blockers.append('max_discharge_power_invalid')
    if margin<0: blockers.append('trade_margin_invalid')
    if peak<0: blockers.append('peak_sale_threshold_invalid')
    axis0, b=_validate_time_axis(energy_slots,solar_slots); blockers+=b
    commitments,b=_manual_commitments(plans); blockers+=b
    axis=[]
    for r in axis0:
        prices=_slot_price(price_by_start,r['start'])
        if prices['import_price'] is None or prices['export_price'] is None: blockers.append(f"price_slot_{r['index']}_missing")
        axis.append({**r,'prices':prices})
    floor=MIN_SOC_PERCENT+reserve
    base={'automatic_planner_active':True,'automatic_plan_store_writes':False,'scheduler_active':False,'safety_prestart_active':False,
          'execution_enabled':False,'physical_execution_authority':False,'mode':'automatic_planner_shadow','observational_only':True}
    if blockers: return {'status':'blocked','valid':False,'blockers':sorted(set(blockers)),'native_slots':[],'hourly_plan':[],'candidates':[],**base}
    safety={}; tc={}; td={}; pd={}; rt=ce*de
    def sim(): return _simulate(axis,commitments,soc,cap,ce,de,max_c,max_d,safety,tc,td,pd)
    initial=sim(); safety_needed=any(r['end_soc_percent']<floor-1e-6 for r in initial)
    def fill_safety():
        for _ in range(FORECAST_SLOTS):
            tr=sim(); breach=next((i for i,r in enumerate(tr) if r['end_soc_percent']<floor-1e-6),None)
            if breach is None: return
            need=floor-tr[breach]['end_soc_percent']
            cand=[i for i,r in enumerate(tr[:breach+1]) if not r['manual_slots'] and r['import_price'] is not None and r['charge_headroom_kwh']>_EPS and pd.get(i,0)<=_EPS and tc.get(i,0)<=_EPS]
            cand.sort(key=lambda i:(tr[i]['import_price'],-i)); made=False
            for i in cand:
                mx=tr[i]['charge_headroom_kwh']; old=safety.get(i,0); safety[i]=old+mx; trial=sim(); gain=trial[breach]['end_soc_percent']-tr[breach]['end_soc_percent']; safety[i]=old
                if gain<=1e-6: continue
                add=mx if gain<=need else mx*need/gain
                safety[i]=old+add; made=True; break
            if not made: return
    fill_safety(); tr=sim()
    for i in sorted([i for i,r in enumerate(tr) if not r['manual_slots'] and r['export_price'] is not None and r['export_price']>=peak and safety.get(i,0)<=_EPS], key=lambda i:(-tr[i]['export_price'],i)):
        tr=sim(); export=tr[i]['export_price']; pv=_usable_solar(axis,i+1)
        grid=next((j for j in range(i+1,len(axis)) if axis[j]['prices']['import_price'] is not None and export-axis[j]['prices']['import_price']/rt>=margin),None)
        opts=[x for x in (pv,grid) if x is not None]
        if not opts: continue
        reload=min(opts); interval=tr[i:reload]
        if not interval: continue
        free=max(0,min(r['end_soc_percent'] for r in interval)-floor)/100*cap*de; add=min(free,tr[i]['discharge_headroom_kwh'])
        if add>_EPS: pd[i]=add
    fill_safety()
    if not safety_needed and not pd:
        tr=sim(); usable=_usable_solar(axis,0); best=None
        for i,a in enumerate(tr[:-1]):
            if a['manual_slots'] or a['import_price'] is None or a['charge_headroom_kwh']<=_EPS or (usable is not None and i<usable): continue
            cost=a['import_price']/rt
            for j in range(i+1,len(tr)):
                b=tr[j]
                if b['manual_slots'] or b['export_price'] is None: continue
                m=b['export_price']-cost
                if m>=margin and (best is None or m>best[0]): best=(m,i,j)
        if best:
            _,i,j=best; tr=sim(); free=max(0,min(r['end_soc_percent'] for r in tr[j:])-floor)/100*cap*de
            dout=min(free,tr[j]['discharge_headroom_kwh']); cin=min(tr[i]['charge_headroom_kwh'],dout/rt if rt else 0); dout=cin*rt
            if cin>_EPS and dout>_EPS: tc[i]=cin; td[j]=dout
    final=sim(); cand=[]
    types=(('charge_from_grid_safety_kwh','veiligheidsladen','laden','planner_floor_protection'),('charge_from_grid_trade_kwh','handelsladen','laden','normal_arbitrage_margin'),
           ('trade_discharge_to_grid_kwh','handel_ontladen','ontladen','normal_arbitrage_margin'),('peak_sale_to_grid_kwh','piek_ontladen','ontladen','peak_price_with_protected_route_to_recharge'))
    for r in final:
        for field,typ,action,reason in types:
            e=float(r.get(field) or 0)
            if e>_EPS: cand.append({'type':typ,'action':action,'time':r['start'],'energy_kwh':round(e,6),'power_w':round(e*4000,1),'import_price':r.get('import_price'),'export_price':r.get('export_price'),'reason':reason})
    cand.sort(key=lambda x:(x['time'],x['type'])); vals=[r['end_soc_percent'] for r in final]; nxt=cand[0] if cand else None
    hourly=_hours(final)
    return {'status':'ready','valid':True,'blockers':[],'decision':nxt['type'] if nxt else 'geen_actie','reason':nxt['reason'] if nxt else 'no_automatic_candidate',
            'next_candidate':nxt,'candidates':cand,'candidate_count':len(cand),'candidate_types':sorted({x['type'] for x in cand}),'native_slots':final,'hourly_plan':hourly,
            'native_slot_count':len(final),'clock_hour_bucket_count':len(hourly),'start':final[0]['start'],'end':final[-1]['end'],'start_soc_percent':soc,'end_soc_percent':final[-1]['end_soc_percent'],
            'projected_min_soc_percent':round(min(vals),6),'projected_max_soc_percent':round(max(vals),6),'technical_min_soc_percent':MIN_SOC_PERCENT,'software_reserve_percent':reserve,
            'planner_floor_soc_percent':floor,'planner_floor_kwh':round(cap*floor/100,6),'capacity_kwh':round(cap,6),'capacity_source':'battery_input_contract_live_sensor',
            'charge_efficiency_percent':round(ce*100,1),'discharge_efficiency_percent':round(de*100,1),'roundtrip_efficiency_percent':round(rt*100,2),'max_charge_power_w':max_c,'max_discharge_power_w':max_d,
            'minimum_trade_margin_eur_per_kwh':margin,'peak_sale_threshold_eur_per_kwh':peak,'safety_charge_needed':safety_needed,'safety_schedule_sufficient':all(r['end_soc_percent']>=floor-1e-6 for r in final),
            'safety_charge_kwh':round(sum(safety.values()),6),'trade_charge_kwh':round(sum(tc.values()),6),'trade_discharge_kwh':round(sum(td.values()),6),'peak_sale_kwh':round(sum(pd.values()),6),
            'manual_commitment_count':len(commitments),'manual_commitment_slots':[p['slot'] for p in commitments],'usable_solar_rule':'first_of_eight_consecutive_native_quarters_where_solar_gte_home',**base}

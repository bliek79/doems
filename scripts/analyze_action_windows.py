"""Read-only comparison of the original DOEMS Bridge against Alpha52 routes.

Run from a git checkout containing OLD_COMMIT (fetch it if the checkout is
shallow). Uses the unchanged pure Plan72 simulation kernel, not a second planner.
Exact segment replay is a control. Old-style candidates are replayed as fixed
commands without optimizing new safety or trading. No HA state or services.
Two-minute preparation is optimistically passive; forced zero-power preparation
is NOT modelled. Results cannot be called a physical safety validation.
For incomplete old-bridge prefixes no full-horizon window comparison is reported.
"""
import sys,json,subprocess,importlib.util,types
from pathlib import Path
from datetime import datetime,timedelta,timezone
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('window_probe_plan72',ROOT/'custom_components/doems/planner_72h.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
calculate_plan72=m.calculate_plan72
NOW=datetime(2026,10,29,12,tzinfo=timezone.utc)
OLD_COMMIT='d0c3a133dadcb94136e0641f25644780bd395ad6'
def rows(value):
 return [dict(start=NOW+timedelta(minutes=15*i),energy_kwh=value(i) if callable(value) else value) for i in range(288)]
def prices(import_price):
 return [dict(start=NOW+timedelta(minutes=15*i),import_all_in=import_price(i),export_all_in=.05,kind='forecast') for i in range(288)]

def stamp(s):return datetime.fromisoformat(s)
def experiment(name,home,solar,tariff):
 h=rows(home);s=rows(solar);p=tariff
 plan=calculate_plan72(h,s,p,now=NOW,soc_percent=50,capacity_kwh=7.2,min_soc_percent=5,reserve_percent=5,max_charge_power_w=3200,max_discharge_power_w=3200,trade_enabled=False)
 b=m._Battery(7.2,3.6,.36,.72,.92,.92,3.2,3.2)
 ts=[x['start'] for x in h]
 def replay(commands):
  model=m._Model(ts,[x['energy_kwh'] for x in h],[x['energy_kwh'] for x in s],[(x['import_all_in'],x['export_all_in'],x['kind']) for x in p],b,commands)
  return model.simulate({},detail=True)[0]
 exact=[];groups=[]
 for i,row in enumerate(plan['timeline']):
  forced=[x for x in row['segments'] if x['origin']=='safety']
  if not forced:continue
  for part in forced:
   exact.append(m._Manual('exact'+str(len(exact)),'charge',stamp(part['start']),stamp(part['end']),part['battery_power_w']/1000,part['stored_end_kwh']))
  if groups and groups[-1][-1][0]+1==i:groups[-1].append((i,row,forced))
  else:groups.append([(i,row,forced)])
 source=subprocess.check_output(['git','show',OLD_COMMIT+':custom_components/doems/automatic_slot_bridge_model.py'],cwd=ROOT,text=True)
 old=types.ModuleType('old_bridge');exec(compile(source,'old_bridge','exec'),old.__dict__)
 native=[]
 for i,r in enumerate(plan['timeline']):
  native.append(dict(index=i,start=r['start'],end=r['end'],start_soc_percent=r['soc_start'],
   charge_from_grid_safety_kwh=r['charge_from_grid_safety_kwh'],
   charge_from_grid_trade_kwh=r['charge_from_grid_trade_kwh'],
   trade_discharge_to_grid_kwh=r['discharge_to_grid_trade_kwh'],manual_slots=[],manual_overlap_seconds=0.,price_source='known'))
 result=old.build_automatic_slot_proposals(dict(status='ready',valid=True,native_slot_count=288,native_slots=native,capacity_kwh=7.2,charge_efficiency_percent=92.,discharge_efficiency_percent=92.,max_charge_power_w=3200.,max_discharge_power_w=3200.),now=NOW-timedelta(seconds=1))
 windows=[];descriptions=[]
 for gi,proposal in enumerate(result['proposals']):
  start=stamp(proposal['start_time'])+timedelta(minutes=2)
  end=stamp(proposal['planned_end_time'])
  windows.append(m._Manual('old'+str(gi),'charge',start,end,proposal['power_w']/1000,7.2*proposal['target_soc']/100))
  descriptions.append(proposal)
 e=replay(exact);w=replay(windows)
 def summary(trace):
  return {'min_soc':min(x['min_soc'] for x in trace),'end_soc':trace[-1]['soc_end'],
   'reserve_breaches':sum(x['reserve_min_gap_kwh']>1e-5 for x in trace),
   'grid_charge_kwh':sum(sum(x['charge_from_grid_'+k+'_kwh'] for k in ('safety','trade','manual')) for x in trace),
   'home_discharge_kwh':sum(x['discharge_to_home_kwh'] for x in trace),
   'grid_home_kwh':sum(x['grid_import_for_home_kwh'] for x in trace),
   'pv_charge_kwh':sum(x['charge_from_solar_kwh'] for x in trace)}
 out={'case':name,'baseline_status':plan['status'],'source_segment_count':len(exact),'merged_window_count':len(windows),
  'exact_replay_max_soc_difference':max(abs(x['soc_end']-y['soc_end']) for x,y in zip(plan['timeline'],e)),
  'window_max_soc_difference':max(abs(x['soc_end']-y['soc_end']) for x,y in zip(plan['timeline'],w)) if len(windows)==result['window_count'] else None,
  'baseline':summary(plan['timeline']),'windows':summary(w) if len(windows)==result['window_count'] else None,'old_bridge_rejected':result['rejected'],'old_bridge_window_count':result['window_count'],'complete_coverage':len(windows)==result['window_count'],'first_window':{k:descriptions[0][k] for k in ('start_time','planned_end_time','power_w','target_soc')} if descriptions else None}
 assert out['exact_replay_max_soc_difference'] < 1e-6, 'replay control failed'
 print(json.dumps(out))
experiment('constant_home_no_pv',.15,0.,prices(lambda i:.1 if i%96>=50 else .3))
experiment('variable_home_with_pv',lambda i:.15 if i%96<48 else .08,lambda i:.20 if 32<=i%96<48 else 0.,prices(lambda i:.1 if i%96<24 else .3))
experiment('low_home_no_pv',.02,0.,prices(lambda i:.1 if i%96<24 else .3))

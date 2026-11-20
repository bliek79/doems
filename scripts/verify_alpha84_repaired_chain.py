"""Evidence report: original Alpha84 -> native-quarter strategy -> actual Plan72/Bridge.

This is a *differential diagnostic*, not an acceptance waiver. Full raw rows,
source windows, native windows and all rejection reasons are retained. Distinct
15-minute allocation and two-minute handoff effects are reported explicitly.

Run: python scripts/verify_alpha84_repaired_chain.py --output report.json
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from compare_alpha84_planners import NOW, reference, scenarios

package_name = 'doems_native_parity_diagnostic'
package = types.ModuleType(package_name)
package.__path__ = [str(ROOT/'custom_components'/'doems')]
sys.modules[package_name] = package
native = importlib.import_module(package_name+'.planner_72h')
bundle = importlib.import_module(package_name+'.alpha84_bundle')
bridge = importlib.import_module(package_name+'.planner_action_bridge')

FLOWS = ('charge_from_solar_kwh', 'charge_from_grid_safety_kwh',
         'charge_from_grid_trade_kwh', 'discharge_to_home_kwh',
         'discharge_to_grid_kwh', 'grid_import_for_home_kwh',
         'solar_export_kwh')


def classify_source_differences(differences):
    """Group observed differences by FIELD, not by assumed cause.

    A matching field does not establish strategic parity. In particular, SOC
    drift and charge timing may be either legitimate quarter resolution or an
    incorrect safety allocation; both require explicit review.
    """
    grouped = {
        'safety_allocation_review': [],
        'soc_trajectory_review': [],
        'trade_allocation_review': [],
        'other_flow_review': [],
    }
    for item in differences:
        field = item['field']
        if field == 'soc_end':
            category = 'soc_trajectory_review'
        elif field == 'charge_from_grid_safety_kwh':
            category = 'safety_allocation_review'
        elif field in ('charge_from_grid_trade_kwh', 'discharge_to_grid_kwh'):
            category = 'trade_allocation_review'
        else:
            category = 'other_flow_review'
        grouped[category].append(item)
    return grouped


def summarize(rows):
    return {key: round(sum(row.get(key, 0) for row in rows), 6) for key in FLOWS}


def compare_case(original_rows, soc):
    original_need = reference('energy_need')['build_energy_need_analysis'](original_rows, soc, 5, now=NOW)
    original_preview = reference('planner_preview')['build_planner_preview'](
        original_rows, original_need, soc, 92, 92, .1, 3200, 3200, now=NOW)
    # The same frozen original uses buffer=0 in the established synthetic
    # comparison; Alpha84's standalone live default is 2%, a separate gate.
    original_plan = reference('planner_72h')['build_72h_plan_preview'](
        original_rows, original_need, original_preview, soc, 92, 92, 0,
        3200, 3200, now=NOW)
    original_bridge = reference('planner_action_bridge')['build_planner_action_bridge'](
        dict(original_plan, forecast_ready=True,
             max_charge_power_w=3200, max_discharge_power_w=3200,
             battery_capacity_kwh=7.2, charge_efficiency_percent=92,
             discharge_efficiency_percent=92), now=NOW)
    price_points=[]; home_points=[]; solar_points=[]; forecast=[]
    for hour in original_rows:
        start=datetime.fromisoformat(hour['time'])
        for q in range(4):
            t=start+timedelta(minutes=q*15)
            home=hour['home_consumption_kwh']/4
            solar=hour['solar_kwh']/4
            forecast.append(dict(time=t.isoformat(),
                home_consumption_kwh=home, solar_kwh=solar,
                import_price=hour['import_price'], export_price=hour['export_price'],
                price_source='known'))
            home_points.append(dict(start=t, energy_kwh=home))
            solar_points.append(dict(start=t, energy_kwh=solar))
            price_points.append(dict(start=t, import_all_in=hour['import_price'],
                export_all_in=hour['export_price'], kind='known'))
    parameters=dict(now=NOW, soc_percent=soc, capacity_kwh=7.2,
        min_soc_percent=5, reserve_percent=5, charge_efficiency=.92,
        discharge_efficiency=.92, max_charge_power_w=3200,
        max_discharge_power_w=3200, minimum_trade_margin=.1,
        trade_enabled=True, execution_buffer_percent=0)
    strategy=bundle.compute_strategy_bundle(forecast, **parameters)
    plan=native.calculate_plan72(home_points, solar_points, price_points,
        practical_windows=True, strategy_factory=bundle.compute_strategy_bundle,
        **parameters)
    plan.update(battery_parameters={key:val for key,val in parameters.items()
        if key not in ('now', 'soc_percent', 'minimum_trade_margin', 'trade_enabled')},
        plan_generation=1, input_fingerprint='frozen-identical-synthetic-72h',
        calculated_at=NOW.isoformat())
    final_bridge=bridge.build_action_bridge(plan,now=NOW)
    source_rows=strategy['plan72']['auto_plan_72h_plan']
    native_rows=plan['timeline']
    hourly_differences=[]
    source_native_differences=[]
    for hour, reference_hour in enumerate(original_plan['auto_plan_72h_plan']):
        slices=source_rows[4*hour:4*hour+4]
        native_slices=native_rows[4*hour:4*hour+4]
        for key in (*FLOWS,'soc_end'):
            source=(slices[-1]['soc_end'] if key=='soc_end' else sum(x[key] for x in slices))
            original=reference_hour[key]
            physical=(native_slices[-1]['soc_end'] if key=='soc_end' else sum(x[key] for x in native_slices))
            tol=.05000001 if key=='soc_end' else .00050001
            if abs(source-original)>tol:
                hourly_differences.append(dict(hour=hour,field=key,source=source,
                                               alpha84=original,precision_tolerance=tol))
            if abs(physical-source)>tol:
                source_native_differences.append(dict(hour=hour,field=key,
                    source=source,plan72=physical,precision_tolerance=tol))
    grouped_source_differences = classify_source_differences(hourly_differences)
    safety_source=sum(x['charge_from_grid_safety_kwh'] for x in source_rows)
    trading_source=[sum(x[f] for x in source_rows) for f in (
        'charge_from_grid_trade_kwh','discharge_to_grid_kwh')]
    return dict(
        comparison_contract=dict(original_hourly_interval_minutes=60,
            native_interval_minutes=15, source_price_averaging=False,
            execution_buffer_percent=0, alpha84_default_execution_buffer_percent=2,
            native_power_handoff_minutes=2, accepted=False),
        input=dict(soc=soc, now=NOW.isoformat(), original_hourly=original_rows,
                   native_quarters=forecast),
        alpha84=dict(preview=original_preview, plan=original_plan,
                     bridge_candidates=original_bridge['auto_bridge_candidates'],
                     totals=summarize(original_plan['auto_plan_72h_plan'])),
        source_quarter=dict(plan=strategy['plan72'],
                     bridge_candidates=strategy['action_bridge']['auto_bridge_candidates'],
                     totals=summarize(source_rows),
                     protected_interval_count=strategy['protected_interval_count']),
        native_plan72=dict(plan=plan, bridge=final_bridge, totals=summarize(native_rows)),
        diagnostic=dict(hourly_source_differences=hourly_differences,
             source_vs_physical_differences=source_native_differences,
             hourly_source_difference_count=len(hourly_differences),
             hourly_source_differences_by_field_group=grouped_source_differences,
             source_strategy_parity_verified=not hourly_differences,
             source_native_difference_count=len(source_native_differences),
             candidate_counts=dict(alpha84=original_bridge['auto_bridge_candidate_count'],
                 source=strategy['action_bridge']['auto_bridge_candidate_count'],
                 native=len(plan['action_windows']), bridge=final_bridge['candidate_count'],
                 accepted=len(final_bridge['slot_preview'])),
             rejected_candidates=[c for c in final_bridge['candidates']
                 if c.get('selection_status')!='eligible'],
             source_trade_kwh=trading_source, source_safety_kwh=safety_source,
             all_energy_conserved=True if plan['valid'] else False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case',choices=list(scenarios()),action='append')
    parser.add_argument('--require-source-parity', action='store_true',
        help='Fail rather than accept any unexplained hourly-vs-quarter source mismatch')
    args=parser.parse_args()
    cases={}
    for name,(rows,soc) in scenarios().items():
        if args.case and name not in args.case:
            continue
        cases[name]=compare_case(rows,soc)
        d=cases[name]['diagnostic']
        print(f"{name}: original/source/Plan72/Bridge candidate counts {d['candidate_counts']};"
              f" hourly-source deviations={d['hourly_source_difference_count']}"
              f" source-vs-physical deviations={d['source_native_difference_count']}")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(status='DIAGNOSTIC_ONLY_NOT_ACCEPTED',
        cases=cases),ensure_ascii=False,indent=2,default=str)+'\n')
    if args.require_source_parity and any(
            case['diagnostic']['hourly_source_differences'] for case in cases.values()):
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())

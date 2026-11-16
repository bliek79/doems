"""Atomic strategy bundle, matching Alpha84's planner_multirate ownership.

Pure worker entry point: no HA reads, Store mutations, or execution calls.
The runtime migration must retain manual constraints before adopting this API.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from math import isfinite

from .alpha84_planning import (
    build_energy_need_analysis, build_planner_preview, build_72h_plan_preview,
)
from .alpha84_action_bridge import build_planner_action_bridge


def compute_strategy_bundle(forecast, *, now, soc_percent, capacity_kwh,
                            min_soc_percent, reserve_percent,
                            charge_efficiency, discharge_efficiency,
                            max_charge_power_w, max_discharge_power_w,
                            minimum_trade_margin, trade_enabled=True,
                            interval_minutes=15, protected_intervals=None,
                            execution_buffer_percent=2.0):
    """Use one validated forecast for allocation, SOC route and action grouping.

    Forecast energies are per interval, prices remain unaveraged. One source
    snapshot is copied before any stage; consumers receive no references into
    the caller's input. The source's explicit action energies feed the Bridge.
    """
    if (not isinstance(now, datetime) or now.tzinfo is None
            or isinstance(interval_minutes, bool) or interval_minutes not in (15, 60)):
        raise ValueError('invalid_strategy_time_basis')
    parameters = (soc_percent, capacity_kwh, min_soc_percent, reserve_percent,
                  charge_efficiency, discharge_efficiency, max_charge_power_w,
                  max_discharge_power_w, minimum_trade_margin, execution_buffer_percent)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v)
           for v in parameters):
        raise ValueError('invalid_strategy_parameters')
    if (not 0 <= soc_percent <= 100 or capacity_kwh <= 0
            or not 0 <= min_soc_percent < 100
            or not 0 <= reserve_percent <= min(30, 100-min_soc_percent)
            or not .5 <= charge_efficiency <= 1 or not .5 <= discharge_efficiency <= 1
            or min(max_charge_power_w, max_discharge_power_w, minimum_trade_margin) < 0
            or not 0 <= execution_buffer_percent <= 10
            or not isinstance(trade_enabled, bool)):
        raise ValueError('unsupported_strategy_parameters')
    rows = deepcopy(forecast)
    if len(rows) != 72*60//interval_minutes:
        raise ValueError('incomplete_strategy_horizon')
    previous = None
    for row in rows:
        stamp = datetime.fromisoformat(str(row['time']).replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.second or stamp.microsecond or stamp.minute % interval_minutes:
            raise ValueError('invalid_strategy_timestamp')
        stamp = stamp.astimezone(timezone.utc)
        if previous is not None and stamp-previous != timedelta(minutes=interval_minutes):
            raise ValueError('noncontiguous_strategy_forecast')
        for key in ('home_consumption_kwh', 'solar_kwh', 'import_price', 'export_price'):
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError('invalid_strategy_forecast_value')
            if key in ('home_consumption_kwh', 'solar_kwh') and value < 0:
                raise ValueError('negative_strategy_forecast_energy')
        row['time'] = stamp.isoformat()
        previous = stamp
    # The caller's *native Plan72* projection provides committed manual/due/
    # active energy and reserved quarter intervals. This is input to Alpha84's
    # original cheapest-feasible-window decision, not a second SOC authority.
    # No source input may change outside this explicitly constrained path.
    protected = deepcopy(protected_intervals or {})
    if protected and interval_minutes != 15:
        raise ValueError('protected_intervals_require_quarter_basis')
    known_stamps = {row['time'] for row in rows}
    for stamp, detail in protected.items():
        if stamp not in known_stamps or not isinstance(detail, dict):
            raise ValueError('invalid_protected_strategy_interval')
        value = detail.get('stored_delta_kwh')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError('invalid_protected_energy_commitment')
    common = dict(now=now, capacity_kwh=capacity_kwh,
                  min_soc_percent=min_soc_percent, interval_minutes=interval_minutes)
    need = build_energy_need_analysis(rows, soc_percent, reserve_percent, **common)
    preview = build_planner_preview(rows, need, soc_percent,
        charge_efficiency*100, discharge_efficiency*100, minimum_trade_margin,
        max_charge_power_w, max_discharge_power_w,
        protected_intervals=protected, **common)
    if not trade_enabled:
        preview['planner_preview_trade_profitable'] = False
    plan = build_72h_plan_preview(rows, need, preview, soc_percent,
        charge_efficiency*100, discharge_efficiency*100, execution_buffer_percent,
        max_charge_power_w, max_discharge_power_w,
        protected_intervals=protected, **common)
    actions = build_planner_action_bridge(dict(plan, forecast_ready=True,
        max_charge_power_w=max_charge_power_w, max_discharge_power_w=max_discharge_power_w,
        battery_capacity_kwh=capacity_kwh, charge_efficiency_percent=charge_efficiency*100,
        discharge_efficiency_percent=discharge_efficiency*100),
        now=now, interval_minutes=interval_minutes)
    return dict(energy_need=need, planner_preview=preview, plan72=plan,
                action_bridge=actions, physical_execution_authority=False,
                execution_enabled=False, interval_minutes=interval_minutes,
                protected_interval_count=len(protected),
                execution_buffer_percent=execution_buffer_percent)

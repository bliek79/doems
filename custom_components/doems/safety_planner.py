"""Native-quarter adaptation of alpha39/ems_alpha36 cheapest-energy safety.

Reference: DOEMS 0.1.0-alpha.39 ems_alpha36/planner_preview.py,
_simulate_safety and the maximum-improvement / binary-allocation loop.
Only scalar battery state is replayed for safety probes. Unlike the historical
hour adapter, inputs and commitments here retain exact native quarter timing.
No historical Plan Store, scheduler or execution authority is imported.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence


def prepare_deadline_probe(slots, schedule, route_soc, start_soc, capacity,
                           charge_eff, discharge_eff, deadline):
    """Compose exact scalar transitions between manual target clamps.

    Each quarter maps stored energy to clamp(stored + offset, floor, ceiling).
    Compositions retain this form. A changed charge at one quarter therefore
    needs one local transition and one composed suffix, without route replay.
    Manual target transitions remain explicit between composed segments.
    """
    floor = .05 * capacity
    suffixes = [None] * (deadline + 1)
    operations = []
    for index in range(deadline, -1, -1):
        suffixes[index] = tuple(operations)
        surplus, deficit, charge_limit, discharge_limit, manual, _ = slots[index]
        incoming = min(charge_limit, surplus + max(0.0, schedule.get(index, 0.0))) * charge_eff
        outgoing = min(deficit, discharge_limit) / discharge_eff
        local_upper = max(floor, capacity - outgoing)
        if manual:
            operations.insert(0, ("manual", manual))
        if operations and operations[0][0] != "manual":
            offset, lower, upper = operations[0]
            operations[0] = (incoming - outgoing + offset,
                             min(upper, max(lower, floor + offset)),
                             min(upper, max(lower, local_upper + offset)))
        else:
            operations.insert(0, (incoming - outgoing, floor, local_upper))

    def apply_manual(stored, manual):
        for charging, requested, target in manual:
            target_stored = target / 100.0 * capacity
            if charging:
                stored += min(requested, max(0.0, target_stored - stored) / charge_eff) * charge_eff
            else:
                stored -= min(requested, max(0.0, stored - target_stored) * discharge_eff) / discharge_eff
        return max(floor, min(capacity, stored))

    def probe(index, charge):
        stored = (start_soc if index == 0 else route_soc[index - 1]) / 100.0 * capacity
        surplus, deficit, charge_limit, discharge_limit, manual, _ = slots[index]
        incoming = min(charge_limit, surplus + max(0.0, charge)) * charge_eff
        outgoing = min(deficit, discharge_limit) / discharge_eff
        stored = max(floor, min(capacity, stored + incoming) - outgoing)
        stored = apply_manual(stored, manual)
        for operation in suffixes[index]:
            if operation[0] == "manual":
                stored = apply_manual(stored, operation[1])
            else:
                delta, low, high = operation
                stored = min(high, max(low, stored + delta))
        return stored / capacity * 100.0

    return probe


def prepare_safety_slots(
    axis: Sequence[Mapping[str, Any]],
    commitments: Sequence[Mapping[str, Any]],
    capacity_kwh: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    max_charge_power_w: float,
    max_discharge_power_w: float,
) -> list[tuple]:
    """Resolve immutable power, solar and manual overlap once per stage."""
    slots = []
    for slot in axis:
        active = []
        seconds = 0.0
        for plan in commitments:
            overlap = max(0.0, (min(slot['end'], plan['end']) - max(slot['start'], plan['start'])).total_seconds())
            if overlap:
                seconds += overlap
                requested = min(float(plan['power_w']), 3500.0) / 1000.0 * overlap / 3600.0
                target = max(5.0, min(100.0, float(plan['target_soc'])))
                active.append((plan['action'] == 'laden', requested, target))
        free_seconds = max(0.0, 900.0 - seconds)
        fraction = free_seconds / 900.0
        net = (float(slot['solar_kwh']) - float(slot['home_kwh'])) * fraction
        slots.append((max(0.0, net), max(0.0, -net),
                      max_charge_power_w / 1000.0 * free_seconds / 3600.0,
                      max_discharge_power_w / 1000.0 * free_seconds / 3600.0,
                      tuple(active), slot['prices'].get('import_price')))
    return slots


def replay_safety(
    slots: Sequence[tuple], schedule: Mapping[int, float],
    start_soc: float, capacity: float, charge_eff: float, discharge_eff: float,
    *, stop: int | None = None, check_work: Callable[[], None] | None = None,
) -> tuple[list[float], list[float]]:
    """Alpha80 scalar solar -> grid-charge -> home-discharge replay.

SOC is carried unrounded between quarters, as in the public simulation.
Combined manual target clamps run after each quarter's automatic fraction.
Probes can end at a deadline (alpha39 sequential_safety.py replay(length)).
"""
    stored = max(5.0, min(100.0, start_soc)) / 100.0 * capacity
    floor = 0.05 * capacity
    end_soc, headroom = [], []
    limit = len(slots) if stop is None else stop + 1
    for index in range(limit):
        if check_work is not None and index % 16 == 0:
            check_work()
        surplus, deficit, charge_limit, discharge_limit, manual, _price = slots[index]
        solar_charge = min(surplus, charge_limit, max(0.0, capacity - stored) / charge_eff)
        stored += solar_charge * charge_eff
        charge_left = charge_limit - solar_charge
        actual = min(max(0.0, schedule.get(index, 0.0)), charge_left,
                     max(0.0, capacity - stored) / charge_eff)
        stored += actual * charge_eff
        charge_left -= actual
        if stop is None:
            headroom.append(min(charge_left, max(0.0, capacity - stored) / charge_eff))
        output = min(deficit, discharge_limit, max(0.0, stored - floor) * discharge_eff)
        stored -= output / discharge_eff
        for charging, requested, target in manual:
            target_stored = target / 100.0 * capacity
            if charging:
                stored += min(requested, max(0.0, target_stored - stored) / charge_eff) * charge_eff
            else:
                stored -= min(requested, max(0.0, stored - target_stored) * discharge_eff) / discharge_eff
        stored = max(floor, min(capacity, stored))
        if stop is None:
            end_soc.append(stored / capacity * 100.0)
    if stop is not None:
        end_soc.append(stored / capacity * 100.0)
    return end_soc, headroom

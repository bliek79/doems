"""Common prestart guard must not distinguish manual from automatic origins."""
from custom_components.doems.execution_common_safety import common_prestart_blockers


def valid(origin):
    return {
        "action": "laden", "origin": origin, "power_w": 300,
        "target_soc": 80,
    }, {
        "status": "ready", "soc_percent": 40,
        "charge_power_w": 0, "discharge_power_w": 0,
    }, {"max_charge_power_w": 3200, "max_discharge_power_w": 3200}


def check(origin, *, mutate=None, fresh=True):
    plan, snapshot, limits = valid(origin)
    if mutate:
        mutate(plan, snapshot, limits)
    return common_prestart_blockers(plan, snapshot, limits, sources_fresh=fresh)


def test_manual_and_automatic_identical_safe_result():
    assert check("manual") == check("automatic_72h_planner") == []


def test_manual_and_automatic_identical_fail_closed_stale():
    for origin in ("manual", "automatic_72h_planner"):
        assert "battery_sources_not_ready" in check(origin, fresh=False)


def test_block_wrong_direction_and_invalid_soc_for_both():
    for origin in ("manual", "automatic_72h_planner"):
        assert "unexpected_discharge" in check(
            origin, mutate=lambda p, s, l: s.update(discharge_power_w=200))
        assert "invalid_soc" in check(
            origin, mutate=lambda p, s, l: s.update(soc_percent=None))


def test_block_limit_and_target_for_both():
    for origin in ("manual", "automatic_72h_planner"):
        assert "invalid_power_limit" in check(
            origin, mutate=lambda p, s, l: p.update(power_w=3300))
        assert "charge_target_already_reached" in check(
            origin, mutate=lambda p, s, l: s.update(soc_percent=80))


def test_discharge_reserve_and_inverted_flow():
    for origin in ("manual", "automatic_72h_planner"):
        assert "discharge_reserve_or_target_reached" in check(
            origin, mutate=lambda p, s, l: (
                p.update(action="ontladen", target_soc=10),
                s.update(soc_percent=5)))
        assert "unexpected_charge" in check(
            origin, mutate=lambda p, s, l: (
                p.update(action="ontladen", target_soc=10),
                s.update(charge_power_w=200)))

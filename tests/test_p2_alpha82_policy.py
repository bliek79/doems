"""P2: Alpha82 pure safety policy regression in DOEMS."""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"


def load_pure(name):
    path = COMPONENT / (name + ".py")
    spec = importlib.util.spec_from_file_location("doems_alpha82_" + name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


power = load_pure("charge_power_limit")
reset = load_pure("execution_status_reset")


class PowerLimitTests(unittest.TestCase):
    def test_deep_discharge_2620_is_reduced_to_battery_2408(self):
        decision = power.choose_charge_power(2620, {"min": 0, "max": 2408, "step": 1}, configured_max_w=3500)
        self.assertEqual((decision.planned_w, decision.applied_w), (2620, 2408))
        self.assertTrue(decision.limited)

    def test_normal_battery_does_not_degrade_valid_plan(self):
        self.assertEqual(power.choose_charge_power(2620, {"min": 0, "max": 3500}, configured_max_w=3500).applied_w, 2620)

    def test_dynamic_limit_can_change_without_policy_change(self):
        limits = {"min": 0, "max": 2408, "step": 1}
        self.assertEqual(power.choose_charge_power(2620, limits, configured_max_w=3500).applied_w, 2408)
        limits["max"] = 2075
        self.assertEqual(power.choose_charge_power(2620, limits, configured_max_w=3500).applied_w, 2075)
        limits["max"] = 3000
        self.assertEqual(power.choose_charge_power(2620, limits, configured_max_w=3500).applied_w, 2620)

    def test_number_step_and_offset_are_respected(self):
        self.assertEqual(power.choose_charge_power(2620, {"min": 100, "max": 2408, "step": 25}, configured_max_w=3500).applied_w, 2400)

    def test_missing_invalid_or_too_low_hardware_limit_fails_closed(self):
        for data in ({}, {"max": None}, {"max": "unavailable"}, {"max": float("nan")}, {"min": 0, "max": 90}, {"min": 2500, "max": 2408}, {"max": 2408, "step": 0}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                power.choose_charge_power(2620, data, configured_max_w=3500)

    def test_never_overrides_configured_ems_maximum(self):
        with self.assertRaises(ValueError):
            power.choose_charge_power(2620, {"max": 3500}, configured_max_w=2400)
        self.assertEqual(power.choose_charge_power(2200, {"max": 2408}, configured_max_w=2200).applied_w, 2200)


class ResetPolicyTests(unittest.TestCase):
    def setUp(self):
        self.execution = {"active": False, "auto_mode_switch_active": False, "status": "emergency_stopped"}
        self.test = {"active": False}

    def can_reset(self, **kwargs):
        args = {"automatic_armed": False, "operating_mode": "self_consumption", "power_state": "0"}
        args.update(kwargs)
        return reset.check_execution_status_reset(self.execution, self.test, **args)

    def test_finished_emergency_with_zero_or_unavailable_control(self):
        self.assertIsNone(self.can_reset())
        self.assertIsNone(self.can_reset(power_state="unavailable"))

    def test_no_restart_or_arm_can_be_hidden(self):
        for kwargs in ({"automatic_armed": True}, {"operating_mode": "third_party_control"}, {"operating_mode": None}, {"power_state": "350"}, {"power_state": "invalid"}):
            with self.subTest(kwargs=kwargs):
                self.assertIsNotNone(self.can_reset(**kwargs))
        self.execution["active"] = True
        self.assertIsNotNone(self.can_reset())
        self.execution["active"] = False
        self.execution["auto_mode_switch_active"] = True
        self.assertIsNotNone(self.can_reset())
        self.execution["auto_mode_switch_active"] = False
        self.test["active"] = True
        self.assertIsNotNone(self.can_reset())
        self.test["active"] = False
        self.execution["status"] = "stop_error"
        self.assertIsNotNone(self.can_reset())



if __name__ == "__main__":
    unittest.main()

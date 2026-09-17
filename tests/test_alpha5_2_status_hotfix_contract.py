from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_doems_status_option_count_is_safe_for_unhashable_values() -> None:
    text = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert 'value not in {None, ""}' not in text
    assert "value is not None" in text
    assert 'value != ""' in text

    options = {
        "instance_name": "DOEMS",
        "energy_forecast_enabled": True,
        "solar_inverter_groups": [{"group_id": "inv_1", "ac_limit_kw": 3.68}],
        "solar_arrays": [{"array_id": "arr_1", "group_id": "inv_1"}],
        "optional_none": None,
        "optional_empty": "",
    }
    configured_fields = sum(
        1
        for key, value in options.items()
        if key not in {"instance_name", "energy_forecast_enabled"}
        and value is not None
        and value != ""
    )
    assert configured_fields == 2


def test_alpha5_2_status_fix_is_carried_forward_into_alpha7() -> None:
    const_text = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert 'VERSION = "0.1.0-alpha.7"' in const_text
    assert manifest["version"] == "0.1.0-alpha.7"
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert 'value not in {None, ""}' not in sensor

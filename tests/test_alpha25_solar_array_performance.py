from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_alpha25_array_performance_contract_is_configurable_and_backward_compatible() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    config = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    foundation = (INTEGRATION / "solar_foundation_model.py").read_text(encoding="utf-8")
    forecast = (INTEGRATION / "solar_forecast_model.py").read_text(encoding="utf-8")

    assert 'SOLAR_DEFAULT_PERFORMANCE_FACTOR = 0.90' in const
    assert '"performance_factor_percent"' in config
    assert '"performance_factor": round(float(user_input["performance_factor_percent"]) / 100.0, 6)' in config
    assert 'item.setdefault("performance_factor", SOLAR_DEFAULT_PERFORMANCE_FACTOR)' in foundation
    assert 'array.get("performance_factor", SOLAR_PERFORMANCE_FACTOR)' in forecast


def test_alpha25_translations_expose_percentage_field() -> None:
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    nl = json.loads((INTEGRATION / "translations" / "nl.json").read_text(encoding="utf-8"))
    en = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))

    assert strings["options"]["step"]["solar_array"]["data"]["performance_factor_percent"]
    assert "(%)" in nl["options"]["step"]["solar_array"]["data"]["performance_factor_percent"]
    assert "(%)" in en["options"]["step"]["solar_array"]["data"]["performance_factor_percent"]


def test_alpha25_keeps_shading_learning_out_of_runtime() -> None:
    runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            INTEGRATION / "solar_forecast.py",
            INTEGRATION / "solar_forecast_model.py",
            INTEGRATION / "solar_foundation_model.py",
        )
    ).lower()
    assert "corrected forecast" not in runtime
    assert "shading_learning" not in runtime
    assert "obstruction_learning" not in runtime

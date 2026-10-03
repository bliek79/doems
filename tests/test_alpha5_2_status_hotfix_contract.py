from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def test_status_option_count_is_safe_for_unhashable_values() -> None:
    text=(INTEGRATION/"sensor.py").read_text(encoding="utf-8")
    assert 'value not in {None, ""}' not in text
    assert "value is not None" in text
    assert 'value != ""' in text

def test_status_fix_is_carried_forward_in_alpha34() -> None:
    const=(INTEGRATION/"const.py").read_text(encoding="utf-8")
    manifest=json.loads((INTEGRATION/"manifest.json").read_text(encoding="utf-8"))
    assert 'VERSION = "0.1.0-alpha.34"' in const
    assert manifest["version"]=="0.1.0-alpha.34"

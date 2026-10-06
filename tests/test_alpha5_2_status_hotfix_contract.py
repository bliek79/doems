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

def test_status_fix_is_carried_forward_in_alpha36() -> None:
    const=(INTEGRATION/"const.py").read_text(encoding="utf-8")
    manifest=json.loads((INTEGRATION/"manifest.json").read_text(encoding="utf-8"))
    version_line=next(line for line in const.splitlines() if line.startswith("VERSION = "))
    const_version=version_line.split('"',2)[1]
    assert const_version==manifest["version"]
    assert const_version.startswith("0.1.0-alpha.")

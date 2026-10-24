"""Import integration and all modules against an installed HA package, without setup."""
import importlib
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
importlib.import_module('custom_components.doems')
for path in sorted((ROOT/'custom_components/doems').glob('*.py')):
    if path.stem != '__init__':
        importlib.import_module(f'custom_components.doems.{path.stem}')
print('All DOEMS modules imported; no HA instance setup or services invoked')

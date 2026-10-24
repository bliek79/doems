"""Validate version identity and build a deterministic HACS integration asset."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def validate(root=ROOT, tag=None):
    integration = root / 'custom_components/doems'
    manifest = json.loads((integration / 'manifest.json').read_text())
    version = manifest['version']
    assert re.fullmatch(r'\d+\.\d+\.\d+(?:-alpha\.\d+(?:\.\d+)*)?', version), 'Invalid version'
    assignments = [n for n in ast.parse((integration / 'const.py').read_text()).body
                   if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in n.targets)]
    assert len(assignments) == 1 and ast.literal_eval(assignments[0].value) == version, 'Version identity mismatch'
    assert manifest['domain'] == 'doems' and manifest['config_flow'] is True
    if tag is not None:
        assert tag == f'v{version}', 'Release tag mismatch'
    for path in integration.rglob('*.json'):
        json.loads(path.read_text())
    hacs = json.loads((root / 'hacs.json').read_text())
    assert hacs['zip_release'] is True and hacs['filename'] == 'doems.zip'
    assert hacs['hide_default_branch'] is True
    notes = root / f'RELEASE_NOTES_{version}.md'
    assert notes.is_file() and f'DOEMS {version}' in notes.read_text(), 'Release notes missing'
    return version

def files(root=ROOT):
    base = root / 'custom_components/doems'
    return {p.relative_to(base).as_posix(): p for p in base.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')}

def verify_archive(archive, root=ROOT):
    expected = files(root)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert len(names) == len(set(names)), 'Duplicate archive entries'
        assert set(names) == set(expected), 'Archive contents differ from integration'
        assert 'manifest.json' in names and '__init__.py' in names, 'HACS archive must have integration at root'
        for name, path in expected.items():
            assert z.read(name) == path.read_bytes(), f'Archive mismatch: {name}'

def build(output, root=ROOT):
    version = validate(root)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'doems.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, path in sorted(files(root).items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, path.read_bytes())
    verify_archive(archive, root)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{digest}  doems.zip\n')
    print(f'{version} {digest}')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--tag')
    p.add_argument('--build', type=Path)
    p.add_argument('--verify-archive', type=Path)
    args = p.parse_args()
    print(validate(tag=args.tag))
    if args.build:
        build(args.build)
    if args.verify_archive:
        verify_archive(args.verify_archive)

"""Reject release identity drift and stale or incomplete HACS artifacts."""
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_contract_test', ROOT/'scripts/release_contract.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)

@pytest.fixture
def release(tmp_path):
    shutil.copytree(ROOT/'custom_components/doems', tmp_path/'custom_components/doems', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy(ROOT/'hacs.json', tmp_path/'hacs.json')
    version = json.loads((ROOT/'custom_components/doems/manifest.json').read_text())['version']
    shutil.copy(ROOT/f'RELEASE_NOTES_{version}.md', tmp_path/f'RELEASE_NOTES_{version}.md')
    return tmp_path


def test_version_drift_is_rejected(release):
    path=release/'custom_components/doems/manifest.json'
    value=json.loads(path.read_text()); value['version']='0.2.0-alpha.999'
    path.write_text(json.dumps(value))
    with pytest.raises(AssertionError,match='identity'): contract.validate(release)


def test_wrong_release_tag_is_rejected(release):
    with pytest.raises(AssertionError,match='tag'): contract.validate(release,'v0.2.0-alpha.9.4')


def test_hacs_archive_is_deterministic_and_complete(release):
    contract.build(release/'dist',release)
    first=(release/'dist/doems.zip').read_bytes()
    contract.build(release/'dist',release)
    assert first == (release/'dist/doems.zip').read_bytes()
    contract.verify_archive(release/'dist/doems.zip',release)


def test_stale_archive_is_rejected(release):
    contract.build(release/'dist',release)
    path=release/'custom_components/doems/const.py'
    path.write_text(path.read_text()+'\n# changed after testing\n')
    with pytest.raises(AssertionError,match='Archive mismatch'): contract.verify_archive(release/'dist/doems.zip',release)


def test_unexpected_archive_file_is_rejected(release):
    contract.build(release/'dist',release)
    with zipfile.ZipFile(release/'dist/doems.zip','a') as z: z.writestr('unreviewed.py','')
    with pytest.raises(AssertionError,match='contents differ'): contract.verify_archive(release/'dist/doems.zip',release)

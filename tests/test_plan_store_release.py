"""Release approval, protected source and tag lookup failure boundaries."""
import importlib
from pathlib import Path
import shutil
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def validator(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    return importlib.import_module('validate_plan_store_release')


def test_approved_release_contract_and_register_are_exact(validator):
    result = validator.validate()
    assert result['version'] == '0.3.0-alpha.7.3'
    assert result['entity_register_approved'] is True
    assert result['slot_entity_count'] + result['diagnostic_entity_count'] == 30


def test_release_rejects_changed_approved_entity_implementation(validator, tmp_path, monkeypatch):
    paths = set(validator.PRESERVED_BLOBS) | {
        'custom_components/doems/manifest.json', 'custom_components/doems/const.py',
        'docs/DOEMS3_CHAPTER7_PLAN_STORE.md', 'RELEASE_NOTES_v0.3.0-alpha.7.3.md'}
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    monkeypatch.setattr(validator, 'ROOT', tmp_path)
    with (tmp_path / 'custom_components/doems/plan_slot_entities.py').open('a') as stream:
        stream.write('\n# unreviewed change\n')
    with pytest.raises(AssertionError, match='reviewed source changed'):
        validator.validate()


@pytest.mark.parametrize('status', [200, 403, 500])
def test_existing_tags_and_failed_lookups_block_publication(validator, monkeypatch, status):
    publisher = importlib.import_module('publish_plan_store_release')
    class Existing:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def request(*args, **kwargs):
        if status == 200: return Existing()
        raise urllib.error.HTTPError('https://api.github.com', status, 'blocked', {}, None)
    monkeypatch.setattr(publisher.urllib.request, 'urlopen', request)
    with pytest.raises(RuntimeError):
        publisher.require_absent('bliek79/doems', 'git/ref/tags/existing', 'test-token')

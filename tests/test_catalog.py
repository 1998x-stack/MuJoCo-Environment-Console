import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest


def test_default_registry():
    from app.catalog import discover
    entries = discover()
    gym = [x for x in entries if x['id'].startswith('gym:')]
    assert len(gym) == 11
    assert len({x['id'] for x in entries}) == len(entries)
    assert any(x['id'] == 'custom:custom_pendulum' for x in entries)
    assert len([x for x in entries if x['id'].startswith('fetch:')]) == 4


def test_reject_path_traversal(tmp_path, monkeypatch):
    import app.catalog as catalog
    monkeypatch.setattr(catalog, 'ENV_ROOT', tmp_path)
    (tmp_path / 'sample').mkdir()
    (tmp_path / 'sample' / 'manifest.json').write_text(json.dumps({'kind':'mjcf','xml':'../outside.xml'}))
    (tmp_path / 'outside.xml').write_text('<mujoco/>')
    assert not any(x['id'] == 'custom:sample' for x in catalog.discover())


def test_manifest_source_xml_parse():
    file = Path(__file__).parents[1] / 'envs/custom_pendulum/model.xml'
    root = ET.parse(file).getroot()
    assert root.tag == 'mujoco'
    assert root.find('actuator/motor') is not None


def test_fingerprint_changes_on_xml(tmp_path):
    from app.jobs import fingerprint
    xml = tmp_path / 'x.xml'
    xml.write_text('<mujoco/>')
    descr = {'id':'custom:x','kind':'mjcf','xml_path':str(xml),'params':{}}
    a = fingerprint(descr)
    xml.write_text('<mujoco model="changed"/>')
    assert fingerprint(descr) != a


def test_missing_dotted_registration_module_is_unavailable(monkeypatch):
    import app.catalog as catalog

    def fake_find_spec(name):
        if name == 'gymnasium':
            return object()
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(catalog.importlib.util, 'find_spec', fake_find_spec)
    entry = catalog._entry(
        'custom:missing', 'Missing plugin', 'Custom', 'External Gymnasium',
        'Missing-v0', 'missing.parent',
    )
    assert entry['installed'] is False

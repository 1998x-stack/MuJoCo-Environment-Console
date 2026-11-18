import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

REPO = Path(__file__).parents[1]


def test_default_registry():
    from app.catalog import discover
    entries = discover()
    gym = [x for x in entries if x['id'].startswith('gym:')]
    assert len(gym) >= 11
    assert len({x['id'] for x in entries}) == len(entries)
    assert any(x['id'] == 'custom:custom_pendulum' for x in entries)
    assert len([x for x in entries if x['id'].startswith('fetch:')]) >= 4


def test_custom_examples_are_discovered_with_expected_flags():
    """The shipped MJCF examples must exercise both the trainable and view-only paths."""
    import app.catalog as catalog
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(catalog, 'ENV_ROOT', REPO / 'envs')
    try:
        by_id = {e['id']: e for e in catalog.discover()}
    finally:
        monkeypatch.undo()

    trainable = by_id['custom:custom_double_pendulum']
    assert trainable['kind'] == 'mjcf'
    assert trainable['trainable'] is True
    # the entry point only resolves when <include> and the relative mesh stay inside the folder
    root = (REPO / 'envs/custom_double_pendulum').resolve()
    xml_path = Path(trainable['xml_path']).resolve()
    assert xml_path.is_relative_to(root)
    assert (root / 'links.xml').is_file()
    assert (root / 'assets/tip.stl').is_file()
    assert '<include file="links.xml"/>' in xml_path.read_text(encoding='utf8')
    ET.parse(xml_path)
    ET.parse(root / 'links.xml')

    viewer = by_id['custom:scene_demo_viewer']
    assert viewer['kind'] == 'mjcf'
    assert viewer['trainable'] is False
    assert viewer['params']['view_only'] is True
    assert viewer['category'] == 'Custom Scene'


def test_shipped_manifests_match_schema():
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads((REPO / 'schemas/environment.schema.json').read_text(encoding='utf8'))
    manifests = sorted((REPO / 'envs').glob('*/manifest.json'))
    assert manifests, 'expected at least one shipped manifest'
    for manifest in manifests:
        install = json.loads(manifest.read_text(encoding='utf8'))
        jsonschema.validate(install, schema)


def test_view_only_scene_has_no_actuators():
    """A view_only manifest must not pretend to be a trainable task."""
    manifest = json.loads(
        (REPO / 'envs/scene_demo_viewer/manifest.json').read_text(encoding='utf8'))
    assert manifest['view_only'] is True
    root = ET.parse(REPO / 'envs/scene_demo_viewer/scene.xml').getroot()
    assert root.find('worldbody/body/joint') is not None
    assert root.find('actuator') is None


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

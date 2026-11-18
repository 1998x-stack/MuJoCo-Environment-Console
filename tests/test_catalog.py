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


def _broken_env_tree(tmp_path):
    (tmp_path / 'ok_mjcf').mkdir()
    (tmp_path / 'ok_mjcf' / 'manifest.json').write_text(
        json.dumps({'kind': 'mjcf', 'name': 'OK', 'xml': 'model.xml'}))
    (tmp_path / 'ok_mjcf' / 'model.xml').write_text('<mujoco/>')

    (tmp_path / 'broken_json').mkdir()
    (tmp_path / 'broken_json' / 'manifest.json').write_text('{not json')

    (tmp_path / 'not_an_object').mkdir()
    (tmp_path / 'not_an_object' / 'manifest.json').write_text('[1, 2, 3]')

    (tmp_path / 'no_manifest').mkdir()

    (tmp_path / 'missing_xml').mkdir()
    (tmp_path / 'missing_xml' / 'manifest.json').write_text(
        json.dumps({'kind': 'mjcf', 'name': 'Missing', 'xml': 'nope.xml'}))

    (tmp_path / 'outside_xml').mkdir()
    (tmp_path / 'outside_xml' / 'manifest.json').write_text(
        json.dumps({'kind': 'mjcf', 'name': 'Outside', 'xml': '../escape.xml'}))
    (tmp_path / 'escape.xml').write_text('<mujoco/>')

    (tmp_path / 'bad_xml_field').mkdir()
    (tmp_path / 'bad_xml_field' / 'manifest.json').write_text(
        json.dumps({'kind': 'mjcf', 'name': 'Bad', 'xml': 'model.txt'}))

    (tmp_path / 'unsupported_kind').mkdir()
    (tmp_path / 'unsupported_kind' / 'manifest.json').write_text(
        json.dumps({'kind': 'dm_control', 'name': 'Unsupported'}))

    (tmp_path / 'gym_bad_module').mkdir()
    (tmp_path / 'gym_bad_module' / 'manifest.json').write_text(
        json.dumps({'kind': 'gym', 'name': 'Gym', 'gym_id': 'X-v0', 'registration_module': '1bad' }))

    (tmp_path / 'gym_bad_id').mkdir()
    (tmp_path / 'gym_bad_id' / 'manifest.json').write_text(
        json.dumps({'kind': 'gym', 'name': 'Gym', 'gym_id': ''}))

    (tmp_path / 'schema_violation').mkdir()
    (tmp_path / 'schema_violation' / 'manifest.json').write_text(
        json.dumps({'kind': 'mjcf', 'name': 'x' * 200, 'xml': 'model.xml'}))
    (tmp_path / 'schema_violation' / 'model.xml').write_text('<mujoco/>')

    bad_folder = tmp_path / 'bad name!'
    bad_folder.mkdir()
    (bad_folder / 'manifest.json').write_text(json.dumps({'kind': 'mjcf', 'name': 'Bad', 'xml': 'm.xml'}))


def test_broken_environments_are_reported_not_fatal(tmp_path, monkeypatch):
    """A broken custom environment must be diagnosable, and must not stop discovery."""
    import app.catalog as catalog
    _broken_env_tree(tmp_path)

    entries, problems = catalog.scan(tmp_path)
    ids = {e['id'] for e in entries}
    assert 'custom:ok_mjcf' in ids, 'the healthy environment must still be listed'
    assert not any(i.startswith('custom:broken') or i.endswith('missing_xml') for i in ids)

    reasons = {p['id']: p['reason'] for p in problems}
    assert reasons['custom:broken_json'] == 'invalid_manifest_json'
    assert reasons['custom:not_an_object'] == 'manifest_not_an_object'
    assert reasons['custom:no_manifest'] == 'missing_manifest'
    assert reasons['custom:missing_xml'] == 'xml_missing'
    assert reasons['custom:outside_xml'] == 'xml_outside_environment'
    assert reasons['custom:bad_xml_field'] == 'invalid_xml_field'
    assert reasons['custom:unsupported_kind'] == 'unsupported_kind'
    assert reasons['custom:gym_bad_module'] == 'invalid_registration_module'
    assert reasons['custom:gym_bad_id'] == 'invalid_gym_id'
    assert reasons['custom:bad name!'] == 'invalid_directory_name'
    assert all(p['severity'] == 'error' for p in problems if p['reason'] != 'schema_violation')
    assert all(p['detail'] for p in problems), 'every problem needs a human-readable detail'

    # discover() stays exception-free and returns the usable subset
    monkeypatch.setattr(catalog, 'ENV_ROOT', tmp_path)
    usable = catalog.discover()
    assert any(e['id'] == 'custom:ok_mjcf' for e in usable)
    assert not any(e['id'] == 'custom:broken_json' for e in usable)


def test_schema_violations_are_warnings_not_rejections(tmp_path):
    """Schema problems are reported, but a merely out-of-range manifest stays usable."""
    import app.catalog as catalog
    if catalog._validator() is None:
        pytest.skip('jsonschema not installed')
    _broken_env_tree(tmp_path)
    entries, problems = catalog.scan(tmp_path)
    violations = [p for p in problems if p['reason'] == 'schema_violation']
    assert any(p['id'] == 'custom:schema_violation' for p in violations)
    assert all(p['severity'] == 'warning' for p in violations)
    assert 'custom:schema_violation' in {e['id'] for e in entries}, 'warnings must not hide the environment'


def test_scan_survives_a_missing_env_root(tmp_path):
    import app.catalog as catalog
    entries, problems = catalog.scan(tmp_path / 'does-not-exist')
    assert len(entries) >= 15 and problems == []


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

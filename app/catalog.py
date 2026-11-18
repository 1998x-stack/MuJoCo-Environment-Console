"""Local, allowlisted environment registry. No arbitrary remote code execution.

Discovery is deliberately fault-tolerant: a broken environment directory must never stop the
console from starting. Instead of silently dropping bad folders, ``scan()`` returns
``(entries, problems)`` where every skipped or degraded environment carries a machine-readable
``reason`` and a human-readable ``detail`` that the API and the UI surface to the operator.
"""
from __future__ import annotations
import importlib.util
import json
import os
import re
from pathlib import Path

ENV_ROOT = Path(os.getenv('CONSOLE_ENV_ROOT', './envs')).resolve()
SCHEMA_PATH = Path(__file__).resolve().parent.parent / 'schemas/environment.schema.json'
SAFE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
MODULE = re.compile(r'[A-Za-z_][\w.]*(?<!\.)')

NAMES = [
    ('InvertedPendulum', '倒立摆', 'Control'),
    ('InvertedDoublePendulum', '双倒立摆', 'Control'),
    ('Reacher', '平面机械臂', 'Manipulation'),
    ('Pusher', '推物体机械臂', 'Manipulation'),
    ('HalfCheetah', '半猎豹', 'Locomotion'),
    ('Hopper', '单足跳跃', 'Locomotion'),
    ('Walker2d', '双足行走', 'Locomotion'),
    ('Swimmer', '游泳机器人', 'Locomotion'),
    ('Ant', '四足蚂蚁', 'Locomotion'),
    ('Humanoid', '人形机器人', 'Humanoid'),
    ('HumanoidStandup', '人形起立', 'Humanoid'),
]
FETCH = [
    ('FetchReach-v4', '机械臂到达目标'),
    ('FetchPush-v4', '机械臂推动方块'),
    ('FetchSlide-v4', '机械臂滑动物体'),
    ('FetchPickAndPlace-v4', '机械臂抓取放置'),
]

_schema_validator = None
_schema_loaded = False


def _validator():
    """Schema validator, or None when the optional ``jsonschema`` package is unavailable."""
    global _schema_validator, _schema_loaded
    if not _schema_loaded:
        _schema_loaded = True
        try:
            import jsonschema
            schema = json.loads(SCHEMA_PATH.read_text(encoding='utf8'))
            _schema_validator = jsonschema.Draft202012Validator(schema)
        except (ImportError, OSError, ValueError, TypeError):
            _schema_validator = None
    return _schema_validator


def _module_available(name):
    if not name:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _entry(key, name, category, library, gym_id=None, module=None, **other):
    if gym_id:
        installed = _module_available('gymnasium') and _module_available(module)
    else:
        installed = _module_available('gymnasium') and _module_available('mujoco')
    return {'id': key, 'name': name, 'category': category, 'library': library,
            'kind': 'gym' if gym_id else 'mjcf', 'gym_id': gym_id,
            'registration_module': module, 'installed': installed, **other}


def _problem(env_id, reason, detail, severity='error'):
    return {'id': env_id, 'reason': reason, 'detail': detail, 'severity': severity}


def _read_manifest(folder, env_id, problems):
    """Return (config, fatal). Records a problem and returns fatal=True when unusable."""
    manifest = folder / 'manifest.json'
    if manifest.is_symlink():
        problems.append(_problem(env_id, 'manifest_is_symlink',
                                 'manifest.json must be a regular file inside the environment'))
        return None, True
    if not manifest.is_file():
        problems.append(_problem(env_id, 'missing_manifest',
                                 'no manifest.json in this directory; add one to register it'))
        return None, True
    try:
        config = json.loads(manifest.read_text(encoding='utf8'))
    except (OSError, ValueError) as exc:
        problems.append(_problem(env_id, 'invalid_manifest_json', f'{type(exc).__name__}: {exc}'))
        return None, True
    if not isinstance(config, dict):
        problems.append(_problem(env_id, 'manifest_not_an_object',
                                 f'manifest.json must contain a JSON object, got {type(config).__name__}'))
        return None, True
    return config, False


def _schema_warnings(config, env_id, problems):
    validator = _validator()
    if validator is None:
        return
    for error in sorted(validator.iter_errors(config), key=lambda e: list(e.path)):
        location = '/'.join(str(part) for part in error.path) or '<root>'
        problems.append(_problem(env_id, 'schema_violation',
                                 f'{location}: {error.message}', severity='warning'))


def _scan_mjcf(folder, env_id, config, problems):
    xml = config.get('xml', 'model.xml')
    if not isinstance(xml, str) or not xml.endswith('.xml'):
        problems.append(_problem(env_id, 'invalid_xml_field',
                                 f'"xml" must be a string ending in .xml, got {xml!r}'))
        return None
    path = (folder / xml).resolve()
    if not path.is_relative_to(folder.resolve()):
        problems.append(_problem(env_id, 'xml_outside_environment',
                                 f'"{xml}" resolves outside {folder.name}; keep assets inside the folder'))
        return None
    if not path.is_file():
        problems.append(_problem(env_id, 'xml_missing',
                                 f'"{xml}" does not exist (looked for {path.name} inside {folder.name})'))
        return None
    return _entry(env_id, str(config.get('name', folder.name))[:80],
                  str(config.get('category', 'Custom'))[:40], 'Local MJCF',
                  xml_path=str(path), params=config,
                  trainable=not bool(config.get('view_only', False)))


def _scan_gym(folder, env_id, config, problems):
    gym_id = config.get('gym_id')
    module = config.get('registration_module')
    if not isinstance(gym_id, str) or not gym_id or len(gym_id) > 128:
        problems.append(_problem(env_id, 'invalid_gym_id',
                                 f'"gym_id" must be a non-empty string of at most 128 chars, got {gym_id!r}'))
        return None
    if module is not None and (not isinstance(module, str) or not MODULE.fullmatch(module)):
        problems.append(_problem(env_id, 'invalid_registration_module',
                                 f'"registration_module" must be a python module name, got {module!r}'))
        return None
    return _entry(env_id, str(config.get('name', folder.name))[:80],
                  str(config.get('category', 'Custom'))[:40], 'External Gymnasium',
                  gym_id, module)


def scan(env_root=None):
    """Discover environments. Returns ``(entries, problems)`` and never raises."""
    root = Path(env_root).resolve() if env_root is not None else ENV_ROOT
    entries = [_entry(f'gym:{name}-v5', name_cn, cat, 'Gymnasium MuJoCo', f'{name}-v5')
               for name, name_cn, cat in NAMES]
    entries += [_entry(f'fetch:{gym_id}', name_cn, 'Fetch Robotics', 'Gymnasium Robotics',
                       gym_id, 'gymnasium_robotics') for gym_id, name_cn in FETCH]
    problems = []
    if not root.is_dir():
        return entries, problems

    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        env_id = f'custom:{folder.name}'
        if not SAFE.fullmatch(folder.name):
            problems.append(_problem(env_id, 'invalid_directory_name',
                                     'directory names must match [a-zA-Z0-9_-]{1,64}'))
            continue
        try:
            config, fatal = _read_manifest(folder, env_id, problems)
            if fatal:
                continue
            _schema_warnings(config, env_id, problems)
            kind = config.get('kind', 'mjcf')
            if kind == 'mjcf':
                entry = _scan_mjcf(folder, env_id, config, problems)
            elif kind == 'gym':
                entry = _scan_gym(folder, env_id, config, problems)
            else:
                problems.append(_problem(env_id, 'unsupported_kind',
                                         f'"kind" must be "mjcf" or "gym", got {kind!r}'))
                entry = None
            if entry is not None:
                entries.append(entry)
        except Exception as exc:                       # never let one folder break discovery
            problems.append(_problem(env_id, 'internal_error',
                                     f'{type(exc).__name__}: {exc}'))
            continue
    return entries, problems


def discover():
    return scan()[0]


def get_env(env_id):
    for entry in discover():
        if entry['id'] == env_id:
            if not entry['installed']:
                raise ValueError('Environment requires extra package: ' + str(entry['registration_module']))
            return entry
    raise ValueError('Unknown environment ID')

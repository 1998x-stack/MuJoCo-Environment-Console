"""Local, allowlisted environment registry. No arbitrary remote code execution."""
from __future__ import annotations
import importlib.util
import json
import os
import re
from pathlib import Path

ENV_ROOT = Path(os.getenv('CONSOLE_ENV_ROOT', './envs')).resolve()
SAFE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

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

def _entry(key, name, category, library, gym_id=None, module=None, **other):
    installed = module is None or importlib.util.find_spec(module) is not None
    return {'id': key, 'name': name, 'category': category, 'library': library,
            'kind': 'gym' if gym_id else 'mjcf', 'gym_id': gym_id,
            'registration_module': module, 'installed': installed, **other}


def discover():
    entries = [_entry(f'gym:{name}-v5', name_cn, cat, 'Gymnasium MuJoCo', f'{name}-v5')
               for name, name_cn, cat in NAMES]
    entries += [_entry(f'fetch:{gym_id}', name_cn, 'Fetch Robotics', 'Gymnasium Robotics',
                       gym_id, 'gymnasium_robotics') for gym_id, name_cn in FETCH]
    if ENV_ROOT.is_dir():
        for folder in sorted(ENV_ROOT.iterdir()):
            if not folder.is_dir() or not SAFE.fullmatch(folder.name):
                continue
            manifest = folder / 'manifest.json'
            if not manifest.is_file() or manifest.is_symlink():
                continue
            try:
                config = json.loads(manifest.read_text(encoding='utf8'))
                if not isinstance(config, dict):
                    continue
                kind = config.get('kind', 'mjcf')
                if kind == 'mjcf':
                    xml = config.get('xml', 'model.xml')
                    if not isinstance(xml, str) or not xml.endswith('.xml'):
                        continue
                    path = (folder / xml).resolve()
                    if not path.is_relative_to(folder.resolve()) or not path.is_file():
                        continue
                    entry = _entry(f'custom:{folder.name}', str(config.get('name', folder.name))[:80],
                                   str(config.get('category', 'Custom'))[:40], 'Local MJCF',
                                   xml_path=str(path), params=config, trainable=not bool(config.get('view_only', False)))
                elif kind == 'gym':
                    gym_id = config.get('gym_id')
                    module = config.get('registration_module')
                    if not isinstance(gym_id, str) or not gym_id or len(gym_id) > 128:
                        continue
                    if module is not None and (not isinstance(module, str) or
                            not re.fullmatch(r'[A-Za-z_][\w.]*(?<!\.)', module)):
                        continue
                    entry = _entry(f'custom:{folder.name}', str(config.get('name', folder.name))[:80],
                                   str(config.get('category', 'Custom'))[:40], 'External Gymnasium',
                                   gym_id, module)
                else:
                    continue
                entries.append(entry)
            except (OSError, ValueError, TypeError):
                continue
    return entries


def get_env(env_id):
    for entry in discover():
        if entry['id'] == env_id:
            if not entry['installed']:
                raise ValueError('Environment requires extra package: ' + str(entry['registration_module']))
            return entry
    raise ValueError('Unknown environment ID')

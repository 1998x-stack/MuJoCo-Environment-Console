"""Run *inside the deployed container*: python scripts/smoke_test.py [--render]"""
import argparse
import json
import sys
import traceback
from app.catalog import discover
from app.env_factory import make_environment

parser = argparse.ArgumentParser()
parser.add_argument('--render', action='store_true')
parser.add_argument('--all', action='store_true', help='include optional and imported environments')
args = parser.parse_args()
report = []
for desc in discover():
    if not desc['installed'] or (not args.all and not desc['id'].startswith('gym:') and desc['id'] != 'custom:custom_pendulum'):
        continue
    env = None
    try:
        env = make_environment(desc, render=args.render)
        obs, info = env.reset(seed=42)
        for _ in range(2):
            obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
            if terminated or truncated:
                obs, info = env.reset()
        if args.render:
            frame = env.render()
            assert frame is not None and len(frame.shape) == 3
        report.append({'id': desc['id'], 'ok': True})
    except Exception as e:
        report.append({'id': desc['id'], 'ok': False, 'error': str(e)})
        traceback.print_exc()
    finally:
        if env is not None:
            env.close()
print(json.dumps(report, indent=2, ensure_ascii=False))
print(f"{sum(1 for r in report if r['ok'])}/{len(report)} environments passed")
sys.exit(0 if report and all(r['ok'] for r in report) else 1)

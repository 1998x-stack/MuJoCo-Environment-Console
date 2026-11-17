from __future__ import annotations
import importlib

def make_environment(descriptor, render=False, width=640, height=480):
    if descriptor['kind'] == 'gym':
        import gymnasium as gym
        if descriptor.get('registration_module'):
            mod = importlib.import_module(descriptor['registration_module'])
            gym.register_envs(mod)
        kw = {'render_mode': 'rgb_array', 'width': width, 'height': height} if render else {}
        return gym.make(descriptor['gym_id'], **kw)
    if descriptor['kind'] == 'mjcf':
        from app.custom_env import MJCFTrackingEnv
        return MJCFTrackingEnv(descriptor['xml_path'], descriptor['params'],
                               render_mode='rgb_array' if render else None,
                               width=width, height=height)
    raise ValueError('Unsupported environment adapter')

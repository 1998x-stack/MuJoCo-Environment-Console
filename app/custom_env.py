"""Minimal generic MJCF goal tracking task.

For research-grade tasks replace this generic reward with a task-specific Env.
"""
from __future__ import annotations
import numpy as np
import gymnasium as gym
from gymnasium import spaces
import mujoco

class MJCFTrackingEnv(gym.Env):
    metadata = {'render_modes': ['rgb_array'], 'render_fps': 25}

    def __init__(self, xml_path, params, render_mode=None, width=640, height=480):
        super().__init__()
        self.model = mujoco.MjModel.from_xml_path(xml_path)
        self.data = mujoco.MjData(self.model)
        self.view_only = bool(params.get('view_only', False))
        if self.model.nu < 1 and not self.view_only:
            raise ValueError('MJCF without actuators must set view_only=true')
        self.target = np.asarray(params.get('target_qpos', self.model.qpos0.tolist()), dtype=np.float64)
        if self.target.shape != (self.model.nq,):
            raise ValueError(f'target_qpos must contain {self.model.nq} elements')
        self.init_qpos = np.asarray(params.get('init_qpos', self.model.qpos0.tolist()), dtype=np.float64)
        if self.init_qpos.shape != (self.model.nq,):
            raise ValueError(f'init_qpos must contain {self.model.nq} elements')
        self.frame_skip = int(params.get('frame_skip', 5))
        self.limit = int(params.get('max_episode_steps', 400))
        if not 1 <= self.frame_skip <= 100 or not 1 <= self.limit <= 100000:
            raise ValueError('frame_skip or max_episode_steps out of range')
        self.render_mode = render_mode
        self.width, self.height = int(width), int(height)
        self.camera = params.get('camera', -1)
        self.renderer = None
        self.count = 0
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(self.model.nq + self.model.nv,), dtype=np.float32)
        self.action_space = spaces.Box(-1., 1., shape=(max(1, self.model.nu),), dtype=np.float32)

    def _obs(self):
        return np.concatenate((self.data.qpos, self.data.qvel)).astype(np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[:] = self.init_qpos
        mujoco.mj_forward(self.model, self.data)
        self.count = 0
        return self._obs(), {}

    def step(self, action):
        action = np.asarray(action, dtype=np.float64).reshape(self.action_space.shape)
        action = np.clip(action, -1., 1.)
        ctrlrange = self.model.actuator_ctrlrange
        limited = self.model.actuator_ctrllimited
        control = action.copy()
        for i in range(self.model.nu):
            if limited[i]:
                lo, hi = ctrlrange[i]
                control[i] = lo + 0.5 * (action[i] + 1.) * (hi - lo)
        if self.model.nu:
            self.data.ctrl[:] = control[:self.model.nu]
        for _ in range(self.frame_skip):
            mujoco.mj_step(self.model, self.data)
        self.count += 1
        err = self.data.qpos - self.target
        cost = float(np.dot(err, err) + 0.01 * np.dot(action, action))
        reward = float(1.0 - cost)
        terminated = not bool(np.isfinite(self._obs()).all())
        truncated = self.count >= self.limit
        return self._obs(), reward, terminated, truncated, {'tracking_cost': cost}

    def render(self):
        if self.render_mode != 'rgb_array':
            return None
        if self.renderer is None:
            self.renderer = mujoco.Renderer(self.model, height=self.height, width=self.width)
        self.renderer.update_scene(self.data, camera=self.camera)
        return self.renderer.render().copy()

    def close(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None

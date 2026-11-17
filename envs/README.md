# 自定义环境接入说明

环境目录内每个子目录包含 `manifest.json`。控制台每次刷新会重新扫描，无需重启服务。

## 方式 A：导入 MJCF/XML

```text
envs/my_robot/
  manifest.json
  scene.xml
  assets/robot.stl
```

示例：

```json
{
  "kind": "mjcf",
  "name": "我的机械臂",
  "category": "Custom",
  "xml": "scene.xml",
  "target_qpos": [0.0],
  "frame_skip": 5,
  "max_episode_steps": 400
}
```

注意：`target_qpos` 的长度必须等于模型的 `nq`，不能简单按电机数量填写。缺省取模型 `qpos0`。`init_qpos` 也必须有 `nq` 个元素，缺省取模型 `qpos0`。单纯的姿态跟踪奖励不适合所有机器人；接触控制和复杂任务应自行编写 Gymnasium Env。没有执行器的模型需要 `"view_only": true`，只允许查看，不允许训练。

使用 `<include file="..."/>` 或网格时，把所有依赖放在该目录，保持相对路径完整。

## 方式 B：挂载 Gymnasium 环境注册代码

```text
envs/my_task/
  manifest.json
  __init__.py
  my_environment.py
```

`__init__.py` 调用 `gymnasium.register(id="MyRobot-v0", entry_point="my_task.my_environment:MyRobotEnv")`。

`manifest.json`：

```json
{
  "kind": "gym",
  "name": "自定义控制任务",
  "category": "Custom",
  "gym_id": "MyRobot-v0",
  "registration_module": "my_task"
}
```

Docker `PYTHONPATH` 包含 `/app/envs`，所以该包在新仿真或训练进程中能导入。模块必须返回标准 Gymnasium `reset()/step()` API；渲染时应接受 `render_mode="rgb_array", width=..., height=...` 参数。带有观测字典的任务使用 SB3 `MultiInputPolicy`。动作空间应是有界 `Box`，适配 PPO/SAC。

**安全提示**：Python 注册模块可以执行任意本地代码，只从可信来源导入，避免在浏览器中允许任意用户上传 Python 包。

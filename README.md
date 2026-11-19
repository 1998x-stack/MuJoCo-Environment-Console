# MuJoCo Environment Console

面向 Ubuntu 服务器的自托管 MuJoCo 仿真与强化学习控制台。通过浏览器管理环境、查看实时仿真、运行 PPO/SAC 训练，并回放训练完成的策略模型。

## 快速部署

要求：Ubuntu 22.04/24.04、Docker Engine、Docker Compose v2，以及可访问软件包仓库和 PyTorch CPU wheel 源的网络。

```bash
git clone https://github.com/1998x-stack/MuJoCo-Environment-Console.git
cd MuJoCo-Environment-Console
bash scripts/deploy.sh
```

部署脚本会：
1. 检查 Docker 与 Compose。
2. 首次生成随机控制台密码，并保存到权限为 `600` 的 `.env`。
3. 根据当前用户 UID/GID 创建数据目录权限配置。
4. 构建 CPU 版 PyTorch、MuJoCo 与控制台镜像。
5. 等待容器健康检查通过，再输出访问地址。

在同一可信局域网浏览器打开：

`http://<Ubuntu-LAN-IP>:8000`

登录密码位于服务器项目目录的 `.env` 中。不要把密码提交到 Git。

## 功能范围

- **Gymnasium MuJoCo v5**：11 个标准控制、运动、机械臂和人形任务。
- **Gymnasium Robotics Fetch**：4 个 Fetch 机械臂任务；默认安装，可在 `.env` 设置 `INSTALL_ROBOTICS=0` 跳过。
- **自定义 MJCF/XML**：扫描 `envs/<name>/manifest.json`，支持相对路径资源、网格和纹理。仓库自带 `custom_pendulum`、`custom_double_pendulum`（`<include>` + 网格）与 `scene_demo_viewer`（`view_only` 仅演示）三个示例，可直接复制为模板。
- **仿真**：独立进程运行环境，服务器端 OSMesa 离屏渲染，通过 MJPEG 向浏览器传输。MJPEG 分片按 RFC 2046 使用 CRLF 分隔，除浏览器外也可被 ffmpeg/OpenCV 等标准客户端解析（已用 ffmpeg 实测：实时流 60 帧、640×480）。
- **按需渲染**：只在有浏览器连接时才渲染。无人观看的会话 CPU 从约 5 核降到约 0.015 核，仍保持物理步进与状态上报；每个 viewer 的光栅化/BLAS 线程数受控，避免默认线程池按核数空转。
- **强化学习**：PPO、SAC；训练日志、进度、评估结果、模型保存和策略回放。PPO 使用完整 rollout batch，实际步数可能向上取整（例如请求 1,000 步时默认 rollout 可能执行 2,048 步）；界面同时展示请求步数与实际完成步数。
- **资源保护**：限制并发查看器、单训练任务、空闲会话回收、按需渲染与 viewer 线程预算，以及服务退出时的 worker 清理。实测 3 个并发查看器从约 860% CPU 降到约 549%，线程数从 142 降到 42。
- **交互工作台 UI/UX Pro Max**：环境目录可筛选且显示匹配数量；训练步数可用快捷预设并实时验证；会话状态显示订阅者数量、渲染请求、目标帧率和渲染分辨率（注意目标 FPS 并非实测 FPS）；训练列表在数据未变时不重新渲染，减少键盘焦点丢失。[设计规范与验收](docs/UI_UX_PRO_MAX_DESIGN.md)。
- **会话可观测**：`GET /api/sessions` 只读列出存活 viewer 会话（订阅数、渲染开关、存活状态、空闲秒数），
  不刷新空闲计时；用于排查被遗弃会话占用查看器槽位。`GET /api/catalog` 除环境与问题列表外，
  还报告 manifest Schema 校验是否真的生效（`schema.available`）。

当前固定 MuJoCo 3.3.7 与 Gymnasium Robotics 1.4.2；不要单独升级 MuJoCo 大版本，升级前必须通过全部 Fetch 环境、渲染和训练 CI。

这是一个 CPU-first 的 MVP。通用 MJCF 适配器提供基础姿态跟踪奖励，并不等于适用于所有机器人任务的研究级奖励函数。复杂接触控制、操作任务和真实机器人部署需要专门设计观测、动作、奖励、安全约束与评估协议。

## 配置

部署前可编辑 `.env`；第一次运行会从 `.env.example` 自动生成。

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `MUJOCO_CONSOLE_PASSWORD` | 自动生成 | 控制台访问密码 |
| `CONSOLE_PORT` | `8000` | 宿主机监听端口 |
| `MAX_VIEWERS` | `3` | 最大并发仿真查看器 |
| `INSTALL_ROBOTICS` | `1` | 是否安装 Fetch Robotics 依赖 |
| `SESSION_IDLE_SECONDS` | `900` | 无活动会话自动回收时间 |
| `VIEWER_FPS` | `12` | 每 viewer 帧率 |
| `VIEWER_WIDTH` / `VIEWER_HEIGHT` | `640` / `480` | 服务端渲染分辨率 |
| `VIEWER_RENDER_THREADS` | `2` | 每个 viewer 的光栅化线程数（详见运维手册 6.1） |
| `VIEWER_BLAS_THREADS` | `1` | 每个 viewer 进程的 BLAS/OpenMP 线程数 |
| `CONSOLE_CPU_LIMIT` / `CONSOLE_MEM_LIMIT` | 不设 | 可选的容器 CPU / 内存上限 |
| `LOGIN_MAX_ATTEMPTS` | `8` | 单 IP 登录失败次数上限 |
| `LOGIN_WINDOW_SECONDS` | `300` | 登录失败统计窗口 |
| `COOKIE_SECURE` | `0` | HTTPS 反向代理场景设为 `1` |

如通过 HTTPS 反向代理访问，请将 `COOKIE_SECURE=1`，并确保反向代理正确配置 TLS。控制台默认按可信局域网 HTTP 部署，不要直接暴露到公网。远程访问优先使用 VPN；不要仅依赖访问密码替代 HTTPS。

## 常用运维命令

```bash
# 查看容器状态和日志
docker compose ps
docker compose logs -f console

# 检查全部已安装环境的物理步进和离屏渲染
docker compose exec -T console python scripts/smoke_test.py --render --all

# 运行短 PPO/SAC 训练、模型保存、加载和策略回放检查
docker compose exec -T console python scripts/training_smoke_test.py

# 更新代码后重建
git pull
docker compose up -d --build

# 停止服务
docker compose down
```

训练数据和模型保存在宿主机 `data/runs/`，容器重建不会删除这些数据。备份该目录即可保留训练记录与模型。

## 添加自定义环境

### MJCF/XML 环境

目录结构：

```text
envs/my_robot/
├── manifest.json
├── scene.xml
└── assets/
    └── robot.stl
```

示例：

```json
{
  "kind": "mjcf",
  "name": "我的机器人",
  "category": "Custom",
  "xml": "scene.xml",
  "target_qpos": [0.0],
  "frame_skip": 5,
  "max_episode_steps": 400
}
```

`target_qpos` 和 `init_qpos` 的长度必须等于模型的 `nq`。没有执行器的场景需设置 `"view_only": true`，只能演示，不能训练。请把 include、mesh、texture 等依赖放在该环境目录内，保持相对路径完整。

manifest 不合法时不会阻止服务启动：控制台会在 `/api/catalog` 的 `problems` 中列出该目录及原因（缺少 `manifest.json`、JSON 非法、XML 缺失、资源路径逃逸目录、`kind` 不支持等），界面也会显示提示。

### Gymnasium 插件

可在环境子目录中提供 Python 注册模块，并在 manifest 中指定 `gym_id` 与 `registration_module`。注册模块会在仿真或训练进程中导入，因此只应加载可信代码。浏览器端不提供任意 Python 上传功能。

### MuJoCo Menagerie

可选执行：

```bash
bash scripts/import_menagerie.sh
```

脚本会导入 Unitree Go2、Unitree G1 和 Franka Panda 场景，并将其标记为只演示环境。Menagerie 模型资源本身不包含经过验证的 RL 任务定义；使用前请遵守各模型目录中的许可证。

## 架构与边界

- FastAPI 提供认证、环境目录、仿真会话、训练任务和日志 API。
- 每个 viewer 使用独立 OS 进程与 OpenGL context，避免渲染状态互相污染。
- 每个训练任务使用独立进程组；取消任务和服务退出时会终止对应进程组。
- 训练模型绑定环境指纹；MJCF 入口 XML 与目录内依赖资源变化后，旧模型不能直接回放。
- 当前不包含 dm_control、robosuite、MuJoCo Playground 的原生适配器，也不提供 GPU 分布式训练或多用户租户隔离。

## 验证

GitHub Actions 执行 Python 单元测试、JavaScript/Shell 语法检查、Manifest Schema 校验，以及 Docker 镜像构建和容器内物理仿真/渲染/训练 smoke tests。真实目标服务器仍需验证其 CPU、内存、驱动、端口和局域网访问条件。

CI 的结果不是靠管道后的 `tee` 状态或 `"passed"` 字符串判定的：严格 step 在 `set -euo pipefail` 下
运行，把 JUnit XML 交给 `scripts/check_pytest_report.py`，任何 failed / error / skipped、或必测的
物理集成测试没真的执行，都会使 job 失败（故意失败 / 故意 skip / 收集失败 / 超时的场景已逐个自检）。
CI 还会**在镜像内不挂载仓库**地校验镜像自带内容（`schemas/` 与 `envs/`），因为挂载时
`import app` 指向仓库副本，验不到镜像本身。当前严格套件为 **93 passed, 0 skipped**。

本地验证参见 `docs/verification/`（部署与分层验证、viewer 资源优化、并发与 CI 门禁），
交接记录见 `docs/handoff/latest.md`。

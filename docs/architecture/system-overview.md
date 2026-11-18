# 系统架构总览

> 面向接手本仓库的 Agent 与工程师。若与代码冲突，以 `app/` 下源码为准，并更新本文件。

## 1. 组件视图

```text
浏览器 (静态前端, 无构建步骤)
  │ HTTP (Cookie: mujoco_session)
  ▼
FastAPI app.main  ──┬── app.catalog      环境发现（白名单 + manifest 解析）
  │                 ├── app.jobs         JobManager：训练任务持久化 + 进程组管理
  │                 └── app.sessions     SessionManager：viewer 会话与资源回收
  │                          │
  │                          ├─ multiprocessing(spawn) ─► app.worker   每个 viewer 一个进程
  │                          │        └─ app.env_factory ─► gymnasium / app.custom_env
  │                          └─ subprocess(start_new_session) ─► app.trainer
  │                                   └─ stable-baselines3 (PPO / SAC)
  ▼
MJPEG (multipart/x-mixed-replace, boundary=frame)
```

关键点：**viewer 与 trainer 都不在 API 进程内运行**。API 进程只做路由与生命周期管理，
因此单个仿真/训练崩溃不会拖垮服务，代价是模型需要用队列（`multiprocessing.Queue`）回传。

## 2. 环境适配层

`app/catalog.py` 是唯一的发现入口，产出 descriptor（dict），三个来源：

| 来源 | id 形式 | kind | 说明 |
|---|---|---|---|
| 内置 Gymnasium MuJoCo v5 | `gym:<Name>-v5` | gym | 11 个标准控制/运动/人形任务 |
| Gymnasium Robotics Fetch | `fetch:<GymId>` | gym | 4 个 Fetch 任务，受 `INSTALL_ROBOTICS` 控制 |
| 本地目录 | `custom:<folder>` | mjcf / gym | 扫描 `$CONSOLE_ENV_ROOT/<folder>/manifest.json` |

安全约束（`catalog.py`）：目录名必须匹配 `^[a-zA-Z0-9_-]{1,64}$`；`manifest.json` 不得为符号链接；
MJCF 入口 XML 必须 `.xml` 结尾且 `resolve()` 后仍位于该环境目录内（阻止路径穿越）；
`registration_module` 必须匹配 Python 模块名正则。

`app/env_factory.make_environment(descriptor, render, width, height)` 统一构造环境。
`kind='gym'` 走 `gym.make(gym_id, render_mode='rgb_array', width=..., height=...)`；
`kind='mjcf'` 走 `app.custom_env.MJCFTrackingEnv`。

`MJCFTrackingEnv` 的约定：

- `target_qpos` / `init_qpos` 长度必须等于 `model.nq`，缺省取 `model.qpos0`。
- 观测 = `concat(qpos, qvel)`，形状 `nq + nv`。
- 动作空间 = `Box(-1, 1, (max(1, nu),))`；有 `ctrllimited` 时线性映射到 `ctrlrange`。
- `view_only: true` 时允许 `nu == 0`，且 `trainable=False`。
- `frame_skip` ∈ [1,100]，`max_episode_steps` ∈ [1,100000]。

奖励是**通用姿态跟踪**：`reward = 1 - (‖qpos - target‖² + 0.01‖a‖²)`。
它不是研究级任务奖励——接触丰富型操作任务必须自行实现 Gymnasium Env。

## 3. Viewer 会话生命周期

```text
POST /api/sessions          → SessionManager.start() → ViewerSession（spawn 子进程）
GET  /api/sessions/{id}     → 状态快照（state/mode/paused/steps/episodes/reward/error）
GET  /api/sessions/{id}/stream → MJPEG（长连接，服务端逐帧推送）
POST /api/sessions/{id}/{reset|pause|driver|stop}
```

- 每个子进程有 3 个队列：`commands`(maxsize 16)、`frames`(2)、`states`(32)。
  满队列策略是「丢最旧」（`worker._publish`），因此慢客户端永远不会阻塞仿真循环。
- `ViewerSession._receive` 线程把队列内容折叠成单个最新帧 + 最新状态，HTTP 层只读内存。
- 回收：`SessionManager.start_reaper()` 线程按 `min(30s, idle/3)` 轮询，超过
  `SESSION_IDLE_SECONDS` 未 `touch()` 的会话被 `close()`。
- `close()` 走 stop 命令 → `join(2s)` → `terminate` → `kill`，并关闭全部队列。
- `touch()` 在 `status()` / `wait_frame()` / `command()` 中调用，因此**正在被观看的会话不会被回收**。

## 4. MJPEG 协议细节（易踩坑）

`app.main.mjpeg_part()` 是唯一定义分片的地方：

```text
--frame\r\n
Content-Type: image/jpeg\r\n
Content-Length: <n>\r\n
\r\n
<jpeg bytes>
\r\n            ← 必须是真实 CRLF（0x0D 0x0A）
```

RFC 2046 规定分隔行是 `CRLF + "--" + boundary`。若结尾写成 `b'\\r\\n'`（Python 中等于
`5C 72 5C 6E` 四个可见字符），则整个流中**不存在任何合法分隔符**：

- Chromium/Firefox 用宽松扫描找 `--frame`，并在 JPEG `FFD9` 后忽略垃圾字节 → 仍能播放；
- ffmpeg / OpenCV / VLC / GStreamer 的 multipart demuxer 按规范查找
  `\r\n--frame` → **一帧也解析不出来**。

`scripts/smoke_test.py` 与旧版 CI 只检查 `Content-Type: image/jpeg` 字符串，无法发现该缺陷；
因此 `tests/test_api.py::test_mjpeg_part_is_rfc2046_framed` 与 `ci.yml` 中的分帧断言是必要的回归闸门。

## 5. 训练任务生命周期

```text
POST /api/training  → JobManager.start()
   校验：algorithm ∈ {PPO, SAC}；timesteps ∈ [1000, 5e6]；descriptor.installed；
        descriptor.trainable；当前没有其他活跃任务
   落盘：data/runs/<uuid>/{status.json, environment.json, output.log}
   启动：python -m app.trainer --run-dir <folder>（start_new_session=True，独立进程组）
```

- `app.trainer.ProgressUpdater` 每 ≥250 步回写 `status.json`（`completed_steps`、`average_reward`）。
- 训练结束保存 `model.zip`，再用**独立**环境跑 3 个种子（101/202/303）各最多 1000 步评估。
- `JobManager.list()` 会 `_reconcile_finished()`：进程已退出但状态仍是 active 的任务被判定为
  `failed` 并给出退出码。
- 取消 / 关停走 `terminate_process_group(pgid)`：SIGTERM → 4s → SIGKILL。
- **进程重启恢复**：`JobManager.__init__` 扫描 `*/status.json`，对仍是 active 的任务，
  先读取 `/proc/<pid>/cmdline` 并确认其中同时含 `app.trainer` 与该 run 目录，才终止进程组，
  然后标记为 `interrupted`。这个 cmdline 校验避免误杀 PID 复用后的无关进程。
- 回放闸门：`JobManager.model()` 要求 `status == 'completed'`、`env_id` 匹配、
  `fingerprint` 与当前 descriptor 一致、`model.zip` 存在。

## 6. 环境指纹

`jobs.fingerprint(descriptor)` = SHA256(稳定 JSON（剔除 `installed`）)，对 MJCF 再追加
环境目录下**所有普通文件**（跳过符号链接与逃逸出目录的路径）的「相对路径 + 内容」流式哈希。
因此改动 mesh、texture 或被 `<include>` 的 XML 都会使旧模型失效。分块读取（1 MiB）以限制内存。

## 7. 认证与边界

- `MUJOCO_CONSOLE_PASSWORD` 为空时 `/api/login` 直接返回 503。
- 密码比较用 `secrets.compare_digest`；成功后签发 `token_urlsafe(32)`，TTL 12h，存于进程内存。
- Cookie：`HttpOnly`、`SameSite=strict`、`Path=/`，`Secure` 由 `COOKIE_SECURE` 控制。
- 限流按客户端 IP：`LOGIN_MAX_ATTEMPTS`/`LOGIN_WINDOW_SECONDS`，命中返回 429。
- `--no-proxy-headers` 使 uvicorn 忽略 `X-Forwarded-For`，反代部署时限流不会被伪造头绕过；
  代价是反代后面所有客户端共享同一限流桶。
- 全局响应头：`nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、
  `Cache-Control: no-store`、受限 CSP。
- 默认面向可信局域网 HTTP；**不要直接暴露公网**。

## 8. 资源与并发

| 维度 | 机制 |
|---|---|
| viewer 并发 | `MAX_VIEWERS`（默认 3），超出返回 400 |
| viewer 空闲回收 | `SESSION_IDLE_SECONDS`（默认 900） |
| 训练并发 | 全局单任务（CPU-first 版本） |
| 进程数 | `pids_limit: 512`；`init: true` 回收僵尸进程 |
| 共享内存 | `shm_size: 1gb`（PyTorch DataLoader 需要） |
| 优雅停止 | `stop_grace_period: 40s` |
| 磁盘 | 训练产物在 `data/runs/`，**无自动清理/配额** |

实测（12 线程 CPU、3 viewer 并发、12 fps 目标）：容器 CPU ≈ 815%，内存 ≈ 594 MiB；
空闲时 ≈ 0.16% CPU / 35 MiB。

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

### 可诊断的环境导入

`scan()` 返回 `(entries, problems)` 且**永不抛异常**：单个坏目录不会阻止控制台启动。
每个 problem 带 `severity` / `reason` / `detail` / `id`：

| severity | 含义 | 例子（`reason`） |
|---|---|---|
| `error` | 环境**不会被列出** | `missing_manifest`、`invalid_manifest_json`、`manifest_not_an_object`、`invalid_directory_name`、`missing_xml`、`xml_outside_environment`、`invalid_xml_field`、`unsupported_kind`、`invalid_gym_id`、`invalid_registration_module`、`manifest_is_symlink`、`internal_error` |
| `warning` | 环境**仍可用**，但 manifest 不符合 schema | `schema_violation`（用 `schemas/environment.schema.json` 校验，由 `jsonschema` 提供） |

> **校验必须真的生效**：schema 文件随镜像发布（`Dockerfile` 的 `COPY schemas ./schemas`，
> 且 `.dockerignore` **不得**排除 `schemas/`）。若 schema 不可用，`GET /api/catalog` 的
> `schema.available` 为 `false` 并给出 `reason`，lifespan 也会打 WARNING——
> **不允许**让「校验关闭」与「目录干净」看起来一样（MJC-P3-110 的教训）。

- `GET /api/catalog` 返回 `{"environments": [...], "problems": [...], "schema": {"available", "path", "reason"}}`，
  前端在环境目录下方用角落提示展示问题摘要（`textContent`，无 XSS 风险）。
- 服务启动时在 lifespan 中把每个 problem 以 warning 写进容器日志。
- `scripts/validate_manifests.py` 在 CI 中既在 runner 上跑，也**在镜像内不挂载仓库**跑
  （挂载时 `import app` 指向仓库副本，验不到镜像自带内容）；任何 problem 即失败。

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
GET  /api/sessions          → 只读清单（公开投影；不刷新 last_seen，轮询不会给会话续命）
GET  /api/sessions/{id}     → 状态快照（state/mode/paused/steps/episodes/reward/error/subscribers/render/fps/width/height）
GET  /api/sessions/{id}/stream → MJPEG（长连接，服务端逐帧推送；进入时 subscribe，断开时 unsubscribe；
                               worker 已退出时返回 409 而不是空流）
POST /api/sessions/{id}/{reset|pause|driver|stop}
```

### 按需渲染（重要契约）

viewer 子进程**只在有订阅者时才创建光栅化器**：

- 渲染真值是会话与 worker **共享的 `multiprocessing.Event`**（`render_requested`），
  与订阅计数在**同一把锁内** set/clear；worker 每循环重读并写进 `runtime.render`。
  它**不**走命令队列：旧实现经 `commands` 下发开关，交错时会「无人观看仍在渲染」或
  「有人观看却冻结」，队列满时开关直接丢失（第三轮 MJC-P1-201，已用竞态复现证明）。
- 历史遗留的 `{'op':'render'}` 命令被**显式忽略**，防止队列里的陈旧命令与事件打架。
- 已 `close()` 或 worker 已退出的会话，`subscribe()` 是 no-op：**死会话不会被晚到的客户端复活**。
- MJPEG 端点的 async generator 在开始时 subscribe、在 `finally` 中 unsubscribe，因此浏览器关闭/
  刷新/切换环境都会自动停止渲染（实测：断开后容器 CPU 169.5% → 1.6%）；
- 无人订阅时物理仍按 `VIEWER_FPS` 步进、状态继续上报，UI 仍能看到步数增长，控制指令也照常生效；
- **程序化消费 `wait_frame()` 的代码必须先 `subscribe()`**（否则永远收不到帧——
  `scripts/training_smoke_test.py` 就是范例，早期版本漏了两行导致回归）。

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
| viewer 渲染 | 仅在有订阅者时渲染；帧率/分辨率由 `VIEWER_FPS`/`VIEWER_WIDTH`/`VIEWER_HEIGHT` 控制 |
| viewer 线程池 | `VIEWER_RENDER_THREADS`（llvmpipe，默认 2）、`VIEWER_BLAS_THREADS`（BLAS/OpenMP，默认 1） |
| 训练并发 | 全局单任务（CPU-first 版本） |
| 容器资源 | `pids_limit: 512`、`shm_size: 1gb`、`init: true`；可选 `CONSOLE_CPU_LIMIT`/`CONSOLE_MEM_LIMIT`（默认不限） |
| 优雅停止 | `stop_grace_period: 40s` |
| 磁盘 | 训练产物在 `data/runs/`，**无自动清理/配额** |

### 实测成本拆解（12 逻辑核 / x86_64 / OSMesa，640x480，目标 12 fps）

单个 viewer 每个循环的 CPU 开销（cgroup `cpu.stat` 采样，容器总量）：

| 阶段 | 开销 | 占循环 |
|---|---|---|
| MuJoCo 物理步进 | 0.12 ms 墙钟 | <1% |
| OSMesa/llvmpipe 光栅化 | 约 490 ms CPU（约 30 ms 墙钟 x 12 线程） | **>99.5%** |
| PIL `fromarray` | 0.18 ms | 0.04% |
| JPEG 编码 q72 | 0.84 ms | 0.17% |
| 策略推理 `predict` | 0.19 ms | 0.04% |

线程归属（单个 viewer 进程）：默认 39 线程 = 12 llvmpipe + 12 OpenBLAS 空闲 + 其余 Python；
限制后 8 线程。uvicorn 进程自身约 20 线程（`asyncio.to_thread` 默认执行器按需扩张）。

llvmpipe 线程数与并发 viewer 数的影响：

| llvmpipe 线程 | 1 viewer | 3 viewers | 每 viewer fps |
|---|---|---|---|
| 12（默认池） | 522% | 645% | 11.4 |
| 4 | 214% | 617% | 11.2 |
| **2（默认值）** | **170%** | **430%** | **11.6** |

优化前后（真实 API 会话，平均窗口 20–26 s）：

| 场景 | 优化前 | 优化后 | 变化 |
|---|---|---|---|
| 1 viewer，无人订阅 | 512% | **1.5%** | −99.7% |
| 1 viewer，正在被观看 | 500% | **159%** | −68% |
| 1 viewer，浏览器断开后 | 499% | **1.6%** | −99.7% |
| 3 viewers 同时观看 | 860% | **549%** | −36% |
| 容器任务数（3 viewers） | 142 | **42** | −70% |

训练侧参考：PPO 短训练约 2.9 核 / 17 线程 / 378 MiB；训练 + 1 viewer 并发时容器约 4.8 核，
宿主仍有约 55% 空闲。容器默认无 CPU/内存上限，可共存但无硬保障。

# 本机验证报告 · 2026-11-18（Ubuntu 24.04 真实部署）

- 仓库：`1998x-stack/MuJoCo-Environment-Console`
- `BASE_SHA`：`f64bc8f5319754e3228bf626804ba408518c5171`（= 本轮开始时 `origin/main`）
- 分支：`agent/local-deploy-20261118-1058`
- 部署主机：Ubuntu 24.04.3 LTS 宿主机（非容器、非 macOS）
- 结论：**PARTIAL → 核心全部 PASS**，见下方未完成项

本轮所有原始日志保存在本机 `.artifacts/runs/20261118-105857-f64bc8f/`（未提交）。

## 1. 宿主机环境

| 项 | 实测值 |
|---|---|
| OS | Ubuntu 24.04.3 LTS (noble) |
| 内核 | Linux 7.0.0-38-generic |
| 架构 | x86_64 |
| CPU | Intel Core i5-10500，6 核 12 线程（AVX2，无 AVX-512） |
| 内存 | 31 GiB（另 8 GiB swap） |
| 磁盘 | `/` 735 GiB，可用 575 GiB |
| Docker | 29.1.3（overlayfs） |
| Docker Compose | 2.40.3 |
| 已有业务容器 | 27 个（其他项目），未被本轮操作影响 |
| 端口冲突 | **8000 被另一个项目 `TraceMap` 占用** → 本轮使用 `CONSOLE_PORT=8010` |

## 2. 部署结果

| 项 | 值 |
|---|---|
| 部署入口 | `bash scripts/deploy.sh`（退出码 0） |
| 镜像 | `mujoco-environment-console:local`，435 MiB，`sha256:1b4f92b42797…` |
| 容器 | `mujoco-console`，`Up (healthy)`，`restarts=0` |
| 端口 | `0.0.0.0:8010 -> 8000/tcp` |
| 健康检查 | `GET /healthz` → `{"ok":true,"service":"mujoco-console"}` |
| 容器内依赖 | MuJoCo 3.3.7 / Gymnasium 1.4.0 / Robotics 1.4.2 / SB3 2.9.2 / torch 2.9.0+cpu / numpy 2.5.5 / pillow 12.3.0 / fastapi 0.163.2 |
| CUDA | `torch.cuda.is_available() == False`（符合 CPU-first 定位） |

## 3. 分层验证结果

### L0 静态检查与单元测试

| 检查 | 结果 |
|---|---|
| `python3 -m compileall -q app tests scripts` | exit 0 |
| `node --check app/static/app.js` | exit 0 |
| `bash -n scripts/*.sh` | 两个脚本均 exit 0 |
| `python3 -m json.tool schemas/environment.schema.json` | exit 0 |
| `python -m pytest -q` | **23 passed**（基线 16 → 新增 7） |
| manifest × JSON Schema 校验 | 新增测试，全部 shipped manifest 通过 |

注：宿主机缺少 `python3-venv`（安装需 sudo 改系统），因此在**一次性容器**中运行 pytest，
未污染系统 Python。

### L1 容器与 API

`CONSOLE_PORT=8010 MAX_VIEWERS=3` 下全部 PASS（0 failures）：

- 未登录访问 `/api/catalog`、`/api/me`、`/api/training` 均 401；`/healthz` 与静态资源 200，未知路径 404。
- `/app.js` → `application/javascript`，`/app.css` → `text/css; charset=utf-8`。
- 安全响应头齐全：`x-content-type-options`、`x-frame-options: DENY`、`referrer-policy`、
  `cache-control: no-store`、CSP。
- 登录：错误密码 401、空密码 422、正确密码 200，Cookie 带 `HttpOnly; SameSite=strict; Max-Age=43200`。
- 输入校验：未知环境 400、缺 `env_id` 422、`DQN` 400、步数 0/500/5 000 001 均 422、
  未知 run 404、路径穿越 `custom:../../etc` 400。
- 会话：创建 / 状态 / reset / pause / driver(random) / driver(policy 无 run_id→400) / 非法 mode→400 /
  stop→200 / stop 后 404。
- **viewer 上限**：第 1–3 个 200，第 4 个 400 `Viewer limit reached (3)`；停止后可再建（200）。
- **登录限流**：连续 8 次错误密码均 401，第 9 次即使密码正确也 429；`docker compose restart` 后
  限流计数清空（恢复 200）。
- 登出后 `/api/catalog` 恢复 401。

### L2 MuJoCo 环境（18/18 PASS）

`docker compose exec -T console python scripts/smoke_test.py --render --all` → **18/18 environments passed**。
逐环境明细（`environment_id / adapter / installed / trainable / reset / step / render / frame_shape / status`）：

| environment_id | adapter | trainable | frame_shape | status |
|---|---|---|---|---|
| `gym:InvertedPendulum-v5` | gym | yes | 480×640×3 | PASS |
| `gym:InvertedDoublePendulum-v5` | gym | yes | 480×640×3 | PASS |
| `gym:Reacher-v5` | gym | yes | 480×640×3 | PASS |
| `gym:Pusher-v5` | gym | yes | 480×640×3 | PASS |
| `gym:HalfCheetah-v5` | gym | yes | 480×640×3 | PASS |
| `gym:Hopper-v5` | gym | yes | 480×640×3 | PASS |
| `gym:Walker2d-v5` | gym | yes | 480×640×3 | PASS |
| `gym:Swimmer-v5` | gym | yes | 480×640×3 | PASS |
| `gym:Ant-v5` | gym | yes | 480×640×3 | PASS |
| `gym:Humanoid-v5` | gym | yes | 480×640×3 | PASS |
| `gym:HumanoidStandup-v5` | gym | yes | 480×640×3 | PASS |
| `fetch:FetchReach-v4` | gym | yes | 480×640×3 | PASS |
| `fetch:FetchPush-v4` | gym | yes | 480×640×3 | PASS |
| `fetch:FetchSlide-v4` | gym | yes | 480×640×3 | PASS |
| `fetch:FetchPickAndPlace-v4` | gym | yes | 480×640×3 | PASS |
| `custom:custom_pendulum` | mjcf | yes | 480×640×3 | PASS |
| `custom:custom_double_pendulum` | mjcf | yes | 480×640×3 | PASS |
| `custom:scene_demo_viewer` | mjcf | **no（仅演示）** | 480×640×3 | PASS |

- Fetch 观测为 `Dict` 空间，其余为 `Box`；全部奖励有限值；无 MuJoCo 运行时警告（`warnings: []`）。
- 历史基线为 16 个环境，本轮为 16（基线集） + 2（本轮新增）。

### L3 浏览器与局域网

以 **真实 Chromium（Playwright 1.65.1，headless）访问局域网地址** 执行，两套脚本共 **48 项断言全部 PASS**：

主流程（30/30）：登录门 → 错误密码内联报错 → 登录 → 18 个环境卡片与计数器 →
分类标签（`全部/控制/自定义控制/自定义场景/Fetch 机器人/人形/运动/机械臂`，标签唯一）→
运动分类筛选 → 搜索 → 启动 Hopper → 浏览器解码 MJPEG（640×480）→ 步数/回合/奖励指标递增 →
截图逐帧比对确认**画面真的在变化** → 暂停后步数冻结、按钮变「▶ 继续」→ 恢复后步数继续增长 →
重置 → 策略驱动无模型时给出引导 toast → 自定义 MJCF 环境运行 → 启动 PPO 训练 →
训练日志弹窗 → 登出回到登录门 → 刷新仍受门 → Cookie 会话跨刷新保持 →
无意外控制台错误（仅预期的 401 引导探测）→ MJPEG 连接仅在会话拆除时被浏览器主动中断。

补充验收（18/18）：新环境（`<include>` + mesh）在浏览器运行并可训练 → 训练 1000 步实际 2048 步
（PPO rollout 取整，符合 README）→ run 卡片显示 `completed` 与「▶ 策略回放」→
回放后服务端 `mode=policy` 且绑定 `policy_run`，UI 驱动控件切换到「策略模型」，步数继续增长，
画面持续更新，无 `Model load failed` → 仅演示场景渲染正常、标注「仅演示」、
训练按钮禁用且服务端返回 400 → `gym:InvertedPendulum-v5` 已有模型回放成功。

**局域网可达性**：端口监听于 `0.0.0.0:8010`，通过局域网 IP `http://<LAN-IP>:8010` 完成全部
浏览器操作（非 `127.0.0.1`）。未从第三方独立客户端验证，标记见 §6。

未使用截图上传至仓库；脱敏截图只保存在本机 `.artifacts/.../browser/`。

### L4 强化学习

`docker compose exec -T console python scripts/training_smoke_test.py` → **exit 0**

| 算法 | 请求步数 | 实际步数 | 评估回报（种子 101/202/303） | 状态 |
|---|---|---|---|---|
| PPO | 1000 | **2048** | 28.0 / 30.0 / 28.0 | completed |
| SAC | 1000 | 1000 | 58.0 / 62.0 / 64.0 | completed |

两者均完成 checkpoint 保存、加载与隔离 ViewerSession 策略回放（`isolated_policy_viewer: passed`）。

训练生命周期补充测试（全部 PASS）：

- 单任务并发限制：第二个任务返回 400 `One training job at a time in the CPU-first edition`。
- 取消：`status=cancelled`，无 `model.zip`，日志仍可读，重复取消 400，未知 run 404。
- **训练中重启容器**：重启后该任务变为 `interrupted`（`error: Server restarted while training was active`），
  残留 trainer 进程组被终止（`gone`），随后可立即启动新任务（200）。
- 优雅停止（`docker compose stop`）时若有活跃训练：写入 `interrupted` + `Server is shutting down`。
- 持久化：容器重启后 4 条历史 run（2 completed / 1 interrupted / 1 cancelled）全部保留，
  completed 的 `model.zip` 与 `average_reward` 均可用。
- 新环境（`custom:custom_double_pendulum`）真实训练完成：评估回报 382.52（3 个种子一致），
  并成功在浏览器回放。

**注意**：短 smoke 训练只证明链路可用，不代表收敛。上表回报来自 1000 步级训练。

### L5 稳定性与资源

| 项 | 结果 |
|---|---|
| 10 次创建/销毁 viewer | 容器进程数 `5 → 6`（含 `ephemeral` shell 开销），无累积 |
| 3 viewer 并发 MJPEG | 三个流分别取到 66 / 66 / 66 帧 |
| 3 viewer 并发资源 | CPU ≈ 815% (12 线程)、内存 ≈ 594 MiB (1.86%)、`pids=136` |
| 空闲资源 | CPU ≈ 0.16%、内存 35 MiB |
| 优雅停止（含活跃 viewer + 训练） | 6–7 s 完成（`stop_grace_period=40s`），无宿主残留进程 |
| 重启后 | `running/healthy`，进程数回落 |
| 空闲会话回收 | 独立实例 `SESSION_IDLE_SECONDS=20`：45 s 后 worker 进程消失、会话 404、可新建（200） |

长时间（小时级）稳定性测试与满负载压力测试 **NOT_RUN**（未获授权，且会影响同机其他业务）。

## 4. 本轮发现并修复的缺陷

| ID | 级别 | 摘要 |
|---|---|---|
| MJC-P2-001 | P2 | MJPEG 分片以字面量 `\r\n` 结尾而非 CRLF，规范客户端完全无法解析 |
| MJC-P3-002 | P3 | CI 对 MJPEG 只断言字符串存在，无法捕获 MJC-P2-001 |
| MJC-P3-003 | P3 | `schemas/environment.schema.json` 从未被执行校验 |
| MJC-P3-004 | P3 | 分类标签把两个不同 category 映射为同名「自定义」，出现两个同名标签页 |

详见 `issues.md`。另记录 2 条仅文档化的运维/产品观察（未修改代码）。

## 5. 证据索引（本机 `.artifacts/runs/20261118-105857-f64bc8f/`）

| 文件 | 内容 |
|---|---|
| `deploy.log` / `deploy-after-fix.log` / `deploy-final-build.log` | 三次构建与部署完整输出 |
| `static-checks.log` | L0 静态检查 |
| `pytest-host.log` / `pytest-final.log` | 单元测试（16 → 23 passed） |
| `l1-api.log` / `l1-api-after-fix.log` | L1 API 全量 |
| `l1-ratelimit-restart.log` | 限流与重启 |
| `smoke-test*.log` | L2 环境 smoke（16/16 → 18/18） |
| `env-probe*.log` | 逐环境 reset/step/render/frame_shape 明细 |
| `mjpeg-conformance.log` | 修复前：严格分隔符 0 个，分片尾部 `5c725c6e` |
| `mjpeg-conformance-after-fix.log` | 修复后：84 个 `\r\n--frame`，84/84 帧严格解码 |
| `training-smoke.log` / `.exit` | L4 PPO/SAC smoke（exit 0） |
| `l4b-training-lifecycle.log` | 并发/取消/训练中重启/持久化 |
| `l5-stability.log` | 重复创建销毁、并发 viewer、优雅停机、资源 |
| `session-reaper.log` | 空闲会话自动回收 |
| `browser/` + `browser-e2e*.log` + `browser-replay-e2e.log` | 真实浏览器 E2E 与截图 |
| `changes.md` 对应 | `git diff` 内容见仓库提交 |

## 6. 未完成 / 受限项

- **独立第三方客户端**（手机 / 其他主机）的局域网访问验证：`NOT_RUN`（无可用设备）。
  已用局域网 IP 从宿主机完成真实浏览器验证作为替代，但仍不等价。
- **小时级长时间稳定性**与**满负载压力**测试：`NOT_RUN`（未获授权，会影响同机 27 个其他业务容器）。
- **GPU / CUDA**：`NOT_RUN`（本项目为 CPU-first，且未要求）。
- **Menagerie 导入流程** `scripts/import_menagerie.sh`：`NOT_RUN`（需克隆约 GB 级仓库；
  其 `view_only` 路径已由本轮新增的 `custom:scene_demo_viewer` 等价覆盖）。
- **GitHub Actions**：本轮推送后由 CI 实测，结果记录在 `latest.md`。

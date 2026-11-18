# Agent Handoff · Latest

## Metadata

- Timestamp: 2026-11-18T06:35:00Z (UTC)
- Agent: Pi（第二轮：Viewer 资源实证优化 + 环境诊断 + CI 覆盖度）
- Host type: Ubuntu 24.04.3 LTS 物理服务器（本机执行；同机另有 27 个业务容器）
- OS: Ubuntu 24.04.3 LTS (noble), kernel 7.0.0-38-generic, x86_64, 12 逻辑线程, 31 GiB
- Base SHA: `e422870481d68dd20feeb4e36538ee57306b97e8`（= PR #1 HEAD；`origin/main` 仍为 `f64bc8f`）
- Final local SHA: `8153590d51da59a81f9fb0ffaa84939d0fcbc0f4`（代码 tip；其后仅文档元数据提交）
- Remote main SHA: `f64bc8f5319754e3228bf626804ba408518c5171`（PR #1 尚未合并）
- Branch: `agent/local-deploy-20261118-1058`（按指示继续在 PR #1 分支协作，未从旧 main 重做）
- PR: https://github.com/1998x-stack/MuJoCo-Environment-Console/pull/1
- CI run（代码 tip `8153590`）: https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44257891758 — **success**（2m37s）

## Current State

| 维度 | 状态 | 说明 |
|---|---|---|
| Deployment | **PASS** | `scripts/deploy.sh` exit 0；容器 `Up (healthy)`，`8010->8000/tcp`，镜像 `sha256:12c10d83…` |
| Container health | **PASS** | `/healthz` 正常；`restarts=0` |
| Unit / integration tests | **PASS** | 完整依赖 **55 passed, 0 skipped**；轻量依赖 54 passed, 1 skipped（守门测试） |
| Environment smoke | **PASS** | `smoke_test.py --render --all` **18/18** |
| API / auth | **PASS** | L1 全量断言 0 失败 |
| Browser E2E | **PASS** | 真 Chromium over LAN：**48/48**（30 主流程 + 18 新环境/回放） |
| Third-party MJPEG | **PASS** | ffmpeg（文件 60 帧 / 实时 HTTP 60 帧 @12fps）、OpenCV（60 帧 640×480），无 boundary 错误 |
| **Viewer CPU（无人观看）** | **PASS（本轮优化）** | 512% → **1.5%**（−99.7%）；断开后 499% → **1.6%** |
| **Viewer CPU（单 viewer 观看）** | **PASS（本轮优化）** | 500% → **159%**（−68%），帧率 10.48 → 10.90 fps |
| **Viewer CPU（3 viewer 观看）** | **PASS（本轮优化）** | 860% → **549%**（−36%），容器任务数 142 → **42**，帧率 10.75 → 11.30 fps |
| PPO | **PASS** | 请求 1000 → 实际 2048 步；评估 28/30/28；checkpoint + 隔离回放通过 |
| SAC | **PASS** | 请求 1000 → 实际 1000 步；评估 58/62/64；checkpoint + 隔离回放通过 |
| Model replay | **PASS** | 浏览器回放 `mode=policy` 并绑定 `policy_run`，画面持续更新 |
| Training lifecycle | **PASS** | 并发限制 / 取消 / 训练中重启 → `interrupted` + 进程组清理 / 持久化 |
| Session cleanup / restart | **PASS** | 10 次创建销毁无累积；优雅停止 6–7 s；重启后 healthy |
| Catalog diagnostics | **PASS** | 坏环境以结构化 `problems` 上报，控制台仍可用；仓库自带 envs 零问题 |
| Resource limits | **PASS（opt-in）** | `CONSOLE_CPU_LIMIT` / `CONSOLE_MEM_LIMIT` 默认不限制 |
| CI (GitHub Actions) | **PASS** | [run 44257891758](https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44257891758)：严格 step `strict suite OK: 55 passed`（0 skipped）、`3/3 manifests valid`、`0 problem(s)`、`MJPEG framing OK: 57 boundaries`、`18/18 environments passed` |
| Long-run stability | **NOT_RUN** | 未获授权（会影响同机其他业务容器） |
| Third-party LAN **device** | **NOT_RUN** | 无可用设备 |
| Convergence | **NOT_RUN** | 需授权与算力预算 |

## 本轮核心结论：为什么 3 个 Viewer 要 815% CPU

1. 无 GPU → `MUJOCO_GL=osmesa` → Mesa llvmpipe **CPU 软光栅化**；
2. llvmpipe 默认按核数建 12 个线程并自旋，numpy/OpenBLAS 再建 12 个（对渲染无用）；
3. `run_worker` **无条件**每帧 `env.render()`，与是否有浏览器观看无关。

成本构成（单 viewer 每循环）：物理 0.12 ms（<1%）、**渲染约 490 ms CPU / 约 30 ms 墙钟（>99.5%）**、
JPEG+PIL 1.0 ms、策略推理 0.19 ms。单个 worker 39 线程。

## Completed Work

1. **按需渲染**（P1）：只有存在订阅者才创建光栅化器；无人观看时物理继续步进、状态继续上报。
2. **viewer 线程预算**（P1）：默认 `LP_NUM_THREADS=2` + BLAS=1，实测 CPU 更低且帧率更高。
3. **可配置化**：`VIEWER_FPS` / `VIEWER_WIDTH` / `VIEWER_HEIGHT` / `VIEWER_RENDER_THREADS` /
   `VIEWER_BLAS_THREADS`，以及可选 `CONSOLE_CPU_LIMIT` / `CONSOLE_MEM_LIMIT`。
4. **修复自引入回归**（MJC-P1-102）：`training_smoke_test.py` 未订阅导致不再产帧；已修并文档化契约。
5. **第三方 MJPEG 实测**：ffmpeg（文件/实时 HTTP）+ OpenCV，≥60 帧、尺寸一致、无 boundary 错误；
   获取与解码分离，凭据不入命令行/日志/Git。
6. **CI 覆盖度**：严格模式 `CONSOLE_TEST_REQUIRE_PHYSICS=1`（依赖缺失 → fail）+ 新 step 在部署镜像内
   跑完整套件并断言 `skipped == 0`。
7. **环境导入可诊断**（P3）：`scan()` 返回结构化 `problems`；`jsonschema` 进入运行时依赖。
8. **训练错误可诊断**（P2）：137/SIGKILL 明确解释为内存上限 / 外部 kill / 宿主 OOM。
9. **文档与 Handoff**：架构成本拆解、runbook 6.1 资源调优、验证报告、本目录 run 记录。

## Confirmed Findings

- 实测证明「3 viewer ≈ 815% CPU」的根因是软光栅化 + 无条件渲染 + 线程池按核数空转。
- 关闭阴影/MSAA（`shadowsize=0` / `offsamples=0`）**无任何收益**（像素与时间差异 0）→ 未引入。
- 降分辨率收益有限（640×480 → 320×240 仅约 −24%），固定开销占主导 → 作为可调项。
- `LP_NUM_THREADS` 从 12 降到 2：CPU −67%，帧率反而 +10%（自旋线程互相争抢）。
- trainer 约 2.94 核 / 17 线程；trainer + 1 viewer 并发时容器 477.9%，宿主仍有约 55% 空闲。
- 宿主机 8000 端口仍被其他项目占用（PID 114256 未变），本轮继续使用 8010。

## Open Issues

| ID | 级别 | 状态 | 摘要 |
|---|---|---|---|
| MJC-P1-101 | P1 | **FIXED** | viewer 无条件渲染导致约 815% CPU；已改为按需渲染 + 线程预算 |
| MJC-P1-102 | P1 | **FIXED** | 自引入回归：`training_smoke_test.py` 未订阅不再产帧 |
| MJC-P2-103 | P2 | **FIXED** | SIGKILL/OOM 训练退出原因不可诊断 |
| MJC-P3-104 | P3 | **FIXED** | CI 集成测试可能被静默跳过（4 skipped） |
| MJC-P3-105 | P3 | **FIXED** | 坏环境目录被静默忽略，前后端都无提示 |
| MJC-P3-106 | P3 | OPEN（仅记录） | uvicorn 默认线程池按需扩张至约 16 线程且不回收 |
| MJC-P3-107 | P3 | OPEN（仅记录） | 缺 viewer 会话枚举/清理接口（影响已从资源降级为槽位） |
| MJC-P3-108 | P3 | OPEN（仅记录） | `data/runs/` 无保留策略 |
| MJC-P3-109 | P3 | OPEN（仅记录） | trainer 线程数未加默认上限（无实测依据，不引入） |

## Blockers

- 无阻塞主流程的 P0/P1 缺陷。
- 未执行项均为「未获授权」或「无可用设备」：小时级稳定性、满负载压力、第三方设备局域网验证、收敛性验证。

## Files Changed

```text
app/worker.py                 按需渲染（ViewerRuntime）+ 线程预算（apply_process_limits）
app/sessions.py               subscribe/unsubscribe 契约、viewer_config 校验、ctx 注入、status 扩展
app/main.py                   MJPEG 端点订阅/退订、catalog problems、lifespan 警告日志
app/catalog.py                scan() 结构化诊断（severity/reason/detail），坏目录不再静默
app/jobs.py                   exit_reason(): 137/143/信号可诊断
app/static/app.js             渲染 problems 摘要
app/static/index.html         新增 #catalogProblems 容器
compose.yaml                  可选 cpus / mem_limit（默认不限制）
requirements.txt              新增 jsonschema>=4.20,<5
.env.example                  viewer 参数与可选上限（附实测说明）
scripts/training_smoke_test.py   读帧前订阅（修 MJC-P1-102）
scripts/validate_manifests.py    schema + scan() 诊断，任何 problem 即失败
tests/test_worker.py          新增：渲染开关、命令语义、线程预算
tests/test_sessions.py        订阅计数驱动渲染、viewer_config、ctx 注入
tests/test_api.py             流订阅/退订、catalog problems、坏环境不阻断
tests/test_catalog.py         11 种坏目录 reason、schema warning、缺失 env root
tests/test_integration.py     require() 严格模式
.github/workflows/ci.yml      新增部署镜像内完整测试 step（禁止 skip）
AGENTS.md / README.md / docs/**  见 changes.md
```

## Evidence

本机证据目录（未提交）：`.artifacts/runs/20261118-053523-e422870/`

关键文件：`phase2-viewer-before.log`（优化前 512/500/499/860%）、`phase2-viewer-final.log`
（优化后 1.5/159/1.6/549%）、`component-bench.log`（成本拆解）、`phase2-knob-sweep.log` 与
`knob-sweep.jsonl`（线程/分辨率/帧率旋钮）、`multiviewer-scaling.log`（3 并发线程缩放）、
`quality-bench.log`（阴影/MSAA 无收益）、`third-party-mjpeg.log` + `ffmpeg-decode.log` +
`ffmpeg-live.log` + `opencv-decode.log`（第三方解码）、`render-toggle-final.log`（订阅→渲染行为）、
`training-smoke-after.log`、`l1-final.log`、`smoke-test-after.log`、`browser-e2e-after.log`、
`browser-replay-after.log`、`l4b-after.log`、`l5-final.log`、`pytest-final.log`、
`resource-samples-*.csv`。

仓库内只保留脱敏摘要（`docs/verification/2026-11-18-viewer-resource-optimisation.md` 与本目录）。

## Remaining Risks

1. 资源对照实验的窗口为 20–26 s，属于有界测量；**未做小时级驻留**，长稳结论不可外推。
2. `LP_NUM_THREADS=2` 在重场景下帧率余量较小（Humanoid-v5 实测 11.70 fps）。若未来引入
   几何更复杂的场景或更大分辨率，应实测后再决定是否提高该值。
3. 按需渲染是行为契约变更：**任何新的程序化 `wait_frame()` 消费者都必须先 `subscribe()`**
   （上一轮已有一次自引入回归的教训）。
4. 容器默认无 CPU/内存上限；多 viewer + 训练并存时可能挤占同机其他业务。
5. ffmpeg/OpenCV 的验证基于本机部署镜像；未在 CI 中固化（工具镜像较大），属人工验证项。
6. `render` 状态目前不在前端显式展示（仅在 API 与日志中可见），排障需要 curl。

## Exact Next Steps

1. ~~回填 `Final local SHA` / `CI run`，确认 CI 全绿~~ → **已完成**：CI success，严格 step 输出 `55 passed` 且 0 skipped。
2. NS-2：用同局域网另一台设备完成真实浏览器验收，并记录连接期间的 viewer CPU。
3. NS-3：新增只读 `GET /api/sessions`，缓解被遗弃会话占用槽位的问题。
4. NS-6：收敛 uvicorn 默认线程池（可选，属优化而非缺陷）。
5. 获授权后执行 NS-5（≥2 小时稳定性）与 NS-7（收敛性）。
6. 若引入更复杂场景/更高分辨率，先重跑 `.artifacts/loop_probe.py` 再决定 `VIEWER_RENDER_THREADS`。

## Resume Instructions

```bash
cd /home/ubuntu/codes/MuJoCo-Environment-Console
git fetch origin --prune && git log --oneline -12
cat AGENTS.md && cat docs/handoff/latest.md
ls docs/handoff/runs/
```

- **部署端口继续用 8010**；不要动 8000 上属于其他项目的服务。
- 不要 `docker compose down -v` / `docker system prune`：同机另有 27 个业务容器。
- 复现资源对照：`python3 .artifacts/sampler.py mujoco-console <秒> 2 <label>`（cgroup 精确采样）
  + `.artifacts/phase2_viewer_experiment.sh`、`.artifacts/render_toggle_check.sh`、
  `.artifacts/third_party_mjpeg_check.sh`（这些脚本在 `.artifacts/`，未提交，可按需重建）。
- 跑完整测试：见 `AGENTS.md` 的 `CONSOLE_TEST_REQUIRE_PHYSICS=1` 命令（必须 0 skipped）。

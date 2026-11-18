# Agent Handoff · Latest

## Metadata

- Timestamp: 2026-11-18T04:13:37Z (UTC)
- Agent: Pi (MuJoCo Environment Console local deploy / verify / fix agent)
- Host type: Ubuntu 24.04.3 LTS 物理服务器（本机执行，非容器、非 macOS）
- OS: Ubuntu 24.04.3 LTS (noble), kernel 7.0.0-38-generic, x86_64
- Base SHA: `f64bc8f5319754e3228bf626804ba408518c5171`
- Final local SHA: `3f3ccb3f9cde03c967662d6486ac1578447eb2e3`（代码 tip；其后仅文档元数据提交）
- Remote main SHA: `f64bc8f5319754e3228bf626804ba408518c5171`（本轮开始时 = BASE_SHA，远端无新提交）
- Branch: `agent/local-deploy-20261118-1058`
- PR: https://github.com/1998x-stack/MuJoCo-Environment-Console/pull/1
- CI run: https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44235254442 — **success**（2m36s）

## Current State

| 维度 | 状态 | 说明 |
|---|---|---|
| Deployment | **PASS** | `scripts/deploy.sh` exit 0；容器 `Up (healthy)`，端口 `8010→8000` |
| Container health | **PASS** | `/healthz` 返回 `{"ok":true,...}`；`restarts=0` |
| Static / unit tests | **PASS** | compileall / node / bash -n / json.tool 全通过；`pytest` **23 passed** |
| Environment smoke | **PASS** | `smoke_test.py --render --all` **18/18**，帧 480×640×3，无 MuJoCo 警告 |
| API / auth | **PASS** | L1 全量断言 0 失败（401/403 路径、限流、校验、viewer 上限） |
| Browser E2E | **PASS** | 真 Chromium over LAN IP，两套脚本 **48/48** 断言通过 |
| MJPEG | **PASS（修复后）** | 严格 RFC 2046：84 个 `\r\n--frame`，84/84 帧解码 |
| PPO | **PASS** | smoke 请求 1000 → 实际 2048 步；评估 28/30/28；checkpoint + 隔离回放通过 |
| SAC | **PASS** | smoke 请求 1000 → 实际 1000 步；评估 58/62/64；checkpoint + 隔离回放通过 |
| Model replay | **PASS** | 浏览器回放：服务端 `mode=policy` 并绑定 `policy_run`，画面持续更新 |
| Session cleanup | **PASS** | 空闲回收（20 s 实例验证）、viewer 上限、无进程累积 |
| Restart / Persistence | **PASS** | 训练中重启 → `interrupted` 且进程组被清理；4 条历史 run 完整保留 |
| Resource tests | **PARTIAL** | 有界测试全通过；小时级/满负载 **NOT_RUN** |
| CI (GitHub Actions) | **PASS** | run 44235254442 success；新增的 schema 校验与 MJPEG 分帧断言均实测执行 |

## Completed Work

1. 在真实 Ubuntu 24.04 宿主机完成 `scripts/deploy.sh` 全流程部署（避让被其他业务占用的 8000 端口）。
2. 执行 L0–L5 分层验证，形成命令 + 退出码 + 日志级别的可复核证据。
3. 定位并修复 **MJC-P2-001**：MJPEG 分片以字面量 `\r\n` 结尾，导致规范 MJPEG 客户端完全无法解析。
4. 用修复前后对照实验量化缺陷（严格分隔符 0 → 84；严格解码 0 → 84 帧）。
5. 硬化 CI（新增 MJPEG 分帧断言、schema 校验依赖、新环境断言），补齐 7 个回归测试。
6. 修补 AI/CI 缺口：新增 manifest × JSON Schema 校验脚本与测试（此前 schema 无人执行）。
7. 新增两个可直接复制的示例环境，覆盖此前完全未被测试的路径：
   `custom_double_pendulum`（`<include>` + 二进制 mesh）与 `scene_demo_viewer`（`view_only`）。
8. 修复新增环境暴露的 UI 缺陷 **MJC-P3-004**（两个同名「自定义」分类标签页）。
9. 建立持久化 Handoff 体系：`AGENTS.md`、`docs/architecture/`、`docs/runbooks/`、
   `docs/verification/`、`docs/handoff/`。

## Confirmed Findings

- 历史 CI 基线（16 环境 + PPO/SAC）在本机**真实复现**，并扩展到 18 环境。
- 旧 CI 与 `smoke_test.py` 对 MJPEG 的断言（仅检查 `Content-Type: image/jpeg` 字符串）
  **无法**发现分帧缺陷；这是本轮修复必须同时硬化 CI 的原因。
- 宿主机 8000 端口被无关项目占用。**不要**为了「按文档使用 8000」而停止其他业务服务。
- 本机存在 27 个其他业务容器；本轮所有操作均在 `mujoco-console` 容器与 `data/`、`envs/` 内完成，
  未触碰其他容器、卷或服务。
- MuJoCo 3.3.7 **无法加载 ASCII STL**（`number of faces should be between 1 and 200000`），
  必须使用二进制 STL。已写入 `AGENTS.md` 与 `envs/README.md`。

## Open Issues

| ID | 级别 | 状态 | 摘要 |
|---|---|---|---|
| MJC-P2-001 | P2 | **FIXED** | MJPEG 分片结尾非 CRLF，规范客户端无法解析 |
| MJC-P3-002 | P3 | **FIXED** | CI/冒烟测试对 MJPEG 的断言过弱 |
| MJC-P3-003 | P3 | **FIXED** | `schemas/environment.schema.json` 从未被执行校验 |
| MJC-P3-004 | P3 | **FIXED** | 两个同名「自定义」分类标签页 |
| MJC-P3-005 | P3 | OPEN（仅记录） | 无「列出/关闭当前 viewer 会话」API；被遗弃会话占用槽位至 `SESSION_IDLE_SECONDS` |
| MJC-P3-006 | P3 | OPEN（仅记录） | `data/runs/` 无配额与清理策略，长期运行会持续增长 |
| MJC-P3-007 | P3 | OPEN（仅记录） | compose 未设置内存/CPU 上限（仅有 `pids_limit` 与单任务约束） |
| MJC-P3-008 | P3 | OPEN（仅记录） | `AUTH` 失效 token 仅在登录或鉴权时惰性清理，极长会话下缓慢增长 |

## Blockers

- 无阻塞主流程的 P0/P1 缺陷。
- 未执行项（见 `runs/20261118-105857-f64bc8f/next-steps.md`）：独立第三方设备局域网验证、
  小时级稳定性、满负载压力 —— 均因**未获授权**或**会影响同机其他业务**而保持 `NOT_RUN`。

## Files Changed

```text
.github/workflows/ci.yml                      MJPEG 分帧断言 + jsonschema 依赖 + 新环境断言
.gitignore                                    + .artifacts/（原始证据不入库）
README.md                                     示例环境与 MJPEG 说明
AGENTS.md                                     新增：持久化工程规范
app/main.py                                   MJPEG 分片改为 RFC 2046 CRLF（+ mjpeg_part 助手）
app/static/app.js                             分类标签去重（自定义控制 / 自定义场景）
envs/README.md                                示例表格 + include/mesh/二进制 STL 说明
envs/custom_double_pendulum/                  新增：include + mesh 可训练 MJCF 示例
envs/scene_demo_viewer/                       新增：view_only 仅演示场景示例
schemas/                                      未改；新增校验脚本
scripts/validate_manifests.py                 新增：manifest × schema 校验入口
tests/test_api.py                             + MJPEG 分帧 / view_only 拒绝训练 回归测试
tests/test_catalog.py                         + 示例发现、schema 校验、view_only 不变量
tests/test_integration.py                     + 两个新环境的物理/渲染集成测试
docs/architecture/system-overview.md          新增
docs/runbooks/ubuntu-deployment.md            新增
docs/verification/2026-11-18-local-verification.md   新增
docs/handoff/**                               新增：Handoff 体系与本轮记录
```

## Evidence

本机证据目录（未提交）：`.artifacts/runs/20261118-105857-f64bc8f/`
索引与逐文件说明见 `docs/verification/2026-11-18-local-verification.md` 第 5 节。

关键对照实验：

- `mjpeg-conformance.log`（修复前）：`rfc2046_delimiters_CRLF--frame = 0`，
  分片尾部 `5c725c6e`（字面量 `\r\n`），严格解析得到 0 帧。
- `mjpeg-conformance-after-fix.log`（修复后）：`rfc2046_delimiters_CRLF--frame = 84`，
  分片尾部 `ffd9`（JPEG EOI），严格解析得到 **84/84** 帧。

## Remaining Risks

1. MJPEG 修复后仅由 Chromium 与严格 Python 解析器验证；未用 ffmpeg/OpenCV 实测（本机未安装）。
   分帧现在符合 RFC 2046，风险低，但下轮可用 `ffmpeg -i http://.../stream` 补一次实测。
2. 训练质量结论仅限 1000 步级 smoke；**未做收敛性验证**，不得据此宣称「策略学会了任务」。
3. 新增的 `custom_double_pendulum` 目标为 `[0,0]`（垂直下垂），初始位姿偏离后回报下降；
   这是演示环境，不是有研究意义的任务定义。
4. 本机 `SESSION_IDLE_SECONDS` 相关的会话占用风险仅在自动化场景显现，人工使用无影响。
5. ~~GitHub Actions 结果尚未确认~~ → 已确认 **success**（run 44235254442）。CI 首次运行曾失败一次：本 Agent 在 `tests/test_integration.py` 顶层 `import numpy`，而 CI 轻量依赖集不含 numpy，导致 pytest **收集阶段**报错；改为 `pytest.importorskip('numpy')` 后通过（本地用 `python:3.12-slim` + 同款依赖复现验证）。

## Exact Next Steps

1. ~~回填 `Final local SHA`、`PR`、`CI run`，确认 CI 全绿~~ → **已完成**：CI success，
   日志确认 `3/3 manifests valid`、`MJPEG framing OK: 56 CRLF-delimited boundaries`、
   `Catalog OK: 18 discovered environments`、`18/18 environments passed`。
2. 用 `ffmpeg` 或 `cv2.VideoCapture` 抓取 `/api/sessions/<id>/stream`，作为 MJPEG 修复的第三方实测。
3. 处理 MJC-P3-005：为非 API 客户端提供会话枚举/清理能力（例如只读的 `GET /api/sessions`
   或容器启动时清理孤儿会话）。
4. 处理 MJC-P3-006/007：为 `data/runs/` 增加保留策略，或在 `compose.yaml` 中加入
   `mem_limit`/`cpus` 与文档说明。
5. 在获授权的前提下执行一次小时级稳定性测试，并单独报告（基础验收与长稳分开）。
6. 收敛性验证（可选、需要授权）：对 `gym:InvertedPendulum-v5` 训练 20 万步，
   记录学习曲线并与随机基线对比。

## Resume Instructions

```bash
cd /home/ubuntu/codes/MuJoCo-Environment-Console
git fetch origin --prune
git log --oneline -10
cat AGENTS.md
cat docs/handoff/latest.md
ls docs/handoff/runs/
```

- 若 `origin/main` 已前进：先 `git log <BASE_SHA>..origin/main --oneline` 与 `git diff`，
  判断是否与本轮改动冲突，再决定 rebase。
- **部署端口**：本机 8000 被其他业务占用，请继续使用 `.env` 中的 `CONSOLE_PORT=8010`。
- **不要**运行 `docker compose down -v` / `docker system prune`，那会破坏同机其他 27 个业务容器。
- 如需重新验证：`bash scripts/deploy.sh` → `pytest -q` → `smoke_test.py --render --all` →
  `training_smoke_test.py`；浏览器脚本模板在本机 `.artifacts/browser_*.js`（未提交，可重建）。

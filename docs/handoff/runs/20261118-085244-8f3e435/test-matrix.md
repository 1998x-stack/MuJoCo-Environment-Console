# 测试矩阵 · 第三轮（2026-11-18）

原始日志根目录：`.artifacts/runs/20261118-085244-8f3e435/`（本机，gitignored）。
`PASS` = 本轮真实执行且成功；`NOT_RUN` = 未执行并附原因。

## 0. 版本与测试档位（必须按名引用）

| 字段 | 值 |
|---|---|
| `base_sha` | `8f3e435816572c0db5fabc4880095ca47fc0412a` |
| `code_sha` | `5cf87de627635ff985187dbc1d2b9f216389d398`（其后 `e042d66` 亦为代码/CI 变更） |
| `pr_head_sha` | 见 `changes.md`（docs 提交后回填） |
| `validated_sha` | `e042d66`（本表所有结果对应的最后一个代码提交） |
| `ci_run_id` | `44285265993`（on `e042d66`） |

| 档位 | 环境 | 结果 | 证据 |
|---|---|---|---|
| 严格（CI job 2，`skipped == 0`） | 部署镜像内 + `CONSOLE_TEST_REQUIRE_PHYSICS=1` + git | **93 passed, 0 skipped** | `pytest-round3.log` |
| 完整镜像非严格 | 部署镜像内 `pytest -q` | 92 passed, 1 skipped（守门测试按设计 skip） | `test-count-matrix.log`（早期 90/1，后随新增测试增长） |
| 轻量（CI job 1，无 MuJoCo） | 宿主 `python` + `fastapi uvicorn httpx pytest jsonschema` | 88 passed, 5 skipped | `test-count-matrix.log` |

> 说明：三档在同一份测试上分别为 `N`、`N-1`、`N-5`。本轮数字随修复过程中的新增测试变化，
> 上表严格档为最终值；不写档位的计数一律视为不可审计。

## 1. 分层回归

| 层级 | 检查项 | 命令 / 方式 | 结果 | 证据 |
|---|---|---|---|---|
| L0 | Python / JS / Shell / JSON 语法 | `compileall`、`node --check`、`bash -n`、`json.tool` | PASS | `l0-round3.log` |
| L0 | 18 环境 manifest schema + 发现诊断（镜像内） | `docker run --rm <image> python scripts/validate_manifests.py` | **PASS（3/3、18 environments、0 problem）** | `mjc-p3-110-before.log` |
| L0 | 镜像内 schema 校验可用性 | `python -c "from app import catalog; catalog.schema_status()"`（镜像内，无挂载） | **PASS `available: True`** | 同上 |
| L0 | 单元/集成（严格） | 镜像内 `CONSOLE_TEST_REQUIRE_PHYSICS=1 pytest -q -rs` | **PASS 93 passed, 0 skipped** | `pytest-round3.log` |
| L1 | 认证/校验/限流/viewer 上限/新端点 | `.artifacts/l1_api_test.sh` | **PASS（0 失败）** | `l1-round3.log` |
| L2 | 18 环境 reset/step/render | `smoke_test.py --render --all` | **PASS 18/18** | `smoke-round3.log`、`frozen-verification.log` |
| L3 | 浏览器 E2E 主流程 | `.artifacts/browser_e2e.js` | **PASS 31/31**（连续 6 次 + 冻结构建 1 次） | `browser-e2e-repeat-summary.log`、`e2e-frozen/run.log` |
| L3 | 浏览器：新环境 + 模型回放 | `.artifacts/browser_replay_e2e.js` | **PASS 18/18** | `e2e-frozen/replay.log` |
| L3 | MJPEG 分帧（RFC 2046） | `.artifacts/mjpeg_probe.py` | **PASS 212 分片 / 211 解码帧 / literal-CRLF 0** | `third-party-mjpeg-round3.log` |
| L3 | 第三方解码 ffmpeg（文件） | `ffmpeg -f mpjpeg -i stream.bin` | **PASS 60 帧 640×480，无 boundary 错误** | 同上 |
| L3 | 第三方解码 ffmpeg（实时 HTTP） | `curl \| ffmpeg -f mpjpeg -i pipe:0` | **PASS 60 帧 @12fps** | 同上 |
| L3 | 第三方解码 OpenCV | `cv2.VideoCapture(remux.avi)` | **PASS 60 帧 640×480** | 同上 |
| L4 | PPO / SAC 训练 + checkpoint + 隔离回放 | `scripts/training_smoke_test.py` | **PASS（exit 0）** | `training-smoke-round3.log` |
| L4 | 并发限制 / 取消 / 训练中重启 / 持久化 | `.artifacts/l4b_training_lifecycle.sh` | **PASS（0 失败）** | `l4b-round3.log` |
| L5 | 重复创建销毁 / 3 viewer / 优雅停止 / 重启 | `.artifacts/l5_stability.sh` | **PASS（0 失败）** | `l5-round3.log` |
| L5 | 递归/长时间稳定性 | 未获授权 | **NOT_RUN** | — |
| 专项 | 订阅竞态复现（修复前） | `.artifacts/race_reproduce.py` | 竞态**已复现**（A 泄漏 / B 冻结 / C 丢开关） | `race-before.log` |
| 专项 | 订阅竞态（修复后） | 同上 | **ALL CONSISTENT**（8×400 风暴 0 违反） | `race-after.log` |
| 专项 | 并发/worker 单测 | `pytest tests/test_sessions.py tests/test_worker.py` | **PASS 37 passed** | `race-tests-round3.log` |
| 专项 | 有界 CPU 回落 | `.artifacts/sampler.py`（cgroup v2）+ 真实流 | **0.1% → 169.5% → 1.6%**（冻结构建 1.7%） | `cpu-A/B/C-*.csv`、`cpu-fallback.log` |
| 专项 | CI 门禁自检（故意失败/skip/收集错误/超时） | `.artifacts/ci_gate_verification.sh` | **PASS（6 场景全部按预期拒绝/通过）** | `ci-gate-verification.log` |
| 专项 | 部署镜像内容（schemas 是否随镜像发布） | CI 新增 step 的本地逐字复刻 | **PASS** | `mjc-p3-110-before.log` |
| CI | GitHub Actions 全流程 | [run 44285265993](https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44285265993)（**success**，24 steps） | `junit: 93 tests, 0 failures, 0 errors, 0 skipped`；`strict suite OK`；`image manifest schema OK`；`3/3 manifests valid`；`MJPEG framing OK: 54 boundaries`；`18/18 environments passed`；轻量 job 88 passed / 5 skipped | CI 日志 |

## 2. 版本/环境要点

| 项 | 值 |
|---|---|
| 宿主容器总数 | **27**（未变动；控制台为其中之一） |
| 控制台端口 | `0.0.0.0:8010->8000/tcp`（8000 仍属其他项目） |
| 镜像 ID | 见 `environment.json` |
| `data/runs/` | 42 条 / 4.8 MB（未删除任何训练记录） |
| 容器空闲 CPU | **0.17%**（L5 实测） |

## 3. 本轮新增/更新的测试脚本（均在 `.artifacts/`，未提交）

`race_reproduce.py`（竞态复现与收敛判定）、`ci_gate_verification.sh`（门禁 6 场景）、
`browser_e2e.js`（判据改为服务端行为 + teardown 自清理）、`third_party_mjpeg_check.sh`
（新增分帧探针）、`l4b_training_lifecycle.sh`（修正持久化摘要的引号 bug）、
`sampler.py`、`l1_api_test.sh`（新增 `/api/sessions` 端到端断言）。

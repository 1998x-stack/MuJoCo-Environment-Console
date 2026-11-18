# Agent Handoff · Latest

## Metadata

- Timestamp: 2026-11-18T11:00:00Z (UTC)
- Agent: Pi（第三轮：订阅并发可靠性 + CI 退出码 + Handoff 可审计性 + 会话清单接口）
- Host type: Ubuntu 24.04.3 LTS 物理服务器（本机执行；同机另有 27 个业务容器）
- OS: Ubuntu 24.04.3 LTS (noble), kernel 7.0.0-38-generic, x86_64, 12 逻辑线程, 31 GiB
- `base_sha`: `8f3e435816572c0db5fabc4880095ca47fc0412a`（第二轮文档收尾；`origin/main` 仍为 `f64bc8f`）
- `code_sha`: `e042d66`（本轮最后一个改动 `app/`/`tests/`/`scripts/`/`.github/` 的提交）
- `pr_head_sha`: 本轮文档提交（其后仅 `docs/`，代码状态与 `code_sha` 相同）
- `validated_sha`: `e042d66`（下表所有结论对应的代码状态）
- `ci_run_id`: `44285265993`（on `e042d66`，**success**）；`44284580092`（on `5cf87de`，**failure**，原因见下）
- Remote main SHA: `f64bc8f5319754e3228bf626804ba408518c5171`（PR #1 未合并，按指示不自动合并）
- Branch: `agent/local-deploy-20261118-1058`
- PR: https://github.com/1998x-stack/MuJoCo-Environment-Console/pull/1
- 复现版本标注：`python scripts/handoff_metadata.py --ci-run-id 44285265993`

> 说明：`code_sha` 与 `pr_head_sha` 在本轮**最后一次代码提交后**才出现文档提交，
> 因此若两者不同，测试/CI 结论一律以 `validated_sha = e042d66` 为准。
> 上一次 CI 失败（`5cf87de`）是 CI 真实抓到的缺陷：`scripts/handoff_metadata.py` 假定
> `origin/main` 存在，而 `actions/checkout` 只取单个 ref；已在 `e042d66` 前向修复（回退到根提交并
> 显式标注 `base_ref_resolved: false`）。

## Current State

| 维度 | 状态 | 说明 |
|---|---|---|
| Deployment | **PASS** | `scripts/deploy.sh` exit 0；容器 `Up (healthy)`，`8010->8000/tcp`，镜像 `sha256:e2825371…` |
| Container health | **PASS** | `/healthz` 正常 |
| Unit / integration tests | **PASS** | 严格（镜像内 + `CONSOLE_TEST_REQUIRE_PHYSICS=1`）**93 passed, 0 skipped**；完整镜像非严格 92/1；轻量 88/5 |
| Environment smoke | **PASS** | `smoke_test.py --render --all` **18/18** |
| API / auth | **PASS** | L1 全量断言 0 失败（含新增 `GET /api/sessions`） |
| Browser E2E | **PASS** | **31/31**（连续 6 次）+ 新环境/回放 **18/18** |
| MJPEG framing | **PASS** | 212 分片 / 211 解码帧 / literal-CRLF 0 / 640×480 / 210 帧有变化 |
| Third-party MJPEG | **PASS** | ffmpeg（文件 60 帧、实时 HTTP 60 帧 @12fps）、OpenCV 60 帧，无 boundary 错误 |
| **订阅竞态（本轮修复）** | **PASS** | 8×400 风暴 0 违反；订阅→True、退订→False；队列满不再丢开关 |
| **CPU 回落（本轮复测）** | **PASS** | 无会话 0.1% → 订阅中 169.5% → **断开后 1.6%**（冻结构建 1.7%） |
| **CI 退出码（本轮修复）** | **PASS** | 故意失败 rc=1、故意 skip rc=1、收集错误 rc=2、超时 rc=124、正常 rc=0（6 场景自检） |
| **镜像 schema 校验（本轮修复）** | **PASS** | 镜像内 `schema_status.available=True`；非法 manifest 会报 `schema_violation` |
| PPO / SAC | **PASS** | PPO 2048 步（eval 28/30/28）、SAC 1000 步（eval 58/62/64）+ checkpoint + 隔离回放 |
| Training lifecycle | **PASS** | 并发限制 / 取消 / 训练中重启→`interrupted` / 僵尸 trainer 回收 / 持久化 42 条 |
| Session cleanup / restart | **PASS** | 10 次创建销毁无累积；优雅停止 6 s；重启后 healthy；`data/runs/` 未删（45 条 / 5.1 MB） |
| Session inventory | **PASS（本轮新增）** | `GET /api/sessions` 只读、不刷新 `last_seen`、无 token/路径/trace |
| CI (GitHub Actions) | **PASS** | [run 44285265993](https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44285265993)：`junit: 93 tests, 0 failures, 0 errors, 0 skipped`、`strict suite OK`、`image manifest schema OK`、`3/3 manifests valid`、`MJPEG framing OK: 54 boundaries`、`18/18 environments passed` |
| Host 其他业务容器 | **PASS（未受影响）** | 27 个容器数量不变；8000 端口未触碰；控制台固定 8010 |
| Long-run stability | **NOT_RUN** | 未获授权 |
| Third-party LAN **device** | **NOT_RUN** | 无可用设备（以 ffmpeg/OpenCV 替代） |
| Convergence | **NOT_RUN** | 需授权与算力预算 |

## 本轮核心结论

1. **渲染开关曾被静默丢弃**：`subscribe/unsubscribe` 在锁内改计数、锁外下发渲染命令，
   交错可导致「无人观看仍在渲染」或「有人观看却冻结」，队列满时开关直接丢失。
   实测复现（`race-before.log`）后改为共享 `multiprocessing.Event`（与计数同锁写入、worker 每循环重读），
   旧命令显式忽略，已关闭/已死会话不可被复活。
2. **CI 会吞掉失败**：严格 step 无 pipefail 且用 `"passed"` 字符串判定。改为
   `set -euo pipefail` + 超时 + JUnit XML + 结构化门禁（0 failed / 0 errors / 0 skipped + 必测项）。
   自检证明：故意失败让管道 rc=1、故意 skip 让 pytest rc=0 但门禁 rc=1、收集错误 rc=2、超时 rc=124。
3. **Handoff 不可审计**：轻量档计数被记成完整镜像非严格的数字；文档提交被当成"代码 tip"。
   新增 `scripts/handoff_metadata.py` 机械推导五个 SHA，协议写明三档测试环境，历史记录以追加修正记录更正。
4. **部署镜像根本没带 `schemas/`**：manifest 校验静默关闭而 API 仍报 "0 problem(s)"；
   CI 也从未在"不挂载仓库"的前提下验证镜像内容。已修（`.dockerignore` + `COPY schemas`），
   并新增镜像内容检查 step 与 `schema_status()` 可观测性。
5. **CI 抓到的真实缺陷（值得保留的做法）**：`5cf87de` 的 CI 失败源于
   `actions/checkout` 单 ref 导致 `origin/main` 不存在；已前向修复并增加两条测试覆盖回退与空区间。

## Completed Work

1. **P1a 订阅竞态（MJC-P1-201）**：共享事件 + 每循环重读 + 旧命令忽略 + 死会话不可复活。
2. **P1b CI 退出码（MJC-P1-202）**：结构化门禁脚本 + 6 场景自检 + 门禁自身的单元测试。
3. **P2 Handoff 可审计（MJC-P3-203）**：五 SHA 工具、档位约定、历史记录追加修正。
4. **P3 会话清单（MJC-P3-107）**：`GET /api/sessions`（只读、不续命、无敏感字段）。
5. **MJC-P3-110（新）**：镜像发布 `schemas/`；`schema_status()` 可观测；缓存按路径失效。
6. **MJC-P3-211（新）**：E2E 判定改为检验服务端行为；E2E 自行清理会话，避免槽位被占满。
7. 全量回归：18 环境、L1、浏览器、MJPEG（含第三方解码）、训练、生命周期、L5、CPU 回落。

## Open Issues

| ID | 级别 | 状态 | 摘要 |
|---|---|---|---|
| MJC-P1-201 | P1 | **FIXED** | 订阅/退订竞态静默丢失渲染开关 |
| MJC-P1-202 | P1 | **FIXED** | CI 吞掉测试失败 + 字符串判定 |
| MJC-P3-203 | P3 | **FIXED** | Handoff 测试计数错档、代码 tip 与文档提交混淆 |
| MJC-P3-107 | P3 | **FIXED** | 缺会话枚举/清理接口（本轮补齐，回归时真实踩到槽位耗尽） |
| MJC-P3-110 | P3 | **FIXED** | 镜像缺 `schemas/`，运行时 manifest 校验静默失效 |
| MJC-P3-211 | P3 | **FIXED（判定侧）** | 客户端取消创建可能留下孤儿会话；缓解=清单接口，创建路径未改 → 见 NS-2 |
| MJC-P3-212 | P3 | OPEN（仅记录） | `session_stream` 访问私有 `session._closed`，宜改公开谓词 |
| MJC-P3-106 | P3 | OPEN（仅记录） | uvicorn 默认线程池按需扩张 |
| MJC-P3-108 | P3 | OPEN（仅记录） | `data/runs/` 无保留策略（45 条 / 5.1 MB） |
| MJC-P3-109 | P3 | OPEN（仅记录） | trainer 线程数无默认上限（无实测依据不引入） |

## Blockers

- 无阻塞主流程的 P0/P1 缺陷。
- 未执行项均为「未获授权」或「无可用设备」。

## Files Changed

```text
app/sessions.py                 render_requested 共享 Event；计数与状态同锁；is_active/info/list
app/worker.py                   事件为唯一真值；旧 render 命令忽略
app/main.py                     GET /api/sessions；流端点 409；catalog schema 字段；lifespan 告警
app/catalog.py                  schema_status()；validator 缓存按路径失效
Dockerfile / .dockerignore      schemas/ 随镜像发布
scripts/check_pytest_report.py  新增（CI 结构化门禁）
scripts/handoff_metadata.py     新增（五 SHA + base 回退）
tests/test_sessions.py, test_worker.py, test_api.py, test_catalog.py, test_integration.py
tests/test_ci_report_check.py, test_handoff_metadata.py     新增
.github/workflows/ci.yml        pipefail + timeout + JUnit + 镜像内容检查 + fetch-depth: 0
docs/handoff/README.md, docs/handoff/runs/**, docs/verification/2026-11-18-concurrency-and-ci-gate.md
README.md, docs/runbooks/ubuntu-deployment.md, docs/architecture/system-overview.md
```

## Evidence

本机证据目录（未提交）：`.artifacts/runs/20261118-085244-8f3e435/`
关键文件：`race-before.log` / `race-after.log`（竞态复现与收敛）、`race-tests-round3.log`（37 项并发单测）、
`cpu-A-idle.csv` / `cpu-B-streaming.csv` / `cpu-C-after.csv`（0.1% / 169.5% / 1.6%）、
`ci-gate-verification.log`（门禁 6 场景）、`mjc-p3-110-before.log`（镜像 schema 修复前后）、
`abandoned-sessions.log`（槽位耗尽真实案例）、`browser-e2e-repeat-summary.log`（6 次确定性）、
`third-party-mjpeg-round3.log`、`pytest-round3.log`、`l1-round3.log`、`smoke-round3.log`、
`training-smoke-round3.log`、`l4b-round3.log`、`l5-round3.log`、`frozen-verification.log`、
`deploy-round3-*.log`、`test-count-matrix.log`。

仓库内只保留脱敏摘要（`docs/verification/2026-11-18-concurrency-and-ci-gate.md` 与本目录）。

## Remaining Risks

1. 资源与 CPU 结论均为**有界窗口**（10–12 s 采样）；**未做小时级驻留**，长稳结论不可外推。
2. 客户端取消创建可能留下孤儿会话（最多占满 `MAX_VIEWERS=3`），只能靠空闲回收或人工用
   `GET /api/sessions` 清理；未修改创建路径（见 `next-steps.md` NS-2）。
3. 渲染状态仍不在 UI 展示，排障需 `GET /api/sessions` 或日志（见 NS-1）。
4. `GET /api/sessions` 未做分页/限流（会话上限仅 3，风险低）。
5. E2E 的"看得到 MJPEG 中止"依赖浏览器上报，已改为服务端行为判定；若未来出现
   `ERR_INCOMPLETE_CHUNKED_ENCODING` 等非取消类失败，判定会立刻失败（这是有意的）。
6. 镜像内容检查目前只覆盖 `schemas/` 与 manifest（见 NS-3）。

## Exact Next Steps

1. NS-1：前端展示会话/渲染状态（可观测性，免授权）。
2. NS-2：消除"取消创建"产生的孤儿会话（幂等键或短窗回收，需实测）。
3. NS-3：把镜像内容检查扩展为清单比对（含 `.dockerignore` 反查）。
4. NS-4：收敛 uvicorn 线程池（专用单线程 executor）。
5. 获授权后执行 NS-5（≥2 小时稳定性）、NS-6（真机）、NS-7（收敛性）。

## Resume Instructions

```bash
cd /home/ubuntu/codes/MuJoCo-Environment-Console
git fetch origin --prune && git log --oneline -12
cat AGENTS.md && cat docs/handoff/latest.md
python scripts/handoff_metadata.py --ci-run-id 44285265993   # 重新导出五个 SHA
ls docs/handoff/runs/
```

- **部署端口继续用 8010**；不要动 8000 上属于其他项目的服务；同机另有 27 个业务容器。
- 不要 `docker compose down -v` / `docker system prune`；不要删 `data/runs/`。
- 跑完整测试（必须 0 skipped；镜像里没有 git，需要先装）：
  ```bash
  docker run --rm --user 0:0 -e HOME=/tmp -e CONSOLE_TEST_REQUIRE_PHYSICS=1 \
    -v "$PWD":/work -w /work mujoco-environment-console:local \
    sh -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && \
           apt-get install -y -qq --no-install-recommends git && \
           git config --global --add safe.directory /work && \
           pip install --quiet httpx pytest jsonschema && \
           python -m pytest -q -rs -p no:cacheprovider'
  ```
- 复现竞态/门禁/CPU：`.artifacts/race_reproduce.py`、`.artifacts/ci_gate_verification.sh`、
  `python3 .artifacts/sampler.py mujoco-console <秒> 2 <标签> [csv]`。
- 跑浏览器 E2E 前先确认 `GET /api/sessions` 为空，否则 `MAX_VIEWERS=3` 会被占满而超时。

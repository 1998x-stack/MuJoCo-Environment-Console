# Run 20261118-085244-8f3e435 · 摘要（第三轮）

## 一句话

修掉了一个会**静默丢失渲染开关**的订阅竞态（`subscribe/unsubscribe` 与命令队列不同步），
修掉了 CI **用 `tee` 吞掉 pytest 失败**、并用 `"passed"` 字符串判定的问题，
并在验证过程中发现部署镜像**根本没有带 `schemas/`、导致 manifest 校验静默关闭**的真实缺陷。

## 版本标注（五个 SHA 必须分开）

| 字段 | 值 |
|---|---|
| `base_sha` | `8f3e435816572c0db5fabc4880095ca47fc0412a`（第二轮文档收尾；`origin/main` 仍为 `f64bc8f`） |
| `code_sha` | `5cf87de627635ff985187dbc1d2b9f216389d398`（最后一个改动 `app/`/`scripts/`/`tests/`/`.github/` 的提交） |
| `pr_head_sha` | `11466c63c73ae09f58bb7cb40bae9c2f70c0c4ed`（本轮文档提交；其后仅 docs，代码状态同 `validated_sha`） |
| `validated_sha` | `5cf87de`（本文件所有结论对应的代码状态） |
| `ci_run_id` | `44285265993`（on `e042d66`，**success**） |

本轮 `pr_head_sha == code_sha`，不存在第二轮那种「文档提交被误标为代码 tip」的问题。
复现命令：`python scripts/handoff_metadata.py --ci-run-id <id>`。

## 做了什么

1. **P1a 订阅竞态（MJC-P1-201，FIXED）**：渲染状态改由共享 `multiprocessing.Event` 承载，
   与订阅计数在同一把锁内写入；worker 每循环重读，**丢一次也会自动收敛**。
   旧的 `render` 命令被显式忽略，防止队列残留下达的命令与事件打架。
2. **P1b CI 退出码（MJC-P1-202，FIXED）**：`set -euo pipefail` + 超时 + JUnit XML
   + `scripts/check_pytest_report.py` 结构化判定（0 failed / 0 errors / 0 skipped
   + 物理集成测试必须真的跑过）。失败仍保留日志尾部。
3. **P2 Handoff 可审计性（MJC-P3-203，FIXED）**：新增 `scripts/handoff_metadata.py` 机械推导
   五个 SHA；修正第二轮「54 passed, 1 skipped 被标为轻量 job」与「8153590 被标为代码 tip」
   两处错误（追加式修正记录）。
4. **P3 会话清单接口（MJC-P3-107，FIXED）**：新增只读 `GET /api/sessions`。
5. **MJC-P3-110（新发现，FIXED，P3）**：镜像缺 `schemas/` → 运行时 manifest 校验静默失效。
6. 回归中另发现 **MJC-P3-211（E2E 判定依赖浏览器上报中止，偶发误报）**，改为断言服务端行为。

## 关键实测数字

| 项 | 结果 | 证据 |
|---|---|---|
| 订阅风暴 8 线程 × 400 次 | 不变量违反 **0**；订阅→True / 退订→False 收敛；队列满 → **DELIVERED** | `race-after.log` |
| 修复前同脚本 | A 渲染泄漏、B 流冻结、C 开关丢失 | `race-before.log` |
| 容器 CPU（无会话） | **0.1%** | `cpu-A-idle.csv` |
| 容器 CPU（1 订阅者流式） | **169.5%**（峰值 173.1%） | `cpu-B-streaming.csv` |
| 容器 CPU（断开后、会话仍活） | **1.6%**（冻结构建复测 1.7%） | `cpu-C-after.csv` |
| 严格套件（部署镜像内 + git） | **91 passed, 0 skipped** | `pytest-round3.log` |
| 完整镜像非严格 | 90 passed, 1 skipped（守门测试按设计 skip） | 同上 |
| 轻量（CI job 1） | 86 passed, 5 skipped | 同上 |
| 18 环境 reset/step/render | **18/18** | `smoke-round3.log` |
| L1 API（含新端点） | **0 失败** | `l1-round3.log` |
| 浏览器主流程 | **31/31**（连续 6 次全绿，另 1 次冻结构建） | `browser-e2e-repeat-summary.log` |
| 浏览器：新环境 + 回放 | **18/18** | `e2e-frozen/replay.log` |
| MJPEG 分帧（RFC 2046） | **212 分片 / 211 解码帧 / literal-CRLF 0** | `third-party-mjpeg-round3.log` |
| ffmpeg（文件 / 实时 HTTP） | 60 帧 640×480 / 60 帧 @12fps，无 boundary 错误 | 同上 |
| OpenCV | 60 帧 640×480 | 同上 |
| PPO / SAC | 2048 步（eval 28/30/28）、1000 步（eval 58/62/64）+ checkpoint + 隔离回放 | `training-smoke-round3.log` |
| 训练生命周期 | 0 失败（并发限制 / 取消 / 训练中重启→interrupted / 僵尸 trainer 回收 / 持久化 42 条） | `l4b-round3.log` |
| L5 稳定性 | 0 失败（10 次创建销毁无累积 / 3 viewer / 优雅停止 6s / 重启 healthy） | `l5-round3.log` |
| CI 门禁自检 | 6 个场景：故意失败 rc=1、故意 skip rc=1、语法错误 rc=2、超时 rc=124、正常 rc=0 | `ci-gate-verification.log` |

## 未执行 / 阻塞

- 小时级稳定性（NS-5）、满负载压力、收敛性（NS-7）：**NOT_RUN**（无授权，且会影响同机 27 个业务容器）。
- 真实第三方设备（手机/笔记本）局域网验收：**NOT_RUN**（无设备；以 ffmpeg/OpenCV 作为第三方客户端替代）。
- Menagerie 导入脚本：**NOT_RUN**（GB 级克隆）。

## 未修但已记录

- **MJC-P3-106**：uvicorn 默认线程池按需扩张（本轮未测到新增证据，保持记录）。
- **MJC-P3-108**：`data/runs/` 无保留策略（本轮 42 条 / 4.8 MB）。
- **MJC-P3-109**：trainer 线程数无默认上限（无实测依据不引入）。
- **MJC-P3-211**（新）：客户端在中途取消的 `POST /api/sessions` 可能留下 UI 不知道 id 的
  孤儿会话，占用 viewer 槽位直到空闲回收；本轮的缓解手段是新增的 `GET /api/sessions`
  可枚举并停止它，未修改创建路径本身。
- **MJC-P3-212**（新，仅记录）：`session_stream` 中 `session._closed` 属私有访问，
  宜改为公开谓词（本轮未改，避免与竞态修复混在一起）。

## CI 结果（回填）

| run | head | 结果 | 说明 |
|---|---|---|---|
| 44284580092 | `5cf87de` | **failure** | CI 真实抓到：`scripts/handoff_metadata.py` 假定 `origin/main` 存在，而 `actions/checkout` 只取单个 ref。已在 `e042d66` 前向修复（回退到根提交并标注 `base_ref_resolved: false`）。 |
| 44285265993 | `e042d66` | **success** | 24 steps 全绿；`junit: 93 tests, 0 failures, 0 errors, 0 skipped`、`strict suite OK: 93 passed`、`image manifest schema OK: /app/schemas/environment.schema.json`、`3/3 manifests valid`、`MJPEG framing OK: 54 boundaries`、`18/18 environments passed`；轻量 job 88 passed / 5 skipped。 |

本文件之后仅追加 `docs/` 提交，代码状态与 `validated_sha = e042d66` 相同。

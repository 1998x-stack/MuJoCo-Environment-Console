# 验证报告 · 订阅并发可靠性、CI 退出码与会话清单（2026-11-18，第三轮）

本报告是脱敏摘要。原始日志、截图、CSV 与归档位于 `.artifacts/runs/20261118-085244-8f3e435/`
（未提交）。所有结论对应 `validated_sha = e042d66`；`code_sha`/`validated_sha`/`ci_run_id`
的区分规则见 `docs/handoff/README.md`。

## 1. 订阅/退订竞态：从复现到收敛

### 1.1 复现（修复前）

用假 `multiprocessing` context 强制交错（`.artifacts/race_reproduce.py`）：

| 场景 | 预期 | 实测 |
|---|---|---|
| A：`subscribe()` 判定开启、退订先落地、开启最后落地 | 渲染应关闭 | **`subscribers=0`，最后一次渲染请求 `True`（渲染泄漏）** |
| B：`unsubscribe()` 判定关闭、订阅先落地、关闭最后落地 | 渲染应开启 | **`subscribers=1`，最后一次请求 `False`（流冻结）** |
| C：命令队列已满（len=16） | 开关不应丢失 | **`requested_render=False`（开关丢失）** |

机制：计数在锁内、渲染开关在锁外经 `commands`（`maxsize=16`）下发，且 `put_nowait` 的
`ValueError` 被吞掉。

### 1.2 修复

共享 `multiprocessing.Event`：与订阅计数在**同一把锁内** set/clear；worker 每循环重读并写入
`runtime.render`；旧 `render` 命令显式忽略；`subscribe()` 对已关闭/已死 worker 为 no-op。

### 1.3 修复后验证

| 检查 | 结果 |
|---|---|
| 8 线程 × 400 次订阅/退订风暴 | 不变量违反 **0**，末态 `subscribers=10 / render_requested=True` |
| 收敛（全部订阅 → 全部退订） | `True` → `False` |
| 队列满（len=16） | **DELIVERED**（不再丢失） |
| 并发/worker 单测 | **37 passed**（同时断开、快速重连、关闭竞态、死 worker、启动失败） |
| 真实部署端到端 | 流中 `subscribers=1 / render_requested=True`；断开后 `0 / False` |

### 1.4 有界 CPU 回落（cgroup v2 `cpu.stat` 采样，窗口 12 s）

| 窗口 | 容器 CPU（core-percent，100 = 1 核） | pids |
|---|---|---|
| 无会话 | **0.1%** | 8 |
| 1 个订阅者流式观看 | **169.5%**（峰值 173.1%） | 19 |
| 客户端断开、会话仍存活 | **1.6%** | 19 |

冻结构建复测：断开后 **1.7%**，会话 `state=ready` 且物理继续步进。
即"最后一个订阅者离开后渲染停止、CPU 回落"在真实部署上成立（约 106× 回落）。

## 2. CI 退出码：从"可能假绿"到结构化门禁

### 2.1 缺陷

严格 step 为 `docker run … pytest -q … | tee /tmp/full-pytest.log`，GitHub 默认 bash 无 pipefail，
于是管道状态取决于 `tee`；随后又用 `if 'passed' not in summary` 判定，无法区分
`55 passed, 0 skipped` 与 `52 passed, 3 skipped`。

### 2.2 修复

`set -euo pipefail` + `timeout 900` + `--junit-xml` + `scripts/check_pytest_report.py`
（要求 0 failed / 0 errors / 0 skipped、至少收集到测试、且 5 个物理集成测试确实执行过）。
失败时打印测试日志尾部。`tests/test_ci_report_check.py`（11 项）用合成 JUnit 覆盖门禁自身的各分支。

### 2.3 自检（逐条复刻 CI 命令）

| 场景 | 管道退出码 | 门禁退出码 | 判定 |
|---|---|---|---|
| 机制对照：无 pipefail 的 `false \| tee` | **0** | — | 失败被吞（缺陷证据） |
| 机制对照：有 pipefail | **1** | — | 失败传播 |
| 正常套件 | 0 | 0 | `strict suite OK: 93 passed, 0 failed, 0 errors, 0 skipped` |
| 注入失败测试 | **1** | **1** | 拒绝，并打印失败用例与日志尾部 |
| 注入 skip 测试 | 0 | **1** | 拒绝（pytest 本身不因 skip 失败——结构化判定的必要性） |
| 注入语法错误（收集失败） | **2** | 1 | 拒绝 |
| 注入 120 s 慢测试 + `timeout 15` | **124** | — | 拒绝 |
| 恢复正常 | 0 | 0 | 通过 |

CI 实跑（run `44285265993`）输出：`junit: 93 tests, 0 failures, 0 errors, 0 skipped`、
`strict suite OK: 93 passed, 0 failed, 0 errors, 0 skipped`。

## 3. 会话清单接口（只读）

`GET /api/sessions` 返回每会话公开投影（id / env_id / subscribers / render_requested / alive /
state 计数 / created / last_seen / idle_seconds / 视口尺寸）+ `limit` / `idle_seconds` / `viewer`，
**不含** traceback、路径、token；**不刷新** `last_seen`，因此轮询不能给被遗弃会话续命。

| 检查 | 结果 |
|---|---|
| 未登录 / 登出后访问 | 401 |
| 字段集合与泄漏检查 | 无 `trace`/`path`/`token`/`cookie`/`password` 键 |
| 列表不刷新空闲时间 | `idle_seconds` 不因轮询减小或重置 |
| 流中状态 | `subscribers=1 render_requested=True` |
| 断开后状态 | `subscribers=0 render_requested=False` |
| 实际用途验证 | 回归中槽位被 3 个遗留会话占满（新建返回 400），用该接口逐个停止后恢复 |

## 4. 部署镜像内容：manifest schema 曾缺失

发现问题：容器内 `python scripts/validate_manifests.py` 抛 `FileNotFoundError`。

| | 修复前 | 修复后 |
|---|---|---|
| 镜像内 `/app/schemas` | **不存在** | 存在 `environment.schema.json` |
| `catalog.schema_status()` | `available: False`（validator None） | `available: True` |
| 镜像内 `validate_manifests.py` | exit 1（FileNotFoundError） | exit 0：`3/3 valid`、`18 environments`、`0 problem(s)` |
| 非法 manifest（`"name": 7`） | `problems: []`（静默通过） | `schema_violation: name: 7 is not of type 'string'` |

根因：`schemas/` 既在 `.dockerignore` 中又被漏 `COPY`；只补 `COPY` 会因构建上下文缺目录而失败
（`failed to compute cache key: "/schemas": not found`）。修复：从 `.dockerignore` 移除 +
`COPY schemas ./schemas`；并把"校验不可用"变为可观测（`schema_status()` + `/api/catalog.schema`
+ 启动告警）；validator 缓存由一次性标志改为按 schema 路径失效。

CI 新增的检查**不挂载仓库**（挂载时 `import app` 指向仓库副本，验不到镜像内容）：
`image manifest schema OK: /app/schemas/environment.schema.json`。

## 5. 回归矩阵（本轮真实执行）

| 项 | 结果 |
|---|---|
| 严格单测（镜像内，`CONSOLE_TEST_REQUIRE_PHYSICS=1`） | **93 passed, 0 skipped** |
| 完整镜像非严格 / 轻量（无 MuJoCo） | 92 passed, 1 skipped / 88 passed, 5 skipped |
| 18 环境 reset/step/render | **18/18** |
| L1 API 断言 | **0 失败** |
| 浏览器主流程 / 新环境+回放 | **31/31**（连续 6 次）/ **18/18** |
| MJPEG 分帧 | 212 分片 / 211 解码帧 / literal-CRLF **0** / 640×480 / 210 帧有变化 |
| ffmpeg（文件 / 实时 HTTP）、OpenCV | 60 帧 640×480 / 60 帧 @12fps / 60 帧 |
| PPO / SAC + checkpoint + 隔离回放 | exit 0；PPO 2048 步 eval 28/30/28；SAC 1000 步 eval 58/62/64 |
| 训练生命周期（并发限制/取消/重启/持久化） | 0 失败；重启后 `interrupted`、僵尸 trainer 已回收、42 条历史 |
| L5（10 次创建销毁、3 viewer、优雅停止、重启） | 0 失败；优雅停止 6 s；空闲 CPU 0.17% |
| Docker 部署 + 健康 | `deploy.sh` exit 0；`Up (healthy)`；`8010->8000/tcp` |
| 同机其他业务容器 | 27 个，未变动；8000 端口未触碰 |
| `data/runs/` | 未删除（45 条 / 5.1 MB） |

## 6. 未执行项

**NOT_RUN**（附原因）：小时级稳定性与满负载压力（未授权，会影响同机 27 个业务容器）；
真实第三方局域网设备验收（无设备，以 ffmpeg/OpenCV 作为第三方客户端替代）；
PPO 收敛性研究（需授权与算力）；Menagerie 导入（GB 级克隆）。

## 7. 本轮自身暴露的两处过程缺陷（已修正并记录）

1. 证据脚本的 heredoc / 引号嵌套导致补丁静默未生效（两次），已改用结构化编辑；
   `l4b_training_lifecycle.sh` 的 f-string 引号错误也一并修正。
2. 浏览器 E2E 的"观察到流出中止"判据不可靠（7 次中 1 次误报；样本为客户端自行取消的
   `POST /api/sessions`）。已改为断言服务端行为（非 `net::ERR_ABORTED` 的请求失败一律判失败），
   并让 E2E 在 teardown 停止自己创建的会话。改后连续 6 次 31/31。

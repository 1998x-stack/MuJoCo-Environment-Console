# 问题清单 · 第三轮（2026-11-18）

每条包含：现象 → 复现 → 根因 → 修复 → 验证证据。`PASS` 只给真实执行过的结果。

---

## MJC-P1-201 · 订阅/退订竞态会静默丢失渲染开关

- **优先级**：P1 · **状态**：FIXED
- **现象**：三个 viewer 场景下 CPU 曲线出现反常——浏览器已断开但渲染仍在跑（白烧一个核），
  或浏览器正在观看却不再出帧（画面冻结）。

### 复现（修复前）

`PYTHONPATH="$PWD" python3 .artifacts/race_reproduce.py`（假 mp context，用 Event 强制交错）：

```text
scenario A - subscribe() decides ON, unsubscribe() lands first, then ON lands last:
  subscribers=0 requested_render=True  landing_order=[False, True] -> INCONSISTENT (render leak)
scenario B - unsubscribe() decides OFF, subscribe() lands first, then OFF lands last:
  subscribers=1 requested_render=False landing_order=[True, False] -> INCONSISTENT (frozen stream)
scenario C - command queue full (len=16):
  requested_render=False -> TOGGLE LOST
RACE REPRODUCED
```

### 根因

`subscribe()`/`unsubscribe()` 在锁内改计数，却**在锁外**通过 `command({'op':'render'})` 下发开关：

1. 计数与开关不是原子对，两个线程交错时最终落地顺序可能与计数相反；
2. 开关走 `commands`（`maxsize=16`），队列满时 `put_nowait` 抛 `ValueError` 被吞掉 → 开关永久丢失，
   状态不再收敛。

### 修复

- 会话创建共享 `multiprocessing.Event`（`render_requested`），**与计数在同一把锁内** set/clear；
- worker 每循环 `runtime.render = bool(render_requested.is_set())`，事件是唯一真值来源，
  丢一次也会在下一轮自愈；
- 旧的 `render` 命令**显式忽略**（返回 `ignored`），避免历史队列项与事件打架；
- 会话已关闭或 worker 已退出时 `subscribe()` 为 no-op（**已关闭的会话不能被复活**）；
- worker 启动失败改为抛 `ValueError`（可诊断的 400），并关闭已创建的队列。

### 验证

| 检查 | 结果 | 证据 |
|---|---|---|
| 风暴 8 线程 × 400 次操作 | 不变量违反 0，末态 `subscribers=10 / render_requested=True` | `race-after.log` |
| 收敛：全部订阅 → 全部退订 | `True` → `False` | 同上 |
| 队列满（len=16） | `DELIVERED`（不再丢失） | 同上 |
| `tests/test_sessions.py`（19 项）与 `tests/test_worker.py`（18 项） | 37 passed | `race-tests-round3.log` |
| 真实部署：边看边断连 | 流中 `subscribers=1 render_requested=True`；断开后 `0 False` | `l1-round3.log` |
| 有界 CPU 回落 | 无会话 0.1% → 订阅中 169.5% → **断开后 1.6%** | `cpu-A/B/C-*.csv` |
| 冻结构建复测 | 断开后 **1.7%**，会话仍 `state=ready` | `frozen-verification.log` |

覆盖的边界：多客户端、同时断开、快速重连、队列满、关闭竞态、worker 已死、启动失败。

---

## MJC-P1-202 · CI 会吞掉测试失败并用字符串判定结果

- **优先级**：P1 · **状态**：FIXED
- **现象**：`.github/workflows/ci.yml` 的严格 step 为
  `docker run … pytest -q … | tee /tmp/full-pytest.log`，而 GitHub 默认 bash **无 pipefail**，
  因此只要 `tee` 成功，整条管道就是 0：**测试失败也能绿**。随后又用
  `if 'passed' not in summary` 判定，无法区分 `55 passed, 0 skipped` 与 `52 passed, 3 skipped`。

### 验证（修复后）

`.artifacts/ci_gate_verification.sh` 逐条复刻 CI 命令：

| 场景 | 结果 |
|---|---|
| 机制对照：`bash -c 'false \| tee /dev/null'` | **rc=0（失败被吞）** |
| 机制对照：`bash -c 'set -o pipefail; false \| tee …'` | **rc=1（失败传播）** |
| 正常套件 | 管道 rc=0，门禁 rc=0，`strict suite OK: 91 passed, 0 failed, 0 errors, 0 skipped` |
| 故意注入失败测试 | 管道 **rc=1**、门禁 rc=1，并打印失败用例与日志尾部 |
| 故意注入 skip 测试 | pytest **rc=0**（pytest 本身不因 skip 失败），门禁 **rc=1** → 这正是必须用结构化判定的原因 |
| 注入语法错误的测试文件（收集失败） | 管道 **rc=2** |
| 注入 120s 慢测试 + `timeout 15` | 管道 **rc=124** |
| 恢复正常 | 管道 rc=0、门禁 rc=0 |

`tests/test_ci_report_check.py`（11 项）用合成 JUnit 报告覆盖：通过 / 失败 / 错误 / 跳过 /
零收集 / 缺必测项 / 报告缺失 / 空报告 / 非法 XML / 失败保留诊断 / 门禁确实接在 workflow 上。
门禁本身无法"悄悄失效"。

---

## MJC-P3-203 · Handoff 无法审计：测试计数错档、代码 tip 与文档提交混淆

- **优先级**：P3 · **状态**：FIXED
- **现象（两处）**：

| 项 | 原记录 | 真值 | 依据 |
|---|---|---|---|
| 轻量档计数 | 「轻量依赖（CI job 1 等价）… 54 passed, 1 skipped」 | 轻量 job 为 **50 passed, 5 skipped**；`54/1` 是**完整镜像非严格**档 | CI run 44257891758 日志、`environment.json.ci_lightweight_unit_tests`、本轮在两种镜像下实测 |
| 版本标注 | `8153590` 被称为「代码 tip」 | 代码 tip 是 `f642f2f`；`8153590`/`8f3e435` 仅改 docs（代码状态相同） | 逐提交 `--name-only` 分类，`scripts/handoff_metadata.py` 可复现 |

### 修复

- 新增 `scripts/handoff_metadata.py`：机械推导 `base_sha` / `code_sha` / `pr_head_sha` /
  `validated_sha` / `ci_run_id`，并显式列出 `code_sha` 之后的纯文档提交；
- `docs/handoff/README.md` 增补：五字段定义与硬性要求（结论只能标注 `code_sha`/`validated_sha`）、
  三档测试环境（轻量 / 完整非严格 / 严格）必须按名引用、历史记录只增不改（错误一律追加修正记录）；
- 第二轮四个文件（`test-matrix.md`、`issues.md`、`changes.md`、`environment.json`）与验证报告
  以**追加修正记录**方式更正，原值保留。

验证：本轮在同一份测试上得到三档 **86/5、90/1、91/0**，并明确标注档位（不再出现"只写数字"）。
`tests/test_handoff_metadata.py`（7 项）在临时 git 仓库中构造 code→docs、docs→code、混合提交等
情形，断言分类与字段取值正确。

---

## MJC-P3-107 · 缺会话枚举/清理接口（本轮补齐）

- **优先级**：P3 · **状态**：FIXED
- **现象**：浏览器关掉后会话仍占用 `MAX_VIEWERS=3` 的槽位，直到空闲回收（默认 900 s）。
  本轮回归时**真实踩到**：连续几次 E2E 留下的 3 个 `gym:Hopper-v5` 会话占满槽位，
  新建会话返回 400，E2E 卡在 `waitForFunction` 超时（证据：`abandoned-sessions.log`）。
- **修复**：新增只读 `GET /api/sessions`，返回公开投影；**不刷新 `last_seen`**（轮询不能续命），
  不含 traceback / 路径 / token。
- **验证**：`l1-round3.log` 中 401（未登录、登出后）、字段集合无泄漏、
  流中 `subscribers=1 render_requested=True`、断开后 `0 False`；`idle_seconds` 不因列表刷新。
  实测用该接口把 3 个遗留会话逐个停止（`abandoned-sessions.log`）。

---

## MJC-P3-110 · 部署镜像未包含 `schemas/`，manifest 校验静默失效（本轮新发现）

- **优先级**：P3 · **状态**：FIXED
- **发现路径**：最终回归时在容器内执行
  `docker compose exec -T console python scripts/validate_manifests.py` → `FileNotFoundError`。

### 证据（修复前，镜像自带 `/app`，无 bind mount）

```text
/app: app data envs requirements*.txt scripts      ← 没有 schemas/
FileNotFoundError: '/app/schemas/environment.schema.json'   (validate_manifests exit=1)
SCHEMA_PATH: /app/schemas/environment.schema.json  exists: False  validator: None
隔离实验：manifest 合法除 name 类型错误 → problems: []        ← 校验静默通过
```

即：**运行时 manifest 校验完全关闭，而 `/api/catalog` 仍报 "0 problem(s)"**——
失败与"干净"不可区分。第二轮声称的 schema 警告在部署容器里实际无效。

### 根因

`schemas/` 同时出现在 `.dockerignore` 与缺失的 `COPY` 中：即使补上 `COPY schemas ./schemas`，
构建也会因上下文缺少该目录而失败（`failed to compute cache key: "/schemas": not found`）。

### 修复

1. `.dockerignore` 移除 `schemas/`；`Dockerfile` 增加 `COPY schemas ./schemas`；
2. `catalog.schema_status()` 返回 `{available, path, reason}`，`/api/catalog` 暴露该字段，
   lifespan 在不可用时打 `WARNING`（可用时 INFO）；
3. validator 缓存改为**按 schema 路径失效**：原来是 `_schema_loaded` 一次性标志，
   一次加载失败会在整个进程内永久关闭校验（这也让测试出现顺序依赖）。

### 验证（修复后）

```text
/app/schemas/environment.schema.json
OK envs/*/manifest.json ×3 → 3/3 manifests valid / 18 environments / 0 problem(s) / PASS  (exit 0)
schema_status: {'available': True, 'path': '/app/schemas/environment.schema.json', 'reason': None}
隔离实验：{'reason': 'schema_violation', 'detail': "name: 7 is not of type 'string'", 'severity': 'warning'}
```

新增回归测试：`tests/test_integration.py::test_the_imported_catalog_copy_has_its_manifest_schema`
（断言被导入的 `app.catalog` 旁边确实有 schema、且 schema 会拒绝非法文档）、
`tests/test_catalog.py::test_the_validator_cache_follows_the_schema_path`、
`tests/test_api.py::test_catalog_reports_whether_schema_validation_is_active`。
CI 新增 step：**不挂载仓库**，直接在镜像内跑 `validate_manifests.py` 与 `schema_status()` 断言
（挂载 `/work` 时 `import app` 指向仓库副本，验不到镜像内容——这是本轮刻意区分的一点）。
CI 已在本地逐字复刻通过：

```text
3/3 manifests valid / 18 environments, 0 problem(s) / PASS   (step1 exit=0)
image manifest schema OK: /app/schemas/environment.schema.json (step2 exit=0)
```

---

## MJC-P3-211 · 浏览器 E2E 的流出中止断言偶发误报（本轮新发现）

- **优先级**：P3 · **状态**：FIXED
- **现象**：`aborts=0 unexpected=1`——7 次运行中出现 1 次。
- **定位**：加插桩后复现并抓到样本：`POST …/api/sessions net::ERR_ABORTED`。
  该轮 teardown 停了 **2** 个会话（其余轮 1 个），说明客户端自行取消的创建请求
  可能留下 UI 不知道 id 的孤儿会话；同时 Chromium 对长连接 MJPEG 响应的取消
  **并不保证上报**，因此原断言（要求"至少观察到一次流出中止"）本身不可靠。
- **修复**（只改判定方式，不放宽服务端要求）：断言改为检验服务端行为——
  **任何非 `net::ERR_ABORTED` 的请求失败都判失败**（`ERR_INCOMPLETE_CHUNKED_ENCODING`、
  `ERR_EMPTY_RESPONSE`、`ERR_CONNECTION_RESET` 都意味着响应被服务端打断），
  并单独断言"每个失败请求都是客户端取消"；失败样本写入报告 JSON。
- **验证**：改后连续 **6 次 31/31、0 failed**，`nonAbortFailures=0`，且运行结束无遗留会话
  （E2E 现在会在 teardown 主动停止自己创建的会话，避免占满槽位）。
- **遗留**：孤儿会话本身未修（记录为 MJC-P3-211 的缓解项），缓解手段是新增的
  `GET /api/sessions`；`SESSION_IDLE_SECONDS` 默认 900 s 的取舍见 `next-steps.md`。

---

## 本轮确认无回归的项

| 项 | 结果 |
|---|---|
| 按需渲染（第二轮 MJC-P1-101） | 无会话 0.1%、断开后 1.6–1.7%（会话仍存活并继续步进） |
| MJPEG 分帧（第一轮 MJC-P2-001） | 212 分片 / 211 解码帧 / literal-CRLF 0 / 640×480 / 210 帧有变化 |
| `training_smoke_test.py` 订阅契约（第二轮 MJC-P1-102） | 训练冒烟 exit 0，checkpoint 与隔离回放通过（PPO/SAC） |
| 18 环境、L1、生命周期、L5 | 全部 0 失败 |
| 同机其他业务容器 | 27 个容器数量不变；8000 端口未触碰；控制台仍为 8010 |

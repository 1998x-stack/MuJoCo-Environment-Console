# 变更清单 · 第二轮（2026-11-18）

- `BASE_SHA`：`e422870481d68dd20feeb4e36538ee57306b97e8`（PR #1 HEAD）
- 分支：`agent/local-deploy-20261118-1058`（继续 PR #1）
- `final_sha`（本轮代码 tip）：`8153590d51da59a81f9fb0ffaa84939d0fcbc0f4`
- PR：https://github.com/1998x-stack/MuJoCo-Environment-Console/pull/1
- CI：https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44257891758（success，2m37s）

## 1. 代码变更

### `app/worker.py`（核心）

```diff
+def apply_process_limits(environ=None):
+    """Cap viewer thread pools. Must run before numpy/MuJoCo create their pools."""
+    env = os.environ if environ is None else environ
+    defaults = {'VIEWER_RENDER_THREADS': int(DEFAULT_RENDER_THREADS),
+                'VIEWER_BLAS_THREADS': int(DEFAULT_BLAS_THREADS)}
+    resolved = {k: _positive_int(env.get(k), v) for k, v in defaults.items()}
+    for target, source in VIEWER_THREAD_ENV.items():
+        env[target] = str(resolved[source])
+    return {'render_threads': ..., 'blas_threads': ...}
+
+class ViewerRuntime:
+    """Mutable viewer state. Rendering is opt-in: it stays off until a subscriber arrives."""
+    def apply(self, command): ...          # runtime = 'stop' | 'changed' | 'reset' | 'policy' | 'ignored'
+
 def run_worker(descriptor, commands, frames, states, fps, width, height):
-        os.environ.setdefault('MUJOCO_GL', 'osmesa')
+        os.environ.setdefault('MUJOCO_GL', 'osmesa')
+        os.environ.setdefault('PYOPENGL_PLATFORM', 'osmesa')
+        limits = apply_process_limits()
...
-            try:
-                rendered = env.render()            # 无条件渲染
-                ...
+            # Rendering is skipped entirely while nobody subscribes: that avoids creating the
+            # rasteriser thread pool at all, and physics/state reporting keep running.
+            if runtime.render:
+                try:
+                    rendered = env.render()
+                    ...
```

- 常量：`DEFAULT_RENDER_THREADS = '2'`、`DEFAULT_BLAS_THREADS = '1'`（附实测依据表）。
- 状态新增 `render` 字段，`viewer_limits` 在 ready 消息中回传。

### `app/sessions.py`

```diff
+def viewer_config(fps=None, width=None, height=None):   # 环境变量 / 显式值，带范围钳制与回退
+class ViewerSession:
+    """... Frames are only produced while at least one consumer is *subscribed* ..."""
+    def subscribe(self):     # 0->1 时下发 {'op':'render','value':True}
+    def unsubscribe(self):   # 1->0 时下发 {'op':'render','value':False}；worker 已退出不报错
+    def _set_render(self, value):
+    def status(self):        # 新增 subscribers / render / fps / width / height
+    def __init__(..., ctx=None)   # 可注入上下文，便于无子进程测试
 class SessionManager:
-    def __init__(self, limit=4, idle_seconds=900):
+    def __init__(self, limit=4, idle_seconds=900, fps=None, width=None, height=None):
+        self.viewer = viewer_config(fps, width, height)
-            session = ViewerSession(descriptor)
+            session = ViewerSession(descriptor, **self.viewer)
```

### `app/main.py`

```diff
+from app.catalog import get_env, scan
+import logging
+logger = logging.getLogger('mujoco-console')
 manager = SessionManager(
     limit=int(os.getenv('MAX_VIEWERS', '3')),
     idle_seconds=int(os.getenv('SESSION_IDLE_SECONDS', '900')),
+    fps=os.getenv('VIEWER_FPS'),
+    width=os.getenv('VIEWER_WIDTH'),
+    height=os.getenv('VIEWER_HEIGHT'),
 )
+    # lifespan：把环境目录问题写成 warning，但不阻止启动
 @app.get('/api/catalog')
-def catalog(...): return {'environments': discover()}
+def catalog(...):
+    environments, problems = scan()
+    return {'environments': environments, 'problems': problems}
     async def gen():
+        session.subscribe()
+        try:
+            while True: ...
+        finally:
+            session.unsubscribe()
```

### `app/catalog.py`（重写发现流程）

`discover()` → `scan()` 返回 `(entries, problems)`；新增 `_read_manifest`、`_scan_mjcf`、
`_scan_gym`、`_schema_warnings`、`_validator`；每个问题带 `severity`/`reason`/`detail`；
`except Exception` 兜底并记录 `internal_error`，绝不因单个目录中断发现。

### `app/jobs.py`

`exit_reason(code)`：137/SIGKILL 明确提示「容器内存上限 / 外部 kill / 宿主 OOM」，
143/SIGTERM、其他负信号、非零退出码分别处理。

### `app/static/app.js` + `index.html`

`renderProblems()`：在环境目录下方显示 `problems` 摘要（`textContent`，无 XSS 风险）；
`refreshCatalog` 改读 `{environments, problems}`。

## 2. 依赖与配置

| 文件 | 变更 |
|---|---|
| `requirements.txt` | 新增 `jsonschema>=4.20,<5`（运行时 schema 校验，导入失败自动降级） |
| `compose.yaml` | 新增可选 `cpus: ${CONSOLE_CPU_LIMIT:-0}`、`mem_limit: ${CONSOLE_MEM_LIMIT:-0}`（0/未设 = 不限制） |
| `.env.example` | 新增 `VIEWER_FPS` / `VIEWER_WIDTH` / `VIEWER_HEIGHT` / `VIEWER_RENDER_THREADS` / `VIEWER_BLAS_THREADS` 与可选上限，附实测说明 |
| `scripts/training_smoke_test.py` | 读帧前 `subscribe()`，`finally` 中 `unsubscribe()`（MJC-P1-102） |
| `scripts/validate_manifests.py` | 改为同时做 schema 校验与 `scan()` 诊断，任何 problem 即失败 |

## 3. 测试变更

| 文件 | 新增 |
|---|---|
| `tests/test_worker.py`（新） | render 默认关闭、`ViewerRuntime` 命令语义、线程预算默认/覆盖/非法值、默认值 pin |
| `tests/test_sessions.py` | `viewer_config` 解析与钳制、`SessionManager` 传参、**订阅计数驱动渲染**、worker 退出后 unsubscribe 不报错、status 暴露设置 |
| `tests/test_api.py` | `session_stream` 订阅/取消订阅、`/api/catalog` 含 `problems`、坏环境时控制台仍可用 |
| `tests/test_catalog.py` | 11 种坏目录形态的 `reason` 断言、schema 违规为 warning、缺失 env root |
| `tests/test_integration.py` | `require()` 严格模式：`CONSOLE_TEST_REQUIRE_PHYSICS=1` 时依赖缺失 fail 而非 skip |

## 4. CI 变更（`.github/workflows/ci.yml`）

1. 新增 step「Run the full test suite inside the deployed image」：在部署镜像内跑完整 pytest，
   设置 `CONSOLE_TEST_REQUIRE_PHYSICS=1`，并用 python 断言 `skipped == 0`（防止集成测试再次被静默跳过）。
2. 依赖安装已含 `jsonschema`（上一轮加入），本轮 `validate_manifests.py` 用它做运行时同源校验。

## 5. 文档变更

| 文件 | 说明 |
|---|---|
| `AGENTS.md` | 按需渲染契约、viewer 线程预算与默认值 pin、严格 pytest 命令、边界与 DoD 更新 |
| `docs/architecture/system-overview.md` | 新增「可诊断的环境导入」「按需渲染（重要契约）」，第 8 节重写为实测成本拆解 + 线程归属 + 前后对照 |
| `docs/runbooks/ubuntu-deployment.md` | 新增 6.1 资源调优表；故障排查新增 viewer CPU / 无画面 / 环境不可见 / OOM 条目 |
| `docs/verification/2026-11-18-viewer-resource-optimisation.md` | **新增**：本轮完整验证报告 |
| `docs/handoff/latest.md` | 覆盖更新为第二轮入口 |
| `docs/handoff/runs/20261118-053523-e422870/*` | **新增**：本轮 run 记录（6 个文件） |
| `README.md` | 配置表新增 viewer/上限变量；功能说明补充按需渲染与实测数据；manifest 诊断说明 |

## 6. 明确未做的事

- 未升级任何既有依赖版本（MuJoCo/Gymnasium/Robotics/SB3/PyTorch 保持不变），仅新增 `jsonschema`。
- 未删除或改写任何 `data/runs/` 记录（本轮新增 7 条验证用 run，共 23 条）。
- 未执行 `docker compose down -v`、`docker system prune`、`rm -rf data`。
- 未停止、重启或删除其他 27 个业务容器；未使用宿主机 8000 端口。
- 未做满负载或小时级压测（未获授权）；未做收敛性验证。
- 未设置未经实测的 trainer 线程默认值。
- 未强制推送、未直接推送 `main`、未合并 PR。
- 未提交 `.env`、密码、Cookie、Token、原始日志或截图。

## 7. 提交记录

| # | Commit | 说明 |
|---|---|---|
| 1 | `10206e4` | `perf(viewer): render on demand and cap the rasteriser thread pools` |
| 2 | `6a7735f` | `feat: make viewer fps, resolution and container limits configurable` |
| 3 | `02243dc` | `feat(catalog): report diagnosable environment problems instead of skipping silently` |
| 4 | `ec00453` | `fix(jobs): explain SIGKILL/OOM trainer exits` |
| 5 | `66685a6` | `test: cover subscriber-driven rendering, thread budgets and catalog diagnostics` |
| 6 | `f642f2f` | `ci: run the full suite in the deployed image and forbid skips` |
| 7 | `8153590` | `docs: record the viewer resource investigation, runbook and handoff` |
| 8 | 本次提交 | `docs: backfill the round-2 CI run and final SHA` |

代码 tip（即 `code_sha`）：`f642f2fa5b6bbe4cdc97fc07d73c68cefbd5e2d1`（`f642f2f`）。

> **修正记录（2026-11-18 第三轮追加）**：原文将 `8153590` 称为「代码 tip」，但该提交只改 `docs/`；
> 最后一个改动代码的提交是 `f642f2f`，其后两个提交（`8153590`、`8f3e435`）均为纯文档，
> 代码状态与 `f642f2f` 完全一致，因此两个 CI run 验证的是同一份代码。
> 判定依据：`git show --name-only` 逐提交文件分类（`scripts/handoff_metadata.py` 可复现）。

CI 日志确认：`strict suite OK: 55 passed`（0 skipped）、
`3/3 manifests valid`、`discovery: 18 environments (3 custom), 0 problem(s)`、
`MJPEG framing OK: 57 CRLF-delimited boundaries`、`18/18 environments passed`。

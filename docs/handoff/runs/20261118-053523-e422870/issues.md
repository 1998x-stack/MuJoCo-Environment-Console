# 问题清单 · 第二轮（2026-11-18）

规则：现象 → 复现 → 证据 → 根因 → 修复/结论 → 回归测试 → 结果。
未修改代码的观察单列在最后。

---

## MJC-P1-101 · 三个 Viewer 占用约 815% CPU（viewer 无条件渲染）

- **优先级**：P1（此前每轮把「3 viewer ≈ 815% CPU」当作已知现象，但从未定位根因）
- **状态**：FIXED

### 现象

3 个 viewer 并发时容器占用约 860% CPU、142 个任务；单 viewer 也约 500%。
浏览器关闭后 CPU **不下降**。

### 复现

```bash
# 真实 API 会话 + 真实 MJPEG 订阅，用容器 cgroup 精确采样
CONSOLE_PORT=8010 bash .artifacts/phase2_viewer_experiment.sh
```

### 证据

`.artifacts/runs/20261118-053523-e422870/phase2-viewer-before.log`：

```text
1-viewer-no-subscriber   cpu_core_percent_mean=512.3  pids=50
1-viewer-with-subscriber cpu_core_percent_mean=499.7  pids=50   （10.48 fps）
1-viewer-after-detach    cpu_core_percent_mean=498.6  pids=50
3-viewers-with-subscribers cpu_core_percent_mean=860.0 pids=142（每个 10.75 fps）
```

组件拆解（`component-bench.log`，`gym:Hopper-v5`，640×480）：

```text
physics_step (no render)   0.12 ms/次    → <1%
render (rgb_array)        ~30 ms 墙钟 / ~490 ms CPU → >99.5%
PIL fromarray              0.18 ms
JPEG encode q72            0.84 ms
policy predict             0.19 ms
renderer 创建后线程 12 → 37（12 个 llvmpipe-0..11 + 1 disk + 其余）
```

### 根因

1. 无 GPU → `MUJOCO_GL=osmesa` → Mesa **llvmpipe CPU 软光栅化**；
2. llvmpipe 默认按核数创建 worker 线程（12 个）且自旋等待；
3. numpy/OpenBLAS 另建 12 个线程（渲染完全用不到）；
4. `run_worker` 每个循环**无条件** `env.render()`，与是否有订阅者无关。

→ 单 worker 39 线程、约 5 核；3 viewer 在 12 核上呈次线性增长（860% 而非 1500%）。

### 修复

`app/worker.py` + `app/sessions.py` + `app/main.py`：

- **按需渲染**：`ViewerSession.subscribe()/unsubscribe()` 引用计数，仅在 0→1 / 1→0 时下发
  `{'op':'render'}`；`session_stream` 的 async generator 在开始时订阅、`finally` 中取消订阅；
  worker 仅在 `runtime.render` 为真时调用 `env.render()`（因此连光栅化器线程池都不会创建）。
- **线程预算**：`apply_process_limits()` 在导入 numpy/MuJoCo 前设置 `LP_NUM_THREADS`（默认 2）
  与 BLAS/OpenMP（默认 1）。

### 回归测试

- 单元：`tests/test_sessions.py::test_render_only_while_subscribed`（订阅计数 + 只在 0→1/1→0 下发指令）、
  `test_unsubscribe_after_worker_exit_is_not_an_error`、
  `tests/test_worker.py`（render 默认关闭、命令语义、线程预算默认值与覆盖值、非法值回退）。
- API：`tests/test_api.py::test_stream_subscribes_then_unsubscribes`（真实走 `session_stream` 生成器，
  断言 subscribe==1、unsubscribe==1、两个分片）。
- 端到端：`.artifacts/render_toggle_check.sh`（真实 API + 真实订阅：无人订阅不出帧但步数增长；
  0→1 打开渲染；两个订阅者；1→0 关闭渲染）。

### 结果（前后对照）

| 场景 | 前 | 后 | 变化 |
|---|---|---|---|
| 1 viewer，无人订阅 | 512.3% | 1.5% | −99.7% |
| 1 viewer，正在观看 | 499.7% | 159.4% | −68.1% |
| 1 viewer，断开后 | 498.6% | 1.6% | −99.7% |
| 3 viewers 同时观看 | 860.0% | 549.3% | −36.1% |
| 容器任务数（3 viewers） | 142 | 42 | −70% |

帧率未受损：1 viewer 10.48 → 10.90 fps；3 viewers 每个 10.75 → 11.30 fps。

---

## MJC-P1-102 · 自引入回归：`training_smoke_test.py` 不再产帧

- **优先级**：P1（破坏了既有 PPO/SAC 冒烟测试）— **本轮由我引入并在 push 前修复**
- **状态**：FIXED

### 现象与证据

```text
File "/app/scripts/training_smoke_test.py", line 60, in run_algorithm
    raise TimeoutError(f'{algorithm} policy viewer did not produce a frame')
```

### 根因

MJC-P1-101 让渲染变成「有订阅者才渲染」。`training_smoke_test.py` 是程序化消费者，直接
`ViewerSession(...)` 后读 `wait_frame()`，**从未 subscribe**，因此永远收不到帧。

### 修复

- `scripts/training_smoke_test.py`：读帧前 `viewer.subscribe()`，`finally` 中 `unsubscribe()` 并附注释说明。
- `ViewerSession` 增加类 docstring，把这个契约写成显式约定（避免下一位同事再踩）。
- `AGENTS.md` 不变量与 `docs/architecture` 的「按需渲染（重要契约）」章节同步记录。

### 结果

`training_smoke_test.py` exit 0：PPO 请求 1000 → 实际 2048 步、评估 28/30/28；
SAC 1000 步、评估 58/62/64；两者 checkpoint 与隔离策略回放均通过。

---

## MJC-P2-103 · 训练进程被 SIGKILL/OOM 时错误信息无法诊断

- **优先级**：P2
- **状态**：FIXED

### 现象

训练进程被容器内存上限、外部 `docker stop` 或宿主 OOM 杀掉时，`status.json` 只写
`Trainer exited unexpectedly (exit code 137)`，看不出是资源上限还是崩溃。

### 修复

`app/jobs.py::exit_reason(code)`：区分 137/SIGKILL（容器内存上限 / 外部 kill / 宿主 OOM）、
143/SIGTERM、其他负信号、非零退出码。仍保留「exit code N」字样，既有测试断言不受影响。

### 回归测试

`tests/test_jobs.py::test_finished_unreconciled_process_does_not_stay_running` 继续通过
（断言含 `exit code 0`）。

---

## MJC-P3-104 · CI 的集成测试可能被静默跳过

- **优先级**：P3（会增加“测试看着绿、其实没跑”的风险）
- **状态**：FIXED

### 证据

上一轮 CI 的 pytest 结果是 `19 passed, 4 skipped`，而本机完整依赖下是 `23 passed`：
4 个依赖 MuJoCo/Gymnasium 的集成测试在 CI 的轻量 job 中从未真正执行。

### 修复

- `tests/test_integration.py` 用 `require(module)` 取代 `pytest.importorskip`：
  当 `CONSOLE_TEST_REQUIRE_PHYSICS=1` 时依赖缺失**直接 fail**，否则 skip（保持本地/轻量可用）。
- 新增守门测试 `test_physics_dependencies_are_available_when_required`。
- `.github/workflows/ci.yml` 新增 step：在**部署镜像内**跑完整测试并断言 `skipped == 0`。

### 结果

本地复刻 CI 依赖（`python:3.12-slim` + 同款 pip 集合）：严格模式 **55 passed, 0 skipped**；
轻量模式 54 passed, 1 skipped（守门测试按设计 skip）。

---

## MJC-P3-105 · 坏环境目录被静默忽略，前后端都无法诊断

- **优先级**：P3
- **状态**：FIXED

### 现象

`catalog.discover()` 对无法解析的环境目录 `continue`，既不记录也不上报。
用户放入一个写错的 `manifest.json`，界面上「什么都没有」，无从下手。

### 修复

- `catalog.scan()` 返回 `(entries, problems)`，永不抛异常；problem 带
  `severity`（`error` = 不列出 / `warning` = 可用但不合 schema）、`reason`、`detail`。
- `GET /api/catalog` 返回 `problems`；启动时把问题写入容器日志；前端显示问题摘要（`textContent`）。
- `jsonschema>=4.20,<5` 加入运行时依赖，使 `schemas/environment.schema.json` 真正生效
  （导入失败自动跳过，不影响可用性）。
- `scripts/validate_manifests.py` 在 CI 中用同一套 `scan()` 校验仓库自带 envs，任何问题即失败。

### 回归测试

`tests/test_catalog.py`：11 种坏目录形态（非法目录名、缺 manifest、非 JSON、非对象、
符号链接由既有测试覆盖、缺 XML、XML 逃逸目录、xml 字段非法、kind 不支持、gym_id 非法、
注册模块非法）逐一断言 `reason`；schema 违规断言为 warning 且环境仍被列出；
`test_scan_survives_a_missing_env_root`。
`tests/test_api.py`：`/api/catalog` 含 `problems`；坏环境时仍 200 且内建环境照常列出。

---

## 仅记录的观察（未修改代码）

### MJC-P3-106 · uvicorn 进程的默认线程池会按需扩张到 16 线程

- 现象：空闲容器 `pids.current` 会在 10–22 之间变化；uvicorn 进程常年约 20 线程。
- 根因：`session_stream` 用 `asyncio.to_thread(session.wait_frame, …)`，落到事件循环的默认
  `ThreadPoolExecutor`（上限 `min(32, cpu+4)`），线程不会回收。
- 影响：轻微（线程空转但不忙等，不占 CPU），仅增加任务计数与少量内存。
- 建议：为 stream 轮询使用专用单线程执行器，或改用原生 `asyncio` 等待。

### MJC-P3-107 · 缺少 viewer 会话枚举/清理接口（沿用上一轮）

- 已被 MJC-P1-101 大幅缓解：被遗弃会话现在约 1.5% CPU（此前约 500%），
  但**仍占用 `MAX_VIEWERS` 槽位**直到 `SESSION_IDLE_SECONDS`。
- 建议：提供只读 `GET /api/sessions`。

### MJC-P3-108 · `data/runs/` 无保留策略（沿用上一轮）

- 本轮 23 条 run 共 2.2 MB，短期无风险。

### MJC-P3-109 · trainer 线程数未加默认上限

- 实测 trainer 约 2.94 核 / 17 线程；与 viewer 并发时容器约 4.8 核、宿主约 55% 空闲。
- 在获得「限流不损失吞吐」的实测证据前，不设置未经证实的默认值；改为提供
  `CONSOLE_CPU_LIMIT` / `CONSOLE_MEM_LIMIT` 作为可选的硬上限。

---

## 审查过但确认无缺陷

1. `ViewerSession.close()` 会重置订阅计数；worker 已退出时 `unsubscribe()` 不抛异常（有测试）。
2. 多个浏览器标签同时观看同一会话时订阅计数正确（1→2→1→0，只在临界点下发指令）。
3. 无订阅者时 `reset`/`pause`/`driver`/`stop` 仍正常（`.artifacts/render_toggle_check.sh` 中验证步数持续增长）。
4. 关闭阴影/MSAA 无收益（实测像素与时间差异为 0），因此**不**引入该配置项。
5. 降分辨率只省约 24%（固定开销占主导），作为可调项而非默认值。

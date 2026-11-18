# 第二轮验证报告 · Viewer 资源实证优化（2026-11-18）

- 仓库：`1998x-stack/MuJoCo-Environment-Console`
- `BASE_SHA`：`e422870481d68dd20feeb4e36538ee57306b97e8`（= PR #1 HEAD，本轮开始时 `origin/main` 仍为 `f64bc8f`）
- 分支：`agent/local-deploy-20261118-1058`（继续在 PR #1 的开发分支协作，未从旧 main 重做）
- 部署主机：Ubuntu 24.04.3 LTS，12 逻辑线程，31 GiB，端口 8010（8000 仍被其他业务占用）
- 结论：**PASS** —— 在未影响同机其他 27 个容器的前提下，实证降低 viewer CPU，并提高回归覆盖

原始证据目录（未提交）：`.artifacts/runs/20261118-053523-e422870/`

## 1. P1 调查：三个 Viewer 为什么消耗约 815% CPU

### 1.1 方法

宿主机可直读容器 cgroup v2（`/sys/fs/cgroup/**/docker-<id>.scope/cpu.stat`），
因此用 `cpu.stat usage_usec` 的差分做精确采样，而不是 `docker stats` 的瞬时值。
所有对照实验均为有界低负载（单 viewer 8–26 s 窗口，最多 3 viewer 20 s），
未做满负载或小时级压测。

### 1.2 逐项成本拆解（实测）

组件级基准（`gym:Hopper-v5`，640×480，12 fps 目标，单个 worker 进程）：

| 阶段 | 开销 | 占循环 |
|---|---|---|
| MuJoCo 物理步进 `env.step` | 0.12 ms 墙钟 | <1% |
| OSMesa/llvmpipe 光栅化 `env.render` | 约 30 ms 墙钟 × 12 线程 ≈ **490 ms CPU** | **>99.5%** |
| PIL `Image.fromarray` | 0.18 ms | 0.04% |
| JPEG 编码 q72 | 0.84 ms | 0.17% |
| 策略推理 `policy.predict` | 0.19 ms | 0.04% |

结论：**CPU 几乎全部花在 CPU 软光栅化上**，物理与编码可以忽略。

根因链：

1. 无 GPU → `MUJOCO_GL=osmesa` → Mesa llvmpipe **CPU** 光栅化；
2. llvmpipe 默认按核数创建 worker 线程（本机 12 个），且这些线程会自旋等待；
3. `numpy`/OpenBLAS 又各自创建 12 个线程（对渲染毫无用处）；
4. worker 循环**无条件**每帧调用 `env.render()`，与是否有浏览器在观看无关。

因此单个 viewer 进程有 39 个线程、稳定占用约 5 核；3 个 viewer 因争抢 12 个核而呈次线性增长
（860% 而不是 1500%+）。

### 1.3 实测 FPS 与目标是否一致

| 场景 | 目标 | 实测 |
|---|---|---|
| 1 viewer，640×480，默认线程池 | 12 fps | **10.48 fps（87%）** |
| 1 viewer，`LP_NUM_THREADS=2` | 12 fps | **11.60 fps（97%）** |
| 1 viewer，`LP_NUM_THREADS=4` | 12 fps | 11.82 fps |
| 3 viewers，默认线程池 | 12 fps | 10.75 fps |
| 3 viewers，`LP_NUM_THREADS=2` | 12 fps | **11.30 fps** |
| 最重模型 `gym:Humanoid-v5`，`LP_NUM_THREADS=2` | 12 fps | 11.70 fps |

**默认线程池反而更慢**：12 个自旋线程互相争抢，帧率只有 87%。限制线程数同时降低 CPU 并提高帧率。

### 1.4 139 PIDs：进程与线程归属

cgroup `pids.current` 统计的是**任务（线程）**，不是进程。优化前 3 viewer = 142：

| 组件 | 线程数 |
|---|---|
| 每个 viewer worker | **39** = 12 llvmpipe + 12 OpenBLAS 空闲线程 + 15 其他 Python 线程 |
| uvicorn（API 进程） | 约 20（`asyncio.to_thread` 默认执行器按需扩张，MJPEG 轮询会用到） |
| `resource_tracker` / `docker-init` | 2 |

优化后单个 worker 8 线程、3 viewer 容器总量 42 线程（−70%）。

### 1.5 浏览器断开后是否仍持续渲染

**是（优化前）**：断开后仍为 498.6% CPU。因为 rendering 与订阅无关，且会话要等
`SESSION_IDLE_SECONDS`（900 s）才被回收 —— 这是本轮最大的浪费点。
优化后同一场景为 **1.6%**。

### 1.6 训练与 Viewer 并发是否影响其他容器

| 场景 | 容器 CPU | 宿主 busy（12 核） |
|---|---|---|
| trainer 单独 | 293.6%（2.94 核，17 线程，378 MiB） | 24.6%（2.95 核） |
| trainer + 1 viewer | 477.9% | 44.7%（5.36 核） |

宿主仍有约 55% 空闲，其他容器可获得 CPU；但容器**默认无 CPU/内存上限**，
若 3 个 viewer 同时观看再加训练，容器可占用 9–10 核。因此新增可选
`CONSOLE_CPU_LIMIT` / `CONSOLE_MEM_LIMIT`（默认不设，保持历史行为）。

## 2. 采用的优化与前后对照

### 2.1 变更

1. **按需渲染**：worker 只在有订阅者时创建光栅化器（`ViewerSession.subscribe()/unsubscribe()`，
   MJPEG 端点自动订阅，断开时在 `finally` 中取消）。无人观看时物理继续步进、状态继续上报。
2. **线程预算**：`apply_process_limits()` 在导入 numpy/MuJoCo 前设置 `LP_NUM_THREADS`（默认 2）
   与 BLAS/OpenMP（默认 1）。渲染不需要 BLAS 线程。
3. **可配置化**：`VIEWER_FPS` / `VIEWER_WIDTH` / `VIEWER_HEIGHT`（带范围校验与回退）。
4. **可选容器上限**：`CONSOLE_CPU_LIMIT` / `CONSOLE_MEM_LIMIT`（`0`/未设为不限制）。
5. **错误反馈**：训练进程被杀时给出可诊断原因（137/SIGKILL → 容器内存上限 / 外部 kill / 宿主 OOM）。

### 2.2 前后对照（真实 API 会话 + 真实 MJPEG 订阅，cgroup 采样）

| 场景 | 优化前 CPU | 优化后 CPU | 变化 | 优化前任务数 | 优化后任务数 |
|---|---|---|---|---|---|
| 1 viewer，无人订阅 | 512.3% | **1.5%** | **−99.7%** | 50 | 12 |
| 1 viewer，正在被观看 | 499.7% | **159.4%** | **−68.1%** | 50 | 20 |
| 1 viewer，浏览器断开后 | 498.6% | **1.6%** | **−99.7%** | 50 | 20 |
| 3 viewers 同时观看 | 860.0% | **549.3%** | **−36.1%** | 142 | **42** |

帧率未被牺牲：1 viewer 10.48 → **10.90 fps**；3 viewers 10.75 → **11.30 fps**（每个）。
内存基本不变（3 viewer 约 600 MiB，主要是 worker 的 RSS 与 OSMesa 缓冲）。

### 2.3 没有采用的方案（因为实测无收益）

- **关闭阴影 / 关闭 MSAA**（`model.vis.quality.shadowsize=0` / `offsamples=0`）：
  在 `gym:Hopper-v5` 与 `custom:custom_double_pendulum` 上帧时间与像素**均无变化**
  （差异 0.0，speedup 1.00）。因此不引入该复杂度。
- **降分辨率**：640×480 → 320×240 仅省约 24%（固定开销占主导），保留为可调项而非默认。

## 3. 第三方 MJPEG 客户端实测（ffmpeg / OpenCV）

要求：验证 ≥30 帧、尺寸一致、解码有效、无 multipart boundary 错误；
**获取流与解码分离**，且 Cookie 不得出现在命令行、日志或 Git 历史中。

做法：凭据写入 `0700` 目录下的 `0600` 文件并只读挂载，用 `-d @file` / python `open()` 读取；
抓流由宿主机 python 进程完成（Cookie 只存在该进程内），解码在隔离容器中进行。

| 客户端 | 方式 | 结果 |
|---|---|---|
| ffmpeg（文件） | `ffmpeg -f mpjpeg -i stream.bin` | `Input #0, mpjpeg`；`Video: mjpeg (Baseline) 640x480`；解码 **60 帧**；exit 0；**无 boundary 错误** |
| ffmpeg（实时 HTTP） | `curl -b jar <stream> \| ffmpeg -f mpjpeg -i pipe:0` | 解码 **60 帧**，**12 fps**（= 目标帧率），无 `Invalid data / boundary` 错误 |
| OpenCV | 用 ffmpeg 转封装后由 `cv2.VideoCapture` 解码 | **60 帧**，尺寸集合仅 `{640x480}` |

这是对 MJC-P2-001（非 CRLF 分帧）的第三方实测确认：符合 RFC 2046 后，
严格客户端能正常解码；修复前实测合法分隔符为 0，全部客户端都拿不到帧。

## 4. 回归测试覆盖度

| 档位 | 命令 | 结果 |
|---|---|---|
| 轻量依赖（CI job 1，无 MuJoCo） | `pip install fastapi uvicorn httpx pytest jsonschema` + `pytest -q` | **50 passed, 5 skipped**（4 个依赖 MuJoCo 的集成测试 + 守门测试按预期 skip） |
| 完整镜像但非严格模式 | 镜像内 `pytest -q` | 54 passed, 1 skipped（物理测试已真实执行，仅守门测试 skip） |
| 严格模式（CI 新增 step） | `CONSOLE_TEST_REQUIRE_PHYSICS=1 pytest -q -rs` | **55 passed, 0 skipped** |

> **修正记录（2026-11-18 第三轮追加）**：本表原文把「54 passed, 1 skipped」标为「轻量依赖（CI 第一个 job）」。
> 真值：轻量 job（无 numpy/MuJoCo）为 `50 passed, 5 skipped`；`54 passed, 1 skipped` 对应**完整镜像非严格**模式。
> 依据：CI run 44257891758 日志、`environment.json.ci_lightweight_unit_tests`、以及本地在两种镜像下的实测。

新增能力：集成测试改用 `require()`，当 `CONSOLE_TEST_REQUIRE_PHYSICS=1` 时
**依赖缺失会直接 fail 而不是静默 skip**，CI 里新增的 step 会执行它并断言 `skipped == 0`。
上一轮「CI 只有 19 passed、4 skipped」的盲区由此关闭。

## 5. 环境扩展机制（可诊断性）

`catalog.scan()` 现在返回 `(entries, problems)` 且永不抛异常，每个问题带
`severity`（`error` = 不被列出 / `warning` = 仍可用但不合 schema）、`reason`、`detail`：

| 覆盖场景 | `reason` |
|---|---|
| 目录名非法 | `invalid_directory_name` |
| 缺少 manifest | `missing_manifest` |
| manifest 非 JSON / 非对象 | `invalid_manifest_json` / `manifest_not_an_object` |
| manifest 是符号链接 | `manifest_is_symlink` |
| XML 字段非法 / 文件缺失 / 逃逸目录 | `invalid_xml_field` / `xml_missing` / `xml_outside_environment` |
| `kind` 不支持 | `unsupported_kind` |
| gym_id / 注册模块非法 | `invalid_gym_id` / `invalid_registration_module` |
| 不符合 JSON Schema | `schema_violation`（warning，环境仍可用） |
| 未知异常 | `internal_error` |

- 控制台**不会**因坏环境而启动失败：`/api/catalog` 返回 200，附带 `problems`；
  启动时把每个问题写入日志；界面在环境目录下方显示问题摘要（`textContent`，无 XSS 风险）。
- 仓库自带的三个示例环境**零问题**；`scripts/validate_manifests.py` 在 CI 中用同一套 `scan()`
  校验它们，任何问题即失败。
- 新增依赖 `jsonschema>=4.20,<5`（纯 Python），使 schema 成为**运行时**校验源而不是文档摆设；
  导入失败时自动降级为“跳过 schema 检查”。

## 6. 未完成 / 受限项

| 项 | 状态 | 原因 |
|---|---|---|
| 小时级长时间稳定性测试 | **NOT_RUN** | 未获授权（会影响同机其他 27 个业务容器） |
| 满负载压力测试 | **NOT_RUN** | 同上 |
| 独立第三方**设备**局域网访问 | **NOT_RUN** | 无可用设备（已用 ffmpeg 作为第三方客户端替代，但不等价） |
| 训练收敛性验证 | **NOT_RUN** | 需授权与算力预算 |
| 真实机器人/复杂接触任务接入 | **NOT_RUN** | 本轮只做机制与示例，未引入新任务定义 |
| trainer 线程上限调优 | **未实施** | 无“限制后不损失吞吐”的证据，不引入未经验证的默认值；已提供容器级上限作为替代 |

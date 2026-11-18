# 测试矩阵 · 第二轮（2026-11-18）

原始日志根目录：`.artifacts/runs/20261118-053523-e422870/`（本机，未提交）。
`PASS` = 本轮真实执行且成功；`NOT_RUN` = 未执行并附原因。

## 1. 分层回归

| 层级 | 检查项 | 命令 / 方式 | 结果 | 证据 |
|---|---|---|---|---|
| L0 | Python/JS/Shell/JSON 语法 | `compileall`、`node --check`、`bash -n`、`json.tool` | PASS | 本轮终端输出 |
| L0 | manifest schema + 发现诊断 | `python scripts/validate_manifests.py` | PASS（3/3，0 problem） | 终端输出 |
| L0 | 单元/集成测试（完整依赖） | 部署镜像内 `pytest -q` | **PASS 55 passed, 0 skipped** | `pytest-final.log` |
| L0 | 轻量依赖（CI job 1 等价） | `python:3.12-slim` + 同款 pip 集合 | PASS 54 passed, 1 skipped | 本轮终端输出 |
| L0 | 严格模式（CI 新增 step 等价） | `CONSOLE_TEST_REQUIRE_PHYSICS=1 pytest -q -rs` | **PASS 55 passed, 0 skipped** | 本轮终端输出 |
| L1 | 认证/校验/限流/viewer 上限 | `.artifacts/l1_api_test.sh` | **PASS（0 失败）** | `l1-final.log` |
| L2 | 18 环境 reset/step/render | `smoke_test.py --render --all` | **PASS 18/18** | `smoke-test-after.log` |
| L3 | 浏览器 E2E 主流程 | `.artifacts/browser_e2e.js` | **PASS 30/30** | `browser-e2e-after.log` |
| L3 | 浏览器：新环境 + 模型回放 | `.artifacts/browser_replay_e2e.js` | **PASS 18/18** | `browser-replay-after.log` |
| L3 | 第三方 MJPEG（ffmpeg/OpenCV） | `.artifacts/third_party_mjpeg_check.sh` | **PASS** | `third-party-mjpeg.log` |
| L4 | PPO/SAC 训练 + checkpoint + 隔离回放 | `training_smoke_test.py` | **PASS（exit 0）** | `training-smoke-after.log` |
| L4 | 并发限制/取消/训练中重启/持久化 | `.artifacts/l4b_training_lifecycle.sh` | **PASS（0 失败）** | `l4b-after.log` |
| L5 | 重复创建销毁/3 viewer/优雅停止/重启 | `.artifacts/l5_stability.sh` | **PASS（0 失败）** | `l5-final.log` |
| L5 | 递归/长时间稳定性 | 未获授权 | **NOT_RUN** | — |
| CI | GitHub Actions 全流程 | [run 44257891758](https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44257891758) | **PASS** | 轻量 50 passed/5 skipped；严格 step `strict suite OK: 55 passed`（0 skipped）；`3/3 manifests valid`、`0 problem(s)`；`MJPEG framing OK: 57 boundaries`；`18/18 environments passed` |

## 2. 本轮新增的资源对照实验

| 实验 | 目的 | 结果 | 证据 |
|---|---|---|---|
| `component_bench.py` | 拆分物理/渲染/编码/推理成本 | 渲染占 >99.5% | `component-bench.log` |
| `loop_probe.py` + `phase2_knob_sweep.sh` | 各线程池/分辨率/帧率旋钮 | `LP=2` 最优（CPU −20%、帧率更高） | `phase2-knob-sweep.log`、`knob-sweep.jsonl` |
| `multiviewer_scaling.sh` | 3 并发 viewer 下的线程数缩放 | LP2 430% / LP4 617% / LP12 645% | `multiviewer-scaling.log` |
| `quality_bench.py` | 阴影/MSAA 是否有收益 | **无收益**（像素与时间差异 0） | `quality-bench.log` |
| `phase2_viewer_experiment.sh` | 真实会话前后对照 | 见 summary 表 | `phase2-viewer-before.log` / `phase2-viewer-final.log` |
| `phase2_trainer_impact.sh` | trainer 自身与并发影响 | trainer 293.6%；并发总量 478% | `phase2-trainer-impact.log` |
| `render_toggle_check.sh` | 订阅→渲染的真实行为 | **PASS（9/9）** | `render-toggle-final.log` |

## 3. 第三方 MJPEG 明细

| 客户端 | 输入 | 解码帧数 | 尺寸 | 错误 |
|---|---|---|---|---|
| ffmpeg 7.x（`-f mpjpeg`） | 抓取的 multipart 文件 | 60 | 640×480（mjpeg Baseline） | 无 boundary/容器错误，exit 0 |
| ffmpeg 6.x（实时 HTTP） | `curl -b jar <stream> \| ffmpeg -f mpjpeg -i pipe:0` | 60 | 640×480 | 无 |
| OpenCV（headless） | ffmpeg 转封装后的 MJPEG | 60 | 尺寸集合仅 `{640×480}` | 无 |

凭据处理：`mktemp -d`（0700）+ `login.json`（0600）只读挂载，`curl -d @file` / python `open()` 读取；
Cookie 只存在于抓流进程与容器内 `/tmp/jar`；命令行、日志、Git 中均不出现。

## 4. 关键计数汇总

| 指标 | 上一轮 | 本轮 |
|---|---|---|
| 单元/集成测试（完整依赖） | 23 passed | **55 passed** |
| 单元测试（轻量依赖） | 19 passed, 4 skipped | 54 passed, 1 skipped |
| 严格模式 | 无此机制 | **55 passed, 0 skipped（CI 强制）** |
| 环境 smoke | 18/18 | 18/18 |
| 浏览器断言 | 48 | 48 |
| 3 viewer 容器任务数 | 142 | **42** |
| 3 viewer CPU | 860% | **549%** |

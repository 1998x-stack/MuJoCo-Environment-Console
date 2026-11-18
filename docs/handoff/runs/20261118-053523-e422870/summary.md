# Run Summary · 20261118-053523 · base `e422870`

## 一句话结论

在不影响同机其他 27 个业务容器的前提下，用实测证据定位并消除了 viewer 的 CPU 浪费：
**无人观看的会话从约 512% 降到 1.5%，正在观看的单 viewer 从 500% 降到 159%，3 viewer 从 860% 降到 549%（线程 142 → 42）**，
帧率不降反升；并用 ffmpeg/OpenCV 完成第三方 MJPEG 实测，关闭了 CI「集成测试被静默跳过」的盲区。

## Metadata

| 项 | 值 |
|---|---|
| Agent | Pi |
| 主机类型 | Ubuntu 24.04.3 LTS 物理服务器（12 逻辑线程 / 31 GiB，另有 27 个业务容器） |
| BASE_SHA | `e422870481d68dd20feeb4e36538ee57306b97e8`（PR #1 HEAD；`origin/main` 仍为 `f64bc8f`） |
| 分支 | `agent/local-deploy-20261118-1058`（继续在 PR #1 分支协作） |
| 部署 | `bash scripts/deploy.sh` exit 0；容器 `Up (healthy)`，`8010->8000/tcp`；镜像 `sha256:12c10d83…` |
| 原始证据 | `.artifacts/runs/20261118-053523-e422870/`（本机，未提交） |

## 关键实测数据

单个 viewer 循环的成本构成（640×480，12 fps 目标）：

| 阶段 | 开销 | 占循环 |
|---|---|---|
| MuJoCo 物理步进 | 0.12 ms | <1% |
| OSMesa/llvmpipe 光栅化 | 约 490 ms CPU / 约 30 ms 墙钟 | **>99.5%** |
| JPEG 编码 + PIL | 1.0 ms | 0.2% |
| 策略推理 | 0.19 ms | 0.04% |

前后对照（真实 API 会话 + 真实 MJPEG 订阅，cgroup `cpu.stat` 采样）：

| 场景 | 前 | 后 | 变化 |
|---|---|---|---|
| 1 viewer，无人订阅 | 512.3% | 1.5% | −99.7% |
| 1 viewer，正在观看 | 499.7% | 159.4% | −68.1% |
| 1 viewer，浏览器断开 | 498.6% | 1.6% | −99.7% |
| 3 viewers 同时观看 | 860.0% | 549.3% | −36.1% |
| 容器任务数（3 viewers） | 142 | 42 | −70% |

帧率：1 viewer 10.48 → 10.90 fps；3 viewers 每个 10.75 → 11.30 fps。

## 主要产出

1. **按需渲染**（`app/worker.py`、`app/sessions.py`、`app/main.py`）：只有存在订阅者时才创建
   光栅化器；无人观看时物理仍步进、状态仍上报。程序化消费者必须 `subscribe()`（已在
   `ViewerSession` 文档化，并修好了因此暴露的 `scripts/training_smoke_test.py` 回归）。
2. **viewer 线程预算**（默认 `LP_NUM_THREADS=2`、BLAS=1）：默认线程池按核数创建且自旋，
   限制后 CPU 更低、帧率更高。已在 `app/worker.py` 内记录实测表，并有测试 pin 住默认值。
3. **可配置化**：`VIEWER_FPS` / `VIEWER_WIDTH` / `VIEWER_HEIGHT` / `VIEWER_RENDER_THREADS` /
   `VIEWER_BLAS_THREADS` / `CONSOLE_CPU_LIMIT` / `CONSOLE_MEM_LIMIT`。
4. **训练错误可诊断**：137/SIGKILL 等退出原因给出明确解释（内存上限 / 外部 kill / 宿主 OOM）。
5. **第三方 MJPEG 实测**：ffmpeg 解码文件 60 帧、实时 HTTP 流 60 帧 @12 fps，OpenCV 60 帧 640×480；
   获取与解码分离，凭据不入命令行/日志/Git。
6. **CI 覆盖度**：集成测试支持 `CONSOLE_TEST_REQUIRE_PHYSICS=1` 严格模式（缺失依赖 → fail），
   新增 CI step 在**部署镜像内**跑完整测试并断言 `skipped == 0`（55 passed / 0 skipped）。
7. **环境导入可诊断**：`catalog.scan()` 返回结构化 `problems`（含 `severity`/`reason`/`detail`），
   坏环境不再静默消失，也不会阻止服务启动；`jsonschema` 进入运行时依赖使 schema 真正生效。
8. **文档**：架构（成本拆解与线程预算）、运维手册（6.1 资源调优 + 故障排查）、
   本轮验证报告、Handoff（本目录 + `latest.md`）。

## 未完成项

| 项 | 状态 | 原因 |
|---|---|---|
| 小时级长时间稳定性 / 满负载压力 | NOT_RUN | 未获授权，会影响同机其他业务容器 |
| 独立第三方设备局域网访问 | NOT_RUN | 无可用设备（已用 ffmpeg 作为第三方客户端替代） |
| 训练收敛性验证 | NOT_RUN | 需授权与算力预算 |
| trainer 线程上限默认值 | 未实施 | 没有「限流不损失吞吐」的证据，不引入未经验证的默认值 |

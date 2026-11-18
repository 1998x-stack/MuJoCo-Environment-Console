# 测试矩阵 · 2026-11-18

约定：`PASS` 表示本轮在本机真实执行并成功；`NOT_RUN` 表示未执行（附原因）；`BLOCKED` 表示被外部条件阻塞。
原始日志路径以 `.artifacts/runs/20261118-105857-f64bc8f/` 为根（未提交，仅本机）。

| 层级 | 检查项 | 命令 / 方式 | 结果 | 证据文件 |
|---|---|---|---|---|
| L0 | Python 语法 | `python3 -m compileall -q app tests scripts` | PASS (exit 0) | `static-checks.log` |
| L0 | 前端语法 | `node --check app/static/app.js` | PASS (exit 0) | `static-checks.log` |
| L0 | Shell 语法 | `bash -n scripts/*.sh` | PASS (2 个脚本) | `static-checks.log` |
| L0 | Schema JSON | `python3 -m json.tool schemas/environment.schema.json` | PASS | `static-checks.log` |
| L0 | manifest × schema | `python scripts/validate_manifests.py` | PASS (3/3) | 本轮终端输出 |
| L0 | 单元/集成测试 | `python -m pytest -q` | PASS (23 passed) | `pytest-final.log` |
| L1 | 容器状态与健康检查 | `docker compose ps` / `curl /healthz` | PASS | `docker-service.log` |
| L1 | 未登录 401 | `/api/catalog`、`/api/me`、`/api/training` | PASS (401) | `l1-api-after-fix.log` |
| L1 | 静态资源与安全头 | `/`、`/app.js`、`/app.css`、响应头 | PASS | `l1-api-after-fix.log` |
| L1 | 登录成功/失败/校验 | 正确 200、错误 401、空 422 | PASS | `l1-api-after-fix.log` |
| L1 | Cookie 属性 | `HttpOnly; SameSite=strict; Max-Age=43200` | PASS | `l1-api-after-fix.log` |
| L1 | 登录限流 | 8 次失败后第 9 次 429 | PASS | `l1-ratelimit-restart.log` |
| L1 | 重启清空限流 | `docker compose restart console` | PASS (恢复 200) | `l1-ratelimit-restart.log` |
| L1 | 输入校验 | 未知环境/非法算法/步数边界/路径穿越 | PASS | `l1-api-after-fix.log` |
| L1 | 会话生命周期 | 创建/状态/reset/pause/driver/stop | PASS | `l1-api-after-fix.log` |
| L1 | viewer 上限 | 第 4 个会话 400，停止后可再建 | PASS | `l1-api-after-fix.log` |
| L1 | 登出后受限 | `/api/catalog` 恢复 401 | PASS | `l1-api-after-fix.log` |
| L2 | 标准 MuJoCo 环境 | `smoke_test.py --render --all` | PASS (11/11) | `smoke-test-final.log` |
| L2 | Fetch Robotics | 同上 | PASS (4/4) | `smoke-test-final.log` |
| L2 | 自定义 MJCF | 同上 | PASS (3/3) | `smoke-test-final.log` |
| L2 | 逐环境明细 | reset/step/render/frame_shape/reward | PASS (18/18) | `env-probe-final.log` |
| L2 | MuJoCo 运行时警告 | 采集 `warnings` 列表 | PASS (空) | `env-probe-final.log` |
| L3 | 登录门与错误提示 | Playwright + Chromium over LAN IP | PASS | `browser-e2e-final.log` |
| L3 | 目录/分类/搜索 | 18 卡片、标签唯一、筛选 | PASS | `browser-e2e-final.log` |
| L3 | MJPEG 浏览器解码 | `naturalWidth>0`、截图逐帧比对变化 | PASS | `browser-e2e-final.log` |
| L3 | 暂停/恢复/重置 | 步数冻结与恢复增长 | PASS | `browser-e2e-final.log` |
| L3 | 策略驱动无模型提示 | 引导 toast | PASS | `browser-e2e-final.log` |
| L3 | 训练日志弹窗 | `#logDialog` 有内容 | PASS | `browser-e2e-final.log` |
| L3 | 登出/Cookie 跨刷新 | 状态正确 | PASS | `browser-e2e-final.log` |
| L3 | MJPEG 严格规范解析 | 真实 CRLF + 84/84 帧解码 | PASS | `mjpeg-conformance-after-fix.log` |
| L3 | 新环境（include+mesh） | 浏览器运行 + 可训练 | PASS | `browser-replay-e2e.log` |
| L3 | view_only 场景 | 渲染 + 「仅演示」+ 训练禁用 + 服务端 400 | PASS | `browser-replay-e2e.log` |
| L3 | 浏览器模型回放 | 服务端 `mode=policy`、UI 切换、画面更新 | PASS | `browser-replay-e2e.log` |
| L3 | 局域网真实浏览器交互 | 通过局域网 IP 完成 | PASS | `browser-e2e-final.log` |
| L3 | 独立第三方设备访问 | 无可用设备 | **NOT_RUN** | — |
| L4 | PPO 训练链路 | `training_smoke_test.py` | PASS (exit 0) | `training-smoke.log` / `.exit` |
| L4 | SAC 训练链路 | 同上 | PASS (exit 0) | `training-smoke.log` / `.exit` |
| L4 | checkpoint 保存/加载 | smoke + 手工 `PPO.load` | PASS | `replay-debug.log` |
| L4 | 隔离 ViewerSession 回放 | smoke `isolated_policy_viewer` | PASS | `training-smoke.log` |
| L4 | 单任务并发限制 | 第二个任务 400 | PASS | `l4b-final.log` |
| L4 | 取消任务 | `status=cancelled`、无 model.zip | PASS | `l4b-final.log` |
| L4 | 训练中重启容器 | `interrupted` + 进程组清理 + 可再启动 | PASS | `l4b-final.log` |
| L4 | 持久化 | 重启后 4 条 run 完整保留 | PASS | `persistence-and-process-audit.log` |
| L4 | 新环境训练与回放 | `custom_double_pendulum` PPO 2048 步 | PASS | `browser-replay-e2e.log` |
| L5 | 重复创建/销毁 10 次 | 无进程累积 | PASS | `l5-final.log` |
| L5 | 3 viewer 并发流 | 3 个流各 66 帧 | PASS | `l5-final.log` |
| L5 | 空闲会话自动回收 | `SESSION_IDLE_SECONDS=20` 实例 | PASS | `session-reaper.log` |
| L5 | 优雅停止（含活跃任务） | 6–7 s，无宿主残留 | PASS | `l5-final.log` |
| L5 | 重启恢复 | `running/healthy` | PASS | `l5-final.log` |
| L5 | 资源基线（空闲/3 viewer） | `docker stats` | PASS | `l5-final.log` |
| L5 | 小时级长时间稳定性 | 未获授权，会影响同机其他业务 | **NOT_RUN** | — |
| L5 | 满负载压力测试 | 同上 | **NOT_RUN** | — |
| — | GPU / CUDA 路径 | 项目为 CPU-first，且未要求 | **NOT_RUN** | — |
| — | Menagerie 导入脚本 | 需克隆 GB 级仓库 | **NOT_RUN** | — |
| — | GitHub Actions | [run 44235254442](https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44235254442) | PASS (2m36s) | CI 日志：`19 passed, 4 skipped`、`3/3 manifests valid`、`MJPEG framing OK: 56 CRLF-delimited boundaries`、`18/18 environments passed` |

## 关键对照实验（修复有效性）

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 合法 RFC 2046 分隔符 `\r\n--frame` | 0 | 84 |
| 分片尾部字节 | `5c725c6e`（字面量 `\r\n`） | `ffd9`（JPEG EOI） |
| 字面量 `5c725c6e` 出现次数 | 104 | 0 |
| 严格解析可解码帧数 | 0 | 84 / 84 |
| 宽松解析可解码帧数（浏览器路径） | 105 | 84 |

## 计数汇总

- 单元/集成测试：16 → **23**
- 环境 smoke：16 → **18**
- 浏览器断言：**48**（30 主流程 + 18 补充），全部通过
- API 断言（L1）：**0 失败**
- 四层脚本（L1/L4b/L5 + smoke）：全部 `RESULT: PASS`

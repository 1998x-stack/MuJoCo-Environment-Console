# Run Summary · 20261118-105857 · base `f64bc8f`

## 一句话结论

在真实 Ubuntu 24.04 服务器上完成部署与 L0–L5 全链路验证，**发现并修复 1 个 P2 与 3 个 P3 缺陷**，
环境覆盖从 16 扩展到 18，单元测试 16 → 23，并建立完整的 Agent Handoff 体系。

## Metadata

| 项 | 值 |
|---|---|
| Agent | Pi |
| 主机类型 | Ubuntu 24.04.3 LTS 物理服务器（非容器/非 macOS） |
| BASE_SHA | `f64bc8f5319754e3228bf626804ba408518c5171`（= 本轮开始时 `origin/main`） |
| 分支 | `agent/local-deploy-20261118-1058` |
| 部署入口 | `bash scripts/deploy.sh`（exit 0） |
| 容器 | `mujoco-console`，`Up (healthy)`，`8010->8000/tcp` |
| 原始证据 | `.artifacts/runs/20261118-105857-f64bc8f/`（本机，未提交） |

## 执行流程

`Discover → Baseline → Deploy → Verify → Diagnose → Fix → Regression → PR → Handoff`

1. **Discover / Baseline**：仓库已存在且工作区干净；`HEAD == origin/main == f64bc8f`，
   远端无新提交。逐文件读取 `app/`、`scripts/`、`tests/`、`schemas/`、`envs/`、`ci.yml`。
2. **环境勘察**：Ubuntu 24.04.3 / i5-10500（12 线程）/ 31 GiB / 575 GiB 可用 / Docker 29.1.3。
   **发现 8000 端口被无关业务占用**，且本机有 27 个其他业务容器 → 决定使用 `CONSOLE_PORT=8010`
   并全程不触碰其他服务。
3. **Deploy**：`scripts/deploy.sh` 成功；镜像 435 MiB；健康检查通过。
4. **Verify**：L0（静态 + 23 单测）→ L1（API/认证/限流/校验/上限）→ L2（18 环境渲染）
   → L3（真实 Chromium over LAN，48 断言）→ L4（PPO/SAC + 取消/重启/持久化）
   → L5（并发/回收/优雅停机/资源）。
5. **Diagnose / Fix**：由 L3 的严格 MJPEG 解析暴露 P2 缺陷；由新增环境暴露 UI P3 缺陷；
   由代码审查发现 schema 未执行、CI 断言过弱。
6. **Regression**：修复后重新构建部署并重跑全部层次，全绿。
7. **PR / Handoff**：提交到工作分支并创建 PR；写入本 Handoff。

## 主要产出

- **修复**：MJPEG 分片改为 RFC 2046 CRLF（MJC-P2-001），并量化修复前后差异
  （规范分隔符 0 → 84；严格解码帧 0 → 84/84）。
- **测试**：新增 7 个测试（MJPEG 分帧、view_only 拒绝训练、示例环境发现、schema 校验、
  include+mesh 物理、view_only 物理、category 不变量）。
- **CI**：新增 MJPEG 分帧断言（可捕获本类缺陷）、manifest schema 校验步骤、新环境断言。
- **脚本**：新增 `scripts/validate_manifests.py`。
- **环境**：新增 `envs/custom_double_pendulum`（`<include>` + 二进制 mesh，可训练）与
  `envs/scene_demo_viewer`（`view_only` 仅演示），覆盖此前零覆盖的路径。
- **可视化修复**：分类标签去重（自定义控制 / 自定义场景）。
- **文档**：`AGENTS.md` + `docs/architecture` + `docs/runbooks` + `docs/verification` + `docs/handoff`。

## 未完成项

| 项 | 状态 | 原因 |
|---|---|---|
| 独立第三方设备局域网验证 | NOT_RUN | 无可用设备；已用局域网 IP 的真实浏览器验证替代 |
| 小时级长时间稳定性 | NOT_RUN | 未获授权，会影响同机 27 个其他业务容器 |
| 满负载压力测试 | NOT_RUN | 同上 |
| GPU / CUDA 路径 | NOT_RUN | 项目为 CPU-first，且未要求 |
| Menagerie 导入脚本 | NOT_RUN | 需克隆 GB 级仓库；`view_only` 路径已由新示例等价覆盖 |
| ffmpeg/OpenCV 实测 MJPEG | NOT_RUN | 本机未安装；已用严格 RFC 2046 解析器替代 |
| GitHub Actions | PENDING | 推送后实测，结果回填 `latest.md` |

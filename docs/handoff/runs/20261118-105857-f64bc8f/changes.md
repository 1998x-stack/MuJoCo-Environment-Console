# 变更清单 · 2026-11-18

- `BASE_SHA`：`f64bc8f5319754e3228bf626804ba408518c5171`
- 分支：`agent/local-deploy-20261118-1058`
- `final_sha`：见本文件末尾的提交记录（提交后回填）

## 代码变更

### `app/main.py` — 修复 MJC-P2-001

```diff
 STATIC = Path(__file__).parent / 'static'
+MJPEG_BOUNDARY = 'frame'
 PASSWORD = os.getenv('MUJOCO_CONSOLE_PASSWORD', '')

+def mjpeg_part(jpeg):
+    """Encode one JPEG as an RFC 2046 multipart body part."""
+    return (
+        b'--' + MJPEG_BOUNDARY.encode()
+        + b'\r\nContent-Type: image/jpeg\r\nContent-Length: '
+        + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n'
+    )

-                yield (
-                    b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '
-                    + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\\r\\n'
-                )
+                yield mjpeg_part(jpeg)
...
-    return StreamingResponse(gen(), media_type='multipart/x-mixed-replace; boundary=frame')
+    return StreamingResponse(
+        gen(), media_type=f'multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}'
+    )
```

### `app/static/app.js` — 修复 MJC-P3-004

```diff
-{'Locomotion':'运动','Control':'控制','Manipulation':'机械臂','Humanoid':'人形','Fetch Robotics':'Fetch 机器人','Custom Control':'自定义','Custom':'自定义'}
+{'Locomotion':'运动','Control':'控制','Manipulation':'机械臂','Humanoid':'人形','Fetch Robotics':'Fetch 机器人','Custom Control':'自定义控制','Custom Scene':'自定义场景','Custom':'自定义'}
```

## 新增环境（此前完全未被测试覆盖的路径）

| 文件 | 说明 |
|---|---|
| `envs/custom_double_pendulum/manifest.json` | 可训练，2 自由度，`target_qpos`/`init_qpos` 长度 = nq |
| `envs/custom_double_pendulum/scene.xml` | 入口 XML：`<include file="links.xml"/>`、相机、地面、2 个 motor |
| `envs/custom_double_pendulum/links.xml` | 被 include 的模型片段：`<asset><mesh file="assets/tip.stl">`、两级摆 body/joint |
| `envs/custom_double_pendulum/assets/tip.stl` | 二进制 STL（384 B，6 面） |
| `envs/scene_demo_viewer/manifest.json` | `view_only: true`，`trainable=False` |
| `envs/scene_demo_viewer/scene.xml` | 无执行器，含被动铰链道具与静态柱体 |
| `envs/scene_demo_viewer/props.xml` | 被 include 的 `<asset>` 片段 |
| `envs/scene_demo_viewer/assets/prop.stl` | 二进制 STL（384 B） |

覆盖能力：`<include>` 相对路径解析、mesh 资产加载、`nq != 1` 的观测/动作空间、
`view_only` 分类与「拒绝训练」分支、环境指纹包含被 include 的 XML 与 mesh。

## 测试变更

| 文件 | 新增内容 |
|---|---|
| `tests/test_api.py` | `test_mjpeg_part_is_rfc2046_framed`、`test_view_only_environment_rejects_training` |
| `tests/test_catalog.py` | `test_custom_examples_are_discovered_with_expected_flags`、`test_shipped_manifests_match_schema`、`test_view_only_scene_has_no_actuators` |
| `tests/test_integration.py` | `test_custom_double_pendulum_resolves_include_and_mesh`、`test_view_only_scene_runs_without_actuators` |

## CI 变更（`.github/workflows/ci.yml`）

1. 依赖安装追加 `jsonschema`。
2. 新增 step：`Validate shipped environment manifests against the schema`
   → `python scripts/validate_manifests.py`。
3. 目录断言要求集合扩展为 5 个核心环境，并断言
   `custom:scene_demo_viewer.trainable is False` 与 `custom:custom_double_pendulum.trainable is True`。
4. 新增 MJPEG 分帧断言（`b'\r\n--frame' in data`，且不得出现转义字面量）——
   该断言能捕获 MJC-P2-001 这类缺陷。

## 新增脚本

- `scripts/validate_manifests.py`：manifest × JSON Schema 校验入口（退出码可被 CI 使用）。

## 文档变更

| 文件 | 说明 |
|---|---|
| `AGENTS.md` | **新增**：持久化工程规范（架构、命令、约束、Git/CI 规则、Handoff 流程、DoD） |
| `docs/architecture/system-overview.md` | **新增**：组件、适配层、会话生命周期、MJPEG 协议细节、训练生命周期、指纹、安全、资源 |
| `docs/runbooks/ubuntu-deployment.md` | **新增**：部署前决策清单、部署、验收、安全边界、数据保护、故障排查、运维速查 |
| `docs/verification/2026-11-18-local-verification.md` | **新增**：本轮完整验证报告 |
| `docs/handoff/README.md` | **新增**：Handoff 协议 |
| `docs/handoff/latest.md` | **新增**：唯一入口索引 |
| `docs/handoff/runs/20261118-105857-f64bc8f/*` | **新增**：本轮 run 记录（6 个文件） |
| `README.md` | 示例环境列举、MJPEG 标准客户端兼容性说明 |
| `envs/README.md` | 示例表格、`<include>`/mesh 相对路径说明、二进制 STL 警告、`view_only` 行为 |
| `.gitignore` | 新增 `.artifacts/`（原始证据不入库） |

## 明确未做的事

- 未升级任何依赖版本（MuJoCo 3.3.7 / Gymnasium 1.4.0 / Robotics 1.4.2 / SB3 2.9.2 / torch 2.9.0+cpu 保持不变）。
- 未删除或改写 `data/runs/` 中任何训练记录；本轮新增 6 条 run 用于验证。
- 未执行 `docker compose down -v`、`docker system prune`、`rm -rf data` 等破坏性命令。
- 未停止、重启或删除宿主机上其他 27 个业务容器；未使用宿主机 8000 端口。
- 未强制推送、未直接推送 `main`、未自动合并 PR。
- 未提交 `.env`、密码、Cookie、Token、原始日志或截图。

## 提交记录

| # | Commit | 说明 |
|---|---|---|
| 1 | `<fill after commit>` | `fix: frame MJPEG parts with a real CRLF terminator` |
| 2 | `<fill after commit>` | `test: cover MJPEG framing, manifests and view-only scenes` |
| 3 | `<fill after commit>` | `ci: assert MJPEG framing and validate environment manifests` |
| 4 | `<fill after commit>` | `feat: add include+mesh and view-only example environments` |
| 5 | `<fill after commit>` | `docs: add agent handoff, architecture, runbook and verification report` |

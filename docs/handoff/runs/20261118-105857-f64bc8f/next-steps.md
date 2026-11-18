# Next Steps · 下一轮工作清单

约定：每项包含优先级、依赖、明确的验收标准。上一轮已 FIXED 项不再列出（见 `issues.md`）。

---

## NS-1（P0 流程）~~确认 CI 全绿并回填 Handoff 元数据~~ — **本轮已完成**

- 结果：CI [run 44235254442](https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44235254442)
  **success**（2m36s）。元数据已回填至 `latest.md`、`environment.json`、`changes.md`、`test-matrix.md`。
- 注意：CI 首次运行**曾失败**——`tests/test_integration.py` 顶层 `import numpy` 使 pytest 在
  **收集阶段**报错（CI 轻量依赖集不含 numpy）。已改为 `pytest.importorskip('numpy')`。
  下轮新增测试时请沿用「重依赖一律 importorskip」的写法，否则会让 CI 在收集阶段直接失败。

### 原始目标（供追溯）

- 依赖：本轮 PR 推送成功。
- 动作：
  1. 打开 PR 对应的 GitHub Actions run，确认全部 step 通过，
     **特别是新增的 `Validate shipped environment manifests against the schema` 与
     MJPEG 分帧断言两步确实执行了**（而非被跳过）。
  2. 回填 `docs/handoff/latest.md` 的 `Final local SHA`、`PR`、`CI run`，
     以及 `changes.md` 的提交表。
- 验收标准：`latest.md` 中三处 PENDING 全部替换为真实值；CI run URL 可访问且结论为 success；
  CI 日志中能检索到 `MJPEG framing OK` 与 `3/3 manifests valid`。

---

## NS-2（P2 验证）用第三方 MJPEG 客户端实测流

- 依赖：无（可在容器内安装 ffmpeg，或在获授权时装到宿主机）。
- 背景：MJC-P2-001 的修复只用 Chromium 与自写的严格 RFC 2046 解析器验证过，
  尚未用 ffmpeg / OpenCV 实测。
- 动作：
  ```bash
  docker compose exec -T console sh -c 'apt-get update -qq && apt-get install -y -qq ffmpeg'  # 仅临时容器内
  # 或使用 python-opencv
  ```
  然后对一个活跃会话执行 `ffmpeg -i "http://127.0.0.1:8010/api/sessions/<sid>/stream" -frames:v 30 -f null -`，
  要求 stderr 无 `Invalid data found` / `boundary not found`，且成功输出 30 帧。
- 验收标准：ffmpeg（或 OpenCV `VideoCapture.read()`）能连续取得 ≥30 帧，退出码 0。
  若失败，重新打开 MJC-P2-001 并附 stderr。

---

## NS-3（P3 产品）为 viewer 会话提供枚举/清理能力（MJC-P3-005）

- 依赖：无。
- 背景：被浏览器遗弃的会话占用 `MAX_VIEWERS` 槽位直到 `SESSION_IDLE_SECONDS`；
  本轮自动化压测真实遇到过「第 4 个会话无法创建」。
- 动作（择一）：
  - a) 新增只读接口 `GET /api/sessions`（返回 id / env_id / last_seen / state），前端不做展示也可；
  - b) 容器启动时清理孤儿会话（进程内存结构本已为空，此项无意义）；
  - c) 在桶满时按 `last_seen` 淘汰最旧的非活跃会话（需要明确的产品决策，慎选）。
- 验收标准：新增接口有测试；`GET /api/sessions` 在 3 个 viewer 时返回 3 条；
  文档（README 运维命令 + runbook）说明如何使用。

---

## NS-4（P3 运维）`data/runs/` 保留策略与容器资源上限（MJC-P3-006 / MJC-P3-007）

- 依赖：需用户确认是否允许自动删除历史 run。
- 动作：
  1. 文档化保留策略（例如仅保留最近 N 条或 M 天），或在 API 中提供手动清理。
  2. `compose.yaml` 增加 `mem_limit`/`cpus`（例如 `mem_limit: 8g`），
     并在 runbook 中给出按宿主机容量取值的依据。
- 验收标准：文档中可查到策略；如实现自动清理，必须在删除前要求显式确认，
  并有测试证明不会删除 `completed` 且带 `model.zip` 的记录（除非用户明确要求）。

---

## NS-5（P3 稳定性，需授权）小时级稳定性测试

- 依赖：**需要用户明确授权**（会占用 CPU/内存，可能影响同机其他 27 个业务容器）。
- 动作：以有界方式运行 ≥2 小时，覆盖：viewer 反复创建销毁、训练/取消循环、
  定时抓流；每 30 s 采样 `docker stats`，记录 RSS、进程数、`data/runs` 增长。
- 验收标准：进程数无单调增长；RSS 波动在 ±20% 内无泄漏趋势；
  训练取消后进程组全部消失；产出 `resource-samples.csv` 与结论写在独立报告中
  （与基础验收分开报告）。

---

## NS-6（可选研究）收敛性验证

- 依赖：需授权（长训练）、CPU 时间预算。
- 动作：对 `gym:InvertedPendulum-v5` 训练 20 万步 PPO，记录学习曲线；
  与随机策略基线（当前 smoke 约 28）对比。
- 验收标准：报告中明确区分「链路可用」与「收敛」；
  给出多条种子曲线与均值，而不是单次回报。

---

## NS-7（P3 完善）用真实外部客户端验证局域网访问

- 依赖：同一局域网内的另一台设备（手机/笔记本）。
- 动作：在另一设备浏览器访问 `http://<LAN-IP>:8010`，完成登录、启动环境、观看画面、
  触发一次训练、回放模型。
- 验收标准：在报告中记录设备类型、浏览器版本与截图（脱敏），
  并把 `latest.md` 的 `third_party_lan_client` 从 `NOT_RUN` 更新为实测结果。

---

## 给下一轮 Agent 的提醒

1. **先读** `AGENTS.md` 与 `docs/handoff/latest.md`，再 `git log` 对比本轮 `final_sha`。
2. 若 `origin/main` 已包含本轮修复，请核对 `app/main.py` 的 `mjpeg_part` 是否仍是 CRLF 版本
   （有人「简化」回 `b'\\r\\n'` 是这类缺陷的复发方式）。
3. 部署端口继续用 8010；不要动 8000 上属于其他项目的服务。
4. 不要在宿主机执行 `pip install`（无 `python3-venv`）；用镜像跑测试，
   或使用 `docs/runbooks/ubuntu-deployment.md` 中的 `docker run` 片段。
5. 新增环境时优先用二进制 STL；ASCII STL 在 MuJoCo 3.3.7 下无法加载。

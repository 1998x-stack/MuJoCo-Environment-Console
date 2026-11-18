# Next Steps · 第三轮工作清单

约定：每项含优先级、依赖、明确验收标准。上一轮已 FIXED 项不再列出（见 `issues.md`）。

---

## NS-1（P0 流程）确认 CI 全绿并回填元数据

- 依赖：本轮提交已推送。
- 动作：打开 PR #1 的最新 Actions run，确认：
  1. 新增 step「Run the full test suite inside the deployed image」通过，且日志中出现
     `strict suite OK: 55 passed`（**不能**出现 `skipped`）；
  2. `Validate shipped environment manifests against the schema` 输出 `3/3 manifests valid`
     与 `0 problem(s)`；
  3. MJPEG 分帧断言输出 `MJPEG framing OK: N CRLF-delimited boundaries`。
- 验收标准：把 run 链接与最终 SHA 回填到 `latest.md` / `environment.json` / `changes.md`；
  CI 首次运行若失败，按错误修复并更新同一个 PR，不得放宽断言。

---

## NS-2（P2 验证）独立第三方**设备**的局域网验证

- 依赖：同一局域网内的另一台设备（手机/笔记本）。
- 背景：本轮用 ffmpeg/OpenCV 完成了第三方客户端验证，但仍未用真实设备验证局域网访问。
- 动作：在另一设备浏览器访问 `http://<LAN-IP>:8010`，完成登录 → 启动环境 → 观看画面 →
  触发训练 → 模型回放；同时记录该设备连接时的 viewer CPU（应约 160%，断开后回落到约 2%）。
- 验收标准：报告中记录设备/浏览器版本 + 脱敏截图；把 `latest.md` 的
  `third_party_lan_client` 从 `NOT_RUN` 更新为实测结果。

---

## NS-3（P2 产品）为 viewer 会话提供枚举/清理接口（MJC-P3-107）

- 依赖：无。
- 背景：被遗弃会话现在只有约 1.5% CPU，但**仍占用 `MAX_VIEWERS` 槽位**直到
  `SESSION_IDLE_SECONDS`（默认 900 s）。自动化脚本容易撞到 400。
- 动作：新增只读 `GET /api/sessions`（返回 id / env_id / subscribers / render / last_seen / state），
  可选提供显式清理入口；前端可选展示。
- 验收标准：接口有测试；3 个 viewer 时返回 3 条；README 运维命令与 runbook 中说明用法。

---

## NS-4（P3 运维）`data/runs/` 保留策略（MJC-P3-108）

- 依赖：**需用户确认**是否允许删除历史 run。
- 动作：文档化保留策略，或提供带显式确认的清理入口。
- 验收标准：文档可查；若实现自动清理，必须有测试证明不会删除 `completed` 且带 `model.zip`
  的记录（除非用户明确要求）。

---

## NS-5（P3 稳定性，需授权）小时级稳定性测试

- 依赖：**需用户明确授权**（会占用资源，可能影响同机其他 27 个业务容器）。
- 动作：≥2 小时有界运行，覆盖 viewer 反复创建/订阅/断开、训练与取消循环；
  每 30 s 采样 cgroup `cpu.stat`/`memory.current`/`pids.current`。
- 验收标准：进程/线程数无单调增长；空闲期 CPU 稳定在约 1–2%；RSS 无泄漏趋势；
  产出 `resource-samples.csv` 与独立报告（与基础验收分开）。
- 提示：本轮已建立可复用的采样器 `.artifacts/sampler.py`（cgroup v2，秒级精度）。

---

## NS-6（P3 可选）uvicorn 线程池收敛（MJC-P3-106）

- 背景：`asyncio.to_thread(session.wait_frame, …)` 让事件循环默认执行器扩张到约 16 线程，
  空闲也不回收（不占 CPU，仅增加任务计数）。
- 动作：为 stream 轮询使用专用执行器，或改用原生 asyncio 等待。
- 验收标准：空闲容器 `pids.current` 从约 20 降到约 8；MJPEG 帧率与延迟无回归
  （用 `.artifacts/render_toggle_check.sh` + ffmpeg 实测帧率）。

---

## NS-7（可选研究，需授权）训练收敛性验证

- 动作：对 `gym:InvertedPendulum-v5` 训练 ≥20 万步，记录学习曲线并与随机基线对比。
- 验收标准：明确区分「链路可用」与「收敛」；给出多种子曲线与均值。

---

## NS-8（P3 完善）真实机器人/复杂接触任务模板

- 背景：仓库现有三个示例（单摆/双摆/静态场景），可作为 MJCF 模板，但没有接触丰富的任务。
- 动作：新增一个使用 `gym` 类型的本地注册模块示例（含 `MultiInputPolicy` 观测字典），
  并在 `envs/README.md` 中记录该路径的验收步骤。
- 验收标准：`smoke_test --all` 覆盖；浏览器可运行；能训练 PPO 并回放；
  CI 的 `required` 集合与 `validate_manifests.py` 同步更新。

---

## 给下一轮 Agent 的提醒

1. **先读** `AGENTS.md`（尤其「按需渲染」与「viewer 线程预算」两条不变量）与 `latest.md`。
2. 改动 viewer 渲染路径时，**必须**用真实 API + 真实 MJPEG 订阅复测
   `.artifacts/render_toggle_check.sh`（单元测试替身无法发现“无人订阅却仍渲染”或“有订阅却不出帧”）。
3. 性能结论一律用 cgroup `cpu.stat` 采样（`sampler.py`），不要用 `docker stats` 的瞬时值。
4. 不要在没有实测的情况下改 `DEFAULT_RENDER_THREADS`（`tests/test_worker.py` 已 pin）。
5. 部署端口继续用 8010；不要动 8000 上属于其他项目的服务，也不要 `docker compose down -v`。
6. 新增测试时，重依赖一律用 `tests/test_integration.py::require`（严格模式下缺失即失败）。

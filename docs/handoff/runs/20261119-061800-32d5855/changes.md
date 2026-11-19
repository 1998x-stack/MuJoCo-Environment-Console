# Changes · 可审计文件清单

- `app/static/index.html` — 可访问的环境查询、telemetry、步数快捷设定、训练按钮状态和真实语义标签。
- `app/static/app.js` — 服务器会话状态投影、步数校验、选择状态、任务增量重绘和原文转义。
- `app/static/app.css` — 设计 tokens、三栏/两栏/纵向响应、min 44px 控件、focus-visible、reduced motion。
- `tests/ui_accessibility.test.mjs` — Node VM 契约测试，无第三方 DOM 依赖。
- `.github/workflows/ci.yml` — 新增 Node UI 测试 step，不削弱已有 Docker/物理烟雾测试。
- `README.md` 与 `docs/UI_UX_PRO_MAX_DESIGN.md` — 使用方式、事实含义与人工验收。
- `docs/handoff/` — 本轮独立追加记录；历史 run 目录不动。

未改 `app/sessions.py`、`app/worker.py`、`app/trainer.py`、`app/main.py`、模型资源、密码与训练产物。所有新增内容只为 UI/UX 目标。

- `base_main_sha`: f64bc8f5319754e3228bf626804ba408518c5171
- `dependency_sha`: 5ffa61598ad534ec8d81ec80ffa0b9a504ec0138
- `code_sha`: 32d5855e9231a893d980c722e6b51e3c3b4fdce7
- `ci_run_id`: 44470889792（创建时运行中；以 GitHub Actions 结论为准）

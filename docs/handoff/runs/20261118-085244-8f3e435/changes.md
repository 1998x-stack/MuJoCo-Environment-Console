# 变更清单 · 第三轮（2026-11-18）

## 提交顺序（语义分组，逐个可回滚）

| # | SHA | 标题 |
|---|---|---|
| 1 | `371b8ce` | `fix(viewer): publish render state through a shared event, not the command queue` |
| 2 | `3eee437` | `fix(catalog): ship the manifest schema in the image and make validation observable` |
| 3 | `483d5b2` | `feat(api): add a read-only GET /api/sessions inventory` |
| 4 | `0f6c4dc` | `ci: fail the job on any test failure, error, timeout or skipped test` |
| 5 | `5cf87de` | `chore(handoff): separate base/code/pr-head/validated SHAs and the test-count tiers` |
| 6 | `e042d66` | `fix(handoff): do not assume origin/main exists in the checkout` |
| 7 | 本轮文档提交 | `docs: record the round-3 concurrency, CI-gate and schema findings` |

`code_sha`（最后一个改动代码的提交）= `e042d66`；其后仅 `docs/`。

## 文件级变更

```text
app/sessions.py         render_requested 共享 Event；订阅计数与渲染状态同锁写入；
                        subscribe/unsubscribe/is_active/info/status/list；worker 启动失败抛 ValueError
app/worker.py           run_worker 接收 render_requested；每循环以事件为唯一真值；
                        旧 render 命令显式忽略（返回 ignored）
app/main.py             GET /api/sessions（只读公开投影）；流端点对非活跃会话返回 409；
                        /api/catalog 增加 schema 状态；lifespan 打印 schema 可用性
app/catalog.py          schema_status()（available/path/reason）；validator 缓存按 schema 路径失效
Dockerfile              COPY schemas ./schemas
.dockerignore           移除 schemas/（否则构建上下文缺目录，COPY 直接失败）
scripts/check_pytest_report.py  新增：JUnit XML 结构化门禁（0 failed / 0 errors / 0 skipped + 必测项）
scripts/handoff_metadata.py     新增：五个 SHA 机械推导 + base ref 回退与空区间告警
tests/test_sessions.py          竞态/边界测试（19 项）
tests/test_worker.py            事件为真值、旧命令被忽略（18 项）
tests/test_api.py                /api/sessions 鉴权与投影、流 409、catalog schema 字段
tests/test_catalog.py            schema_status 与缓存随路径失效
tests/test_integration.py        镜像/副本必须带 schema 且校验器真的会拒绝非法文档
tests/test_ci_report_check.py    新增：门禁自身不可静默失效（11 项）
tests/test_handoff_metadata.py  新增：SHA 分类、base 回退、浅克隆空区间（9 项）
.github/workflows/ci.yml        set -euo pipefail + timeout + JUnit + 结构化门禁 + git 安装
                                + 镜像内容检查 step（不挂载仓库）+ checkout fetch-depth: 0
docs/handoff/README.md          SHA 分类与测试档位约定、历史记录只增不改
docs/handoff/runs/20261118-053523-e422870/**  第二轮记录的两处错误以「修正记录」追加
docs/handoff/runs/20261118-085244-8f3e435/**  本轮记录（6 个文件）
docs/handoff/latest.md          本轮入口
docs/verification/2026-11-18-concurrency-and-ci-gate.md  本轮验证报告
README.md / docs/runbooks/ubuntu-deployment.md / docs/architecture/system-overview.md
                                新端点、CI 门禁、镜像内容检查与测试 git 依赖的说明
```

## 关键行为契约（本轮建立/澄清）

1. **渲染真值只有一个**：共享 `multiprocessing.Event`，与订阅计数同锁写入；命令队列不再承载渲染开关，
   历史 `render` 命令被忽略。
2. **已关闭/已死亡的会话不能被复活**：`subscribe()` 对非活跃会话为 no-op；流端点对非活跃会话 409。
3. **测试结论必须标注档位与 `code_sha`/`validated_sha`**（见 `docs/handoff/README.md`）。
4. **CI 的"绿"只来自结构化判定**：`scripts/check_pytest_report.py`，且必测的物理集成测试必须真的执行过。
5. **镜像内容必须在"不挂载仓库"的前提下验证**：挂载 `/work` 时 `import app` 指向仓库副本，
   证明不了镜像自带的 `/app`。
6. **杀青前必须核对 `.dockerignore`**：新增随镜像发布的目录要先确认没被排除。

## 与本轮的假设/取舍

- 未引入任何依赖或大版本升级；`jsonschema` 仍是运行时依赖（第二轮加入），本轮只把它真正"送达"镜像。
- 未修改训练器、RL 算法、前端 UI 逻辑（`app/static/*` 本轮零改动）。
- E2E 判定方式改动只收紧服务端要求（非 `net::ERR_ABORTED` 的请求失败一律判失败），未放宽对产品的检查。

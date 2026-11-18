# Agent Handoff 协议

本目录是「上一轮 Agent → 下一轮 Agent」的唯一交接通道。**不要用 Handoff 代替真实源码**：
任何与本机/远端 HEAD 行为冲突的记录，一律标记 `STALE` 并重新验证。

## 目录约定与 SHA 分类

### 五个必须分开记录的 SHA

同一个提交号曾经同时被当作「代码版本」和「文档版本」使用，导致 CI 证据无法对应到具体代码。
因此每轮必须区分下列字段（可由 `python scripts/handoff_metadata.py --ci-run-id <id>` 自动推导）：

| 字段 | 含义 | 取值方式 |
|---|---|---|
| `base_sha` | 本轮起点的 merge base | `git merge-base HEAD origin/main` |
| `code_sha` | **最后一个改动非文档文件的提交**（行为被验证的那个） | 见下 |
| `pr_head_sha` | PR 当前指向的提交（可能只是文档提交） | `git rev-parse HEAD` |
| `validated_sha` | 记录的证据实际对应的提交，默认等于 `code_sha` | 显式记录 |
| `ci_run_id` | 产出证据的 Actions run id | 显式记录 |

**硬性要求**：给测试/CI 结论标注版本时**只能**引用 `code_sha`（或 `validated_sha`）。
若 `pr_head_sha != code_sha`，必须在 `latest.md` 与 run 记录里**显式写出**这两者，并说明
「其后提交仅改动 docs」。禁止把文档提交称为「代码 tip」。

代码路径（改动即视为 code）：`app/`、`envs/`、`scripts/`、`tests/`、`schemas/`、`.github/`、
`Dockerfile`、`compose.yaml`、`requirements*.txt`、`pytest.ini`；
文档路径：`docs/`、`AGENTS.md`、`README.md`。

### 测试计数必须注明运行环境

同一份测试在不同依赖集合下 `passed/skipped` 不同，只写数字不可审计。必须写清是下面哪一档：

| 档位 | 环境 | 说明 |
|---|---|---|
| 轻量（CI job 1） | 宿主 `python` + `fastapi uvicorn httpx pytest jsonschema`，**无 numpy/MuJoCo** | 依赖 MuJoCo 的集成测试会 skip（预期） |
| 完整镜像（非严格） | 部署镜像内 `pytest -q`，未设 `CONSOLE_TEST_REQUIRE_PHYSICS` | 物理测试真实执行，守门测试按设计 skip |
| 严格（CI 强制，`skipped == 0`） | 部署镜像内 + `CONSOLE_TEST_REQUIRE_PHYSICS=1` + git | 唯一可作为「测试全绿」依据的档位 |

### 目录约定

```text
docs/handoff/
├── README.md            本文件：协议说明
├── latest.md            唯一入口索引，每轮结束覆盖更新
└── runs/
    └── YYYYMMDD-HHMMSS-<short-sha>/
        ├── summary.md           本轮做了什么、结论、遗留
        ├── environment.json     结构化机器环境与测试状态
        ├── issues.md            问题清单（含根因、修复、验证）
        ├── test-matrix.md       分层测试矩阵与证据路径
        ├── changes.md           代码/文档变更清单与提交
        └── next-steps.md        下一轮优先级与验收标准
```

历史 run 目录**只增不改**：不重写既有结论，发现错误一律追加「修正记录」并注明日期、原值、真值与依据。

## 每轮开始时

1. `git fetch origin --prune`；记录 `BASE_SHA`、`origin/main` SHA、是否存在未合并 PR。
2. 读 `AGENTS.md`、`docs/handoff/latest.md`、最近一次 run 的全部文件。
3. `git log --oneline <上次 final_sha>..origin/main` 与 `git diff` 分析增量；
   确认上次未解决问题是否已被其他提交修复。
4. 判断 `latest.md` 是否 `STALE`（与 HEAD 行为不符），是则重新验证并注明。

## 每轮结束时

1. 新建 run 目录并写全六个文件。
2. 覆盖更新 `latest.md`（含五个 SHA 字段）。
3. 原始证据写 `.artifacts/runs/<run-id>/`（gitignored）；只把脱敏摘要提交到 `docs/`。
   若发现历史 run 记录有误，**不要静默改写**：在原文件追加「修正记录」段落，写明原值、真值与
   判定依据（保持可审计），并遵守本目录的「只增不改」原则。
4. 记录 `BASE_SHA`、`code_sha`、`pr_head_sha`、`validated_sha`、`ci_run_id`、分支、PR。

## 脱敏红线

**不得**写入仓库：控制台密码、GitHub Token、SSH 私钥、Cookie、API Key；
公网 IP、真实主机名、用户名；未经清洗的系统日志。
局域网私有 IP 也仅在必要时出现，且应使用占位形式。

## 状态取值

`PASS` / `FAIL` / `PARTIAL` / `BLOCKED` / `NOT_RUN`。
未实际执行的项一律 `NOT_RUN` 或 `BLOCKED`，禁止推测为 `PASS`。

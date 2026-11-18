# Agent Handoff 协议

本目录是「上一轮 Agent → 下一轮 Agent」的唯一交接通道。**不要用 Handoff 代替真实源码**：
任何与本机/远端 HEAD 行为冲突的记录，一律标记 `STALE` 并重新验证。

## 目录约定

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

历史 run 目录**只增不改**。

## 每轮开始时

1. `git fetch origin --prune`；记录 `BASE_SHA`、`origin/main` SHA、是否存在未合并 PR。
2. 读 `AGENTS.md`、`docs/handoff/latest.md`、最近一次 run 的全部文件。
3. `git log --oneline <上次 final_sha>..origin/main` 与 `git diff` 分析增量；
   确认上次未解决问题是否已被其他提交修复。
4. 判断 `latest.md` 是否 `STALE`（与 HEAD 行为不符），是则重新验证并注明。

## 每轮结束时

1. 新建 run 目录并写全六个文件。
2. 覆盖更新 `latest.md`。
3. 原始证据写 `.artifacts/runs/<run-id>/`（gitignored）；只把脱敏摘要提交到 `docs/`。
4. 记录 `BASE_SHA`、`final_sha`、分支、PR、CI run 链接。

## 脱敏红线

**不得**写入仓库：控制台密码、GitHub Token、SSH 私钥、Cookie、API Key；
公网 IP、真实主机名、用户名；未经清洗的系统日志。
局域网私有 IP 也仅在必要时出现，且应使用占位形式。

## 状态取值

`PASS` / `FAIL` / `PARTIAL` / `BLOCKED` / `NOT_RUN`。
未实际执行的项一律 `NOT_RUN` 或 `BLOCKED`，禁止推测为 `PASS`。

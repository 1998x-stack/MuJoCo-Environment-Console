# AGENTS.md — MuJoCo Environment Console 工程规范

本文件面向 Pi / Codex / 其他 Coding Agent，以及需要在本机 Ubuntu 服务器上继续迭代的人类工程师。
目标不是重复 README，而是说明「怎么改、怎么验证、怎么交棒」。

## 1. 项目目标

自托管、局域网优先的 MuJoCo 仿真与强化学习控制台：浏览器管理环境、查看 MJPEG 实时仿真、运行 PPO/SAC 训练并回放策略模型。当前定位为 **CPU-first MVP**，不是多租户研究平台。

## 2. 真实目录结构

```text
app/
├── main.py            FastAPI 应用：认证、目录、会话、MJPEG、训练 API
├── catalog.py         环境发现与白名单校验（gym / fetch / envs/*/manifest.json）
├── env_factory.py     统一适配器入口 make_environment()
├── custom_env.py      通用 MJCF 姿态跟踪 Env（MJCFTrackingEnv）
├── sessions.py        ViewerSession + SessionManager（每 viewer 一个 OS 进程）
├── worker.py          子进程仿真循环：随机/策略驱动、JPEG 编码
├── jobs.py            训练任务持久化、进程组生命周期、环境指纹
├── trainer.py         训练子进程：SB3 训练 + 独立评估
└── static/            index.html / app.js / app.css（无构建步骤的原生前端）
envs/<name>/           manifest.json + MJCF/Python 环境（容器内只读挂载）
schemas/               环境 manifest JSON Schema
scripts/               deploy.sh / smoke_test.py / training_smoke_test.py / import_menagerie.sh
tests/                 pytest 单元与集成测试
docs/                  架构、运维手册、验证报告、Handoff
.artifacts/            本机验证原始证据（已 gitignore，禁止提交）
```

数据与运行时目录：`data/runs/<run_id>/`（status.json / environment.json / output.log / model.zip）。
容器内路径：`/app/envs`（只读）、`/app/data`（读写）。`CONSOLE_ENV_ROOT`、`CONSOLE_DATA_ROOT` 可覆盖。

## 3. 核心架构与不变量

- **进程隔离**：每个 viewer 一个 `multiprocessing` spawn 子进程（独立 OpenGL context）；每个训练任务一个独立进程组（`start_new_session=True`）。
- **viewer 按需渲染**：子进程只在**有订阅者**时才创建光栅化器并出帧（`ViewerSession.subscribe()/unsubscribe()`；MJPEG 端点为每个连接自动订阅）。无人订阅时仍继续物理步进与状态上报。任何程序化读取 `wait_frame()` 的代码都必须先 `subscribe()`，否则永远收不到帧。
- **viewer 线程预算**：`apply_process_limits()` 在导入 numpy/MuJoCo 前设置 `LP_NUM_THREADS`（默认 2）与 BLAS/OpenMP 线程数（默认 1）。默认线程池会按核数创建线程且空转：本机 12 线程下 1 个 viewer 空闲订阅时约 520% CPU，限制后约 170%，帧率反而更高。不要在没有实测数据的情况下调整这两个默认值（`tests/test_worker.py` 对此有 pin）。
- **渲染**：服务器端 OSMesa 离屏渲染（`MUJOCO_GL=osmesa`），JPEG 经 MJPEG 传给浏览器。实测渲染占 viewer 循环开销的 99.5% 以上（物理 0.12 ms、JPEG 编码 0.84 ms、策略推理 0.19 ms，而单帧渲染约 30 ms 墙钟 / 约 490 ms CPU）。
- **MJPEG 分帧必须符合 RFC 2046**：分片以 `--frame\r\n` 开始、以**真实 CRLF** 结束。绝不要写成 `b'\\r\\n'`（字面量反斜杠），浏览器能容错但 ffmpeg/OpenCV/VLC 会完全解析失败。
- **模型—环境绑定**：`jobs.fingerprint()` 对 MJCF 入口 XML 与目录内全部资源（含 mesh/texture/include）取哈希；环境变更后旧模型拒绝回放。
- **并发上限**：单训练任务、`MAX_VIEWERS` 个 viewer、空闲会话自动回收。这些是产品行为，不是缺陷。
- **认证**：单密码 + 随机 session token（进程内存，`--workers 1`）；按 IP 限流；`--no-proxy-headers` 使反代场景默认安全。

## 4. 依赖与版本约束

在 `requirements.txt` 中固定，**不要为了追新而升级**：

| 组件 | 版本 |
|---|---|
| MuJoCo | 3.3.7 |
| Gymnasium | 1.4.0 |
| Gymnasium Robotics | 1.4.2 |
| Stable-Baselines3 | 2.9.2 |
| PyTorch | 2.9.0 CPU（`--index-url .../whl/cpu`） |

升级 MuJoCo 或 Gymnasium-Robotics 大版本前，必须回归：全部 Fetch 环境 reset/step/render、16+ 环境 smoke、PPO/SAC 短训练与策略回放。

MuJoCo 资产注意：**ASCII STL 在 3.3.7 下会报 `number of faces should be between 1 and 200000`，请使用二进制 STL**。

## 5. 推荐开发与验证命令

```bash
# 静态检查（宿主机即可）
python3 -m compileall -q app tests scripts
node --check app/static/app.js
bash -n scripts/*.sh
python3 -m json.tool schemas/environment.schema.json > /dev/null
python scripts/validate_manifests.py          # schema + 发现诊断（需要 jsonschema）

# 单元测试：需要 fastapi/uvicorn/httpx/pytest/jsonschema
python -m pytest -q

# 完整测试（含依赖 MuJoCo 的集成测试）。CONSOLE_TEST_REQUIRE_PHYSICS=1 会把
# 「依赖缺失」从 skip 变成 fail，CI 用它保证集成测试真的执行：
docker run --rm --user 0:0 -e HOME=/tmp -e CONSOLE_TEST_REQUIRE_PHYSICS=1 \
  -v "$PWD":/work -w /work mujoco-environment-console:local \
  sh -c 'pip install --quiet httpx pytest jsonschema && python -m pytest -q -rs -p no:cacheprovider'

# 部署（唯一受支持的入口，会生成 .env、构建镜像、等待健康检查）
bash scripts/deploy.sh

# 容器内验证
docker compose ps
curl -fsS http://127.0.0.1:${CONSOLE_PORT:-8000}/healthz
docker compose exec -T console python scripts/smoke_test.py --render --all
docker compose exec -T console python scripts/training_smoke_test.py
```

宿主机缺少 `python3-venv` 时，用镜像跑测试而不污染系统 Python：

```bash
docker run --rm --user 0:0 -e HOME=/tmp -v "$PWD":/work -w /work mujoco-environment-console:local \
  sh -c 'pip install --quiet httpx pytest jsonschema && python -m pytest -q -p no:cacheprovider'
```

## 6. 数据与安全约束

- 不执行 `docker compose down -v`、`docker system prune -a --volumes`、`rm -rf data` 等破坏性命令。
- `.env`（含控制台密码）、`data/`、`.artifacts/` 一律不提交。提交前执行 `git status --short` 与 `git diff --check` 复核。
- 不删除 `data/runs/` 中他人的训练记录与模型。
- 服务器上可能存在**其他业务服务**（本机端口 8000 曾被非本项目服务占用）。部署前必须确认端口空闲，用 `CONSOLE_PORT` 避让，绝不 `docker kill`/删除其他容器。
- 未经明确授权不要把服务暴露到公网，不要开启 TLS 终止或反向代理绕过。
- 环境 manifest 中的 `registration_module` 会在子进程中导入任意本地 Python 代码，只允许可信来源。

## 7. Git 工作流

1. `git fetch origin --prune`，记录 `BASE_SHA = git rev-parse origin/main`。
2. 从最新 `origin/main` 创建分支：`agent/<用途>-YYYYMMDD-HHMM`。
3. 禁止 `git reset --hard`、`git clean -fd`、`git push --force`、直接推送 `main`。
4. 提交信息使用 `fix: / test: / docs: / refactor: / perf: / ci: / chore:` 前缀，一次提交一个语义。
5. 推送分支并创建 PR；不自动合并。

## 8. CI 规则

`.github/workflows/ci.yml` 在 `ubuntu-24.04` 上执行：语法检查 → 单元测试（含 manifest schema 校验）→ 用 `scripts/deploy.sh` 真实部署（端口 18000）→ 断言物理依赖版本 → 认证 API + **MJPEG RFC 2046 分帧断言** → 18 环境 smoke + PPO/SAC 训练。

任何「让 CI 变绿」的手段（跳过测试、放宽断言、删除失败环境、吞异常、关闭认证）都视为违规。修改 CI 断言时必须同时说明它现在能捕获哪一类缺陷。

## 9. Handoff 读写流程

**每次开始工作前必读**（缺一不可）：

1. `AGENTS.md`（本文件）
2. `docs/handoff/latest.md`
3. `docs/handoff/runs/<最近一次>/next-steps.md`
4. `git log --oneline -10` 与 `git diff <上次 final_sha>..origin/main`

**每次结束工作后必须写**：

1. 新建 `docs/handoff/runs/YYYYMMDD-HHMMSS-<short-sha>/`，包含
   `summary.md`、`environment.json`、`issues.md`、`test-matrix.md`、`changes.md`、`next-steps.md`。
2. 覆盖更新 `docs/handoff/latest.md`（唯一入口索引）。
3. 历史 run 目录只增不改。
4. 若 Handoff 与当前 HEAD 行为冲突，标记为 `STALE` 并重新验证，不要以文档代替源码。

原始日志放 `.artifacts/runs/<run-id>/`（`docker-build.log`、`docker-service.log`、`smoke-test.log`、`training-test.log`、`resource-samples.csv`、`browser/`）。只把脱敏摘要写入 `docs/`。

## 10. 已知工程边界

- 通用 MJCF 适配器只有基础姿态跟踪奖励，**不等于**研究级任务定义；短 smoke 训练只证明链路可用，**不证明收敛**。
- 无 `dm_control` / `robosuite` / Playground 原生适配器；无 GPU 训练；无多用户隔离。
- `sessions` 只在进程内存中，服务重启后全部失效（训练状态则从 `data/runs` 恢复）。
- 没有「列出当前 viewer 会话」的 API：被浏览器遗弃的会话会占用 `MAX_VIEWERS` 槽位，直到 `SESSION_IDLE_SECONDS` 后由回收线程清理。**但已不再持续渲染**（占用约 1.5% CPU，而不是约 500%），因此影响从「资源问题」降级为「槽位问题」。
- viewer 的 CPU 现在是「除非有人在看，否则几乎为零」。若发现 viewer CPU 很高，先用 `docker compose exec -T console python - <<'PY'` 读取 `/api/sessions/<id>` 中的 `subscribers` / `render` 字段确认是否真有订阅者。
- trainer 约 2.9 核 / 17 线程（PPO 短训练实测）；与 viewer 并发时容器总量约 4.8 核，宿主仍有约 55% 空闲。容器默认无 CPU/内存上限，需要时可设 `CONSOLE_CPU_LIMIT`/`CONSOLE_MEM_LIMIT`。
- PPO 实际步数会向上取整到 rollout batch（请求 1000 步可能执行 2048 步），这是预期行为。

## 11. Definition of Done

变更必须同时满足：

- [ ] 真实运行验证（不是只读代码或只看 CI 绿灯）。
- [ ] 新增/修改行为有回归测试，或说明为何无法测试。
- [ ] `python -m pytest -q` 全绿；涉及环境时 `smoke_test.py --render --all` 全绿。
- [ ] 涉及 viewer 行为时，同时用真实 API + 真实 MJPEG 订阅验证（`subscribe/unsubscribe` 计数与 `render` 状态），不能只依赖单元测试替身。
- [ ] 涉及性能/资源结论时，必须给出修改前后的可比较数据（cgroup `cpu.stat` 采样，而不是 `docker stats` 的瞬时值）。
- [ ] 涉及训练/回放时，PPO 与 SAC 的端到端路径均通过。
- [ ] 未泄露敏感信息；`git diff` 无无关文件。
- [ ] README / AGENTS.md / Handoff 与实际行为一致。
- [ ] 无法验证的项一律标记 `NOT_RUN` / `BLOCKED`，绝不谎报 PASS。

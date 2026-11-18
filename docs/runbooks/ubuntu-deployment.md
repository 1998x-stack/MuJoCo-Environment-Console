# Runbook：在 Ubuntu 服务器上部署 MuJoCo Environment Console

适用范围：Ubuntu 22.04 / 24.04，Docker Engine + Compose v2，x86_64 或 aarch64，**无需 GPU**。

## 0. 决策清单（动手前确认）

- [ ] 目标机器是 Ubuntu 宿主机（不是 macOS、不是容器内部）？`uname -a`、`cat /etc/os-release`。
- [ ] `CONSOLE_PORT`（默认 8000）**没有被其他业务占用**？`ss -ltnp | grep ":8000"`。
      本服务器上 8000 曾被另一个项目占用，因此实际部署使用 `CONSOLE_PORT=8010`。
- [ ] 当前用户属于 `docker` 组？`id -nG | tr ' ' '\n' | grep -x docker`。
- [ ] 磁盘 ≥ 5 GiB 可用？构建镜像约 1.5 GiB，运行时镜像约 435 MiB。
- [ ] `data/runs/` 是否有需要保留的训练记录？**先备份再升级**。

## 1. 标准部署

```bash
git clone https://github.com/1998x-stack/MuJoCo-Environment-Console.git
cd MuJoCo-Environment-Console

# 若默认端口被占用，先手动生成 .env 并改端口（deploy.sh 不会覆盖已存在的 .env）
cp .env.example .env
PORT=$(openssl rand -hex 20)
sed -i "s/REPLACE_WITH_STRONG_UNIQUE_PASSWORD/${PORT}/" .env
sed -i "s/^CONSOLE_PORT=.*/CONSOLE_PORT=8010/" .env
chmod 600 .env

bash scripts/deploy.sh
```

`deploy.sh` 会：校验 docker/compose/python3 → （必要时）生成 `.env` 与随机密码 →
追加 `CONSOLE_UID/CONSOLE_GID`（保证容器内进程与挂载目录同权限）→ `chmod 600 .env` →
`mkdir -p data/runs` → 校验密码与端口 → `docker compose config --quiet` → `up -d --build` →
最多等待 120 s 健康检查。

## 2. 部署后验收（按顺序）

```bash
docker compose ps                                   # 期望 Up (healthy)，端口映射到 CONSOLE_PORT
curl -fsS "http://127.0.0.1:8010/healthz"           # {"ok":true,"service":"mujoco-console"}
docker compose logs --no-color --tail=50 console

docker compose exec -T console python - <<'PY'
import importlib.metadata, mujoco
assert mujoco.__version__ == '3.3.7'
assert importlib.metadata.version('gymnasium-robotics') == '1.4.2'
print('pins ok')
PY

docker compose exec -T console python scripts/smoke_test.py --render --all
# 镜像自带内容必须在**不挂载仓库**的前提下验证（挂载时 import app 指向仓库副本）：
docker run --rm mujoco-environment-console:local python scripts/validate_manifests.py
docker run --rm mujoco-environment-console:local python -c \
  "from app import catalog; s = catalog.schema_status(); assert s['available'], s; print(s)"
docker compose exec -T console python scripts/training_smoke_test.py   # 建议加 timeout 600
```

完整单测（必须 `0 skipped`；镜像内没有 git，而元数据测试需要它，所以要先装）：

```bash
docker run --rm --user 0:0 -e HOME=/tmp -e CONSOLE_TEST_REQUIRE_PHYSICS=1 \
  -v "$PWD":/work -w /work mujoco-environment-console:local \
  sh -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && \
         apt-get install -y -qq --no-install-recommends git && \
         git config --global --add safe.directory /work && \
         pip install --quiet httpx pytest jsonschema && \
         python -m pytest -q -rs -p no:cacheprovider'
```

CI 用 `scripts/check_pytest_report.py` 读 JUnit XML 做结构化判定：任何 failed / error /
skipped、或必测的物理集成测试没真的执行，都会使 job 失败（不再用管道后的 `tee` 状态或
`"passed"` 字符串判定）。

浏览器打开 `http://<服务器局域网IP>:<CONSOLE_PORT>`，密码在服务器 `.env` 的
`MUJOCO_CONSOLE_PASSWORD`（不要复制到聊天/工单/日志）。

## 3. 局域网与安全边界

- 容器端口发布为 `0.0.0.0:<CONSOLE_PORT>`，局域网内可直接访问。用 VPN 远程访问。
- **不要**把该端口映射到公网、不要只靠单密码替代 HTTPS。
- 若必须经过反向代理：设置 `COOKIE_SECURE=1` 并正确终止 TLS。注意 uvicorn 以
  `--no-proxy-headers` 运行，登录限流按代理自身 IP 统计（所有客户端共享一个桶）。
- 只导入可信的 `envs/` 内容：`registration_module` 会在子进程中执行任意 Python。

## 4. 数据保护

```bash
# 备份（唯一需要备份的目录）
tar czf mujoco-console-data-$(date +%Y%m%d).tgz data/runs

# 重建而不丢数据
git pull
docker compose up -d --build
```

禁止：`docker compose down -v`、`docker system prune -a --volumes`、`rm -rf data`。
这些命令会删除卷、镜像与其他项目的资源。本机存在多组其他业务的容器与网络。

## 5. 常见故障排查

| 症状 | 检查 | 处理 |
|---|---|---|
| 部署脚本报 `Console did not become healthy` | `docker compose logs --tail=120 console` | 看 uvicorn 启动异常：密码缺失 503、依赖未装、端口冲突 |
| 容器 `unhealthy` | `docker inspect --format '{{json .State.Health}}' mujoco-console` | 健康检查是 `curl -fsS /healthz`；确认 curl 存在于镜像且 8000 未被占用 |
| 页面能开但无画面 | `GET /api/sessions/<id>` 的 `subscribers`/`render`，再看 `error` 与容器日志 | `render:false`+`subscribers:0` 表示没有订阅者在看（属正常）；有订阅者却不出帧时看 `error`（多为 OSMesa 缺失或 `MUJOCO_GL` 被改写） |
| **viewer CPU 很高** | `GET /api/sessions/<id>` 的 `subscribers`/`render`；`docker stats` | 有订阅者时属正常（见 6.1 节的实测表）；若无订阅者仍在渲染，说明按需渲染回归，检查 `subscribe/unsubscribe` |
| 环境目录「看不见」 | `/api/catalog` 响应中的 `problems`；或 `python scripts/validate_manifests.py` | 每个被跳过的目录都带 `reason`（`missing_xml`、`xml_outside_environment`、`unsupported_kind` …）与 `detail` |
| 浏览器有画面但 ffmpeg 抓不到流 | 检查 MJPEG 分帧是否为 CRLF（见 `docs/architecture/system-overview.md` 第 4 节） | `python -c` 断言 `b'\r\n--frame' in data` |
| 登录返回 429 | 该 IP 在窗口内失败次数超限 | 等待 `LOGIN_WINDOW_SECONDS`，或 `docker compose restart console` 清空内存计数 |
| 无法新建 viewer（400 Viewer limit reached） | `curl -b <cookie> http://127.0.0.1:8010/api/sessions` 列出存活会话 | 第三轮起有**只读清单接口**：先看 `subscribers`/`render_requested`/`idle_seconds`，确认是被遗弃的会话后用 `POST /api/sessions/<id>/stop` 立即释放槽位（不必重启容器，也不必修 `SESSION_IDLE_SECONDS`） |
| `problems` 为空但 manifest 明明不合法 | `curl -b <cookie> …/api/catalog` 看 `schema.available` 与 `schema.reason`；或 `docker run --rm <image> python -c "from app import catalog; print(catalog.schema_status())"` | `available:false` 说明 **manifest schema 校验被关闭**（曾是镜像漏拷 `schemas/` 所致）：检查 `Dockerfile` 的 `COPY schemas` 与 `.dockerignore` 是否排除了 `schemas/`。lifespan 也会打 WARNING |
| 流请求返回 409 | `GET /api/sessions` 里该会话的 `alive`/`state` | worker 已退出：这是预期的快速失败（避免浏览器无限等待空流）；停止该会话后重建 |
| 训练立即 `failed` | `cat data/runs/<id>/output.log` 与 `status.json` | 常见：环境不可训练、注册模块导入失败、OOM。退出码 137/SIGKILL 会明确提示「容器内存上限 / 外部 kill / 宿主 OOM」 |
| 重启后训练变 `interrupted` | `cat data/runs/<id>/status.json` | 预期行为：服务关停会终止训练进程组并标注原因 |
| 模型无法回放 | 同上 `status.json` 的 `fingerprint` 与当前环境比对 | 环境定义变更后必须重新训练（设计如此） |
| 权限错误写 `data/` | `ls -ld data data/runs` | 确认 `.env` 的 `CONSOLE_UID/GID` 与宿主机目录属主一致 |

## 6. 运维命令速查

```bash
docker compose ps
docker compose logs -f console
docker compose restart console
docker compose stop console && docker compose start console
docker stats --no-stream mujoco-console
docker compose exec -T console ps -eo pid,ppid,etime,args --no-headers   # 检查残留 worker/trainer
du -sh data/runs
```

正常空闲时容器内应只有 `docker-init` 与 `uvicorn` 两个进程。若看到
`multiprocessing.spawn` 或 `app.trainer`，说明有活跃 viewer（且确有订阅者）或训练正在运行。

## 6.1 Viewer 资源调优（实测依据）

OSMesa/llvmpipe 是 CPU 软光栅化，viewer 的开销几乎全在渲染与线程空转上（见
`docs/architecture/system-overview.md` 第 8 节）。可调项都在 `.env`：

| 变量 | 默认 | 作用 | 何时调整 |
|---|---|---|---|
| `VIEWER_FPS` | 12 | 每 viewer 帧率（1–60） | 降帧率可线性降 CPU：6 fps 约 130%、8 fps 约 182%（640x480） |
| `VIEWER_WIDTH`/`VIEWER_HEIGHT` | 640/480 | 渲染分辨率（64–1920） | 320x240 比 640x480 约省 24%（固定开销占大头，不能只靠降分辨率） |
| `VIEWER_RENDER_THREADS` | 2 | llvmpipe 光栅化线程数（1–64） | 重场景或大分辨率可提到 4；降到 1 会使帧率跌到约 7.9 fps |
| `VIEWER_BLAS_THREADS` | 1 | viewer 进程内 BLAS/OpenMP 线程 | 一般不用改，渲染不需要 BLAS |
| `CONSOLE_CPU_LIMIT` | 不设 | 容器 CPU 上限（cpus） | 与其他业务共存且希望有硬上限时 |
| `CONSOLE_MEM_LIMIT` | 不设 | 容器内存上限 | 同上；触发时会给出明确的 137/SIGKILL 训练错误信息 |

这些是 **viewer 专用**变量，不改变 trainer 的线程数（trainer 的 BLAS 线程仍由容器环境决定，
未设置时等于核数）。

调整后必须重新验证：`smoke_test.py --render --all`、浏览器画面是否流畅（不能只降 CPU 而把
帧率压到明显卡顿），以及训练与 viewer 并发时的表现。

渲染只发生在**有浏览器连接**时；关闭页面后 CPU 应回落到约 1–2%（实测：订阅中 169.5% →
断开后 1.6%，窗口 12 s，cgroup v2 `cpu.stat` 采样）。若否则属回归，先看 `GET /api/sessions`
的 `subscribers` 与 `render_requested`：

- 两个都为 0 但 CPU 仍高 → 按需渲染回归（检查订阅计数与 `render_requested` 事件是否同锁写入）；
- `subscribers` 不减 → 客户端未正常断开计数（检查 MJPEG generator 的 `finally`）。

枚举被遗弃会话（不会给会话续命）：

```bash
curl -s -b cookies.txt http://127.0.0.1:8010/api/sessions | python3 -m json.tool
# 释放某个槽位：
curl -s -b cookies.txt -X POST http://127.0.0.1:8010/api/sessions/<id>/stop
```

## 7. 可选的 MuJoCo Menagerie 导入

```bash
bash scripts/import_menagerie.sh    # 需要访问 github.com，会克隆到 data/menagerie-src
```

导入的环境被标记为 `view_only`，只能演示、不能训练。请遵守各模型目录的许可证。

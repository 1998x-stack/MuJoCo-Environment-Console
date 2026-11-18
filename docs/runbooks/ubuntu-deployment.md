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
docker compose exec -T console python scripts/training_smoke_test.py   # 建议加 timeout 600
```

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
| 页面能开但无画面 | `docker compose exec -T console python -c "import mujoco;print(mujoco.__version__)"`、查看会话 `error` 字段 | 多为 OSMesa 缺失或 `MUJOCO_GL` 被改写；确认 `.env` 中 `MUJOCO_GL=osmesa` |
| 浏览器有画面但 ffmpeg 抓不到流 | 检查 MJPEG 分帧是否为 CRLF（见 `docs/architecture/system-overview.md` 第 4 节） | `python -c` 断言 `b'\r\n--frame' in data` |
| 登录返回 429 | 该 IP 在窗口内失败次数超限 | 等待 `LOGIN_WINDOW_SECONDS`，或 `docker compose restart console` 清空内存计数 |
| 无法新建 viewer（400 Viewer limit reached） | 有被遗弃的浏览器会话占用槽位 | 等待 `SESSION_IDLE_SECONDS` 自动回收，或重启容器 |
| 训练立即 `failed` | `cat data/runs/<id>/output.log` | 常见原因：环境不可训练、注册模块导入失败、显存/内存不足 |
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
`multiprocessing.spawn` 或 `app.trainer`，说明有活跃 viewer/viewer 尚未回收或训练正在运行。

## 7. 可选的 MuJoCo Menagerie 导入

```bash
bash scripts/import_menagerie.sh    # 需要访问 github.com，会克隆到 data/menagerie-src
```

导入的环境被标记为 `view_only`，只能演示、不能训练。请遵守各模型目录的许可证。

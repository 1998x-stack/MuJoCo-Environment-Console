# MuJoCo Environment Console

面向 Ubuntu 的自托管 MuJoCo 环境控制台：通过局域网浏览器管理环境、观看随机策略驱动的实时仿真、运行 PPO/SAC 训练并回放已训练模型。

## 获取源码

完整源码包包含 FastAPI 服务、Web UI、环境注册器、训练/仿真 worker、Docker 部署配置、测试、环境 Manifest Schema 和环境扩展说明。

仓库为控制二进制体积采用压缩源码分片存储：
- [源码分片目录](release/source-parts/)
- [源码重组脚本](scripts/assemble-source.sh)

先克隆并重组源码包：

```bash
git clone https://github.com/1998x-stack/MuJoCo-Environment-Console.git
cd MuJoCo-Environment-Console
bash scripts/assemble-source.sh
tar -xJf release/mujoco-console-source.tar.xz
```

解压会将项目文件放入仓库根目录。归档 SHA-256：

`2721a58736c66bc79bdce5384c217d6afd7ef46fcd3bf445899f5f7475964fed`

## Ubuntu 部署

部署要求 Ubuntu 22.04/24.04、Docker Engine 和 Docker Compose v2。首次构建需要联网下载 Ubuntu 软件包、Python 依赖和 CPU 版 PyTorch。

```bash
bash scripts/deploy.sh
hostname -I
```

在同一局域网浏览器打开：

`http://<Ubuntu-LAN-IP>:8000`

访问密码由 `scripts/deploy.sh` 首次启动时生成，保存在项目目录 `.env`。

## 首版能力

- Gymnasium MuJoCo v5：11 个标准控制/运动环境。
- Gymnasium Robotics Fetch：4 个可选机械臂环境（默认启用安装）。
- 本地 MJCF/XML 环境目录自动发现。
- Random 随机动作演示、PPO/SAC 训练、训练日志、模型检查点与策略回放。
- 独立仿真进程和训练进程；本地数据持久化。
- 浏览器通过 HTTP/MJPEG 访问，无需客户端安装 MuJoCo。
- 局域网访问密码；默认不开放公网访问。

## 扩展边界

自定义 MJCF 环境放入 `envs/<name>/manifest.json` 与 XML/资源文件；Gymnasium 插件可按项目文档注册。MuJoCo Menagerie 模型资源不自动等于强化学习任务，必须另行定义观测、动作、奖励和终止条件。dm_control、robosuite、MuJoCo Playground 适配器列入后续路线，尚未宣称首版开箱即用。

## 验证状态

仓库 CI 会重组归档并执行 Python 语法、pytest、JavaScript、Shell 和 JSON Schema 检查。当前测试报告为 6 项通过、2 项需要 MuJoCo/Gymnasium 物理依赖的集成测试跳过。

尚未在真实 Ubuntu Docker 主机完成物理仿真、离屏渲染和 PPO/SAC 端到端实测。部署后请执行：

```bash
docker compose exec console python scripts/smoke_test.py --render
```

不要将 HTTP 登录服务直接暴露到公网。需要远程访问时使用 VPN 或正确配置 HTTPS 反向代理。
# MuJoCo Console · UI/UX Pro Max 设计系统与行为约束

> 2026-11-19 | 设计依据：[UI UX Pro Max Skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) 的 Accessibility → Interaction → Performance → Responsive → Typography → Data 规则。
>
> 本轮将这些通用规范结合原生 HTML / CSS / JavaScript 实施，没有引入 UI 框架、浏览器端 Python 执行或第三方 CDN。

## 1. 产品定位

这是 **实验员控制台**，不是营销展示页。主要用户通过可信局域网连接 Ubuntu 上的 MuJoCo 服务，完成环境选择、MJPEG 实时观看、随机/策略驱动、PPO/SAC 训练与训练日志查看。

三个操作区域：左侧环境资源目录；中心仿真画布、控制和服务端状态；右侧训练参数、任务与日志。小屏改上下流程：发现环境 → 观察仿真 → 调整参数/训练。

## 2. 信息层级与状态真实含义

| UI 位置 | 现实数据来源 | 不允许的误导 |
|---|---|---|
| LIVE 指示 | `GET /api/sessions/{id}` 的 `state`, `paused` | 把初始空闲显示成运行中 |
| 订阅者数量 | `subscribers` | 把页面存在等同于实际有 viewer |
| 渲染开关 | `render_requested` | 以此声称一定有真实帧或达到 12 FPS |
| 帧率 | 会话 `fps` 配置 | 当成测得的实时帧率 |
| 分辨率 | 会话 `width × height` | 仅用固定 640×480 冒充实际尺寸 |
| 训练进度 | `completed_steps / timesteps` | 宣称 PPO 实际步数永不超过用户请求值 |
| 平均奖励 | `average_reward` | 未评估时显示 `NaN` 或虚构 0 |
| 算法 | 用户选定 PPO/SAC | 不能把随机演示写为已学得策略 |

## 3. 设计规范

- 深海蓝中性表面；青绿色强调交互、暖金表示暂停、粉红表示错误。状态始终以文字配合，不能只依赖颜色。
- 基础正文 16px；核心标签与读数在 12–24px 区间，信息必须可读，移动端不再显示 7px 字体。
- 核心按钮、类别切换、运行操作、预设步数和输入的触控高度不小于 44px。
- 保留 `:focus-visible`，为不可见原生 radio 的选中卡添加焦点轮廓，提供跳过导航链接及具有上下文的控件标签。
- 高信息密度的 3 面板桌面布局，约 1280px 转两列，约 780px 转纵向；320–400px 时单列环境列表和 2×2 状态指标。
- 动画仅辅助变化，尊重系统 `prefers-reduced-motion`，无弹跳、模糊/玻璃、装饰性的持续动画。
- 展示成功与异常的区别：启动中、运行中、暂停、错误，以及来源字段未知（—）。仅在 API 认证成功且会话存在时显示动态状态。

## 4. 交互改进

1. **环境目录**：筛选后的数量和总数，`aria-pressed` 反映类别和选择状态；未安装依赖的环境保留但禁用。
2. **仿真监测**：在 MJPEG 画布下方展示 server-reported 订阅者、渲染请求、目标 FPS 和服务端画面规格，避免把渲染节流误判为进程停止。
3. **驱动**：随机/策略切换通过 `aria-pressed` 呈现；未有模型时保留真实错误提示，而不是显示成功。
4. **训练参数**：1 万 / 5 万 / 20 万快捷输入，整数字段验证范围 1,000–5,000,000，错误紧邻输入；提交请求期间禁用启动按钮，防止重复触发。
5. **训练列表**：只有后端结果变化才重新渲染，避免周期轮询打断按钮焦点；平均奖励为 null 时不显示数值。
6. **日志**：原生 dialog 使用 `aria-labelledby`，保留关闭按钮与原始输出。

## 5. 测试与未完成项

新增 `tests/ui_accessibility.test.mjs`（无需 DOM 第三方依赖，Node 内建 test + vm），覆盖搜索结果、HTML 转义、输入范围、控件状态、会话渲染语义、训练列表稳定性。
CI 增加 `node --test tests/ui_accessibility.test.mjs`，但它不是浏览器端全流程 UI 验收替代品。

```bash
node --check app/static/app.js
node --test tests/ui_accessibility.test.mjs
python -m pytest -q
```

**浏览器手工待测**（无目标服务器控制权限，不能宣称通过）：

- 1440×900、820×1180、390×844 和 320×568 下无横向滚动，按钮无遮挡；
- Tab/Shift+Tab、焦点轮廓、PPO/SAC radio、取消/日志交互；
- 0 与 1+ 订阅者切换时渲染请求指标真实随 API 变化；
- 未登录、会话报错、网络中断、训练任务 0 / running / completed 状态；
- 对有真实跑通 MJPEG 的 Ubuntu 环境截图/录屏并执行浏览器无障碍扫描。

后续可在经过数据量验证后添加奖励趋势、会话历史图表；本轮不虚构性能或训练效果。

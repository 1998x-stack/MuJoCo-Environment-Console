# Test matrix · 以代码 SHA 为准

| 档位 | 结果 | 证据 |
|---|---|---|
| JavaScript 静态解析 | PASS（编辑时 V8 语法解析） | 修改 app/static/app.js 后即时解析 |
| UI Node test | PASS（首轮 Actions） | PR #2 初始提交 `4c9fa659` 的 CI `44470848654` 中对应 step |
| Python lightweight | PASS（首轮 Actions） | 同上，完整严格镜像另行判定 |
| 当前代码 `32d5855` CI | IN_PROGRESS | `44470889792`（含后续 Docker/MuJoCo 验证） |
| 真实 Ubuntu/MJPEG 浏览器 E2E | NOT_RUN | 当前无服务器及网络访问授权 |
| 320/390/820/1440 断点截图 | NOT_RUN | 需浏览器实际渲染与截图 |
| CPU A/B 与长期驻留 | NOT_RUN | 本轮未修改物理/渲染线程预算，不宣称性能收益 |

链接：https://github.com/1998x-stack/MuJoCo-Environment-Console/actions/runs/44470889792

不能把“运行中”写成“成功”；严格套件必须以 CI 最终 conclusion 为准。

# Issues · UI/UX Pro Max

| ID | 状态 | 说明 |
|---|---|---|
| UX-01 | IMPLEMENTED | 移动端信息字号过小；新增响应式覆盖与正文对比度。 |
| UX-02 | IMPLEMENTED | 缺少会话订阅/渲染状态；使用现有 status API 无新增高负载轮询。 |
| UX-03 | IMPLEMENTED | 训练步数缺反馈与快捷操作；添加范围校验、预设和重复提交防护。 |
| UX-04 | IMPLEMENTED | 训练任务每 2.4 秒无条件重新渲染导致键盘焦点丢失；仅签名变化时重绘。 |
| UX-05 | IMPLEMENTED | 原生选择控件缺 `aria-pressed` 与焦点样式；添加语义和键盘可达设计。 |
| UX-06 | NOT_RUN | 真实浏览器/移动端截图、WCAG 工具扫描尚未验证。 |
| UX-07 | OPEN | PR #1 依赖未合并，PR #2 当前为依赖型变更；不得直接在较旧 main 上错误发布。 |

原始 MuJoCo/MJPEG/认证/训练后端未改。本轮没有声称性能提高或训练收敛。

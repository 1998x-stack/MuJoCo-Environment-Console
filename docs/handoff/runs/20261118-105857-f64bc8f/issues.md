# 问题清单 · 2026-11-18

规则：每个问题记录 现象 → 复现 → 证据 → 根因 → 修复方案 → 最小补丁 → 回归测试 → 全量相关测试 → 结果。
未修改代码的观察单独列在最后，标注 **OPEN（仅记录）**。

---

## MJC-P2-001 · MJPEG 分片结尾使用字面量 `\r\n`（非 CRLF），规范客户端完全无法解析

- **优先级**：P2（Major）— 浏览器可用，但所有符合 RFC 2046 的 MJPEG 客户端完全失效
- **状态**：FIXED

### Symptom

通过 `/api/sessions/{id}/stream` 观看仿真时，浏览器画面正常，但任何按规范解析
`multipart/x-mixed-replace` 的客户端（ffmpeg、OpenCV `VideoCapture`、VLC、GStreamer
multipartdemux）**一帧也拿不到**。

### Reproduction

```bash
curl -s --max-time 8 -b cookies.txt \
  "http://127.0.0.1:8010/api/sessions/<sid>/stream" -o stream.bin
python3 - <<'PY'
raw = open('stream.bin','rb').read()
print('rfc2046 delimiters  :', raw.count(b'\r\n--frame'))
print('lenient delimiters  :', raw.count(b'--frame'))
print('literal 5c725c6e    :', raw.count(b'\x5c\x72\x5c\x6e'))
PY
```

### Evidence

修复前（`.artifacts/runs/20261118-105857-f64bc8f/mjpeg-conformance.log`）：

```json
{
  "total_bytes": 5997481,
  "rfc2046_delimiters_CRLF--frame": 0,
  "lenient_delimiters_--frame": 105,
  "literal_backslash_r_backslash_n_before_boundary": 104,
  "real_crlf_before_boundary": 0,
  "strict_parts_found": 0,
  "lenient_frames_decoded": 105,
  "distinct_part_tails": ["5c725c6e (\\r\\n)"],
  "sample_part_last_8_bytes_hex": "b33fffd95c725c6e"
}
```

- 合法分隔符 **0 个**；分片尾部是 `5c 72 5c 6e`（反斜杠、`r`、反斜杠、`n` 四个可见字符），
  而不是 `0d 0a`。
- JPEG 数据以 `ffd9`（EOI）结束后紧跟这 4 个垃圾字节。

### Root Cause

`app/main.py::session_stream` 的内联拼装写成了字节字面量 `b'\\r\\n'`。
在 Python 中 `b'\\r\\n'` 是 4 个字符的**字面转义文本**，`b'\r\n'` 才是 CR/ LF。
RFC 2046 要求分隔行是 `CRLF + "--" + boundary`，因此整个流中不存在合法分隔符。

Chromium/Firefox 使用宽松扫描（查找 `--frame`）并在 JPEG `EOI` 之后丢弃多余字节，
所以浏览器「看起来正常」，缺陷被掩盖。

### Fix Options

1. 只把 `b'\\r\\n'` 改为 `b'\r\n'`（一行，最小）。
2. 把分片拼装抽成 `mjpeg_part()` 以便单元测试（额外收益：可回归、可被 CI 断言）。
3. 改用第三方 MJPEG 库或 WebSocket — 不必要，改协议会破坏既有前端与文档。

选择 **1 + 2**。

### Minimal Patch

`app/main.py`：

```python
MJPEG_BOUNDARY = 'frame'

def mjpeg_part(jpeg):
    """Encode one JPEG as an RFC 2046 multipart body part."""
    return (
        b'--' + MJPEG_BOUNDARY.encode()
        + b'\r\nContent-Type: image/jpeg\r\nContent-Length: '
        + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n'
    )
```

`session_stream` 改为 `yield mjpeg_part(jpeg)`，媒体类型用 `f'... boundary={MJPEG_BOUNDARY}'`。

### Regression Test

`tests/test_api.py::test_mjpeg_part_is_rfc2046_framed`：
断言分片以 `--frame\r\n` 开头、以 `\r\n\r\n<jpeg>\r\n` 结尾、**不含**字面量 `b'\\r\\n'`，
且两个分片拼接后恰好存在 1 个 `CRLF--frame` 分隔符。

### Full Relevant Tests

- `python -m pytest -q` → **23 passed**
- `docker compose exec -T console python scripts/smoke_test.py --render --all` → 18/18
- 真实浏览器 E2E（30+18 断言）→ 全部通过
- 修复后对照实验：`rfc2046_delimiters_CRLF--frame = 84`、`literal_5c725c6e_occurrences = 0`、
  `strict_rfc2046_frames_decoded = 84/84`、分片尾部 `ffd9`。

### Result

FIXED，已在修复后的镜像上重新部署并通过全部回归。

### Residual Risk

未在本机用 ffmpeg/OpenCV 实测（未安装）。分帧已符合 RFC 2046，风险低；已列入 next-steps 补实测。

---

## MJC-P3-002 · CI 与冒烟测试对 MJPEG 的断言过弱（缺陷盲区）

- **优先级**：P3（Minor，但会导致同类缺陷再次溜进 main）
- **状态**：FIXED

### Symptom

MJC-P2-001 在历史上多次 CI 通过的情况下长期存在。

### Evidence

修复前的 `.github/workflows/ci.yml` 只做：

```bash
test -s /tmp/mujoco-stream.bin
grep -a -q 'Content-Type: image/jpeg' /tmp/mujoco-stream.bin
```

这两条断言对「分帧是否合法」完全不敏感。

### Root Cause

断言停留在「流里有 JPEG 头」这一层，没有校验 multipart 结构。

### Minimal Patch

`ci.yml` 的同一 step 中追加：

```python
data = open('/tmp/mujoco-stream.bin', 'rb').read()
assert data.count(b'--frame') >= 1, 'no MJPEG boundary in the stream'
assert b'\\r\\n--frame' not in data, 'boundary uses an escaped literal instead of CRLF'
assert b'\r\n--frame' in data, 'MJPEG parts are not CRLF-delimited (RFC 2046)'
```

该断言现在能捕获的缺陷类别：**分帧分隔符被写成转义字面量**（即 MJC-P2-001 本身）。

### Result

FIXED（与 MJC-P2-001 同一提交）。

---

## MJC-P3-003 · `schemas/environment.schema.json` 从未被执行校验

- **优先级**：P3
- **状态**：FIXED

### Evidence

修复前全仓搜索：schema 只被 `python -m json.tool` 检查是否为合法 JSON，
**没有任何地方用它对 `envs/*/manifest.json` 做校验**；`jsonschema` 甚至不在 CI 依赖中。

### Root Cause

schema 是「文档性」资产，缺少执行闭环。

### Minimal Patch

1. `scripts/validate_manifests.py`：用 `Draft202012Validator` 校验全部
   `envs/*/manifest.json`，输出 `OK/FAIL` 与总计，失败退出码 1。
2. CI：依赖安装加 `jsonschema`，并新增 step `Validate shipped environment manifests against the schema`。
3. `tests/test_catalog.py::test_shipped_manifests_match_schema`（`importorskip('jsonschema')`）。

### Result

FIXED；`python scripts/validate_manifests.py` → `3/3 manifests valid`。

---

## MJC-P3-004 · 两个同名「自定义」分类标签页

- **优先级**：P3
- **状态**：FIXED

### Symptom

新增 `envs/scene_demo_viewer`（`category: "Custom"`）后，目录区出现两个都叫「自定义」
的分类按钮，分别对应不同的筛选条件，用户无法分辨。

### Reproduction

登录后在浏览器 E2E 中读取 `#categoryTabs button` 文本：

```text
全部/控制/自定义/自定义/Fetch 机器人/人形/运动/机械臂
```

### Root Cause

`app/static/app.js::renderCategoryTabs` 的标签映射把两个不同 raw category 映射到同一中文名：

```js
'Custom Control':'自定义','Custom':'自定义'
```

此前仓库只有一个自定义 category，问题未被暴露。

### Minimal Patch

1. `app.js`：`'Custom Control':'自定义控制'`、`'Custom Scene':'自定义场景'`、`'Custom':'自定义'`。
2. `envs/scene_demo_viewer/manifest.json`：`category` 改为 `"Custom Scene"`。
3. `tests/test_catalog.py`：断言该示例的 category。
4. 浏览器 E2E 新增断言：`new Set(tabs).size === tabs.length`（标签唯一）。

### Result

FIXED：`全部/控制/自定义控制/自定义场景/Fetch 机器人/人形/运动/机械臂`，标签唯一。

---

## 仅记录的观察（OPEN，本轮未修改代码）

### MJC-P3-005 · 缺少 viewer 会话枚举/清理能力

- 被浏览器遗弃的会话会占用 `MAX_VIEWERS` 槽位，直到 `SESSION_IDLE_SECONDS`（默认 900 s）
  由回收线程清理；期间新建会话返回 400。
- 复现（本轮真实发生）：连续多次运行浏览器自动化脚本后，第 4 个会话创建失败；
  `docker compose restart console` 后立即恢复。
- 影响：自动化压测与长时间无人值守场景；人工使用无感。
- 建议：提供只读的 `GET /api/sessions`，或在启动时清理孤儿会话。

### MJC-P3-006 · `data/runs/` 无保留策略

- 每个 run 目录含 `model.zip`、`output.log`；无配额、无自动清理，长期运行持续增长。
- 本轮 4 条 run 仅 360 KiB，短期无风险。
- 建议：文档化保留策略，或提供按时间/数量的清理能力（须先确认用户同意删除）。

### MJC-P3-007 · compose 未设置内存/CPU 上限

- `compose.yaml` 有 `pids_limit: 512`、`shm_size: 1gb`、`stop_grace_period: 40s`，
  但没有 `mem_limit`/`cpus`。`Humanoid-v5` 这类大环境下 OOM 会影响同机其他服务。
- 本轮 3 viewer 并发实测占 594 MiB / 815% CPU（12 线程），单训练任务受限，风险可控。
- 建议：按宿主机容量显式设置上限，并在 runbook 中说明。

### MJC-P3-008 · 失效 token 惰性清理

- `AUTH` 字典仅在登录（`_prune_auth`）或命中鉴权时清理过期 token。
- 影响：极长运行 + 高频登录时内存缓慢增长（每 token 约几十字节），可忽略。
- 建议：随限流清理一并在 reaper 中定期 `_prune_auth`。

---

## 审查过但确认无缺陷的高风险路径

以下路径在本轮被刻意审查并用真实运行验证，结论为**无缺陷**：

1. `JobManager.__init__` 对遗留 trainer 的 `/proc/<pid>/cmdline` 双重校验（含 `app.trainer`
   且含该 run 目录）→ 避免 PID 复用误杀。已在“训练中重启”测试中验证只杀自己的进程。
2. `terminate_process_group` 的 SIGTERM → 4 s → SIGKILL 升级链；取消与关停均验证进程组消失。
3. `MJCFTrackingEnv` 的 `target_qpos`/`init_qpos` 长度校验、`ctrllimited` 线性映射、
   `view_only` 与 `nu==0` 分支。
4. `catalog` 的路径穿越防护（`custom:../../etc` 返回 400，单测覆盖）。
5. 训练与 viewer 的并发上限、viewer 空闲回收、训练中断后的状态一致性。
6. 优雅停止时 `stop_all()` 先写 `interrupted` 再退出，容器 6–7 s 内干净结束、无宿主残留进程。

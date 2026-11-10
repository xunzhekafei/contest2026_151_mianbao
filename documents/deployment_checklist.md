# 云端部署检查单（2026-11-10，答辩后收尾版）

> 适用：把 `cloud/` 的 Flask 服务部署到一台常开电脑（Windows/Linux）供开发板使用。
> 压测数据见 `tools/loadtest_cloud.py`（mock 16 并发 / 241 req/s / p95 80ms；
> 真实服务健康检查 300 请求 / 176 req/s / 0 错误）。

## 1. 启动

```bash
# venv 已就绪（cloud/.venv）；key 只从环境变量或 ~/.mimo_key 读，不进仓库
python app.py            # 监听 0.0.0.0:5000，threaded=True
```

启动自检（按顺序）：

1. `curl http://127.0.0.1:5000/api/health` 返回 `{"status":"ok"}`
2. 日志出现 `[题库] 已加载 2830 道题…6 个岗位`
3. 浏览器打开 `http://127.0.0.1:5000/status` 能看到事件面板（为空是正常的）
4. 板端 `CLOUD_URL` 指向本机（默认编死 `http://172.20.10.2:5000`；
   也可写 `/data/ai_interview_cloud` 运行期覆盖，不用重烧）

## 2. 进程与守护

| 项 | 现状 | 建议 |
|---|---|---|
| 运行方式 | `python app.py`（Flask 自带 dev server，`threaded=True`） | 长期部署换 `waitress-serve --threads=16 --port=5000 app:app`（Windows）/ gunicorn（Linux） |
| 进程守护 | 无 | Windows：计划任务/`nssm` 服务；Linux：systemd `Restart=always` |
| 单实例 | 单进程即可 | **不要起两个**（并发闸在进程内存里，双实例等于双份会话 + 端口冲突） |
| 自动重启丢什么 | 内存会话丢失，磁盘存档保留（每轮落盘，`/api/history` 仍可读） | 可接受；需要零丢失则改外部会话存储 |

## 3. 并发能力（实测 + 推算）

- **mock 压测**：16 并发会话 × 4 轮 = 96 请求，0.4s，**241 req/s**，p95 80ms，0 错误；
  **同会话并发闸**：同时 8 个请求 → 1×200 + 7×409（设计即如此，防重复报告）。
- **真实瓶颈是上游模型**：一轮 = ASR + LLM + TTS，约 3~20 秒；每个在途请求占一个线程。
  单机建议 **≤10 台设备同时练习**（峰值约 10 线程 + 评分/笔记/复盘后台线程）；
  20 台以上需要拆服务 + 队列。
- 内存峰值估算：每个在途响应持有 base64 音频（~1~2MB），10 并发放大约 +30MB。
- 所有上游调用都有超时（ASR 60s / TTS 90s / LLM 90s，最多重试 1 次），
  单次卡死不会再锁死会话（2026-11-06 修复）。

## 4. 数据

- `cloud/data/sessions/*.json`：每场一个快照（含 messages/score/notes/expression），
  随场次增长；**定期归档**（`data/sessions_archive_<日期>/`，程序不会加载子目录）。
- `cloud/data/users/users.json`：扫码绑定的账号（token 即身份，无密码）。
- 音频**不落盘**（ASR 后即弃），只存文字与评分。
- `cloud/data/` 已在 `.gitignore`，不会进仓库。

## 5. 观测与排障

- `/status`：每轮请求时间线（请求 → ASR → LLM → TTS → 完成/409/错误 → 笔记/复盘），
  顶部显示"正在处理中的会话"。**上传是否走流式**看有没有「上传」事件。
- 日志：`$TEMP/flask_err.log`（Windows，GBK 编码；werkzeug + app logger）。
- 常见故障：
  - 板子"上传失败"→ 先看 /status：409 = 有请求卡在服务端（已加超时，重启 Flask 即解）；
    无任何请求 = 网络/`CLOUD_URL` 问题。
  - `Unsupported model` → MIMO 模型下线，改 `LLM_MODEL`。
  - `tts_audio` 为空 → 云端缺 key 或 TTS 服务异常。

## 6. 安全（演示环境口径）

- 服务只监听局域网；**不要公网暴露**——接口无鉴权、无 TLS。
- MIMO key 只放 `~/.mimo_key` 或环境变量，绝不进仓库（`tools/redact_secrets.sh` 可扫）。
- Wi-Fi 密码只在板子内存（2026-11-03 起不落盘，每次开机重新输入）。
- 账号 token 即身份：谁先扫到二维码谁是账号主人（演示场景可接受）。

## 7. 已知限制

- Flask dev server 不适合长期生产（无 TLS、无优雅重启、单进程）。
- 云端不可用时板子端只能"暂停练习不丢进度"（断网三层兜底），**不是离线可用**。
- 评分口径 v3 只对新场次生效，历史 v1/v2 分数在成长页会提示跨版本混用。
- 报告轮的"逐题流式"条目可能晚于评分到达（后台逐题生成，刷新可见）。

# 中期测试证据目录

本目录保存可复核的测试证据，不保存 API key、账号 token、Wi-Fi 密码等敏感信息。

## 已有文件

| 文件 | 说明 |
|---|---|
| `automated_tests_2026-11-27.log` | 完整依赖环境测试，23 个文件、441 个用例 |
| `automated_tests_nodeps_2026-11-27.log` | 无第三方依赖环境测试，16 个纯单测文件、291 个用例通过，7 个跳过 |
| `flask_smoke_2026-11-27.log` | Flask 路由与模板冒烟：9 岗位、9615 道题；health、history API 和 history 页面均为 200 |
| `manifest.json` | 上述日志和图片的大小、SHA-256 |
| `device_overview_2026-11-03.jpg` | 从真实设备录像第 3 秒取帧，展示开发板、外壳、屏幕和接口 |
| `device_interview_state_2026-11-03.jpg` | 从同一录像第 15 秒取帧，展示“面试中”状态 |
| `web_conversation_historical.jpg` | 从历史网页录屏取帧，展示对话、轮次和岗位 |
| `web_report_historical.jpg` | 从历史网页录屏取帧，展示报告、评分和导出入口 |

四张图片是**历史画面证据**，不是 `d76e2597` 当前固件的新实拍。原始视频标识：

- 设备录像 SHA-256：`e25f3cd632195f2d4d656c2cdc5aa9d03fed580fa0041168736a8840729b1375`
- 网页录屏 SHA-256：`d8b8eb5b3ad0b684403e899f84fba9a4c95f3f9bb3a0b55d160ad5f7d4feef45`

`flask_smoke` 使用了一个非真实的占位 Key 来绕过应用的启动检查，只验证路由和模板；日志已写明没有调用任何 ASR、LLM 或 TTS 接口。

## 真机测试待补文件

| 文件 | 内容 |
|---|---|
| `firmware_boot_2026-11-27.log` | 启动日志，需能确认镜像版本 |
| `round1_serial_2026-11-27.log` | 第一轮串口日志 |
| `round2_serial_2026-11-27.log` | 第二轮串口日志 |
| `round3_serial_2026-11-27.log` | 第三轮串口日志 |
| `network_cut_serial_2026-11-27.log` | 断网与恢复补送日志 |
| `round1_device.jpg` | 第一轮设备状态照片 |
| `round3_report_play.jpg` | 报告轮播放照片 |
| `report_web_2026-11-27.png` | 网页报告截图 |
| `history_web_2026-11-27.png` | 网页历史截图 |

串口日志建议统一使用 `tools/capture_serial.ps1` 采集，每行包含本地时间和相对秒数，便于复算录音、首句和总时长。

采集完成后可用 `tools/summarize_serial.ps1` 自动生成四项时长：

```powershell
.\tools\summarize_serial.ps1 -Path .\documents\evidence\midterm\round1_serial_2026-11-27.log -OutputPath .\documents\evidence\midterm\round1_metrics.csv
```

脚本只解析日志，不推测缺失事件；缺少开始、录音完成或播放事件时会留空并在 `Status` 标为 `INCOMPLETE`。

大型原始视频不要直接提交到 GitHub；保留在本地或网盘，仓库只放压缩后的三分钟成片或外部链接。

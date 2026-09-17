# host · PC 侧上位机与调试工具

通过 USB 串口（CP2102，**115200 8N1**）与主控板上的 `PIANO_GLOVE_1` 固件通信。

> 协议细节见 [../docs/handoff-2026-09-17.md](../docs/handoff-2026-09-17.md#2-固件-piano_glove_1-命令协议核心)。

## 文件

| 文件 | 说明 |
| --- | --- |
| **`web_piano_glove.html`** ★ | 单文件网页调试台，无外部依赖。含连接（模拟 / 实机 Web Serial）、INFO、槽位表与行程条、舵机编号向导、校准流程、扭矩/ARM/SAFE/PRESS/RELEASE/MOVE/DEMO、命令终端。**内置模拟固件，不接硬件也能跑通全流程** |
| **`glove_fw.py`** | PIANO_GLOVE 协议的 Python 封装 + CLI |
| **`assign_ids.py`** | 舵机编号向导（命令行版，全自动，只需插拔舵机）。支持 `--from N` 断点续跑；内含串口异常自动恢复、`SCAN` 不可靠改用逐个 `PING`、改号后等待重启复核等实战逻辑 |
| `live.html` | 编号向导的实时进度网页，读 `assign_log.txt`，1.5s 自动刷新 |
| `assign_log.txt` | 编号向导运行日志，含固件回复原文 —— **协议逆向的第一手证据，勿删** |
| `scservo_sdk/` | 飞特官方 Python SDK（原始 SCS/STS 协议用）。注意 `sc.PacketHandler` 在新版已移除，应使用 `sc.sms_sts(portHandler)` |
| `legacy/` | ⚠️ **与当前固件不兼容**，见下 |

## 快速开始

```bash
pip install -r requirements.txt

python glove_fw.py info                  # 固件 / 档位 / 校准 / armed
python glove_fw.py assign                # 逐个把舵机 ID 编成 1~6
python glove_fw.py auto                  # 固件自检，action= 字段含诊断建议
python glove_fw.py status                # 6 槽位总表
python glove_fw.py cal wizard 20         # 一键校准向导
python glove_fw.py monitor               # 轮询实时反馈
python glove_fw.py raw "CAL STATUS"      # 发任意命令
```

板子串口默认 `COM11`，用 `--port COMx` 覆盖。

网页调试台：

```bash
python -m http.server 8123 --bind 127.0.0.1
# 浏览器打开 http://localhost:8123/web_piano_glove.html
# 实机模式需 Chrome / Edge，波特率固定 115200
```

## 写客户端时要注意的几条

- **串口会因 USB 重新枚举而失效**：Python 侧报 `ClearCommError failed (PermissionError 13)` 或 `FileNotFoundError(2)`。前者=端口句柄失效，后者=设备消失。健壮客户端应捕获 `serial.SerialException` → 关端口 → 循环重开。
- **不要发广播 `PING 254`**：某些 SDK/固件在此路径会返回空包导致崩溃。
- **`SETID` 报 `write_or_verify_failed` 不等于失败**：常见于写入成功但复核赶上舵机重启空窗。判据应为「稍等后 `PING <new_id>` 是否通」。
- **轮询别刷太猛**：遍历 10 个 ID ≈ 6 秒，自动刷新建议 2~3 秒一次。

## legacy/ 里的东西为什么不能用

`web_debug.html` 与 `glove_calibration.py` 是**早期版本**，直连 Feetech SCS 原始协议，本意是「PC 直连舵机总线」。但当前主控固件 **`PIANO_GLOVE_1` 没有串口透传功能**，所以这两套工具在现有硬件上发什么都没反应。

保留原因：`web_debug.html` 里有**手指 SVG 动画、示波器、跟随误差评估、calib.json 导入导出**，是很好的 UI 素材，扩展网页调试台时可直接借鉴。

复活条件：把板子刷成微雪官方 ST 系列固件并打开 `SERIAL_FORWARDING`（串口透传）。

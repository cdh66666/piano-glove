# host · PC 侧上位机与调试工具

通过 USB 串口（CP2102，**115200 8N1**）与主控板上的 `PIANO_GLOVE_1` 固件通信。

> 协议细节见 [../docs/handoff-2026-09-17.md](../docs/handoff-2026-09-17.md#2-固件-piano_glove_1-命令协议核心)。

## 文件

| 文件 | 说明 |
| --- | --- |
| **`web_piano_glove.html`** ★ | **分页式调试台（当前主用）**。底部导航 6 个页面：连接 / 编号 / 校准 / 试动作 / 演奏 / 日志。内置模拟固件，无硬件也能走完全流程；含 MIDI 导入与演奏引擎 |
| **`glove_fw.py`** | PIANO_GLOVE 协议的 Python 封装 + CLI |
| **`assign_ids.py`** | 舵机编号向导（命令行版，全自动，只需插拔舵机）。支持 `--from N` 断点续跑；内含串口异常自动恢复、`SCAN` 不可靠改用逐个 `PING`、改号后等待重启复核等实战逻辑 |
| `live.html` | 编号向导的实时进度网页，读 `assign_log.txt`，1.5s 自动刷新 |
| `assign_log.txt` | 编号向导运行日志，含固件回复原文 —— **协议逆向的第一手证据，勿删** |
| `tests/` | 无硬件自测脚本（端到端流程 + MIDI 解析器交叉验证），见 [tests/README.md](tests/README.md) |
| `scservo_sdk/` | 飞特官方 Python SDK（原始 SCS/STS 协议用）。注意 `sc.PacketHandler` 在新版已移除，应使用 `sc.sms_sts(portHandler)` |
| `legacy/` | ⚠️ **与当前固件不兼容**，见下 |

## 调试台怎么用

打开 `web_piano_glove.html`，底部 6 个页面按顺序走一遍就是完整流程。没接硬件时选「模拟模式」，全流程一样能跑通。

| 页面 | 做什么 | 过关标志 |
| --- | --- | --- |
| 1 连接 | 选模拟 / 实机，点连接，读 INFO，把档位设成 `STS3032` | 顶栏「已连接」，档位显示「正确」 |
| 2 编号 | **一次只插一个舵机**，轮流改成 1~6 号并贴标签 | 6 个进度点全绿 |
| 3 校准 | 先把 6 个舵机接回总线确认全在线，再采样活动手指 | 顶栏「已校准」 |
| 4 试动作 | 使能后逐个「按一下」，核对编号↔手指、按压方向 | 每根手指动作正确 |
| 4B 测响应速度 | 测 `PING` / `MOVE` 往返延迟，并连发 60 条压测 | 出结论：能不能跑到 6 Hz |
| 5 演奏 | 导入 MIDI，看分配预览，点开始 | 手指跟着节奏动 |
| 6 日志 | 原始命令与回复，排查问题用 | — |

前置步骤没完成时，后续页面会被**闸门挡住**并提示先去哪一步，不会让人在错误状态下瞎点。

## 4B 响应速度实测（决定演奏能跑多快）

**先测这个，再谈演奏。** 一次触键 = 按下 + 抬起两条命令，6 根手指跑 6 Hz 就是
6 × 6 × 2 = **72 条/秒**。固件如果每条命令都要死等一个固定窗口，这个数就上不去。

三个按钮：

1. **测通信往返** —— `PING` × 20，不动舵机，最安全。拿到的是纯协议往返延迟
2. **测动作往返** —— `MOVE` × 20，含舵机动作开销（需先 ARM）
3. **压测** —— 不等回复连喷 60 条 `MOVE`（演奏页真实的工作方式），看固件会不会被压死、
   回复会不会丢；之后还会 `PING` 一次确认串口还活着

结果会直接给结论：**能跑满 6 Hz** / **需要降速到多少** / **必须改固件加原生命令**。

> 实现细节：`Transport.send()` 收到第一行回复后，只要 **140ms** 安静就立即返回，
> 不再死等 `timeoutMs`。计时写进 `T.last = {first, ms, lines}`，`first` 就是往返延迟。
> 这个改动同时让编号向导这类连续命令的操作快了一个数量级。
> 模拟模式下延迟是假的（固定 24ms），界面上会明确标出来，别拿模拟数字下结论。

## 演奏页（MIDI → 手套）

- 支持 **format 0 / 1** 的 `.mid`，自动处理 running status、变速（tempo map）、SMPTE 时基
- 两种分配方式：
  - **轮流分配**（默认）—— 把音符依次分给当时空闲的手指，节奏最完整、手指动得最均匀
  - **音高对应** —— 低音给拇指、高音给小指，更像真手型
- 可按轨道 / 通道 / 音域筛选（钢琴曲通常只弹右手主旋律）
- 导入后会**预估峰值命令速率**并提示。手套只有 6 个自由度，音比手多时主动丢音保节奏，不会卡住不动
- 按住时长取音符时长的 80%（夹在 55~200ms），接近真人触键

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

板子串口**自动识别**（挨个串口发 `INFO`，谁回 `OK INFO` 就是它）。串口号会随 USB 枚举变化，所以别写死；要指定就 `--port COMx`。

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

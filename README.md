# 六自由度钢琴手套 · Piano Glove

用 6 个舵机驱动的可穿戴手套：通过连杆/绳驱带动佩戴者的手指按压琴键，实现自动演奏与指法驱动。

> **状态（2026-09-17）**：固件协议已完全逆向；舵机编号进行到 1/6；主控板 USB 当前断开，待重新连接后继续。

---

## 硬件

| 项目 | 规格 |
| --- | --- |
| 主控板 | 微雪 **Servo Driver with ESP32**（SKU 21593）：ESP32 + CP2102 + OLED + WiFi + DC 6~12V 供电 |
| 主控固件 | **自定义 `PIANO_GLOVE_1`**（非微雪出厂固件，**无串口透传**） |
| 舵机 | 6 × **Feetech STS3032-C001**：12bit 磁编码，量程 0~4095（360°），工作电压 4.8~6V，TTL 半双工 |
| PC ↔ 板 | USB-C（UART0），**固定 115200 8N1** |
| 板 ↔ 舵机 | UART1，**GPIO18=RX / GPIO19=TX，1,000,000 bps** |
| 供电 | **5V/5A 适配器接 DC 圆口**（USB-C 只给板子供电，不带舵机） |
| 自由度 | 6：拇指 2 个（下压 + 侧压），其余四指各 1 个 |

### 槽位 ↔ 舵机（固件默认）

| slot | 手指 | 默认舵机 ID |
| --- | --- | --- |
| 0 | 拇指侧压 | 1 |
| 1 | 拇指下压 | 2 |
| 2 | 食指 | 3 |
| 3 | 中指 | 4 |
| 4 | 无名指 | 5 |
| 5 | 小指 | 6 |

> ⚠️ **slot0/slot1 的「侧压 / 下压」角色尚未实机确认**，上手后需用 `MOVE` 逐个驱动核实，必要时 `MAP` / `SETDIR` 修正。

---

## 三个最容易踩的坑

1. **别发原始 Feetech SCS 包。** 板子是自定义 `PIANO_GLOVE_1` 固件，**没有串口透传**，舵机原始协议发过去毫无反应。必须用文本命令协议（见 [protocol](docs/handoff-2026-09-17.md#2-固件-piano_glove_1-命令协议核心)）。
2. **6 个舵机出厂 ID 全是 1，不是 1~6。** 同时挂上总线会互相抢答，表现为「偶尔 ping 通、SCAN 只找到一个」。**改号必须一次只接一个舵机**。
3. **`PING` 单次固定约 610ms；`SCAN` 约 1/3 概率漏报。** 探测舵机请逐个 `PING`，不要依赖 `SCAN`。

---

## 仓库结构

```
piano-glove/
├── docs/
│   ├── handoff-2026-09-17.md   ★ 交接文档（协议逆向、踩坑、进度、路线的唯一事实来源）
│   └── design-notes.md         决策记录 · 待定问题 · 里程碑
├── host/                       PC 侧上位机与调试工具
│   ├── web_piano_glove.html    ★ 单文件网页调试台（内置模拟固件，无硬件也能跑通全流程）
│   ├── glove_fw.py             PIANO_GLOVE 协议 Python 封装 + CLI
│   ├── assign_ids.py           舵机 ID 编号向导（命令行，支持断电续跑）
│   ├── live.html               编号向导实时进度网页
│   ├── assign_log.txt          编号运行日志（协议逆向的第一手证据）
│   ├── scservo_sdk/            飞特官方 Python SDK（原始 SCS/STS 协议用）
│   └── legacy/                 ⚠️ 与当前固件不兼容，仅作 UI 素材参考
├── firmware/                   固件源码不在本机（见目录内说明）
└── hardware/                   结构件与电路
```

---

## 快速开始

### 网页调试台（推荐，无硬件也能玩）

```bash
cd host
python -m http.server 8123 --bind 127.0.0.1
# 浏览器打开 http://localhost:8123/web_piano_glove.html
```

模拟模式下可以完整走通 INFO / 编号向导 / 校准 / 动作测试，不接硬件即可验证逻辑。
连实机需 Chrome 或 Edge（Web Serial），波特率 **115200**。

### Python 命令行

```bash
cd host
pip install -r requirements.txt

python glove_fw.py info                    # 固件 / 档位 / 校准 / armed 状态
python glove_fw.py assign                  # 逐个把舵机 ID 编成 1~6
python glove_fw.py auto                    # 固件自检（含诊断建议字段）
python glove_fw.py status                  # 6 槽位总表
python glove_fw.py cal wizard 20           # 一键校准向导（20 秒活动时间）
python glove_fw.py monitor                 # 轮询实时反馈
python glove_fw.py raw "CAL STATUS"        # 发任意命令
```

板子串口默认 `COM11`，可在 `glove_fw.py` 顶部 `DEFAULT_PORT` 或用 `--port COMx` 指定。

---

## 当前进度

| 项目 | 状态 |
| --- | --- |
| 固件协议逆向 | ✅ 完成 |
| 舵机档位设为 `STS3032` | ✅ 完成 |
| 舵机编号 1~6 | ⏳ **进行中（1/6 完成）** |
| 单舵机验证 | ✅ `PING` 20/20 通，可读 pos/电压/温度 |
| 校准 / ARM / 按压 / DEMO | ❌ 未进行（依赖 6 个舵机全部在线） |
| 主控板 USB | ⚠️ 当前系统 COM 口数量为 0，需重新插好 |

已知硬件缺陷：有 1 个舵机接触不良（20 次 ping 仅 6 次通），建议换线或重压端子后再装回手套。

---

## 后续路线

1. 恢复连接 → 2. 完成编号 → 3. 整体自检 → 4. 角色确认 → 5. 校准 → 6. 动作验证 → 7. 新功能

完整步骤与原始需求见 **[docs/handoff-2026-09-17.md](docs/handoff-2026-09-17.md)**。
未解决的方案问题见 **[docs/design-notes.md](docs/design-notes.md)**。

---

## 关联仓库

- [dual-n20-pot-motor-driver](https://github.com/cdh66666/dual-n20-pot-motor-driver) —— Web Serial 实时调参与曲线可视化思路
- [dual-esp32-motor-force-feedback](https://github.com/cdh66666/dual-esp32-motor-force-feedback) —— 舵机同步总线与闭环调试工具链
- [Bus_Servo_Driver](https://github.com/cdh66666/Bus_Servo_Driver) —— 飞特总线舵机驱动板

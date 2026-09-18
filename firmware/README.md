# firmware · 主控固件（自研 `PIANO_GLOVE_2`）

> **2026-09-18 起，本项目不再依赖别人的固件。** 这里就是源码。

板子跑的是本项目自研的 `PIANO_GLOVE_2`，替代原来那块闭源的 `PIANO_GLOVE_1`。
**文本协议逐命令兼容** —— `host/web_piano_glove.html` 和 `host/glove_fw.py` 一行都不用改。

---

## 为什么重写

原厂固件（别人写的、源码不在手上的那块）只有一个致命问题，但它卡死了整个上层需求：

| | 原厂 `PIANO_GLOVE_1` | 自研 `PIANO_GLOVE_2` |
| --- | --- | --- |
| 单条命令处理 | 固定约 **103 ms** | 收到回复立即返回，超时窗口 20 ms |
| **固件受理速率** | **9.9 条/秒**（实测） | 只受 1 Mbps 总线限制，理论上百条/秒 |
| 6 指 × 6 Hz 需要 | 72 条/秒 → **差 7.3 倍** | 满足 |
| 板载扫频（行程 % / 频率 / 时长） | ❌ 没有 | ✅ `SWEEP` |
| 舵机编号流程 | 状态语义含糊，实测会死循环 | ✅ `ENROLL` 状态机，总线清空才允许插下一个 |

那 103 ms 与舵机无关，是固件每条命令的固定等待窗口 —— 所以**上位机再怎么优化都没用**，
必须换固件。实测数据见 [`../host/bench.py`](../host/bench.py) 与
[`../docs/design-notes.md`](../docs/design-notes.md) 的风险 1。

---

## 硬件

| 项目 | 值 | 来源 |
| --- | --- | --- |
| 主控 | **ESP32-D0WD-V3 rev3.1** | `esptool flash-id` 实测 |
| Flash | **4 MB**（厂商 46 / 器件 4016） | 同上 |
| MAC | `28:05:a5:c4:f1:88` | 对上原厂 AP 名 `PIANO_GLOVE_A50528` |
| 晶振 | 40 MHz | 同上 |
| 板子 | 微雪 Servo Driver with ESP32 (SKU 21593)，CP2102 转串口 | 交接文档 |
| PC ↔ 板 | UART0 / USB-C，**115200 8N1**（上位机固定，勿改） | 交接文档 |
| 板 ↔ 舵机 | UART1，**GPIO18=RX / GPIO19=TX，1,000,000 bps** | 与原厂固件一致 |
| 舵机 | 6 × Feetech **STS3032-C001**，12bit 磁编码，量程 0~4095 | 交接文档 |

> GPIO18/19 是照抄原厂固件的可用配置。没有实测过是否还有方向控制脚 —— 原厂能跑通，
> 说明总线侧的方向处理在硬件上已经解决，固件照抄即可。

---

## 编译与烧录

```bash
# 编译
PLATFORMIO_CORE_DIR=<workspace>/.pio-core \
  <venv>/python.exe -m platformio run -d firmware

# 烧录（自动识别端口，或显式 --upload-port COM3）
PLATFORMIO_CORE_DIR=<workspace>/.pio-core \
  <venv>/python.exe -m platformio run -d firmware -t upload --upload-port COM3
```

沙箱 / 受限环境下 PlatformIO 会去锁 `~/.platformio/platforms.lock` 报 `PermissionError`。
解决办法是用目录联接把缓存映射到工作区（`New-Item -ItemType Junction`），
然后所有调用都带 `PLATFORMIO_CORE_DIR`。已在本机验证可用。

### 回滚到原厂固件

首次刷写前已把整片 4 MB 备份到：

```
_inbox/fw_backup/original_PIANO_GLOVE_1_4MB.bin
```

（不在仓库里，避免 4 MB 二进制进 git。文件丢了也不要紧 —— 协议已被完整记录在
[`../docs/handoff-2026-09-17.md`](../docs/handoff-2026-09-17.md)。）

```bash
python -m esptool --port COM3 --baud 230400 write-flash 0x0 original_PIANO_GLOVE_1_4MB.bin
```

> ⚠️ CP2102 在 **460800** 下读 4 MB 会中途数据校验失败（实测踩过），用 230400 稳。

---

## 源码结构

```
firmware/
├── platformio.ini        esp32dev / espressif32@6.4.0 / Arduino
└── src/
    ├── scs_bus.h/.cpp    飞特 SCS/STS 协议驱动（官方 Python SDK 的 C++ 移植）
    ├── glove.h/.cpp      槽位模型、校准表、按压/松开、扫频引擎、NVS 持久化
    └── main.cpp          命令分发 + ENROLL 状态机
```

### 协议实现要点（写代码时最容易错的地方）

- 包格式 `0xFF 0xFF ID LEN INSTR PARAM... CHECKSUM`，`LEN = 参数数 + 2`，总长 `LEN + 4`
- 校验和 `~(ID + LEN + INSTR + PARAM...) & 0xFF`
- **状态包第 5 字节是错误码，不是指令** —— 请求包的 `INSTR` 位在回包里成了 `ERR` 位，
  这是区分「自己发的回显」和「舵机的回复」的唯一依据之一
- 反馈一次读 **56~70 共 15 字节**（位置/速度/负载/电压/温度/运动中/电流），省 7 次往返
- 改舵机 ID 前要先写 `LOCK=0` 解锁 EEPROM，改完再上锁；
  **写入后必须等约 300 ms 再 `PING` 新 ID 复核** —— 舵机应用新 ID 需要时间

### 串口接收缓冲必须放大（v2.0.1 修的坑）

Arduino-ESP32 的 `HardwareSerial` RX 环形缓冲**默认只有 256 字节**。
115200 8N1 下这只相当于 22 ms 的余量 —— 而上位机在演奏场景会一次连发几十条命令，
只要主循环在 `glove::tick()` 里停 8 ms 去读总线，环形缓冲就溢出、字节被丢，
现象是「发 60 条只回 45 条」并且回复内容被截断。

修法是 `Serial.setRxBufferSize(4096)`，且**必须在 `Serial.begin()` 之前调用**才生效
（`_rxBufferSize` 是 `HardwareSerial` 的 protected 成员，没有公开 getter，
所以 `READY BUS ... uart_rx_buf=` 里打印的是一个编译期常量 `UART_RX_BUF`）。

另外 `loop()` 里加了一个行缓冲溢出保护：单行超过 255 字节时丢弃整行并计数，
计数从 `BUSINFO` 的 `rx_drop=` 读出 —— 若这个数在涨，说明上位机发得太快或发坏了。

`host/tests/verify_firmware.py` 现在区分两种压测：
`burst()` 一次性猛灌（考突发吸收）、`burst_paced()` 每 2 ms 一条（考稳态处理）。
两个数字一起看才能判断丢包发生在链路还是在固件。

### 回显处理（很容易踩）

端口探测时会向不存在的 ID 发一条 `PING`，数收到几个字节：收到等于自己发包长度的字节数，
说明板上 TX/RX 是并联的（半双工常见做法），后续每发一包都要先吃掉这段回显。
`BUSINFO` 里的 `echo=` / `echo_bytes=` 就是这件事，`ECHO 0|1` 可以手动覆盖。

---

## 命令集

### 与原厂完全兼容（上位机无需改动）

`INFO` `PROFILE` `PING` `SCAN` `STATUS` `STATUS_ALL` `MAP` `SETDIR` `SETID`
`CAL (STATUS/CLEAR/CAPTURE/SAVE/AUTO START|STATUS|FINISH|CANCEL)`
`TORQUE` `ARM` `DISARM` `SAFE` `STANDBY CONFIRM` `PRESS` `RELEASE` `MOVE` `DEMO`
`AUTO` `ENROLL` `HELP`

回复格式逐字段对齐（含 `SLOT` / `CAL` / `CAL_AUTO` 行的字段顺序），
所以调试台和 CLI 的解析逻辑一个字都不用动。

### 自研新增

| 命令 | 作用 |
| --- | --- |
| **`SWEEP <slots> <freq_mhz> <depth%> <dur_ms> [speed] [acc]`** | 板载扫频。`slots`：`0`/`all`=全部，`1..6`=单个槽（1 起），`0x3F`=位掩码；`freq_mhz` 单位 0.001 Hz（`6000` = 6 Hz）；`depth%` 行程百分比（**原始需求是 80**）；`dur_ms` 持续时长。结束时自动松手并打印 `SWEEP_DONE` |
| `SWEEP STOP` | 中止扫频，回到 standby |
| `SWEEP` | 查看当前扫频状态 |
| `BUSINFO` | 总线诊断：引脚、波特率、回显判定、收发计数、超时数、校验错数 |
| `ECHO 0\|1` | 手动覆盖回显判定 |
| `PRESET <speed> <acc>` | 设置 `PRESS`/`RELEASE`/`DEMO` 的默认速度与加速度 |

扫频用 **SYNC_WRITE 一帧同时更新所有参与槽位**，所以 6 指同时扫也不会因为逐个下发而错位。

### 行为上的差异（有意为之）

- `MOVE <id> <pos>` 的 `speed`/`acc`/`ARM` 变成**可选**。上位机的「响应速度实测」页只发
  `MOVE 1 200`，原厂会回 usage 错误（测出来的往返时间其实只是报错时间）。
- `PROFILE SC09` 返回 `ERR`。原厂接受但在 SC09 档下舵机 ping 不通；本固件只有 STS 寄存器表，
  报错比假装接受更诚实。
- `DISARM` 会有回复（原厂无回复）。有回复总是更好调试。

---

## 已验证 / 未验证（务必看清）

| 项 | 状态 |
| --- | --- |
| 编译通过 | ✅ `pio run` 零错误 |
| 芯片身份 / Flash 容量 / MAC | ✅ esptool 实测 |
| 协议格式、寄存器表 | ✅ 逐字节对齐飞特官方 SDK，且与 `assign_log.txt` 里原厂回复原文核对 |
| **与原厂固件行为等价** | ❌ **未验证 —— 需要接上真实舵机** |
| 舵机总线收发 | ❌ 未验证（写固件时一个舵机都没接，见下） |
| 行程 80% / 0~6 Hz 扫频实测 | ❌ 未验证 |
| OLED 屏 / WiFi AP | ❌ 本版**未实现**（原厂有，属可选功能） |

**为什么舵机总线现在验证不了**：写这份固件时手上一个舵机都没接。
好消息是端口探测（`BUSINFO` 的 `echo=`）**不需要舵机**就能验证收发链路是否通，
所以刷完之后第一件事就是看 `BUSINFO`。

### 上电后按这个顺序验证

```
BUSINFO                 # echo=1？→ TX/RX 并联正常；echo=0 且 tx 在涨 → 板子没在发或线没接
INFO                    # 应回 fw=PIANO_GLOVE_2 profile=STS3032 range=4095
PING 1                  # 接上舵机后逐个数
STATUS_ALL              # 6 个槽位在线情况
```

---

## NVS 持久化

命名空间 `pianoglove`。键：`speed` / `acc` / `calib`，
每个槽位 `s{n}id` / `s{n}lo` / `s{n}st` / `s{n}hi` / `s{n}vd` / `s{n}d`。

`MAP` / `SETDIR` / `SETID` / `CAL SAVE` / `CAL CAPTURE` 会自动落盘，
断电重连后槽位映射和校准值都还在 —— 这是原厂固件做不到的便利。

---

## 待办

- [ ] 接上舵机后跑通 `BUSINFO` / `PING` / `STATUS_ALL`
- [ ] 实测 `SWEEP 0 6000 80 10000` 是否真的跑得到 6 Hz（舵机跟不跟得上）
- [ ] 接上舵机后补跑 `host/tests/` 的实机回归（目前 e2e 只跑模拟固件）
- [ ] OLED 状态显示（需要先确认屏的 I2C 引脚与控制器）
- [ ] WiFi AP + 网页入口（原厂有 `PIANO_GLOVE_A50528` / 192.168.4.1）

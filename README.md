# Piano Glove · 钢琴手套

可穿戴手部设备：感知手指姿态 / 触键力度，并可通过力反馈引导手部动作，用于钢琴练习辅助与 MIDI 演奏。

> 状态：**项目初始化中**（仓库骨架已建，方案选型进行中，见 [docs/design-notes.md](docs/design-notes.md)）

---

## 项目定位

待确认（见 design-notes 的「待定问题」）：

- **A. 演奏型** —— 戴着手套，手指动作直接映射为 MIDI 音符，不依赖真钢琴也能弹。
- **B. 教学型** —— 有压力 / 姿态感知 + 力反馈，纠正手型、指法、力度，需配合练习曲目。
- **C. 二者兼顾** —— 先做感知与 MIDI 输出，力反馈作为第二阶段。

---

## 目录结构

```
piano-glove/
├── firmware/     ESP32 固件（PlatformIO，传感器采样 / 通信 / 力反馈闭环）
├── host/         上位机：数据采集、可视化、MIDI 路由、标定与调参界面
├── hardware/     结构件与电路设计资料（3D 模型、原理图、BOM）
└── docs/         方案笔记、通信协议、测试记录
```

---

## 硬件预选型（未定稿）

| 模块 | 候选 | 备注 |
| --- | --- | --- |
| 主控 | ESP32-S3 | 原生 USB OTG，可直接做 USB-MIDI；蓝牙 MIDI 亦可 |
| 弯曲感知 | 电阻式弯曲传感器 / 霍尔 + 磁铁 / 柔性应变片 | 需评估寿命、一致性、标定难度 |
| 触键力度 | FSR 薄膜压力传感器（指尖） | 与弯曲量联合判定「真实触键」 |
| 惯性测量 | IMU（腕部，单颗） | 手腕翻转 / 手位判定 |
| 力反馈 | N20 电机绳驱（复用 `dual-esp32-motor-force-feedback` 方案）/ LRA 振动 | 绳驱可做真实阻力引导，振动仅能做提示 |

> 绳驱力反馈与仓库 [`dual-esp32-motor-force-feedback`](https://github.com/cdh66666/dual-esp32-motor-force-feedback)、[`Cable_driven_massage`](https://github.com/cdh66666/Cable_driven_massage) 的技术栈高度重合，优先复用同步总线与闭环调试工具链。

---

## 开发环境

固件（待补充 `platformio.ini` 后生效）：

```bash
cd firmware
pio run -t upload
pio device monitor
```

上位机（待定语言/框架）：

```bash
cd host
# 待补充
```

---

## 关联仓库

- [dual-esp32-motor-force-feedback](https://github.com/cdh66666/dual-esp32-motor-force-feedback) —— 力反馈驱动与 1 Mbaud 同步总线
- [dual-n20-pot-motor-driver](https://github.com/cdh66666/dual-n20-pot-motor-driver) —— N20 闭环调试固件与 Web Serial 调参 UI

---

## License

待定（默认建议 MIT，可随时改为私有或其它协议）。

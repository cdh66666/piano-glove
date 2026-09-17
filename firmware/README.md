# firmware · ESP32 固件

待搭建。预计使用 PlatformIO（与 `dual-esp32-motor-force-feedback`、`dual-n20-pot-motor-driver` 保持一致的工具链习惯）。

## 规划的模块

```
firmware/
├── platformio.ini
├── src/
│   ├── main.cpp          主循环 / 任务调度
│   ├── sensors/          弯曲、触键、IMU 采样与轻量滤波
│   ├── mapping/          传感器 → 手指姿态 → 触键判定 → MIDI 事件
│   ├── midi/             USB-MIDI / BLE-MIDI 输出
│   └── link/             上位机通信（串口 / USB），用于标定与调参
├── include/
├── lib/
└── test/
```

> 本期**不含**力反馈执行器模块。

## 待办

- [ ] 确定主控型号与开发板（ESP32-S3？需确认 USB OTG 做 USB-MIDI 的可行性）
- [ ] 建立 `platformio.ini`，跑通 LED 点灯
- [ ] 接第一路弯曲传感器，串口输出原始值
- [ ] 打通 USB-MIDI，让电脑收到一个音符

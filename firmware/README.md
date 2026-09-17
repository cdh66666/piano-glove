# firmware · ESP32 固件

待搭建。预计使用 PlatformIO（与 `dual-esp32-motor-force-feedback`、`dual-n20-pot-motor-driver` 保持一致的工具链习惯）。

## 规划的模块

```
firmware/
├── platformio.ini
├── src/
│   ├── main.cpp          主循环 / 任务调度
│   ├── sensors/          弯曲、压力、IMU 采样与滤波
│   ├── haptics/          力反馈执行器控制（电机闭环 / LRA 驱动）
│   ├── mapping/          传感器 → 手指姿态 / 触键力度 → MIDI 事件
│   └── link/             上位机通信（串口 / USB / BLE）
├── include/
├── lib/
└── test/
```

## 待办

- [ ] 确定主控型号与开发板（ESP32-S3？）
- [ ] 建立 `platformio.ini`，跑通 LED 点灯
- [ ] 接第一路弯曲传感器，串口输出原始值

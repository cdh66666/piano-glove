# firmware · 主控固件

## 现状：源码不在本机

板子（微雪 Servo Driver with ESP32，SKU 21593）跑的是**自定义固件 `PIANO_GLOVE_1`，不是微雪出厂固件**。其**源码目前不在本机**，只有通过串口逆向出的文本命令协议。

- 协议全文：[../docs/handoff-2026-09-17.md](../docs/handoff-2026-09-17.md#2-固件-piano_glove_1-命令协议核心)
- 已探明命令：`INFO PROFILE AUTO ENROLL SCAN PING STATUS STATUS_ALL MAP SETDIR SETID CAL TORQUE ARM DISARM SAFE STANDBY PRESS RELEASE MOVE DEMO`

## 为什么这件事卡着

原始需求「按行程 80%、0~6 Hz 正弦往复驱动」**当前固件没有对应命令**。固件只有 `MOVE <id> <pos> <speed> <acc> ARM` 这种一次性定位。可选路径：

- **上位机每 20~50 ms 逼近**（不改固件）—— 但 `PING` 单次固定耗时约 610 ms，说明固件内部每条命令都有固定等待窗口，**很可能跑不到 6 Hz**，需先实测 `MOVE` 往返延迟。
- **新增固件命令**（改固件）—— 唯一可靠满足 6 Hz 的路径，但需要拿到或重写源码并重刷。

> 决策见 [../docs/design-notes.md](../docs/design-notes.md) 的 Q1 与风险 1。

## 待办

- [ ] 找到 `PIANO_GLOVE_1` 源码；找不到就评估重写的范围
- [ ] **实测 `MOVE` 命令的往返延迟**（决定 Q1 走哪条路）
- [ ] 评估新增命令：`SWEEP <slot> <freq> <amplitude>` 之类的板载频率驱动
- [ ] 评估固件侧提高命令刷新率 / 去掉固定等待窗口

## 备选路线：刷官方固件

若嫌 `PIANO_GLOVE_1` 限制多，可刷微雪官方 ST 系列固件并打开 `SERIAL_FORWARDING`（串口透传），届时 `host/legacy/` 里的两套原始 SCS 协议工具可直接复活。

代价：现有文本协议、槽位映射、内置曲目等全部作废。

> 本目录暂无代码，仅作固件相关决策的落点。

# tests · 无硬件自测

网页调试台内置了模拟固件，所以**不接板子**就能把「编号 → 校准 → 试动作 → MIDI 演奏」整条链路跑一遍。
这套脚本用真实浏览器（Chromium）打开页面、点按钮、检查结果，用来在接硬件之前确认界面没坏。

## 依赖

```bash
pip install pyserial          # 只有 glove_fw.py 需要，测试本身不需要
npm i playwright-core         # 浏览器驱动
npx playwright install chromium   # 或者用系统已有的 Chrome，设 CHROME_PATH 环境变量
```

## 跑法

```bash
cd host/tests

# 1) 交叉验证 MIDI 解析器：网页端 vs 独立 Python 参考实现，逐音符比对
python make_midi.py       # 生成测试用 MIDI（含 format 1 / format 0 两份）
python ref_parse.py       # 参考实现解析 -> ref.json
node compare.js           # 两边结果比对

# 2) 端到端流程自测（模拟固件，无需硬件）
node e2e.js               # 输出 60+ 项 PASS/FAIL，截图存到 shots/

# 3) 关键页面视觉抽查（视口截图 + 窄屏横向滚动检查）
node shots.js
```

`CHROME_PATH=/path/to/chrome node e2e.js` 可以指定浏览器。

## 各文件做什么

| 文件 | 说明 |
| --- | --- |
| `make_midi.py` | 生成测试 MIDI。故意包含 **running status**、多轨、变速、密集快速音、五音和弦 —— 覆盖解析器最容易出错的分支 |
| `ref_parse.py` | **独立写的** MIDI 参考解析器（Python）。两边独立实现，结果一致才说明网页端解析器是对的 |
| `compare.js` | 逐音符比对网页端解析器与参考实现的时间/音高/时长/力度 |
| `e2e.js` | 端到端流程自测：连接 → 6 轮编号 → 校准 → 使能 → 单指测试 → MIDI 演奏 → 日志，并检查全程无 JS 报错 |
| `shots.js` | 关键页面视觉抽查 |

## 已知的坑（写脚本时踩过）

- **测试 MIDI 的手写生成器极易造出非法文件**：一个事件必须是「delta-time + 事件」的完整单元。
  曾经把 `vlq(480)` 和后面第一组 `vlq(0)` 分开写，导致事件里出现两个 delta-time，
  解析器按 running status 一路错位。表现形式是「音符数量对但时间全歪」。
  所以生成的每个文件都要先用 `ref_parse.py` 验一遍结构。
- **解析器遇到损坏文件应该降级而不是崩**：读越界返回 0 并置 `truncated` 标记，界面上给出黄色提示。
  如果用裸 `DataView.getUint8()`，一个坏字段就会抛 `Offset is outside the bounds of the DataView`。
- **`SCAN` 不可靠**：浏览器端也是逐个 `PING 1~10`，每个约 0.6 秒，一次检测约 6 秒属正常。

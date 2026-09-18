"""列出串口并逐个试着打开，把失败原因说清楚。"""

import serial
import serial.tools.list_ports

print("=== 枚举到的串口 ===")
for p in serial.tools.list_ports.comports():
    print(f"  {p.device:8s} | {p.description} | {p.hwid}")

print("\n=== 逐个试开 ===")
for p in serial.tools.list_ports.comports():
    dev = p.device
    if not dev.upper().startswith("COM"):
        continue
    try:
        s = serial.Serial(dev, 115200, timeout=0)
        s.close()
        print(f"  {dev:8s} 可以打开")
    except Exception as e:
        print(f"  {dev:8s} 打不开 -> {type(e).__name__}: {e}")

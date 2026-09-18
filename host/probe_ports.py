# -*- coding: utf-8 -*-
"""探测哪个串口是钢琴手套主板。

只发 INFO / PING —— **不会驱动舵机**，插着任何东西都能安全跑。

用法：
    python probe_ports.py                 # 探测所有串口
    python probe_ports.py COM4 COM23      # 只探这两个

读数的含义：
    打不开 / 拒绝访问(5)  → 被别的程序占着（浏览器调试台、串口监视器、另一个 agent…）
                            先把那些关掉，或拔插一次
    没有发挥作用(31)     → 枚举还在但驱动栈卡住了，**拔插一次**基本就好了
    (无任何回复)         → 端口开着但对面不说话：可能是别的板子，或固件没跑起来
    OK INFO ...          → 这就是手套主板
"""
import sys
import time

try:
    import serial
    import serial.tools.list_ports as lp
except ImportError:
    print("需要 pyserial:  pip install pyserial")
    sys.exit(1)

# Windows 错误码 → 人话
WINERR = {
    5:  "拒绝访问 —— 端口被别的程序占用，先关掉它再试",
    31: "设备没有发挥作用 —— 驱动栈卡住了，拔插一次 USB 基本能解决",
}


def probe(port, baud=115200, cmd="INFO", wait=3.0):
    try:
        ser = serial.Serial(port, baud, timeout=0.2)
    except Exception as e:
        code = getattr(e, "winerror", None)
        hint = WINERR.get(code)
        return None, f"打不开：{e}" + (f"\n      ↳ {hint}" if hint else "")
    try:
        time.sleep(0.3)
        ser.reset_input_buffer()
        idle = ser.read(4096)                     # 有些固件开机会主动上报
        ser.write((cmd + "\r\n").encode())
        t0 = time.time()
        buf, last = b"", t0
        while time.time() - t0 < wait:
            d = ser.read(4096)
            if d:
                buf += d
                last = time.time()
            elif time.time() - last > 0.6:
                break
        note = f"开机主动上报 {len(idle)} 字节" if idle else ""
        return buf.decode("utf-8", "replace").strip(), note
    finally:
        ser.close()


def main():
    targets = sys.argv[1:] or [p.device for p in lp.comports()]
    if not targets:
        print("系统里没有发现任何串口。")
        return
    print("待探测：", targets)

    found = []
    for port in targets:
        print(f"\n===== {port} =====")
        txt, note = probe(port)
        if note:
            print("  ", note)
        if txt is None:
            continue
        if not txt:
            print("   (无任何回复)")
            continue
        for line in txt.splitlines()[:12]:
            print("   >", line.replace("\r", ""))
        if any(l.startswith("OK INFO") for l in txt.splitlines()):
            found.append(port)

    print()
    if len(found) == 1:
        print(f"✔ 手套主板在 {found[0]}")
    elif found:
        print(f"⚠ 有多个端口回应了 INFO：{found} —— 确认一下哪块是手套")
    else:
        print("✘ 没有端口回应 INFO。检查：DC 圆口 5V 电源有没有插、USB 线是不是只充电的线、"
              "有没有别的程序占着串口。")


if __name__ == "__main__":
    main()

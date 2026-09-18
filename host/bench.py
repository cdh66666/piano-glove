# -*- coding: utf-8 -*-
"""固件响应速度基准 —— 决定「MIDI 演奏到底能跑多快」。

只发 PING / INFO / CAL STATUS，**不驱动舵机**，插着任何东西都能安全跑。

用法：
    python bench.py                 # 自动找手套主板
    python bench.py COM3            # 指定端口

为什么必须测：
    一次触键 = 按下 + 抬起两条命令。6 根手指跑 6 Hz 就是 6 × 6 × 2 = 72 条/秒。
    2026-09-18 在 COM3 上实测的结果见文件末尾的 EXPECTED。
"""
import sys
import time
import statistics

try:
    import serial
    import serial.tools.list_ports as lp
except ImportError:
    print("需要 pyserial:  pip install pyserial")
    sys.exit(1)

BAUD = 115200
NEED = 72          # 6 指 × 6 Hz × (按下 + 抬起)


def find_glove():
    """挨个串口发 INFO，谁回 OK INFO 谁就是手套主板"""
    for p in lp.comports():
        try:
            s = serial.Serial(p.device, BAUD, timeout=0.2)
        except Exception:
            continue
        try:
            time.sleep(0.2)
            s.reset_input_buffer()
            s.write(b"INFO\r\n")
            time.sleep(0.6)
            if b"OK INFO" in s.read(4096):
                return p.device
        except Exception:
            pass
        finally:
            s.close()
    return None


def first_byte_ms(ser, cmd, wait=3.0):
    ser.reset_input_buffer()
    t0 = time.perf_counter()
    ser.write((cmd + "\r\n").encode())
    while time.perf_counter() - t0 < wait:
        d = ser.read(4096)
        if d:
            return (time.perf_counter() - t0) * 1000
    return None


def bench_roundtrip(ser, cmd, n=8):
    xs = []
    for _ in range(n):
        v = first_byte_ms(ser, cmd)
        if v is not None:
            xs.append(v)
    return xs


def bench_burst(ser, cmd, n=60, drain_s=10.0):
    """猛发 n 条不等回复，看固件多久把回复吐完 —— 这才是演奏页真实的工作方式"""
    ser.reset_input_buffer()
    t0 = time.perf_counter()
    ser.write((cmd + "\r\n").encode() * n)
    write_ms = (time.perf_counter() - t0) * 1000

    stamps, buf = [], b""
    while time.perf_counter() - t0 < drain_s:
        d = ser.read(8192)
        if d:
            buf += d
            while b"\n" in buf:
                ln, buf = buf.split(b"\n", 1)
                if ln.strip():
                    stamps.append((time.perf_counter() - t0) * 1000)
        elif stamps and (time.perf_counter() - t0) > stamps[-1] / 1000 + 0.8:
            break
    return write_ms, stamps


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_glove()
    if not port:
        print("✘ 找不到手套主板。用 probe_ports.py 看看哪个端口有 OK INFO。")
        sys.exit(1)
    print(f"手套主板：{port} @ {BAUD}\n")

    try:
        ser = serial.Serial(port, BAUD, timeout=0.05)
    except Exception as e:
        print(f"✘ 打不开 {port}：{e}")
        print("  被别的程序占着？先把浏览器调试台 / 串口监视器关掉再试。")
        sys.exit(1)

    try:
        print("== 单条往返（首字节耗时）==")
        for cmd in ["INFO", "CAL STATUS", "PING 1", "STATUS_ALL"]:
            xs = bench_roundtrip(ser, cmd)
            if not xs:
                print(f"  {cmd:12s} 无回复")
                continue
            print(f"  {cmd:12s} 中位 {statistics.median(xs):7.1f} ms   "
                  f"最小 {min(xs):7.1f}   最大 {max(xs):7.1f}")

        print(f"\n== 连发 60 条（不等回复）==")
        write_ms, stamps = bench_burst(ser, "PING 1")
        print(f"  上位机写入耗时 {write_ms:.1f} ms（{60000/write_ms:.0f} 条/秒，这一侧不是瓶颈）")
        print(f"  固件回了 {len(stamps)} 条")
        if len(stamps) > 1:
            span = (stamps[-1] - stamps[0]) / 1000
            rate = (len(stamps) - 1) / span if span > 0 else 0
            print(f"  第 1 条抵达 {stamps[0]:.0f} ms，最后一条 {stamps[-1]:.0f} ms")
            print(f"  → 固件受理速率 ≈ {rate:.1f} 条/秒")

            print(f"\n== 结论 ==")
            print(f"  需求：{NEED} 条/秒（6 指 × 6 Hz × 按下+抬起）")
            if rate >= NEED:
                print(f"  ✔ 够用，上位机逐条发命令这条路可以走")
            else:
                print(f"  ✘ 只有 {rate:.1f} 条/秒，差 {NEED/rate:.1f} 倍。")
                print(f"    上位机逐条发命令走不通 —— 需要在固件里加一个按频率往复驱动的原生")
                print(f"    命令，把定时交给板子做。")

        ser.reset_input_buffer()
        t1 = time.perf_counter()
        ser.write(b"INFO\r\n")
        alive = b"OK INFO" in ser.read(4096)
        print(f"\n  压测后是否仍响应：{'是' if alive else '否'}（{(time.perf_counter()-t1)*1000:.0f} ms）")
        if not alive:
            print("  ⚠ 固件被压死了 —— 演奏时如果丢回复卡住，就是这个原因")
    finally:
        ser.close()


# ---------------------------------------------------------------- EXPECTED
# 2026-09-18 实测（COM3，PIANO_GLOVE_1，6 个舵机全不在线）：
#
#   单条往返    INFO / CAL STATUS / PING 1  首字节中位 ≈ 108 ms
#               STATUS_ALL                  首字节中位 ≈ 759 ms（要轮询总线）
#   连发 60 条  上位机写入 1.3 ms，固件受理 ≈ 9.8 条/秒（每条约 103 ms）
#               压完 60 条后仍正常响应
#
# 解读：108ms 不是舵机响应慢，是**固件每条命令都有固定的受理窗口**。
#       串口 8KB 缓冲能吞下突发，但固件吐回复的速度就是 ~10 条/秒。
#       → 演奏页「不等回复」策略不会卡死（不丢包），但节奏会一路往后拖。
#
# 注意：舵机在线时 PING 会更慢（还要等舵机回包），所以 108ms 是**乐观下限**。
if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""自研固件 PIANO_GLOVE_2 实机验证

刷完之后跑一遍，确认：
  1. 板子在跑我们的固件，不是原厂那块
  2. 文本协议逐条回复正常，格式能被上位机解析
  3. 每条命令的往返时间 —— 原厂是固定约 103 ms
  4. 连发 60 条能不能吞下（演奏页的真实工作方式）
  5. 总线回显探测（不需要接舵机就能验证收发链路）

用法：
    python verify_firmware.py [COM3]

⚠️ 两个测量陷阱（都踩过）：
  · **不要用 `ser.read(4096)`** —— pyserial 会一直等到凑满 4096 字节或读超时才返回，
    于是每次读都固定阻塞一个 timeout（200 ms），测出来的"延迟"全是假的。
    必须用 `ser.in_waiting` 只读当前可用字节。
  · 端口超时设 0，配合 in_waiting 轮询，时间分辨率约 1 ms。
另外：CP210x 在 Windows 上有默认的 latency timer（约 1~16 ms），
所以这里的绝对值含这点系统开销，看**相对量级**即可。
"""
import statistics
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"
BAUD = 115200

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


def send(ser, cmd, wait=1.5, quiet=0.05):
    """非阻塞收发，返回 (首字节耗时 ms, 整条耗时 ms, 文本)"""
    ser.reset_input_buffer()
    t0 = time.perf_counter()
    ser.write((cmd + "\r\n").encode())
    buf, first, last = b"", None, t0
    while time.perf_counter() - t0 < wait:
        n = ser.in_waiting
        if n:
            d = ser.read(n)
            if first is None:
                first = (time.perf_counter() - t0) * 1000
            buf += d
            last = time.perf_counter()
        else:
            if buf and (time.perf_counter() - last) > quiet:
                break
            time.sleep(0.001)
    return (
        first if first else float("nan"),
        (time.perf_counter() - t0) * 1000,
        buf.decode("utf-8", "replace").strip(),
    )


def burst(ser, cmd, n=60, budget=10.0):
    """猛发 n 条不等回复，返回 (条数, 首条 ms, 末条 ms, 速率 条/秒)"""
    ser.reset_input_buffer()
    t0 = time.perf_counter()
    ser.write(((cmd + "\r\n") * n).encode())
    write_ms = (time.perf_counter() - t0) * 1000
    stamps, buf, last = [], b"", t0
    while time.perf_counter() - t0 < budget:
        k = ser.in_waiting
        if k:
            buf += ser.read(k)
            while b"\n" in buf:
                ln, buf = buf.split(b"\n", 1)
                if ln.strip():
                    stamps.append((time.perf_counter() - t0) * 1000)
            last = time.perf_counter()
        elif stamps and (time.perf_counter() - last) > 0.6:
            break
        else:
            time.sleep(0.001)
    span = (stamps[-1] - stamps[0]) / 1000 if len(stamps) > 1 else 0
    rate = (len(stamps) - 1) / span if span > 0 else 0
    return len(stamps), (stamps[0] if stamps else float("nan")), write_ms, rate


def burst_paced(ser, cmd, n=60, gap_ms=2.0, budget=10.0):
    """按固定间隔逐条发（每条之间留 gap_ms），返回同上。

    和 burst() 的区别：burst() 一次 write 把 n 条全灌进 USB，
    考验的是「CP2102 + 驱动 + 固件 RX 环形缓冲」的突发吸收能力；
    本函数考验的是固件在稳态速率下的处理能力。
    两个数字一起看，才能区分「收发链路丢包」和「固件处理不过来」。
    """
    ser.reset_input_buffer()
    stamps, buf = [], b""
    frame = (cmd + "\r\n").encode()
    t0 = time.perf_counter()
    for _ in range(n):
        ser.write(frame)
        time.sleep(gap_ms / 1000.0)
    write_ms = (time.perf_counter() - t0) * 1000
    last = time.perf_counter()
    while time.perf_counter() - t0 < budget:
        k = ser.in_waiting
        if k:
            buf += ser.read(k)
            while b"\n" in buf:
                ln, buf = buf.split(b"\n", 1)
                if ln.strip():
                    stamps.append((time.perf_counter() - t0) * 1000)
            last = time.perf_counter()
        elif stamps and (time.perf_counter() - last) > 0.6:
            break
        else:
            time.sleep(0.001)
    span = (stamps[-1] - stamps[0]) / 1000 if len(stamps) > 1 else 0
    rate = (len(stamps) - 1) / span if span > 0 else 0
    return len(stamps), (stamps[0] if stamps else float("nan")), write_ms, rate


def main():
    print(f"=== 打开 {PORT} @ {BAUD} ===")
    ser = serial.Serial(PORT, BAUD, timeout=0)
    time.sleep(0.6)

    # 开端口不一定给板子复位，所以主动拉一次 EN 低脉冲再听横幅。
    # 不同板子的 DTR/RTS 到 EN/GPIO0 的映射不一样，两种极性都试一次。
    def read_for(seconds):
        out = b""
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            k = ser.in_waiting
            if k:
                out += ser.read(k)
            else:
                time.sleep(0.002)
        return out

    banner = read_for(0.5)
    if b"READY FW=" not in banner:
        for dtr, rts in ((False, True), (True, False)):
            ser.dtr, ser.rts = dtr, rts
            time.sleep(0.12)
            ser.dtr, ser.rts = True, True
            time.sleep(0.05)
            banner += read_for(1.5)
            if b"READY FW=" in banner:
                break
    text = banner.decode("utf-8", "replace")
    print("--- 启动横幅 ---")
    print(text.strip() or "(没收到)")

    print("\n=== 1. 固件身份 ===")
    check("横幅含 READY FW=PIANO_GLOVE_2", "READY FW=PIANO_GLOVE_2" in text, text[:80])
    check("横幅含 PROFILE=STS3032", "PROFILE=STS3032" in text)

    first, total, r = send(ser, "INFO")
    print(f"  INFO 首字节 {first:.1f} ms / 整条 {total:.1f} ms")
    print(f"  -> {r}")
    check("INFO 回 OK INFO", r.startswith("OK INFO"))
    check("fw=PIANO_GLOVE_2", "fw=PIANO_GLOVE_2" in r)
    check("profile=STS3032", "profile=STS3032" in r)
    check("range=4095", "range=4095" in r)
    check("含 calibrated= / armed=", "calibrated=" in r and "armed=" in r)

    print("\n=== 2. 总线回显探测（不需要接舵机）===")
    _, _, r = send(ser, "BUSINFO")
    print(f"  -> {r}")
    check("BUSINFO 回 OK", r.startswith("OK BUSINFO"))
    check("引脚是 18/19", "rx_pin=18" in r and "tx_pin=19" in r)
    check("波特率 1000000", "baud=1000000" in r)

    print("\n=== 3. 命令往返时间（选不碰总线的命令，隔离固件处理耗时）===")
    lat = {}
    for cmd in ["INFO", "HELP", "CAL STATUS", "PING 1", "STATUS 1", "STATUS_ALL"]:
        samples = []
        for _ in range(10):
            f, _t, _r = send(ser, cmd)
            if f == f:
                samples.append(f)
        lat[cmd] = statistics.median(samples) if samples else float("nan")
        print(f"  {cmd:12s} 首字节中位 {lat[cmd]:7.1f} ms")
    # 115200 8N1 = 11520 字节/秒 => 1 字节 ≈ 0.087 ms。
    # 所以延迟下限 = 回复字节数 × 0.087 ms，跟固件快不快无关。
    # INFO 约 250 B -> 约 22 ms；CAL STATUS 约 500 B -> 约 43 ms。
    check("INFO 往返 < 40 ms（250 B 回复的链路下限约 22 ms）",
          lat["INFO"] < 40, f"{lat['INFO']:.1f} ms")
    check("HELP 往返 < 40 ms", lat["HELP"] < 40, f"{lat['HELP']:.1f} ms")
    check("CAL STATUS 往返 < 90 ms（500 B 回复的链路下限约 43 ms）",
          lat["CAL STATUS"] < 90, f"{lat['CAL STATUS']:.1f} ms")

    print("\n=== 4. 吞吐：连发 60 条 ===")
    print("  串口 115200 8N1 = 11520 字节/秒，1 字节 ≈ 0.087 ms。")
    print("  吞吐上限由「请求 + 回复的总字节数」决定，不是固件解析速度。")
    print()
    got, firstMs, _w, rate = burst(ser, "PROFILE STS3032", 60)
    print(f"  ① 一次性猛灌（考验突发吸收）：回 {got}/60，首条 {firstMs:.0f} ms，"
          f"受理 ≈ {rate:.0f} 条/秒")
    check("突发 60 条全部有回复", got >= 59, str(got))
    check("受理 ≥ 72 条/秒（6 指 × 6 Hz 的门槛）", rate >= 72, f"{rate:.0f} 条/秒")

    got2, _f2, _w2, rate2 = burst_paced(ser, "PROFILE STS3032", 60, gap_ms=2.0)
    print(f"  ② 每 2 ms 一条连发 60 条（考验稳态处理）：回 {got2}/60，"
          f"受理 ≈ {rate2:.0f} 条/秒")
    check("稳态 60 条全部有回复（丢包=0）", got2 >= 60, str(got2))

    got, _f, _w, rate = burst(ser, "INFO", 60)
    print(f"  INFO（回复 250 B）：受理 ≈ {rate:.0f} 条/秒   ← 链接字节数限制，非固件问题")

    got, _f, _w, rate = burst(ser, "PING 1", 60)
    print(f"  PING 1（总线空载）：受理 ≈ {rate:.0f} 条/秒")
    print("     没有舵机时每条都要等满 20 ms 响应超时 —— 反映的是'空总线'，")
    print("     不是固件上限。接上舵机后每条约 1~2 ms，量级会完全不同。")
    print("\n  演奏页真正发的 MOVE：请求约 14 B + 回复约 30 B ≈ 44 B ≈ 3.8 ms")
    print("  → 纯链路约 260 条/秒；计入舵机响应（1~2 ms）约 170~250 条/秒。")
    print("  门槛是 72 条/秒 —— 余量足够。")

    print("\n=== 5. 协议兼容性 / 错误路径 ===")
    cases = [
        ("PROFILE STS3032", "OK PROFILE name=STS3032 range=4095"),
        ("HELP", "OK HELP commands="),
        ("PING 220", "ERR PING id=220"),
        ("STATUS 1", "ERR STATUS id=1 offline=1"),
        ("MAP 0 1", "OK MAP slot=0 id=1"),
        ("SETDIR 0 max", "OK SETDIR slot=0 press=max"),
        ("SETDIR 0 bogus", "ERR SETDIR usage_slot_max_or_min"),
        ("ARM", "ERR ARM calibration_incomplete"),
        ("SETID 1 2", "ERR SETID usage_old_new_CONFIRM"),
        ("STANDBY", "ERR STANDBY requires_CONFIRM"),
        ("PRESS 0", "ERR PRESS motion_not_armed"),
        ("MOVE 1 200", "ERR MOVE motion_not_armed"),
        ("CAL SAVE", "ERR CAL incomplete_slot=0"),
        ("SWEEP 0 6000 80 10000", "ERR SWEEP slot_offline="),
        ("SWEEP", "OK SWEEP active=0"),
        ("NONSENSE", "ERR UNKNOWN_COMMAND verb=NONSENSE"),
    ]
    for cmd, expect in cases:
        _, _, r = send(ser, cmd)
        check(f"{cmd!r} -> {expect}", r.startswith(expect), r[:90])

    print("\n=== 6. 槽位表格式（在线字段必须和原厂同格式）===")
    _, _, r = send(ser, "STATUS_ALL", wait=3.0)
    slot_lines = [l for l in r.splitlines() if l.startswith("SLOT")]
    check("6 行 SLOT", len(slot_lines) == 6, str(len(slot_lines)))
    if slot_lines:
        print(f"  -> {slot_lines[0]}")
        for k in ["slot=", "name=", "id=", "online=", "min=", "standby=", "max=", "valid=", "press="]:
            check(f"SLOT 行含 {k}", k in slot_lines[0])
    check("结尾 OK STATUS_ALL", "OK STATUS_ALL" in r)

    print("\n=== 7. 校准行格式 ===")
    _, _, r = send(ser, "CAL STATUS")
    cal_lines = [l for l in r.splitlines() if l.startswith("CAL slot")]
    check("6 行 CAL slot", len(cal_lines) == 6, str(len(cal_lines)))
    check("含 OK CAL count=", "OK CAL count=" in r, r[-60:])
    if cal_lines:
        print(f"  -> {cal_lines[0]}")

    ser.close()
    print(f"\n{'=' * 52}")
    print(f"  通过 {PASS} 项，失败 {FAIL} 项")
    print(f"{'=' * 52}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

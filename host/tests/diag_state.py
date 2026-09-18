"""连上板子读一遍真实状态。

用法：
    python host/tests/diag_state.py [PORT]

内容：开端口 -> INFO -> CAL STATUS -> STATUS_ALL -> BUSINFO
目的：拿到用户已经跑完「编号 + 校准」之后落在 NVS 里的真实数据。
"""

import sys
import time

import serial
import serial.tools.list_ports


def find_port():
    """挨个串口发 INFO，认回 PIANO_GLOVE 的那个。"""
    cands = []
    for p in serial.tools.list_ports.comports():
        if p.device.upper().startswith("COM"):
            cands.append(p.device)
    for dev in cands:
        try:
            with serial.Serial(dev, 115200, timeout=0) as s:
                time.sleep(0.3)
                s.reset_input_buffer()
                for _ in range(3):
                    s.write(b"INFO\r\n")
                    t0 = time.perf_counter()
                    buf = b""
                    while time.perf_counter() - t0 < 0.6:
                        k = s.in_waiting
                        if k:
                            buf += s.read(k)
                        else:
                            time.sleep(0.001)
                    if b"PIANO_GLOVE" in buf:
                        return dev, buf.decode("utf-8", "replace").strip()
        except Exception:
            continue
    return None, ""


class Board:
    def __init__(self, port):
        self.s = serial.Serial(port, 115200, timeout=0)
        time.sleep(0.5)
        self.s.reset_input_buffer()

    def cmd(self, text, quiet=0.20, budget=3.0):
        self.s.reset_input_buffer()
        self.s.write((text + "\r\n").encode())
        buf = b""
        t0 = time.perf_counter()
        last = t0
        while time.perf_counter() - t0 < budget:
            k = self.s.in_waiting
            if k:
                buf += self.s.read(k)
                last = time.perf_counter()
            elif buf and (time.perf_counter() - last) > quiet:
                break
            else:
                time.sleep(0.001)
        return buf.decode("utf-8", "replace").strip()

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else None
    if not port:
        port, banner = find_port()
        if not port:
            print("找不到钢琴手套板子（没有串口回 PIANO_GLOVE）")
            return 1
        print(f"自动识别到 {port}")
        print(f"  横幅: {banner.splitlines()[0] if banner else '(空)'}")
    else:
        banner = ""

    b = Board(port)
    # 开端口可能给了复位脉冲，先叫醒
    for _ in range(4):
        r = b.cmd("INFO")
        if r.startswith("OK INFO"):
            break
    print("\n" + "=" * 70)
    print("INFO")
    print("=" * 70)
    print(r)

    for name in ("CAL STATUS", "STATUS_ALL", "BUSINFO"):
        print("\n" + "=" * 70)
        print(name)
        print("=" * 70)
        print(b.cmd(name, budget=5.0))

    b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

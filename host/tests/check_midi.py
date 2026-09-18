"""校验自己生成的 MIDI 能不能被"标准"解析器读出来。

用法：python host/tests/check_midi.py <file.mid>

复用 ref_parse.py 里那套参考解析逻辑（它和网页端解析器是两份独立实现，
两边一致才说明文件是对的）。ref_parse.py 在导入时会跑它自己的测试，
所以这里直接内联一份同样的解析，避免副作用。
"""

import struct
import sys
from pathlib import Path


def parse(path):
    b = Path(path).read_bytes()
    p = 0

    def u8():
        nonlocal p
        v = b[p]
        p += 1
        return v

    def vlq():
        nonlocal p
        v = 0
        while True:
            c = u8()
            v = (v << 7) | (c & 0x7F)
            if not (c & 0x80):
                return v

    assert b[p:p + 4] == b"MThd", "没有 MThd 头"
    p += 4
    u32 = lambda: None  # noqa: E731  (占位，下面手工读)
    hlen = struct.unpack(">I", b[p:p + 4])[0]; p += 4
    fmt = struct.unpack(">H", b[p:p + 2])[0]; p += 2
    ntrk = struct.unpack(">H", b[p:p + 2])[0]; p += 2
    div = struct.unpack(">H", b[p:p + 2])[0]; p += 2
    p += hlen - 6
    ppq = div & 0x7FFF

    notes, metas = [], []
    for t in range(ntrk):
        assert b[p:p + 4] == b"MTrk", f"第 {t} 轨没有 MTrk @{p}"
        p += 4
        ln = struct.unpack(">I", b[p:p + 4])[0]; p += 4
        end = p + ln
        tick = 0
        status = 0
        open_ = {}
        while p < end:
            tick += vlq()
            c = b[p]
            if c & 0x80:
                status = c
                p += 1
            typ, ch = status & 0xF0, status & 0x0F
            if status == 0xFF:
                mt = u8()
                ml = vlq()
                metas.append((tick, mt, ml))
                p += ml
            elif status in (0xF0, 0xF7):
                p += vlq()
            elif typ in (0x90, 0x80):
                n = u8(); v = u8()
                k = ch * 128 + n
                if typ == 0x90 and v > 0:
                    open_[k] = (tick, v)
                elif k in open_:
                    st, vel = open_.pop(k)
                    notes.append((st, tick - st, n, vel))
            elif typ in (0xA0, 0xB0, 0xE0):
                p += 2
            elif typ in (0xC0, 0xD0):
                p += 1
            else:
                raise SystemExit(f"未知状态 0x{status:02X} @{p}")
        assert p == end, f"轨道长度对不上: {p} != {end}"
    return fmt, ntrk, ppq, notes, metas


def main():
    # ⚠️ 默认路径必须相对**本脚本**解析，不能相对 CWD ——
    # 否则 `cd host/tests && python check_midi.py` 会报 FileNotFoundError，
    # 看着像样本文件坏了，其实是路径找错了。
    default = Path(__file__).resolve().parents[1] / "samples" / "two-tigers.mid"
    f = sys.argv[1] if len(sys.argv) > 1 else str(default)
    fmt, ntrk, ppq, notes, metas = parse(f)
    print(f"{f}")
    print(f"  格式 {fmt} / {ntrk} 轨 / {ppq} ticks per 四分音符")
    print(f"  元事件 {len(metas)} 个: " + ", ".join(f"0x{mt:02X}({ml}B)" for _, mt, ml in metas[:5]))
    print(f"  音符 {len(notes)} 个")
    if notes:
        ticks = max(st + d for st, d, _, _ in notes)
        print(f"  总长 {ticks} ticks = {ticks / ppq:.2f} 拍")
        print(f"  音高范围 {min(n for _, _, n, _ in notes)}~{max(n for _, _, n, _ in notes)}")
    assert notes, "一个音符都没解析出来"
    assert not [k for k in notes if k[1] <= 0], "有非正时长的音符"
    print("  ✔ 文件结构正确")


if __name__ == "__main__":
    main()

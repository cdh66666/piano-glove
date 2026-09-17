"""独立参考实现：用 Python 重新解析 test.mid，与网页端解析器结果逐音符比对。
两边完全独立写，只要结果一致就说明网页端解析器是对的。"""
import struct, pathlib, json

def parse(path):
    b = pathlib.Path(path).read_bytes()
    p = 0
    def u8():
        nonlocal p
        v = b[p]; p += 1; return v
    def u16():
        nonlocal p
        v = struct.unpack(">H", b[p:p+2])[0]; p += 2; return v
    def u32():
        nonlocal p
        v = struct.unpack(">I", b[p:p+4])[0]; p += 4; return v
    def vlq():
        nonlocal p
        v = 0
        while True:
            c = u8(); v = (v << 7) | (c & 0x7F)
            if not (c & 0x80): return v

    assert b[p:p+4] == b"MThd"; p += 4
    hlen = u32(); fmt = u16(); ntrk = u16(); div = u16()
    p += hlen - 6
    ppq = div & 0x7FFF

    notes, tempo, tracks = [], [(0, 500000)], []
    for t in range(ntrk):
        assert b[p:p+4] == b"MTrk", (t, p, b[p:p+4])
        p += 4
        ln = u32(); end = p + ln
        tick = 0; status = 0; open_ = {}
        while p < end:
            tick += vlq()
            c = b[p]
            if c & 0x80: status = c; p += 1
            typ, ch = status & 0xF0, status & 0x0F
            if status == 0xFF:
                mt = u8(); ml = vlq()
                if mt == 0x51 and ml == 3:
                    tempo.append((tick, (u8() << 16) | (u8() << 8) | u8()))
                else:
                    p += ml
            elif status in (0xF0, 0xF7):
                p += vlq()
            elif typ in (0x90, 0x80):
                n = u8(); v = u8()
                k = ch * 128 + n
                if typ == 0x90 and v > 0: open_[k] = (tick, v)
                else:
                    if k in open_:
                        st, vel = open_.pop(k)
                        notes.append((st, tick - st, n, vel, ch, t))
            elif typ in (0xA0, 0xB0, 0xE0): p += 2
            elif typ in (0xC0, 0xD0): p += 1
            else: raise SystemExit("未知状态 @%d" % p)
        assert p == end, (p, end)
        tracks.append(t)

    tempo.sort()
    def to_ms(tk):
        ms = 0; lt = 0; lu = 500000
        for tt, uu in tempo:
            if tt > tk: break
            ms += (tt - lt) * lu / ppq / 1000
            lt, lu = tt, uu
        ms += (tk - lt) * lu / ppq / 1000
        return ms

    out = []
    for st, dur, n, vel, ch, tr in sorted(notes):
        out.append(dict(t=round(to_ms(st)), d=max(28, round(to_ms(st+dur) - to_ms(st))),
                        note=n, vel=vel, ch=ch, tr=tr))
    return out

ref = parse(pathlib.Path(__file__).with_name("test.mid"))
print("参考实现解析出", len(ref), "个音符")
print("前 8 个:", json.dumps(ref[:8]))
pathlib.Path(__file__).with_name("ref.json").write_text(json.dumps(ref), encoding="utf-8")

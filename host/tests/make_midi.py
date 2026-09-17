import struct, random, pathlib

PPQ = 480
def vlq(n):
    out = bytearray([n & 0x7f]); n >>= 7
    while n: out.insert(0, (n & 0x7f) | 0x80); n >>= 7
    return bytes(out)

def chunk(cid, payload): return cid + struct.pack(">I", len(payload)) + payload

def meta_text(mtype, s):
    b = s.encode("utf-8")
    return b"\xff" + bytes([mtype]) + vlq(len(b)) + b

# ---- 轨道 0: 速度与曲名 ----
meta = b""
meta += vlq(0) + meta_text(0x03, "节奏")
meta += vlq(0) + b"\xff\x51\x03" + struct.pack(">I", 500000)[1:]
meta += vlq(1920) + b"\xff\x51\x03" + struct.pack(">I", 400000)[1:]
meta += vlq(1920) + b"\xff\x51\x03" + struct.pack(">I", 300000)[1:]
meta += vlq(0) + b"\xff\x2f\x00"
trk0 = chunk(b"MTrk", meta)

# ---- 轨道 1: 旋律 (故意使用 running status + 密集音符压测) ----
random.seed(7)
ev = b""
ev += vlq(0) + meta_text(0x03, "右手旋律")

status = 0x90
prev = None
tick = 0
scale = [60,62,64,65,67,69,71,72,74,76,77,79,81,83,84]
for i, n in enumerate(scale):
    d = 240
    body = bytes([n, 90])
    if prev == status:
        ev += vlq(0) + body
    else:
        ev += vlq(0) + bytes([status]) + body
        prev = status
    tick += d
    ev += vlq(d) + bytes([0x80, n, 0])   # note off (显式状态, 打断 running status)
    prev = 0x80

# 一段密集快速音 (模拟快速走句) —— 用来观察峰值命令速率
for i in range(60):
    n = 55 + (i * 7) % 25
    ev += vlq(0) + bytes([0x90, n, 100])
    ev += vlq(60) + bytes([0x80, n, 0])
    tick += 60

# 和弦 (同时 5 个音, 看丢音策略)
for c in ([60,64,67,72,76], [62,65,69,74,77]):
    for n in c:
        ev += vlq(0) + bytes([0x90, n, 80])
    for i, n in enumerate(c):
        ev += vlq(480 if i == 0 else 0) + bytes([0x80, n, 0])

ev += vlq(0) + b"\xff\x2f\x00"
trk1 = chunk(b"MTrk", ev)

header = chunk(b"MThd", struct.pack(">HHH", 1, 2, PPQ))
out = pathlib.Path(__file__).with_name("test.mid")
out.write_bytes(header + trk0 + trk1)

# 顺带生成一个 format 0 单轨版本, 验证另一条解析路径
ev0  = vlq(0) + b"\xff\x51\x03" + struct.pack(">I", 600000)[1:]
prev = None
for i, n in enumerate([64,67,69,72]):
    ev0 += vlq(0) + bytes([0x90, n, 100]); prev = 0x90
    ev0 += vlq(480) + bytes([0x80, n, 0]); prev = 0x80
ev0 += vlq(0) + b"\xff\x2f\x00"
pathlib.Path(__file__).with_name("test_f0.mid").write_bytes(
    chunk(b"MThd", struct.pack(">HHH", 0, 1, PPQ)) + chunk(b"MTrk", ev0))

print("wrote", out, out.stat().st_size, "bytes")

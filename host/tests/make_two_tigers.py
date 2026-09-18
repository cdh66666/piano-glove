"""生成《两只老虎》的 MIDI 演奏文件（零依赖，手写 MIDI 字节）。

用法：
    python host/tests/make_two_tigers.py [输出路径]

为什么手写而不是引第三方库：整个项目的上位机是"单文件、零依赖、能直接双击打开"，
生成工具也保持同样风格，别人拿到仓库不用装任何东西就能重新生成。

编配说明（这也是选它的原因）：
    旋律只用到 C D E F G A 六个音 —— 正好对应手套的 6 根手指。
    所以「音高对应」这个分配方式在它上面特别好看：一个音固定一根手指，
    按下哪个音用哪根手指一目了然，适合拿来核对编号对不对。
"""

import struct
import sys
from pathlib import Path

BPM = 120
DIV = 480                      # 每四分音符 480 tick
PPQ = DIV


def vlq(n: int) -> bytes:
    """MIDI 变长数量（variable length quantity）。"""
    if n < 0:
        raise ValueError(n)
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


# (音高, 拍数) —— 音高用中央 C = 60 的 MIDI 编号
# 1=C4 2=D4 3=E4 4=F4 5=G4 6=A4
MELODY = [
    # 两只老虎
    (60, 1), (62, 1), (64, 1), (60, 1),
    # 两只老虎
    (60, 1), (62, 1), (64, 1), (60, 1),
    # 跑得快
    (64, 1), (65, 1), (67, 2),
    # 跑得快
    (64, 1), (65, 1), (67, 2),
    # 一只没有眼睛
    (67, .5), (69, .5), (67, .5), (65, .5), (64, 1), (60, 1),
    # 一只没有尾巴
    (67, .5), (69, .5), (67, .5), (65, .5), (64, 1), (60, 1),
    # 真奇怪
    (62, 1), (67, 1), (60, 2),
    # 真奇怪
    (62, 1), (67, 1), (60, 2),
]


def build_track() -> bytes:
    ev = bytearray()

    # 速度：120 BPM
    ev += vlq(0) + b"\xFF\x51\x03" + struct.pack(">I", int(60_000_000 / BPM))[1:]
    # 曲名
    title = "两只老虎 (Two Tigers)".encode("utf-8")
    ev += vlq(0) + b"\xFF\x03" + vlq(len(title)) + title
    # 拍号 4/4
    ev += vlq(0) + b"\xFF\x58\x04\x04\x02\x18\x08"

    # 上一个音符"抬起之后剩下的间隔"，第一个音符之前没有间隔，所以从 0 开始
    carry = 0

    for pitch, beats in MELODY:
        ticks = int(round(beats * PPQ))
        hold  = max(1, int(ticks * 0.8))
        # 按下（力度 100）—— delta 用「上一个音符抬起后剩下的间隔」
        ev += vlq(carry) + bytes([0x90, pitch, 100])
        # 抬起（留 80% 发声时长，和调试台演奏页的默认处理一致）
        ev += vlq(hold) + bytes([0x80, pitch, 0])
        # 剩下的 20% 是"时间"不是"事件"：它必须并进**下一个**音符的 delta。
        # 曾经在这里直接写了一个裸的 vlq(ticks - hold)，后面没有跟事件字节，
        # 解析器就会把这个 delta 后面的下一个字节当成状态字节，导致整条轨道错位
        # —— 现象是"只解出 1 个音符 / 文件有损坏的字段"。（这个坑踩过，已由 check_midi.py 抓到）
        carry = ticks - hold

    # 轨道结束（把最后一个音符剩下的间隔补上）
    ev += vlq(carry) + b"\xFF\x2F\x00"
    return b"MTrk" + struct.pack(">I", len(ev)) + bytes(ev)


def build_file() -> bytes:
    track = build_track()
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, DIV) + track


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("host/samples/two-tigers.mid")
    out.parent.mkdir(parents=True, exist_ok=True)
    data = build_file()
    out.write_bytes(data)
    beats = sum(b for _, b in MELODY)
    print(f"已写入 {out}  ({len(data)} 字节)")
    print(f"  音符 {len(MELODY)} 个 / {beats:g} 拍 / {BPM} BPM / 约 {beats * 60 / BPM:.1f} 秒")
    print(f"  音域 {min(p for p, _ in MELODY)}~{max(p for p, _ in MELODY)}"
          f"（C4~A4，正好 6 个音 = 6 根手指）")


if __name__ == "__main__":
    main()

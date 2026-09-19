# -*- coding: utf-8 -*-
"""生成 10 首分级钢琴曲 MIDI 样本（零依赖，手写 MIDI 字节）。

用法：
    python host/tests/make_samples.py            # 生成全部 10 首到 host/samples/，并逐首自检
    python host/tests/make_samples.py --list     # 只打清单，不写文件

「无指法」自检是**默认开着**的，不是可选项 —— 生成的每个文件都会被解析一遍
（见 audit_no_fingering），发现任何 Text / Lyric 之类的 meta 就直接报错退出码 1。

═══════════════════════════════════════════════════════════════════════
这些 MIDI 里**没有任何指法信息** —— 这是刻意设计，也是本文件最重要的约定
═══════════════════════════════════════════════════════════════════════

文件里只写四类事件：曲名（0x03）／速度（0x51）／拍号（0x58）／音符开关。
一个字节关于「哪个音用哪根手指」的信息都没有，连轨道名都只有一句曲名。

手指分配全部由上位机在导入时**自动算**出来（web_piano_glove.html 的 buildPlan()）：
  · 轮流分配（默认）—— 谁的活儿先干完谁接下一个音，节奏最完整、手指动得最匀
  · 音高对应      —— 低音偏拇指侧、高音偏小指侧，更像真手型

所以同一份样本文件换一种分配方式，就能得到完全不同的指法，MIDI 不用改。
**要测指法，测的是上位机的分配算法，不是这些文件。**
（指法表见 samples/FINGERING.md，那份是跑真实分配算法导出的，不是人写的谱。）

分级 L1 最容易、L5 最难，每级两首：

    L1 入门   小星星 / 玛丽有只小羊羔          6 个音以内，一音对一指，核对编号用
    L2 简单   欢乐颂 / 伦敦桥                  音阶级进 + 附点节奏，音域扩到 8 度
    L3 初级   铃儿响叮当 / 平安夜              同音反复提速 + 长音，考验起停调度
    L4 中级   致爱丽丝 / 卡农                  半音邻音 + 宽音域跳进，考验分配质量
    L5 挑战   月光奏鸣曲 / 革命练习曲          三连音连绵 + 多声部柱式和弦，
                                              **拍点上同时响 5 个音**，压命令速率上限

一条实测结论（先记在这儿，省得后人再猜）：**光靠「音符密」压不垮手套。**
上位机的触键时长夹在 55~200ms，6 根手指轮转足够 —— 单声部旋律哪怕全是十六分音符，
也不会丢音。真正决定成败的是**同一时刻要几根手指**。所以 L5 那首用了柱式和弦，
而不是更快的单音跑动。
"""

import json
import struct
import sys
from base64 import b64encode
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):          # Windows 控制台默认 GBK，中文会炸
    sys.stdout.reconfigure(encoding="utf-8")

PPQ = 480                                       # 每四分音符的 tick 数

# ─────────────────────────── MIDI 基础件 ───────────────────────────

def vlq(n: int) -> bytes:
    """MIDI 变长数量（variable length quantity）。"""
    if n < 0:
        raise ValueError("vlq 不接受负数，说明事件的绝对 tick 没排好序")
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def m(name: str) -> int:
    """音名 → MIDI 编号。m("C4")=60，m("A#3")=58，m("G#3")=56。

    直接写数字的谱子没法校对，写音名才能一眼看出对不对。
    """
    s = name.strip()
    i = 1
    while i < len(s) and s[i] in "#b":
        i += 1
    pc = _PC[s[0].upper()]
    for ch in s[1:i]:
        pc += 1 if ch == "#" else -1
    return (int(s[i:]) + 1) * 12 + pc


class Track:
    """收集 (绝对tick, 数据)，最后统一排序写出。

    为什么不边生成边写 delta：曲子里有「低音和右手首音同时响」这种事件，
    还有「低音持续到下一个事件之后」的长音。按生成顺序写 delta 会出现负数
    （上一个音还没抬，下一个音就要落了），而绝对 tick + 统一排序天然没这个问题。
    """

    def __init__(self):
        self.evs = []                # (tick, prio, 生成序, bytes)
        self._i = 0

    def add(self, tick: int, data: bytes, prio: int = 1):
        self.evs.append((tick, prio, self._i, data))
        self._i += 1

    def meta(self, tick: int, data: bytes):
        """元事件：prio=0，永远排在同时刻的音符事件之前。"""
        self.add(tick, data, 0)

    def render(self) -> bytes:
        # prio 让「抬指」排在「按指」前面：同一 tick 上先关后开，
        # 否则同音高的连续两个音会被后一个 on 吞掉，听起来少一个音。
        self.evs.sort(key=lambda e: (e[0], 0 if e[3][0] in (0x80,) else e[1], e[2]))
        cur = 0
        out = bytearray()
        for tick, _p, _s, data in self.evs:
            out += vlq(tick - cur) + data
            cur = tick
        out += vlq(0) + b"\xFF\x2F\x00"          # End of Track
        return b"MTrk" + struct.pack(">I", len(out)) + bytes(out)


def _pitches(p):
    """归一化成音高列表，并**去重**。

    同一时刻、同一个音高出现两次，在 MIDI 里是没有意义的 —— 一个键只能按一次，
    解析器（上位机的和任何 DAW 的）都会把后一个 note-on 当成重复触发而合并掉。
    这是编配多声部时最容易犯的错：《革命练习曲》里左手琶音的音恰好落在
    右手和弦的音上（都是 Cm 的组成音），不去重的话文件标称 256 个音、
    实际只解析出 240 —— 差的那 16 个是撞车的。
    """
    lst = [p] if isinstance(p, int) else list(p)
    out = []
    for x in lst:
        if x not in out:
            out.append(x)
    return out


def _norm(item):
    """(拍数, 音) → (拍数, [音], 保持拍数)；三元组则保持拍数由调用者显式给。"""
    if len(item) == 2:
        beats, p = item
        return float(beats), _pitches(p), float(beats) * 0.8
    beats, p, hold = item
    return float(beats), _pitches(p), float(hold)


def song_ticks(events):
    """(拍数, 音[, 保持]) 序列 → [(on_tick, off_tick, [音])]，并返回总拍数。"""
    out = []
    cur = 0.0
    for item in events:
        beats, ps, hold = _norm(item)
        on = int(round(cur * PPQ))
        off = on + max(1, int(round(hold * PPQ)))
        out.append((on, off, ps))
        cur += beats
    return out, cur


def build_midi(song) -> bytes:
    """把一首曲子写成完整的 .mid 字节（format 0，单轨）。"""
    t = Track()
    t.meta(0, b"\xFF\x03" + vlq(len(song["title_bytes"])) + song["title_bytes"])
    t.meta(0, b"\xFF\x51\x03" + struct.pack(">I", int(60_000_000 / song["bpm"]))[1:])
    num, den = song["timesig"]
    t.meta(0, b"\xFF\x58\x04" + bytes([num, den.bit_length() - 1, 24, 8]))

    for on, off, ps in song["ticks"]:
        for p in ps:
            t.add(on, bytes([0x90, p, 100]))
        for p in ps:
            t.add(off, bytes([0x80, p, 0]))

    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ) + t.render()


# ─────────────────────────── 无指法自检 ───────────────────────────

_META_NAMES = {
    0x00: "SequenceNumber", 0x01: "Text", 0x02: "Copyright", 0x03: "TrackName",
    0x04: "InstrumentName", 0x05: "Lyric", 0x06: "Marker", 0x07: "CuePoint",
    0x20: "ChannelPrefix", 0x21: "Port", 0x2F: "EndOfTrack", 0x51: "SetTempo",
    0x54: "SMPTEOffset", 0x58: "TimeSignature", 0x59: "KeySignature",
    0x7F: "SequencerSpecific",
}

# 允许出现的 meta：曲名、速度、拍号、结束。
# 特别注意**不允许** 0x01(Text) / 0x05(Lyric) —— 这两类是「指法」最常见的藏身之处：
# 谱面软件常把 finger 数字写进 Text 事件或歌词里，人眼看不出来但解析器读得到。
_ALLOWED_META = {0x03, 0x51, 0x58, 0x2F}


def audit_no_fingering(data: bytes):
    """扫一遍所有 meta 事件，返回 (meta类型计数, 违规列表)。

    这是对「MIDI 不含指法」这个承诺的机器校验 —— 不靠人看，靠解析。
    """
    if data[:4] != b"MThd":
        raise ValueError("不是 MIDI 文件")
    _len, _fmt, _ntrk, _div = struct.unpack(">IHHH", data[4:14])
    p = 14
    kinds, bad = {}, []

    while p < len(data):
        if data[p:p + 4] != b"MTrk":
            break
        size = struct.unpack(">I", data[p + 4:p + 8])[0]
        end, p = p + 8 + size, p + 8
        running = None
        while p < end:
            delta = 0
            while True:
                b = data[p]; p += 1
                delta = (delta << 7) | (b & 0x7F)
                if not (b & 0x80):
                    break
            st = data[p]
            if st & 0x80:
                p += 1
                running = st
            else:
                st = running
                if st is None:
                    break
            if st == 0xFF:
                mt = data[p]; p += 1
                ln = 0
                while True:
                    b = data[p]; p += 1
                    ln = (ln << 7) | (b & 0x7F)
                    if not (b & 0x80):
                        break
                body = data[p:p + ln]; p += ln
                name = _META_NAMES.get(mt, "0x%02X" % mt)
                kinds[name] = kinds.get(name, 0) + 1
                if mt not in _ALLOWED_META:
                    bad.append((name, body[:60]))
                elif mt == 0x03 and any(k in body.lower() for k in
                                        (b"finger", b"\xe6\x8c\x87", b"fingering")):
                    bad.append((name, body[:60]))
            elif st in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                p += 2
            elif st in (0xC0, 0xD0):
                p += 1
            elif st in (0xF0, 0xF7):
                ln = 0
                while True:
                    b = data[p]; p += 1
                    ln = (ln << 7) | (b & 0x7F)
                    if not (b & 0x80):
                        break
                p += ln
            else:
                break
        p = end
    return kinds, bad


# ─────────────────────────── 曲库 ───────────────────────────
# 谱子一律用音名写，方便校对。二元组 (拍数, 音)；三元组 (拍数, 音, 保持拍数)。
# 「拍数」是**距离上一个事件开始**的拍数，可以是 0 —— 表示与上一个音同刻响（和弦/低音同响）。

TWINKLE = [
    (1, m("C4")), (1, m("C4")), (1, m("G4")), (1, m("G4")), (1, m("A4")), (1, m("A4")), (2, m("G4")),
    (1, m("F4")), (1, m("F4")), (1, m("E4")), (1, m("E4")), (1, m("D4")), (1, m("D4")), (2, m("C4")),
    (1, m("G4")), (1, m("G4")), (1, m("F4")), (1, m("F4")), (1, m("E4")), (1, m("E4")), (2, m("D4")),
    (1, m("G4")), (1, m("G4")), (1, m("F4")), (1, m("F4")), (1, m("E4")), (1, m("E4")), (2, m("D4")),
    (1, m("C4")), (1, m("C4")), (1, m("G4")), (1, m("G4")), (1, m("A4")), (1, m("A4")), (2, m("G4")),
    (1, m("F4")), (1, m("F4")), (1, m("E4")), (1, m("E4")), (1, m("D4")), (1, m("D4")), (2, m("C4")),
]

MARY = [
    (1, m("E4")), (1, m("D4")), (1, m("C4")), (1, m("D4")),
    (1, m("E4")), (1, m("E4")), (2, m("E4")),
    (1, m("D4")), (1, m("D4")), (2, m("D4")),
    (1, m("E4")), (1, m("G4")), (2, m("G4")),
    (1, m("E4")), (1, m("D4")), (1, m("C4")), (1, m("D4")),
    (1, m("E4")), (1, m("E4")), (1, m("E4")), (1, m("E4")),
    (1, m("D4")), (1, m("D4")), (1, m("E4")), (1, m("D4")),
    (4, m("C4")),
]

ODE = [
    (1, m("E4")), (1, m("E4")), (1, m("F4")), (1, m("G4")),
    (1, m("G4")), (1, m("F4")), (1, m("E4")), (1, m("D4")),
    (1, m("C4")), (1, m("C4")), (1, m("D4")), (1, m("E4")),
    (1.5, m("E4")), (0.5, m("D4")), (2, m("D4")),
    (1, m("E4")), (1, m("E4")), (1, m("F4")), (1, m("G4")),
    (1, m("G4")), (1, m("F4")), (1, m("E4")), (1, m("D4")),
    (1, m("C4")), (1, m("C4")), (1, m("D4")), (1, m("E4")),
    (1.5, m("D4")), (0.5, m("C4")), (2, m("C4")),
]

LONDON = [
    (1, m("G4")), (1, m("A4")), (1, m("G4")), (1, m("F4")),
    (1, m("E4")), (1, m("F4")), (2, m("G4")),
    (1, m("D4")), (1, m("E4")), (2, m("F4")),
    (1, m("E4")), (1, m("F4")), (2, m("G4")),
    (1, m("G4")), (1, m("A4")), (1, m("G4")), (1, m("F4")),
    (1, m("E4")), (1, m("F4")), (2, m("G4")),
    (1, m("D4")), (1, m("G4")), (2, m("E4")),
    (4, m("C4")),
]

JINGLE = [
    (1, m("E4")), (1, m("E4")), (2, m("E4")),
    (1, m("E4")), (1, m("E4")), (2, m("E4")),
    (1, m("E4")), (1, m("G4")), (1, m("C4")), (1, m("D4")), (4, m("E4")),
    (1, m("F4")), (1, m("F4")), (1, m("F4")), (1, m("F4")),
    (1, m("F4")), (1, m("E4")), (1, m("E4")), (1, m("E4")),
    (1, m("E4")), (1, m("D4")), (1, m("D4")), (1, m("E4")), (2, m("D4")), (2, m("G4")),
]

SILENT_NIGHT = [
    (1.5, m("G4")), (0.5, m("A4")), (1, m("G4")), (3, m("E4")),
    (1.5, m("G4")), (0.5, m("A4")), (1, m("G4")), (3, m("E4")),
    (2, m("D5")), (1, m("D5")), (3, m("B4")),
    (2, m("C5")), (1, m("C5")), (3, m("G4")),
    (2, m("A4")), (1, m("A4")), (1.5, m("C5")), (0.5, m("B4")), (1, m("A4")),
    (2, m("G4")), (1, m("G4")), (1.5, m("A4")), (0.5, m("G4")), (1, m("E4")),
    (2, m("C5")), (1, m("C5")), (1.5, m("D5")), (0.5, m("B4")), (1, m("G4")),
    (3, m("A4")), (1.5, m("G4")), (0.5, m("A4")), (1, m("G4")),
    (3, m("E4")), (3, m("C5")),
]

FUR_ELISE = [
    (0.5, m("E5")), (0.5, m("D#5")), (0.5, m("E5")), (0.5, m("D#5")),
    (0.5, m("E5")), (0.5, m("B4")), (0.5, m("D5")), (0.5, m("C5")),
    (0.5, m("A4")), (0.5, m("C4")), (0.5, m("E4")), (0.5, m("A4")),
    (0.5, m("B4")), (0.5, m("E4")), (0.5, m("G#4")), (0.5, m("B4")),
    (0.5, m("C5")), (0.5, m("E4")), (0.5, m("E5")), (0.5, m("D#5")),
    (0.5, m("E5")), (0.5, m("D#5")), (0.5, m("E5")), (0.5, m("B4")),
    (0.5, m("D5")), (0.5, m("C5")), (0.5, m("A4")), (0.5, m("C4")),
    (0.5, m("E4")), (0.5, m("A4")), (0.5, m("B4")), (0.5, m("E4")),
    (0.5, m("C5")), (0.5, m("B4")), (3, m("A4")),
]

CANON = [
    (2, m("F#5")), (2, m("E5")), (2, m("D5")), (2, m("C#5")),
    (2, m("B4")), (2, m("A4")), (2, m("B4")), (2, m("C#5")),
    (2, m("D5")), (2, m("C#5")), (2, m("B4")), (2, m("A4")),
    (2, m("G4")), (2, m("F#4")), (2, m("G4")), (2, m("E4")),
    (2, m("F#4")), (2, m("E4")), (2, m("D4")), (2, m("C#4")),
    (2, m("D4")), (2, m("E4")), (2, m("F#4")), (4, m("F#4")),
]


def moonlight():
    """月光奏鸣曲 第一乐章（C# 小调，三连音 + 低音），简化成 8 小节。

    只保留「右手三连音跑动 + 左手和弦根音」这个骨架 —— 它正是这一乐章最难的部分：
    连绵不断的三连音没有一处空隙，手套必须一直动，是最接近「真实钢琴曲」的样本。
    """
    prog = [
        ([m("G#3"), m("C#4"), m("E4")], m("C#3")),      # C#m
        ([m("G#3"), m("C#4"), m("E4")], m("C#3")),
        ([m("E3"),  m("A3"),  m("C#4")], m("A2")),      # A
        ([m("E3"),  m("A3"),  m("C#4")], m("A2")),
        ([m("C#4"), m("F#4"), m("A4")],  m("F#2")),     # F#m
        ([m("C#4"), m("F#4"), m("A4")],  m("F#2")),
        ([m("B3"),  m("D#4"), m("G#4")], m("G#2")),     # G#
        ([m("B3"),  m("D#4"), m("G#4")], m("G#2")),
    ]
    ev = []
    for broken, bass in prog:
        for i in range(4):                              # 每小节 4 组三连音
            for k, p in enumerate(broken):
                if i == 0 and k == 0:
                    # 低音和右手首音**同刻**响（beats=0 的写法在这儿用上），
                    # 持音给满一小节，模拟左手的持续低音
                    ev.append((1 / 3, [p, bass], 1.0))
                else:
                    ev.append((1 / 3, p))
    return ev


def revolutionary():
    """肖邦《革命练习曲》Op.10 No.12 的开头动机（C 小调）。

    这是 10 首里对手套负载最重的一首，选它是因为**它是唯一真正「音比手多」的样本**：
      · 左手：十六分音符琶音连绵跑动，全程不停（BPM 160 下每 94ms 一个音）
      · 右手：每拍一个柱式和弦（4 个音同时）
      · 两者叠加 → 拍点上**同时响 5 个音**，6 根手指要用掉 5 根
    整体约 21 个音/秒、峰值 40+ 条命令/秒，是压固件命令速率上限的那一首。

    对比一下就清楚了：光靠「音符密」是压不垮手套的 —— 单声部旋律哪怕练成十六分音符，
    上位机的触键时长也只有 55~200ms，6 根手指轮转绰绰有余。
    真正决定成败的是**同一时刻要几根手指**。
    """
    # (和声名, 上行琶音 8 个音 = 2 拍, 右手柱式和弦)
    prog = [
        ("Cm", [m("C3"), m("D#3"), m("G3"), m("C4"), m("D#4"), m("G4"), m("C5"), m("D#5")],
               [m("C4"), m("D#4"), m("G4"), m("C5")]),
        ("Ab", [m("G#2"), m("C3"), m("D#3"), m("G#3"), m("C4"), m("D#4"), m("G#4"), m("C5")],
               [m("G#3"), m("C4"), m("D#4"), m("G#4")]),
        ("G",  [m("G2"), m("B2"), m("D3"), m("G3"), m("B3"), m("D4"), m("G4"), m("B4")],
               [m("G3"), m("B3"), m("D4"), m("G4")]),
        ("Cm", [m("C3"), m("D#3"), m("G3"), m("C4"), m("D#4"), m("G4"), m("C5"), m("D#5")],
               [m("C4"), m("D#4"), m("G4"), m("C5")]),
    ]
    ev = []
    for _ in range(2):                              # 进行跑两遍 = 8 小节
        for _name, up, chord in prog:
            bass = up + list(reversed(up))          # 上行 + 下行 = 16 个十六分 = 4 拍
            for k, p in enumerate(bass):
                # 每拍的第一、五、九、十三个位置上，右手和弦与左手音**同刻**响
                ev.append((0.25, [p] + chord if k % 4 == 0 else p))
    return ev


SPECS = [
    dict(slug="twinkle", title="小星星", level=1, level_name="入门",
         bpm=100, timesig=(4, 4), events=TWINKLE,
         desc="旋律只用 C D E F G A 六个音，正好一个音一根手指。"
              "拿来核对「编号 ↔ 手指」最合适：听哪个音不对，就知道哪根手指编错了。",
         tests="编号核对 · 一音对一指"),
    dict(slug="mary", title="玛丽有只小羊羔", level=1, level_name="入门",
         bpm=110, timesig=(4, 4), events=MARY,
         desc="同样六个音，但要求每个音独立起停 —— 考验「按一下、完全抬起、再按下一个」"
              "这个最基本的动作序列会不会粘键。",
         tests="起停干净 · 不粘键"),
    dict(slug="ode-to-joy", title="欢乐颂", level=2, level_name="简单",
         bpm=108, timesig=(4, 4), events=ODE,
         desc="音阶级进为主，加入了附点节奏（1.5 拍 + 0.5 拍）。"
              "附点会让两个相邻音的间隔明显不一样，能看出节奏有没有被固件拖平。",
         tests="附点节奏 · 时值区分"),
    dict(slug="london-bridge", title="伦敦桥", level=2, level_name="简单",
         bpm=112, timesig=(4, 4), events=LONDON,
         desc="级进旋律 + 一次跨四度的跳进。速度稍快，看分配算法在相邻音之间"
              "会不会来回抢同一根手指。",
         tests="级进分配 · 略快速度"),
    dict(slug="jingle-bells", title="铃儿响叮当", level=3, level_name="初级",
         bpm=120, timesig=(4, 4), events=JINGLE,
         desc="开头是连续的同音反复（E E E / E E E）。同音反复是最好抓的漏音场景："
              "少一下马上就听得出来。",
         tests="同音反复 · 漏音检测"),
    dict(slug="silent-night", title="平安夜", level=3, level_name="初级",
         bpm=96, timesig=(3, 4), events=SILENT_NIGHT,
         desc="3/4 拍，附点 + 长音交替。长音期间手指是闲着的，"
              "可以观察手套能不能在长音里安静待住、不发抖。",
         tests="3/4 拍 · 长音保持"),
    dict(slug="fur-elise", title="致爱丽丝", level=4, level_name="中级",
         bpm=100, timesig=(3, 4), events=FUR_ELISE,
         desc="半音邻音（E–D#–E）密集出现，音域从 C4 拉到 E5。"
              "半音相邻的两个音在「音高对应」分配下会落到相邻手指，是分配质量的分水岭。",
         tests="半音邻音 · 宽音域"),
    dict(slug="canon", title="卡农", level=4, level_name="中级",
         bpm=84, timesig=(4, 4), events=CANON,
         desc="每音两拍，音域跨 C#4~F#5。音符少、间隔大，是不丢音的基准线 ——"
              "如果连它都丢音，说明问题不在速度，而在分配或通信。",
         tests="基准线 · 应当零丢音"),
    dict(slug="moonlight", title="月光奏鸣曲（一）", level=5, level_name="挑战",
         bpm=50, timesig=(4, 4), events=moonlight(),
         desc="连绵不断的三连音 + 左手低音同响，全曲没有一处空隙，手指一直在动。"
              "它会稳定地丢掉一部分音 —— 这正是设计目标：保住节奏、主动降级，绝不卡住。",
         tests="三连音密集 · 和弦同响 · 预期丢音"),
    dict(slug="revolutionary", title="革命练习曲", level=5, level_name="挑战",
         bpm=160, timesig=(4, 4), events=revolutionary(),
         desc="肖邦 Op.10 No.12 的开头动机：左手十六分音符琶音全程不停，右手每拍一记柱式和弦。"
              "**10 首里唯一真正「音比手多」的样本** —— 拍点上同时响 5 个音，"
              "约 21 个音/秒、峰值 40+ 条命令/秒，专门用来压固件的命令速率上限。",
         tests="多声部叠加 · 同时音最多 · 命令速率上限"),
]


# ─────────────────────────── 同步到调试台 ───────────────────────────
#
# 调试台的曲库是**内嵌**的（base64 直接写进 HTML），不是 fetch：
# 调试台要能直接双击打开（file://），而 file:// 下 fetch 本地文件会被浏览器拦掉，
# 那样曲库就整个失效了。所以由本脚本把 .mid 编码成 base64 注入 HTML 的标记区块，
# 保证「磁盘上的样本」和「网页里的曲库」永远是同一份字节。
#
# 手工把 6KB base64 粘进 HTML 是不可能保持同步的 —— 所以这一步必须自动化。

LIB_BEGIN = "/* === SONG LIB BEGIN === */"
LIB_END = "/* === SONG LIB END === */"


def song_lib_js(songs) -> str:
    j = lambda v: json.dumps(v, ensure_ascii=False)
    items = []
    for s in songs:
        b64 = b64encode(build_midi(s)).decode("ascii")
        items.append(
            "  {slug:%s, title:%s, level:%d, levelName:%s, bpm:%d, timesig:[%d,%d],\n"
            "   notes:%d, seconds:%s, beats:%s,\n"
            "   tests:%s, desc:%s,\n"
            "   b64:%s}"
            % (j(s["slug"]), j(s["title"]), s["level"], j(s["level_name"]),
               s["bpm"], s["timesig"][0], s["timesig"][1],
               s["note_count"], j(round(s["seconds"], 1)), j(round(s["beats"], 2)),
               j(s["tests"]), j(s["desc"]), j(b64)))
    return "const SONG_LIB = [\n" + ",\n".join(items) + "\n];"


def sync_html(html_path: Path, lib_js: str) -> str:
    """把曲库注入 HTML 的两个标记之间。返回一句结果说明。

    全程走 bytes，只替换标记之间的内容 —— 不碰文件其余任何一个字节，
    免得顺手把行尾（CRLF）或编码改掉。
    """
    if not html_path.exists():
        return "跳过：找不到 %s" % html_path
    raw = html_path.read_bytes().decode("utf-8")
    if LIB_BEGIN not in raw or LIB_END not in raw:
        return "跳过：HTML 里没有 %s / %s 标记" % (LIB_BEGIN, LIB_END)

    nl = "\r\n" if "\r\n" in raw else "\n"
    i = raw.index(LIB_BEGIN) + len(LIB_BEGIN)
    j = raw.index(LIB_END)
    out = raw[:i] + nl + lib_js.replace("\n", nl) + nl + raw[j:]
    html_path.write_bytes(out.encode("utf-8"))
    return "已同步 %s（内嵌 %d 首，%.1f KB）" % (
        html_path.name, lib_js.count("{slug:"), len(lib_js) / 1024)


# ─────────────────────────── 主流程 ───────────────────────────

def prepare(spec):
    ticks, beats = song_ticks(spec["events"])
    note_count = sum(len(ps) for _on, _off, ps in ticks)
    seconds = beats * 60.0 / spec["bpm"]
    return {**spec,
            "ticks": ticks,
            "beats": beats,
            "note_count": note_count,
            "seconds": seconds,
            "title_bytes": spec["title"].encode("utf-8"),
            "issues": None}


def main():
    argv = sys.argv[1:]
    out_dir = Path(__file__).resolve().parents[1] / "samples"
    songs = [prepare(s) for s in SPECS]
    names = ("级别  曲名                  BPM  拍号  音符  时长    文件\n"
             + "-" * 74)
    for s in songs:
        sec = s["seconds"]
        names += ("\nL%d %-4s %-18s %4d  %d/%d %5d  %4.0f:%02d  %s.mid"
                  % (s["level"], s["level_name"], s["title"], s["bpm"],
                     s["timesig"][0], s["timesig"][1], s["note_count"],
                     int(sec) // 60, int(sec) % 60, s["slug"]))

    if "--list" in argv:
        print(names)
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    catalog = {
        "note": "本目录下所有 .mid 均不含任何指法信息；手指分配由上位机 buildPlan() 自动完成。"
                "指法表见 FINGERING.md。",
        "generator": "host/tests/make_samples.py",
        "songs": [],
    }

    print(names + "\n")
    for s in songs:
        data = build_midi(s)
        path = out_dir / (s["slug"] + ".mid")
        path.write_bytes(data)

        kinds, bad = audit_no_fingering(data)
        s["issues"] = bad
        catalog["songs"].append({
            "slug": s["slug"], "file": s["slug"] + ".mid", "title": s["title"],
            "level": s["level"], "levelName": s["level_name"], "bpm": s["bpm"],
            "timesig": list(s["timesig"]), "beats": round(s["beats"], 2),
            "notes": s["note_count"], "seconds": round(s["seconds"], 1),
            "desc": s["desc"], "tests": s["tests"],
        })
        flag = "OK" if not bad else "!! 违规 %d" % len(bad)
        print("%-12s %5d 字节  %2d 音符  meta=%s  %s"
              % (path.name, len(data), s["note_count"],
                 ",".join("%s×%d" % (k, v) for k, v in sorted(kinds.items())), flag))
        for name, body in bad:
            print("              ↑ 不该出现的 meta：%s %r" % (name, body))

    (out_dir / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n已写入 %s" % (out_dir / "catalog.json"))

    # 把曲库同步进调试台（.mid 是唯一真相源，HTML 里的 base64 由它派生）
    try:
        print(sync_html(Path(__file__).resolve().parents[1] / "web_piano_glove.html",
                        song_lib_js(songs)))
    except Exception as e:                                     # noqa: BLE001
        print("✘ 同步 HTML 失败：%s" % e)
        return 1

    total_bad = sum(len(s["issues"] or []) for s in songs)
    if total_bad:
        print("\n✘ 有 %d 处 meta 事件不符合「不含指法」的约定" % total_bad)
        return 1
    print("✔ 10 首全部通过「无指法」自检：只含 曲名/速度/拍号/结束 四类 meta，"
          "一个字节的指法信息都没有")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

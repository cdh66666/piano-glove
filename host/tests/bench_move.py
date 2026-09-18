"""实机验证：发了 MOVE 之后，舵机到底动没动。

用法：
    python host/tests/bench_move.py [PORT] [--slot 1,2,3] [--wait MS] [--rate]
                                    [--rate-depth 60] [--rate-cycles 3] [--force] [--no-move]

为什么需要它：
    「点一下试动作，只有电机锁住了、舵机纹丝不动」这个问题，从串口回的字面上
    是看不出来的 —— 固件回了 OK，就说明它把指令发出去了；舵机到底有没有转，
    只有一个办法能证明：**发指令之前读一次位置，发完再读一次，比差值**。

    这个脚本就是干这件事的。它不猜，它量。

判定口径：
    delta < 30 计数  -> 没动（或只抖了一下）。30 计数 ≈ 2.6°（4095 量程）。
    delta >= 30      -> 真的动了。

两条安全闸（都是实机踩出来的）：
    1. **校准自检**：舵机现在就停在某个位置，理应在"静止位"附近。
       差得超过 CAL_SUSPECT，说明这个槽位的校准根本不是这块舵机的
       （改过号 / 换过舵机没重新校准）—— 默认跳过，`--force` 才动。
       硬拿错的行程去驱动，很容易顶到机械限位。
    2. **重复 id 检测**：两个槽位指向同一块舵机时报出来。
       除了"两根手指一起动"，还会让多槽位 SYNC_READ 少收回包，
       导致测速每个半程都等满超时（实测过：`half_ms=800 lost=10`）。
"""

import argparse
import re
import sys
import time

import serial
import serial.tools.list_ports

POS_TOL = 30          # 认为「动了」的最小位移（计数）
MOVE_SETTLE_MS = 700  # 发完 MOVE 等它走完的时间

# 校准值和"舵机现在停在哪"差得超过这么多，就认为这个槽位的校准数据
# 根本不是这块舵机的（比如编号改过号、或者换了舵机没重新校准）。
# 这种槽位**默认不碰** —— 拿错的行程去驱动，很容易顶到机械限位。
CAL_SUSPECT = 600


# ------------------------------------------------------------------ 串口助手

def find_board():
    for p in serial.tools.list_ports.comports():
        dev = p.device
        if not dev.upper().startswith("COM"):
            continue
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
                        return dev
        except Exception:
            continue
    return None


class Board:
    def __init__(self, port):
        self.s = serial.Serial(port, 115200, timeout=0)
        time.sleep(0.5)
        self.s.reset_input_buffer()

    def cmd(self, text, quiet=0.20, budget=3.0):
        """发一条命令，收完这一条的回复就返回（用静默判定结束）。"""
        self.s.reset_input_buffer()
        self.s.write((text + "\r\n").encode())
        buf, t0, last = b"", time.perf_counter(), time.perf_counter()
        while time.perf_counter() - t0 < budget:
            k = self.s.in_waiting
            if k:
                buf += self.s.read(k)
                last = time.perf_counter()
            elif buf and (time.perf_counter() - last) > quiet:
                break
            else:
                time.sleep(0.001)
        return buf.decode("utf-8", "replace")

    def cmd_lines(self, text, **kw):
        return [l for l in self.cmd(text, **kw).splitlines() if l.strip()]

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


# ------------------------------------------------------------------ 解析

KV = re.compile(r"(\w+)=(\S+)")


def kv(line):
    return {k: v for k, v in KV.findall(line)}


def read_slots(b):
    """STATUS_ALL -> {slot: {pos, online, valid, lo, standby, hi, press, name, id}}"""
    out = {}
    for line in b.cmd_lines("STATUS_ALL", budget=5.0):
        if not line.startswith("SLOT"):
            continue
        d = kv(line)
        if "slot" not in d:
            continue
        s = int(d["slot"])
        out[s] = {
            "name": d.get("name", "?"),
            "id": int(d.get("id", 0)),
            "online": d.get("online") == "1",
            "pos": int(d["pos"]) if "pos" in d else None,
            "lo": int(d.get("min", 0)),
            "standby": int(d.get("standby", 0)),
            "hi": int(d.get("max", 0)),
            "valid": d.get("valid") == "1",
            "press": d.get("press", "?"),
        }
    return out


def businfo(b):
    for line in b.cmd_lines("BUSINFO", budget=4.0):
        if "servo_err" in line:
            return kv(line)
    return {}


def press_pos(sl):
    """这个槽位「按下去」应该去的目标位置。"""
    return sl["lo"] if sl["press"] == "min" else sl["hi"]


def rate_test(b, mask, speed, depth, cycles, budget=None):
    """发 RATE，一直读到 RATE_DONE。返回 (done_line, all_lines)。

    注意「静默就收工」这个判断要小心：RATE 是**中途一句话都不说**的
    （跑完才吐 RATE_DONE）。一旦某个半程真的卡到 800 ms 超时，
    整条命令能有十几秒完全没有输出 —— 如果按"静默 1.5 秒就结束"来收，
    就会把"跑得慢"误判成"没反应"。（这个坑踩过）
    所以这里只在**连 RATE_START 都没见到**时才提前收工。
    """
    if budget is None:
        budget = cycles * 2 * 0.8 + 5.0        # 每个半程最坏 800 ms + 余量

    b.s.reset_input_buffer()
    b.s.write(("RATE 0x%02X %d 0 %d %d\r\n" % (mask, speed, depth, cycles)).encode())
    buf, t0, last = b"", time.perf_counter(), time.perf_counter()
    while time.perf_counter() - t0 < budget:
        k = b.s.in_waiting
        if k:
            buf += b.s.read(k)
            last = time.perf_counter()
            if b"RATE_DONE" in buf:
                time.sleep(0.15)          # 把尾行收干净
                buf += b.s.read(b.s.in_waiting)
                break
        elif b"RATE_START" not in buf and (time.perf_counter() - last) > 2.0:
            break                          # 连"开始"都没回，板子多半不认这条命令
        else:
            time.sleep(0.001)
    text = buf.decode("utf-8", "replace")
    lines = [l for l in text.splitlines() if l.strip()]
    done = next((l for l in lines if l.startswith("RATE_DONE")), None)
    return done, lines


# ------------------------------------------------------------------ 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default=None)
    ap.add_argument("--slot", default=None,
                    help="只测某些槽位，0~5，可逗号分隔（如 1,2,3）；不给就全测")
    ap.add_argument("--force", action="store_true",
                    help="连「校准值和当前位置对不上」的槽位也照动（有顶限位的风险）")
    ap.add_argument("--wait", type=int, default=MOVE_SETTLE_MS, help="每条 MOVE 后等多少毫秒")
    ap.add_argument("--rate", action="store_true", help="跑完位移动测试后接着做速度实测")
    ap.add_argument("--rate-speed", type=int, default=0)
    ap.add_argument("--rate-depth", type=int, default=100)
    ap.add_argument("--rate-cycles", type=int, default=3)
    ap.add_argument("--no-move", action="store_true", help="只看状态，不发任何会动舵机的命令")
    args = ap.parse_args()

    port = args.port or find_board()
    if not port:
        print("找不到钢琴手套板子（没有串口回 PIANO_GLOVE）。")
        print("提示：先确认板子插好；如果调试网页开着，它会占住串口，先把网页关掉或点断开。")
        return 1
    print(f"板子：{port}\n")

    b = Board(port)
    try:
        info = ""
        for _ in range(4):
            info = next((l for l in b.cmd_lines("INFO") if l.startswith("OK INFO")), "")
            if info:
                break
            time.sleep(0.3)
        print("INFO      :", info or "(无回复)")

        be = businfo(b)
        err0 = int(be.get("servo_err", 0) or 0)
        print("BUSINFO   :", " ".join(f"{k}={v}" for k, v in be.items()) or "(无回复)")

        slots = read_slots(b)
        if not slots:
            print("\nSTATUS_ALL 没有返回任何 SLOT 行 —— 总线上一根舵机都没认到。")
            return 2

        print("\n" + "=" * 78)
        print("槽位状态")
        print("=" * 78)
        suspect = []
        for s in sorted(slots):
            sl = slots[s]
            flag = "在线" if sl["online"] else "离线"
            v = "已校准" if sl["valid"] else "未校准"
            # 校准自检：舵机现在就停在这儿，按理应该离"静止位"不远
            gap = None
            if sl["online"] and sl["valid"] and sl["pos"] is not None:
                gap = abs(sl["pos"] - sl["standby"])
            mark = ""
            if gap is not None and gap > CAL_SUSPECT:
                mark = f"   ⚠ 校准可疑：现在停在 {sl['pos']}，校准的静止位却是 {sl['standby']}（差 {gap}）"
                suspect.append(s)
            print(f"  {s}  {sl['name']:<10} id={sl['id']}  {flag}  {v}  "
                  f"当前={sl['pos']}  按下位={press_pos(sl)}  静止位={sl['standby']}"
                  f"  行程={abs(press_pos(sl) - sl['standby'])}{mark}")

        if suspect:
            print("\n  ⚠ 以下槽位的校准值不像是对应这块舵机的：" +
                  "、".join(f"{s}·{slots[s]['name']}" for s in suspect))
            print("    常见原因：编号时改过号，但没重新做第 3 步校准 ——")
            print("    校准是**按槽位存**的，槽位换了一块舵机，旧的行程就作废了。")
            print("    这几个槽位默认跳过（--force 可强行测）。")
            print("    要修：去调试网页第 3 步重做一次校准。")

        byid = {}
        for s in slots:
            byid.setdefault(slots[s]["id"], []).append(s)
        dup = {i: v for i, v in byid.items() if len(v) > 1}
        if dup:
            print("\n  ⚠ 有多个槽位指向同一块舵机：" +
                  "；".join(f"id={i} ← 槽位 " + "、".join(str(x) for x in v) for i, v in dup.items()))
            print("    这些槽位会一起动（就是同一块舵机），而且多槽位 SYNC_READ 会少收回包。")
            print("    要修：重做第 2 步编号，或者用 MAP <槽位> <正确id> 手工校正。")

        want = None
        if args.slot is not None:
            want = {int(x) for x in str(args.slot).replace("，", ",").split(",") if x.strip() != ""}
        live = [s for s in sorted(slots) if slots[s]["online"] and slots[s]["valid"]]
        if want is not None:
            live = [s for s in live if s in want]
        if not args.force:
            live = [s for s in live if s not in suspect]

        todo = [s for s in live if abs(press_pos(slots[s]) - slots[s]["standby"]) >= POS_TOL]

        if not live:
            print("\n没有「在线且已校准」的槽位，先去做编号 + 校准。")
            return 3
        for s in live:
            if s not in todo:
                print(f"\n  槽位 {s} 行程 < {POS_TOL} 计数，跳过位移动测试（太小了看不出来）。")

        if args.no_move:
            print("\n--no-move：跳过位移动测试。")
            results = []
        else:
            # ------------------------------------------------------ ARM
            print("\n" + "=" * 78)
            print("使能（ARM）")
            print("=" * 78)
            arm = b.cmd_lines("ARM", budget=5.0)
            for l in arm:
                print("  " + l)
            if not any(l.startswith("OK ARM") for l in arm):
                print("  使能没成功，后面的位移测试没有意义，停在这里。")
                return 4
            time.sleep(0.3)

            # ------------------------------------------------------ 位移测试
            print("\n" + "=" * 78)
            print(f"位移测试（每条 MOVE 后等 {args.wait} ms）")
            print("=" * 78)

            results = []
            for s in todo:
                sl = slots[s]
                name, sid = sl["name"], sl["id"]
                down, home = press_pos(sl), sl["standby"]

                before = (read_slots(b).get(s) or {}).get("pos")

                r1 = b.cmd_lines(f"MOVE {sid} {down} 0 0 ARM", budget=4.0)
                time.sleep(args.wait / 1000.0)
                mid = (read_slots(b).get(s) or {}).get("pos")

                r2 = b.cmd_lines(f"MOVE {sid} {home} 0 0 ARM", budget=4.0)
                time.sleep(args.wait / 1000.0)
                after = (read_slots(b).get(s) or {}).get("pos")

                d1 = None if (before is None or mid is None) else abs(mid - before)
                d2 = None if (mid is None or after is None) else abs(after - mid)

                def verdict(d):
                    if d is None:
                        return "读不到位置"
                    return "动了 ✔" if d >= POS_TOL else "没动 ✘"

                print(f"\n  槽位 {s} · {name} · id={sid}")
                print(f"    发 {before} → MOVE {down} → {mid}   位移 {d1}   {verdict(d1)}")
                print(f"    发 {mid} → MOVE {home} → {after}   位移 {d2}   {verdict(d2)}")
                if r1:
                    print(f"    固件回复: {r1[0]}")
                if r2 and len(r2) > 0 and r2[0] != (r1[0] if r1 else None):
                    print(f"    回位回复: {r2[0]}")

                ok = (d1 is not None and d1 >= POS_TOL) and (d2 is not None and d2 >= POS_TOL)
                results.append((s, name, d1, d2, ok))

            # ------------------------------------------------------ 位移汇总
            be2 = businfo(b)
            err1 = int(be2.get("servo_err", 0) or 0)
            moved = [r for r in results if r[4]]
            dead = [r for r in results if not r[4]]

            print("\n" + "=" * 78)
            print("位移结论")
            print("=" * 78)
            print(f"  测了 {len(results)} 根，动了 {len(moved)} 根，没动 {len(dead)} 根")
            if dead:
                print("  没动的：" + "、".join(f"{r[0]}·{r[1]}" for r in dead))
                print("  对没动的这几根，按这个顺序查：")
                print("    1. 看它是不是被机械卡住了（断电用手拨一下，应该能轻松拨动）")
                print("    2. 看舵机线是不是只接了电源没接信号（锁死但不动 = 信号线没通）")
                print("    3. 看 BUSINFO 的 servo_err 有没有涨（涨了 = 舵机在拒收指令）")
            print(f"  servo_err: {err0} -> {err1}" + ("  ⚠ 有增长，舵机在拒收指令" if err1 > err0 else "  （没增长）"))

        # ---------------------------------------------------------- 速度实测
        if args.rate and live:
            mask = 0
            for s in live:
                mask |= (1 << s)
            ids = sorted({slots[s]["id"] for s in live if (mask >> s) & 1})
            print("\n" + "=" * 78)
            print(f"速度实测 RATE 0x{mask:02X} speed={args.rate_speed} "
                  f"depth={args.rate_depth}% cycles={args.rate_cycles}   舵机 id={ids}")
            print("=" * 78)
            print("  （舵机接下来会全速来回跑，手离远一点）")
            if len(ids) != len([s for s in live if (mask >> s) & 1]):
                print(f"  ⚠ 选中的槽位里有重复 id（{ids}），同一块舵机会收到两条指令，结果偏高。")
            done, lines = rate_test(b, mask, args.rate_speed, args.rate_depth, args.rate_cycles)
            for l in lines:
                print("  " + l)
            if done:
                d = kv(done)
                hz = float(d.get("hz", 0))
                mark = "达到 6 Hz 目标 ✔" if hz >= 6 else ("过了 4 Hz 及格线" if hz >= 4 else "连 4 Hz 都不到 ✘")
                print(f"\n  -> 实测 {hz:.2f} Hz（单程 {d.get('half_ms')} ms，"
                      f"最慢 {d.get('slow_ms')} ms，丢步 {d.get('lost')}）  {mark}")
            else:
                print("\n  没等到 RATE_DONE —— 可能是板子上还是旧固件（需要 PIANO_GLOVE_2 v2.1.0 以上）。")

        return 0
    finally:
        b.close()


if __name__ == "__main__":
    sys.exit(main())

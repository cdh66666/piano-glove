"""诊断：读板子上真实的校准表，检查「按压行程」和「目标位是否越界」。

用法：
    python host/tests/diag_cal.py [PORT]

为什么需要它：
    「试动作幅度太小」和「测动作撞到不该去的地方卡住」，从界面上都只能看出
    「动了 / 没动」，看不出**动多少才算对**。唯一可靠的办法是把固件里的
    校准表读出来，自己把 pressPos() 算一遍，跟 standby 比：

        pressPos(s, depth) = standby + (目标端 - standby) * depth / 100
        目标端 = (dir == max) ? hi : lo

    这个脚本不驱动任何舵机（只发读命令），跑起来是安全的。

报告里会标出两类危险：
    [越界]  按下目标位不在 [min, max] 区间内 —— 机械上可能顶死。
    [疑似]  舵机当前位置离 standby 太远 —— 这个槽位的校准多半不是这块舵机的。
"""

import re
import sys
import time

dirname_ok = True
try:
    from bench_move import Board, find_board, kv
except ImportError:
    dirname_ok = False


def press_target(sl):
    """复刻固件 glove.cpp 的 pressPos(s, 100) 的目标端。"""
    return sl["max"] if sl["press"] == "max" else sl["min"]


def analyse(port):
    b = Board(port)
    out = []
    try:
        info = b.cmd("INFO")
        for l in info.splitlines():
            if "PIANO_GLOVE" in l:
                out.append("板子: " + l.strip())

        cal = {}
        for l in b.cmd_lines("CAL STATUS", budget=4.0):
            if l.startswith("CAL "):
                cal[int(kv(l)["slot"])] = kv(l)

        st = {}
        for l in b.cmd_lines("STATUS_ALL", budget=8.0):
            if l.startswith("SLOT "):
                st[int(kv(l)["slot"])] = kv(l)
    finally:
        b.close()

    n = len(cal) or len(st)
    if not n:
        return ["拿不到 CAL STATUS / STATUS_ALL —— 检查板子是否插着、端口对不对"]
    if not cal:
        return ["CAL STATUS 一条都没回 —— 校准表可能没存进 NVS，需要重做第 3 步校准"]

    out.append("")
    out.append("槽  指  id  min   standby  max   方向  行程  pos    偏差  valid 判定")
    out.append("-" * 88)

    bad = []
    suspect = []
    span_of = []
    for s in range(n):
        c = cal.get(s) or st.get(s)
        if not c:
            continue
        name = c.get("name", "?")
        sid = int(c.get("id", 0))
        lo = int(c.get("min", 0))
        sb = int(c.get("standby", 0))
        hi = int(c.get("max", 0))
        press = c.get("press", "?")
        valid = int(c.get("valid", 0))

        sl = {"min": lo, "standby": sb, "max": hi, "press": press}
        tgt = press_target(sl)
        span = abs(tgt - sb)                 # 按下一次的真实行程（计数）
        full = abs(hi - lo)                  # 校准的完整量程
        span_of.append(span)

        p = st.get(s, {}).get("pos")
        pos = int(p) if p is not None else None
        dev = abs(pos - sb) if pos is not None else None

        flags = []
        # 目标端必须在校准区间内
        lo_b, hi_b = min(lo, hi), max(lo, hi)
        if not (lo_b <= tgt <= hi_b):
            flags.append("越界")
            bad.append(s)
        # standby 也必须在区间内，否则插值基准就错了
        if not (lo_b <= sb <= hi_b):
            flags.append("standby越界")
        if span < 100:
            flags.append("行程过小")
            bad.append(s)
        if valid == 0:
            flags.append("未校准")
            bad.append(s)
        if dev is not None and dev > 600:
            flags.append("疑似换过舵机")
            suspect.append(s)

        out.append(
            "%d   %-4s %-3d %-5d %-8d %-5d %-5s %-4d %-6s %-5s %d     %s"
            % (s, name[:4], sid, lo, sb, hi, press, span,
               "-" if pos is None else str(pos),
               "-" if dev is None else str(dev),
               valid,
               " ".join(flags) or "OK")
        )

    out.append("")
    both = [abs(int((cal[s].get("max", 0))) - int(cal[s].get("min", 0))) for s in cal]
    if both:
        out.append("完整量程 min->max: " + " ".join(str(v) for v in both) + " 计数")
    out.append("按压行程 standby->按下端: " + " ".join(str(v) for v in span_of) + " 计数")
    if span_of:
        out.append("  最小 %d / 最大 %d —— 如果这两个数差很多，说明有的槽位校准没做全"
                   % (min(span_of), max(span_of)))

    out.append("")
    if bad:
        out.append("!! 危险槽位 %s：按下目标位越界或行程过小，先别驱动它们。"
                   % ",".join(str(x + 1) for x in sorted(set(bad))))
    else:
        out.append("所有槽位的按下目标位都在校准区间内，SPAN OK。")

    if suspect:
        out.append("!! 疑似换过舵机（当前位置离 standby > 600 计数）: 槽 %s"
                   % ",".join(str(x + 1) for x in sorted(set(suspect))))
        out.append("   这多半是校准按槽位存、但映射改过 —— 需要重做这些槽位的第 3 步校准。")

    # 顺便把「硬编码 MOVE 目标」的危险量化出来
    out.append("")
    out.append("对比：界面「测动作往返」硬编码的是 MOVE <id> 200 —— 位置 200。")
    for s in range(n):
        c = cal.get(s)
        if not c:
            continue
        lo_b = min(int(c.get("min", 0)), int(c.get("max", 0)))
        hi_b = max(int(c.get("min", 0)), int(c.get("max", 0)))
        if not (lo_b <= 200 <= hi_b):
            out.append("   槽 %d (id=%s) 校准区间 [%d,%d]，200 在区间外 —— 会顶死。"
                       % (s + 1, c.get("id"), lo_b, hi_b))

    return out


def main():
    if not dirname_ok:
        print("需要和 bench_move.py 放在同一目录（复用它的 Board 类）")
        return 1
    port = sys.argv[1] if len(sys.argv) > 1 else None
    if not port:
        port = find_board()
    if not port:
        print("没找到板子。检查 USB 和串口占用。")
        return 1
    print("端口: " + port)
    print("\n".join(analyse(port)))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())

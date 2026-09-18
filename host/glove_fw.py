# -*- coding: utf-8 -*-
"""
PIANO_GLOVE 固件调试工具（微雪 Servo Driver with ESP32 主控板）
=============================================================
板子跑的固件自带一套文本命令协议（115200, USB-UART，自动识别端口）, 本工具把它封装成
命令行 + 一键校准向导。

固件命令表(HELP 输出):
  INFO PROFILE AUTO ENROLL SCAN PING STATUS STATUS_ALL MAP SETDIR SETID CAL
  TORQUE ARM DISARM SAFE STANDBY PRESS RELEASE MOVE DEMO

已探明的语法:
  INFO                                 查看固件/串口/校准/armed 状态
  PROFILE SC09|STS3032                 舵机系列档位 (STS3032 = 你的舵机)
  SCAN                                 扫描总线上的舵机 ID
  PING <id>                            单个探测
  AUTO                                 自动识别型号/档位 (自带诊断建议)
  STATUS <id> / STATUS_ALL             状态; STATUS_ALL 列出 6 个槽位
  MAP <slot> <id>                      槽位 -> 舵机 ID
  SETDIR <slot> max|min                该槽"按下"对应位置大端还是小端
  SETID <old> <new> CONFIRM            改舵机 ID (要一次只接一个舵机!)
  CAL STATUS                           查看校准表
  CAL CLEAR                            清空校准数据
  CAL CAPTURE <slot> <MIN> <STANDBY> <MAX>   手动写入校准值(会先读一次舵机验证)
  CAL AUTO START|STATUS|FINISH|CANCEL  自动采样: 你活动手指, 固件记录 min/max
  CAL SAVE                             保存(需要 6 个槽位都有效)
  TORQUE <slot|id> 0|1                 扭矩开关
  ARM / DISARM / SAFE / STANDBY CONFIRM 使能/失能/急停/待机
  PRESS <slot> / RELEASE <slot>        按下/松开某个手指(需先 ARM)
  MOVE <id> <position> <speed> <acc> ARM
  DEMO                                 播放内置曲目(需先 ARM 且校准完成)

槽位(默认): 0=拇指侧向(id1) 1=拇指按键(id2) 2=食指(id3) 3=中指(id4)
            4=无名指(id5) 5=小指(id6)

用法示例:
  python glove_fw.py info
  python glove_fw.py auto
  python glove_fw.py cal status
  python glove_fw.py cal wizard 20         # 一键校准向导(20 秒活动时间)
  python glove_fw.py cal auto status       # 实时看采样
  python glove_fw.py assign                # 引导逐个把舵机 ID 改成 1~6
  python glove_fw.py raw "CAL STATUS"      # 发任意命令
  python glove_fw.py monitor               # 轮询状态, 实时看反馈
"""

import argparse
import re
import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("需要 pyserial:  pip install pyserial")
    sys.exit(1)

# 串口号会随 USB 枚举顺序变化（插拔、换 USB 口都会变），所以默认自动识别：
# 挨个串口发 INFO，谁回 OK INFO 谁就是手套主板。
DEFAULT_PORT = "auto"
DEFAULT_BAUD = 115200


def _query_info(ser, wait=1.2):
    """向已打开的串口发一条 INFO，返回回复内容（没回复就返回 b""）"""
    ser.reset_input_buffer()
    ser.write(b"INFO\r\n")
    t0, buf = time.time(), b""
    while time.time() - t0 < wait:
        d = ser.read(4096)
        if d:
            buf += d
        elif buf:
            break
    return buf


def autodetect_port(baud=DEFAULT_BAUD, rounds=3):
    """扫所有串口找手套主板。只发 INFO，不会动舵机。

    为什么要扫多轮：**打开/关闭串口本身会给板子一个复位脉冲**（CP2102 自动复位电路），
    刚被复位过的板子要 1~2 秒才起来，那一刻发 INFO 是没反应的。所以每轮之间要留间隔重试。
    """
    ports = [p.device for p in serial.tools.list_ports.comports()]
    unreachable = []
    for rnd in range(rounds):
        for dev in ports:
            try:
                s = serial.Serial(dev, baud, timeout=0.2)
            except Exception:
                if rnd == rounds - 1 and dev not in unreachable:
                    unreachable.append(dev)
                continue
            try:
                time.sleep(0.5)
                if b"OK INFO" in _query_info(s):
                    return dev
            except Exception:
                pass
            finally:
                try:
                    s.close()
                except Exception:
                    pass
            time.sleep(0.25)
        if rnd < rounds - 1:
            time.sleep(0.9)
    raise RuntimeError(
        "没找到手套主板（挨个串口发 INFO 都没回 OK INFO）。扫过：" + ", ".join(ports) +
        ("；打不开的：" + ", ".join(unreachable) if unreachable else "") +
        "\n  · 打不开通常是被别的程序占着 —— 先关掉浏览器调试台 / 串口监视器\n"
        "  · 也可以 --port COMx 手动指定，或跑 probe_ports.py 看哪个端口有反应"
    )

SLOT_NAMES = ["拇指侧向", "拇指按键", "食指", "中指", "无名指", "小指"]
SLOT_IDS = [1, 2, 3, 4, 5, 6]


def _kv(line):
    """把 'a=1 b=2' 解析成 dict"""
    out = {}
    for m in re.finditer(r"(\w+)=([^\s]+)", line):
        out[m.group(1)] = m.group(2)
    return out


class PianoGlove:
    def __init__(self, port=DEFAULT_PORT, baud=DEFAULT_BAUD):
        self.port_name, self.baud = port, baud
        self.ser = None

    def open(self, tries=4):
        if self.port_name in (None, "", "auto"):
            self.port_name = autodetect_port(self.baud)
            print(f"[自动识别] 手套主板在 {self.port_name}")
        # 打开串口时 DTR/RTS 的跳变会给板子一个复位脉冲（CP2102 自动复位电路），
        # 紧接着发的第一条命令必然丢。所以这里先发一条 INFO "叫醒" 它，收到回复才算打开成功。
        err = None
        for _ in range(tries):
            try:
                self.ser = serial.Serial(self.port_name, self.baud, timeout=0.2)
                time.sleep(0.45)
                self.ser.reset_input_buffer()
                self.ser.write(b"INFO\r\n")
                t0, buf = time.time(), b""
                while time.time() - t0 < 2.0:
                    d = self.ser.read(4096)
                    if d:
                        buf += d
                    elif buf:
                        break
                if b"OK INFO" in buf:
                    self.ser.reset_input_buffer()
                    return self
                try:
                    self.ser.close()
                except Exception:
                    pass
                time.sleep(0.5)
            except Exception as e:
                err = e
                time.sleep(0.5)
        raise RuntimeError(
            f"打开了 {self.port_name} 但板子不回应 INFO"
            + (f"（{err}）" if err else "")
            + "\n  · 端口被别的程序占着？先关掉浏览器调试台 / 串口监视器\n"
            "  · 或者拔插一次 USB"
        )

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass

    def __enter__(self):
        return self.open()

    def __exit__(self, *a):
        self.close()

    # ---------------- 底层收发 ----------------
    def send(self, cmd, wait=6.0, quiet=0.6):
        """发一条命令, 收齐回复(读到安静 quiet 秒或超时 wait 秒)"""
        if not self.ser:
            raise RuntimeError("串口未打开")
        self.ser.reset_input_buffer()
        t0 = time.time()
        self.ser.write((cmd + "\r\n").encode())
        buf, last = b"", t0
        while time.time() - t0 < wait:
            d = self.ser.read(4096)
            if d:
                buf += d
                last = time.time()
            elif time.time() - last > quiet:
                break
        txt = buf.decode("utf-8", "replace").replace("\r\n", "\n").strip()
        return txt

    def lines(self, cmd, **kw):
        t = self.send(cmd, **kw)
        return [l for l in t.split("\n") if l.strip()]

    # ---------------- 查询 ----------------
    def info(self):
        for l in self.lines("INFO", wait=3):
            if l.startswith("OK INFO"):
                return _kv(l)
        return {}

    def scan(self, wait=25):
        ids = []
        for l in self.lines("SCAN", wait=wait, quiet=3.0):
            m = re.match(r"FOUND id=(\d+)", l)
            if m:
                ids.append(int(m.group(1)))
        return ids

    def ping(self, sid):
        for l in self.lines("PING %d" % sid, wait=2, quiet=0.5):
            if l.startswith("OK PING"):
                return True
        return False

    def status_all(self, wait=10):
        """返回 {slot: {...}}"""
        slots = {}
        for l in self.lines("STATUS_ALL", wait=wait, quiet=2.0):
            if l.startswith("SLOT"):
                d = _kv(l)
                slots[int(d.get("slot", -1))] = d
        return slots

    def cal_status(self, wait=4):
        slots = {}
        complete = None
        for l in self.lines("CAL STATUS", wait=wait):
            if l.startswith("CAL slot"):
                d = _kv(l)
                slots[int(d.get("slot", -1))] = d
            elif l.startswith("OK CAL"):
                complete = _kv(l).get("complete")
        return slots, complete

    # ---------------- 配置 ----------------
    def profile(self, name):
        return self.send("PROFILE " + name, wait=4)

    def map_slot(self, slot, sid):
        return self.send("MAP %d %d" % (slot, sid), wait=3)

    def setdir(self, slot, direction):
        return self.send("SETDIR %d %s" % (slot, direction), wait=3)

    def setid(self, old, new):
        return self.send("SETID %d %d CONFIRM" % (old, new), wait=5)

    # ---------------- 校准 ----------------
    def cal_clear(self):
        return self.send("CAL CLEAR", wait=5, quiet=1.0)

    def cal_auto(self, sub):
        return self.lines("CAL AUTO " + sub, wait=4)

    def cal_auto_snapshot(self):
        """返回 {slot: {samples,min,max,last}}"""
        out = {}
        for l in self.cal_auto("STATUS"):
            if l.startswith("CAL_AUTO"):
                d = _kv(l)
                out[int(d.get("slot", -1))] = d
        return out

    def cal_capture(self, slot, mn, st, mx):
        return self.send("CAL CAPTURE %d %d %d %d" % (slot, mn, st, mx), wait=5)

    def cal_save(self):
        return self.send("CAL SAVE", wait=5)

    # ---------------- 动作 ----------------
    def torque(self, target, on):
        return self.send("TORQUE %s %d" % (target, 1 if on else 0), wait=3)

    def arm(self):
        return self.send("ARM", wait=3)

    def disarm(self):
        return self.send("DISARM", wait=3)

    def safe(self):
        return self.send("SAFE", wait=3)

    def standby(self):
        return self.send("STANDBY CONFIRM", wait=3)

    def press(self, slot):
        return self.send("PRESS %d" % slot, wait=3)

    def release(self, slot):
        return self.send("RELEASE %d" % slot, wait=3)

    def move(self, sid, pos, speed, acc):
        return self.send("MOVE %d %d %d %d ARM" % (sid, pos, speed, acc), wait=3)

    def demo(self):
        return self.send("DEMO", wait=3)

    def enroll(self, sub):
        return self.send("ENROLL " + sub, wait=6)


# ======================= 命令行 =======================
def _print_slots(slots):
    print("槽位  手指       舵机ID  在线  最小  中位  最大  有效  按压方向")
    for s in range(6):
        d = slots.get(s)
        if not d:
            print("  %-4d %-10s  --" % (s, SLOT_NAMES[s]))
            continue
        print("  %-4d %-10s %-6s %-5s %-5s %-5s %-5s %-5s %-6s" % (
            s, d.get("name", SLOT_NAMES[s]), d.get("id", "?"), d.get("online", "?"),
            d.get("min", "?"), d.get("standby", "?"), d.get("max", "?"),
            d.get("valid", "?"), d.get("press", "?")))


def cmd_info(g):
    info = g.info()
    if not info:
        print("没有收到 INFO 回复")
        return
    print("固件版本 : %s" % info.get("fw"))
    print("舵机档位 : %s  (量程 %s)" % (info.get("profile"), info.get("range")))
    print("热点/地址: %s / %s" % (info.get("ap"), info.get("ip")))
    print("已校准   : %s   已使能: %s   自动采样: %s" % (
        info.get("calibrated"), info.get("armed"), info.get("auto_active")))
    print("ENROLL   : active=%s next=%s phase=%s" % (
        info.get("enroll_active"), info.get("enroll_next"), info.get("enroll_phase")))


def cmd_wizard(g, seconds):
    """一键校准向导: 清空 -> 开始自动采样 -> 提示活动手指 -> 结束 -> 保存"""
    info = g.info()
    if info.get("profile") != "STS3032":
        print("当前档位是 %s, 你的舵机是 STS3032, 先切换..." % info.get("profile"))
        print("  " + g.profile("STS3032"))
    print("先做一次总线自检...")
    ids = g.scan()
    print("  扫描到舵机: %s" % (ids if ids else "无 ← 先解决接线/供电/ID 问题再来校准"))
    slots = g.status_all()
    _print_slots(slots)
    offline = [s for s in range(6) if str(slots.get(s, {}).get("online", "0")) != "1"]
    if offline:
        print("\n⚠ 槽位 %s 的舵机不在线, 固件会拒绝校准。" % offline)
        print("  建议先运行:  python glove_fw.py assign   (逐个把舵机 ID 设成 1~6)")
        if input("仍要继续? [y/N] ").strip().lower() != "y":
            return

    print("\n[1/4] 清空旧校准数据 ...  %s" % g.cal_clear())
    print("[2/4] 开始自动采样: %s" % " ".join(g.cal_auto("START")))
    print("[3/4] 请在 %d 秒内反复做这些动作:" % seconds)
    print("      · 拇指: 直直往下按到底 ↔ 完全松开")
    print("      · 拇指: 向侧方压到底  ↔ 完全松开")
    print("      · 其余四指: 伸直 ↔ 用力握到底")
    t0 = time.time()
    while time.time() - t0 < seconds:
        snap = g.cal_auto_snapshot()
        left = seconds - (time.time() - t0)
        print("  [剩 %4.1fs]  " % left + "  ".join(
            "s%d:%s(%s~%s)" % (k, v.get("samples"), v.get("min"), v.get("max"))
            for k, v in sorted(snap.items())), end="\r")
        time.sleep(0.5)
    print()
    print("[4/4] 结束采样: %s" % " ".join(g.cal_auto("FINISH")))
    slots, _ = g.cal_status()
    _print_slots(slots)
    print("保存校准: %s" % g.cal_save())


def cmd_assign(g):
    """引导逐个把舵机 ID 设成 1~6 (总线 ID 冲突时的修复流程)"""
    print("这个方法可以修好「多个舵机 ID 撞车 / 扫不到」的问题。")
    print("做法: 每次只把 1 个舵机接到板子上, 单独改它的 ID, 改完贴上标签再换下一个。\n")
    info = g.info()
    if info.get("profile") != "STS3032":
        print("先切档位: %s" % g.profile("STS3032"))
    for i, sid in enumerate(SLOT_IDS, start=1):
        input(">> 现在只接【第 %d 个】舵机(要设成 ID %d), 接好后按回车..." % (i, sid))
        ids = g.scan(wait=12)
        print("   扫描到: %s" % (ids if ids else "无"))
        cur = ids[0] if ids else 1
        if cur == sid:
            print("   已经是 ID %d, 跳过改号" % sid)
        else:
            print("   把 ID %d 改成 %d: %s" % (cur, sid, g.setid(cur, sid)))
        print("   复核: %s" % ("PING OK" if g.ping(sid) else "还是没反应, 检查接线/供电"))
    print("\n全部设完, 把 6 个舵机按顺序串回总线, 再跑:  python glove_fw.py auto")


def cmd_monitor(g, interval):
    print("轮询中 (Ctrl+C 退出)")
    try:
        while True:
            snap = g.cal_auto_snapshot()
            line = "  ".join("%s:%s/%.0f%%" % (
                SLOT_NAMES[k][:3], v.get("last"),
                (int(v.get("max", 0)) / max(1, int(g.info().get("range") or 4095)) * 100)
            ) for k, v in sorted(snap.items())) if snap else ""
            print("\r" + line[:150], end="")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已停止")


def main():
    ap = argparse.ArgumentParser(description="PIANO_GLOVE 固件调试工具")
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("info", help="固件信息")
    sub.add_parser("scan", help="扫描舵机 ID")
    sub.add_parser("auto", help="固件自动识别(含诊断建议)")
    sub.add_parser("status", help="STATUS_ALL 槽位表")
    sub.add_parser("assign", help="引导逐个设置舵机 ID 1~6")

    p = sub.add_parser("profile", help="设置舵机档位")
    p.add_argument("name", choices=["SC09", "STS3032"])

    p = sub.add_parser("ping", help="探测单个舵机")
    p.add_argument("sid", type=int)

    p = sub.add_parser("torque", help="扭矩开关")
    p.add_argument("target")
    p.add_argument("on", type=int, choices=[0, 1])

    p = sub.add_parser("setdir", help="设置某槽按压方向")
    p.add_argument("slot", type=int)
    p.add_argument("direction", choices=["max", "min"])

    p = sub.add_parser("map", help="槽位->舵机ID")
    p.add_argument("slot", type=int)
    p.add_argument("sid", type=int)

    p = sub.add_parser("setid", help="改舵机 ID")
    p.add_argument("old", type=int)
    p.add_argument("new", type=int)

    c = sub.add_parser("cal", help="校准")
    c.add_argument("action", choices=["status", "clear", "start", "watch", "finish", "save", "wizard"])
    c.add_argument("seconds", nargs="?", type=int, default=20)

    sub.add_parser("arm", help="使能动作")
    sub.add_parser("disarm", help="失能")
    sub.add_parser("safe", help="急停(关扭矩)")
    sub.add_parser("standby", help="待机")
    sub.add_parser("demo", help="播放内置曲目")
    sub.add_parser("enroll-status", help="查看 ENROLL 状态")

    p = sub.add_parser("press", help="按下某手指")
    p.add_argument("slot", type=int)
    p = sub.add_parser("release", help="松开某手指")
    p.add_argument("slot", type=int)

    p = sub.add_parser("move", help="直接写位置")
    p.add_argument("sid", type=int)
    p.add_argument("pos", type=int)
    p.add_argument("speed", type=int, nargs="?", default=500)
    p.add_argument("acc", type=int, nargs="?", default=20)

    p = sub.add_parser("raw", help="发送任意命令")
    p.add_argument("text")

    p = sub.add_parser("monitor", help="轮询状态")
    p.add_argument("--interval", type=float, default=0.5)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return

    with PianoGlove(args.port, args.baud) as g:
        if args.cmd == "info":
            cmd_info(g)
        elif args.cmd == "scan":
            ids = g.scan()
            print("扫描到 %d 个舵机: %s" % (len(ids), ids if ids else "无"))
        elif args.cmd == "auto":
            print(g.send("AUTO", wait=90, quiet=5))
        elif args.cmd == "status":
            _print_slots(g.status_all())
        elif args.cmd == "assign":
            cmd_assign(g)
        elif args.cmd == "profile":
            print(g.profile(args.name))
        elif args.cmd == "ping":
            print("ID %d %s" % (args.sid, "在线" if g.ping(args.sid) else "无响应"))
        elif args.cmd == "torque":
            print(g.torque(args.target, bool(args.on)))
        elif args.cmd == "setdir":
            print(g.setdir(args.slot, args.direction))
        elif args.cmd == "map":
            print(g.map_slot(args.slot, args.sid))
        elif args.cmd == "setid":
            print(g.setid(args.old, args.new))
        elif args.cmd == "cal":
            if args.action == "wizard":
                cmd_wizard(g, args.seconds)
            elif args.action == "status":
                slots, complete = g.cal_status()
                _print_slots(slots)
                print("complete=%s" % complete)
            elif args.action == "clear":
                print(g.cal_clear())
            elif args.action == "start":
                print(" ".join(g.cal_auto("START")))
            elif args.action == "watch":
                print(g.send("CAL AUTO STATUS", wait=4))
            elif args.action == "finish":
                print(" ".join(g.cal_auto("FINISH")))
            elif args.action == "save":
                print(g.cal_save())
        elif args.cmd == "arm":
            print(g.arm())
        elif args.cmd == "disarm":
            print(g.disarm())
        elif args.cmd == "safe":
            print(g.safe())
        elif args.cmd == "standby":
            print(g.standby())
        elif args.cmd == "demo":
            print(g.demo())
        elif args.cmd == "enroll-status":
            print(g.enroll("STATUS"))
        elif args.cmd == "press":
            print(g.press(args.slot))
        elif args.cmd == "release":
            print(g.release(args.slot))
        elif args.cmd == "move":
            print(g.move(args.sid, args.pos, args.speed, args.acc))
        elif args.cmd == "raw":
            print(g.send(args.text))
        elif args.cmd == "monitor":
            cmd_monitor(g, args.interval)


if __name__ == "__main__":
    main()

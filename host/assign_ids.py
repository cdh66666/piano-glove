# -*- coding: utf-8 -*-
"""
舵机 ID 自动编号向导（PIANO_GLOVE 固件）
=======================================
用途: 修复「多个舵机 ID 撞车 → 总线上互相抢答 → 扫不到 / 读失败」的问题。

用法:
  1. 先拔掉所有舵机
  2. 运行本脚本
  3. 按屏幕提示「插一个 → 等一下 → 拔掉 → 插下一个」, 全程不用敲键盘

原理: 全程保证总线上只有一个舵机, 脚本扫描到它 -> 用 SETID 改成目标 ID -> 复核 -> 提示换下一个。
"""
import re
import sys
import time

import serial
import serial.tools.list_ports

PORT = "auto"   # 串口号会变；改为自动识别（发 INFO 看谁回 OK INFO）
BAUD = 115200
MAX_ID = 10                      # 扫描范围
TARGETS = [1, 2, 3, 4, 5, 6]
LABELS = ["拇指侧压(slot0)", "拇指下压(slot1)", "食指", "中指", "无名指", "小指"]
TRACE = {}                       # 记录: 出现过但未编号的 ID


LOGFILE = "assign_log.txt"


def _autodetect():
    """扫所有串口, 谁回 OK INFO 谁就是手套主板（只发 INFO, 不会动舵机）"""
    tried = []
    for p in serial.tools.list_ports.comports():
        try:
            s = serial.Serial(p.device, BAUD, timeout=0.2)
        except Exception as e:
            tried.append(f"{p.device}(打不开)")
            continue
        try:
            time.sleep(0.2)
            s.reset_input_buffer()
            s.write(b"INFO\r\n")
            time.sleep(0.6)
            if b"OK INFO" in s.read(4096):
                return p.device
            tried.append(p.device)
        except Exception:
            tried.append(p.device)
        finally:
            s.close()
    raise RuntimeError(
        "没找到手套主板（挨个串口发 INFO 都没回 OK INFO）。已试过：" + ", ".join(tried) +
        "\n  · 改 PORT 手动指定，例如 PORT = \"COM3\"\n"
        "  · 或跑 probe_ports.py 看哪个端口有反应"
    )


LOGFILE = "assign_log.txt"


def log(*a):
    print(*a, flush=True)
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(" ".join(str(x) for x in a) + "\n")
    except Exception:
        pass


def ping_wait(bus, sid, timeout=6.0):
    """改完 ID 后舵机可能要重启示号, 轮询等待它以新 ID 应答"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if bus.ping(sid):
            return True
        time.sleep(0.4)
    return False


def try_setid(bus, cur, target):
    """改 ID, 带重试; 处理「实际已写成功但回读失败」和「new_id_occupied 其实已成功」"""
    for k in range(3):
        r = bus.setid(cur, target)
        log("    尝试 %d: 改 ID %d -> %d : %s" % (k + 1, cur, target, r))
        if "OK SETID" in r:
            if ping_wait(bus, target):
                return True
            log("    (写成功但新 ID 暂时没应答, 等它重启后再确认…)")
        if "new_id_occupied" in r and ping_wait(bus, target):
            log("    (固件说新 ID 已被占用, 但能 ping 通 → 视为已成功)")
            return True
        # 再全面确认一次: 万一已经写成功了
        if ping_wait(bus, target, 2.0):
            return True
        time.sleep(0.8)
    return False


class Bus:
    def __init__(self):
        self.open()

    def open(self):
        global PORT
        if PORT in (None, "", "auto"):
            PORT = _autodetect()
            log(f"    自动识别到手套主板: {PORT}")
        # 打开串口时 DTR/RTS 跳变会给板子一个复位脉冲，紧接着发的第一条命令必丢。
        # 所以先发一条 INFO "叫醒" 它，收到回复才算真的通了。
        self.s = serial.Serial(PORT, BAUD, timeout=0.2)
        for _ in range(4):
            time.sleep(0.45)
            self.s.reset_input_buffer()
            self.s.write(b"INFO\r\n")
            t0, buf = time.time(), b""
            while time.time() - t0 < 2.0:
                d = self.s.read(4096)
                if d:
                    buf += d
                elif buf:
                    break
            if b"OK INFO" in buf:
                self.s.reset_input_buffer()
                return
            time.sleep(0.5)
        raise RuntimeError(f"{PORT} 打开了但板子不回应 INFO —— 端口被别的程序占着？或拔插一次 USB")

    def reopen(self):
        """USB 重新枚举/端口失效后自动恢复"""
        try:
            self.s.close()
        except Exception:
            pass
        t0 = time.time()
        while time.time() - t0 < 180:
            try:
                self.open()
                log("    串口已恢复")
                return True
            except Exception:
                log("    串口打不开 (设备可能被拔了?), 2 秒后重试… 检查 USB 线")
                time.sleep(2)
        return False

    def send(self, cmd, wait=6.0, quiet=1.0):
        for attempt in (1, 2):
            try:
                return self._send_once(cmd, wait, quiet)
            except serial.SerialException as e:
                log("    ⚠ 串口异常: %s — 尝试恢复…" % e.__class__.__name__)
                if attempt == 2 or not self.reopen():
                    raise
                # 恢复后重发

    def _send_once(self, cmd, wait=6.0, quiet=1.0):
        self.s.reset_input_buffer()
        t0 = time.time()
        self.s.write((cmd + "\r\n").encode())
        buf, last = b"", t0
        while time.time() - t0 < wait:
            d = self.s.read(4096)
            if d:
                buf += d
                last = time.time()
            elif time.time() - last > quiet:
                break
        return buf.decode("utf-8", "replace")

    def profile(self):
        m = re.search(r"profile=(\w+)", self.send("INFO", 3, 0.6))
        return m.group(1) if m else "?"

    def scan(self):
        """固件自带的 SCAN 约 1/3 概率漏报, 所以这里用逐个 PING 探测 (可靠)"""
        return [sid for sid in range(1, MAX_ID + 1) if self.ping(sid)]

    def setid(self, old, new):
        return self.send("SETID %d %d CONFIRM" % (old, new), 10, 1.0).strip()

    def ping(self, sid):
        return self.send("PING %d" % sid, 2, 0.4).startswith("OK PING")

    def status(self, sid):
        return self.send("STATUS %d" % sid, 2, 0.4).strip()

    def close(self):
        self.s.close()


def probe_ids(bus, ids):
    return [sid for sid in ids if bus.ping(sid)]


def wait_one(bus, timeout=1800, what=""):
    """等总线上出现且稳定为 1 个舵机, 返回它的 ID。
    快路径: 大多数舵机出厂/上次遗留的 ID 就是 1, 先探它。"""
    t0 = time.time()
    last = None
    last_beat = 0.0
    while time.time() - t0 < timeout:
        ids = probe_ids(bus, [1])
        if not ids:
            ids = probe_ids(bus, range(2, 9))
        if len(ids) == 1 and ids == last:
            return ids[0]
        if len(ids) > 1:
            log("   ⚠ 总线上现在有 %d 个舵机 %s —— 请拔掉多余的, 只留一个" % (len(ids), ids))
        last = ids if len(ids) == 1 else None
        if time.time() - last_beat > 15:
            last_beat = time.time()
            log("    …等待中 (%d 秒): 请接入【%s】, 只插这一个" % (int(time.time() - t0), what or "下一个舵机"))
        time.sleep(0.3)
    return None


def wait_really_empty(bus, need=2, timeout=1800):
    """等总线真正空: 连续 need 次全量探测(1~MAX_ID)都找不到舵机才算拔干净。
    之前只盯单个 ID 连续 miss 两次, 接触不良的舵机会误判成「已拔下」。"""
    t0 = time.time()
    empty = 0
    last_msg = None
    while time.time() - t0 < timeout:
        ids = bus.scan()
        empty = empty + 1 if not ids else 0
        if empty >= need:
            return True
        if ids and ids != last_msg:
            last_msg = ids
            hint = ("如果这是本轮要编号的新舵机: 请把它【拔下再插回】一次以确认; "
                    "如果是上一轮已贴标签的: 请拔下换下一个") if ids == [1] else "请拔掉多余的, 只留一个"
            log("    总线上有 %s —— %s" % (ids, hint))
        elif not ids:
            last_msg = None
        time.sleep(0.5)
    return False


def main():
    start = 1
    if "--from" in sys.argv:
        start = int(sys.argv[sys.argv.index("--from") + 1])
    log("\n" + "=" * 62)
    log(" 舵机 ID 自动编号向导  (从第 %d 轮继续)" % start)
    log("=" * 62)
    bus = Bus()
    prof = bus.profile()
    log("当前档位: %s %s" % (prof, "(正确)" if prof == "STS3032" else ""))
    if prof != "STS3032":
        log(bus.send("PROFILE STS3032", 4, 0.8).strip())

    if start == 1:
        log("\n先确认总线上没有舵机 ...")
        if probe_ids(bus, [1]) or probe_ids(bus, range(2, 9)):
            log("检测到还有舵机接着, 请先全部拔掉 —— 我在等你拔 (全程不用敲键盘)")
            while probe_ids(bus, [1]) or probe_ids(bus, range(2, 9)):
                time.sleep(0.5)
            log("OK, 已经全部拔下了。")

    log("\n每轮: ① 按提示把【一个】舵机插到板子上  ② 等 ✔ 已编号  ③ 拔下贴标签, 插下一个")
    log("(插的顺序 = 下面列表的顺序, 插错顺序也能用, 后面可以改映射)\n")

    done = []
    assigned = set(range(1, start))          # 之前轮次已编号的 ID
    rounds = list(zip(TARGETS, LABELS))[start - 1:]
    for i, (target, label) in enumerate(rounds, start=start):
        log("-" * 62)
        log(">>> 第 %d 轮: 请接入【%s】这个舵机 (只插这一个)" % (i, label))
        if start > 1 or i > 1:
            wait_really_empty(bus)           # 先确认上一轮的舵机真的拔了
        # 出厂舵机都是 ID 1, 这里不做「已编号」拦截 —— 上一轮是否拔干净
        # 由 wait_really_empty 严格保证; 若上一轮还插着, 探测会看到两个 ID 并提示。
        cur = wait_one(bus, what=label)
        log("    检测到舵机, 当前 ID = %d" % cur)
        if cur == target:
            log("    它已经是 ID %d, 不用改" % target)
        else:
            if not try_setid(bus, cur, target):
                log("    ✘ 改号失败(重试 3 次都不行)。")
                log("      这个舵机/线可能接触不良: 换个插法、换根线再试; 也可以先跳过它。")
                log("      保持它插着没关系, 我会继续等它稳定…")
                # 不退出: 继续等这个舵机稳定后重试
                ok = False
                for k in range(6):
                    time.sleep(5)
                    if probe_ids(bus, [cur]) and try_setid(bus, cur, target):
                        ok = True
                        break
                if not ok:
                    log("    ✘ 放弃这个舵机, 请手动处理。脚本退出。")
                    bus.close()
                    return
        log("    ✔ 已编号为 ID %d (%s)" % (target, label))
        log("    反馈: %s" % bus.status(target))
        done.append((target, label))
        assigned.add(target)
        log(">>> 请把这个舵机【拔下来】, 贴标签 %d, 然后接下一个" % target)
        wait_really_empty(bus)

    log("\n" + "=" * 62)
    if len(done) == len(rounds):
        log("全部完成! 编号结果:")
        for t, l in done:
            log("   ID %d  ->  %s" % (t, l))
        log("\n下一步: 把 6 个舵机按 1~6 顺序串回总线, 然后告诉我, 我来跑整体自检和校准。")
    else:
        log("本轮完成了 %d 个: %s" % (len(done), done))
    log("=" * 62)
    bus.close()


if __name__ == "__main__":
    main()

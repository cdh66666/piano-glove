#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""钢琴手套 · 本地串口桥（bridge）

为什么要有这么个东西
--------------------
调试台是个网页。网页想开串口只有一条路：Web Serial API。而这个 API：

  · 只有电脑版 Chrome / Edge 才有；
  · 要求安全上下文 —— 直接双击 .html 用 file:// 打开就是没有；
  · 侧边栏浏览器、内嵌 WebView、微信/豆包内置浏览器**一律没有**。

于是「点连接永远没反应」根本不是驱动问题，是那个浏览器压根没这个 API。

桥把串口搬到 Python 进程里：网页只跟 http://127.0.0.1:8123 说 HTTP，
由 Python 用 pyserial 去开真实串口。这样**任何能打开网页的东西**都能用，
而且不用选口 —— 桥自己扫描、按芯片型号打分、逐个发 INFO 试探，
谁回 OK INFO 就连谁；板子拔了再插也会自己连回来。

顺带还解决了两件事：
  1. 网页不用再弹「选择串口」对话框（Web Serial 每次都要弹，很烦）；
  2. 静态页和 API 同源，不用配 CORS。

用法
----
    python bridge.py                              # 起在 127.0.0.1:8123，自动找板子
    python bridge.py --port 8123
    python bridge.py --url COM4                   # 指定死某个口
    python bridge.py --url socket://127.0.0.1:9701   # 自测用（pyserial 的 URL 语法）
    python bridge.py --no-auto                    # 只提供 API，不自动连

HTTP API（页面同源直接 fetch，不需要 CORS 头）
    GET  /api/status                    桥/串口状态 + 端口清单 + 推荐理由
    POST /api/scan                      重新扫一遍串口，返回打分后的清单
    POST /api/connect   {port?, baud?}  不传 port 就自动挑推荐口
    POST /api/disconnect
    POST /api/send      {cmd, timeoutMs?, quietMs?, since?}
                        -> {pre, lines, first, ms, seq}
                        pre = 灌进来到命令发出前的杂线（比如 RATE_DONE 这类异步输出）
    POST /api/fire      {cmd}           只发不等（整曲演奏时用，不能被固件延迟卡住）
    GET  /api/lines?since=N&wait=S      长轮询拿异步输出行

安全
----
只 bind 127.0.0.1，并且校验 Origin：浏览器之外的页面（别的网站）发过来的
跨站请求一律 403。这不是防黑客，是防「随手打开的某个网页偷偷驱动你的手套」。
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import traceback
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

try:
    import serial
    import serial.tools.list_ports as list_ports
except ImportError:
    sys.stderr.write(
        "\n[!] 缺少 pyserial。装一下就好：\n"
        "    python -m pip install pyserial\n\n")
    raise

# ============================================================
# 推荐串口：按芯片打分
# ============================================================
# 微雪那块 ESP32 主控板板载的是 CP2102（Silicon Labs），所以它分最高。
# 但用户手上也常有 CH340 的杂牌板 / ESP32-S3 原生 USB，都给够高的分。
VENDOR_HINTS = [
    ("10C4", 100, "Silicon Labs CP210x —— 微雪 ESP32 主板板载的 USB 转串口"),
    ("1A86", 92, "沁恒 CH340 / CH9102 USB 转串口"),
    ("303A", 88, "乐鑫 ESP32-S3 原生 USB（芯片直出）"),
    ("0403", 84, "FTDI USB 转串口"),
    ("1A0C", 60, "其它乐鑫开发板"),
    ("2341", 55, "Arduino 官方板"),
]

# 这些口**永远不可能是**手套主板，探测它们纯属浪费时间：
#   蓝牙虚拟口、主板自带 ACPI 通信口、并口、软件虚拟口
BLACKLIST = [
    ("BTHENUM",  "蓝牙虚拟串口"),
    ("BTHMODEM", "蓝牙调制解调器"),
    ("LPTENUM",  "并口"),
    ("ROOT\\PORTS", "软件虚拟口"),
    ("ACPI\\PNP0501", "主板自带通信口（不是 USB 设备）"),
]
BLACKLIST_DESC = ["蓝牙", "Bluetooth", "红外", "IrDA"]

SCORE_PROBE_FLOOR = 0     # 分数 >= 这个值才值得去试探
SCORE_BLACKLISTED = -1000


def score_port(device, desc, hwid):
    """给一个串口打分，返回 (分数, 理由)。

    分数越高越可能是手套主板。被拉黑的返回 SCORE_BLACKLISTED。
    这是个**纯函数** —— 不碰硬件，所以可以拿假的 hwid 直接单测。
    """
    h = (hwid or "").upper()
    d = (desc or "")
    for frag, why in BLACKLIST:
        if frag.upper() in h:
            return SCORE_BLACKLISTED, "跳过：" + why
    for frag in BLACKLIST_DESC:
        if frag in d:
            return SCORE_BLACKLISTED, "跳过：描述里写着 " + frag
    for vid, sc, why in VENDOR_HINTS:
        if vid in h:
            return sc, why
    if "VID_" in h or "VID:" in h:
        return 20, "USB 串口设备（芯片没认出来，放最后试）"
    # 剩下的多半是板载口/虚拟口，还是试一下 —— 万一用户拿的就是它
    return 5, "非 USB 串口（最后才试）"


def rank_ports(entries=None):
    """列出并排序串口。entries=None 时去问操作系统要。

    entries 可以传 [(device, desc, hwid), ...]，方便单测。
    """
    if entries is None:
        entries = [(p.device, p.description or "", p.hwid or "") for p in list_ports.comports()]
    out = []
    for dev, desc, hwid in entries:
        sc, why = score_port(dev, desc, hwid)
        out.append({"device": dev, "desc": desc, "hwid": hwid,
                    "score": sc, "reason": why,
                    "candidate": sc >= SCORE_PROBE_FLOOR})
    out.sort(key=lambda e: (-e["score"], e["device"]))
    return out


def short_reason(entry):
    return entry["reason"]


# ============================================================
# 串口会话
# ============================================================
PROBE_TTL = 20.0          # 探测结果缓存多久（秒）—— 免得每次重扫都把没回应的口又问一遍
LOG_MAX = 4000            # 保留多少行历史（够页面长轮询回补）


class Bridge(object):
    """一条串口 + 一个行缓冲日志。

    所有对外的读写都从这里过。线程模型：
      · 读线程     —— 唯一一个碰 ser.read 的人，读到的行塞进 self._log
      · 写锁       —— 保护 ser.write，避免两个请求把字节插花
      · 自动连接线程 —— 没连上时定期扫口、试探、连上
    """

    def __init__(self, url=None, baud=115200, auto=True):
        self.url = url                 # 指定了口就一直用它
        self.baud = baud
        self.auto = auto and (url is None)
        self.ser = None
        self.port = None               # 当前实际连着的口（"COM4" 或 url）
        self.connected = False
        self.last_error = ""
        self.connected_at = 0.0
        self.reconnects = 0
        self.paused = False            # 用户按了「断开」就置位 —— 别立刻又给他连上
        self.probe_ok = None           # 探测命中的那个口（给 UI 显示「推荐」）

        self._log = deque(maxlen=LOG_MAX)   # [(seq, line)]
        self._seq = 0
        self._log_base = 1                  # self._log[0] 对应的 seq
        self._cv = threading.Condition()
        self._wlock = threading.Lock()
        self._send_lock = threading.Lock()
        self._probe_cache = {}              # device -> (时间, 是否回应 INFO)
        self._stop = False
        self._reader = None

        self._reload_ports()

    # ---------- 端口清单 ----------
    def _reload_ports(self):
        try:
            self.ports = rank_ports()
        except Exception as e:                     # 枚举本身失败也不能把服务搞死
            self.ports = []
            self.last_error = "枚举串口失败：%s" % e

    # ---------- 日志 ----------
    def _push(self, line):
        with self._cv:
            self._seq += 1
            self._log.append((self._seq, line))
            self._log_base = self._log[0][0]
            self._cv.notify_all()

    def lines_since(self, since):
        """返回 seq > since 的所有行。"""
        with self._cv:
            if not self._log:
                return [], self._seq
            base = self._log[0][0]
            idx = max(0, since + 1 - base)
            return [{"seq": s, "line": l} for s, l in list(self._log)[idx:]], self._seq

    # ---------- 打开/关闭 ----------
    def _open_raw(self, target):
        """target 可以是 'COM4'，也可以是 pyserial 的 URL（socket://… / spy://…）。"""
        if "://" in target:
            ser = serial.serial_for_url(target, baudrate=self.baud, timeout=0.05,
                                        write_timeout=1.0, do_not_open=True)
            ser.open()
        else:
            ser = serial.Serial(target, self.baud, timeout=0.05, write_timeout=1.0)
        return ser

    def _start_reader(self):
        self._reader = threading.Thread(target=self._read_loop, name="pg-read", daemon=True)
        self._reader.start()

    def _read_loop(self):
        buf = b""
        while not self._stop:
            ser = self.ser
            if ser is None or not self.connected:
                return
            try:
                chunk = ser.read(4096)
            except Exception as e:
                # 主动 close() 时 ser 已经关了，这里必然会抛 —— 那是正常收工，不是掉线
                if self.connected:
                    self._drop("串口读失败：" + str(e))
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", "replace").rstrip("\r")
                if line.strip():
                    self._push(line)
        return

    def _drop(self, why):
        """断开（不关 ser，让 close 统一处理）。"""
        was = self.connected
        self.connected = False
        self.last_error = why
        if was:
            self._push("<<桥>> 串口断开：" + why)

    def close(self):
        self.connected = False
        ser, self.ser = self.ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        self.port = None
        self.connected_at = 0.0        # 断了就别留着上次的时间戳，界面会照着它算「连了多久」
        with self._cv:
            self._cv.notify_all()

    def open(self, target=None, baud=None):
        """连一个口。返回 (ok, 说明)。"""
        target = target or self.url or self.port
        if not target:
            return False, "没有指定串口"
        if baud:
            self.baud = baud
        self.close()
        try:
            self.ser = self._open_raw(target)
        except Exception as e:
            code = getattr(e, "winerror", None)
            hint = {5: "端口被别的程序占着（串口监视器？另一个浏览器标签？），关掉它或拔插一次",
                    31: "驱动栈卡住了，拔插一次 USB 基本就好"}.get(code, "")
            self.last_error = "打不开 %s：%s" % (target, e) + ("｜" + hint if hint else "")
            return False, self.last_error
        self.port = target
        self.connected = True
        self.connected_at = time.time()
        self.last_error = ""
        # 立刻起读线程，不在这里做 reset_input_buffer()。
        # 曾经这里 sleep 0.25 秒再把缓冲里那点字节读出来当「上电主动上报」，
        # 结果 reset_input_buffer() 先把它清掉了 —— 板子上电自己吐的 BOOT 行
        # 直接消失（自测里那条 pre 断言就是这么照出来的）。
        # 读线程从第一毫秒就在听，什么都不会漏；这些行会先落到日志里，
        # 页面用 since 拿的时候会作为「杂线 pre」还给它，不会混进命令回复。
        self._start_reader()
        return True, "已连接 " + target

    # ---------- 探测 ----------
    def probe(self, target, wait=1.6, use_cache=True):
        """给一个口发 INFO，看它回不回 OK INFO。会**真的开关串口**。

        返回 (是否命中, 说明)。绝不发任何驱动舵机的命令，插着什么都安全。

        注意：一般不用它做自动连接的判断（见 autoconnect_once —— 那才是主路径）。
        它留在这里是给手动排查用的：打开就复位、复位完又可能没启动完，
        所以这里要**多问几次**，一次不答不等于不是它。
        """
        now = time.time()
        if use_cache:
            hit = self._probe_cache.get(target)
            if hit and now - hit[0] < PROBE_TTL:
                return hit[1], hit[2]
        try:
            ser = self._open_raw(target)
        except Exception as e:
            self._probe_cache[target] = (now, False, "打不开：" + str(e))
            return False, self._probe_cache[target][2]
        try:
            time.sleep(0.35)                 # 让板子从"开串口导致的复位"里缓过来
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            buf = b""
            for _ in range(2):
                try:
                    ser.write(b"INFO\r\n")
                except Exception:
                    break
                t0 = time.time()
                while time.time() - t0 < wait / 2:
                    try:
                        d = ser.read(4096)
                    except Exception:
                        d = b""
                    if d:
                        buf += d
                        if b"OK INFO" in buf:
                            break
                    else:
                        time.sleep(0.02)
                if b"OK INFO" in buf:
                    break
            ok = b"OK INFO" in buf
            why = "回应了 OK INFO" if ok else ("收到 %d 字节但没 INFO" % len(buf) if buf else "没有任何回应")
            self._probe_cache[target] = (now, ok, why)
            return ok, why
        except Exception as e:
            self._probe_cache[target] = (now, False, "探测出错：" + str(e))
            return False, self._probe_cache[target][2]
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def _wait_info(self, attempts=4, wait=0.7):
        """已经开着口了，问几次 INFO，看板子答不答。

        为什么不能只问一次：**打开串口本身会让 ESP32 复位**（CP2102 的 DTR/RTS
        接着自动复位电路）。刚 open 完就发 INFO，十有八九打在启动过程里，
        于是"板子明明插着、却判成不是它" —— 自动连接就成了随机事件。
        这里给足 4 × 0.7s，正常板子 1 秒内就答了。
        """
        start = self._seq
        for _ in range(attempts):
            if not self._write("INFO"):
                return False
            t0 = time.time()
            while time.time() - t0 < wait:
                lines, _ = self.lines_since(start)
                if any(l["line"].startswith("OK INFO") for l in lines):
                    return True
                time.sleep(0.04)
        return False

    # ---------- 自动连接 ----------
    def autoconnect_once(self):
        """扫一遍，按推荐顺序逐个"开起来问一句"。返回 (ok, 说明)。

        为什么是"先开再问"而不是"先探再开"：
        探测和连接都要 open 一次串口，open 就复位。先探后连 = 复位两次，
        板子白等一轮启动；而且探测期间它还没启动完，很容易误判成"不是它"。
        所以直接开，开完耐心问几次 INFO，答了就是它。
        """
        if self.connected:
            return True, "已连接 " + str(self.port)
        if self.paused:
            return False, "已被用户断开，等一个明确的连接请求"
        self._reload_ports()
        cands = [p for p in self.ports if p["candidate"]]
        if not cands and self.ports:
            cands = self.ports[:1]                 # 全被拉黑了也试一个，别彻底放弃
        if not cands:
            return False, "没有发现任何串口 —— 板子插了吗？USB 线是数据线吗？"
        # 自己再排一次，不指望调用方给的是排好的 —— "推荐口优先"是这一步的核心承诺，
        # 不能因为上游哪天忘了 sort 就悄悄退化成"按枚举顺序碰运气"。
        cands.sort(key=lambda p: (-p["score"], p["device"]))
        tried = []
        for p in cands:
            dev = p["device"]
            hit = self._probe_cache.get(dev)
            if hit and not hit[1] and time.time() - hit[0] < PROBE_TTL:
                tried.append(dev + "(刚试过没回应)")
                continue
            ok, msg = self.open(dev)
            if not ok:
                self._probe_cache[dev] = (time.time(), False, "打不开")
                tried.append(dev + "(打不开)")
                continue
            if self._wait_info():
                self._probe_cache[dev] = (time.time(), True, "OK INFO")
                self.probe_ok = dev
                self._push("<<桥>> 自动连接 " + dev + "（" + short_reason(p) + "）")
                return True, msg
            self._probe_cache[dev] = (time.time(), False, "没有回应 INFO")
            tried.append(dev + "(没回应INFO)")
            self.close()
        return False, "试过 " + " ".join(tried) + "，都没有回应 INFO"

    def _autoloop(self):
        """没连上就一直扫。用户主动断开（paused）时不扫 —— 否则「断开」按钮会当场失效：
        前脚断开，后脚这一轮循环又给连回去了（自测里那条断言就是这么照出来的）。"""
        if self.url:
            while not self._stop:
                if not self.connected and not self.paused:
                    self.open(self.url)
                time.sleep(1.0)
            return
        if not self.auto:
            return
        while not self._stop:
            if not self.connected and not self.paused:
                try:
                    self.autoconnect_once()
                except Exception:
                    pass
                # 没连上就快扫（等热插拔），连上了就慢扫（只是看着）
                time.sleep(2.0)
            else:
                time.sleep(1.0)

    # ---------- 写 ----------
    def _write(self, cmd):
        ser = self.ser
        if not self.connected or ser is None:
            self.last_error = "串口没连上"
            return False
        data = (cmd + "\r\n").encode("utf-8")
        try:
            with self._wlock:
                ser.write(data)
            return True
        except Exception as e:
            self._drop("写失败：" + str(e))
            return False

    def fire(self, cmd):
        return self._write(cmd)

    def send(self, cmd, timeout_ms=2500, quiet_ms=140, since=None):
        """发一条命令并收回复。

        收尾规则和网页版一致：收到第一行后，安静 quiet_ms 毫秒就认为说完了，立刻返回。
        这样长得像 STATUS_ALL 的多行回复不会被死等到 timeout。
        """
        t0 = time.time()
        with self._send_lock:
            if not self.connected:
                return {"ok": False, "error": self.last_error or "串口没连上",
                        "pre": [], "lines": [], "first": None, "ms": 0,
                        "seq": self._seq}
            pre = []
            if since is not None:
                pre, _ = self.lines_since(since)
                pre = [p["line"] for p in pre]
            cur = self._seq
            if not self._write(cmd):
                return {"ok": False, "error": self.last_error,
                        "pre": pre, "lines": [], "first": None, "ms": 0, "seq": cur}
            got, first, last = [], None, t0
            deadline = t0 + timeout_ms / 1000.0
            idle_giveup = t0 + max(0.0, (timeout_ms - 200)) / 1000.0
            while True:
                fresh, _ = self.lines_since(cur)
                for item in fresh:
                    cur = item["seq"]
                    got.append(item["line"])
                    if first is None:
                        first = time.time()
                    last = time.time()
                now = time.time()
                if got and (now - last) * 1000 >= quiet_ms:
                    break
                if now >= deadline or (not got and now >= idle_giveup):
                    break
                with self._cv:
                    self._cv.wait(0.012)
            ms = (max(first or 0.0, last) - t0) * 1000.0
            return {"ok": True, "pre": pre, "lines": got,
                    "first": None if first is None else (first - t0) * 1000.0,
                    "ms": ms, "seq": cur}

    # ---------- 状态 ----------
    def status(self):
        return {
            "bridge": 1,
            "connected": self.connected,
            "port": self.port,
            "baud": self.baud,
            "auto": self.auto,
            "paused": self.paused,
            "fixed": self.url,
            "error": self.last_error,
            "recommended": self.probe_ok,
            "ports": self.ports,
            "seq": self._seq,
            "connectedAt": self.connected_at,
        }


# ============================================================
# HTTP 层
# ============================================================
HOST_DIR = os.path.dirname(os.path.abspath(__file__))
MIME = {".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".mid": "audio/midi",
        ".md": "text/markdown; charset=utf-8",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".bat": "text/plain; charset=utf-8",
        ".py": "text/plain; charset=utf-8"}

# 这些路径不给静态服务 —— 免得随手一个 GET 就把主机上能开的串口列表/测试脚本全抖出去
DENY_PREFIX = ("/tests/shots",)
DENY_FILES = (".git",)


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        server_version = "piano-glove-bridge"
        protocol_version = "HTTP/1.1"

        # ---- 小工具 ----
        def _origin_ok(self):
            """只放行同源和本机来源。

            别的网站如果让用户的浏览器去 POST /api/fire，是能真把舵机拧动的。
            所以这里按 Origin 拦一道 —— 没这个头（curl、同源 GET）就放过。
            """
            org = self.headers.get("Origin")
            if not org:
                return True
            try:
                host = urlparse(org).hostname
            except Exception:
                return False
            return host in ("127.0.0.1", "localhost", "[::1]", "::1")

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception:
                return {}

        def log_message(self, fmt, *args):
            pass                                   # 别把访问日志刷满屏幕

        # ---- GET ----
        def do_GET(self):
            if not self._origin_ok():
                return self._json({"ok": False, "error": "跨站请求被拒绝"}, 403)
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/status":
                return self._json(bridge.status())
            if u.path == "/api/ports":
                bridge._reload_ports()
                return self._json({"ports": bridge.ports})
            if u.path == "/api/lines":
                since = int((q.get("since") or ["0"])[0])
                wait = min(20.0, max(0.0, float((q.get("wait") or ["0"])[0])))
                lines, latest = bridge.lines_since(since)
                if not lines and wait > 0 and bridge.connected:
                    with bridge._cv:
                        bridge._cv.wait(wait)
                    lines, latest = bridge.lines_since(since)
                return self._json({"lines": lines, "seq": latest})
            return self._static(u.path)

        # ---- POST ----
        def do_POST(self):
            if not self._origin_ok():
                return self._json({"ok": False, "error": "跨站请求被拒绝"}, 403)
            u = urlparse(self.path)
            b = self._body()
            try:
                if u.path == "/api/scan":
                    bridge._reload_ports()
                    ok, why = (None, "") if not b.get("probe") else bridge.autoconnect_once()
                    return self._json({"ok": True, "ports": bridge.ports,
                                       "connect": ({"ok": ok, "msg": why} if ok is not None else None)})
                if u.path == "/api/connect":
                    port = (b.get("port") or "").strip()
                    baud = b.get("baud")
                    bridge.paused = False
                    if port:
                        ok, msg = bridge.open(port, baud)
                        if ok:
                            bridge.probe_ok = port
                    else:
                        ok, msg = bridge.autoconnect_once()
                    return self._json({"ok": ok, "msg": msg, "port": bridge.port,
                                       "baud": bridge.baud, "seq": bridge._seq,
                                       "ports": bridge.ports})
                if u.path == "/api/disconnect":
                    bridge.paused = True
                    bridge.close()
                    return self._json({"ok": True})
                if u.path == "/api/send":
                    r = bridge.send(str(b.get("cmd", "")),
                                    float(b.get("timeoutMs", 2500)),
                                    float(b.get("quietMs", 140)),
                                    b.get("since"))
                    return self._json(r)
                if u.path == "/api/fire":
                    ok = bridge.fire(str(b.get("cmd", "")))
                    return self._json({"ok": ok, "error": bridge.last_error})
            except Exception as e:
                return self._json({"ok": False, "error": str(e),
                                   "trace": traceback.format_exc()}, 500)
            return self._json({"ok": False, "error": "未知接口 " + u.path}, 404)

        # ---- 静态文件 ----
        def _static(self, path):
            if path == "/":
                path = "/web_piano_glove.html"
            path = unquote(path)
            if any(d in path for d in DENY_FILES) or path.startswith(DENY_PREFIX):
                return self._json({"ok": False, "error": "不给"}, 403)
            fp = os.path.normpath(os.path.join(HOST_DIR, path.lstrip("/\\")))
            if not fp.startswith(HOST_DIR):
                return self._json({"ok": False, "error": "越界"}, 403)
            if not os.path.isfile(fp):
                body = ("找不到 " + path).encode("utf-8")
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            size = os.path.getsize(fp)
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(os.path.splitext(fp)[1].lower(),
                                                      "application/octet-stream"))
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")   # 改完页面刷新就能看到
            self.end_headers()
            with open(fp, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except Exception:
                        return
            return

        def handle_one_request(self):
            # 浏览器长轮询会提前断连，这时 BaseHTTPRequestHandler 会喷一堆
            # ConnectionAbortedError 到 stderr。屏蔽掉，只当无事发生。
            try:
                BaseHTTPRequestHandler.handle_one_request(self)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                self.close_connection = True

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="钢琴手套本地串口桥")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PG_BRIDGE_PORT", 8123)),
                    help="HTTP 端口（默认 8123）")
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--url", default=os.environ.get("PG_SERIAL_URL"),
                    help="写死串口，例如 COM4 或 socket://127.0.0.1:9701")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--no-auto", action="store_true", help="不自动扫描/连接")
    ap.add_argument("--open", action="store_true", help="起来后自动开浏览器")
    args = ap.parse_args(argv)

    bridge = Bridge(url=args.url, baud=args.baud, auto=not args.no_auto)
    threading.Thread(target=bridge._autoloop, name="pg-auto", daemon=True).start()

    srv = ThreadingHTTPServer((args.bind, args.port), make_handler(bridge))
    srv.daemon_threads = True
    url = "http://%s:%d/web_piano_glove.html" % (args.bind, args.port)

    print("=" * 62)
    print(" 钢琴手套 · 本地串口桥")
    print("=" * 62)
    print(" 调试台： " + url)
    if args.url:
        print(" 串口：   %s（写死，%d baud）" % (args.url, args.baud))
    elif args.no_auto:
        print(" 串口：   不自动连接（页面上手动选）")
    else:
        print(" 串口：   自动扫描 + 自动连接（拔了再插会自己连回来）")
    ports = bridge.ports
    if ports:
        for p in ports:
            mark = "★推荐" if p["candidate"] else " 跳过"
            print("   %s %-6s %s  —— %s" % (mark, p["device"], p["desc"][:36], p["reason"]))
    else:
        print("   （现在一个串口都没发现）")
    print("-" * 62)
    print(" 页面里不用再选串口。改完页面文件刷新即可（不缓存）。")
    print(" Ctrl+C 退出。")
    print("=" * 62)
    sys.stdout.flush()

    if args.open:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] 收工")
    finally:
        bridge.close()


if __name__ == "__main__":
    main()

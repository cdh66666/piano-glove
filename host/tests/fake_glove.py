#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一台「假手套」—— 一个 TCP socket，说手套的文本协议。

为什么要用 TCP 装串口
--------------------
pyserial 本身支持 `socket://host:port` 这种「串口 URL」。所以：
    bridge.py --url socket://127.0.0.1:9701
就能把 TCP 当成串口用。于是自测里 **bridge.py 的每一行都是真跑的**
（真进程、真 HTTP、真 pyserial、真的收发线程），唯一假的东西是"对面那块板子"——
而那个本来就没法在 CI 里假装是真的。

它是给 tests/ 用的，**不在产品里**，页面上也没有任何入口。

用法：
    python tests/fake_glove.py 9701          # 前台跑，Ctrl+C 停
"""

import socket
import socketserver
import sys
import threading
import time

SLOT_NAMES = ["拇指侧压", "拇指下压", "食指", "中指", "无名指", "小指"]
CLOSE_WAIT = 0.05


class Device(object):
    """极简版固件。只实现自测要用到的命令 —— 需要什么再加，别抄成第二份完整固件。

    这里故意**不**照抄页面里那份 MockFirmware：那份是给"没有串口的页面级自测"用的，
    这份是给"真串口链路"用的，职责不同。重复实现是不好，但它俩假的东西不一样。
    """

    def __init__(self):
        self.profile = "STS3032"
        self.calibrated = "0"
        self.armed = "0"
        self.slot_id = [1, 2, 3, 4, 5, 6]
        self.online = [True] * 6
        self.rates = []                      # 延迟吐 RATE_DONE 的定时器

    def range_(self):
        return 4095 if self.profile == "STS3032" else 1023

    def handle(self, cmd, out):
        """out(line) 用来吐行；RATE_DONE 之类的异步行也走它。"""
        parts = cmd.strip().split()
        if not parts:
            return
        v = parts[0].upper()
        a = parts[1:]

        if v == "HELP":
            out("OK HELP INFO PROFILE PING SCAN STATUS STATUS_ALL RATE ECHO")
        elif v == "ECHO":
            out("OK ECHO " + " ".join(a))
        elif v == "INFO":
            out("OK INFO fw=PIANO_GLOVE_2 profile=%s range=%d ap=PIANO_GLOVE_FAKE "
                "ip=192.168.4.1 calibrated=%s armed=%s auto_active=0 enroll_active=0 "
                "enroll_next=1 enroll_temp=10 enroll_phase=OFF"
                % (self.profile, self.range_(), self.calibrated, self.armed))
        elif v == "PROFILE":
            n = (a[0] if a else "").upper()
            if n in ("SC09", "STS3032"):
                self.profile = n
                out("OK PROFILE name=%s range=%d" % (n, self.range_()))
            else:
                out("ERR PROFILE must_be_SC09_or_STS3032")
        elif v == "PING":
            i = int(a[0]) if a else 0
            ok = 1 <= i <= 6 and self.online[i - 1]
            out(("OK PING id=%d" if ok else "ERR PING id=%d") % i)
        elif v == "STATUS":
            i = int(a[0]) if a else 0
            ok = 1 <= i <= 6 and self.online[i - 1]
            out(("OK STATUS id=%d profile=%s pos=2048 speed=0 load=0 voltage_raw=57 "
                 "temperature=32 current=0 moving=0 mode=0" % (i, self.profile)) if ok
                else "ERR STATUS id=%d offline=1" % i)
        elif v == "STATUS_ALL":
            for s in range(6):
                i = self.slot_id[s]
                on = self.online[s]
                out("SLOT slot=%d name=%s id=%d online=%d%s min=512 standby=2048 max=3584 "
                    "valid=%d press=+"
                    % (s, SLOT_NAMES[s], i, 1 if on else 0,
                       " pos=2048 speed=0 load=0 voltage_raw=57 temperature=32 current=0" if on else "",
                       1 if self.calibrated == "1" else 0))
            out("OK STATUS_ALL profile=%s armed=%s" % (self.profile, self.armed))
        elif v == "SCAN":
            out("SCAN_BEGIN profile=%s max=20" % self.profile)
            for s in range(6):
                if self.online[s]:
                    out("FOUND id=%d" % self.slot_id[s])
            out("SCAN_END count=%d" % sum(1 for x in self.online if x))
        elif v == "MAP":
            s, i = int(a[0]), int(a[1])
            self.slot_id[s] = i
            out("OK MAP slot=%d id=%d" % (s, i))
        elif v == "RATE":
            # 故意**拖到最后才吐** RATE_DONE：这样它一定是在 HTTP 响应返回之后
            # 才从串口冒出来的异步行，正好用来验长轮询（/api/lines）这条路通不通。
            out("OK RATE_START slots=0x3F speed=100 acc=0 depth=100 cycles=3")
            t = threading.Timer(0.45, lambda: out(
                "RATE_DONE cycles=3 half_ms=34.0 full_ms=68.0 hz=14.71 slow_ms=35.0 lost=0"))
            t.daemon = True
            t.start()
            self.rates.append(t)
        else:
            out("ERR UNKNOWN_COMMAND verb=" + v)


class Session(socketserver.BaseRequestHandler):
    def handle(self):
        dev = Device()
        self.request.settimeout(0.2)
        self._lock = threading.Lock()
        buf = b""
        # 上电主动上报 —— 真板子也是这样，桥必须能把它当成"杂线"而不是命令回复
        self.emit("BOOT fw=PIANO_GLOVE_2 ready=1")
        while True:
            try:
                chunk = self.request.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                cmd = raw.decode("utf-8", "replace").strip()
                if not cmd:
                    continue
                # ⚠️ out 必须是"立刻发出去"，不能是"append 到一个列表里等会儿发"。
                # 一开始写成列表，结果 RATE_DONE 这种**过一会儿才吐**的行
                # 加进的是已经发完、即将被丢弃的那个列表 —— 一个字都出不去，
                # 桥那边的长轮询自然永远等不到它。
                dev.handle(cmd, self.emit)

    def emit(self, line):
        with self._lock:
            try:
                self.request.sendall((line + "\r\n").encode("utf-8"))
            except OSError:
                pass
        time.sleep(0.002)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(port):
    srv = Server(("127.0.0.1", port), Session)
    print("假手套在端口 %d 等着（pyserial 用 socket://127.0.0.1:%d 接进来）" % (port, port))
    sys.stdout.flush()
    srv.serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9701)

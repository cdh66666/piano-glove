#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地串口桥的自测 —— 不需要任何硬件。

假的东西只有"对面那块板子"（tests/fake_glove.py，一个说手套协议的 TCP 服务，
pyserial 用 socket:// 就能接上去）。剩下全是真的：
真 bridge.py 进程、真 HTTP、真 pyserial、真收发线程。

跑法：
    python tests/bridge_check.py

退出码 0 = 全过。
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.path.dirname(HERE)
sys.path.insert(0, HOST)

import bridge as B                                    # noqa: E402  （顺便单测它的打分函数）

PORT = 8139
FAKE_PORT = 9701
PY = sys.executable

checks = 0
failures = 0


def check(name, cond, extra=None):
    global checks, failures
    checks += 1
    if not cond:
        failures += 1
    tag = "  PASS" if cond else "  FAIL"
    print(tag + "  " + name + ("   [" + str(extra) + "]" if extra is not None else ""))


def get(path, timeout=10):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def post(path, body, origin=None, timeout=20):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=data,
                                 headers={"Content-Type": "application/json"})
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def raw(method, path, origin=None, acrm=None, acrh=None, timeout=10):
    """发一个请求，连**状态码 + 响应头 + body** 一起拿回来。

    为什么非得看响应头：跨来源到底能不能用，全在 CORS 头上 ——
    只看状态码 200 完全不够。浏览器会因为缺少 `Access-Control-Allow-Origin`
    把响应整个丢掉，页面那头的表现和 403 一模一样（都报"桥没运行"）。
    所以「跨来源能用」这件事必须验到头上，不能只验"服务端处理了"。
    """
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), method=method)
    if origin:
        req.add_header("Origin", origin)
    if acrm:
        req.add_header("Access-Control-Request-Method", acrm)
    if acrh:
        req.add_header("Access-Control-Request-Headers", acrh)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def wait_up(timeout=12.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s, j = get("/api/status", 2)
            if j.get("bridge") == 1:
                return j
        except Exception:
            pass
        time.sleep(0.2)
    return None


def wait_connected(timeout=12.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s, j = get("/api/status", 2)
            if j.get("connected"):
                return j
        except Exception:
            pass
        time.sleep(0.2)
    return None


# ============================================================
# 1. 推荐串口的打分（纯函数，不用起进程）
# ============================================================
def test_scoring():
    print("\n=== 1. 推荐串口打分 ===")
    sc, why = B.score_port("COM4", "Silicon Labs CP210x USB to UART Bridge",
                           "USB VID:PID=10C4:EA60 SER=0001")
    check("CP210x（微雪板载）分最高", sc == 100 and "CP210" in why, "%d %s" % (sc, why))

    sc2, _ = B.score_port("COM7", "USB-SERIAL CH340", "USB VID:PID=1A86:7523")
    check("CH340 也认得出且低于 CP210x", 0 < sc2 < sc, sc2)

    sc3, _ = B.score_port("COM9", "ESP32-S3 USB Serial/JTAG", "USB VID:PID=303A:1001")
    check("ESP32-S3 原生 USB 认得出", sc3 > 0, sc3)

    bad, whyb = B.score_port("COM5", "Bluetooth 链路上的标准串行",
                             "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}")
    check("蓝牙虚拟口被拉黑", bad == B.SCORE_BLACKLISTED, whyb)

    bad2, why2 = B.score_port("COM1", "通信端口 (COM1)", "ACPI\\PNP0501\\0")
    check("主板自带 COM1 被拉黑", bad2 == B.SCORE_BLACKLISTED, why2)

    sc4, _ = B.score_port("COM11", "USB Serial Device", "USB VID:PID=1234:5678")
    check("认不出芯片的 USB 口仍会去试（放最后）",
          sc4 == 20 and sc4 >= B.SCORE_PROBE_FLOOR, sc4)

    ranked = B.rank_ports([
        ("COM1", "通信端口 (COM1)", "ACPI\\PNP0501\\0"),
        ("COM7", "USB-SERIAL CH340", "USB VID:PID=1A86:7523"),
        ("COM4", "Silicon Labs CP210x", "USB VID:PID=10C4:EA60"),
        ("COM5", "Bluetooth", "BTHENUM\\{00001101}"),
    ])
    order = [p["device"] for p in ranked]
    check("排序：推荐口在最前，被拉黑的在最后",
          order[0] == "COM4" and order[-1] == "COM5", order)
    check("被拉黑的不算候选", [p["candidate"] for p in ranked] == [True, True, False, False],
          [p["candidate"] for p in ranked])


# ============================================================
# 2. 自动挑推荐口 —— 用户的原始诉求就是这一句「自动选择推荐串口自动连接」
# ============================================================
def test_autoconnect_order():
    print("\n=== 2. 自动挑推荐口（只验决策，不碰硬件） ===")

    def make(ports, answering):
        """造一个桥，把"打开口"和"问 INFO"换成假的，只看它**怎么选**。"""
        br = B.Bridge(auto=False)            # auto=False -> 不起自动线程
        br._reload_ports = lambda: None
        br.ports = ports
        opens = []
        br.open = lambda dev, baud=None: (opens.append(dev),
                                          setattr(br, "port", dev),
                                          setattr(br, "connected", True),
                                          (True, "已连接 " + dev))[3]
        br.close = lambda: (setattr(br, "connected", False), setattr(br, "port", None))
        br._wait_info = lambda attempts=4, wait=0.7: br.port in answering
        return br, opens

    P = lambda dev, score, cand, why: {"device": dev, "desc": "", "hwid": "",
                                       "score": score, "reason": why, "candidate": cand}

    ports = [
        P("COM1", -1000, False, "主板自带通信口"),
        P("COM7", 92, True, "沁恒 CH340"),
        P("COM4", 100, True, "Silicon Labs CP210x"),
    ]
    br, opens = make(ports, {"COM4"})
    ok, msg = br.autoconnect_once()
    check("被拉黑的口根本不去打开它", "COM1" not in opens, opens)
    check("按推荐分从高到低试，不回应的口会被跳过",
          opens == ["COM4"], opens)
    check("连上的是回了 OK INFO 的那个口",
          ok and br.probe_ok == "COM4" and br.port == "COM4", "%s / %s" % (ok, msg))

    # 微雪板子排在后面时，前面那个杂牌口不回应 —— 必须继续往后试，不能栽在第一个
    ports2 = [P("COM4", 100, True, "CP210x"), P("COM7", 92, True, "CH340")]
    br2, opens2 = make(ports2, {"COM7"})
    ok2, msg2 = br2.autoconnect_once()
    check("推荐口不对时会继续试下一个，直到找到板子",
          ok2 and br2.port == "COM7" and opens2 == ["COM4", "COM7"], opens2)

    # 谁都不答：必须明确说"都没有回应"，绝不能瞎连一个
    br3, opens3 = make(ports, set())
    ok3, msg3 = br3.autoconnect_once()
    check("没有板子时不瞎连、并给出人能看懂的原因",
          (not ok3) and (not br3.connected) and "没有回应" in msg3, msg3)

    # 刚试过没回应的口要进缓存 —— 不然每 2 秒就把所有口重开一遍（每次开都复位板子）
    opens3.clear()
    br3.autoconnect_once()
    check("刚试过没回应的口会被缓存跳过（不反复复位板子）", opens3 == [], opens3)

    # 板子插上（缓存过期）后要能自己认出来
    br3._probe_cache.clear()
    br3._wait_info = lambda attempts=4, wait=0.7: br3.port == "COM4"
    ok4, _ = br3.autoconnect_once()
    check("缓存过期后重扫能认出新插上的板子", ok4 and br3.probe_ok == "COM4", br3.port)

    # ★ 只剩被硬拉黑的口时，兜底也**不能**去连它。
    # 曾经这里写的是 self.ports[:1]（"全被拉黑了也试一个，别彻底放弃"），
    # 于是主板自带的 COM1（ACPI\PNP0501）被当成手套连上了，界面还显示"已连接"——
    # 之后桥再也不去找真板子。比"没找到设备"难查一百倍。
    # 这里连"COM1 会回 INFO"这种最严的情况也一起验：拉黑就该是真的拉黑。
    br5, opens5 = make([P("COM1", -1000, False, "主板自带通信口")], {"COM1"})
    ok5, msg5 = br5.autoconnect_once()
    check("只剩硬拉黑的口时不兜底连它（宁可老实说没找到）",
          (not ok5) and (not br5.connected) and opens5 == [],
          "ok=%s opens=%s msg=%s" % (ok5, opens5, msg5))


# ============================================================
# 3. 真桥 + 假手套 跑一遍 API
# ============================================================
def test_api():
    print("\n=== 3. 桥的 HTTP 接口（真进程 / 真 pyserial / 假板子） ===")
    fake = subprocess.Popen([PY, "-u", os.path.join(HERE, "fake_glove.py"), str(FAKE_PORT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    time.sleep(0.6)
    br = subprocess.Popen([PY, "-u", os.path.join(HOST, "bridge.py"),
                           "--port", str(PORT),
                           "--url", "socket://127.0.0.1:%d" % FAKE_PORT],
                          stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                          cwd=HOST)
    try:
        st = wait_up()
        check("桥起来了并且 /api/status 自报身份", bool(st), st and st.get("bridge"))

        st = wait_connected()
        check("桥自动连上了指定的口", bool(st) and st.get("connected"), st and st.get("port"))

        # ---- 静态服务 ----
        with urllib.request.urlopen("http://127.0.0.1:%d/web_piano_glove.html" % PORT, timeout=10) as r:
            html = r.read()
        check("同源托管调试台页面", r.status == 200 and len(html) > 50000, "%d 字节" % len(html))
        check("页面里确实有桥的传输层代码", b"/api/send" in html and b"bridgeSeen" in html)

        # ---- 越界 / 跨站 ----
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/..%%2fREADME.md" % PORT, timeout=10)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        check("目录穿越被挡", code == 403, code)
        code, j = post("/api/send", {"cmd": "INFO"}, origin="http://evil.example")
        check("别的网站发来的跨站请求被挡", code == 403 and not j.get("ok"), code)

        # ---- CORS：页面未必在桥的来源上（别的本地服务器托管 / file:// 双击）----
        # 用户实际踩过：页面相对路径 /api/status 打不到桥上，报「没找到本地串口服务」，
        # 可桥明明在跑。修法就是页面改朝绝对地址问 + 桥回 CORS 头 —— 这里验后面那半。
        st, hd, _ = raw("GET", "/api/status", origin="http://127.0.0.1:8151")
        check("跨来源 GET 镜像回请求的 Origin（不是 `*`）",
              st == 200 and hd.get("Access-Control-Allow-Origin") == "http://127.0.0.1:8151",
              "%s %s" % (st, hd.get("Access-Control-Allow-Origin")))

        st, hd, _ = raw("GET", "/api/status", origin="null")
        check("file:// 双击打开的页面（Origin: null）被放行",
              st == 200 and hd.get("Access-Control-Allow-Origin") == "null",
              "%s %s" % (st, hd.get("Access-Control-Allow-Origin")))

        st, hd, _ = raw("OPTIONS", "/api/connect", origin="http://127.0.0.1:8151",
                        acrm="POST", acrh="content-type")
        check("POST 预检被正确应答（否则跨来源命令一条都发不出去）",
              st == 204
              and "POST" in (hd.get("Access-Control-Allow-Methods") or "")
              and "content-type" in (hd.get("Access-Control-Allow-Headers") or "").lower(),
              "%s methods=%s headers=%s" % (st, hd.get("Access-Control-Allow-Methods"),
                                            hd.get("Access-Control-Allow-Headers")))

        st, hd, _ = raw("POST", "/api/send", origin="http://evil.example")
        check("外站 Origin 仍然 403，而且**连 CORS 头都不给**（别把数据漏出去）",
              st == 403 and not hd.get("Access-Control-Allow-Origin"),
              "%s %s" % (st, hd.get("Access-Control-Allow-Origin")))

        # ---- send：普通命令 ----
        s, j = post("/api/send", {"cmd": "INFO", "since": 0})
        lines = j.get("lines") or []
        check("send INFO 拿到 OK INFO",
              any(l.startswith("OK INFO") and "PIANO_GLOVE_2" in l for l in lines), lines)
        check("上电主动上报被当成「杂线」(pre) 而不是命令回复",
              any("BOOT" in l for l in (j.get("pre") or [])), j.get("pre"))
        check("send 回报了首字节延迟和总耗时",
              isinstance(j.get("first"), (int, float)) and isinstance(j.get("ms"), (int, float)),
              "first=%s ms=%s" % (j.get("first"), j.get("ms")))

        s, j = post("/api/send", {"cmd": "STATUS_ALL", "timeoutMs": 4000})
        lines = j.get("lines") or []
        slots = [l for l in lines if l.startswith("SLOT")]
        check("STATUS_ALL 收满 6 行 SLOT + 1 行 OK",
              len(slots) == 6 and any(l.startswith("OK STATUS_ALL") for l in lines),
              "%d SLOT / %d 总行" % (len(slots), len(lines)))
        ids = []
        for l in slots:
            for tok in l.split():
                if tok.startswith("id="):
                    ids.append(int(tok[3:]))
        check("槽位 -> 舵机 ID 映射被原样带回来", ids == [1, 2, 3, 4, 5, 6], ids)
        seq_after_status = j["seq"]

        # ---- fire：只发不等 ----
        post("/api/fire", {"cmd": "ECHO ping"})
        time.sleep(0.4)
        s, j2 = get("/api/lines?since=%d&wait=0" % seq_after_status)
        got = [it["line"] for it in j2["lines"]]
        check("fire 的回复靠长轮询捞回来（不等不堵）",
              any("OK ECHO ping" in l for l in got), got)
        check("长轮询的 seq 是单调递增的",
              all(j2["lines"][i]["seq"] < j2["lines"][i + 1]["seq"] for i in range(len(j2["lines"]) - 1)),
              [it["seq"] for it in j2["lines"]])
        cur = j2["seq"]

        # ---- ★ 批量 fire：一次写一批 —— 这是「演奏延迟」的正解 ----
        # 演奏时上位机一帧能产生几十条 MOVE。逐条 POST 会被浏览器同源并发上限
        # （6 条）排成长队：声音是 Web Audio 当场同步响的，早就听到了，
        # 动作却还在 HTTP 队列里等 —— 用户报的「延迟严重、声音和动作不同步」。
        # 所以桥必须能一次吃下一整批、一次 write 全写下去。
        batch = ["ECHO b%03d" % i for i in range(40)]
        t0 = time.time()
        s, jb = post("/api/fire", {"cmds": batch})
        dt_batch = (time.time() - t0) * 1000
        check("fire 收数组：一次写 40 条",
              jb.get("sent") == 40 and jb.get("asked") == 40, jb)

        t0 = time.time()
        for c in batch:
            post("/api/fire", {"cmd": c})
        dt_single = (time.time() - t0) * 1000

        # 「回 OK」什么都不证明，得数假手套真正收到几条回复行。
        time.sleep(1.2)
        s, j4 = get("/api/lines?since=%d&wait=0" % cur)
        echoed = [it["line"] for it in j4["lines"] if "OK ECHO b" in it["line"]]
        check("批量 + 逐条两条路径发出去的 80 条命令一条不丢",
              len(echoed) == 80, "收到 %d 条（40 批内 + 40 逐条）" % len(echoed))
        check("批量写比逐条写快得多（一帧几十条时的差别就是延迟）",
              dt_batch < dt_single / 2,
              "批量 40 条 %.1fms vs 逐条 40 条 %.1fms" % (dt_batch, dt_single))
        cur = j4["seq"]

        # ---- ★ 异步行：RATE_DONE 是过一会儿才吐的，必须也能捞到 ----
        s, j = post("/api/send", {"cmd": "RATE 1", "timeoutMs": 2000})
        check("RATE 的即时回复立刻拿到",
              any("OK RATE_START" in l for l in (j.get("lines") or [])), j.get("lines"))
        cur = max(cur, j["seq"])
        deadline = time.time() + 4
        done = None
        while time.time() < deadline and not done:
            s, j3 = get("/api/lines?since=%d&wait=1" % cur)
            for it in j3["lines"]:
                cur = it["seq"]
                if "RATE_DONE" in it["line"]:
                    done = it["line"]
        check("延迟吐出的 RATE_DONE 能通过长轮询到达", bool(done), done)

        # ---- RATE_DONE 里报的频率要能被解析出来（页面的测速卡就靠它） ----
        hz = None
        if done:
            for tok in done.split():
                if tok.startswith("hz="):
                    hz = float(tok[3:])
        check("RATE_DONE 里的 hz 可解析", hz is not None and hz > 0, hz)

        # ---- 推荐口的理由要能讲给用户听 ----
        s, j = get("/api/status")
        check("status 带上了端口清单", isinstance(j.get("ports"), list), j.get("ports"))
        check("固定了口时 status 会说明是被写死的",
              j.get("fixed") == "socket://127.0.0.1:%d" % FAKE_PORT, j.get("fixed"))

        # ---- 断开 ----
        s, j = post("/api/disconnect", {})
        time.sleep(0.3)
        s, j = get("/api/status")
        check("断开后 connected=false", j.get("connected") is False, j.get("connected"))
        s, j = post("/api/send", {"cmd": "INFO"})
        check("没连上时 send 明确报错而不是挂死", j.get("ok") is False and j.get("error"), j.get("error"))
    finally:
        for p in (br, fake):
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(0.3)
        for p in (br, fake):
            try:
                p.kill()
            except Exception:
                pass


def main():
    print("=" * 60)
    print(" 本地串口桥自测（不需要硬件）")
    print("=" * 60)
    test_scoring()
    test_autoconnect_order()
    test_api()
    print("\n" + ("全部通过 ✔  共 %d 项" % checks if failures == 0
                  else "失败 %d / %d 项 ✘" % (failures, checks)))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

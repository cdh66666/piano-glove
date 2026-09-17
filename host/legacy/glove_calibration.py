# -*- coding: utf-8 -*-
"""
六自由度钢琴手套 —— 舵机校准 / 驱动程序
========================================
硬件 : 6x STS3032 串行总线舵机 (Feetech SCS/STS 协议, 半双工 TTL 串行)
       全部并联在总线上, 舵机 ID 分别为 1~6
       【拇指双舵机协同】
         1 号 = 拇指·下压 (像其他四指一样直直按下)
         2 号 = 拇指·侧压 (拇指侧向压)
         1+2 同时动 => 拇指斜向下按键
       3、4、5、6 号 -> 食指、中指、无名指、小指
接线 : USB 转总线舵机调试板(或 URT-1 等控制板) -> PC
依赖 : pip install pyserial  (scservo_sdk 已随程序放在同目录)

功能 :
  1. 连接串口后可实时显示 6 个舵机的位置反馈(含 0~100% 行程)
  2. 「开始校准」: 自动关闭扭矩 -> 10 秒内手动活动所有手指(拇指要同时做
     下压和侧压动作) -> 采样每个舵机的最小/最大位置, 保存到 calib.json
  3. 「驱动模式」: 可选目标手指 + 频率 0~6 Hz, 在 80% 行程内正弦往复;
     选「拇指」时 1、2 号同相位运动, 走出斜向按下的轨迹
  4. 「歌曲模式」: 按节奏驱动手指。do = 拇指直按(仅 1 号),
     re = 拇指斜按(1+2 号协同), mi/fa/sol/la = 食/中/无/小指
  5. 随时可「急停」: 关闭全部扭矩
"""

import json
import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import scservo_sdk as sc
except ImportError:
    sc = None

# ----------------- 基本配置 -----------------
SERVO_IDS = [1, 2, 3, 4, 5, 6]

# 拇指是两个舵机协同: 1 号负责拇指「直直向下压」, 2 号负责拇指「侧向压」
# 两个一起动作 => 拇指斜向下按按键
SERVO_ROLE = {
    1: "拇指·下压",
    2: "拇指·侧压",
    3: "食指",
    4: "中指",
    5: "无名指",
    6: "小指",
}
THUMB_SERVOS = [1, 2]          # 拇指由这两个舵机共同控制
LATERAL_RATIO = 0.85           # 侧压舵机(2号)的行程比例, 侧压通常不需要压到底

# 逻辑手指(执行器) -> 参与的舵机, 用于驱动模式
ACTUATORS = [
    ("拇指(下压+侧压)", [1, 2]),
    ("食指", [3]),
    ("中指", [4]),
    ("无名指", [5]),
    ("小指", [6]),
]

CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calib.json")

DEFAULT_BAUD = 115200            # 微雪 Servo Driver with ESP32: PC(USB-C/UART0) <-> 板子串口透传固定 115200
                                 # 板子内部再以 1000000 与 STS3032 总线(UART1, GPIO18/19)通信, 无需关心
CALIB_SECONDS = 10              # 校准采样时长(秒)
SAMPLE_HZ = 100                 # 校准采样率
DRIVE_LOOP_HZ = 50              # 驱动模式控制循环频率
RANGE_USE = 0.80                # 使用最大活动范围的 80%
SPEED = 3400                    # 舵机运动速度(最大档)
ACC = 50                        # 舵机加速度

# STS 系列(含 STS3032) 控制表地址
ADDR_TORQUE_ENABLE = 40
ADDR_GOAL_POSITION = 42         # WritePosEx 内部使用
ADDR_PRESENT_POSITION = 56      # 当前位置, 2 字节

# ----------------- 歌曲模式配置 -----------------
# 音符 -> 一组「同时动作」的舵机 {舵机ID: 下压深度比例(0~1)}
# 拇指直按  = 只动 1 号(下压)
# 拇指斜按  = 1 号(下压) + 2 号(侧压) 一起动
NOTE_ACTIONS = {
    1: {1: 1.00},                                  # do  : 拇指直按
    2: {1: 1.00, 2: LATERAL_RATIO},                # re  : 拇指斜按(双舵机协同)
    3: {3: 1.00},                                  # mi  : 食指
    4: {4: 1.00},                                  # fa  : 中指
    5: {5: 1.00},                                  # sol : 无名指
    6: {6: 1.00},                                  # la  : 小指
    -5: {5: 1.00},                                 # 低音sol: 复用无名指
}
NOTE_NAMES = {1: "do", 2: "re", 3: "mi", 4: "fa", 5: "sol", 6: "la", -5: "sol(低)"}
ACTION_LABELS = {
    1: "do 拇指直按(1号)",
    2: "re 拇指斜按(1+2号)",
    3: "mi 食指(3号)",
    4: "fa 中指(4号)",
    5: "sol 无名指(5号)",
    6: "la 小指(6号)",
    -5: "sol 低音(5号)",
}

# (音符, 拍数), 音符 0 = 休止; 拍数 0.5 = 半拍
SONGS = {
    "两只老虎": [
        (1, 1), (2, 1), (3, 1), (1, 1),
        (1, 1), (2, 1), (3, 1), (1, 1),
        (3, 1), (4, 1), (5, 2),
        (3, 1), (4, 1), (5, 2),
        (5, 0.5), (6, 0.5), (5, 0.5), (4, 0.5), (3, 1), (1, 1),
        (5, 0.5), (6, 0.5), (5, 0.5), (4, 0.5), (3, 1), (1, 1),
        (2, 1), (5, 1), (1, 2),
        (2, 1), (5, 1), (1, 2),
    ],
}


class ServoBus:
    """SCS/STS 总线的封装: 连接、读位置、写位置、扭矩开关。"""

    def __init__(self, port: str, baud: int):
        if sc is None:
            raise RuntimeError("未安装 scservo_sdk, 请先执行: pip install scservo_sdk")
        self.port_name = port
        self.baud = baud
        self.port = sc.PortHandler(port)
        self.ph = sc.sms_sts(self.port)   # STS 系列协议栈 (端口在构造时绑定)

    def connect(self):
        if not self.port.openPort():
            raise RuntimeError(f"无法打开串口 {self.port_name}")
        if not self.port.setBaudRate(self.baud):
            raise RuntimeError(f"无法设置波特率 {self.baud}")

    def close(self):
        try:
            self.port.closePort()
        except Exception:
            pass

    def _comm_err(self, result, error, what):
        if result != sc.COMM_SUCCESS:
            raise RuntimeError(f"{what} 通信失败: {self.ph.getTxRxResult(result)}")
        if error != 0:
            raise RuntimeError(f"{what} 舵机报错: {self.ph.getRxPacketError(error)}")

    def read_position(self, sid: int):
        pos, result, error = self.ph.read2ByteTxRx(sid, sc.SMS_STS_PRESENT_POSITION_L)
        self._comm_err(result, error, f"[{sid}] 读位置")
        return pos

    def write_position(self, sid: int, position: int):
        result, error = self.ph.WritePosEx(sid, int(position), SPEED, ACC)
        self._comm_err(result, error, f"[{sid}] 写位置")

    def set_torque(self, sid: int, on: bool):
        result, error = self.ph.write1ByteTxRx(sid, sc.SMS_STS_TORQUE_ENABLE, 1 if on else 0)
        self._comm_err(result, error, f"[{sid}] 扭矩{'使能' if on else '关闭'}")


class GloveApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("六自由度钢琴手套 - 校准/驱动")

        self.bus: ServoBus | None = None
        self.connected = False

        # 每个舵机状态: pos(实时位置) / cmin / cmax(校准结果)
        self.state = {sid: {"pos": None, "cmin": None, "cmax": None} for sid in SERVO_IDS}
        self.calib = self.load_calib()

        # 校准 / 驱动 / 歌曲 线程控制
        self.calibrating = False
        self.driving = False
        self.singing = False
        self.active_note = None       # 歌曲模式当前正在按下的音符通道
        self.freq = 0.0
        self.lock = threading.Lock()

        self._build_ui()
        self.root.after(120, self._refresh_labels)

    # ----------------- 校准文件 -----------------
    def load_calib(self):
        try:
            with open(CALIB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_calib(self):
        data = {}
        for sid in SERVO_IDS:
            st = self.state[sid]
            if st["cmin"] is not None and st["cmax"] is not None:
                data[str(sid)] = {"min": st["cmin"], "max": st["cmax"]}
        with open(CALIB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.calib = data

    # ----------------- 界面 -----------------
    def _build_ui(self):
        pad = {"padx": 6, "pady": 4}

        top = ttk.LabelFrame(self.root, text="串口连接")
        top.pack(fill="x", **pad)
        ttk.Label(top, text="串口:").grid(row=0, column=0, **pad)
        self.port_var = tk.StringVar(value="COM11")
        ttk.Entry(top, textvariable=self.port_var, width=8).grid(row=0, column=1, **pad)
        ttk.Label(top, text="波特率:").grid(row=0, column=2, **pad)
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        baud_box = ttk.Combobox(top, textvariable=self.baud_var, width=10,
                                values=[str(b) for b in (9600, 57600, 115200, 500000, 1000000)])
        baud_box.grid(row=0, column=3, **pad)
        self.connect_btn = ttk.Button(top, text="连接", command=self.toggle_connect)
        self.connect_btn.grid(row=0, column=4, **pad)
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(top, textvariable=self.status_var).grid(row=0, column=5, **pad)

        # 舵机状态表
        table = ttk.LabelFrame(self.root, text="舵机状态 (位置反馈)   ※ 1、2 号同在拇指上: 1=下压, 2=侧压, 两者协同=斜按")
        table.pack(fill="x", **pad)
        headers = ["ID", "作用", "当前位置", "校准最小", "校准最大", "范围"]
        for c, h in enumerate(headers):
            ttk.Label(table, text=h, font=("", 10, "bold")).grid(row=0, column=c, padx=10, pady=2)
        self.pos_labels = {}
        for r, sid in enumerate(SERVO_IDS, start=1):
            ttk.Label(table, text=str(sid)).grid(row=r, column=0, padx=10)
            ttk.Label(table, text=SERVO_ROLE[sid]).grid(row=r, column=1, padx=10)
            pos_lbl = ttk.Label(table, text="--", width=10)
            pos_lbl.grid(row=r, column=2, padx=10)
            self.pos_labels[sid] = pos_lbl
            for c, key in enumerate(("cmin", "cmax"), start=3):
                lbl = ttk.Label(table, text="--", width=10)
                lbl.grid(row=r, column=c, padx=10)
                self.pos_labels[f"{sid}_{key}"] = lbl
            rng_lbl = ttk.Label(table, text="--", width=10)
            rng_lbl.grid(row=r, column=5, padx=10)
            self.pos_labels[f"{sid}_rng"] = rng_lbl
            # 若已有历史校准则恢复显示
            rec = self.calib.get(str(sid))
            if rec:
                self.state[sid]["cmin"] = rec["min"]
                self.state[sid]["cmax"] = rec["max"]

        # 校准区
        cal = ttk.LabelFrame(self.root, text="校准")
        cal.pack(fill="x", **pad)
        self.calib_btn = ttk.Button(cal, text=f"开始校准 ({CALIB_SECONDS}s)", command=self.start_calib, state="disabled")
        self.calib_btn.pack(side="left", **pad)
        self.calib_status = tk.StringVar(value="校准前请确认: 全部手指处于可自由活动状态")
        ttk.Label(cal, textvariable=self.calib_status).pack(side="left", **pad)

        # 驱动区
        drv = ttk.LabelFrame(self.root, text="驱动模式 (活动范围 80% 正弦往复, 拇指两个舵机同相位协同)")
        drv.pack(fill="x", **pad)
        ttk.Label(drv, text="目标:").pack(side="left", **pad)
        self.target_var = tk.StringVar(value="全部手指")
        ttk.Combobox(drv, textvariable=self.target_var, width=16, state="readonly",
                     values=["全部手指"] + [a[0] for a in ACTUATORS]
                     ).pack(side="left", **pad)
        ttk.Label(drv, text="频率:").pack(side="left", **pad)
        self.freq_var = tk.DoubleVar(value=1.0)
        for f in (0, 1, 2, 3, 4, 5, 6):
            ttk.Radiobutton(drv, text=f"{f} Hz", value=float(f),
                            variable=self.freq_var,
                            command=lambda: setattr(self, "freq", self.freq_var.get())
                            ).pack(side="left", padx=2)
        self.freq = self.freq_var.get()
        self.drive_btn = ttk.Button(drv, text="开始驱动", command=self.toggle_drive, state="disabled")
        self.drive_btn.pack(side="left", **pad)

        # 歌曲区
        song = ttk.LabelFrame(self.root, text="歌曲模式 (按节奏驱动手指, 高亮 = 正在按下)")
        song.pack(fill="x", **pad)
        ttk.Label(song, text="曲目:").pack(side="left", **pad)
        self.song_var = tk.StringVar(value=list(SONGS.keys())[0])
        ttk.Combobox(song, textvariable=self.song_var, width=12,
                     values=list(SONGS.keys()), state="readonly").pack(side="left", **pad)
        ttk.Label(song, text="速度:").pack(side="left", **pad)
        self.bpm_var = tk.IntVar(value=100)
        ttk.Spinbox(song, from_=40, to=180, increment=5, width=5,
                    textvariable=self.bpm_var).pack(side="left", **pad)
        ttk.Label(song, text="BPM").pack(side="left")
        self.song_btn = ttk.Button(song, text="开始播放", command=self.toggle_song, state="disabled")
        self.song_btn.pack(side="left", **pad)
        # 音符指示灯 (高亮 = 当前正在按下的音符通道)
        self.ind_labels = {}
        for note in (1, 2, 3, 4, 5, 6):
            lbl = tk.Label(song, text=ACTION_LABELS[note], relief="groove",
                           width=17, bg="#f0f0f0", fg="#333333", font=("", 9))
            lbl.pack(side="left", padx=2)
            self.ind_labels[note] = lbl

        # 底部操作
        bot = ttk.Frame(self.root)
        bot.pack(fill="x", **pad)
        self.torque_btn = ttk.Button(bot, text="全部扭矩使能", command=lambda: self.torque_all(True), state="disabled")
        self.torque_btn.pack(side="left", **pad)
        self.center_btn = ttk.Button(bot, text="回到中位", command=self.go_center, state="disabled")
        self.center_btn.pack(side="left", **pad)
        stop = ttk.Button(bot, text="急 停 (关闭全部扭矩)", command=self.emergency_stop)
        stop.pack(side="left", **pad)

    # ----------------- 连接 -----------------
    def toggle_connect(self):
        if not self.connected:
            try:
                bus = ServoBus(self.port_var.get().strip(), int(self.baud_var.get()))
                bus.connect()
                bus.read_position(SERVO_IDS[0])  # 探测总线
                self.bus = bus
                self.connected = True
                self.status_var.set(f"已连接 {self.port_var.get()} @ {self.baud_var.get()}")
                self.connect_btn.config(text="断开")
                for b in (self.calib_btn, self.torque_btn, self.center_btn):
                    b.config(state="normal")
                threading.Thread(target=self._pos_poll_loop, daemon=True).start()
            except Exception as e:
                messagebox.showerror("连接失败", str(e))
        else:
            self.emergency_stop(silent=True)
            self.singing = False
            self.driving = False
            self.bus.close()
            self.connected = False
            self.status_var.set("未连接")
            self.connect_btn.config(text="连接")
            self.drive_btn.config(text="开始驱动", state="disabled")
            self.calib_btn.config(state="disabled")
            self.torque_btn.config(state="disabled")
            self.center_btn.config(state="disabled")

    def _pos_poll_loop(self):
        """后台实时读取位置反馈 (~15 Hz)。"""
        while self.connected:
            for sid in SERVO_IDS:
                try:
                    self.state[sid]["pos"] = self.bus.read_position(sid)
                except Exception:
                    self.state[sid]["pos"] = None
            time.sleep(0.06)

    # ----------------- 校准 -----------------
    def start_calib(self):
        if self.calibrating or not self.connected:
            return
        self.calibrating = True
        self.calib_btn.config(state="disabled")
        self.drive_btn.config(state="disabled")
        threading.Thread(target=self._calib_thread, daemon=True).start()

    def _calib_thread(self):
        try:
            self._set_status("正在关闭扭矩, 请用手自由活动所有手指...")
            for sid in SERVO_IDS:
                self.bus.set_torque(sid, False)
            self._set_status(f"校准中! 请在 {CALIB_SECONDS} 秒内做全范围活动...")

            mins = {sid: None for sid in SERVO_IDS}
            maxs = {sid: None for sid in SERVO_IDS}
            t0 = time.perf_counter()
            n = 0
            while time.perf_counter() - t0 < CALIB_SECONDS:
                for sid in SERVO_IDS:
                    try:
                        p = self.bus.read_position(sid)
                    except Exception:
                        continue
                    mins[sid] = p if mins[sid] is None else min(mins[sid], p)
                    maxs[sid] = p if maxs[sid] is None else max(maxs[sid], p)
                n += 1
                self.root.after(0, self._update_calib_labels, dict(mins), dict(maxs))
                time.sleep(1.0 / SAMPLE_HZ)

            ok = True
            for sid in SERVO_IDS:
                if mins[sid] is None or (maxs[sid] - mins[sid]) < 50:
                    ok = False
                    self._set_status(f"[{SERVO_ROLE[sid]} {sid}号] 范围过小或无反馈, 请重新校准!")
            if ok:
                for sid in SERVO_IDS:
                    self.state[sid]["cmin"], self.state[sid]["cmax"] = mins[sid], maxs[sid]
                self.save_calib()
                self._set_status(f"校准完成, 已保存到 {os.path.basename(CALIB_FILE)}。可以开始驱动。")
                self.root.after(0, self._update_calib_labels, mins, maxs)
        except Exception as e:
            self._set_status(f"校准出错: {e}")
        finally:
            self.calibrating = False
            self.root.after(0, lambda: (self.calib_btn.config(state="normal"),
                                        self.drive_btn.config(state="normal")))

    def _update_calib_labels(self, mins, maxs):
        for sid in SERVO_IDS:
            if mins.get(sid) is not None and maxs.get(sid) is not None:
                self.state[sid]["cmin"], self.state[sid]["cmax"] = mins[sid], maxs[sid]
                self.pos_labels[f"{sid}_cmin"].config(text=str(mins[sid]))
                self.pos_labels[f"{sid}_cmax"].config(text=str(maxs[sid]))
                self.pos_labels[f"{sid}_rng"].config(text=str(maxs[sid] - mins[sid]))

    # ----------------- 位置计算工具 -----------------
    def _servo_range(self, sid):
        """返回 (中位, 80%行程的一半)。"""
        lo, hi = self.state[sid]["cmin"], self.state[sid]["cmax"]
        center = (lo + hi) / 2.0
        amp = (hi - lo) * RANGE_USE / 2.0
        return center, amp

    def _press_target(self, sid, depth=1.0):
        """按下目标位置: 从中位朝最小位置方向走 depth 比例的最大行程。"""
        center, amp = self._servo_range(sid)
        return int(round(center - amp * depth))

    def _lift_target(self, sid):
        """抬起位置(回中偏上, 手指伸直但不顶死)。"""
        center, amp = self._servo_range(sid)
        return int(round(center + amp))

    def _selected_servo_depths(self):
        """驱动模式: 返回 {舵机ID: 行程比例}。选「拇指」时 1、2 号一起动(斜按轨迹)。"""
        target = self.target_var.get()
        if target == "全部手指":
            chosen = [s for _, servos in ACTUATORS for s in servos]
        else:
            chosen = [s for name, servos in ACTUATORS if name == target for s in servos]
        return {sid: (LATERAL_RATIO if sid == 2 else 1.0) for sid in chosen}

    # ----------------- 驱动 -----------------
    def toggle_drive(self):
        if not self.driving:
            ready = all(self.state[sid]["cmin"] is not None for sid in SERVO_IDS)
            if not ready:
                messagebox.showwarning("未校准", "请先完成校准(6 个舵机都需要有效范围)。")
                return
            self.freq = self.freq_var.get()
            self.driving = True
            self.drive_btn.config(text="停止驱动")
            self.calib_btn.config(state="disabled")
            threading.Thread(target=self._drive_thread, daemon=True).start()
        else:
            self.driving = False

    def _drive_thread(self):
        try:
            depths = self._selected_servo_depths()
            for sid in depths:
                self.bus.set_torque(sid, True)
            self._set_status(f"驱动 [{self.target_var.get()}] 中, 频率 {self.freq:.0f} Hz (0 Hz = 保持中位)")
            t0 = time.perf_counter()
            while self.driving:
                f = self.freq
                t = time.perf_counter() - t0
                for sid, depth in depths.items():
                    center, amp = self._servo_range(sid)
                    if f <= 0:
                        target = center
                    else:
                        target = center + amp * depth * math.sin(2 * math.pi * f * t)
                    try:
                        self.bus.write_position(sid, int(round(target)))
                    except Exception as e:
                        self._set_status(f"驱动写位置失败: {e}")
                        self.driving = False
                        break
                time.sleep(1.0 / DRIVE_LOOP_HZ)
        except Exception as e:
            self._set_status(f"驱动出错: {e}")
        finally:
            try:
                for sid in SERVO_IDS:
                    self.bus.set_torque(sid, False)
            except Exception:
                pass
            self.driving = False
            self._set_status("驱动已停止, 扭矩已关闭。")
            self.root.after(0, lambda: (self.drive_btn.config(text="开始驱动", state="normal"),
                                        self.calib_btn.config(state="normal")))

    def go_center(self):
        try:
            for sid in SERVO_IDS:
                lo, hi = self.state[sid]["cmin"], self.state[sid]["cmax"]
                if lo is None:
                    continue
                self.bus.set_torque(sid, True)
                self.bus.write_position(sid, int((lo + hi) / 2))
            self._set_status("已回中位 (扭矩保持使能, 可点急停释放)。")
        except Exception as e:
            self._set_status(f"回中位失败: {e}")

    # ----------------- 歌曲模式 -----------------
    def toggle_song(self):
        if not self.singing:
            ready = all(self.state[sid]["cmin"] is not None for sid in SERVO_IDS)
            if not ready:
                messagebox.showwarning("未校准", "请先完成校准(6 个舵机都需要有效范围)。")
                return
            self.singing = True
            self.song_btn.config(text="停止播放")
            self.drive_btn.config(state="disabled")
            self.calib_btn.config(state="disabled")
            threading.Thread(target=self._song_thread, daemon=True).start()
        else:
            self.singing = False

    def _song_thread(self):
        try:
            song = SONGS[self.song_var.get()]
            beat = 60.0 / max(40, self.bpm_var.get())   # 一拍的秒数

            # 全部手指先抬起
            lift = {sid: self._lift_target(sid) for sid in SERVO_IDS}
            for sid in SERVO_IDS:
                self.bus.set_torque(sid, True)
                self.bus.write_position(sid, lift[sid])
            self._set_status(f"播放《{self.song_var.get()}》, {self.bpm_var.get()} BPM "
                             f"(拇指直按=do, 拇指斜按=re 由 1+2 号协同)")

            for note, beats in song:
                if not self.singing:
                    break
                dur = beats * beat
                actions = NOTE_ACTIONS.get(note, {})
                if actions:
                    # 该音符涉及的所有舵机同时下压(深度可不同)
                    self.active_note = note
                    for sid, depth in actions.items():
                        self.bus.write_position(sid, self._press_target(sid, depth))
                # 分段休眠, 便于随时停止
                end = time.perf_counter() + dur
                while self.singing and time.perf_counter() < end:
                    time.sleep(0.02)
                for sid in actions:
                    self.bus.write_position(sid, lift[sid])
                self.active_note = None
        except Exception as e:
            self._set_status(f"播放出错: {e}")
        finally:
            self.singing = False
            self.active_note = None
            try:
                for sid in SERVO_IDS:
                    lo, hi = self.state[sid]["cmin"], self.state[sid]["cmax"]
                    self.bus.write_position(sid, int((lo + hi) / 2))  # 回中
                    self.bus.set_torque(sid, False)
            except Exception:
                pass
            self._set_status("播放结束, 扭矩已关闭。")
            self.root.after(0, lambda: (self.song_btn.config(text="开始播放", state="normal"),
                                        self.drive_btn.config(state="normal"),
                                        self.calib_btn.config(state="normal")))

    # ----------------- 通用 -----------------
    def torque_all(self, on: bool):
        try:
            for sid in SERVO_IDS:
                self.bus.set_torque(sid, on)
            self._set_status("扭矩已全部使能" if on else "扭矩已全部关闭")
            if on:
                self.torque_btn.config(text="全部扭矩关闭", command=lambda: self.torque_all(False))
            else:
                self.torque_btn.config(text="全部扭矩使能", command=lambda: self.torque_all(True))
        except Exception as e:
            self._set_status(f"扭矩操作失败: {e}")

    def emergency_stop(self, silent=False):
        self.driving = False
        if self.connected and self.bus:
            try:
                for sid in SERVO_IDS:
                    self.bus.set_torque(sid, False)
                if not silent:
                    self._set_status("急停! 全部扭矩已关闭。")
            except Exception:
                pass

    def _set_status(self, text):
        self.root.after(0, lambda: self.calib_status.set(text))

    def _refresh_labels(self):
        for sid in SERVO_IDS:
            p = self.state[sid]["pos"]
            pct = ""
            lo, hi = self.state[sid]["cmin"], self.state[sid]["cmax"]
            if p is not None and lo is not None and hi > lo:
                pct = f"  {100.0 * (p - lo) / (hi - lo):.0f}%"
            self.pos_labels[sid].config(text=(f"{p}{pct}" if p is not None else "--"))
        # 音符指示灯: 正在按下的通道高亮
        for note, lbl in self.ind_labels.items():
            if self.singing and self.active_note == note:
                lbl.config(bg="#ff8a65", fg="white")
            else:
                lbl.config(bg="#f0f0f0", fg="#333333")
        self.root.after(120, self._refresh_labels)


def main():
    root = tk.Tk()
    GloveApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

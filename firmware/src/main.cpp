// 钢琴手套 · 主控固件（自研 PIANO_GLOVE_2）
//
// 设计目标：
//   1. 与原厂 PIANO_GLOVE_1 的文本协议**逐命令兼容** —— host/web_piano_glove.html
//      和 host/glove_fw.py 不用改一行就能用
//   2. 拿掉原厂每条命令固定约 103 ms 的等待窗口（它把吞吐锁在 9.9 条/秒，
//      而 6 指 6 Hz 需要 72 条/秒）
//   3. 补上原厂没有的板载扫频命令 SWEEP（行程百分比 + 频率 + 时长）
//   4. ENROLL 改成真正可用的状态机：总线必须被清空才允许插下一个舵机，
//      不再出现 assign_log.txt 里那种 "总线上还有 [1] —— 请把它拔下来" 的死循环

#include <Arduino.h>
#include <stdarg.h>

#include "glove.h"
#include "scs_bus.h"

#define FW_ID  "PIANO_GLOVE_2"
#define FW_VER "2.1.2"     // 2.1.2: 静止位改回「松开端」（原来被设成量程中点，按压只有半个行程）
                           //        + MOVE 越界安全闸（防"转到不该去的地方卡住"）
                           //        + CAL ALIGN 修正存量校准
                           // 2.1.1: 修「编号时 remapId 把已编好的槽位一起改掉」+ sendRecv 的 pkt[32] 栈溢出

// 串口接收环形缓冲。Arduino 默认只有 256 B（115200 下 ≈ 22 ms 余量），
// 扛不住上位机一次连发几十条命令，放大到 4 KB。详见 setup() 里的说明。
#define UART_RX_BUF 4096

// ---------------------------------------------------------------- 输出

static void sayf(const char *fmt, ...) {
  char    b[384];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(b, sizeof(b), fmt, ap);
  va_end(ap);
  Serial.println(b);
}
static void okf(const char *fmt, ...) {
  char    b[384];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(b, sizeof(b), fmt, ap);
  va_end(ap);
  Serial.print("OK ");
  Serial.println(b);
}
static void errf(const char *fmt, ...) {
  char    b[384];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(b, sizeof(b), fmt, ap);
  va_end(ap);
  Serial.print("ERR ");
  Serial.println(b);
}

static int bitcount(uint8_t m) {
  int n = 0;
  while (m) {
    n += (m & 1);
    m >>= 1;
  }
  return n;
}

// ---------------------------------------------------------------- 行接收统计

// 在 setup() 里定义，命令分发（BUSINFO）要读它，所以前置声明。
static uint32_t g_rxDrop;

// ---------------------------------------------------------------- ENROLL 状态机

static bool        g_enroll        = false;
static uint8_t     g_enrollNext    = 1;
static const char *g_enrollPhase   = "OFF";
static uint32_t    g_enrollTickMs  = 0;

static void enrollTick(uint32_t now) {
  if (!g_enroll) return;
  if (now - g_enrollTickMs < 500) return;
  g_enrollTickMs = now;

  uint8_t     found[12];
  const int   c = scs::scan(10, found, 12);

  if (c == 0) {                                  // 总线是空的
    if (strcmp(g_enrollPhase, "ASSIGNED") == 0) {
      ++g_enrollNext;
      if (g_enrollNext > glove::SLOT_COUNT) {
        g_enrollPhase = "DONE";
        g_enroll      = false;
        sayf("ENROLL DONE assigned=%d", glove::SLOT_COUNT);
        return;
      }
    }
    g_enrollPhase = "WAIT_EMPTY";
    return;
  }
  if (c > 1) {                                   // 多个舵机同时在线
    g_enrollPhase = "CONFLICT";
    return;
  }

  const uint8_t cur  = found[0];
  const int     slot = (int)g_enrollNext - 1;      // 第 N 轮 -> 槽位 N-1

  // ⚠️ 这里**必须**用 setMap(slot, id) 明确"这一轮填哪个槽位"，
  //    不能用 glove::remapId() —— 那个是给 SETID 命令用的
  //    （"某块舵机的号变了，把指向它的槽位跟着改"）。
  //
  //    编号流程里每轮插上的都是**新的出厂舵机，出厂号全是 1**，
  //    于是第 2 轮就会调 remapId(1, 2)，把**第 1 轮已经填好的槽位 0**
  //    （它也存着 1）一起改成 2 —— 结果 6 轮跑完得到 [2,2,3,4,5,6]，
  //    槽位 0 和槽位 1 指向同一块舵机，id=1 那块永远不动。
  //    界面还会显示"编号完成"，一点错都看不出来。（这个坑踩过）
  if (cur == g_enrollNext) {                       // 正好是目标号，不用改号
    glove::setMap(slot, g_enrollNext);             // 但映射无论如何都要写
    g_enrollPhase = "ASSIGNED";
    sayf("ENROLL ASSIGNED id=%u slot=%d (号已正确)", (unsigned)g_enrollNext, slot);
    return;
  }
  if (scs::setId(cur, g_enrollNext)) {
    glove::setMap(slot, g_enrollNext);
    g_enrollPhase = "ASSIGNED";
    sayf("ENROLL ASSIGNED id=%u slot=%d was=%u", (unsigned)g_enrollNext, slot, (unsigned)cur);
  } else {
    g_enrollPhase = "FAILED";
  }
}

// ---------------------------------------------------------------- 槽位行输出

// 槽位行必须**单行**输出，且在线字段插在 online= 与 min= 之间 ——
// 上位机只解析以 "SLOT" 开头的行，换行会把 pos 丢掉。
static void printSlotLine(int s, const scs::Feedback *fb) {
  const glove::Slot &sl = glove::slot(s);
  const bool         on = (fb && fb->ok);
  char               b[320];

  if (on) {
    snprintf(b, sizeof(b),
             "SLOT slot=%d name=%s id=%u online=1 pos=%d speed=%d load=%d voltage_raw=%u "
             "temperature=%u current=%d min=%u standby=%u max=%u valid=%d press=%s",
             s, glove::name(s), (unsigned)sl.id, (int)fb->pos, (int)fb->speed, (int)fb->load,
             (unsigned)fb->voltage, (unsigned)fb->temp, (int)fb->current,
             (unsigned)sl.lo, (unsigned)sl.standby, (unsigned)sl.hi,
             sl.valid ? 1 : 0, (sl.dir == glove::DIR_PRESS_MAX) ? "max" : "min");
  } else {
    snprintf(b, sizeof(b),
             "SLOT slot=%d name=%s id=%u online=0 min=%u standby=%u max=%u valid=%d press=%s",
             s, glove::name(s), (unsigned)sl.id,
             (unsigned)sl.lo, (unsigned)sl.standby, (unsigned)sl.hi,
             sl.valid ? 1 : 0, (sl.dir == glove::DIR_PRESS_MAX) ? "max" : "min");
  }
  sayf("%s", b);
}

static void printCalLine(int s) {
  const glove::Slot &sl = glove::slot(s);
  sayf("CAL slot=%d name=%s id=%u min=%u standby=%u max=%u valid=%d press=%s",
       s, glove::name(s), (unsigned)sl.id, (unsigned)sl.lo, (unsigned)sl.standby,
       (unsigned)sl.hi, sl.valid ? 1 : 0,
       (sl.dir == glove::DIR_PRESS_MAX) ? "max" : "min");
}

// ---------------------------------------------------------------- 命令实现

static void cmdInfo() {
  sayf("OK INFO fw=%s profile=STS3032 range=4095 ap=PIANO_GLOVE_A50528 ip=192.168.4.1 "
       "calibrated=%d armed=%d auto_active=%d enroll_active=%d enroll_next=%d enroll_temp=10 "
       "enroll_phase=%s online=%d sweep=%d ver=%s",
       FW_ID, glove::calibrated() ? 1 : 0, glove::armed() ? 1 : 0, glove::autoActive() ? 1 : 0,
       g_enroll ? 1 : 0, (unsigned)g_enrollNext, g_enrollPhase,
       bitcount(glove::onlineMask()), glove::sweepActive() ? 1 : 0, FW_VER);
}

static void cmdStatusAll() {
  for (int s = 0; s < glove::SLOT_COUNT; ++s) {
    scs::Feedback fb;
    glove::slot(s).online = scs::readFeedback(glove::slot(s).id, fb);
    if (fb.ok) glove::slot(s).last = fb.pos;
    printSlotLine(s, fb.ok ? &fb : nullptr);
  }
  okf("STATUS_ALL profile=STS3032 armed=%d online=%d", glove::armed() ? 1 : 0,
      bitcount(glove::onlineMask()));
}

static void cmdAuto() {
  sayf("AUTO_BEGIN ids=1-6 attempts=3");
  bool     present[7] = {false};
  uint8_t  ids[8];
  int      nid = 0;
  for (uint8_t id = 1; id <= 6; ++id) {
    present[id] = scs::ping(id);
    if (present[id]) ids[nid++] = id;
    sayf("AUTO_ID id=%u pings=%d identity=%d type=%s", (unsigned)id, present[id] ? 1 : 0,
         present[id] ? 1 : -1, present[id] ? "STS" : "none");
  }
  char idList[48] = "none", missList[48] = "";
  if (nid) {
    int k = 0;
    for (int i = 0; i < nid; ++i) k += snprintf(idList + k, sizeof(idList) - k, "%s%u", i ? "," : "", (unsigned)ids[i]);
  }
  {
    int k = 0;
    for (uint8_t id = 1; id <= 6; ++id)
      if (!present[id]) k += snprintf(missList + k, sizeof(missList) - k, "%s%u", k ? "," : "", (unsigned)id);
    if (!k) snprintf(missList, sizeof(missList), "none");
  }
  sayf("AUTO_PROFILE name=STS3032 found=%d ids=%s missing=%s unstable=none", nid, idList, missList);
  sayf("AUTO_RESULT profile=STS3032 found=%d ready=%d action=%s", nid, (nid == 6) ? 1 : 0,
       (nid == 6) ? "none" : "check_power_wiring_unique_ids_or_protocol");
  okf("AUTO profile=STS3032 ready=%d range=4095", (nid == 6) ? 1 : 0);
}

static void cmdCal(const int n, char **t) {
  if (n < 2) {
    errf("CAL subcommand_unknown");
    return;
  }
  char sub[16];
  strncpy(sub, t[1], sizeof(sub) - 1);
  sub[sizeof(sub) - 1] = 0;
  for (char *p = sub; *p; ++p) *p = (char)toupper((unsigned char)*p);

  if (strcmp(sub, "STATUS") == 0) {
    for (int s = 0; s < glove::SLOT_COUNT; ++s) printCalLine(s);
    const int v = glove::calValidCount();
    okf("CAL count=%d complete=%d", v, (v == glove::SLOT_COUNT) ? 1 : 0);
    return;
  }
  if (strcmp(sub, "CLEAR") == 0) {
    glove::calClear();
    glove::torqueAll(false);
    okf("CAL CLEAR torque=off");
    return;
  }
  if (strcmp(sub, "CAPTURE") == 0) {
    if (n < 6) {
      errf("CAL CAPTURE usage_slot_MIN_STANDBY_MAX");
      return;
    }
    const int s = atoi(t[2]);
    if (s < 0 || s >= glove::SLOT_COUNT) {
      errf("CAL CAPTURE usage_slot_MIN_STANDBY_MAX");
      return;
    }
    if (!glove::refresh(s)) {
      errf("CAL CAPTURE servo_read_failed");
      return;
    }
    glove::calCapture(s, (uint16_t)atoi(t[3]), (uint16_t)atoi(t[4]), (uint16_t)atoi(t[5]));
    okf("CAL CAPTURE slot=%d", s);
    return;
  }
  if (strcmp(sub, "ALIGN") == 0) {
    // 把静止位对齐到「松开端」—— 修 2.1.1 及更早的自动校准留下的量程中点，
    // 不用重做采样。上位机第 3 步也可以一键调用。
    // snapStandby() 内部有改动时会自己持久化。
    const uint8_t fixed = glove::snapStandby();
    okf("CAL ALIGN fixed_mask=0x%02X standby_moved_to_release_end", (unsigned)fixed);
    return;
  }
  if (strcmp(sub, "SAVE") == 0) {
    const int bad = glove::calInvalidSlot();
    if (bad >= 0) {
      errf("CAL incomplete_slot=%d", bad);
      return;
    }
    glove::calSave();
    okf("CAL SAVE calibrated=1");
    return;
  }
  if (strcmp(sub, "AUTO") == 0) {
    if (n < 3) {
      errf("CAL subcommand_unknown");
      return;
    }
    char a[16];
    strncpy(a, t[2], sizeof(a) - 1);
    a[sizeof(a) - 1] = 0;
    for (char *p = a; *p; ++p) *p = (char)toupper((unsigned char)*p);

    if (strcmp(a, "START") == 0) {
      for (int s = 0; s < glove::SLOT_COUNT; ++s) {
        if (!glove::refresh(s)) {
          errf("CAL AUTO feedback_missing_slot=%d_id=%u fix_ids_or_wiring_first", s,
               (unsigned)glove::slot(s).id);
          return;
        }
      }
      glove::autoStart();
      okf("CAL AUTO START");
      return;
    }
    if (strcmp(a, "STATUS") == 0) {
      for (int s = 0; s < glove::SLOT_COUNT; ++s) {
        sayf("CAL_AUTO slot=%d samples=%u min=%u max=%u last=%d", s,
             (unsigned)glove::autoSamples(s), (unsigned)glove::autoMin(s),
             (unsigned)glove::autoMax(s), (int)glove::autoLast(s));
      }
      okf("CAL AUTO STATUS active=%d", glove::autoActive() ? 1 : 0);
      return;
    }
    if (strcmp(a, "FINISH") == 0) {
      glove::autoFinish();
      glove::torqueAll(false);
      okf("CAL AUTO FINISH torque=off");
      return;
    }
    if (strcmp(a, "CANCEL") == 0) {
      glove::autoCancel();
      glove::torqueAll(false);
      okf("CAL AUTO CANCEL torque=off");
      return;
    }
    errf("CAL subcommand_unknown");
    return;
  }
  errf("CAL subcommand_unknown");
}

// 槽位选择参数：0 / all = 全部 6 个；0x3F = 位掩码；1..6 = 单个槽位（1 起）。
// 返回 0 表示参数非法或没选中任何槽位 —— 调用方据此报错。
static uint8_t parseMask(const char *a) {
  uint8_t mask = 0;
  if (strcasecmp(a, "all") == 0 || strcmp(a, "0") == 0) {
    mask = 0x3F;
  } else if (a[0] == '0' && (a[1] == 'x' || a[1] == 'X')) {
    mask = (uint8_t)strtol(a + 2, nullptr, 16);
  } else {
    const int s = atoi(a);
    if (s < 1 || s > (int)glove::SLOT_COUNT) return 0;
    mask = (uint8_t)(1 << (s - 1));
  }
  return (uint8_t)(mask & 0x3F);
}

static void cmdSweep(const int n, char **t) {
  if (n >= 2 && strcasecmp(t[1], "STOP") == 0) {
    glove::sweepStop();
    okf("SWEEP STOP");
    return;
  }
  if (n < 5) {                                   // 无参 -> 报状态
    if (n == 1) {
      okf("SWEEP active=%d freq_mhz=%u depth=%u elapsed_ms=%u", glove::sweepActive() ? 1 : 0,
          (unsigned)glove::sweepFreqMilliHz(), (unsigned)glove::sweepDepth(),
          (unsigned)glove::sweepElapsedMs());
      return;
    }
    errf("SWEEP usage_slots_freq_mhz_depth_duration_ms_speed_acc");
    return;
  }

  // 1) 参与的槽位：0/all = 全部；1..6 = 单槽（1 起）；0x3F = 位掩码
  const uint8_t mask = parseMask(t[1]);
  if (!mask) {
    errf("SWEEP bad_slot");
    return;
  }

  const unsigned freq  = (unsigned)atol(t[2]);        // 0.001 Hz 单位：6000 = 6 Hz
  const unsigned depth = (unsigned)atol(t[3]);
  const unsigned dur   = (unsigned)atol(t[4]);
  const unsigned speed = (n >= 6) ? (unsigned)atol(t[5]) : 0;
  const unsigned acc   = (n >= 7) ? (unsigned)atol(t[6]) : 0;

  if (freq == 0 || freq > 20000 || depth == 0 || depth > 100 || dur == 0) {
    errf("SWEEP bad_args");
    return;
  }
  if (!glove::sweepStart(mask, (uint16_t)freq, (uint8_t)depth, (uint32_t)dur,
                         (uint16_t)speed, (uint8_t)acc)) {
    int off = -1;
    for (int s = 0; s < glove::SLOT_COUNT; ++s)
      if ((mask & (1 << s)) && !glove::slot(s).online) { off = s; break; }
    if (off >= 0) errf("SWEEP slot_offline=%d_id=%u", off, (unsigned)glove::slot(off).id);
    else          errf("SWEEP bad_args");
    return;
  }
  okf("SWEEP slots=%d freq_mhz=%u depth=%u dur_ms=%u speed=%u acc=%u", mask, freq, depth, dur,
      speed, acc);
}

// SETID <old> <new> CONFIRM [slot]
//
// 两种语义，靠最后那个可选 slot 区分：
//   不给 slot —— 「修号」：某块舵机的号变了，把**指向它的槽位**跟着改（remapId）。
//   给   slot —— 「编号向导」：这块刚插上来的舵机就归槽位 slot 了，
//               其它槽位一律不许动（setMap）。
//
// ⚠️ 为什么必须分两种：编号向导每轮插上来的都是**出厂新舵机，出厂号全是 1**。
//    第 2 轮发 SETID 1 2 时，如果按"修号"语义走 remapId(1,2)，
//    就会把第 1 轮已经填好的槽位 0（它也存着 1）一起改成 2 ——
//    6 轮跑完得到 [2,2,3,4,5,6]，槽位 0 和 1 指向同一块舵机，
//    1 号那块永远不动，而界面显示"编号全部完成"。（这个坑踩过）
static void cmdSetId(const int n, char **t) {
  if (n < 4 || strcasecmp(t[3], "CONFIRM") != 0) {
    errf("SETID usage_old_new_CONFIRM_[slot]");
    return;
  }
  const int oldId = atoi(t[1]), newId = atoi(t[2]);
  if (oldId < 0 || oldId > 253 || newId < 1 || newId > 253) {
    errf("SETID usage_old_new_CONFIRM_[slot]");
    return;
  }
  const bool hasSlot = (n >= 5);
  const int  slot    = hasSlot ? atoi(t[4]) : -1;
  if (hasSlot && (slot < 0 || slot >= glove::SLOT_COUNT)) {
    errf("SETID bad_slot=%d", slot);
    return;
  }
  if (!scs::ping((uint8_t)oldId)) {
    errf("SETID old_not_found");
    return;
  }
  if (scs::ping((uint8_t)newId)) {
    errf("SETID new_id_occupied");
    return;
  }
  if (!scs::setId((uint8_t)oldId, (uint8_t)newId)) {
    errf("SETID write_or_verify_failed");
    return;
  }
  if (hasSlot) {
    glove::setMap(slot, (uint8_t)newId);       // 只认这一块，别碰别的槽位
    okf("SETID old_id=%d new_id=%d slot=%d mode=guide", oldId, newId, slot);
  } else {
    glove::remapId((uint8_t)oldId, (uint8_t)newId);
    okf("SETID old_id=%d new_id=%d mode=repair", oldId, newId);
  }
}

static void cmdLine(char *raw) {
  char  buf[256];
  strncpy(buf, raw, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = 0;

  char *t[8];
  int   n = 0;
  char *p = buf;
  while (*p && n < 8) {
    while (*p == ' ' || *p == '\t') ++p;
    if (!*p) break;
    t[n++] = p;
    while (*p && *p != ' ' && *p != '\t') ++p;
    if (*p) *p++ = 0;
  }
  if (n == 0) return;

  glove::markCommand();          // 让后台轮询让出总线，别和前台命令抢

  char v[16];
  strncpy(v, t[0], sizeof(v) - 1);
  v[sizeof(v) - 1] = 0;
  for (char *q = v; *q; ++q) *q = (char)toupper((unsigned char)*q);

  // ---- 全局 ----
  if (strcmp(v, "INFO") == 0)     { cmdInfo(); return; }
  if (strcmp(v, "HELP") == 0) {
    okf("HELP commands=%s",
        "INFO PROFILE PING SCAN STATUS STATUS_ALL MAP SETDIR SETID CAL TORQUE ARM DISARM SAFE "
        "STANDBY PRESS RELEASE MOVE DEMO SWEEP RATE PRESET AUTO ENROLL ECHO BUSINFO HELP");
    return;
  }
  if (strcmp(v, "BUSINFO") == 0) {
    const scs::Stats &st = scs::stats();
    okf("BUSINFO rx_pin=%d tx_pin=%d baud=%u echo=%d echo_bytes=%u timeout_ms=%u tx=%u rx=%u timeout=%u badsum=%u servo_err=%u rx_drop=%u",
        scs::RX_PIN, scs::TX_PIN, (unsigned)scs::BUS_BAUD, st.echo ? 1 : 0,
        (unsigned)st.echoBytes, (unsigned)scs::RESP_TIMEOUT_MS, (unsigned)st.tx,
        (unsigned)st.rx, (unsigned)st.timeout, (unsigned)st.badsum,
        (unsigned)st.servoErr, (unsigned)g_rxDrop);
    return;
  }
  if (strcmp(v, "ECHO") == 0) {
    if (n >= 2) scs::setEcho(atoi(t[1]) != 0);
    okf("ECHO enabled=%d echo_bytes=%u", scs::stats().echo ? 1 : 0,
        (unsigned)scs::stats().echoBytes);
    return;
  }
  if (strcmp(v, "PROFILE") == 0) {
    if (n >= 2 && strcasecmp(t[1], "STS3032") == 0) okf("PROFILE name=STS3032 range=4095");
    else errf("PROFILE must_be_SC09_or_STS3032");
    return;
  }
  if (strcmp(v, "PRESET") == 0) {
    if (n < 3) {
      okf("PRESET speed=%u acc=%u", (unsigned)glove::pressSpeed(), (unsigned)glove::pressAcc());
      return;
    }
    glove::setPressProfile((uint16_t)atoi(t[1]), (uint8_t)atoi(t[2]));
    okf("PRESET speed=%u acc=%u", (unsigned)glove::pressSpeed(), (unsigned)glove::pressAcc());
    return;
  }
  if (strcmp(v, "SCAN") == 0) {
    sayf("SCAN_BEGIN profile=STS3032 max=20");
    uint8_t found[24];
    const int c = scs::scan(20, found, 24);
    for (int i = 0; i < c; ++i) sayf("FOUND id=%u", (unsigned)found[i]);
    sayf("SCAN_END count=%d", c);
    return;
  }
  if (strcmp(v, "AUTO") == 0)     { cmdAuto(); return; }
  if (strcmp(v, "STATUS_ALL") == 0) { cmdStatusAll(); return; }

  // ---- 舵机级 ----
  if (strcmp(v, "PING") == 0) {
    if (n < 2) { errf("PING usage_id"); return; }
    const int id = atoi(t[1]);
    if (id >= 0 && id <= 253 && scs::ping((uint8_t)id)) okf("PING id=%d", id);
    else errf("PING id=%d", id);
    return;
  }
  if (strcmp(v, "STATUS") == 0) {
    if (n < 2) { errf("STATUS usage_id"); return; }
    const int id = atoi(t[1]);
    scs::Feedback fb;
    if (!scs::readFeedback((uint8_t)id, fb)) {
      errf("STATUS id=%d offline=1", id);
      return;
    }
    okf("STATUS id=%d profile=STS3032 pos=%d speed=%d load=%d voltage_raw=%u temperature=%u "
        "current=%d moving=%u mode=0",
        id, (int)fb.pos, (int)fb.speed, (int)fb.load, (unsigned)fb.voltage, (unsigned)fb.temp,
        (int)fb.current, (unsigned)fb.moving);
    return;
  }
  if (strcmp(v, "MAP") == 0) {
    if (n < 3) { errf("MAP usage_slot_id"); return; }
    const int s = atoi(t[1]), id = atoi(t[2]);
    if (!glove::setMap(s, (uint8_t)id)) { errf("MAP usage_slot_id"); return; }
    okf("MAP slot=%d id=%d", s, id);
    return;
  }
  if (strcmp(v, "SETDIR") == 0) {
    if (n < 3) { errf("SETDIR usage_slot_max_or_min"); return; }
    const int s = atoi(t[1]);
    if (s < 0 || s >= glove::SLOT_COUNT) { errf("SETDIR usage_slot_max_or_min"); return; }
    if (strcasecmp(t[2], "max") == 0)      glove::setDir(s, glove::DIR_PRESS_MAX);
    else if (strcasecmp(t[2], "min") == 0) glove::setDir(s, glove::DIR_PRESS_MIN);
    else { errf("SETDIR usage_slot_max_or_min"); return; }
    okf("SETDIR slot=%d press=%s", s, (glove::slot(s).dir == glove::DIR_PRESS_MAX) ? "max" : "min");
    return;
  }
  if (strcmp(v, "SETID") == 0) { cmdSetId(n, t); return; }
  if (strcmp(v, "TORQUE") == 0) {
    if (n < 3) { errf("TORQUE usage_slot_or_id_0_or_1"); return; }
    const int target = atoi(t[1]);
    const int on     = atoi(t[2]);
    if ((on != 0 && on != 1) || target < 0) { errf("TORQUE usage_slot_or_id_0_or_1"); return; }
    if (target == 0) {
      glove::torqueAll(on != 0);
    } else if (target >= 1 && target <= glove::SLOT_COUNT) {
      glove::torqueSlot(target - 1, on != 0);
    } else {
      scs::setTorque((uint8_t)target, on != 0);
    }
    okf("TORQUE target=%d enabled=%d", target, on);
    return;
  }

  // ---- 动作级 ----
  if (strcmp(v, "CAL") == 0) { cmdCal(n, t); return; }
  if (strcmp(v, "SWEEP") == 0) { cmdSweep(n, t); return; }
  if (strcmp(v, "RATE") == 0) {
    // RATE <slots> <speed> <acc> <depth%> [cycles]
    //   一次完整行程 = 最小 → 最大 → 最小。跑完自动打 RATE_DONE。
    if (n < 2) {
      // 不带参数 = 查状态
      okf("RATE active=%d done=%u/%u half_ms=%.1f slow_ms=%.1f lost=%u",
          glove::rateActive() ? 1 : 0, (unsigned)glove::rateDone(),
          (unsigned)glove::rateCycles(), glove::rateHalfUs() / 1000.0f,
          glove::rateSlowUs() / 1000.0f, (unsigned)glove::rateLost());
      return;
    }
    if (strcasecmp(t[1], "STOP") == 0) {
      glove::rateStop();
      okf("RATE stopped");
      return;
    }
    const uint8_t  mask  = parseMask(t[1]);
    if (mask == 0) { errf("RATE no_slot_selected_or_offline"); return; }
    const uint16_t speed = (n >= 3) ? (uint16_t)atol(t[2]) : 0;
    const uint8_t  acc   = (n >= 4) ? (uint8_t)atol(t[3]) : 0;
    const uint8_t  depth = (n >= 5) ? (uint8_t)atoi(t[4]) : 100;
    const uint16_t cyc   = (n >= 6) ? (uint16_t)atoi(t[5]) : 3;

    const int bad = glove::rateBadSlot(mask, depth);
    if (bad >= 0) {
      errf("RATE stroke_too_small slot=%d (先做第 3 步校准，或把 depth 调大)", bad);
      return;
    }
    if (!glove::rateStart(mask, speed, acc, depth, cyc)) {
      errf("RATE start_failed slots=0x%02X (检查槽位是否在线)", (unsigned)mask);
      return;
    }
    okf("RATE_START slots=0x%02X speed=%u acc=%u depth=%u cycles=%u", (unsigned)mask,
        (unsigned)speed, (unsigned)acc, (unsigned)depth, (unsigned)cyc);
    return;
  }
  if (strcmp(v, "ARM") == 0) {
    if (!glove::calibrated()) { errf("ARM calibration_incomplete"); return; }
    glove::setArmed(true);
    glove::torqueAll(true);
    okf("ARM armed=1");
    return;
  }
  if (strcmp(v, "DISARM") == 0) {
    glove::setArmed(false);
    glove::torqueAll(false);
    okf("DISARM armed=0");
    return;
  }
  if (strcmp(v, "SAFE") == 0) {
    glove::sweepStop();
    glove::safe();
    okf("SAFE torque=off armed=0");
    return;
  }
  if (strcmp(v, "STANDBY") == 0) {
    if (n < 2 || strcasecmp(t[1], "CONFIRM") != 0) {
      errf("STANDBY requires_CONFIRM");
      return;
    }
    glove::safe();
    okf("STANDBY torque=off");
    return;
  }
  if (strcmp(v, "PRESS") == 0 || strcmp(v, "RELEASE") == 0) {
    const bool isPress = (v[0] == 'P');
    if (!glove::armed()) { errf("%s motion_not_armed", v); return; }
    if (n < 2) { errf("%s usage_slot", v); return; }
    const int s = atoi(t[1]);
    if (s < 0 || s >= glove::SLOT_COUNT) { errf("%s slot_out_of_range", v); return; }
    if (!glove::slot(s).online && !glove::refresh(s)) {
      errf("%s slot_offline=%d", v, s);
      return;
    }
    if (isPress) glove::pressSlot(s, glove::pressSpeed(), glove::pressAcc());
    else         glove::releaseSlot(s, glove::pressSpeed(), glove::pressAcc());
    const uint8_t e = scs::lastError();
    if (e) {
      errf("%s servo_rejected slot=%d err=%u (err 非 0 = 舵机拒收，指令没生效)", v, s,
           (unsigned)e);
      return;
    }
    okf("%s slot=%d depth_percent=%d err=0", v, s, isPress ? 100 : 0);
    return;
  }
  if (strcmp(v, "MOVE") == 0) {
    if (!glove::armed()) { errf("MOVE motion_not_armed"); return; }
    if (n < 3) { errf("MOVE usage_id_position_speed_acceleration_[FORCE]"); return; }
    const int id  = atoi(t[1]);
    const int pos = atoi(t[2]);
    // speed / acc 可选（上位机的响应速度实测页只发 id + pos）
    const unsigned speed = (n >= 4) ? (unsigned)atol(t[3]) : (unsigned)glove::pressSpeed();
    const unsigned acc   = (n >= 5) ? (unsigned)atol(t[4]) : (unsigned)glove::pressAcc();

    // ★ 安全闸：目标位置必须落在该槽位校准出的机械区间内。
    //
    // MOVE 是唯一能直接指定**原始位置**的命令，也最容易撞限位 ——
    // 界面上「测动作往返」曾经硬编码 MOVE <id> 200，而那块舵机校准出来的
    // 区间可能是 [2091, 2600]：200 远在界外，舵机就一路顶过去顶死在那儿。
    // 用手册里的行话说这叫"转到不该转到的地方卡住"。
    // 宁可拒绝并说清楚，也不要让用户不明不白地看着它卡着。
    // FORCE 出现在**任何**位置都算。之所以不写死 t[5]：
    // 演奏页发的是 MOVE <id> <pos> <speed> <acc> ARM —— t[5] 被 "ARM" 占了，
    // 用户按 usage 写 MOVE 1 200 FORCE 更是压根没有 t[5]。
    // 认不出来就等于闸门放行不了，用户会以为"加了 FORCE 也没用"。
    bool force = false;
    for (int i = 1; i < n; ++i)
      if (strcasecmp(t[i], "FORCE") == 0) force = true;

    if (!force) {
      const int s = glove::slotOfId((uint8_t)id);
      if (s >= 0 && glove::slot(s).valid) {
        const int a0 = (int)glove::slot(s).lo, a1 = (int)glove::slot(s).hi;
        const int lo = (a0 < a1) ? a0 : a1;
        const int hi = (a0 < a1) ? a1 : a0;
        if (pos < lo || pos > hi) {
          errf("MOVE out_of_cal_range id=%d pos=%d allowed=%d..%d add_FORCE_to_override",
               id, pos, lo, hi);
          return;
        }
      }
    }

    if (!glove::moveRaw((uint8_t)id, (uint16_t)pos, (uint16_t)speed, (uint8_t)acc)) {
      errf("MOVE servo_no_reply id=%d", id);
      return;
    }
    const uint8_t e = scs::lastError();
    if (e) {
      // 曾经这里无条件报 OK，把「舵机拒收指令」伪装成成功，
      // 直接导致试动作时"只有 ARM 锁了电机、按下去不动"却看不出任何错。
      errf("MOVE servo_rejected id=%d pos=%d err=%u", id, pos, (unsigned)e);
      return;
    }
    okf("MOVE id=%d pos=%d speed=%u acc=%u err=0", id, pos, speed, acc);
    return;
  }
  if (strcmp(v, "DEMO") == 0) {
    if (!glove::armed() || !glove::calibrated()) { errf("DEMO arm_and_calibrate_first"); return; }
    glove::demoStart();
    okf("DEMO start");
    return;
  }

  // ---- ENROLL ----
  if (strcmp(v, "ENROLL") == 0) {
    char a[16] = "STATUS";
    if (n >= 2) {
      strncpy(a, t[1], sizeof(a) - 1);
      a[sizeof(a) - 1] = 0;
      for (char *q = a; *q; ++q) *q = (char)toupper((unsigned char)*q);
    }
    if (strcmp(a, "START") == 0) {
      g_enroll       = true;
      g_enrollNext   = 1;
      g_enrollPhase  = "WAIT_EMPTY";
      g_enrollTickMs = 0;
      okf("ENROLL START active=1 next=1 temp=10 phase=WAIT_EMPTY requirement=%s",
          "first_1_to_10_then_add_id1_as_2_to_6_then_10_to_1");
      return;
    }
    if (strcmp(a, "STOP") == 0) {
      g_enroll      = false;
      g_enrollPhase = "OFF";
      okf("ENROLL STOP");
      return;
    }
    if (strcmp(a, "RESET") == 0) {
      g_enrollNext  = 1;
      g_enrollPhase = g_enroll ? "WAIT_EMPTY" : "OFF";
      okf("ENROLL RESET next=1");
      return;
    }
    okf("ENROLL STATUS active=%d next=%u phase=%s", g_enroll ? 1 : 0, (unsigned)g_enrollNext,
        g_enrollPhase);
    return;
  }

  errf("UNKNOWN_COMMAND verb=%s", v);
}

// ---------------------------------------------------------------- 主流程

static char g_rx[256];
static int  g_rxLen = 0;
// g_rxDrop 在文件上方已前置声明 —— 因行缓冲溢出被丢弃的行数，用于诊断上位机突发丢包

void setup() {
  // Arduino-ESP32 的 HardwareSerial RX 环形缓冲默认只有 256 字节。
  // 115200 波特率下仅相当于 22 ms 的余量：上位机一次连发 60 条命令约 1.1 KB，
  // 只要主循环在 glove::tick() 里停 8 ms 读总线，环形缓冲就会溢出、字节被丢，
  // 表现为"发 60 条只回 45 条"且行内容被截断。
  // 演奏场景必须扛得住 6 指 × 6 Hz × 2 的突发，这里放大到 4 KB。
  // 注意：setRxBufferSize 必须在 begin 之前调用才会生效。
  Serial.setRxBufferSize(UART_RX_BUF);
  Serial.begin(115200);
  delay(60);
  Serial.println();
  sayf("READY FW=%s ver=%s boot_motion=0 torque=off", FW_ID, FW_VER);
  sayf("READY PROFILE=STS3032 range=4095 bus_baud=%u rx=%d tx=%d resp_timeout_ms=%u",
       (unsigned)scs::BUS_BAUD, scs::RX_PIN, scs::TX_PIN, (unsigned)scs::RESP_TIMEOUT_MS);
  scs::begin();
  glove::begin();
  sayf("READY BUS echo=%d echo_bytes=%u uart_rx_buf=%u (echo=1 说明 TX/RX 并联，属正常)",
       scs::stats().echo ? 1 : 0, (unsigned)scs::stats().echoBytes,
       (unsigned)UART_RX_BUF);
}

void loop() {
  while (Serial.available()) {
    const char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (g_rxLen > 0) {
        g_rx[g_rxLen] = 0;
        cmdLine(g_rx);
        g_rxLen = 0;
      }
    } else if (g_rxLen < (int)sizeof(g_rx) - 1) {
      g_rx[g_rxLen++] = c;
    } else if (g_rxLen >= (int)sizeof(g_rx) - 1) {
      // 行太长（正常命令不可能超过 255 字节）。丢弃整个残行并在下一个换行处复位，
      // 否则后面所有字节都会被拼到这条坏行上，造成连锁解析错乱。
      g_rxLen = 0;
      g_rxDrop++;
    }
  }

  const uint32_t now = millis();
  glove::tick();
  enrollTick(now);
}

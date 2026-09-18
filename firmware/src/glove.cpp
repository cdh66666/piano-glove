#include "glove.h"

#include <Preferences.h>

namespace glove {

namespace {

const char *SLOT_NAME[SLOT_COUNT] = {"拇指侧压", "拇指下压", "食指", "中指", "无名指", "小指"};

Slot     g_slot[SLOT_COUNT];
bool     g_calibrated   = false;
bool     g_armed        = false;
uint16_t g_speed        = 1200;      // PRESS / RELEASE / DEMO 的默认速度
uint8_t  g_acc          = 30;
uint32_t g_lastPollMs   = 0;
uint32_t g_lastCmdMs    = 0;
uint8_t  g_pollNext     = 0;

// 后台轮询用的短超时。一次把 6 个离线槽位全读一遍要 6×20 = 120 ms，
// 会把这期间到达的命令全部推迟 —— 轮转单槽 + 8 ms 把最坏附加延迟压到 8 ms。
constexpr uint16_t POLL_TIMEOUT_MS = 8;

// ---- 自动采样 ----
bool     g_auto         = false;
uint32_t g_autoN[SLOT_COUNT];
uint16_t g_autoMin[SLOT_COUNT];
uint16_t g_autoMax[SLOT_COUNT];
uint32_t g_autoTickMs   = 0;

// ---- 扫频 ----
bool     g_sweep        = false;
uint8_t  g_swMask       = 0;
uint16_t g_swFreq       = 1000;       // 单位 0.001 Hz（1000 = 1 Hz）
uint8_t  g_swDepth      = 80;
uint32_t g_swDur        = 0;
uint32_t g_swT0         = 0;
uint32_t g_swTickMs     = 0;
uint16_t g_swSpeed      = 0;          // 0 = 舵机最大速度
uint8_t  g_swAcc        = 0;

// ---- DEMO ----
bool     g_demo         = false;
uint32_t g_demoT0       = 0;
uint8_t  g_demoStep     = 0;

Preferences prefs;

inline uint16_t clampPos(int v) { return (uint16_t)(v < 0 ? 0 : (v > 4095 ? 4095 : v)); }

void keyOf(char *out, size_t n, int s, const char *suffix) {
  snprintf(out, n, "s%d%s", s, suffix);
}

void releaseMask(uint8_t mask) {
  scs::SyncItem items[SLOT_COUNT];
  int n = 0;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(mask & (1 << s))) continue;
    items[n].id    = g_slot[s].id;
    items[n].pos   = g_slot[s].standby;
    items[n].speed = g_speed;
    items[n].acc   = g_acc;
    ++n;
  }
  if (n) {
    scs::syncMove(items, n);
    scs::drain(3);
  }
}

void sweepTick(uint32_t now) {
  if (now - g_swT0 >= g_swDur) {          // 到时：松手，回到 standby
    releaseMask(g_swMask);
    g_sweep = false;
    Serial.println("SWEEP_DONE");
    return;
  }
  if (now - g_swTickMs < 5) return;        // 更新率上限 200 Hz
  g_swTickMs = now;

  const float t  = (now - g_swT0) / 1000.0f;
  const float f  = g_swFreq / 1000.0f;
  const float ph = 2.0f * PI * f * t;

  scs::SyncItem items[SLOT_COUNT];
  int n = 0;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(g_swMask & (1 << s))) continue;
    const uint16_t tgt = pressPos(s, g_swDepth);
    const float    a   = (1.0f - cosf(ph)) * 0.5f;      // 0..1，频率 = f
    items[n].id    = g_slot[s].id;
    items[n].pos   = clampPos((int)((float)g_slot[s].standby +
                                    ((float)tgt - (float)g_slot[s].standby) * a));
    items[n].speed = g_swSpeed;
    items[n].acc   = g_swAcc;
    ++n;
  }
  if (n) {
    scs::syncMove(items, n);
    scs::drain(2);                                      // 6 个舵机都会回执，直接丢掉
  }
}

void demoTick(uint32_t now) {
  const uint32_t el = now - g_demoT0;
  const uint8_t  k  = (uint8_t)(el / 250);              // 每 250 ms 一拍
  if (k >= SLOT_COUNT * 2) {
    g_demo = false;
    Serial.println("DEMO_DONE");
    return;
  }
  if (k == g_demoStep) return;
  g_demoStep = k;
  const int s = k / 2;
  if ((k % 2) == 0) pressSlot(s, g_speed, g_acc);
  else              releaseSlot(s, g_speed, g_acc);
}

}  // namespace

// ------------------------------------------------------------------

void begin() {
  load();
  g_lastPollMs = millis();
}

void tick() {
  const uint32_t now = millis();

  if (g_sweep) {                                        // 扫频独占总线
    sweepTick(now);
    return;
  }
  if (g_demo) demoTick(now);

  if (g_auto) {                                         // 校准采样中
    if (now - g_autoTickMs >= 20) {
      g_autoTickMs = now;
      for (int s = 0; s < SLOT_COUNT; ++s) {
        scs::Feedback fb;
        if (!scs::readFeedback(g_slot[s].id, fb)) continue;
        g_slot[s].online = true;
        g_slot[s].last   = fb.pos;
        const uint16_t p = clampPos(fb.pos);
        if (g_autoN[s] == 0) {
          g_autoMin[s] = p;
          g_autoMax[s] = p;
        } else {
          if (p < g_autoMin[s]) g_autoMin[s] = p;
          if (p > g_autoMax[s]) g_autoMax[s] = p;
        }
        ++g_autoN[s];
      }
    }
    return;
  }

  // 空闲时轮转刷新在线状态：每 300 ms 只读一个槽位，6 个槽位 1.8 s 转一圈。
  // 刚处理完命令就让出总线，别和前台抢。
  if (now - g_lastPollMs >= 300 && now - g_lastCmdMs > 300) {
    g_lastPollMs = now;
    const int s  = g_pollNext;
    g_pollNext   = (uint8_t)((s + 1) % SLOT_COUNT);
    Slot &sl     = g_slot[s];
    scs::Feedback fb;
    const bool on = scs::readFeedback(sl.id, fb, POLL_TIMEOUT_MS);
    sl.online = on;
    if (on) sl.last = fb.pos;
  }
}

void markCommand() { g_lastCmdMs = millis(); }

const char *name(int s) { return (s >= 0 && s < SLOT_COUNT) ? SLOT_NAME[s] : "?"; }

Slot &slot(int s) {
  static Slot dummy;
  return (s >= 0 && s < SLOT_COUNT) ? g_slot[s] : dummy;
}

int slotOfId(uint8_t id) {
  for (int s = 0; s < SLOT_COUNT; ++s)
    if (g_slot[s].id == id) return s;
  return -1;
}

bool    calibrated() { return g_calibrated; }
bool    armed()      { return g_armed; }
void    setArmed(bool on) { g_armed = on; }

uint8_t onlineMask() {
  uint8_t m = 0;
  for (int s = 0; s < SLOT_COUNT; ++s)
    if (g_slot[s].online) m |= (1 << s);
  return m;
}

bool allOnline() { return onlineMask() == 0x3F; }

bool refresh(int s) {
  Slot &sl = g_slot[s];
  scs::Feedback fb;
  const bool on = scs::readFeedback(sl.id, fb);
  sl.online = on;
  if (on) sl.last = fb.pos;
  return on;
}

bool refreshAll() {
  bool all = true;
  for (int s = 0; s < SLOT_COUNT; ++s)
    if (!refresh(s)) all = false;
  return all;
}

bool torqueSlot(int s, bool on) { return scs::setTorque(g_slot[s].id, on); }

void torqueAll(bool on) {
  for (int s = 0; s < SLOT_COUNT; ++s) scs::setTorque(g_slot[s].id, on);
}

void safe() {
  torqueAll(false);
  g_armed = false;
}

uint16_t pressPos(int s, uint8_t depthPct) {
  const Slot &sl = g_slot[s];
  if (depthPct > 100) depthPct = 100;
  const int from = (int)sl.standby;
  const int to   = (int)((sl.dir == DIR_PRESS_MAX) ? sl.hi : sl.lo);
  return clampPos(from + (to - from) * (int)depthPct / 100);
}

uint16_t releasePos(int s) { return g_slot[s].standby; }

bool pressSlot(int s, uint16_t speed, uint8_t acc) {
  if (s < 0 || s >= SLOT_COUNT) return false;
  return scs::moveTo(g_slot[s].id, pressPos(s, 100), speed, acc);
}

bool releaseSlot(int s, uint16_t speed, uint8_t acc) {
  if (s < 0 || s >= SLOT_COUNT) return false;
  return scs::moveTo(g_slot[s].id, g_slot[s].standby, speed, acc);
}

bool moveRaw(uint8_t id, uint16_t pos, uint16_t speed, uint8_t acc) {
  if (pos > 4095) pos = 4095;
  return scs::moveTo(id, pos, speed, acc);
}

bool setMap(int s, uint8_t id) {
  if (s < 0 || s >= SLOT_COUNT || id < 1 || id > 253) return false;
  g_slot[s].id     = id;
  g_slot[s].online = false;
  g_slot[s].last   = -1;
  save();
  return true;
}

void setDir(int s, Dir d) {
  if (s < 0 || s >= SLOT_COUNT) return;
  g_slot[s].dir = d;
  save();
}

void remapId(uint8_t oldId, uint8_t newId) {
  bool changed = false;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (g_slot[s].id == oldId) {
      g_slot[s].id = newId;
      changed      = true;
    }
  }
  if (changed) save();
}

void calClear() {
  for (int s = 0; s < SLOT_COUNT; ++s) {
    g_slot[s].lo      = 0;
    g_slot[s].hi      = 0;
    g_slot[s].standby = 2048;
    g_slot[s].valid   = false;
  }
  g_calibrated = false;
  g_armed      = false;
  save();
}

void calCapture(int s, uint16_t mn, uint16_t st, uint16_t mx) {
  if (s < 0 || s >= SLOT_COUNT) return;
  g_slot[s].lo      = mn;
  g_slot[s].standby = st;
  g_slot[s].hi      = mx;
  g_slot[s].valid   = true;
  save();
}

int calInvalidSlot() {
  for (int s = 0; s < SLOT_COUNT; ++s)
    if (!g_slot[s].valid) return s;
  return -1;
}

int calValidCount() {
  int n = 0;
  for (int s = 0; s < SLOT_COUNT; ++s)
    if (g_slot[s].valid) ++n;
  return n;
}

bool calSave() {
  if (calInvalidSlot() >= 0) return false;
  g_calibrated = true;
  save();
  return true;
}

void autoStart() {
  for (int s = 0; s < SLOT_COUNT; ++s) {
    g_autoN[s]   = 0;
    g_autoMin[s] = 4095;
    g_autoMax[s] = 0;
  }
  g_auto       = true;
  g_autoTickMs = 0;
  g_armed      = false;
  torqueAll(false);
}

bool     autoActive()      { return g_auto; }
uint32_t autoSamples(int s) { return (s >= 0 && s < SLOT_COUNT) ? g_autoN[s] : 0; }
int16_t  autoLast(int s)    { return (s >= 0 && s < SLOT_COUNT) ? g_slot[s].last : -1; }
uint16_t autoMin(int s)     { return (s >= 0 && s < SLOT_COUNT) ? g_autoMin[s] : 0; }
uint16_t autoMax(int s)     { return (s >= 0 && s < SLOT_COUNT) ? g_autoMax[s] : 0; }

void autoFinish() {
  g_auto = false;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (g_autoN[s] == 0) continue;
    g_slot[s].lo      = g_autoMin[s];
    g_slot[s].hi      = g_autoMax[s];
    g_slot[s].standby = (uint16_t)(((uint32_t)g_autoMin[s] + g_autoMax[s]) / 2);
    g_slot[s].valid   = true;
  }
  torqueAll(false);
  g_armed = false;
  save();
}

void autoCancel() {
  g_auto = false;
  torqueAll(false);
  g_armed = false;
}

bool sweepStart(uint8_t mask, uint16_t freqMilliHz, uint8_t depthPct, uint32_t durMs,
                uint16_t speed, uint8_t acc) {
  if (mask == 0 || freqMilliHz == 0 || durMs == 0) return false;
  if (depthPct == 0 || depthPct > 100) return false;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(mask & (1 << s))) continue;
    if (!refresh(s)) return false;                 // 参与的槽位必须在线
    scs::setTorque(g_slot[s].id, true);
  }
  g_swMask   = mask;
  g_swFreq   = freqMilliHz;
  g_swDepth  = depthPct;
  g_swDur    = durMs;
  g_swSpeed  = speed;
  g_swAcc    = acc;
  g_swT0     = millis();
  g_swTickMs = 0;
  g_sweep    = true;
  g_armed    = true;
  return true;
}

void sweepStop() {
  if (!g_sweep) return;
  g_sweep = false;
  releaseMask(g_swMask);
}

bool     sweepActive()        { return g_sweep; }
uint16_t sweepFreqMilliHz()   { return g_swFreq; }
uint8_t  sweepDepth()         { return g_swDepth; }
uint32_t sweepElapsedMs()     { return g_sweep ? (millis() - g_swT0) : 0; }

bool demoActive() { return g_demo; }

void demoStart() {
  g_demo     = true;
  g_demoT0   = millis();
  g_demoStep = 255;                                 // 强制第一拍立即执行
}

uint16_t pressSpeed() { return g_speed; }
uint8_t  pressAcc()   { return g_acc; }

void setPressProfile(uint16_t speed, uint8_t acc) {
  g_speed = speed;
  g_acc   = acc;
  save();
}

// ---------------- NVS ----------------

void load() {
  prefs.begin("pianoglove", false);
  g_speed      = prefs.getUShort("speed", 1200);
  g_acc        = prefs.getUChar("acc", 30);
  g_calibrated = prefs.getBool("calib", false);

  char k[12];
  for (int s = 0; s < SLOT_COUNT; ++s) {
    keyOf(k, sizeof(k), s, "id");
    g_slot[s].id = prefs.getUChar(k, (uint8_t)(s + 1));
    keyOf(k, sizeof(k), s, "lo");
    g_slot[s].lo = prefs.getUShort(k, 0);
    keyOf(k, sizeof(k), s, "st");
    g_slot[s].standby = prefs.getUShort(k, 2048);
    keyOf(k, sizeof(k), s, "hi");
    g_slot[s].hi = prefs.getUShort(k, 0);
    keyOf(k, sizeof(k), s, "vd");
    g_slot[s].valid = prefs.getBool(k, false);
    keyOf(k, sizeof(k), s, "d");
    g_slot[s].dir = (Dir)prefs.getUChar(k, (uint8_t)DIR_PRESS_MAX);
    g_slot[s].online = false;
    g_slot[s].last   = -1;
  }
}

void save() {
  prefs.putUShort("speed", g_speed);
  prefs.putUChar("acc", g_acc);
  prefs.putBool("calib", g_calibrated);

  char k[12];
  for (int s = 0; s < SLOT_COUNT; ++s) {
    keyOf(k, sizeof(k), s, "id"); prefs.putUChar(k, g_slot[s].id);
    keyOf(k, sizeof(k), s, "lo"); prefs.putUShort(k, g_slot[s].lo);
    keyOf(k, sizeof(k), s, "st"); prefs.putUShort(k, g_slot[s].standby);
    keyOf(k, sizeof(k), s, "hi"); prefs.putUShort(k, g_slot[s].hi);
    keyOf(k, sizeof(k), s, "vd"); prefs.putBool(k, g_slot[s].valid);
    keyOf(k, sizeof(k), s, "d");  prefs.putUChar(k, (uint8_t)g_slot[s].dir);
  }
}

}  // namespace glove

#include "glove.h"

#include <Preferences.h>

namespace glove {

namespace {

/* 槽位名。★ 拇指那两根轴**不是两个可独立演奏的自由度**：
     slot0 = 按压轴，真的把拇指压到琴键上 → 参与演奏
     slot1 = 侧摆轴，只把拇指摆到能压到键的位置 → 不参与演奏，使能到位后全程不动
   （2026-09-20 用户实机确认：出厂贴的"按下/侧摆"标签和拇指真实动作是反的。
     上位机据此把参与演奏的手指定为 5 根，侧摆的使能位由用户在调试台第 3C 步
     试出来并保存在页面侧 —— 所以**固件这里不需要任何新命令**。
     名字只影响 STATUS_ALL 的可读性；页面显示的是它自己的角色推导名，
     就算这块板子刷的还是老固件，演奏逻辑也是对的。） */
const char *SLOT_NAME[SLOT_COUNT] = {"拇指按压", "拇指侧摆", "食指", "中指", "无名指", "小指"};

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

// ---- 速度实测（RATE）----
bool     g_rate         = false;
uint8_t  g_rateMask     = 0;
uint16_t g_rateSpeed    = 0;
uint8_t  g_rateAcc      = 0;
uint8_t  g_rateDepth    = 100;
uint16_t g_rateCycles   = 3;
uint16_t g_rateDone     = 0;    // 已完成的完整行程数
uint8_t  g_ratePhase    = 0;    // 0 = 去「按下」位，1 = 回「静止」位
uint32_t g_ratePhaseT0  = 0;    // 本半程起点（微秒）
bool     g_rateSent     = false;
uint32_t g_rateHalfUs   = 0;    // 最近一个半程耗时
uint32_t g_rateSlowUs   = 0;    // 最慢的一个半程
uint32_t g_rateSumUs    = 0;
uint16_t g_rateHalfN    = 0;
uint16_t g_rateLost     = 0;    // 超时没到位的半程数

// 单个半程最多等多久。等满 = 舵机/机构跟不上，记为 lost。
constexpr uint32_t RATE_HALF_TIMEOUT_MS = 800;

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

// 速度实测的一个 tick。
//
// 关键点：**每个半程都等舵机真正到位才发下一个**，量的才是真实可达频率。
// 如果只是按固定周期猛发目标位置，量到的是"命令频率"，
// 舵机跟不跟得上完全看不出来 —— 那就失去了做这个测试的意义。
void rateTick() {
  if (!g_rate) return;

  uint8_t  ids[SLOT_COUNT];
  uint16_t tgt[SLOT_COUNT];
  int      n = 0;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(g_rateMask & (1 << s))) continue;
    ids[n] = g_slot[s].id;
    tgt[n] = (g_ratePhase == 0) ? pressPos(s, g_rateDepth) : g_slot[s].standby;
    ++n;
  }
  if (n == 0) { g_rate = false; return; }

  if (!g_rateSent) {
    scs::SyncItem items[SLOT_COUNT];
    for (int i = 0; i < n; ++i) {
      items[i].id    = ids[i];
      items[i].pos   = tgt[i];
      items[i].speed = g_rateSpeed;
      items[i].acc   = g_rateAcc;
    }
    scs::syncMove(items, n);
    scs::drain(1);
    g_rateSent    = true;
    g_ratePhaseT0 = micros();
    return;
  }

  uint16_t pos[SLOT_COUNT];
  scs::syncReadPos(ids, n, pos, 8);

  bool all = true;
  for (int i = 0; i < n; ++i) {
    if (pos[i] == 0xFFFF) { all = false; continue; }   // 这一轮没读到，当作未到位
    const int d = (int)pos[i] - (int)tgt[i];
    if (d > scs::POS_TOL || d < -scs::POS_TOL) all = false;
  }

  const uint32_t el = micros() - g_ratePhaseT0;
  if (!all && el < RATE_HALF_TIMEOUT_MS * 1000UL) return;   // 还没到，继续等

  if (!all) ++g_rateLost;                 // 等满超时都没到位 = 这套机构跟不上
  g_rateHalfUs = el;
  if (el > g_rateSlowUs) g_rateSlowUs = el;
  g_rateSumUs += el;
  ++g_rateHalfN;

  g_rateSent = false;
  if (g_ratePhase == 1) ++g_rateDone;     // 回程结束 = 走完一次"最小→最大→最小"

  if (g_rateDone >= g_rateCycles) {
    const float half = (g_rateHalfN ? (float)g_rateSumUs / g_rateHalfN : 0.0f) / 1000.0f;
    const float full = half * 2.0f;
    const float hz   = (full > 0.01f) ? (1000.0f / full) : 0.0f;
    Serial.printf("RATE_DONE cycles=%u half_ms=%.1f full_ms=%.1f hz=%.2f slow_ms=%.1f lost=%u\n",
                  (unsigned)g_rateDone, half, full, hz, g_rateSlowUs / 1000.0f,
                  (unsigned)g_rateLost);
    g_rate = false;
    return;
  }
  g_ratePhase = (uint8_t)(1 - g_ratePhase);
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
//
// ⚠️ 下面这三个函数定义在**命名空间级**、而不是上面的匿名 namespace 里。
// 原因是 glove.h 里也声明了它们（main.cpp 的 CAL ALIGN 要用 snapStandby）。
// 匿名 namespace 的成员在父命名空间里也是可见的 —— 两边都定义就成了
// 两个候选，gcc 直接报 "call of overloaded ... is ambiguous"。

void load();
void save();

// ---- 行程的两个端点 ----
//
// dir 描述的是**按下去往哪边走**，不是"哪边数值大"：
//   DIR_PRESS_MAX -> 按下端 = hi，松开端 = lo
//   DIR_PRESS_MIN -> 按下端 = lo，松开端 = hi
//
// 之所以把"松开端"单独拎出来：**静止位必须落在松开端**，
// 按压才是从"手指完全松开"一路走到"完全按下"，也就是校准出的整个量程。
uint16_t pressEnd(int s) {
  const Slot &sl = g_slot[s];
  return (sl.dir == DIR_PRESS_MAX) ? sl.hi : sl.lo;
}

uint16_t releaseEnd(int s) {
  const Slot &sl = g_slot[s];
  return (sl.dir == DIR_PRESS_MAX) ? sl.lo : sl.hi;
}

// 把静止位对齐到松开端，返回被修正的槽位掩码。
// 供 begin() 修正历史数据、以及 CAL ALIGN 手动触发。
// 只修"明显跑偏"的（离松开端超过量程的 1/4），免得把手工校准里有意留的偏移也改掉。
uint8_t snapStandby() {
  uint8_t changed = 0;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!g_slot[s].valid) continue;
    const int want = (int)releaseEnd(s);
    const int span = abs((int)g_slot[s].hi - (int)g_slot[s].lo);
    if (abs((int)g_slot[s].standby - want) > span / 4) {
      g_slot[s].standby = (uint16_t)want;
      changed |= (uint8_t)(1 << s);
    }
  }
  if (changed) save();
  return changed;
}

void begin() {
  load();
  // 修一次存量校准：2.1.1 及更早的自动校准把静止位写成了量程中点，
  // 导致按压幅度只有校准行程的一半。这里对齐到松开端，用户不必重做校准。
  const uint8_t fixed = snapStandby();          // 内部会持久化
  if (fixed) Serial.printf("CAL SNAPBASE fixed=0x%02X standby_moved_to_release_end\n", fixed);
  g_lastPollMs = millis();
}

void tick() {
  const uint32_t now = millis();

  if (g_sweep) {                                        // 扫频独占总线
    sweepTick(now);
    return;
  }
  if (g_rate) {                                         // 速度实测也独占总线
    rateTick();
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
  // ⚠️ 起点是**静止位**，终点是**按下端** —— 所以静止位必须待在松开端附近。
  // 先把它夹进校准区间：历史数据里它可能落在区间外（旧固件的自动校准
  // 把它写成了量程中点，见 autoFinish 的注释；更老的还可能是别的舵机采的）。
  // 不夹的话插值会算出区间外的目标位，机械上就是"顶死"。
  const int lo   = (sl.lo < sl.hi) ? (int)sl.lo : (int)sl.hi;
  const int hi   = (sl.lo < sl.hi) ? (int)sl.hi : (int)sl.lo;
  const int from = constrain((int)sl.standby, lo, hi);
  const int to   = (int)pressEnd(s);
  return clampPos(from + (to - from) * (int)depthPct / 100);
}

// 松开 = 回到静止位。静止位就是「松开端」（见 autoFinish / snapStandby）。
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
  // 方向一改，"松开端"就换到另一半了 —— 静止位必须跟过去，
  // 否则按下行程会从错的端点起算（表现为幅度减半，甚至整个反向）。
  if (g_slot[s].valid) g_slot[s].standby = releaseEnd(s);
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
    g_slot[s].lo = g_autoMin[s];
    g_slot[s].hi = g_autoMax[s];
    // ★ 静止位 = **松开端**，不是量程中点。
    //
    // 这里原来是 (min+max)/2。同一份校准下：
    //   standby=中点  -> pressPos(100) = 中点..按下端 —— 只有半个量程
    //   standby=松开端 -> pressPos(100) = 松开端..按下端 —— 整个量程
    // 用户做完第 3 步（手指伸直<->握拳来回活动），看到的是**整个量程**，
    // 一试动作却发现幅度只有一半，原话就是"怎么幅度这么小，
    // 要用我校准的最大幅度来啊"。
    //
    // 注意 releaseEnd() 依赖 dir，而自动校准时 dir 还是默认的 DIR_PRESS_MAX，
    // 所以这里取到的就是 lo；用户之后在试动作页改 SETDIR 时，
    // setDir() 会把静止位跟着挪到新的松开端。
    g_slot[s].standby = releaseEnd(s);
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

// ---------------------------------------------------------- 速度实测（RATE）

bool rateStart(uint8_t mask, uint16_t speed, uint8_t acc, uint8_t depthPct, uint16_t cycles) {
  if (mask == 0 || cycles == 0) return false;
  if (depthPct == 0 || depthPct > 100) return false;
  if (g_sweep || g_rate) return false;

  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(mask & (1 << s))) continue;
    Slot &sl = g_slot[s];
    if (!refresh(s)) return false;                     // 参与的槽位必须在线
    const int span = (int)pressPos(s, depthPct) - (int)sl.standby;
    // 行程太小的话"一次完整行程"几乎没有位移，测出来的频率是假的。
    if (span > -100 && span < 100) return false;       // 调用方看 rateStart 返回 false 后自查
    scs::setTorque(sl.id, true);
  }

  g_rateMask   = mask;
  g_rateSpeed  = speed;
  g_rateAcc    = acc;
  g_rateDepth  = depthPct;
  g_rateCycles = cycles;
  g_rateDone   = 0;
  g_ratePhase  = 0;
  g_rateSent   = false;
  g_rateHalfUs = 0;
  g_rateSlowUs = 0;
  g_rateSumUs  = 0;
  g_rateHalfN  = 0;
  g_rateLost   = 0;
  g_rate       = true;
  g_armed      = true;
  return true;
}

void rateStop() {
  if (!g_rate) return;
  g_rate = false;
  releaseMask(g_rateMask);
}

bool     rateActive()   { return g_rate; }
uint16_t rateDone()     { return g_rateDone; }
uint16_t rateCycles()   { return g_rateCycles; }
uint32_t rateHalfUs()   { return g_rateHalfUs; }
uint32_t rateSlowUs()   { return g_rateSlowUs; }
uint16_t rateLost()     { return g_rateLost; }

// 给调用方做前置检查：返回第一个"行程过小"的槽位号，没有则 -1。
int rateBadSlot(uint8_t mask, uint8_t depthPct) {
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(mask & (1 << s))) continue;
    const int span = (int)pressPos(s, depthPct) - (int)g_slot[s].standby;
    if (span > -100 && span < 100) return s;
  }
  return -1;
}

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

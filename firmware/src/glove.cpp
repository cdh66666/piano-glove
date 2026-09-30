#include "glove.h"
#include "cal_circle.h"

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
bool g_benchActive=false;uint32_t g_benchDeadline=0;
const char *g_benchFailure="none";
bool g_mountActive=false;uint32_t g_mountDeadline=0,g_mountPollMs=0,g_mountArrivalDeadline=0;
uint8_t g_mountReady=0,g_mountNext=0;uint16_t g_mountLo[6]={},g_mountHi[6]={};int16_t g_mountPos[6]={-1,-1,-1,-1,-1,-1};
const char *g_mountReason="none";
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

// 采样期的**轨迹**（直方图）。
//
// 只记 min/max 是不够的 —— 实测踩到过：食指静止在 4077，离编码器 4095/0
// 接缝只剩 18 个计数，采样期一次越过接缝的读数（2）就把它算成行程 4092
// （满量程），而这只手指的真实行程只有 500 上下。min/max 里看不出任何异常，
// 因为**离群值和真值一样"合法"**。
//
// 直方图是轨迹的压缩表示：结束时靠它剔离群、并认出"行程跨过接缝"。
constexpr int HIST_BINS = 128;
uint16_t g_autoHist[SLOT_COUNT][HIST_BINS];
uint32_t g_autoBad[SLOT_COUNT];     // 读到负位置（无效反馈）的次数 —— 不计入轨迹
uint16_t g_autoLo[SLOT_COUNT];      // 稳健区间：剔掉离群后真正的主簇范围
uint16_t g_autoHi[SLOT_COUNT];
uint32_t g_autoDrop[SLOT_COUNT];    // 被判为离群、没进稳健区间的样本数
bool     g_autoWrap[SLOT_COUNT];    // 主簇绕过了编码器零点（行程跨接缝）

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
uint16_t g_ratePress[SLOT_COUNT], g_rateRest[SLOT_COUNT], g_rateLo[SLOT_COUNT], g_rateHi[SLOT_COUNT];
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

// 位置上下限一律按**当前量程**夹，不写死 4095 —— 换了 SC09（0~1023）之后
// 写死的 4095 会把越界值原样发给舵机，舵机回错误包，看着却是"命令发出去了"。
inline uint16_t clampPos(int v) {
  const int r = (int)scs::profile().range;
  return (uint16_t)(v < 0 ? 0 : (v > r ? r : v));
}

// 量程中点：还没校准时手指的默认静止位（STS 2048 / SCS 511）
inline uint16_t midPos() { return (uint16_t)(scs::profile().range / 2); }

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
  if (!g_armed) { g_sweep = false; return; }
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
  if (!g_armed) { g_rate = false; return; }

  uint8_t  ids[SLOT_COUNT];
  uint16_t tgt[SLOT_COUNT];
  int      n = 0;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(g_rateMask & (1 << s))) continue;
    ids[n] = g_slot[s].id;
    tgt[n] = (g_ratePhase == 0) ? g_ratePress[s] : g_rateRest[s];
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
    g_ratePhaseT0 = micros(); // Include command transmission and readback latency.
    scs::syncMove(items, n);
    scs::drain(1);
    g_rateSent    = true;
    return;
  }

  uint16_t pos[SLOT_COUNT];
  scs::syncReadPos(ids, n, pos, scs::positionReadBudget(n));

  bool all = true;
  int i=0;
  for (int slot=0;slot<SLOT_COUNT;++slot) {
    if(!(g_rateMask&(1<<slot)))continue;
    if(pos[i]==0xFFFF){all=false;++i;continue;}
    const int tolBase=abs((int)g_ratePress[slot]-(int)g_rateRest[slot])/10;
    const int tol=tolBase<scs::posTol()?(tolBase<1?1:tolBase):scs::posTol();
    // Feedback, not merely command acknowledgement, proves the complete excursion.
    if(pos[i]+scs::posTol()<g_rateLo[slot] || pos[i]>g_rateHi[slot]+scs::posTol()){
      ++g_rateLost;safe();Serial.printf("RATE_FAILED slot=%d reason=feedback_outside_range pos=%u allowed=%u..%u valid=0\n",slot,pos[i],g_rateLo[slot],g_rateHi[slot]);return;
    }
    if(abs((int)tgt[i]-(int)pos[i])>tol)all=false;
    g_slot[slot].last=pos[i];g_slot[slot].online=true;++i;
  }
  const uint32_t el = micros() - g_ratePhaseT0;
  if(!all && el<RATE_HALF_TIMEOUT_MS*1000UL)return;
  if(!all){++g_rateLost;safe();Serial.printf("RATE_FAILED reason=arrival_timeout lost=%u valid=0\n",g_rateLost);return;}
  if(g_ratePhase==2){g_ratePhase=0;g_rateSent=false;return;} // Initial return is not a measured stroke.
  g_rateHalfUs=el;
  if(el>g_rateSlowUs)g_rateSlowUs=el;
  g_rateSumUs+=el;++g_rateHalfN;

  g_rateSent = false;
  if (g_ratePhase == 1) ++g_rateDone;     // 回程结束 = 走完一次"最小→最大→最小"

  if (g_rateDone >= g_rateCycles) {
    const float half = (g_rateHalfN ? (float)g_rateSumUs / g_rateHalfN : 0.0f) / 1000.0f;
    const float full = half * 2.0f;
    const float hz   = (full > 0.01f) ? (1000.0f / full) : 0.0f;
    Serial.printf("RATE_DONE cycles=%u half_ms=%.1f full_ms=%.1f hz=%.2f slow_ms=%.1f lost=%u valid=1\n",
                  (unsigned)g_rateDone, half, full, hz, g_rateSlowUs / 1000.0f,
                  (unsigned)g_rateLost);
    safe();
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
    const int span = calcircle::span(g_slot[s].lo,g_slot[s].hi,scs::profile().range);
    if (abs(calcircle::delta(want,g_slot[s].standby,scs::profile().range)) > span / 4) {
      g_slot[s].standby = (uint16_t)want;
      changed |= (uint8_t)(1 << s);
    }
  }
  if (changed) save();
  return changed;
}

void begin() {
  load();
  /* 型号 / 量程：先读回上次的结论，setup() 里的实测探测随后会再覆盖一次。
     放在这里而不是 load() 里，是因为 load() 定义在后面、且它只读槽位表。 */
  loadProfile();
  // 修一次存量校准：2.1.1 及更早的自动校准把静止位写成了量程中点，
  // 导致按压幅度只有校准行程的一半。这里对齐到松开端，用户不必重做校准。
  // Preserve the user-recorded natural relaxed position. CAL ALIGN remains explicit.
  g_lastPollMs = millis();
}

void tick() {
  mountTick();
  if(g_mountActive)return;
  benchTick();
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
        // ★ 负位置 = 无效反馈，直接跳过，别让它进轨迹。
        //   原实现走 clampPos()，而 clampPos 把"负数"当"越界"钳到 0 ——
        //   于是读失败的 -1 被伪装成"手指在量程零点"，成了最脏的那个离群值。
        if (fb.pos < 0) { ++g_autoBad[s]; continue; }
        const uint16_t p   = clampPos(fb.pos);
        const uint16_t rng = scs::profile().range;
        int bin = (int)((uint32_t)p * HIST_BINS / (rng ? rng : 1));
        if (bin >= HIST_BINS) bin = HIST_BINS - 1;
        ++g_autoHist[s][bin];            // 轨迹：这一帧落在哪个桶
        if (g_autoN[s] == 0) {           // 极值照旧记 —— 上报时和稳健区间对照着看
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
  // Cancel first: no release/standby target may be queued by an emergency stop.
  g_sweep = false;
  g_rate = false;
  g_rateSent = false;
  g_demo = false;
  g_auto = false;
  g_armed = false;
  g_benchActive=false;g_benchDeadline=0;
  if(g_mountActive){g_mountReason="released";for(uint8_t id=1;id<=6;++id)scs::setTorque(id,false);}
  g_mountActive=false;g_mountDeadline=0;g_mountArrivalDeadline=0;g_mountReady=0;
  torqueAll(false);
}

bool motionCalibrationSupported() {
  for(int s=0;s<SLOT_COUNT;++s) if(g_slot[s].valid && g_slot[s].lo>g_slot[s].hi){
    Serial.println(scs::profile().family==scs::Family::SCS ?
      "ERR scs_wrap_motion_unverified" : "ERR sts_wrap_motion_unverified");
    return false;
  }
  return true;
}

static char g_armFailure[176]="none";
const char *armFailure(){return g_armFailure;}
static bool armFail(const char *stage,int s=-1,int observed=-1,int expected=-1,int busErrorOverride=-1){const int busError=busErrorOverride>=0?busErrorOverride:scs::lastError();snprintf(g_armFailure,sizeof(g_armFailure),"stage=%s slot=%d id=%d observed=%d expected=%d bus_error=%d speed=%u acc=%u",stage,s,s>=0?g_slot[s].id:0,observed,expected,busError,g_speed,g_acc);safe();return false;}
bool inspectArmSlot(int s,ArmCheck &out){
 if(s<0||s>=SLOT_COUNT)return false;
 const bool big=scs::profile().family==scs::Family::SCS;
 uint8_t regs[4]={},limits[4]={},response=0;scs::Feedback fb;
 // SCS response level (8) and hardware limits (9..12) share one fresh read.
 // Keep STS's existing register transactions unchanged.
 bool responseOk=false;
 if(big){uint8_t config[5]={};const bool configOk=scs::readRegs(g_slot[s].id,8,5,config)&&!scs::lastError();out.responseError=out.limitError=scs::lastError();responseOk=configOk;out.limitsOk=configOk;response=config[0];memcpy(limits,config+1,4);}
 else{responseOk=scs::readRegs(g_slot[s].id,8,1,&response)&&!scs::lastError();out.responseError=scs::lastError();}
 out.responseLevel=responseOk?response:-1;
 out.registersOk=scs::readRegs(g_slot[s].id,scs::REG_TORQUE_EN,4,regs)&&!scs::lastError();out.registerError=scs::lastError();
 out.feedbackOk=scs::readFeedback(g_slot[s].id,fb)&&!scs::lastError()&&fb.ok;out.feedbackError=scs::lastError();
 if(!big){out.limitsOk=scs::readRegs(g_slot[s].id,9,4,limits)&&!scs::lastError();out.limitError=scs::lastError();}
 out.torque=out.registersOk?regs[0]:-1;out.goal=out.registersOk?(big?(regs[2]<<8)|regs[3]:regs[2]|(regs[3]<<8)):-1;
 out.position=out.feedbackOk?fb.pos:-1;out.minimum=out.limitsOk?(big?(limits[0]<<8)|limits[1]:limits[0]|(limits[1]<<8)):-1;out.maximum=out.limitsOk?(big?(limits[2]<<8)|limits[3]:limits[2]|(limits[3]<<8)):-1;
 return out.registersOk&&out.feedbackOk&&out.limitsOk;
}
// Measurement slack is separate from allowed command travel: never persist or
// send an expanded endpoint. SCS feedback gets at most six counts at an edge.
static int armFeedbackMargin(const Slot &sl){
 if(scs::profile().family!=scs::Family::SCS||sl.lo>sl.hi)return 0;
 const int span=sl.hi-sl.lo;
 int tol=scs::posTol();if(tol>6)tol=6;if(tol>span/4)tol=span/4;return tol;
}
static bool armFeedbackAllowed(const Slot &sl,int pos,int range){
 if(pos<0||pos>range)return false;
 if(calcircle::contains(sl.lo,sl.hi,pos,range))return true;
 const int tol=armFeedbackMargin(sl);
 return sl.lo<=sl.hi&&pos>=int(sl.lo)-tol&&pos<=int(sl.hi)+tol;
}
static int armCurrentGoal(const Slot &sl,int pos,int hardwareLo,int hardwareHi){
 const int lo=sl.lo>hardwareLo?sl.lo:hardwareLo,hi=sl.hi<hardwareHi?sl.hi:hardwareHi;
 if(lo>hi)return -1;
 return pos<lo?lo:(pos>hi?hi:pos);
}
// Position commands may engage an SCS servo from passive mechanical slack.
// Wait only for the existing goal: never send a corrective goal during settling.
static bool checkArmSettled(int s,int goal,int hardwareLo,int hardwareHi,bool wait,const char *readStage,const char *outsideStage,const char *movedStage){
 const auto &sl=g_slot[s];const int range=scs::profile().range;const uint32_t started=millis();int consecutive=0;
 do{
  scs::Feedback fb;
  if(!scs::readFeedback(sl.id,fb)||scs::lastError()||!fb.ok)return armFail(readStage,s);
  if(!armFeedbackAllowed(sl,fb.pos,range)||fb.pos<hardwareLo||fb.pos>hardwareHi)return armFail(outsideStage,s,fb.pos,goal);
  const bool within=abs(calcircle::delta(goal,fb.pos,range))<=scs::posTol();
  if(!wait)return within?true:armFail(movedStage,s,fb.pos,goal);
  consecutive=within?consecutive+1:0;
  if(consecutive>=2)return true;
  if(millis()-started>=300)return armFail(movedStage,s,fb.pos,goal);
  delay(5);
 }while(true);
}
static bool prepareArm(uint8_t mask,bool enable){
 safe();g_armFailure[0]=0;
 const scs::Profile &pf=scs::profile();const bool big=pf.family==scs::Family::SCS;
 if((pf.family!=scs::Family::STS&&!big)||(big&&(!pf.probed||pf.range!=1023)))return armFail("profile");
 if(!mask||(mask&~0x3F))return armFail("mask");
 if(!g_calibrated||calInvalidSlot()>=0)return armFail("calibration",calInvalidSlot());
 if(!motionCalibrationSupported())return armFail("wrapped_motion");
 uint16_t goals[SLOT_COUNT]={},hardwareLo[SLOT_COUNT]={},hardwareHi[SLOT_COUNT]={};
 // Check every selected axis before any position write can auto-enable an SCS servo.
 for(int s=0;s<SLOT_COUNT;++s){if(!(mask&(1<<s)))continue;const Slot &sl=g_slot[s];uint8_t off=0xFF;scs::Feedback fb;
  if(!scs::readRegs(sl.id,scs::REG_TORQUE_EN,1,&off)||scs::lastError())return armFail("torque_off_read",s,off,0);
  if(off!=0)return armFail("torque_off_value",s,off,0);
  uint8_t limits[4]={};
  if(!scs::readRegs(sl.id,9,4,limits)||scs::lastError())return armFail("hardware_limits_read",s);
  hardwareLo[s]=big?(limits[0]<<8)|limits[1]:limits[0]|(limits[1]<<8);
  hardwareHi[s]=big?(limits[2]<<8)|limits[3]:limits[2]|(limits[3]<<8);
  if(hardwareLo[s]>=hardwareHi[s]||hardwareHi[s]>pf.range)return armFail("hardware_limits_invalid",s,hardwareLo[s],hardwareHi[s]);
  if(!scs::readFeedback(sl.id,fb)||scs::lastError()||!fb.ok)return armFail("feedback_read",s);
  if(!armFeedbackAllowed(sl,fb.pos,pf.range))return armFail("feedback_outside",s,fb.pos);
  if(fb.pos<hardwareLo[s]||fb.pos>hardwareHi[s])return armFail("feedback_hardware_outside",s,fb.pos);
  const int boundedGoal=armCurrentGoal(sl,fb.pos,hardwareLo[s],hardwareHi[s]);
  if(boundedGoal<0)return armFail("target_intersection_empty",s);
  goals[s]=boundedGoal;
 }
 for(int s=0;s<SLOT_COUNT;++s){if(!(mask&(1<<s)))continue;const Slot &sl=g_slot[s];scs::Feedback fb;
  if(!scs::readFeedback(sl.id,fb)||scs::lastError()||!fb.ok)return armFail("prewrite_feedback",s);
  if(!armFeedbackAllowed(sl,fb.pos,pf.range))return armFail("prewrite_outside",s,fb.pos);
  if(fb.pos<hardwareLo[s]||fb.pos>hardwareHi[s])return armFail("prewrite_hardware_outside",s,fb.pos);
  // While torque is off, passive slack can settle after the all-axis snapshot.
  // Use the fresh position immediately before writing, never chase the old snapshot.
  uint8_t stillOff=0xFF;
  if(!scs::readRegs(sl.id,scs::REG_TORQUE_EN,1,&stillOff)||scs::lastError()||stillOff!=0)return armFail("prewrite_torque",s,stillOff,0);
  const int boundedGoal=armCurrentGoal(sl,fb.pos,hardwareLo[s],hardwareHi[s]);
  if(boundedGoal<0)return armFail("target_intersection_empty",s);
  goals[s]=boundedGoal;
  const bool writeOk=scs::moveTo(sl.id,goals[s],g_speed,g_acc)&&!scs::lastError();const int writeError=scs::lastError();
  // SC09 position writes have been observed to auto-enable. PREPARE requests off
 // immediately, then proves off/goal/current readback; it is not a never-enabled command.
  if(big&&!enable&&(!scs::setTorque(sl.id,false)||scs::lastError()))return armFail("prepare_off_write",s);
  uint8_t regs[4];if(!scs::readRegs(sl.id,scs::REG_TORQUE_EN,4,regs)||scs::lastError())return armFail("goal_read",s);
  const int goal=big?(regs[2]<<8)|regs[3]:regs[2]|(regs[3]<<8);if(goal!=goals[s])return armFail("goal_mismatch",s,goal,goals[s]);
  if((!big||!enable)?regs[0]!=0:regs[0]>1)return armFail("goal_torque_changed",s,regs[0],!big||!enable?0:1);
  if(!writeOk)return armFail("goal_write_unacknowledged",s,goal,goals[s],writeError);
  if(!checkArmSettled(s,goals[s],hardwareLo[s],hardwareHi[s],big&&enable,"postwrite_feedback","postwrite_outside","postwrite_moved"))return false;
 }
 for(int s=0;s<SLOT_COUNT;++s){if(!(mask&(1<<s)))continue;
  if(!checkArmSettled(s,goals[s],hardwareLo[s],hardwareHi[s],big&&enable,"current_read","current_outside","current_moved"))return false;
 }
 if(!enable){g_armed=false;return true;}
 for(int s=0;s<SLOT_COUNT;++s){if(!(mask&(1<<s)))continue;
  uint8_t on=0;if(!scs::readRegs(g_slot[s].id,scs::REG_TORQUE_EN,1,&on)||scs::lastError())return armFail("pre_enable_read",s);
  if(on>1||(!big&&on!=0))return armFail("pre_enable_value",s,on,0);
  if(on==0&&(!scs::setTorque(g_slot[s].id,true)||scs::lastError()))return armFail("enable_write",s);
 }
 for(int s=0;s<SLOT_COUNT;++s){if(!(mask&(1<<s)))continue;uint8_t on=0;scs::Feedback fb;
  if(!scs::readRegs(g_slot[s].id,scs::REG_TORQUE_EN,1,&on)||scs::lastError())return armFail("enable_read",s);
  if(on!=1)return armFail("enable_value",s,on,1);
  if(!checkArmSettled(s,goals[s],hardwareLo[s],hardwareHi[s],big,"enabled_feedback","enabled_outside","enabled_moved"))return false;
 }
 g_armed=true;return true;
}
bool armAtCurrent(uint8_t mask){return prepareArm(mask,true);}
bool armPrepareCurrent(uint8_t mask){return prepareArm(mask,false);}

uint16_t pressPos(int s, uint8_t depthPct) {
  const Slot &sl = g_slot[s];
  if (depthPct > 100) depthPct = 100;
  const int range=scs::profile().range;
  const int from=calcircle::contains(sl.lo,sl.hi,sl.standby,range)?sl.standby:releaseEnd(s);
  const int to=pressEnd(s);
  const int distance=sl.lo>sl.hi?calcircle::delta(from,to,range):to-from;
  return (uint16_t)calcircle::wrap(from+distance*(int)depthPct/100,range);
}

// 松开 = 回到静止位。静止位就是「松开端」（见 autoFinish / snapStandby）。
uint16_t releasePos(int s) { return g_slot[s].standby; }

bool pressSlot(int s, uint16_t speed, uint8_t acc) {
  if (s < 0 || s >= SLOT_COUNT || !motionCalibrationSupported()) return false;
  return moveRaw(g_slot[s].id, pressPos(s, 100), speed, acc);
}

bool releaseSlot(int s, uint16_t speed, uint8_t acc) {
  if (s < 0 || s >= SLOT_COUNT || !motionCalibrationSupported()) return false;
  return moveRaw(g_slot[s].id, g_slot[s].standby, speed, acc);
}

bool moveRaw(uint8_t id, uint16_t pos, uint16_t speed, uint8_t acc) {
  if (!g_armed || !motionCalibrationSupported() || pos > scs::profile().range) return false;
  const int s=slotOfId(id);
  if(s<0||!g_slot[s].valid||!calcircle::contains(g_slot[s].lo,g_slot[s].hi,pos,scs::profile().range))return false;
  uint8_t limits[4]={};
  if(!scs::readRegs(id,9,4,limits)||scs::lastError())return false;
  const bool big=scs::profile().family==scs::Family::SCS;
  const int lo=big?(limits[0]<<8)|limits[1]:limits[0]|(limits[1]<<8);
  const int hi=big?(limits[2]<<8)|limits[3]:limits[2]|(limits[3]<<8);
  if(lo>=hi||pos<lo||pos>hi)return false;
  return scs::moveTo(id, pos, speed, acc);
}

bool benchActive(){return g_benchActive;}
const char *benchFailure(){return g_benchFailure;}
void benchTick(){
 if(g_benchActive&&int32_t(millis()-g_benchDeadline)>=0){safe();Serial.println("BENCH_DONE reason=deadline torque=off armed=0");}
}
static bool benchValidate(uint8_t id,uint16_t pos,uint16_t speed){
 g_benchFailure="none";
 if(scs::profile().family!=scs::Family::SCS||!scs::profile().probed||scs::profile().range!=1023){g_benchFailure="SCS_required";return false;}
 if(id<1||id>6||speed<50||speed>1000){g_benchFailure="id_or_speed_outside_bounds";return false;}
 if(!g_armed||!g_calibrated||calInvalidSlot()>=0||g_sweep||g_rate||g_auto||g_demo){g_benchFailure="not_armed_or_busy";return false;}
 const int s=slotOfId(id);ArmCheck row;
 if(s<0||!g_slot[s].valid||!motionCalibrationSupported()||!inspectArmSlot(s,row)||!row.registersOk||!row.feedbackOk||!row.limitsOk||row.torque!=1){g_benchFailure="feedback_or_torque_invalid";return false;}
 const auto &sl=g_slot[s];
 if(row.minimum>=row.maximum||pos>1023||!calcircle::contains(sl.lo,sl.hi,pos,1023)||pos<row.minimum||pos>row.maximum||!armFeedbackAllowed(sl,row.position,1023)||row.position<row.minimum||row.position>row.maximum){g_benchFailure="outside_calibrated_or_hardware_range";return false;}
 return true;
}
bool benchMove(uint8_t id,uint16_t pos,uint16_t speed){
 if(!benchValidate(id,pos,speed))return false;
 const uint8_t goal[6]={uint8_t(pos>>8),uint8_t(pos),0,0,uint8_t(speed>>8),uint8_t(speed)};
 g_benchActive=true;g_benchDeadline=millis()+1200; // Autonomous cutoff; host silence cannot leave torque enabled.
 if(!scs::writeRegs(id,42,goal,6)||scs::lastError()){g_benchFailure="write_failed";safe();return false;}
 uint8_t actual[6]={};
 if(!scs::readRegs(id,42,6,actual)||scs::lastError()||memcmp(actual,goal,6)){g_benchFailure="goal_readback_failed";safe();return false;}
 benchTick();if(!g_benchActive){g_benchFailure="deadline";return false;}
 return true;
}
bool benchGroup(uint8_t mask,const uint16_t positions[6],uint16_t speed){
 g_benchFailure="none";benchTick();
 if(!positions||!mask||(mask&~0x3Fu)||speed<50||speed>1000){g_benchFailure="group_input_outside_bounds";safe();return false;}
 for(int id=1;id<=6;++id)if(positions[id-1]>1023){g_benchFailure="group_input_outside_bounds";safe();return false;}
 scs::SyncItem items[6];int n=0;
 for(int id=1;id<=6;++id)if(mask&(1u<<(id-1))){if(!benchValidate(id,positions[id-1],speed)){safe();return false;}benchTick();if(!g_armed){g_benchFailure="deadline";return false;}items[n++]={uint8_t(id),positions[id-1],speed,0};}
 // All selected devices are verified before the single broadcast. Ordinary syncMove remains capped.
 benchTick();if(!g_armed){g_benchFailure="deadline";return false;}
 g_benchActive=true;g_benchDeadline=millis()+1200;
 scs::syncMove(items,n,true);
 if(scs::lastError()){g_benchFailure="group_write_failed";safe();return false;}
 for(int i=0;i<n;++i){const auto &v=items[i];const uint8_t goal[6]={uint8_t(v.pos>>8),uint8_t(v.pos),0,0,uint8_t(speed>>8),uint8_t(speed)};uint8_t actual[6]={};
  if(!scs::readRegs(v.id,42,6,actual)||scs::lastError()||memcmp(actual,goal,6)){g_benchFailure="group_goal_readback_failed";safe();return false;}
  benchTick();if(!g_benchActive){g_benchFailure="deadline";return false;}
 }
 return true;
}
bool mountActive(){return g_mountActive;}
uint8_t mountReadyMask(){return g_mountReady;}
int mountPosition(int id){return id>=1&&id<=6?g_mountPos[id-1]:-1;}
const char *mountReason(){return g_mountReason;}
static bool mountFail(const char *reason){safe();g_mountReason=reason;return false;}
static bool mountRead(int axis){
 const uint8_t id=axis+1;scs::Feedback fb;uint8_t on=0;
 if(!scs::readFeedback(id,fb)||scs::lastError()||!fb.ok)return mountFail("feedback_missing");
 if(fb.pos<g_mountLo[axis]||fb.pos>g_mountHi[axis])return mountFail("feedback_hardware_outside");
 if(!scs::readRegs(id,40,1,&on)||scs::lastError()||on!=1)return mountFail("holding_torque_missing");
 g_mountPos[axis]=fb.pos;
 const uint8_t bit=1u<<axis;
 if(abs(fb.pos-512)<=scs::posTol())g_mountReady|=bit;else g_mountReady&=uint8_t(~bit);
 return true;
}
void mountTick(){
 if(!g_mountActive)return;
 if(int32_t(millis()-g_mountDeadline)>=0){mountFail("watchdog");Serial.println("MOUNT_DONE reason=watchdog torque=off_requested armed=0");return;}
 if(g_mountArrivalDeadline&&g_mountReady!=0x3F&&int32_t(millis()-g_mountArrivalDeadline)>=0){mountFail("arrival_timeout");Serial.println("MOUNT_DONE reason=arrival_timeout torque=off_requested armed=0");return;}
 if(millis()-g_mountPollMs<20)return;
 g_mountPollMs=millis();
 if(!mountRead(g_mountNext)){Serial.println("MOUNT_DONE reason=feedback_or_hardware_failure torque=off_requested armed=0");return;}
 if(g_mountReady==0x3F)g_mountArrivalDeadline=0;
 g_mountNext=(g_mountNext+1)%6;
}
bool mountKeep(){mountTick();if(!g_mountActive)return false;g_mountDeadline=millis()+3000;return true;}
bool mountStop(){
 safe();
 for(uint8_t id=1;id<=6;++id){
  uint8_t off=255;
  if(!scs::setTorque(id,false)||scs::lastError()||!scs::readRegs(id,40,1,&off)||scs::lastError()||off!=0){g_mountReason="release_unverified";return false;}
 }
 g_mountReason="stopped";return true;
}
bool mountStart(){
 if(g_mountActive){g_mountReason="already_active";return false;}
 safe();g_mountReason="none";
 for(uint8_t id=1;id<=6;++id)scs::setTorque(id,false);
 if(scs::profile().family!=scs::Family::SCS||!scs::profile().probed||scs::profile().range!=1023)return mountFail("SCS_required");
 uint16_t model=0;
 // Validate all six fixed addresses before any position write. Old travel calibration is irrelevant here.
 for(int axis=0;axis<6;++axis){
  const uint8_t id=axis+1;uint8_t limits[4]={},identity[2]={},off=255;scs::Feedback fb;
  if(!scs::readRegs(id,3,2,identity)||scs::lastError())return mountFail("identity_missing");
  const uint16_t actualModel=(uint16_t(identity[0])<<8)|identity[1];
  if(!actualModel||actualModel==0xFFFF||(model&&model!=actualModel))return mountFail("mixed_or_invalid_model");
  model=actualModel;
  if(!scs::readRegs(id,9,4,limits)||scs::lastError())return mountFail("hardware_limits_missing");
  const uint16_t lo=(uint16_t(limits[0])<<8)|limits[1],hi=(uint16_t(limits[2])<<8)|limits[3];
  if(lo>=hi||hi>1023||lo>512||hi<512)return mountFail("midpoint_outside_hardware_limits");
  if(!scs::readFeedback(id,fb)||scs::lastError()||!fb.ok||fb.pos<lo||fb.pos>hi)return mountFail("feedback_invalid");
  if(!scs::readRegs(id,40,1,&off)||scs::lastError()||off!=0)return mountFail("torque_off_unverified");
  g_mountLo[axis]=lo;g_mountHi[axis]=hi;g_mountPos[axis]=fb.pos;
 }
 invalidateCalibration(); // Persist before remounting: old limits can never resume on reconnect/reboot.
 g_mountReady=0;g_mountNext=0;g_mountActive=true;g_mountDeadline=millis()+3000;g_mountArrivalDeadline=millis()+4000;g_mountPollMs=millis();
 for(int axis=0;axis<6;++axis){
  const uint8_t id=axis+1;uint8_t goal[6]={};
  if(!scs::moveTo(id,512,200,0)||scs::lastError())return mountFail("midpoint_write_failed");
  if(!scs::readRegs(id,42,6,goal)||scs::lastError()||goal[0]!=2||goal[1]!=0||goal[2]!=0||goal[3]!=0||goal[4]!=0||goal[5]!=200)return mountFail("midpoint_goal_unverified");
  uint8_t on=0;if(!scs::readRegs(id,40,1,&on)||scs::lastError()||on>1)return mountFail("torque_read_failed");
  if(on==0&&(!scs::setTorque(id,true)||scs::lastError()))return mountFail("holding_torque_failed");
  if(!mountRead(axis))return false;
  if(int32_t(millis()-g_mountDeadline)>=0)return mountFail("watchdog");
 }
 return true; // UI must wait for all six feedback positions, not merely this acknowledgement.
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

void invalidateCalibration() {
  safe();
  g_calibrated=false;
  for (int s=0;s<SLOT_COUNT;++s) g_slot[s].valid=false;
  save();
}

void calClear() {
  for (int s = 0; s < SLOT_COUNT; ++s) {
    g_slot[s].lo      = 0;
    g_slot[s].hi      = 0;
    g_slot[s].standby = midPos();
    g_slot[s].valid   = false;
  }
  g_calibrated = false;
  g_armed      = false;
  save();
}

void calCapture(int s, uint16_t mn, uint16_t st, uint16_t mx) {
  if (s < 0 || s >= SLOT_COUNT) return;
  if(!calcircle::valid(mn,st,mx,scs::profile().range)) return;
  safe(); // Changing endpoints cancels all active trajectories.
  g_calibrated=false;
  g_slot[s].lo      = mn;
  g_slot[s].standby = st;
  g_slot[s].hi      = mx;
  g_slot[s].valid   = true;
  save();
}

static bool validCalibration(int s) {
  const Slot &sl = g_slot[s];
  const unsigned range = scs::profile().range;
  if (!sl.valid || !calcircle::valid(sl.lo,sl.standby,sl.hi,range)) return false;
  for (int i = 0; i < SLOT_COUNT; ++i)
    if (i != s && g_slot[i].id == sl.id) return false;
  return true;
}

int calInvalidSlot() {
  for (int s = 0; s < SLOT_COUNT; ++s)
    if (!validCalibration(s)) return s;
  return -1;
}

int calValidCount() {
  int n = 0;
  for (int s = 0; s < SLOT_COUNT; ++s)
    if (validCalibration(s)) ++n;
  return n;
}

bool calSave() {
  if (calInvalidSlot() >= 0) return false;
  g_calibrated = true;
  save();
  return true;
}

void autoStart() {
  safe();
  for (int s = 0; s < SLOT_COUNT; ++s) {
    g_autoN[s]   = 0;
    g_autoMin[s] = 4095;
    g_autoMax[s] = 0;
    memset(g_autoHist[s], 0, sizeof(g_autoHist[s]));
    g_autoBad[s]  = 0;
    g_autoLo[s]   = 0;
    g_autoHi[s]   = 0;
    g_autoDrop[s] = 0;
    g_autoWrap[s] = false;
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
uint16_t autoLo(int s)      { return (s >= 0 && s < SLOT_COUNT) ? g_autoLo[s] : 0; }
uint16_t autoHi(int s)      { return (s >= 0 && s < SLOT_COUNT) ? g_autoHi[s] : 0; }
uint32_t autoDrop(int s)    { return (s >= 0 && s < SLOT_COUNT) ? g_autoDrop[s] : 0; }
uint32_t autoBad(int s)     { return (s >= 0 && s < SLOT_COUNT) ? g_autoBad[s] : 0; }
bool     autoWrap(int s)    { return (s >= 0 && s < SLOT_COUNT) ? g_autoWrap[s] : false; }
int      autoHistBins()     { return HIST_BINS; }
uint16_t autoHistBw() {
  return (uint16_t)(((int)scs::profile().range + HIST_BINS - 1) / HIST_BINS);
}
uint16_t autoHist(int s, int b) {
  return (s >= 0 && s < SLOT_COUNT && b >= 0 && b < HIST_BINS) ? g_autoHist[s][b] : 0;
}

// 从采样轨迹（直方图）里挑出「主簇」—— 样本最集中的那段连续桶。
//
// 返回被丢弃的样本数；lo/hi 输出该簇覆盖的位置范围。
// 若主簇绕过了编码器零点（行程真的跨 0/4095 接缝），标记 wrap 并把 lo/hi 留 0 ——
// lo/hi 这两个 uint16 表达不了环形区间，硬塞进去只会算错，不如交给上层报警。
//
// 判据用「桶内样本数是否达标」而不是「桶是否非空」：单点噪声只占 1 个样本，
// 0.5% 的阈值天然把它挡在外面，而真轨迹的边缘桶总会有几十个样本。
// 直接用 min/max 的教训见 g_autoHist 的注释（食指被一次越缝读数撑成满量程）。
static uint32_t robustRange(int s, uint16_t &lo, uint16_t &hi) {
  const uint16_t rng = scs::profile().range;
  const uint32_t N   = g_autoN[s];
  lo = 0;
  hi = 0;
  if (!N) return 0;

  const int      bw  = ((int)rng + HIST_BINS - 1) / HIST_BINS;
  const uint32_t thr = (N / 200) ? (N / 200) : 1;      // 0.5% 样本，至少 1

  // 环形扫描所有「连续达标桶段」，取样本最多的那段当主簇。
  int bestSum = -1, bestStart = 0, bestLen = 0;
  for (int i = 0; i < HIST_BINS; ++i) {
    if (g_autoHist[s][(i + HIST_BINS - 1) % HIST_BINS] >= thr) continue;  // 前一桶也达标 -> 不是段首
    int sum = 0, len = 0;
    for (int k = 0; k < HIST_BINS; ++k) {
      const int j = (i + k) % HIST_BINS;
      if (g_autoHist[s][j] < thr) break;
      sum += g_autoHist[s][j];
      ++len;
    }
    if (sum > bestSum) {
      bestSum = sum;
      bestStart = i;
      bestLen = len;
    }
  }

  if (bestLen == 0) {                                   // 没有达标桶：样本太散，退回极值
    lo = g_autoMin[s];
    hi = g_autoMax[s];
    return 0;
  }
  if (bestStart + bestLen > HIST_BINS) {                // 主簇绕过桶 0 = 行程跨编码器零点
    g_autoWrap[s] = true;
    return N;                                           // 全丢：交给上层报警，别静默算错
  }

  const int a = bestStart * bw;
  int       b = (bestStart + bestLen - 1) * bw + bw - 1;
  if (b > (int)rng) b = (int)rng;
  lo = (uint16_t)a;
  hi = (uint16_t)b;
  return N - (uint32_t)bestSum;
}

void autoFinish() {
  g_auto = false;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (g_autoN[s] == 0) continue;
    uint16_t       lo   = 0, hi = 0;
    const uint32_t drop = robustRange(s, lo, hi);
    g_autoDrop[s] = drop;
    if (g_autoWrap[s]) {
      // 行程真的跨了编码器零点：这不是软件能"修"的 —— 按下行程在这里是环形的，
      // 线性插值必然算错。保持该槽无效，让用户挪齿位重装（或用手工校准兜底）。
      g_slot[s].valid = false;
      continue;
    }
    if (lo >= hi) {                                     // 退化成一个桶：沿用旧行为，交给 CAL SAVE 判幅度
      lo = g_autoMin[s];
      hi = g_autoMax[s];
    }
    g_autoLo[s] = lo;
    g_autoHi[s] = hi;
    g_slot[s].lo = lo;
    g_slot[s].hi = hi;
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
  if (mask == 0) return false;
  if (freqMilliHz == 0) { safe(); return true; }
  if (!g_calibrated || calInvalidSlot() >= 0 || g_sweep || g_rate || g_demo || g_auto) return false;
  if (durMs == 0) return false;
  if (depthPct == 0 || depthPct > 100) return false;
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(mask & (1 << s))) continue;
    if (!refresh(s)) { safe(); return false; }    // Validate every axis before enabling any.
  }
  if (!armAtCurrent(mask)) return false;
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
  if (!g_calibrated || calInvalidSlot() >= 0 || g_demo || g_auto) return false;
  if (mask == 0 || cycles == 0) return false;
  if (depthPct == 0 || depthPct > 100) return false;
  if (g_sweep || g_rate) return false;

  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(mask & (1 << s))) continue;
    if (!refresh(s)) { safe(); return false; }           // No partial torque on failure.
    ArmCheck row;
    if(!inspectArmSlot(s,row)||!row.feedbackOk||!row.limitsOk||!motionCalibrationSupported()){safe();return false;}
    const int lo=g_slot[s].lo>row.minimum?g_slot[s].lo:row.minimum;
    const int hi=g_slot[s].hi<row.maximum?g_slot[s].hi:row.maximum;
    const int rest=g_slot[s].standby;
    if(lo>=hi||rest<lo||rest>hi||row.position<lo||row.position>hi){safe();return false;}
    int endpoint=pressEnd(s);if(endpoint<lo)endpoint=lo;if(endpoint>hi)endpoint=hi;
    const int target=rest+(endpoint-rest)*(int)depthPct/100;
    if(abs(target-rest)<4){safe();return false;}
    g_rateLo[s]=lo;g_rateHi[s]=hi;g_rateRest[s]=rest;g_ratePress[s]=target;
  }
  if (!armAtCurrent(mask)) return false;

  g_rateMask   = mask;
  g_rateSpeed  = speed;
  g_rateAcc    = acc;
  g_rateDepth  = depthPct;
  g_rateCycles = cycles;
  g_rateDone   = 0;
  g_ratePhase  = 2;
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
  safe(); // Stop never sends another motion target.
}

bool     rateActive()   { return g_rate; }
uint16_t rateDone()     { return g_rateDone; }
uint16_t rateCycles()   { return g_rateCycles; }
uint32_t rateHalfUs()   { return g_rateHalfN ? g_rateSumUs/g_rateHalfN : 0; }
uint32_t rateSlowUs()   { return g_rateSlowUs; }
uint16_t rateLost()     { return g_rateLost; }

// 给调用方做前置检查：返回第一个"行程过小"的槽位号，没有则 -1。
int rateBadSlot(uint8_t mask, uint8_t depthPct) {
  for (int s = 0; s < SLOT_COUNT; ++s) {
    if (!(mask & (1 << s))) continue;
    const int span = calcircle::delta(g_slot[s].standby,pressPos(s,depthPct),scs::profile().range);
    if (span == 0) return s;
  }
  return -1;
}

bool demoActive() { return g_demo; }

void demoStart() {
  if (!g_armed || !g_calibrated || calInvalidSlot() >= 0 || g_sweep || g_rate || g_auto) return;
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
    g_slot[s].standby = prefs.getUShort(k, midPos());
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

void loadProfile() {
  const uint8_t fam = prefs.getUChar("pfam", (uint8_t)scs::Family::STS);
  scs::Profile p;
  p.family = (fam == (uint8_t)scs::Family::SCS) ? scs::Family::SCS : scs::Family::STS;
  p.range  = prefs.getUShort("prng", (p.family == scs::Family::SCS) ? 1023 : 4095);
  if (p.range < 128) p.range = (p.family == scs::Family::SCS) ? 1023 : 4095;   // 坏数据兜底
  p.probed = false;                 // 读回来的只是"上次的结论"，不是这次的实测
  scs::setProfile(p);
  const uint32_t baud=prefs.getUInt("pbaud",scs::BUS_BAUD);
  if(baud==1000000||baud==500000||baud==250000||baud==128000||baud==115200)scs::setBusBaud(baud);
}

void saveProfile() {
  const scs::Profile &p = scs::profile();
  const uint8_t oldFamily = prefs.getUChar("pfam", (uint8_t)scs::Family::STS);
  const uint16_t oldRange = prefs.getUShort("prng", oldFamily == (uint8_t)scs::Family::SCS ? 1023 : 4095);
  if (oldFamily != (uint8_t)p.family || oldRange != p.range) {
    // Keep numeric endpoints for inspection, but never reuse or rescale them.
    safe();
    g_calibrated = false;
    for (int s = 0; s < SLOT_COUNT; ++s) g_slot[s].valid = false;
    save();
    Serial.println("CAL INVALIDATED profile_changed recapture_required=1");
  }
  prefs.putUChar("pfam", (uint8_t)p.family);
  prefs.putUShort("prng", p.range);
  prefs.putUInt("pbaud",scs::busBaud());
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

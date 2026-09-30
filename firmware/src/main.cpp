#include "cal_circle.h"
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
#include "enroll_flow.h"
#include "profile_limits.h"

#define FW_ID  "PIANO_GLOVE_2"
#define FW_VER "2.2.4"
// 2.2.0: 型号 / 位置量程改成**从舵机读回来**（STS3032 + SC09 双适配）；
//        新增 POSALL 一帧读回全部槽位位置（演奏闭环的心跳）。
// 2.1.2: 静止位改回「松开端」（原来被设成量程中点，按压只有半个行程）
                           //        + MOVE 越界安全闸（防"转到不该去的地方卡住"）
                           //        + CAL ALIGN 修正存量校准
                           // 2.1.1: 修「编号时 remapId 把已编好的槽位一起改掉」+ sendRecv 的 pkt[32] 栈溢出

// 串口接收环形缓冲。Arduino 默认只有 256 B（115200 下 ≈ 22 ms 余量），
// 扛不住上位机一次连发几十条命令，放大到 4 KB。详见 setup() 里的说明。
#define UART_RX_BUF 4096

// ---------------------------------------------------------------- 输出

static void sayf(const char *fmt, ...) {
  char    b[1024];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(b, sizeof(b), fmt, ap);
  va_end(ap);
  Serial.println(b);
}
static void okf(const char *fmt, ...) {
  char    b[1024];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(b, sizeof(b), fmt, ap);
  va_end(ap);
  Serial.print("OK ");
  Serial.println(b);
}
static void errf(const char *fmt, ...) {
  char    b[1024];
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

static EnrollFlow g_enrollFlow;
static bool g_enroll=false;
static bool g_enrollAutomaticBoot=false;
static uint8_t g_enrollBootReadyStable=0;
static void probeAndReport(uint8_t id);
static uint8_t g_enrollNext=1;
static const char *g_enrollPhase="OFF";
static const uint32_t ENROLL_BAUDS[]={1000000,500000,250000,128000,115200};
static uint8_t g_enrollScanId=1,g_enrollBaudIndex=0,g_enrollLockedScans=0;
static uint32_t g_enrollSeen=0,g_enrollLockedBaud=0,g_enrollFoundBaud=0;
static uint32_t g_enrollStartBaud=scs::BUS_BAUD;
static uint16_t g_enrollModel=0;
static const char *g_enrollReason="none",*g_enrollStep="idle";
static int g_enrollModelRaw=-1,g_enrollMaxRaw=-1;
static bool enrollFail(const char *reason,const char *step){
 g_enrollReason=reason;g_enrollStep=step;
 sayf("ENROLL DIAG reason=%s step=%s model_raw=%d max_raw=%d baud=%u",reason,step,g_enrollModelRaw,g_enrollMaxRaw,(unsigned)scs::busBaud());
 return false;
}
static scs::Family g_enrollFamily=scs::Family::UNKNOWN;
static void enrollSync(){g_enroll=g_enrollFlow.active();g_enrollNext=g_enrollFlow.next;g_enrollPhase=g_enrollFlow.name();}
static void enrollStop(){
  const uint32_t restore=g_enrollLockedBaud?g_enrollLockedBaud:(g_enroll?g_enrollStartBaud:scs::busBaud());
  g_enrollFlow.stop();enrollSync();g_enrollAutomaticBoot=false;g_enrollBootReadyStable=0;
  scs::setBusBaud(restore);
  glove::safe();g_enrollScanId=1;g_enrollSeen=0;g_enrollBaudIndex=0;g_enrollLockedScans=0;
}
static bool enrollStart(bool automaticBoot=false){
 if(g_enroll)return false;
 enrollStop();
 g_enrollReason="none";g_enrollStep="scanning";g_enrollModelRaw=-1;g_enrollMaxRaw=-1;
 g_enrollStartBaud=scs::busBaud();
 g_enrollLockedBaud=0;g_enrollModel=0;g_enrollFamily=scs::Family::UNKNOWN;g_enrollFoundBaud=0;
 g_enrollFlow.start();enrollSync();g_enrollAutomaticBoot=automaticBoot;return true;
}
static uint8_t freshFixedDevices(){
 uint8_t live=0;
 for(uint8_t id=1;id<=6;++id){
  scs::Feedback fb;
  if(scs::ping(id,8)&&!scs::lastError()&&scs::readFeedback(id,fb,8)&&!scs::lastError()&&fb.ok&&fb.pos>=0&&fb.pos<=scs::profile().range)live|=uint8_t(1u<<(id-1));
 }
 return live;
}
static bool g_bootEnrollmentChecked=false;
static void bootCheckEnrollment(){
 if(g_bootEnrollmentChecked)return;
 g_bootEnrollmentChecked=true;
 // Fresh fixed-address reads, independent of saved mapping and cached onlineMask.
 const uint8_t live=freshFixedDevices();
 if(live!=0x3F)enrollStart(true);
 sayf("BOOT DEVICES live_mask=0x%02X ready=%d enrollment=%s motion=0",live,live==0x3F,g_enrollPhase);
}
static bool enrollIdentity(uint8_t id,scs::Profile &p){
  uint8_t m[2],lo[2],hi[2];
  g_enrollModelRaw=-1;g_enrollMaxRaw=-1;
  if(!scs::readRegs(id,3,2,m))return enrollFail("read_model_failed","read_reg3");
  const uint16_t raw=(uint16_t(m[0])<<8)|m[1];g_enrollModelRaw=raw;
  if(raw==0 || raw==0xffff)return enrollFail("model_invalid","identify");
  if(!scs::readRegs(id,9,2,lo))return enrollFail("read_limit_failed","read_reg9");
  if(!scs::readRegs(id,11,2,hi))return enrollFail("read_limit_failed","read_reg11");
  g_enrollMaxRaw=(uint16_t(hi[0])<<8)|hi[1];
  uint16_t mn=0,mx=0;int kind=identifyLimitEndian(lo,hi,mn,mx);
  if(!kind){uint8_t endian=255;if(!scs::readRegs(id,2,1,&endian)||scs::lastError())return enrollFail("read_endian_failed","read_reg2");kind=identifyMarkedLimits(lo,hi,endian,mn,mx);}
  if(!kind)return enrollFail("family_ambiguous_limits","identify");
  p.family=kind==1?scs::Family::STS:scs::Family::SCS;p.range=kind==1?4095:1023;
  p.model=raw;p.minAng=mn;p.maxAng=mx;p.probed=true;return true;
}
static bool enrollRename(uint8_t from,uint8_t to){
  scs::Profile p;uint8_t torque=255;
  if(!enrollIdentity(from,p))return false;
  if(g_enrollModel && (p.model!=g_enrollModel||p.family!=g_enrollFamily)){g_enrollFlow.conflict();return enrollFail("mixed_model","compare_model");}
  if(!g_enrollModel){g_enrollModel=p.model;g_enrollFamily=p.family;scs::setProfile(p);glove::saveProfile();}
  if(!scs::setTorque(from,false))return enrollFail("torque_write_failed","disable_torque");
  if(!scs::readRegs(from,40,1,&torque)||torque!=0)return enrollFail("torque_off_unverified","verify_torque");
  if(from==to){ // A partial prior session may already have isolated this physical slot.
    if(!scs::ping(to,5))return enrollFail("existing_id_missing","verify_existing");
    scs::Profile after;
    return enrollIdentity(to,after)&&after.model==g_enrollModel&&after.family==g_enrollFamily;
  }
  if(scs::ping(to,5))return enrollFail("target_id_present","before_write");
  // SDK: STS LOCK=55, SCSCL LOCK=48. ID=5 and TORQUE=40 are common one-byte registers.
  const uint8_t lock=p.family==scs::Family::SCS?48:55,z=0,o=1;
  if(!scs::writeRegs(from,lock,&z,1))return enrollFail("unlock_failed","unlock");
  delay(10);
  scs::writeRegs(from,5,&to,1); // ID-write ACK may use the new address; verify both addresses below.
  delay(300);
  if(scs::ping(from,5))return enrollFail("old_id_remains","verify_id");
  if(!scs::ping(to,5))return enrollFail("new_id_missing","verify_id");
  if(!scs::writeRegs(to,lock,&o,1))return enrollFail("relock_failed","relock");
  scs::Profile after;
  return enrollIdentity(to,after)&&after.model==g_enrollModel&&after.family==g_enrollFamily;
}
static void enrollTick(uint32_t now){
  (void)now;if(!g_enroll)return;
  glove::markCommand();
  uint8_t baudIndex=g_enrollBaudIndex;
  if(g_enrollLockedBaud){
    uint8_t locked=0;while(ENROLL_BAUDS[locked]!=g_enrollLockedBaud)++locked;
    baudIndex=g_enrollBaudIndex==0?locked:(g_enrollBaudIndex-1<locked?g_enrollBaudIndex-1:g_enrollBaudIndex);
  }
  const uint32_t baud=ENROLL_BAUDS[baudIndex];
  scs::setBusBaud(baud);
  if(scs::ping(g_enrollScanId,5)){
    if(g_enrollLockedBaud && baud!=g_enrollLockedBaud){
      scs::Profile candidate;
      if(!enrollIdentity(g_enrollScanId,candidate))g_enrollFlow.fail();
      else if(candidate.model!=g_enrollModel || candidate.family!=g_enrollFamily)g_enrollFlow.conflict();
      else g_enrollFlow.phase=EnrollFlow::PAUSED_BAUD;
      sayf("ENROLL PAUSED different_baud=%u id=%u action=match_bus_baud_then_restart",(unsigned)baud,g_enrollScanId);
    } else if(g_enrollFoundBaud && g_enrollFoundBaud!=baud){g_enrollFlow.conflict();}
    g_enrollFoundBaud=baud;g_enrollSeen|=1ul<<g_enrollScanId;
  }
  // Always restore locked bus between incremental probes, including before SAFE.
  if(g_enrollLockedBaud)scs::setBusBaud(g_enrollLockedBaud);
  if(!g_enrollFlow.active()){enrollSync();glove::safe();sayf("ENROLL STATUS active=0 next=%u count=%u phase=%s enroll_flow=3",g_enrollNext,g_enrollFlow.count,g_enrollPhase);return;}
  if(++g_enrollScanId<=20)return;
  g_enrollScanId=1;
  if(!g_enrollLockedBaud&&g_enrollBaudIndex==0&&g_enrollFlow.phase==EnrollFlow::WAIT_FIRST&&g_enrollSeen&&!(g_enrollSeen&(g_enrollSeen-1))){
    uint8_t candidate=1;while(!(g_enrollSeen&(1ul<<candidate)))++candidate;
    scs::Profile identity;
    if(candidate<=20&&enrollIdentity(candidate,identity))g_enrollLockedBaud=g_enrollFoundBaud;
  }
  // Confirm the locked bus after each fast ID1..20 scan. Only every eighth
  // idle round searches the other supported bauds; writes/verification never
  // wait behind alternate-baud scans.
  if(g_enrollLockedBaud&&g_enrollBaudIndex==0){
    const bool idle=g_enrollSeen==g_enrollFlow.expected&&
      (g_enrollFlow.phase==EnrollFlow::WAIT_NEXT||g_enrollFlow.phase==EnrollFlow::WAIT_FIRST);
    if(!idle||++g_enrollLockedScans<8)g_enrollBaudIndex=sizeof(ENROLL_BAUDS)/sizeof(ENROLL_BAUDS[0])-1;
    else g_enrollLockedScans=0;
  }
  if(++g_enrollBaudIndex<sizeof(ENROLL_BAUDS)/sizeof(ENROLL_BAUDS[0]))return;
  g_enrollBaudIndex=0;
  const auto before=g_enrollFlow.phase;
  // Main USB may boot before the separately powered servo bus. Only automatic
  // boot preparation can accept an already complete bus without renumbering.
  if(g_enrollAutomaticBoot&&g_enrollFlow.count==0&&(before==EnrollFlow::WAIT_EMPTY||before==EnrollFlow::WAIT_FIRST)){
    g_enrollBootReadyStable=g_enrollSeen==0x7E?g_enrollBootReadyStable+1:0;
    if(g_enrollBootReadyStable>=2){
      const uint32_t liveBaud=g_enrollFoundBaud?g_enrollFoundBaud:scs::busBaud();
      scs::setBusBaud(liveBaud);probeAndReport(1);
      if(freshFixedDevices()!=0x3F){g_enrollBootReadyStable=0;g_enrollSeen=0;g_enrollFoundBaud=0;return;}
      enrollStop();scs::setBusBaud(liveBaud);
      sayf("ENROLL READY active=0 count=6 phase=OFF boot_auto=1 motion=0");return;
    }
    if(g_enrollSeen==0x7E){g_enrollSeen=0;g_enrollFoundBaud=0;return;} // Await second complete scan; do not classify six additions as conflict.
  }
  const char *previousScanReason=g_enrollFlow.reason;
  const bool rename=g_enrollFlow.observe(g_enrollSeen,millis());
  if(!strcmp(g_enrollFlow.reason,"none")&&!strcmp(g_enrollReason,"expected_missing_retry")){g_enrollReason="none";g_enrollStep="scanning";}
  if(strcmp(g_enrollFlow.reason,"none")){
    g_enrollReason=g_enrollFlow.reason;g_enrollStep="scan_validation";
    if(strcmp(previousScanReason,g_enrollFlow.reason)||before!=g_enrollFlow.phase)sayf("ENROLL SCAN reason=%s seen=0x%08lX expected=0x%08lX missing_scans=%u phase=%s",g_enrollReason,(unsigned long)g_enrollFlow.lastSeen,(unsigned long)g_enrollFlow.lastExpected,g_enrollFlow.missingScans,g_enrollFlow.name());
  }
  if(rename){
    if(g_enrollFlow.count==0&&g_enrollFlow.phase==EnrollFlow::VERIFY_ASSIGN)glove::invalidateCalibration();
    if(!g_enrollLockedBaud)g_enrollLockedBaud=g_enrollFoundBaud;
    scs::setBusBaud(g_enrollLockedBaud);
    if(!enrollRename(g_enrollFlow.from,g_enrollFlow.to)||!glove::setMap(g_enrollFlow.slot,g_enrollFlow.to)){if(g_enrollFlow.active())g_enrollFlow.fail();}
    else sayf("ENROLL ASSIGNED id=%u slot=%u was=%u verifying=1",g_enrollFlow.to,g_enrollFlow.slot,g_enrollFlow.from);
  }
  g_enrollSeen=0;g_enrollFoundBaud=0;enrollSync();
  if(!g_enroll)glove::safe();
  if(before!=g_enrollFlow.phase)sayf("ENROLL STATUS active=%d next=%u count=%u phase=%s enroll_flow=3 baud=%u model=%u",g_enroll?1:0,g_enrollNext,g_enrollFlow.count,g_enrollPhase,(unsigned)g_enrollLockedBaud,g_enrollModel);
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
             "temperature=%u current=%d min=%u standby=%u max=%u valid=%d press=%s wrap=%d",
             s, glove::name(s), (unsigned)sl.id, (int)fb->pos, (int)fb->speed, (int)fb->load,
             (unsigned)fb->voltage, (unsigned)fb->temp, (int)fb->current,
             (unsigned)sl.lo, (unsigned)sl.standby, (unsigned)sl.hi,
             sl.valid ? 1 : 0, (sl.dir == glove::DIR_PRESS_MAX) ? "max" : "min", sl.lo>sl.hi?1:0);
  } else {
    snprintf(b, sizeof(b),
             "SLOT slot=%d name=%s id=%u online=0 min=%u standby=%u max=%u valid=%d press=%s wrap=%d",
             s, glove::name(s), (unsigned)sl.id,
             (unsigned)sl.lo, (unsigned)sl.standby, (unsigned)sl.hi,
             sl.valid ? 1 : 0, (sl.dir == glove::DIR_PRESS_MAX) ? "max" : "min", sl.lo>sl.hi?1:0);
  }
  sayf("%s", b);
}

static void printCalLine(int s) {
  const glove::Slot &sl = glove::slot(s);
  sayf("CAL slot=%d name=%s id=%u min=%u standby=%u max=%u valid=%d press=%s wrap=%d",
       s, glove::name(s), (unsigned)sl.id, (unsigned)sl.lo, (unsigned)sl.standby,
       (unsigned)sl.hi, sl.valid ? 1 : 0,
       (sl.dir == glove::DIR_PRESS_MAX) ? "max" : "min", sl.lo>sl.hi?1:0);
}

// ---------------------------------------------------------------- 命令实现

/* 从某个在线舵机把型号 / 位置量程读回来。
 *
 * 为什么上电就得做：位置量程决定校准区间、MOVE 的安全闸、到位判定容差。
 * 用户手上有两套舵机（STS3032 = 12 位 0~4095，SC09 = 10 位 0~1023），
 * 写死 4095 的话 SC09 插上去整段行程只剩 1/4，表现是"只肯动一点点就顶死"，
 * 而且舵机回的错还得靠错误位才看得出来。
 *
 * 探测失败时**保持原值**并把假设明确打出来 —— 探测失败比探测错误好：
 * 至少用户知道现在用的是哪个假设，而不是被一个静默的错量程坑住。 */
static void probeAndReport(uint8_t id) {
  scs::Profile p;
  if (scs::probeProfile(id, p)) {
    scs::setProfile(p);
    glove::saveProfile();          // 探测结果落盘：下次就算探测失败也有对的兜底
    sayf("PROFILE_AUTO id=%u family=%s range=%u pos_tol=%d model=%u min_angle=%u max_angle=%u",
         (unsigned)id, scs::familyName(p.family), (unsigned)p.range, scs::posTol(),
         (unsigned)p.model, (unsigned)p.minAng, (unsigned)p.maxAng);
  } else {
    const scs::Profile &cur = scs::profile();
    sayf("PROFILE_AUTO id=%u failed=1 keep=%s range=%u pos_tol=%d",
         (unsigned)id, scs::familyName(cur.family), (unsigned)cur.range, scs::posTol());
  }
}

static void cmdInfo() {
  const scs::Profile &pf = scs::profile();
  sayf("OK INFO fw=%s profile=%s range=%u probed=%d ap=PIANO_GLOVE_A50528 ip=192.168.4.1 "
       "calibrated=%d armed=%d auto_active=%d enroll_active=%d enroll_next=%d enroll_temp=20 "
       "enroll_phase=%s enroll_flow=3 online=%d sweep=%d ver=%s bench_group=1 bench_feedback=1 bench_sts=1 bench_keep=1 bench_fullstroke=1 cal_origin=1 bench_acc=0 motion_speed_unit=counts_per_s bench_speed_min=50 bench_speed_max=%d bench_default_speed=%d motion_speed_default=%d motion_speed_max=%d motion_tolerance=%d motion_inset=%d mount_target=%d mount_speed=%d origin_epoch=%lu",
       FW_ID, scs::familyName(pf.family), (unsigned)pf.range, pf.probed ? 1 : 0,
       glove::calibrated() ? 1 : 0, glove::armed() ? 1 : 0, glove::autoActive() ? 1 : 0,
       g_enroll ? 1 : 0, (unsigned)g_enrollNext, g_enrollPhase,
       bitcount(glove::onlineMask()), glove::sweepActive() ? 1 : 0, FW_VER,pf.family==scs::Family::SCS?1000:8000,pf.family==scs::Family::SCS?1000:8000,pf.family==scs::Family::SCS?200:8000,pf.family==scs::Family::SCS?1000:8000,pf.family==scs::Family::SCS?35:114,pf.family==scs::Family::SCS?6:24,glove::mountTarget(),glove::mountSpeed(),(unsigned long)glove::originEpoch());
}

static void cmdStatusAll() {
  for (int s = 0; s < glove::SLOT_COUNT; ++s) {
    scs::Feedback fb;
    glove::slot(s).online = scs::readFeedback(glove::slot(s).id, fb);
    if (fb.ok) glove::slot(s).last = fb.pos;
    printSlotLine(s, fb.ok ? &fb : nullptr);
  }
  okf("STATUS_ALL profile=%s range=%u armed=%d online=%d",
      scs::familyName(scs::profile().family), (unsigned)scs::profile().range,
      glove::armed() ? 1 : 0, bitcount(glove::onlineMask()));
}

static void cmdAuto() {
  sayf("AUTO_BEGIN ids=1-6 attempts=3");
  bool     present[7] = {false};
  uint8_t  ids[8];
  int      nid = 0;
  for (uint8_t id = 1; id <= 6; ++id) {
    present[id] = scs::ping(id);
    if (present[id]) ids[nid++] = id;
    /* type 不再写死 "STS"：那是在没探测之前就替舵机认了名。
       到底是哪一族要等读回来才算，见下面的 probeAndReport。 */
    sayf("AUTO_ID id=%u pings=%d identity=%d type=%s", (unsigned)id, present[id] ? 1 : 0,
         present[id] ? 1 : -1, present[id] ? "servo" : "none");
  }
  /* AUTO 是"接上一批新舵机"的入口，换套舵机（STS3032 ↔ SC09）正是走这条路，
     所以型号/量程必须在这里同步一次，不能指望用户记得手动敲 PROFILE。 */
  if (nid) probeAndReport(ids[0]);

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
  sayf("AUTO_PROFILE name=%s found=%d ids=%s missing=%s unstable=none",
       scs::familyName(scs::profile().family), nid, idList, missList);
  sayf("AUTO_RESULT profile=%s found=%d ready=%d action=%s",
       scs::familyName(scs::profile().family), nid, (nid == 6) ? 1 : 0,
       (nid == 6) ? "none" : "check_power_wiring_unique_ids_or_protocol");
  okf("AUTO profile=%s ready=%d range=%u", scs::familyName(scs::profile().family),
      (nid == 6) ? 1 : 0, (unsigned)scs::profile().range);
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
  if (strcmp(sub, "HIST") == 0) {
    // 把采样**轨迹**吐出来（直方图），只报非零桶：`bin:count` 空格分隔。
    // 存在的意义：min/max 里看不出采样被污染，轨迹里一眼就能看出
    // "主流分布在哪、哪些是孤零零的离群桶"。
    const int only = (n >= 3) ? atoi(t[2]) : -1;        // -1 = 全部 6 个槽
    const int bins = glove::autoHistBins();
    for (int s = 0; s < glove::SLOT_COUNT; ++s) {
      if (only >= 0 && s != only) continue;
      Serial.printf("CAL_HIST slot=%d bins=%d bw=%u n=%u", s, bins,
                    (unsigned)glove::autoHistBw(), (unsigned)glove::autoSamples(s));
      for (int b = 0; b < bins; ++b) {
        const uint16_t c = glove::autoHist(s, b);
        if (c) Serial.printf(" %d:%u", b, (unsigned)c);
      }
      Serial.println();
    }
    okf("CAL HIST done");
    return;
  }
  if (strcmp(sub, "CLEAR") == 0) {
    glove::calClear();
    glove::torqueAll(false);
    okf("CAL CLEAR torque=off");
    return;
  }
  if (strcmp(sub,"ORIGIN")==0){enrollStop();if(!glove::calOrigin()){errf("CAL ORIGIN %s",glove::originFailure());return;}okf("CAL ORIGIN target=2048 verified=1 motion=0");return;}
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
    const int mn=atoi(t[3]),st=atoi(t[4]),mx=atoi(t[5]);
    if(!calcircle::valid(mn,st,mx,scs::profile().range)){
      errf("CAL CAPTURE invalid_circular_range");return;
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
        sayf("CAL_AUTO slot=%d samples=%u min=%u max=%u last=%d lo=%u hi=%u drop=%u bad=%u wrap=%d",
             s, (unsigned)glove::autoSamples(s), (unsigned)glove::autoMin(s),
             (unsigned)glove::autoMax(s), (int)glove::autoLast(s),
             (unsigned)glove::autoLo(s), (unsigned)glove::autoHi(s),
             (unsigned)glove::autoDrop(s), (unsigned)glove::autoBad(s),
             glove::autoWrap(s) ? 1 : 0);
      }
      okf("CAL AUTO STATUS active=%d", glove::autoActive() ? 1 : 0);
      return;
    }
    if (strcmp(a, "FINISH") == 0) {
      glove::autoFinish();
      glove::torqueAll(false);
      // 采样结论：每根手指的轨迹算出了什么。
      // drop 大 = 采样被离群读数污染过（已剔除，不影响结果）；
      // wrap=1 = 行程真的跨了编码器 0/4095 接缝，这根手指算不了行程，要挪齿位重装。
      for (int s = 0; s < glove::SLOT_COUNT; ++s) {
        const uint16_t lo = glove::autoLo(s), hi = glove::autoHi(s);
        sayf("CAL_DONE slot=%d n=%u lo=%u hi=%u span=%u drop=%u bad=%u wrap=%d",
             s, (unsigned)glove::autoSamples(s), (unsigned)lo, (unsigned)hi,
             (unsigned)((hi > lo) ? (hi - lo) : 0), (unsigned)glove::autoDrop(s),
             (unsigned)glove::autoBad(s), glove::autoWrap(s) ? 1 : 0);
      }
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

  if (freq == 0) {
    glove::safe();
    okf("SWEEP freq_mhz=0 stopped=1 torque=off armed=0");
    return;
  }
  if (!glove::calibrated() || glove::calInvalidSlot() >= 0) {
    errf("SWEEP calibration_incomplete"); return;
  }
  if (freq > 20000 || depth == 0 || depth > 100 || dur == 0) {
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

static bool servoDiag(uint8_t id){
 if(id<1||id>6||(scs::profile().family!=scs::Family::SCS&&scs::profile().family!=scs::Family::STS)){errf("DIAG verified_family_id1to6_required");return false;}
 uint8_t d[67]={};
 for(uint8_t start=0;start<67;start+=16){
  const uint8_t n=start+16<=67?16:67-start;
  if(!scs::readRegs(id,start,n,d+start)||scs::lastError()){errf("DIAG read_failed id=%u start=%u error=%u",id,start,scs::lastError());return false;}
  char hex[33];for(uint8_t i=0;i<n;++i)snprintf(hex+2*i,3,"%02X",d[start+i]);
  sayf("DIAG_RAW id=%u start=%u length=%u hex=%s",id,start,n,hex);
 }
 const auto be=[&](int a)->uint16_t{return (uint16_t(d[a])<<8)|d[a+1];};
 if(scs::profile().family==scs::Family::STS){
  const auto le=[&](int a)->uint16_t{return uint16_t(d[a])|(uint16_t(d[a+1])<<8);};
  sayf("DIAG_STS id=%u endian=%u model_raw=%u min=%u max=%u phase=%u resolution=%u mode=%u offset=%u torque=%u acceleration=%u goal=%u pwm=%u speed_raw=%u position_raw=%u status=%u lock=%u speed_unit=%s speed_zero=%s",id,d[2],be(3),le(9),le(11),d[18],d[30],d[33],le(31),d[40],d[41],le(42),le(44),le(46),le(56),d[65],d[55],(d[18]&4)?"counts_per_s":"50counts_per_s",(d[18]&8)?"max":"stop");
  okf("DIAG id=%u raw_count=67 read_only=1",id);return true;
 }
 sayf("DIAG_SCS id=%u min=%u max=%u max_torque=%u phase=%u P=%u D=%u punch=%u dead_positive=%u dead_negative=%u hold_torque=%u protection_time=%u overload_torque=%u lock=%u",id,be(9),be(11),be(16),d[18],d[21],d[22],be(24),d[26],d[27],d[37],d[38],d[39],d[48]);
 sayf("DIAG_FEEDBACK id=%u torque=%u goal=%u time=%u speed=%u position_raw=%u speed_raw=%u load_raw=%u voltage_raw=%u temperature=%u async=%u status=%u moving=%u",id,d[40],be(42),be(44),be(46),be(56),be(58),be(60),d[62],d[63],d[64],d[65],d[66]);
 okf("DIAG id=%u raw_count=67 read_only=1",id);return true;
}
static void cmdLine(char *raw) {
  char  buf[256];
  strncpy(buf, raw, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = 0;

  char *t[16];
  int   n = 0;
  char *p = buf;
  while (*p && n < int(sizeof(t)/sizeof(t[0]))) {
    while (*p == ' ' || *p == '\t') ++p;
    if (!*p) break;
    t[n++] = p;
    while (*p && *p != ' ' && *p != '\t') ++p;
    if (*p) *p++ = 0;
  }
  while (*p == ' ' || *p == '\t') ++p;
  if (*p) { glove::safe(); errf("COMMAND too_many_arguments"); return; }
  if (n == 0) return;

  glove::markCommand();          // 让后台轮询让出总线，别和前台命令抢

  char v[16];
  strncpy(v, t[0], sizeof(v) - 1);
  v[sizeof(v) - 1] = 0;
  for (char *q = v; *q; ++q) *q = (char)toupper((unsigned char)*q);

  glove::mountTick();
  if(glove::mountActive()&&strcmp(v,"MOUNT")&&strcmp(v,"DIAG")&&strcmp(v,"INFO")&&strcmp(v,"STATUS")&&strcmp(v,"STATUS_ALL")&&strcmp(v,"POSALL")&&strcmp(v,"SAFE")&&strcmp(v,"DISARM")&&strcmp(v,"BUSINFO")){errf("MOUNT active_STOP_first");return;}
  glove::benchTick();
  if(glove::benchActive()&&strcmp(v,"BENCH")&&strcmp(v,"DIAG")&&strcmp(v,"INFO")&&strcmp(v,"STATUS")&&strcmp(v,"STATUS_ALL")&&strcmp(v,"POSALL")&&strcmp(v,"SAFE")&&strcmp(v,"DISARM")&&strcmp(v,"BUSINFO")){errf("BENCH active_wait_deadline_or_SAFE");return;}
  // Enrollment exclusively owns bus writes; status and emergency stop remain available.
  if (g_enroll && strcmp(v,"INFO") && strcmp(v,"STATUS") && strcmp(v,"STATUS_ALL") &&
      strcmp(v,"ENROLL") && strcmp(v,"MOUNT") && strcmp(v,"SAFE") && strcmp(v,"DISARM") && strcmp(v,"BUSINFO")) {
    errf("ENROLL active_stop_first"); return;
  }
  if(!strcmp(v,"MOUNT")){
    const char *action=n>=2?t[1]:"STATUS";
    if(!strcasecmp(action,"START")){
      if(glove::mountActive()){errf("MOUNT already_active");return;}
      enrollStop();if(!glove::mountStart()){errf("MOUNT %s",glove::mountReason());return;}
      okf("MOUNT START active=1 target=%d speed=%d profile=%s tolerance=%d watchdog_ms=3000 ready_mask=0x%02X",glove::mountTarget(),glove::mountSpeed(),scs::familyName(scs::profile().family),scs::posTol(),glove::mountReadyMask());return;
    }
    if(!strcasecmp(action,"KEEP")){if(!glove::mountKeep()){errf("MOUNT inactive reason=%s",glove::mountReason());return;}okf("MOUNT KEEP active=1 watchdog_ms=3000");return;}
    if(!strcasecmp(action,"STOP")){if(!glove::mountStop()){errf("MOUNT STOP active=0 release_unverified");return;}okf("MOUNT STOP active=0 torque=off verified=1");return;}
    if(!strcasecmp(action,"STATUS")){
      for(int id=1;id<=6;++id)sayf("MOUNT_SLOT id=%d pos=%d ready=%d",id,glove::mountPosition(id),(glove::mountReadyMask()>>(id-1))&1);
      okf("MOUNT STATUS active=%d target=%d profile=%s tolerance=%d ready_mask=0x%02X ready=%d reason=%s",glove::mountActive(),glove::mountTarget(),scs::familyName(scs::profile().family),scs::posTol(),glove::mountReadyMask(),glove::mountActive()&&glove::mountReadyMask()==0x3F,glove::mountReason());return;
    }
    errf("MOUNT usage_START_KEEP_STOP_STATUS");return;
  }
  if(!strcmp(v,"DIAG")){if(n!=2){errf("DIAG usage_id1to6");return;}const int id=atoi(t[1]);if(id<1||id>6){errf("DIAG id_outside1to6");return;}servoDiag(id);return;}
  if(!strcmp(v,"BENCH")){
    if(n==2&&!strcasecmp(t[1],"KEEP")){if(!glove::benchKeep()){errf("BENCH KEEP inactive_or_expired");return;}okf("BENCH KEEP active=1 armed=1 cutoff_ms=1200");return;}
    if(n>=2&&!strcasecmp(t[1],"GROUP")){
      if(n!=10){glove::safe();errf("BENCH GROUP usage_mask_p1_p2_p3_p4_p5_p6_speed");return;}
      char *end=nullptr;const unsigned long mask=strtoul(t[2],&end,0);
      if(!end||*end||!mask||mask>0x3F){glove::safe();errf("BENCH GROUP mask_outside1to63");return;}
      uint16_t positions[6];for(int id=0;id<6;++id){const long pos=strtol(t[id+3],&end,10);if(!end||*end||pos<0||pos>scs::profile().range){glove::safe();errf("BENCH GROUP target_outside_bounds id=%d",id+1);return;}positions[id]=uint16_t(pos);}
      const long speed=strtol(t[9],&end,10);if(!end||*end||speed<50||speed>(scs::profile().family==scs::Family::SCS?1000:8000)){glove::safe();errf("BENCH GROUP speed_outside_profile_bounds");return;}
      if(!glove::benchGroup(uint8_t(mask),positions,uint16_t(speed))){errf("BENCH GROUP %s",glove::benchFailure());return;}
      glove::benchTick();
      if(!glove::armed()||!glove::benchActive()){errf("BENCH GROUP deadline");return;}
      okf("BENCH GROUP mask=0x%02lX speed=%ld readback=1 count=%d cutoff_ms=1200 armed=1 bench_active=1 actual_speed=%u",mask,speed,bitcount(uint8_t(mask)),glove::benchActualSpeed());return;
    }
    if(n!=5||strcasecmp(t[1],"MOVE")){errf("BENCH usage_MOVE_id_position_speed");return;}
    const int id=atoi(t[2]),pos=atoi(t[3]),speed=atoi(t[4]);
    if(id<1||id>6||pos<0||pos>scs::profile().range||speed<50||speed>(scs::profile().family==scs::Family::SCS?1000:8000)){errf("BENCH input_outside_bounds");return;}
    if(!glove::benchMove(id,pos,speed)){errf("BENCH %s",glove::benchFailure());return;}
    okf("BENCH MOVE id=%d pos=%d speed=%d readback=1 cutoff_ms=1200 actual_speed=%u",id,pos,speed,glove::benchActualSpeed());return;
  }
  // ---- 全局 ----
  if (strcmp(v, "INFO") == 0)     { cmdInfo(); return; }
  if (strcmp(v, "HELP") == 0) {
    okf("HELP commands=%s",
        "INFO PROFILE PING SCAN STATUS STATUS_ALL POSALL MAP SETDIR SETID CAL TORQUE ARM "
        "DISARM SAFE STANDBY PRESS RELEASE MOVE DEMO SWEEP RATE PRESET AUTO ENROLL ECHO "
        "BUSINFO HELP");
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
  if (strcmp(v,"MODEL") == 0) {
    const int id=n>=2?atoi(t[1]):0;
    if(id<1||id>20){errf("MODEL usage_id1to20");return;}
    uint8_t m[2],lo[2],hi[2];
    if(!scs::readRegs(id,3,2,m)){errf("MODEL id=%d step=read_reg3",id);return;}
    if(!scs::readRegs(id,9,2,lo)||!scs::readRegs(id,11,2,hi)){errf("MODEL id=%d step=read_limits model_b0=%u model_b1=%u",id,m[0],m[1]);return;}
    okf("MODEL id=%d model_b0=%u model_b1=%u min_b0=%u min_b1=%u max_b0=%u max_b1=%u baud=%u",id,m[0],m[1],lo[0],lo[1],hi[0],hi[1],(unsigned)scs::busBaud());return;
  }
  if (strcmp(v, "PROFILE") == 0) {
    /* PROFILE             查当前用的是什么
     * PROFILE AUTO        拿第一个在线舵机去读型号/量程（默认行为）
     * PROFILE STS3032     手动钉成 12 位（自动判错时的救生索）
     * PROFILE SC09 / SCS  手动钉成 10 位
     *
     * 为什么必须留手动入口：量程判错的后果是"整套位置都错 4 倍"，
     * 而自动判据依赖舵机 EEPROM 里的 Max Angle Limit 是出厂值。
     * 万一有人改过它，用户得有办法自己掰回来，而不是只能等固件升级。 */
    if (n < 2 || strcasecmp(t[1], "AUTO") == 0) {
      /* 同样不依赖 onlineMask —— 见 setup() 里那段注释 */
      uint8_t pid = 0;
      for (int s = 0; s < glove::SLOT_COUNT && !pid; ++s) {
        const uint8_t sid = glove::slot(s).id;
        if (sid >= 1 && sid <= 253 && scs::ping(sid)) pid = sid;
      }
      if (pid) probeAndReport(pid);
      else     sayf("PROFILE_AUTO skipped=no_servo_answered");
    } else if (strcasecmp(t[1], "STS3032") == 0) {
      scs::Profile p = scs::profile();
      p.family = scs::Family::STS; p.range = 4095; p.probed = false;
      scs::setProfile(p);
      glove::saveProfile();        // 手动钉的也要记住，见 glove.h 的说明
    } else if (strcasecmp(t[1], "SC09") == 0 || strcasecmp(t[1], "SCS") == 0) {
      scs::Profile p = scs::profile();
      p.family = scs::Family::SCS; p.range = 1023; p.probed = false;
      scs::setProfile(p);
      glove::saveProfile();
    } else {
      errf("PROFILE usage_AUTO_or_STS3032_or_SC09");
      return;
    }
    const scs::Profile &pf = scs::profile();
    okf("PROFILE name=%s range=%u probed=%d pos_tol=%d",
        scs::familyName(pf.family), (unsigned)pf.range, pf.probed ? 1 : 0, scs::posTol());
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
    sayf("SCAN_BEGIN profile=%s max=20", scs::familyName(scs::profile().family));
    uint8_t found[24];
    const int c = scs::scan(20, found, 24);
    for (int i = 0; i < c; ++i) sayf("FOUND id=%u", (unsigned)found[i]);
    sayf("SCAN_END count=%d", c);
    return;
  }
  if (strcmp(v, "AUTO") == 0)     { cmdAuto(); return; }
  if (strcmp(v, "STATUS_ALL") == 0) { cmdStatusAll(); return; }
  if (strcmp(v, "POSALL") == 0) {
    /* 一帧读回所有在线槽位的当前位置 —— 演奏闭环的心跳。
     *
     * 为什么不做成逐槽位 readFeedback：那是 6 次往返（≈10 ms），
     * 按 20~30 Hz 轮询会把总线和串口全占满，演奏命令反而挤不进去。
     * syncReadPos 一帧问、n 条回包，1 Mbps 下总共不到 1 ms。
     *
     * 输出固定按**槽位下标**给 6 个数（读不到写 -1）。
     * 不做成"只列在线槽位"：那样子串里第 i 个数对应哪个槽位会随在线情况漂，
     * 而演奏闭环正是按下标索引的 —— 一漂就把命令发到别的指头上了。 */
    uint8_t  ids[glove::SLOT_COUNT];
    int      slotOf[glove::SLOT_COUNT];
    int      n = 0;
    for (int s = 0; s < glove::SLOT_COUNT; ++s) {
      if (!(glove::onlineMask() & (1 << s))) continue;
      ids[n]    = glove::slot(s).id;
      slotOf[n] = s;
      ++n;
    }
    if (n == 0) { glove::benchTick();okf("POSALL -1 -1 -1 -1 -1 -1 online=0 armed=%d bench_active=%d",glove::armed()?1:0,glove::benchActive()?1:0); return; }

    uint16_t pos[glove::SLOT_COUNT];
    scs::syncReadPos(ids, n, pos, scs::positionReadBudget(n));

    char buf[80];
    int  k = 0;
    for (int s = 0; s < glove::SLOT_COUNT; ++s) {
      int16_t pv = -1;                                  // 读不到 = 0xFFFF → int16 就是 -1
      for (int i = 0; i < n; ++i) if (slotOf[i] == s) { pv = (int16_t)pos[i]; break; }
      if (pv >= 0) glove::slot(s).last = pv;
      if (k >= 0 && k < (int)sizeof(buf) - 1)
        k += snprintf(buf + k, sizeof(buf) - (size_t)k, "%s%d", k ? " " : "", (int)pv);
    }
    glove::benchTick();
    okf("POSALL %s armed=%d bench_active=%d", buf,glove::armed()?1:0,glove::benchActive()?1:0);
    return;
  }

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
    okf("STATUS id=%d profile=%s pos=%d speed=%d load=%d voltage_raw=%u temperature=%u "
        "current=%d moving=%u mode=0",
        id, scs::familyName(scs::profile().family), (int)fb.pos, (int)fb.speed, (int)fb.load,
        (unsigned)fb.voltage, (unsigned)fb.temp, (int)fb.current, (unsigned)fb.moving);
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
      okf("RATE active=%d done=%u/%u half_ms=%.1f slow_ms=%.1f lost=%u valid=%d full_ms=%.1f hz=%.2f",
          glove::rateActive() ? 1 : 0, (unsigned)glove::rateDone(),
          (unsigned)glove::rateCycles(), glove::rateHalfUs() / 1000.0f,
          glove::rateSlowUs() / 1000.0f, (unsigned)glove::rateLost(), !glove::rateActive() && glove::rateDone()==glove::rateCycles() && glove::rateLost()==0, glove::rateHalfUs()/500.0f, glove::rateHalfUs() && !glove::rateLost() ? 500000.0f/glove::rateHalfUs() : 0.0f);
      return;
    }
    if (strcasecmp(t[1], "STOP") == 0) {
      glove::rateStop();
      okf("RATE stopped");
      return;
    }
    if (!glove::calibrated() || glove::calInvalidSlot() >= 0) {
      errf("RATE calibration_incomplete"); return;
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
    if(n>=2&&strcasecmp(t[1],"CHECK")==0){
      const auto &pf=scs::profile();
      for(int s=0;s<glove::SLOT_COUNT;++s){glove::ArmCheck row;const bool pass=glove::inspectArmSlot(s,row);const auto &sl=glove::slot(s);
        Serial.printf("ARM_CHECK_SLOT slot=%d id=%u ok=%d pos=%d torque=%d goal=%d min=%d max=%d register_error=%d feedback_error=%d limit_error=%d response_level=%d response_error=%d\n",s,sl.id,pass,row.position,row.torque,row.goal,row.minimum,row.maximum,row.registerError,row.feedbackError,row.limitError,row.responseLevel,row.responseError);
      }
      okf("ARM CHECK armed=%d profile=%s range=%u read_only=1",glove::armed(),pf.family==scs::Family::SCS?"SCS":"STS",pf.range);return;
    }
    if(n>=2&&strcasecmp(t[1],"PREPARE")==0){if(!glove::armPrepareCurrent()){errf("ARM PREPARE %s torque_off_requested",glove::armFailure());return;}okf("ARM PREPARE armed=0 goals_verified=1");return;}
    if (!glove::calibrated() || glove::calInvalidSlot() >= 0) { errf("ARM calibration_incomplete"); return; }
    if (!glove::armAtCurrent()) {
      errf("ARM safe_prepare_failed %s torque_off_requested",glove::armFailure());
      return;
    }
    okf("ARM armed=1");
    return;
  }
  if (strcmp(v, "DISARM") == 0) {
    enrollStop();
    okf("DISARM armed=0");
    return;
  }
  if (strcmp(v, "SAFE") == 0) {
    enrollStop();
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
        const int lo = a0, hi = a1;
        if (!calcircle::contains(lo,hi,pos,scs::profile().range)) {
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
    if (!glove::armed() || !glove::calibrated() || glove::calInvalidSlot() >= 0) { errf("DEMO arm_and_calibrate_first"); return; }
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
      if (!enrollStart()) { errf("ENROLL already_active"); return; }
      okf("ENROLL START active=1 next=1 temp=20 phase=WAIT_EMPTY requirement=%s",
          "append_one_id1_or_permuted_1to6_as_20to15_then_finalize_1to6");
      return;
    }
    if (strcmp(a, "STOP") == 0) {
      enrollStop();
      okf("ENROLL STOP");
      return;
    }
    if (strcmp(a, "RESET") == 0) {
      enrollStop();
      g_enrollFlow.next=1; enrollSync();
      okf("ENROLL RESET next=1");
      return;
    }
    okf("ENROLL STATUS active=%d next=%u count=%u phase=%s enroll_flow=3 baud=%u model=%u reason=%s step=%s model_raw=%d max_raw=%d seen=0x%08lX expected=0x%08lX missing_scans=%u", g_enroll ? 1 : 0, (unsigned)g_enrollNext,g_enrollFlow.count,
        g_enrollPhase,(unsigned)g_enrollLockedBaud,g_enrollModel,g_enrollReason,g_enrollStep,g_enrollModelRaw,g_enrollMaxRaw,(unsigned long)g_enrollFlow.lastSeen,(unsigned long)g_enrollFlow.lastExpected,g_enrollFlow.missingScans);
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
  sayf("READY bus_baud=%u rx=%d tx=%d resp_timeout_ms=%u",
       (unsigned)scs::BUS_BAUD, scs::RX_PIN, scs::TX_PIN, (unsigned)scs::RESP_TIMEOUT_MS);
  scs::begin();
  glove::begin();

  /* 上电就把型号 / 位置量程探出来 —— 后面每一处校准、限位、到位判定都依赖它。
     必须排在 glove::begin() 之后：那一步才会去问在线掩码。 */
  {
    /* ⚠️ 不能看 onlineMask()：begin() 刚跑完，后台轮询还没转过一圈，
       此刻它一定是 0 —— 实测就因此整段探测没发生，INFO 里 probed=0。
       直接挨个 ping 才靠得住：一条 ping ≈1 ms，最坏 6 条也不到 10 ms。 */
    uint8_t pid = 0;
    for (int s = 0; s < glove::SLOT_COUNT && !pid; ++s) {
      const uint8_t sid = glove::slot(s).id;
      if (sid >= 1 && sid <= 253 && scs::ping(sid)) pid = sid;
    }
    if (pid) probeAndReport(pid);
    else     sayf("PROFILE_AUTO skipped=no_servo_answered keep=%s range=%u",
                  scs::familyName(scs::profile().family), (unsigned)scs::profile().range);
  }
  // Profile/register layout is now resolved. Actually request torque-off before ready.
  glove::safe();
  bootCheckEnrollment(); // Once per power-on; STOP and reconnect never restart enrollment.
  sayf("READY FW=%s ver=%s boot_motion=0 torque=off_requested", FW_ID, FW_VER);
  sayf("READY BUS echo=%d echo_bytes=%u uart_rx_buf=%u (echo=1 说明 TX/RX 并联，属正常)",
       scs::stats().echo ? 1 : 0, (unsigned)scs::stats().echoBytes,
       (unsigned)UART_RX_BUF);
}

void loop() {
  glove::mountTick();
  glove::benchTick();
  while (Serial.available()) {
    glove::mountTick();
    glove::benchTick();
    const char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (g_rxLen > 0) {
        g_rx[g_rxLen] = 0;
        cmdLine(g_rx);
        glove::mountTick();
        glove::benchTick();
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
  if(!g_enroll)glove::tick(); // Enrollment has exclusive ownership of the servo bus.
  enrollTick(now);
}

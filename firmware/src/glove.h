// 手套业务模型：6 个槽位 -> 舵机、校准表、按压/松开、扫频、自检序列
#pragma once

#include <Arduino.h>
#include "scs_bus.h"

namespace glove {

constexpr int SLOT_COUNT = 6;

enum Dir : uint8_t {
  DIR_PRESS_MAX = 0,   // 往数值大的一端按下去（默认）
  DIR_PRESS_MIN = 1,   // 往数值小的一端按下去
};

struct Slot {
  uint8_t  id      = 1;        // 该槽位对应的舵机 ID
  uint16_t lo      = 0;        // 校准采样下限
  uint16_t standby = 2048;     // 松开（手指自然伸直）位置
  uint16_t hi      = 0;        // 校准采样上限
  bool     valid   = false;    // 该槽校准是否有效
  Dir      dir     = DIR_PRESS_MAX;
  bool     online  = false;    // 最近一次读取是否成功
  int16_t  last    = -1;       // 最近一次读到的位置，-1 = 未知
};

void    begin();
void    tick();
void    markCommand();       // 命令刚处理完，让后台轮询先让出总线

const char *name(int s);
Slot       &slot(int s);
int         slotOfId(uint8_t id);

bool    calibrated();
bool    armed();
void    setArmed(bool on);
uint8_t onlineMask();
bool    allOnline();

bool    refresh(int s);
bool    refreshAll();

bool    torqueSlot(int s, bool on);
void    torqueAll(bool on);
void    safe();

uint16_t pressPos(int s, uint8_t depthPct);
uint16_t releasePos(int s);
uint16_t pressEnd(int s);     // 按到底的那一端（由 dir 决定）
uint16_t releaseEnd(int s);   // 完全松开的那一端
uint8_t  snapStandby();       // 把静止位对齐到松开端，返回被修正的槽位掩码

bool    pressSlot(int s, uint16_t speed, uint8_t acc);
bool    releaseSlot(int s, uint16_t speed, uint8_t acc);
bool    moveRaw(uint8_t id, uint16_t pos, uint16_t speed, uint8_t acc);

bool    setMap(int s, uint8_t id);
void    setDir(int s, Dir d);
void    remapId(uint8_t oldId, uint8_t newId);

void    calClear();
void    calCapture(int s, uint16_t mn, uint16_t st, uint16_t mx);
bool    calSave();
int     calInvalidSlot();
int     calValidCount();

void     autoStart();
bool     autoActive();
void     autoFinish();
void     autoCancel();
uint32_t autoSamples(int s);
int16_t  autoLast(int s);
uint16_t autoMin(int s);
uint16_t autoMax(int s);

// 扫频：行程 depth% 、频率 freq、持续 dur
bool     sweepStart(uint8_t mask, uint16_t freqMilliHz, uint8_t depthPct, uint32_t durMs,
                    uint16_t speed, uint8_t acc);
void     sweepStop();
bool     sweepActive();
uint16_t sweepFreqMilliHz();
uint8_t  sweepDepth();
uint32_t sweepElapsedMs();

bool    demoActive();
void    demoStart();

// ---- 速度实测（RATE）----
//
// 定义：一次完整行程 = 最小 → 最大 → 最小（往返各一次）。
// 板子驱动选中的舵机跑 cycles 次完整行程，**每次都等舵机真正到位再走下一半程**，
// 所以量出来的是「这套机械 + 这个速度设定」实际能跑到的频率，不是命令频率。
//
// 输出（跑完自动打印）：
//   RATE_DONE cycles=3 half_ms=78.3 full_ms=156.6 hz=6.39 slow_ms=84.1 lost=0
//
// hz = 1000 / full_ms。演奏要 6 Hz 就得 hz >= 6。
bool     rateStart(uint8_t mask, uint16_t speed, uint8_t acc, uint8_t depthPct, uint16_t cycles);
void     rateStop();
bool     rateActive();
uint16_t rateDone();          // 已完成几次完整行程
uint16_t rateCycles();
uint32_t rateHalfUs();        // 最近一个半程耗时（微秒）
uint32_t rateSlowUs();        // 最慢的一个半程（超时说明跟不上）
uint16_t rateLost();          // 有多少个半程是超时放弃的

// 前置检查：返回第一个"行程过小"的槽位号（校准不到位/范围太窄），没有则 -1。
int      rateBadSlot(uint8_t mask, uint8_t depthPct);

uint16_t pressSpeed();
uint8_t  pressAcc();
void     setPressProfile(uint16_t speed, uint8_t acc);

void    load();
void    save();

// 型号 / 位置量程的持久化。
// 开机探测成功时是探测值说了算；探测**失败**时靠这里存的兜底 ——
// 否则用户手动 `PROFILE SC09` 之后一断电重启又被打回 4095，
// 症状是"明明设好了，重启就坏"。手动设置也是一种事实，该记住。
void    loadProfile();
void    saveProfile();

}  // namespace glove

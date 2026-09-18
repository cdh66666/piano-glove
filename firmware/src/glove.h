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

uint16_t pressSpeed();
uint8_t  pressAcc();
void     setPressProfile(uint16_t speed, uint8_t acc);

void    load();
void    save();

}  // namespace glove

// 飞特 SCS/STS 半双工单总线驱动
//
// 协议：0xFF 0xFF ID LEN INSTR PARAM... CHECKSUM
//   LEN      = 参数个数 + 2
//   总长度    = LEN + 4
//   CHECKSUM = ~(ID + LEN + INSTR + PARAM...) & 0xFF
// 状态包：0xFF 0xFF ID LEN ERR DATA... CHECKSUM（第 5 字节是错误码，不是指令）
//
// 本文件是 host/scservo_sdk/ 官方 Python SDK 的 C++ 移植，
// 寄存器地址与包格式逐字节对齐，便于两边交叉验证。
#pragma once

#include <Arduino.h>

namespace scs {

// ---------------- 总线硬件（与原厂固件一致，勿随意改） ----------------
constexpr int      RX_PIN   = 18;     // 板子 -> 舵机（UART1 RX）
constexpr int      TX_PIN   = 19;     // 板子 -> 舵机（UART1 TX）
constexpr uint32_t BUS_BAUD = 1000000;

// 单条命令的回复等待窗口。原厂固件固定约 103 ms/条，这是它吞吐只有
// 9.9 条/秒的根因。1 Mbps 下一包往返不到 2 ms，20 ms 已非常宽裕。
constexpr uint16_t RESP_TIMEOUT_MS = 20;

// ---------------- 指令 ----------------
enum : uint8_t {
  INST_PING       = 0x01,
  INST_READ       = 0x02,
  INST_WRITE      = 0x03,
  INST_REG_WRITE  = 0x04,
  INST_ACTION     = 0x05,
  INST_RESET      = 0x0A,
  INST_SYNC_WRITE = 0x83,
  INST_SYNC_READ  = 0x82,
};
constexpr uint8_t BROADCAST_ID = 0xFE;

// ---------------- STS/SMS 内存表 ----------------
enum : uint8_t {
  REG_MODEL_L      = 3,
  REG_ID           = 5,
  REG_BAUD         = 6,
  REG_MIN_ANGLE_L  = 9,
  REG_MAX_ANGLE_L  = 11,
  REG_CW_DEAD      = 26,
  REG_OFS_L        = 31,
  REG_MODE         = 33,
  REG_TORQUE_EN    = 40,
  REG_ACC          = 41,
  REG_GOAL_POS_L   = 42,
  REG_GOAL_TIME_L  = 44,
  REG_GOAL_SPEED_L = 46,
  REG_LOCK         = 55,
  REG_PRES_POS_L   = 56,
  REG_PRES_SPEED_L = 58,
  REG_PRES_LOAD_L  = 60,
  REG_PRES_VOLT    = 62,
  REG_PRES_TEMP    = 63,
  REG_MOVING       = 66,
  REG_PRES_CURR_L  = 69,
  // 56..70 连续 15 字节一次读完，省往返
  PRES_BLOCK_LEN   = 15,
};

struct Feedback {
  bool    ok      = false;
  int16_t pos     = -1;
  int16_t speed   = 0;
  int16_t load    = 0;
  int16_t current = 0;
  uint8_t voltage = 0;   // 原始值，÷10 = 伏特
  uint8_t temp    = 0;   // ℃
  uint8_t moving  = 0;
  uint8_t mode    = 0;
};

struct Stats {
  uint32_t tx       = 0;   // 发出的包数
  uint32_t rx       = 0;   // 收到的字节数
  uint32_t timeout  = 0;   // 等回复超时次数
  uint32_t badsum   = 0;   // 校验和/长度错次数
  uint32_t servoErr = 0;   // 舵机在状态包里报了错误位的次数
  uint16_t echoBytes = 0;  // 开机探测时收到的自身回显字节数
  bool     echo     = false;
};

void    begin();
Stats  &stats();
void    setEcho(bool on);          // 手动覆盖回显判定（诊断用）

// 最近一条回复里舵机上报的错误位（状态包第 5 字节）。0 = 正常。
//
// 为什么需要它：`sendRecv` 只判断"有没有收到一条校验正确的回包"，
// 而舵机拒绝一条指令时**照样会回包**（只是错误位非 0）。曾经因为漏看这一位，
// moveTo() 少写了起始寄存器地址、舵机收下垃圾地址后回了个错误包，
// 固件却报 OK —— 现象是「使能以后舵机锁死但一点也不动」，查了很久。
uint8_t lastError();

bool    ping(uint8_t id);
bool    readRegs(uint8_t id, uint8_t addr, uint8_t len, uint8_t *out,
                 uint16_t timeoutMs = RESP_TIMEOUT_MS);
bool    writeRegs(uint8_t id, uint8_t addr, const uint8_t *data, uint8_t len);
bool    readFeedback(uint8_t id, Feedback &fb, uint16_t timeoutMs = RESP_TIMEOUT_MS);

// 位置到位判定容差（舵机计数，4096 计数 = 360°，所以 25 计数 ≈ 2.2°）
constexpr int POS_TOL = 25;

// 下发目标位置：写 ACC(41) 起 7 字节（ACC + 位置 + 运行时间 + 速度）。
// speed = 0 表示用舵机自身的最大速度。
// 返回 false = 没收到回包；返回 true 但 lastError()!=0 = 舵机拒绝了这条指令。
bool    moveTo(uint8_t id, uint16_t pos, uint16_t speed, uint8_t acc);
bool    setTorque(uint8_t id, bool on);
bool    setId(uint8_t oldId, uint8_t newId);
int     scan(uint8_t maxId, uint8_t *found, int cap);

struct SyncItem { uint8_t id; uint16_t pos; uint16_t speed; uint8_t acc; };
void    syncMove(const SyncItem *items, int n);   // 一帧同时更新多个舵机

// 一次 SYNC_READ 读回 n 个舵机的当前位置。
// ids[] 必须互不相同；pos[] 与 ids[] 一一对应，读不到的置 0xFFFF。
// 返回值 = 真正读到的个数。
//
// 为什么不用 for 循环逐个 readRegs：读 6 个舵机要 6 次往返（≈10 ms），
// 做速度实测时这个开销会直接吃掉测量精度。SYNC_READ 一帧问、6 条回包，
// 1 Mbps 下总共不到 1 ms。
int     syncReadPos(const uint8_t *ids, int n, uint16_t *pos,
                    uint16_t timeoutMs = RESP_TIMEOUT_MS);

void    drain(uint16_t ms);                       // 丢弃总线上的残包

}  // namespace scs

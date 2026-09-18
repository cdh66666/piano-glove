#include "scs_bus.h"

namespace scs {

namespace {

HardwareSerial &bus = Serial1;
Stats  g_stats;
bool   g_echo = false;      // TX/RX 是否并联（能收到自己的发送）
uint8_t g_lastErr = 0;      // 最近一条状态包里的错误位（见 scs_bus.h 的说明）

// 本文件里所有「接收缓冲」的统一大小。
// 必须是 readPacket 里 buf[] 的大小 —— 那条 memcpy 的长度由舵机回包的
// LEN 字段决定，最大就是 buf 的大小。见 readPacket 上方的不变式说明。
constexpr int RESP_BUF = 96;

// 校验和：对 [from, to) 求和后取反
inline uint8_t checksum(const uint8_t *p, int from, int to) {
  uint8_t s = 0;
  for (int i = from; i < to; ++i) s = (uint8_t)(s + p[i]);
  return (uint8_t)(~s);
}

// 组包，返回总长度
uint8_t build(uint8_t id, uint8_t inst, const uint8_t *params, uint8_t plen, uint8_t *out) {
  out[0] = 0xFF;
  out[1] = 0xFF;
  out[2] = id;
  out[3] = (uint8_t)(plen + 2);
  out[4] = inst;
  for (uint8_t i = 0; i < plen; ++i) out[5 + i] = params[i];
  const uint8_t total = (uint8_t)(plen + 6);
  out[total - 1] = checksum(out, 2, (int)total - 1);
  return total;
}

// 吃掉自身回显（仅当探测到 TX/RX 并联）
void eatEcho(uint8_t n) {
  if (!g_echo || n == 0) return;
  const uint32_t t0 = micros();
  while (n > 0 && (uint32_t)(micros() - t0) < 4000) {
    if (bus.available()) {
      bus.read();
      --n;
    }
  }
}

// 读一条 ID 匹配、校验正确的状态包；失败返回 false
// expectId = 0xFF 表示"收谁的都行"（SYNC_READ 要收好几条不同 ID 的回包）。
// 0xFF 不是合法舵机 ID（广播是 0xFE，可用 ID 1~253），不会和真实 ID 撞。
//
// ⚠️ 不变式：out 指向的缓冲**至少要有 RESP_BUF 字节**。
// 因为包长来自舵机回包里的 LEN 字段，最多能到 sizeof(buf)，
// 这里会原样 memcpy 过去。本文件里所有 reply 缓冲都统一用 RESP_BUF，
// 就是为了让"舵机回了个超长包"也绝不会写穿调用者的栈。（这个坑踩过）
bool readPacket(uint8_t expectId, uint8_t *out, int &outLen, uint16_t timeoutMs) {
  uint8_t  buf[96];
  int      n  = 0;
  const uint32_t t0 = millis();

  while ((uint32_t)(millis() - t0) < timeoutMs) {
    if (!bus.available()) continue;
    const uint8_t b = (uint8_t)bus.read();
    ++g_stats.rx;

    if (n == 0) {                       // 找第一个 0xFF
      if (b == 0xFF) buf[n++] = b;
      continue;
    }
    if (n == 1) {                       // 找第二个 0xFF
      if (b == 0xFF) {
        buf[n++] = b;
      } else {
        n = 0;
        if (b == 0xFF) buf[n++] = b;
      }
      continue;
    }
    if (n >= (int)sizeof(buf)) { n = 0; continue; }
    buf[n++] = b;
    if (n < 4) continue;

    const int need = (int)buf[3] + 4;   // LEN + 4
    if (need < 6 || need > (int)sizeof(buf)) {   // 长度字段非法 -> 丢 1 字节重同步
      memmove(buf, buf + 1, (size_t)(--n));
      continue;
    }
    if (n < need) continue;

    if (checksum(buf, 2, need - 1) == buf[need - 1]) {
      if (buf[2] == expectId || expectId == 0xFF) {
        g_lastErr = buf[4];                 // 状态包第 5 字节 = 舵机的错误位
        if (g_lastErr) ++g_stats.servoErr;
        memcpy(out, buf, (size_t)need);
        outLen = need;
        return true;
      }
    } else {
      ++g_stats.badsum;
    }
    memmove(buf, buf + 1, (size_t)(--n));        // 丢 1 字节继续找
  }
  ++g_stats.timeout;
  return false;
}

// 发一包；wantReply=false 时只发不收
bool sendRecv(uint8_t id, uint8_t inst, const uint8_t *params, uint8_t plen,
              uint8_t *reply, int &replyLen, bool wantReply,
              uint16_t timeoutMs = RESP_TIMEOUT_MS) {
  // ⚠️ pkt 必须容得下**最长的**那一条参数：
  //   SYNC_WRITE 每根舵机 7 字节 + 头 2 字节（起始地址 + 每根字节数），
  //   一次最多 8 根 -> 2 + 7*8 = 58，加 6 字节包头 = 64。
  // 这里曾经是 pkt[32]，只够 3 根（2+7*3+6 = 29）；第 4 根起就写穿栈，
  // 6 根一起同步写必然触发 "Stack smashing protect failure!" 直接复位。
  // 单根 MOVE 只写 8 字节、writeRegs 最多 24 字节，都碰不到 32，所以这个坑
  // 一直躲着 —— 直到 RATE 第一次 6 根同时同步写才炸出来。（这个坑踩过）
  uint8_t pkt[80];
  const uint8_t total = build(id, inst, params, plen, pkt);

  g_lastErr = 0;                                 // 每条命令独立判定，别继承上一条的错误
  while (bus.available()) bus.read();            // 清残留，避免和上一条串包
  bus.write(pkt, total);
  bus.flush();                                   // 等 TX 移位寄存器发完
  ++g_stats.tx;

  if (!wantReply) return true;
  eatEcho(total);
  return readPacket(id, reply, replyLen, timeoutMs);
}

// 开机探测 TX/RX 是否并联：向一个不存在的 ID 发 PING，看能收回几个字节
void probeEcho() {
  uint8_t pkt[8];
  const uint8_t total = build(220, INST_PING, nullptr, 0, pkt);

  while (bus.available()) bus.read();
  bus.write(pkt, total);
  bus.flush();
  delayMicroseconds(120);

  uint16_t c = 0;
  const uint32_t t0 = micros();
  while ((uint32_t)(micros() - t0) < 3000) {
    if (bus.available()) {
      bus.read();
      ++c;
    }
  }
  g_stats.echoBytes = c;
  g_echo            = (c >= total);
  g_stats.echo      = g_echo;
}

}  // namespace

// ------------------------------------------------------------------

void begin() {
  bus.begin(BUS_BAUD, SERIAL_8N1, RX_PIN, TX_PIN);
  bus.setTimeout(2);
  delay(30);
  while (bus.available()) bus.read();
  probeEcho();
}

Stats &stats() { return g_stats; }

uint8_t lastError() { return g_lastErr; }

void setEcho(bool on) {
  g_echo       = on;
  g_stats.echo = on;
}

void drain(uint16_t ms) {
  const uint32_t t0   = millis();
  uint32_t       last = t0;
  while ((uint32_t)(millis() - t0) < ms) {
    if (bus.available()) {
      bus.read();
      last = millis();
    } else if ((uint32_t)(millis() - last) > 3) {
      break;                                     // 连续 3 ms 没动静就算干净
    }
  }
}

bool ping(uint8_t id) {
  uint8_t r[RESP_BUF];
  int     rl = 0;
  if (!sendRecv(id, INST_PING, nullptr, 0, r, rl, true)) return false;
  return rl >= 6;
}

bool readRegs(uint8_t id, uint8_t addr, uint8_t len, uint8_t *out, uint16_t timeoutMs) {
  const uint8_t p[2] = {addr, len};
  uint8_t       r[RESP_BUF];
  int           rl = 0;
  if (!sendRecv(id, INST_READ, p, 2, r, rl, true, timeoutMs)) return false;
  if (rl < (int)len + 6) return false;
  memcpy(out, r + 5, len);
  return true;
}

bool writeRegs(uint8_t id, uint8_t addr, const uint8_t *data, uint8_t len) {
  uint8_t p[24];
  p[0] = addr;
  memcpy(p + 1, data, len);
  uint8_t r[RESP_BUF];
  int     rl = 0;
  return sendRecv(id, INST_WRITE, p, (uint8_t)(len + 1), r, rl, true);
}

bool readFeedback(uint8_t id, Feedback &fb, uint16_t timeoutMs) {
  uint8_t d[PRES_BLOCK_LEN];
  if (!readRegs(id, REG_PRES_POS_L, PRES_BLOCK_LEN, d, timeoutMs)) {
    fb.ok = false;
    return false;
  }
  // 56..57 位置 / 58..59 速度 / 60..61 负载 / 62 电压 / 63 温度
  // 64..65 保留 / 66 运动中 / 67..68 保留 / 69..70 电流
  fb.pos     = (int16_t)((uint16_t)d[0] | ((uint16_t)d[1] << 8));
  fb.speed   = (int16_t)((uint16_t)d[2] | ((uint16_t)d[3] << 8));
  fb.load    = (int16_t)((uint16_t)d[4] | ((uint16_t)d[5] << 8));
  fb.voltage = d[6];
  fb.temp    = d[7];
  fb.moving  = d[10];
  fb.current = (int16_t)((uint16_t)d[13] | ((uint16_t)d[14] << 8));
  fb.mode    = 0;
  fb.ok      = true;
  return true;
}

bool moveTo(uint8_t id, uint16_t pos, uint16_t speed, uint8_t acc) {
  // 写 ACC(41) 起 7 字节：ACC + 目标位置 + 运行时间 + 运行速度
  //
  // ⚠️ INST_WRITE 的参数里**第一个字节必须是起始寄存器地址**。
  // 这里曾经漏掉它，于是舵机把 ACC 的值（默认 30）当成了地址，
  // 收到一条"往寄存器 30 写 6 字节"的指令 —— 越界/受保护，舵机回了个错误包，
  // 而 sendRecv 只看到"有回包"就返回成功。现象就是：
  // 使能之后舵机确实锁死了（TORQUE 是另一条正确的写指令），但按下去一点都不动。
  uint8_t p[8];
  p[0] = REG_ACC;                               // ← 起始寄存器地址，漏了必然不动
  p[1] = acc;
  p[2] = (uint8_t)(pos & 0xFF);
  p[3] = (uint8_t)(pos >> 8);
  p[4] = 0;
  p[5] = 0;                                     // 运行时间 0 = 不用时间控制
  p[6] = (uint8_t)(speed & 0xFF);
  p[7] = (uint8_t)(speed >> 8);
  uint8_t r[RESP_BUF];
  int     rl = 0;
  return sendRecv(id, INST_WRITE, p, 8, r, rl, true);
}

bool setTorque(uint8_t id, bool on) {
  const uint8_t v = on ? 1 : 0;
  return writeRegs(id, REG_TORQUE_EN, &v, 1);
}

bool setId(uint8_t oldId, uint8_t newId) {
  const uint8_t z = 0, o = 1;
  writeRegs(oldId, REG_LOCK, &z, 1);            // 解锁 EEPROM
  delay(10);
  writeRegs(oldId, REG_ID, &newId, 1);
  delay(300);                                   // 舵机应用新 ID 需要时间
  if (!ping(newId)) return false;
  writeRegs(newId, REG_LOCK, &o, 1);            // 重新上锁（失败无所谓）
  return true;
}

int scan(uint8_t maxId, uint8_t *found, int cap) {
  int n = 0;
  for (uint8_t id = 1; id <= maxId && n < cap; ++id) {
    if (ping(id)) found[n++] = id;
  }
  return n;
}

void syncMove(const SyncItem *items, int n) {
  if (n <= 0) return;
  if (n > 8) n = 8;
  uint8_t p[2 + 8 * 8];
  int     k = 0;
  p[k++] = REG_ACC;                             // 起始地址
  p[k++] = 7;                                   // 每个舵机写 7 字节
  for (int i = 0; i < n; ++i) {
    p[k++] = items[i].id;
    p[k++] = items[i].acc;
    p[k++] = (uint8_t)(items[i].pos & 0xFF);
    p[k++] = (uint8_t)(items[i].pos >> 8);
    p[k++] = 0;
    p[k++] = 0;
    p[k++] = (uint8_t)(items[i].speed & 0xFF);
    p[k++] = (uint8_t)(items[i].speed >> 8);
  }
  uint8_t r[RESP_BUF];
  int     rl = 0;
  sendRecv(BROADCAST_ID, INST_SYNC_WRITE, p, (uint8_t)k, r, rl, false);
}

int syncReadPos(const uint8_t *ids, int n, uint16_t *pos, uint16_t timeoutMs) {
  if (n <= 0) return 0;
  if (n > 16) n = 16;
  for (int i = 0; i < n; ++i) pos[i] = 0xFFFF;

  uint8_t p[2 + 16];
  int     k = 0;
  p[k++] = REG_PRES_POS_L;          // 56
  p[k++] = 2;                       // 每次读 2 字节（位置）
  for (int i = 0; i < n; ++i) p[k++] = ids[i];

  uint8_t       pkt[40];
  const uint8_t total = build(BROADCAST_ID, INST_SYNC_READ, p, (uint8_t)k, pkt);

  g_lastErr = 0;
  while (bus.available()) bus.read();
  bus.write(pkt, total);
  bus.flush();
  ++g_stats.tx;
  eatEcho(total);

  int          got = 0;
  uint8_t      r[RESP_BUF];        // 提到循环外，别每收一条就在栈上重开 96 字节
  const uint32_t t0 = millis();
  while (got < n) {
    const uint32_t spent = (uint32_t)(millis() - t0);
    if (spent >= timeoutMs) break;
    int rl = 0;
    if (!readPacket(0xFF, r, rl, (uint16_t)(timeoutMs - spent))) break;   // 0xFF = 收谁的都行
    if (rl < 8) continue;
    for (int i = 0; i < n; ++i) {
      if (ids[i] == r[2] && pos[i] == 0xFFFF) {
        pos[i] = (uint16_t)(r[5] | ((uint16_t)r[6] << 8));
        ++got;
        break;
      }
    }
  }
  return got;
}

}  // namespace scs

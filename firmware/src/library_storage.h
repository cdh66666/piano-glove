#pragma once
#include <stdint.h>

namespace librarystorage {
constexpr uint32_t maximumRawBytes=960128;
constexpr uint32_t chunkBytes=384;
constexpr uint32_t reserveBytes=8192;
inline bool validRawSize(uint32_t bytes){return bytes>=144&&bytes<=maximumRawBytes&&(bytes-128)%16==0;}
// PGL permits at most 24 hours: each time/duration varint uses at most four
// bytes, plus four event attributes. Preserve both old slot and raw staging
// until a complete compressed candidate has been verified.
inline uint32_t stagingSpace(uint32_t rawBytes){return rawBytes+132+((rawBytes-128)/16)*12+reserveBytes;}
}

#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
namespace pgl {
inline uint16_t u16(const uint8_t*p){return p[0]|uint16_t(p[1])<<8;}
inline uint32_t u32(const uint8_t*p){return p[0]|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;}
inline void put32(uint8_t*p,uint32_t x){for(int i=0;i<4;++i)p[i]=x>>(8*i);}
inline uint32_t crcByte(uint32_t crc,uint8_t b){crc^=b;for(int i=0;i<8;++i)crc=(crc>>1)^(0xEDB88320u&uint32_t(-int32_t(crc&1)));return crc;}
struct Event {uint32_t t,d;uint8_t pitch,finger,velocity,amplitude;};
inline Event event(const uint8_t*p){return {u32(p),u32(p+4),p[8],p[9],p[10],p[11]};}
inline void bytes(Event e,uint8_t*p){memset(p,0,16);put32(p,e.t);put32(p+4,e.d);p[8]=e.pitch;p[9]=e.finger;p[10]=e.velocity;p[11]=e.amplitude;}
struct Validator {
 uint32_t count=0,duration=0,expected=0,seen=0,previous=0,ends[5]={},crc=0xffffffff;
 bool header(const uint8_t*p,size_t size){
  count=u32(p+8);duration=u32(p+12);expected=u32(p+16);
  if(size!=128+size_t(count)*16||memcmp(p,"PGL1",4)||u16(p+4)!=1||u16(p+6)!=128||!count||count>60000||!duration||duration>86400000||!u16(p+20)||u16(p+20)>96||u16(p+22))return false;
  for(int i=24;i<24+u16(p+20);++i)if(!p[i])return false;
  for(int i=24+u16(p+20);i<128;++i)if(p[i])return false;
  for(int i=0;i<128;++i)crc=crcByte(crc,i>=16&&i<20?0:p[i]);return true;
 }
 bool add(const uint8_t*p){Event e=event(p);if(seen>=count||e.t<previous||e.t>duration||!e.d||e.d>duration-e.t||e.pitch>127||!e.finger||e.finger>5||!e.velocity||e.velocity>127||!e.amplitude||e.amplitude>100||u16(p+12)||u16(p+14)||ends[e.finger-1]>e.t)return false;
  previous=e.t;ends[e.finger-1]=e.t+e.d;++seen;for(int i=0;i<16;++i)crc=crcByte(crc,p[i]);return true;
 }
 bool finish()const{return seen==count&&(crc^0xffffffff)==expected;}
};
inline int varint(uint32_t x,uint8_t*p){int n=0;do{p[n]=uint8_t(x&127);x>>=7;if(x)p[n]|=128;++n;}while(x);return n;}
inline bool readVar(const uint8_t*p,size_t n,size_t&k,uint32_t&x){x=0;for(int j=0;j<5&&k<n;++j){uint8_t b=p[k++];if(j==4&&(b&0xf0))return false;x|=uint32_t(b&127)<<(j*7);if(!(b&128))return true;}return false;}
inline int pack(Event e,uint32_t prev,uint8_t*p){int n=varint(e.t-prev,p);n+=varint(e.d,p+n);p[n++]=e.pitch;p[n++]=e.finger;p[n++]=e.velocity;p[n++]=e.amplitude;return n;}
inline bool unpack(const uint8_t*p,size_t n,size_t&k,uint32_t prev,Event&e){uint32_t delta;if(!readVar(p,n,k,delta)||delta>0xffffffff-prev||!readVar(p,n,k,e.d)||k+4>n)return false;e.t=prev+delta;e.pitch=p[k++];e.finger=p[k++];e.velocity=p[k++];e.amplitude=p[k++];return true;}
}

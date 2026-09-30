#pragma once
#include <stdint.h>
// 0=ambiguous/invalid, 1=STS little-endian, 2=SCS big-endian.
// EEPROM limits are mutable; require a unique legal interpretation, not factory endpoints.
inline int identifyLimitEndian(const uint8_t *lo,const uint8_t *hi,uint16_t &mn,uint16_t &mx){
 const uint16_t ll=uint16_t(lo[0])|(uint16_t(lo[1])<<8),lh=uint16_t(hi[0])|(uint16_t(hi[1])<<8);
 const uint16_t bl=(uint16_t(lo[0])<<8)|lo[1],bh=(uint16_t(hi[0])<<8)|hi[1];
 const bool sts=ll<lh && lh<=4095,scs=bl<bh && bh<=1023;
 if(sts==scs)return 0;
 mn=sts?ll:bl;mx=sts?lh:bh;return sts?1:2;
}
inline uint16_t servoWord(const uint8_t *p,bool big){return big?((uint16_t(p[0])<<8)|p[1]):(uint16_t(p[0])|(uint16_t(p[1])<<8));}
inline int identifyMarkedLimits(const uint8_t*lo,const uint8_t*hi,uint8_t endian,uint16_t &mn,uint16_t &mx){
 if(endian>1)return 0;
 mn=servoWord(lo,endian==1);mx=servoWord(hi,endian==1);
 if(mn>=mx||mx>(endian==1?1023:4095))return 0;
 return endian==0?1:2;
}
inline bool normalizedStsSpeed(uint8_t endian,uint8_t phase,uint8_t resolution,uint8_t mode,uint16_t speed,uint16_t &raw){
 if(endian!=0||resolution!=1||mode!=0||speed<50||speed>8000)return false;
 raw=(phase&4)?speed:speed/50;return raw>0;
}
inline uint8_t benchMotionPayload(bool scs,uint16_t pos,uint16_t raw,uint8_t acc,uint8_t*p){
 uint8_t k=0;p[k++]=scs?42:41;if(!scs)p[k++]=acc;
 p[k++]=scs?pos>>8:pos&255;p[k++]=scs?pos&255:pos>>8;
 p[k++]=0;p[k++]=0;p[k++]=scs?raw>>8:raw&255;p[k++]=scs?raw&255:raw>>8;return k;
}
// Return write parameters including the first register address.
inline uint8_t motionPayload(bool scs,uint16_t pos,uint16_t speed,uint8_t acc,uint8_t *p){
 if(scs && (speed==0||speed>200))speed=200; // Project software cap, not a manufacturer rating.
 uint8_t k=0;p[k++]=scs?42:41;if(!scs)p[k++]=acc;
 p[k++]=scs?pos>>8:pos&255;p[k++]=scs?pos&255:pos>>8;
 p[k++]=0;p[k++]=0;
 p[k++]=scs?speed>>8:speed&255;p[k++]=scs?speed&255:speed>>8;return k;
}

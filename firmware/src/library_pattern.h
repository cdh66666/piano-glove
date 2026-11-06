#pragma once
#include <stdint.h>

// Device-local training timing. No transport, target, amplitude or direction
// decisions belong here: every phase still uses the existing calibrated goals.
namespace librarypattern {
inline bool nativeMotionEnded(uint32_t sampleMs,uint32_t commandMs,int speed,uint8_t moving){return int32_t(sampleMs-commandMs)>0&&speed==0&&moving==0;}
inline bool validRate(int rate){return rate>=50&&rate<=1000;}
inline bool validPatternRate(int rate){return rate==0||validRate(rate);}
inline int phaseTolerance(int requestedDistance,int baseTolerance){int half=requestedDistance/2;return half<baseTolerance?half:baseTolerance;}
inline bool phaseReady(int requestedDistance,int targetError,int baseTolerance){return targetError<=phaseTolerance(requestedDistance,baseTolerance);}
inline bool transitionReady(bool score,bool previousTargetReady,int distance,int tolerance){return !score||distance<=2*tolerance||previousTargetReady;}
inline bool eventHasReleaseTime(uint32_t remaining,int rate){return uint64_t(remaining)*100>=uint64_t(40)*rate;}
inline uint8_t length(int pattern){return pattern==2?2:5;}
inline uint8_t selected(int pattern,int index){
 static const uint8_t single[5]={1,2,4,8,16},combination[5]={3,12,20,9,18},alternating[2]={21,10};
 return pattern==0?single[index%5]:pattern==1?combination[index%5]:alternating[index%2];
}
struct Sequence {
 int pattern=0,repeats=1,rate=100;uint16_t step=0,total=0;uint32_t phaseStarted=0;
 bool begin(int id,int cycles,int speed,uint32_t now){
  if(id<0||id>2||cycles<1||cycles>20||!validPatternRate(speed))return false;
  pattern=id;repeats=cycles;rate=speed;step=0;total=length(id)*cycles*2;phaseStarted=now;return true;
 }
 bool fastest()const{return rate==0;}
 uint8_t mask()const{return step%2?0:selected(pattern,step/2);}
 uint32_t dwell()const{return fastest()?0:((step%2?18000u:35000u)+uint32_t(rate)-1)/uint32_t(rate);}
 bool due(uint32_t now,bool targetsArrived)const{return fastest()?targetsArrived:uint32_t(now-phaseStarted)>=dwell();}
 bool expired(uint32_t now,bool targetsArrived)const{(void)now;(void)targetsArrived;return false;}
 bool advance(uint32_t now){phaseStarted=fastest()?now:phaseStarted+dwell();++step;return step<total;}
 uint32_t minimumDuration()const{return fastest()?0:(53000u*length(pattern)*repeats+uint32_t(rate)-1)/uint32_t(rate);}
};
}

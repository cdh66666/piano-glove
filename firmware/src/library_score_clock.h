#pragma once
#include <stdint.h>

// Score time follows elapsed wall time at the requested tempo. Position
// feedback never pauses or rewinds the software music timeline.
namespace libraryclock {
// Score playback uses this independently of arrival feedback. Integrating at
// each observed wall time preserves fractional source milliseconds and tempo
// changes; handled event boundaries never rewind or pause this clock.
class WallClock {
 uint32_t value=0,wall=0;uint16_t fraction=0;
public:
 void start(uint32_t now){value=0;wall=now;fraction=0;}
 uint32_t elapsed()const{return value;}
 bool paused()const{return false;}
 uint32_t desired(uint32_t now,int rate){uint64_t advance=uint64_t(uint32_t(now-wall))*rate+fraction;wall=now;fraction=advance%100;uint64_t total=uint64_t(value)+advance/100;value=total>0xffffffffu?0xffffffffu:uint32_t(total);return value;}
};
}

#include "../src/cal_circle.h"
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
namespace scs {struct Profile{int range;}p; const Profile& profile(){return p;}}
struct Slot{int lo,hi,standby;bool max;};Slot g_slot[1];
int pressEnd(int){return g_slot[0].max?g_slot[0].hi:g_slot[0].lo;}
int releaseEnd(int){return g_slot[0].max?g_slot[0].lo:g_slot[0].hi;}
uint16_t pressPos(int s, uint8_t depthPct) {
  const Slot &sl = g_slot[s];
  if (depthPct > 100) depthPct = 100;
  const int range=scs::profile().range;
  const int from=calcircle::contains(sl.lo,sl.hi,sl.standby,range)?sl.standby:releaseEnd(s);
  const int to=pressEnd(s);
  const int distance=sl.lo>sl.hi?calcircle::delta(from,to,range):to-from;
  return (uint16_t)calcircle::wrap(from+distance*(int)depthPct/100,range);
}


int main(){assert(calcircle::span(504,31,1023)==551);assert(calcircle::valid(504,9,31,1023));assert(!calcircle::valid(504,300,31,1023));assert(!calcircle::valid(200,9,100,1023));for(int range=1023;range<=4095;range+=3072){
 scs::p.range=range;
 for(int n=1;n<=7;n++){
  assert(calcircle::valid(100,100,100+n,range));
  g_slot[0]={100,100+n,100,true};assert(pressPos(0,100)==100+n);
  g_slot[0]={100,100+n,100+n,false};assert(pressPos(0,100)==100);
  int lo=range-n+1,hi=0;assert(calcircle::valid(lo,lo,hi,range));
  assert(calcircle::contains(lo,hi,range,range));assert(!calcircle::contains(lo,hi,100,range));
  g_slot[0]={lo,hi,lo,true};assert(pressPos(0,100)==hi);
  assert(pressPos(0,50)==calcircle::wrap(lo+n/2,range));
  g_slot[0]={lo,hi,hi,false};assert(pressPos(0,100)==lo);
  assert(pressPos(0,50)==calcircle::wrap(-n/2,range));
 }
 assert(!calcircle::valid(100,100,100,range));assert(!calcircle::valid(range+1,0,5,range));
 assert(!calcircle::valid(range-2,100,2,range));
 assert(calcircle::delta(range-2,2,range)==5);assert(calcircle::delta(2,range-2,range)==-5);
}puts("actual pressPos + circular validity PASS: both families spans1..7, both directions, wrap and nonwrap, invalid endpoints/standby/zero");}

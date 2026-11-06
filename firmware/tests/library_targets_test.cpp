#include "../src/library_targets.h"
#include <assert.h>
#include <stdio.h>
#include <initializer_list>
int main(){
 for(bool scs:{true,false})for(int slot=0;slot<6;++slot){
  const int lo=scs?100:1000,hi=scs?900:2000,range=scs?1023:4095;
  const int low=lo,high=hi;
  const bool maximum=false;
  assert(librarytargets::pressMaximum(slot,scs)==maximum);
  const int released=maximum?low:high,down=maximum?high:low;
  assert(librarytargets::target(slot,scs,lo,hi,0,range,false,100)==released);
  assert(librarytargets::target(slot,scs,lo,hi,0,range,true,100)==down);
  for(int amplitude:{0,20,40,60,80,100}){
   int goal=librarytargets::target(slot,scs,lo,hi,0,range,true,amplitude);
   assert(goal==released+(down-released)*amplitude/100&&goal>=low&&goal<=high);
   assert(librarytargets::target(slot,scs,lo,hi,0,range,false,amplitude)==released);
  }
  int hardwareLo=low+10,hardwareHi=high-10;
  assert(librarytargets::target(slot,scs,lo,hi,hardwareLo,hardwareHi,true,100)==(maximum?hardwareHi:hardwareLo));
  assert(librarytargets::target(slot,scs,lo,hi,hardwareLo,hardwareHi,false,100)==(maximum?hardwareLo:hardwareHi));
  assert(librarytargets::target(slot,scs,lo,hi,0,range,true,-1)==-1);
  assert(librarytargets::target(slot,scs,lo,hi,0,range,true,101)==-1);
 }
 assert(librarytargets::target(-1,false,1000,2000,0,4095,true,100)==-1);
 assert(librarytargets::target(6,false,1000,2000,0,4095,true,100)==-1);
 assert(librarytargets::target(0,false,2000,1000,0,4095,true,100)==-1);
 assert(librarytargets::target(0,false,1000,2000,2500,3000,true,100)==-1);
 // Generic small/full spans: musical endpoints are no longer inset. ID1
 // keeps the high pose when released; ID2 remains the low-press piano thumb.
 for(bool scs:{false,true})for(int span:{1,4,7,100,237,600})for(int slot=0;slot<6;++slot){
  const int a=20+slot*7,b=a+span,range=scs?1023:4095;
  assert(librarytargets::softwareTarget(slot,scs,a,b,0,range,true,100)==a);
  assert(librarytargets::softwareTarget(slot,scs,a,b,0,range,false,100)==b);
  assert(librarytargets::target(slot,scs,a,b,0,range,true,100)==a);
 }
 for(bool scs:{true,false}){
  assert(librarytargets::repeatedReleaseTarget(2,scs,500,900,0,1023)==900);
  assert(librarytargets::repeatedReleaseTarget(2,scs,500,900,0,890)==890);
  assert(librarytargets::repeatedReleaseTarget(2,scs,500,900,950,1023)==-1);
  assert(librarytargets::repeatedReleaseTarget(0,scs,500,900,0,1023)==900);
 }
 puts("PASS actual LIB fixed targets: both models press low, STS thumb correction; all six amplitudes and hardware bounds");
}

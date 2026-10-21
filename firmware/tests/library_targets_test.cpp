#include "../src/library_targets.h"
#include <assert.h>
#include <stdio.h>
#include <initializer_list>
int main(){
 for(bool scs:{true,false})for(int slot=0;slot<6;++slot){
  const int lo=scs?100:1000,hi=scs?900:2000,range=scs?1023:4095;
  const int low=scs?106:1050,high=scs?894:1950;
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
 // Regression: STS ID2 must press low and lift high; ID1 stays lifted high.
 assert(librarytargets::target(1,false,1920,2422,0,4095,true,100)==1945);
 assert(librarytargets::target(1,false,1920,2422,0,4095,false,100)==2397);
 assert(librarytargets::target(0,false,1276,2287,0,4095,false,100)==2237);
 puts("PASS actual LIB fixed targets: both models press low, STS thumb correction; all six amplitudes and hardware bounds");
}

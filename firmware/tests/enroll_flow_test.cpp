#include "../src/enroll_flow.h"
#include <assert.h>
#include <stdio.h>
#include <algorithm>
#include <string.h>
static bool twice(EnrollFlow &f,uint32_t mask){f.observe(mask);return f.observe(mask);}
static void run(const int *ids){
 EnrollFlow f;f.start();twice(f,2);assert(f.phase==EnrollFlow::WAIT_EMPTY);twice(f,0);assert(f.phase==EnrollFlow::WAIT_FIRST);
 uint32_t bus=0;
 for(int i=0;i<6;++i){
  assert(twice(f,bus|(1ul<<ids[i])));assert(f.from==ids[i]&&f.to==20-i&&f.slot==i);
  bus|=1ul<<(20-i);bool action=twice(f,bus);
  if(i<5){assert(!action&&f.count==i+1&&f.next==i+2);}
  else assert(action&&f.from==20&&f.to==1&&f.slot==0);
 }
 for(int i=0;i<6;++i){
  assert(f.from==20-i&&f.to==i+1&&f.slot==i);
  bus=(bus&~(1ul<<(20-i)))|(1ul<<(i+1));bool action=twice(f,bus);
  if(i<5)assert(action);else assert(!action&&f.phase==EnrollFlow::DONE);
 }
 assert(bus==0x7e && f.count==6);
}
int main(){
 int defaults[]={1,1,1,1,1,1};run(defaults);
 int ids[]={1,2,3,4,5,6},n=0;do{run(ids);++n;}while(std::next_permutation(ids,ids+6));assert(n==720);
 EnrollFlow f;
 for(uint32_t bad:{(1ul<<1)|(1ul<<2),1ul<<0,1ul<<21}){f.start();twice(f,0);f.observe(bad);assert(f.phase==EnrollFlow::CONFLICT);}
 f.start();twice(f,0);twice(f,2);f.observe(2);assert(f.phase==EnrollFlow::VERIFY_ASSIGN&&f.missingScans==1);f.observe(2,500);f.observe(2,1000);assert(f.phase==EnrollFlow::CONFLICT);
 f.start();twice(f,0);twice(f,2);twice(f,1ul<<20);f.observe(0);assert(f.phase==EnrollFlow::WAIT_NEXT);f.observe(0,500);f.observe(0,1000);assert(f.phase==EnrollFlow::CONFLICT);
 for(int p=EnrollFlow::WAIT_EMPTY;p<=EnrollFlow::VERIFY_FINAL;++p){f.start();f.phase=(EnrollFlow::Phase)p;f.stop();assert(!f.active()&&!f.observe(2));}
 f.start();f.fail();assert(!f.active()&&!f.observe(2));
 // Old numbered servos mixed with replacement factory-ID1 servos remain
 // unique on the bus because every accepted servo is isolated first.
 int mixed1[]={1,2,1,4,5,6};run(mixed1);
 int mixed2[]={2,1,1,4,5,6};run(mixed2);
 int mixed3[]={1,1,3,1,5,6};run(mixed3);
 // New insertion during rename verification remains a conflict, even when
 // it is a legitimate factory replacement address.
 f.start();twice(f,0);assert(twice(f,2));f.observe((1ul<<20)|2);assert(f.phase==EnrollFlow::CONFLICT);
 f.start();twice(f,0);assert(twice(f,4));f.observe((1ul<<20)|2);assert(f.phase==EnrollFlow::CONFLICT);
 // Missing staged servo blocks writes and retries; multiple additions stop immediately.
 f.start();twice(f,0);assert(twice(f,4));twice(f,1ul<<20);f.observe(2);assert(f.phase==EnrollFlow::WAIT_NEXT);f.observe(2,500);f.observe(2,1000);assert(f.phase==EnrollFlow::CONFLICT);
 f.start();twice(f,0);assert(twice(f,4));twice(f,1ul<<20);f.observe((1ul<<20)|2|(1ul<<3));assert(f.phase==EnrollFlow::CONFLICT);
 // Restart in original physical-slot order, with already isolated IDs20/19.
 int partial[]={20,19,1,4,5,6};run(partial);
 int isolated[]={20,19,18,17,16,15};run(isolated);
 int finalPartial[]={1,2,18,17,16,15};run(finalPartial);
 // Fast repeated misses within 1000ms remain safe retry, never a write.
 f.start();twice(f,0);assert(twice(f,2));twice(f,1ul<<20);
 for(uint32_t t=100;t<1000;t+=100)assert(!f.observe(2,t)&&f.active());
 assert(!f.observe(2,1100)&&f.phase==EnrollFlow::CONFLICT&&!strcmp(f.reason,"expected_missing_persistent"));
 // A missed staged reply blocks writes but recovers after two complete scans.
 f.start();twice(f,0);assert(twice(f,2));twice(f,1ul<<20);assert(f.phase==EnrollFlow::WAIT_NEXT);
 assert(!f.observe(2)&&f.active()&&f.missingScans==1&&!strcmp(f.reason,"expected_missing_retry"));
 assert(!f.observe((1ul<<20)|2));assert(f.observe((1ul<<20)|2)&&f.from==1&&f.to==19);
 // The same no-write rule applies while verifying an assignment.
 assert(!f.observe(1ul<<19)&&f.phase==EnrollFlow::VERIFY_ASSIGN);
 assert(!f.observe((1ul<<20)|(1ul<<19)));assert(!f.observe((1ul<<20)|(1ul<<19)));assert(f.phase==EnrollFlow::WAIT_NEXT);
 puts("flow3 PASS: default1, all720 permutations, old/new mixed1-2-1 and2-1-1, strict scan/rename guards, stop, failure, slot-order mapping");
}

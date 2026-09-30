#pragma once
#include <stdint.h>
// Only IDs 1..20 are scanned. Same-address physical duplicates cannot be distinguished.
struct EnrollFlow {
 enum Phase { OFF,WAIT_EMPTY,WAIT_FIRST,WAIT_NEXT,VERIFY_ASSIGN,VERIFY_FINAL,DONE,CONFLICT,FAILED,PAUSED_BAUD } phase=OFF;
 uint8_t next=1,count=0,from=0,to=0,slot=0,stable=0,mode=0,finalSlot=0,missingScans=0;
 uint32_t expected=0,previous=0xffffffff,originals=0,lastSeen=0,lastExpected=0,missingSinceMs=0;
 const char *reason="none";
 bool active() const {return phase>=WAIT_EMPTY && phase<=VERIFY_FINAL;}
 const char *name() const {static const char *n[]={"OFF","WAIT_EMPTY","WAIT_FIRST","WAIT_NEXT","VERIFY_ASSIGN","VERIFY_FINAL","DONE","CONFLICT","FAILED","PAUSED_BAUD"};return n[phase];}
 void start(){*this=EnrollFlow();phase=WAIT_EMPTY;}
 void stop(){phase=OFF;from=to=0;}
 void fail(){phase=FAILED;from=to=0;}
 void conflict(const char *why="bus_conflict"){phase=CONFLICT;from=to=0;reason=why;}
 void transition(Phase p){phase=p;stable=0;missingScans=0;previous=0xffffffff;}
 bool finalize(){slot=finalSlot;from=20-finalSlot;to=1+finalSlot;expected=(expected&~(1ul<<from))|(1ul<<to);transition(VERIFY_FINAL);return true;}
 bool observe(uint32_t seen,uint32_t nowMs=0){
  from=to=0;lastSeen=seen;lastExpected=expected;if(!active())return false;
  if(phase==WAIT_EMPTY && seen){stable=0;return false;}
  uint32_t added=seen&~expected;
  if(phase!=WAIT_EMPTY && (seen&expected)!=expected){
   stable=0;previous=0xffffffff;reason="expected_missing_retry";
   if(!missingScans)missingSinceMs=nowMs;
   if(missingScans<255)++missingScans;
   if(missingScans>=3&&uint32_t(nowMs-missingSinceMs)>=1000)conflict("expected_missing_persistent");
   return false; // Never write while a required staged device is missing.
  }
  missingScans=0;reason="none";
  if(phase!=WAIT_EMPTY&&added){
   if(phase==VERIFY_ASSIGN||phase==VERIFY_FINAL){conflict("inserted_during_verification");return false;}
   if(added&(added-1)){conflict("multiple_new_addresses");return false;}
   if(added&~0x1ffffeul){conflict("source_outside_1to20");return false;}
  }
  stable=seen==previous?uint8_t(stable+1):1;previous=seen;if(stable<2)return false;
  if(phase==WAIT_EMPTY){transition(WAIT_FIRST);return false;}
  if(phase==VERIFY_FINAL){if(++finalSlot<6)return finalize();transition(DONE);return false;}
  if(phase==VERIFY_ASSIGN){++count;next=count<6?count+1:6;if(count==6)return finalize();transition(WAIT_NEXT);return false;}
  if(!added){stable=0;return false;}
  uint8_t source=1;while(!(added&(1ul<<source)))++source;
  // Every accepted servo has already been isolated at ID20..15 before waiting
  // for the next one. Its original ID is therefore free, including a new
  // factory-ID1 servo following previously numbered servos. Scan-set guards
  // above still require all isolated IDs, exactly one new address, and two
  // stable scans; VERIFY phases still reject any new address.
  if(count==0)mode=source==1?1:2;
  else if((mode==1&&source!=1)||(mode==2&&source==1))mode=3; // Informational mixed mode.
  originals|=added;slot=count;from=source;to=20-count;expected|=1ul<<to;transition(VERIFY_ASSIGN);return true;
 }
};

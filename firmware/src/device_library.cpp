#include "device_library.h"
#include "score_format.h"
#include "glove.h"
#include "scs_bus.h"
#include "cal_circle.h"
#include "software_ui.h"
#include <WiFi.h>
#include <WebServer.h>
#include <SPIFFS.h>
#include <esp_partition.h>
#include <WiFiUdp.h>
#include <esp_netif.h>
#include <dhcpserver/dhcpserver.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "profile_limits.h"
#include "library_recovery.h"
#include "library_targets.h"
#include "library_hold.h"
#include "library_pattern.h"
#include "library_score_clock.h"
#include "library_controller.h"
#include "library_storage.h"
#include "library_portal_dns.h"
namespace library {
static WebServer web(80);
static WiFiUDP portalDns;
static bool portalDnsReady=false,portalDhcpReady=false;
static uint32_t portalDnsQueries=0,portalProbes=0,portalLandings=0,portalRedirects=0,portalLastAt=0;
static uint8_t portalDnsOfferBefore=0,portalDnsOfferAfter=0;
static int portalDhcpError=0;
static char portalLastPath[97]={},portalLastHost[97]={},portalLastAgent[161]={},portalLastDns[97]={};
static uint8_t portalQuery[512],portalAnswer[512];
static bool ready=false,ap=false;
static bool exclusiveBusy=false;
static bool offhandTestMode=false;
static uint8_t recoveryMask=0;
static uint16_t hardwareMinimum[6]={},hardwareMaximum[6]={};
void setExclusiveBusy(bool value){exclusiveBusy=value;}
struct Metadata {bool valid=false;uint32_t bytes=0,stored=0,notes=0,duration=0;char title[97]={};};
static Metadata meta[101];
static int cachedCount=0;
static void cacheEntry(int slot,const uint8_t*h,uint32_t stored){if(!meta[slot].valid)++cachedCount;meta[slot].valid=true;meta[slot].bytes=128+pgl::u32(h+8)*16;meta[slot].stored=stored;meta[slot].notes=pgl::u32(h+8);meta[slot].duration=pgl::u32(h+12);memcpy(meta[slot].title,h+24,pgl::u16(h+20));meta[slot].title[pgl::u16(h+20)]=0;}
static char apName[32]="PianoGlove";
static File incoming,playing;
static int uploadSlot=0,currentSlot=0;
static String uploadOwner="none";
static String uploadController,controller;
static uint32_t expectedBytes=0,received=0,uploadLast=0,started=0,keepAt=0,previousEvent=0,index=0,count=0,duration=0;
static uint16_t tempo=100;
static uint8_t amp=100,mask=0,hold=100;
static uint8_t requestedHold=100;
static uint32_t endTimes[5]={};
static bool running=false,training=false,nextReady=false;
static bool patternRunning=false;
static uint8_t patternChangedMask=0;
static librarypattern::Sequence patternSequence;
static libraryclock::WallClock scoreClock;
static bool boundaryPending=false,boundaryReleaseStarted=false;
static uint32_t boundaryAt=0,lastScoreBoundary=0,candidateEnds[5]={};
static uint8_t candidateMask=0,boundaryRepeatMask=0,boundaryReleaseMask=0;
static uint8_t repeatLiftMask=0,candidateLiftMask=0;
static uint32_t playedEventCount=0,candidateEventCount=0;
static bool initializing=false;
static uint32_t feedbackAt=0,poseAt=0;
static uint32_t positionsAt=0,positionSampleMs[6]={},healthSampleMs[6]={};
static uint8_t movingMask=0,healthValidMask=0,positionValidMask=0;
static uint32_t axisPoseAt[6]={};
static uint8_t feedbackSlot=0;
static int16_t actual[6]={},poseFrom[6]={};
static uint16_t poseTargets[6]={},originalLimit[6]={},appliedLimit[6]={};
static uint8_t positionsReady=0,limitsSaved=0,volts[6]={},temps[6]={};
static int16_t currentRaw[6]={};
static bool resistanceSupported=false;
static uint8_t enabledMask=0;
static pgl::Event nextEvent;
static String failure="none",owner="none";
static String lastStopReason="none";
static uint32_t lastStopAt=0,lastPrepareMs=0,lastPoseMs=0;
static void recordStop(const String&reason){lastStopReason=reason;lastStopAt=millis();Serial.printf("LIB_STOP reason=%s owner=%s slot=%d mask=%u\n",reason.c_str(),owner.c_str(),currentSlot,unsigned(mask));}
static String path(int slot){return String("/s")+slot+".pgc";}
static String escape(String s){String out;out.reserve(s.length()+8);for(size_t i=0;i<s.length();++i){uint8_t c=s[i];if(c<32){char value[7];snprintf(value,sizeof(value),"\\u%04x",c);out+=value;}else if(c=='"'||c=='\\'){out+='\\';out+=char(c);}else out+=char(c);}return out;}
static bool validSlot(int s){return s>=1&&s<=100;}
static String requestController(const char*who){if(strcmp(who,"wifi"))return "";return web.hasHeader("X-Piano-Controller")?web.header("X-Piano-Controller"):web.arg("controller");}
static bool validController(const char*who){String token=requestController(who);if(!librarycontroller::validToken(token.c_str(),token.length())){failure="controller_token_invalid";return false;}return true;}
static bool motionOwnerMatches(const char*who){if(!validController(who))return false;String token=requestController(who);if(!librarycontroller::matches(running,owner==who,controller.c_str(),controller.length(),token.c_str(),token.length())){failure="controller_mismatch";return false;}return true;}
static void abortUpload(){if(incoming)incoming.close();SPIFFS.remove("/upload.tmp");uploadSlot=0;expectedBytes=received=0;uploadOwner="none";uploadController="";}
static bool ownerMatches(const char*who){if(!validController(who))return false;if(incoming||uploadSlot){if(uploadOwner!=who){failure="upload_owned_by_other_transport";return false;}if(uploadController!=requestController(who)){failure="controller_mismatch";return false;}}return true;}
static bool startUpload(int slot,uint32_t bytes,const char*who){
 if(!ready){failure="storage_not_ready";return false;}
 if(running){failure="motion_busy";return false;}
 if(!validSlot(slot)){failure="slot_out_of_range";return false;}
 if(!librarystorage::validRawSize(bytes)){failure="pgl_size_invalid";return false;}
 if(!ownerMatches(who))return false;
 abortUpload();uint32_t free=SPIFFS.totalBytes()-SPIFFS.usedBytes();
 if(librarystorage::stagingSpace(bytes)>free){failure="storage_full";return false;}
 incoming=SPIFFS.open("/upload.tmp",FILE_WRITE);if(!incoming){failure="open_failed";return false;}
 uploadSlot=slot;expectedBytes=bytes;uploadOwner=who;uploadController=requestController(who);uploadLast=millis();failure="none";return true;
}
static bool chunk(const uint8_t*p,size_t n){if(!incoming){failure="upload_not_started";return false;}if(!n||received>expectedBytes||n>expectedBytes-received){failure="upload_chunk_bounds";abortUpload();return false;}if(incoming.write(p,n)!=n){failure="upload_write_failed";abortUpload();return false;}received+=n;uploadLast=millis();failure="none";return true;}
// All library/file handlers execute synchronously on Arduino's one loop task.
// Keep storage scratch off its stack. Playback has its own buffer and cannot
// run during upload, verification or download.
static uint8_t storageReadBuffer[1024],playReadBuffer[1024],compressionBuffer[1024],usbChunkBuffer[384];
static void storageDiagnostics(const char *phase){Serial.printf("LIB_STORAGE phase=%s stack_free=%u heap_free=%u heap_largest=%u\n",phase,unsigned(uxTaskGetStackHighWaterMark(nullptr)),unsigned(ESP.getFreeHeap()),unsigned(ESP.getMaxAllocHeap()));}
static bool readExact(File &f,uint8_t*p,size_t n){return f.read(p,n)==n;}
static bool openScore(int slot,File &f,uint8_t*h,bool verify=true);
static bool openScorePath(const String&name,File &f,uint8_t*h,bool verify=true);
static bool validateRaw(File &f,pgl::Validator &v,uint8_t*header){
 if(!f||f.size()<144||!readExact(f,header,128)||!v.header(header,f.size()))return false;
 uint8_t b[16];for(uint32_t i=0;i<v.count;++i){if(!readExact(f,b,16)||!v.add(b))return false;if(!(i%256))delay(0);}return v.finish();
}
static bool commit(){
 if(!incoming||received!=expectedBytes){failure="incomplete";abortUpload();return false;}
 storageDiagnostics("commit_begin");
 incoming.close();File raw=SPIFFS.open("/upload.tmp",FILE_READ);uint8_t header[128];pgl::Validator validator;
 if(!validateRaw(raw,validator,header)){raw.close();failure="invalid_pgl_crc_or_events";abortUpload();return false;}
 if(!raw.seek(128)){raw.close();failure="raw_seek_failed";abortUpload();return false;}SPIFFS.remove("/compressed.tmp");File compressed=SPIFFS.open("/compressed.tmp",FILE_WRITE);
 if(!compressed){raw.close();failure="compress_open";abortUpload();return false;}
 bool ok=compressed.write((const uint8_t*)"PGC1",4)==4&&compressed.write(header,128)==128;
 uint32_t prev=0;uint8_t eventBytes[16],packed[14];size_t buffered=0;
 for(uint32_t i=0;ok&&i<validator.count;++i){if(!readExact(raw,eventBytes,16)){ok=false;break;}pgl::Event e=pgl::event(eventBytes);int n=pgl::pack(e,prev,packed);if(n<=0||size_t(n)>sizeof(packed)){ok=false;break;}if(buffered+size_t(n)>sizeof(compressionBuffer)){ok=compressed.write(compressionBuffer,buffered)==buffered;buffered=0;if(!ok)break;}memcpy(compressionBuffer+buffered,packed,n);buffered+=n;prev=e.t;if(!(i%256))delay(0);}
 if(ok&&buffered)ok=compressed.write(compressionBuffer,buffered)==buffered;
 compressed.close();raw.close();int slot=uploadSlot;abortUpload();
 if(!ok){SPIFFS.remove("/compressed.tmp");failure="storage_full_or_write_failed";return false;}
 bool stagedValid=openScorePath("/compressed.tmp",raw,header);raw.close();
 if(!stagedValid){SPIFFS.remove("/compressed.tmp");failure="compressed_staging_crc_failed";return false;}
 String target=path(slot),backup=target+".bak";
 if(SPIFFS.exists(backup)){bool primaryValid=openScore(slot,raw,header);raw.close();if(!primaryValid||!SPIFFS.remove(backup)){SPIFFS.remove("/compressed.tmp");failure="storage_recovery_required";return false;}}
 if(SPIFFS.exists(target)&&!SPIFFS.rename(target,backup)){SPIFFS.remove("/compressed.tmp");failure="replace_backup_failed";return false;}
 if(!SPIFFS.rename("/compressed.tmp",target)){bool restored=!SPIFFS.exists(backup)||SPIFFS.rename(backup,target);SPIFFS.remove("/compressed.tmp");if(!restored&&meta[slot].valid){meta[slot].valid=false;--cachedCount;}failure=restored?"commit_rename_failed":"commit_rollback_failed";return false;}
 bool verified=openScore(slot,raw,header);uint32_t stored=verified?raw.size():0;raw.close();
 if(!verified){bool restored=SPIFFS.remove(target);if(SPIFFS.exists(backup))restored=restored&&SPIFFS.rename(backup,target);if(!restored&&meta[slot].valid){meta[slot].valid=false;--cachedCount;}failure=restored?"compressed_readback_crc_failed":"commit_rollback_failed";return false;}
 SPIFFS.remove(backup);cacheEntry(slot,header,stored);failure="none";storageDiagnostics("commit_done");return true;
}
static bool readCompressedEvent(File &f,uint32_t prev,pgl::Event &event){
 uint8_t p[14];size_t k=0;for(int field=0;field<2;++field){bool end=false;for(int n=0;n<5;++n){if(!readExact(f,p+k,1))return false;if(!(p[k++]&128)){end=true;break;}}if(!end)return false;}
 if(!readExact(f,p+k,4))return false;k+=4;size_t offset=0;return pgl::unpack(p,k,offset,prev,event)&&offset==k;
}
class EventReader {
 File &file;uint8_t *buffer;size_t bufferSize,at=0,end=0;
 bool byte(uint8_t&b){if(at==end){end=file.read(buffer,bufferSize);at=0;if(!end)return false;}b=buffer[at++];return true;}
public:
 explicit EventReader(File&f,uint8_t*storage,size_t capacity):file(f),buffer(storage),bufferSize(capacity){}
 void reset(){at=end=0;}
 bool event(uint32_t prev,pgl::Event&e){uint8_t p[14];size_t k=0;for(int field=0;field<2;++field){bool terminated=false;for(int j=0;j<5;++j){if(!byte(p[k]))return false;if(!(p[k++]&128)){terminated=true;break;}}if(!terminated)return false;}for(int j=0;j<4;++j)if(!byte(p[k++]))return false;size_t offset=0;return pgl::unpack(p,k,offset,prev,e)&&offset==k;}
 bool exhausted()const{return at==end&&file.position()==file.size();}
};
static EventReader playReader(playing,playReadBuffer,sizeof(playReadBuffer));
static bool openScore(int slot,File &f,uint8_t*h,bool verify){
 if(!validSlot(slot))return false;return openScorePath(path(slot),f,h,verify);
}
static bool openScorePath(const String&name,File &f,uint8_t*h,bool verify){
 f=SPIFFS.open(name,FILE_READ);uint8_t magic[4];
 if(!f||!readExact(f,magic,4)||memcmp(magic,"PGC1",4)||!readExact(f,h,128))return false;
 pgl::Validator v;if(!v.header(h,128+size_t(pgl::u32(h+8))*16))return false;
 if(verify){uint32_t prev=0;uint8_t b[16];pgl::Event event;EventReader reader(f,storageReadBuffer,sizeof(storageReadBuffer));
  for(uint32_t i=0;i<v.count;++i){if(!reader.event(prev,event))return false;pgl::bytes(event,b);if(!v.add(b))return false;prev=event.t;if(!(i%256))delay(0);}
  if(!v.finish()||!reader.exhausted()||!f.seek(132))return false;
 }return true;
}
static bool recoverStoredSlot(int slot){
 String backup=path(slot)+".bak";if(!SPIFFS.exists(backup))return true;
 File candidate;uint8_t header[128];bool primaryValid=openScore(slot,candidate,header);candidate.close();
 if(primaryValid){if(SPIFFS.remove(backup))return true;failure="storage_recovery_required";return false;}
 bool backupValid=openScorePath(backup,candidate,header);candidate.close();
 if(!backupValid){failure="storage_backup_corrupt_preserved";return false;}
 if((SPIFFS.exists(path(slot))&&!SPIFFS.remove(path(slot)))||!SPIFFS.rename(backup,path(slot))){failure="storage_recovery_required";return false;}
 return true;
}
static String entry(int slot){const auto&m=meta[slot];if(!m.valid)return "";return "{\"slot\":"+String(slot)+",\"title\":\""+escape(m.title)+"\",\"bytes\":"+String(m.bytes)+",\"stored\":"+String(m.stored)+",\"notes\":"+String(m.notes)+",\"duration_ms\":"+String(m.duration)+"}";}
static int libraryCount(){return cachedCount;}
static bool deleteScore(int slot){if(!ready){failure="storage_not_ready";return false;}if(running){failure="motion_busy";return false;}if(incoming||uploadSlot){failure="upload_active_finish_or_abort_first";return false;}if(!validSlot(slot)){failure="slot_out_of_range";return false;}if(!meta[slot].valid){failure="score_missing_or_corrupt";return false;}if(!SPIFFS.remove(path(slot))){failure="delete_failed";return false;}meta[slot].valid=false;--cachedCount;failure="none";return true;}
static String listing(){String json="{\"ready\":"+String(ready?"true":"false")+",\"max\":100,\"count\":"+String(libraryCount())+",\"total\":"+String(SPIFFS.totalBytes())+",\"used\":"+String(SPIFFS.usedBytes())+",\"free\":"+String(SPIFFS.totalBytes()-SPIFFS.usedBytes())+",\"slots\":[";bool comma=false;for(int slot=1;slot<=100;++slot){String item=entry(slot);if(item.length()){if(comma)json+=",";json+=item;comma=true;}}return json+"]}";}
static uint32_t elapsed(){if(!running||initializing)return 0;return training?millis()-started:min(duration,scoreClock.desired(millis(),tempo));}
static int scoreLimit(){return -1;} // Continuous score time has no arrival/event barrier.
// Read idle positions on request; never re-arm, restore torque or resend goals.
static void refreshIdlePositions(){
 if(running)return;
 positionValidMask=0;
 if(exclusiveBusy||glove::autoActive()||glove::mountActive()||glove::benchActive()||glove::rateActive()||glove::sweepActive())return;
 uint8_t ids[6];for(int s=0;s<6;++s){ids[s]=glove::slot(s).id;if(!ids[s]||ids[s]>=scs::BROADCAST_ID)return;for(int before=0;before<s;++before)if(ids[before]==ids[s])return;}
 uint16_t positions[6];const uint32_t sampled=millis();
 if(scs::syncReadPos(ids,6,positions,scs::positionReadBudget(6))!=6||scs::lastError())return;
 for(int s=0;s<6;++s)if(positions[s]>scs::profile().range)return;
 for(int s=0;s<6;++s){actual[s]=positions[s];glove::slot(s).last=positions[s];positionSampleMs[s]=sampled;}
 positionValidMask=0x3f;
}
static bool calibrationValid(int s){const auto&sl=glove::slot(s);return sl.valid&&sl.lo<sl.hi&&sl.hi<=scs::profile().range;}
static bool patternPreparationReady(){
 if(positionValidMask!=0x3f)return false;
 const int tolerance=scs::profile().family==scs::Family::SCS?35:114;
 for(int s=0;s<6;++s)if(abs(int(poseTargets[s])-actual[s])>tolerance)return false;
 return true;
}
static bool patternPhaseReady(){
 const int baseTolerance=scs::profile().family==scs::Family::SCS?35:114;
 for(int s=0;s<6;++s)if(patternChangedMask&(1<<s)){
  if(!(positionValidMask&(1<<s))||!librarypattern::phaseReady(abs(int(poseTargets[s])-poseFrom[s]),abs(int(poseTargets[s])-actual[s]),baseTolerance))return false;
 }
 return true;
}
static String state(){
 refreshIdlePositions();const uint32_t now=millis();String json="{\"score_clock\":\"continuous-v1\",\"calibration_advisory\":true,\"active\":"+String(running?"true":"false")+",\"initializing\":"+String(initializing?"true":"false")+",\"mode\":\""+String(patternRunning?"pattern":training?"train":"score")+"\",\"slot\":"+String(currentSlot)+",\"elapsed_ms\":"+String(elapsed())+",\"duration_ms\":"+String(duration)+",\"tempo\":"+String(tempo)+",\"mask\":"+String(mask)+",\"hold\":"+String(hold)+",\"hold_variable\":"+String(resistanceSupported?"true":"false")+",\"owner\":\""+owner+"\",\"error\":\""+escape(failure)+"\",\"device_ms\":"+String(now)+",\"moving_mask\":"+String(movingMask)+",\"pattern\":"+String(patternSequence.pattern)+",\"pattern_step\":"+String(patternSequence.step)+",\"pattern_total\":"+String(patternSequence.total)+",\"fastest\":"+String(patternRunning&&patternSequence.fastest()?"true":"false")+",\"clock_paused\":"+String("false")+",\"clock_limit_ms\":"+String(scoreLimit()<0?"null":String(scoreLimit()))+",\"encoder_range\":"+String(scs::profile().range)+",\"feedback\":[";
 for(int s=0;s<6;++s){const auto&sl=glove::slot(s);int margin=librarypolicy::margin(sl.lo,sl.hi,scs::profile().family==scs::Family::SCS);if(s)json+=",";json+="{\"id\":"+String(s+1)+",\"position\":"+String(actual[s])+",\"target\":"+String(poseTargets[s])+",\"voltage_raw\":"+String(volts[s])+",\"temperature\":"+String(temps[s])+",\"current_raw\":"+String(currentRaw[s])+",\"hold_limit\":"+String(appliedLimit[s])+",\"sample_age_ms\":"+String(now-positionSampleMs[s])+",\"position_age_ms\":"+String(now-positionSampleMs[s])+",\"position_sample_ms\":"+String(positionSampleMs[s])+",\"pos_valid\":"+String((positionValidMask&(1<<s))?"true":"false")+",\"position_valid\":"+String((positionValidMask&(1<<s))?"true":"false")+",\"health_age_ms\":"+String((healthValidMask&(1<<s))?now-healthSampleMs[s]:0)+",\"health_valid\":"+String((healthValidMask&(1<<s))?"true":"false")+",\"min\":"+String(sl.lo)+",\"max\":"+String(sl.hi)+",\"allowed_min\":"+String(max(0,int(sl.lo)-margin))+",\"allowed_max\":"+String(min(int(scs::profile().range),int(sl.hi)+margin))+",\"calibration_valid\":"+String(calibrationValid(s)?"true":"false")+"}";}
 return json+"],\"pv\":"+String(positionValidMask)+",\"score_index\":"+String(playedEventCount)+",\"score_total\":"+String(count)+"}";
}
static String compactState(){
 refreshIdlePositions();const uint32_t now=millis();int ownerCode=owner=="usb"?1:(owner=="wifi"?2:0);
 String json="{\"v\":1,\"ct\":1,\"ca\":1,\"a\":"+String(running?1:0)+",\"i\":"+String(initializing?1:0)+",\"m\":"+String(patternRunning?2:training?1:0)+",\"s\":"+String(currentSlot)+",\"t\":"+String(elapsed())+",\"d\":"+String(duration)+",\"q\":"+String(tempo)+",\"k\":"+String(mask)+",\"h\":"+String(hold)+",\"r\":"+String(resistanceSupported?1:0)+",\"o\":"+String(ownerCode)+",\"e\":\""+escape(failure)+"\",\"x\":"+String(offhandTestMode?1:0)+",\"z\":"+String(recoveryMask)+",\"p\":"+String(scs::profile().family==scs::Family::SCS?1:0)+",\"l\":\""+escape(lastStopReason)+"\",\"la\":"+String(lastStopAt)+",\"pa\":"+String(lastPrepareMs)+",\"pm\":"+String(lastPoseMs)+",\"ts\":"+String(now)+",\"mm\":"+String(movingMask)+",\"pt\":"+String(patternSequence.pattern)+",\"ps\":"+String(patternSequence.step)+",\"pc\":"+String(patternSequence.total)+",\"pf\":"+String(patternRunning&&patternSequence.fastest()?1:0)+",\"cp\":"+String(0)+",\"cl\":"+String(scoreLimit())+",\"er\":"+String(scs::profile().range)+",\"b\":[";
 for(int s=0;s<6;++s){if(s)json+=",";const auto&sl=glove::slot(s);json+="["+String(sl.lo)+","+String(sl.hi)+","+String(librarypolicy::margin(sl.lo,sl.hi,scs::profile().family==scs::Family::SCS))+","+String(calibrationValid(s)?1:0)+"]";}json+="],\"f\":[";
 for(int s=0;s<6;++s){if(s)json+=",";json+="["+String(actual[s])+","+String(poseTargets[s])+","+String(now-positionSampleMs[s])+","+String(volts[s])+","+String(temps[s])+","+String(currentRaw[s])+","+String(appliedLimit[s])+","+String((healthValidMask&(1<<s))?now-healthSampleMs[s]:0)+","+String((healthValidMask&(1<<s))?1:0)+"]";}
 return json+"],\"pv\":"+String(positionValidMask)+",\"si\":"+String(playedEventCount)+",\"sn\":"+String(count)+"}";
}
static bool writeLimit(int s,uint16_t limit){uint8_t data[2]={uint8_t(limit),uint8_t(limit>>8)},back[2]={};if(!scs::writeRegs(s+1,48,data,2)||scs::lastError()||!scs::readRegs(s+1,48,2,back)||scs::lastError()||pgl::u16(back)!=limit)return false;appliedLimit[s]=limit;return true;}
void stop(const char *reason){bool wasActive=running;if(wasActive)recordStop(reason);running=false;training=false;patternRunning=false;patternChangedMask=0;initializing=false;boundaryPending=boundaryReleaseStarted=false;repeatLiftMask=candidateLiftMask=0;mask=0;recoveryMask=0;movingMask=0;nextReady=false;if(playing)playing.close();owner="none";controller="";failure=reason;if(wasActive)glove::safe();for(int s=0;s<6;++s)if(limitsSaved&(1<<s)){if(writeLimit(s,originalLimit[s]))limitsSaved&=~(1<<s);else{failure="hold_limit_restore_failed";recordStop(failure);}}enabledMask=0;}
bool active(){return running;}
static bool keep(const char *who){if(!motionOwnerMatches(who))return false;if(running)keepAt=millis();return true;}
static void tickScoreTimeline();
static bool changeTempo(int rate,const char *who){if(!librarypattern::validRate(rate)){failure="tempo_out_of_range";return false;}if(!motionOwnerMatches(who))return false;if(running&&!training&&!initializing)tickScoreTimeline();tempo=rate;if(patternRunning){patternSequence.rate=rate;duration=patternSequence.minimumDuration();}if(running)keepAt=millis();return true;}
// Firmware targets use the same central 90% working stroke and single broadcast as the bench.
static int target(int slot,bool pressed,uint8_t amplitude){const auto&s=glove::slot(slot);return librarytargets::softwareTarget(slot,scs::profile().family==scs::Family::SCS,s.lo,s.hi,hardwareMinimum[slot],hardwareMaximum[slot],pressed,amplitude);}
static bool applyOutput(int s){
 const bool pressed=s>0&&(mask&(1<<(s-1))),moving=movingMask&(1<<s);
 if(resistanceSupported){uint16_t limit=libraryhold::limit(originalLimit[s],s,pressed,moving,hold);if(limit!=appliedLimit[s]&&!writeLimit(s,limit)){stop("hold_limit_write_readback_failed");return false;}}
 const bool enable=libraryhold::enabled(s,pressed,moving,hold);
 if(enable!=bool(enabledMask&(1<<s))){if(!glove::torqueSlot(s,enable)){stop("hold_torque_switch_failed");return false;}if(enable)enabledMask|=1<<s;else enabledMask&=~(1<<s);}
 return true;
}
static uint16_t speeds[6]={};
static bool prepare(int selected=0,int amplitude=100){
 const uint32_t prepareStart=millis();
 positionValidMask=0;
 if(incoming||uploadSlot){failure="upload_active_finish_or_abort_first";return false;}
 if(limitsSaved){stop("restore_before_arm");if(limitsSaved){failure="hold_limit_restore_failed";return false;}}
 if(exclusiveBusy||glove::autoActive()||glove::mountActive()||glove::benchActive()||glove::rateActive()||glove::sweepActive()){failure="motion_busy";return false;}
 if(!glove::calibrated()||!glove::motionCalibrationSupported()){failure="calibration_not_ready";return false;}
 for(int s=0;s<6;++s)if(glove::slot(s).id!=s+1||!glove::slot(s).valid){failure="requires_ids_1_to_6_and_calibration";return false;}
 if(!glove::armLibrarySoftwarePose(selected,amplitude)){failure=glove::armFailure();lastPrepareMs=millis()-prepareStart;recordStop(failure);return false;}
 for(int s=0;s<6;++s)if(!scs::checkedBenchSpeed(s+1,scs::profile().family==scs::Family::SCS?1000:8000,speeds[s])){failure="speed_register_incompatible";glove::safe();return false;}
 limitsSaved=0;resistanceSupported=scs::profile().family==scs::Family::STS;
 recoveryMask=0;
 for(int s=0;s<6;++s){
  actual[s]=glove::armLibraryLastPosition(s);glove::slot(s).last=actual[s];poseTargets[s]=actual[s];hardwareMinimum[s]=glove::armLibraryHardwareMinimum(s);hardwareMaximum[s]=glove::armLibraryHardwareMaximum(s);
 }
 for(int s=0;s<6;++s)if(resistanceSupported){uint8_t raw[2]={};if(!scs::readRegs(s+1,48,2,raw)||scs::lastError()||pgl::u16(raw)==0||pgl::u16(raw)>1000){resistanceSupported=false;break;}originalLimit[s]=appliedLimit[s]=pgl::u16(raw);limitsSaved|=1<<s;}
 if(!resistanceSupported)limitsSaved=0;
 uint8_t ids[6]={1,2,3,4,5,6};uint16_t positions[6];const uint32_t sampleStart=millis();
 if(scs::syncReadPos(ids,6,positions,scs::positionReadBudget(6))!=6||scs::lastError()){failure="initial_position_frame_lost";glove::safe();recordStop(failure);return false;}
 recoveryMask=0;
 for(int s=0;s<6;++s){if(positions[s]<hardwareMinimum[s]||positions[s]>hardwareMaximum[s]){failure="initial_position_hardware_limit";glove::safe();recordStop(failure);return false;}actual[s]=positions[s];glove::slot(s).last=actual[s];poseTargets[s]=target(s,s>0&&(selected&(1<<(s-1))),s==0?100:amplitude);poseFrom[s]=actual[s];positionSampleMs[s]=sampleStart;}
 enabledMask=0x3f;positionValidMask=0x3f;movingMask=0;healthValidMask=0;positionsReady=0;feedbackSlot=0;feedbackAt=positionsAt=millis();for(int s=0;s<6;++s){axisPoseAt[s]=millis();const int tol=scs::profile().family==scs::Family::SCS?35:114;if(abs(int(poseTargets[s])-actual[s])>tol)movingMask|=1<<s;else positionsReady|=1<<s;}
 lastPrepareMs=millis()-prepareStart;
 return true;
}
// Validate the complete candidate before any target, timer or output changes.
// Arrival and recorded calibration feedback do not veto bounded software goals.
// -1 is an invalid commanded target; 1 can be committed immediately.
static int poseTransition(uint8_t selected,uint16_t computed[6],uint8_t lifted=0){
 for(int s=0;s<6;++s){const uint8_t bit=s?1<<(s-1):0;int goal=s==0?target(0,false,100):target(s,bool(selected&bit),amp);if(s&&!(selected&bit)&&(lifted&bit)){const auto&slot=glove::slot(s);goal=librarytargets::repeatedReleaseTarget(s,scs::profile().family==scs::Family::SCS,slot.lo,slot.hi,hardwareMinimum[s],hardwareMaximum[s]);}if(goal<0)return -1;computed[s]=goal;}
 return 1;
}
static bool sendPose(bool forceAll=false){const uint32_t poseStart=millis();uint16_t computed[6];if(poseTransition(mask,computed,repeatLiftMask)<0){stop("working_target_invalid");return false;}if(patternRunning)patternChangedMask=0;scs::SyncItem items[6];int n=0;for(int s=0;s<6;++s){uint16_t pos=computed[s];if(pos!=poseTargets[s]||forceAll){poseFrom[s]=actual[s];poseTargets[s]=pos;axisPoseAt[s]=millis();positionsReady&=~(1<<s);movingMask|=1<<s;if(patternRunning)patternChangedMask|=1<<s;items[n++]={uint8_t(s+1),pos,speeds[s],0};}
  if(!applyOutput(s))return false;
 }if(n)scs::syncMove(items,n,true);poseAt=millis();lastPoseMs=millis()-poseStart;if(scs::lastError()){failure="sync_write_failed";stop("sync_write_failed");return false;}return true;}
static bool startPlay(int slot,int rate,int amplitude,const char *who,int resistance=100){
 if(!motionOwnerMatches(who))return false;if(running){failure="motion_busy";return false;}if(!validSlot(slot)){failure="slot_out_of_range";return false;}if(!librarypattern::validRate(rate)||amplitude<1||amplitude>100||resistance<0||resistance>100){failure="play_parameters_invalid";return false;}if(!ready){failure="storage_not_ready";return false;}uint8_t h[128];if(!openScore(slot,playing,h)){playing.close();failure="score_missing_or_corrupt";return false;}
 // Read the first musical mask, but arm at the released musical pose. This
 // keeps a pressed first note out of the slower per-axis arming/readback path.
 // There is no midpoint, recovery pose or all-fingers-arrived barrier.
 uint8_t firstMask=0;pgl::Event first;uint32_t firstPrevious=0;playReader.reset();
 for(uint32_t i=0;i<pgl::u32(h+8);++i){if(!playReader.event(firstPrevious,first)){playing.close();failure="score_read_error";return false;}if(first.t)break;firstMask|=1<<(first.finger-1);firstPrevious=first.t;}
 if(!playing.seek(132)){playing.close();failure="score_read_error";return false;}playReader.reset();
 if(!prepare(0,amplitude)){playing.close();return false;}
 if(!resistanceSupported&&resistance!=0&&resistance!=100){glove::safe();playing.close();failure="hold_register_not_verified";return false;}
 playReader.reset();currentSlot=slot;tempo=rate;amp=amplitude;requestedHold=hold=resistance;count=pgl::u32(h+8);duration=pgl::u32(h+12);index=previousEvent=playedEventCount=0;memset(endTimes,0,sizeof(endTimes));boundaryPending=boundaryReleaseStarted=false;repeatLiftMask=candidateLiftMask=0;lastScoreBoundary=0;mask=firstMask;training=false;running=true;initializing=false;nextReady=false;owner=who;controller=requestController(who);failure="none";
 // The canonical clock and first six-axis musical broadcast begin together
 // after hardware arming. Force all axes even if a goal is already identical.
 started=keepAt=millis();scoreClock.start(started);
 if(!sendPose(true))return false;mask=0;tickScoreTimeline();return running;
}
static bool train(int selected,int resistance,int amplitude,const char *who){
 if(!motionOwnerMatches(who))return false;if(selected<0||selected>31||resistance<0||resistance>100||amplitude<1||amplitude>100){failure="train_parameters_invalid";return false;}if(running&&(!training||patternRunning)){failure="motion_busy";return false;}
 if(scs::profile().family==scs::Family::SCS&&resistance!=0&&resistance!=100){failure="sc09_hold_supports_0_or_100";return false;}
 const bool freshStart=!running;if(freshStart&&!prepare(selected,amplitude))return false;
 if(!resistanceSupported&&resistance!=0&&resistance!=100){glove::safe();failure="hold_register_not_verified";return false;}
 repeatLiftMask=candidateLiftMask=0;training=true;running=true;initializing=false;currentSlot=0;tempo=100;amp=amplitude;mask=selected;hold=resistance;duration=0;owner=who;controller=requestController(who);failure="none";started=keepAt=millis();return sendPose(freshStart);
}
static bool startPattern(int id,int repeats,int rate,int amplitude,int resistance,const char *who){
 if(!motionOwnerMatches(who))return false;if(running){failure="motion_busy";return false;}if(id<0||id>2||repeats<1||repeats>20||!librarypattern::validPatternRate(rate)||amplitude<1||amplitude>100||resistance<0||resistance>100){failure="pattern_parameters_invalid";return false;}
 if(scs::profile().family==scs::Family::SCS&&resistance!=0&&resistance!=100){failure="sc09_hold_supports_0_or_100";return false;}
 if(!prepare(0,amplitude))return false;
 if(!resistanceSupported&&resistance!=0&&resistance!=100){glove::safe();failure="hold_register_not_verified";return false;}
 repeatLiftMask=candidateLiftMask=0;patternSequence.begin(id,repeats,rate,millis());patternRunning=true;training=true;running=true;initializing=true;currentSlot=0;tempo=rate;amp=amplitude;requestedHold=resistance;hold=100;mask=0;duration=patternSequence.minimumDuration();owner=who;controller=requestController(who);failure="none";started=keepAt=millis();return sendPose(true);
}
static bool peekScoreEvent(){if(index>=count)return true;if(!nextReady){if(!playReader.event(previousEvent,nextEvent)){stop("score_read_error");return false;}nextReady=true;}return true;}
static bool prepareBoundary(){
 if(boundaryPending)return true;if(!peekScoreEvent())return false;
 boundaryAt=duration;if(index<count)boundaryAt=min(boundaryAt,nextEvent.t);
 for(int f=0;f<5;++f)if(mask&(1<<f))boundaryAt=min(boundaryAt,endTimes[f]);
 candidateMask=mask;boundaryRepeatMask=0;candidateEventCount=0;
 memcpy(candidateEnds,endTimes,sizeof(endTimes));
 for(int f=0;f<5;++f)if((mask&(1<<f))&&endTimes[f]<=boundaryAt)candidateMask&=~(1<<f);
 boundaryReleaseMask=candidateMask;
 while(index<count&&nextEvent.t==boundaryAt){
  const uint8_t bit=1<<(nextEvent.finger-1);
  if((mask&bit)&&endTimes[nextEvent.finger-1]<=boundaryAt)boundaryRepeatMask|=bit;
  candidateMask|=bit;candidateEnds[nextEvent.finger-1]=nextEvent.t+nextEvent.d;++candidateEventCount;
  previousEvent=nextEvent.t;++index;nextReady=false;if(!peekScoreEvent())return false;
 }
 boundaryReleaseMask=mask&~boundaryRepeatMask;
 candidateLiftMask=boundaryAt>=duration?0:uint8_t(repeatLiftMask&~candidateMask);
 // Explicit rests in a monophonic score can separate two same-finger taps.
 if(index<count&&nextEvent.t>boundaryAt)candidateLiftMask|=(mask&~candidateMask)&(1<<(nextEvent.finger-1));
 boundaryPending=true;boundaryReleaseStarted=false;return true;
}
static void tickScoreTimeline(){
 if(!running)return;
 const uint32_t desired=min(duration,scoreClock.desired(millis(),tempo));
 while(running){
  if(!prepareBoundary())return;
  // Adjacent notes on one finger need a small *scheduled* lift. Borrow no
  // more than half the preceding interval and no more than 40 wall ms, so
  // the next downstroke retains its canonical musical onset. A late tick
  // skips an already-missed lift rather than adding wait time to the score.
  const uint32_t releaseLead=min(uint32_t(40)*tempo/100,(boundaryAt-lastScoreBoundary)/2);
  if(desired<boundaryAt){
   if(boundaryRepeatMask&&!boundaryReleaseStarted&&releaseLead&&desired>=boundaryAt-releaseLead){
    repeatLiftMask|=boundaryRepeatMask;mask=boundaryReleaseMask;if(!sendPose())return;boundaryReleaseStarted=true;
   }
   return;
  }
  uint16_t checked[6];
  if(poseTransition(candidateMask,checked,candidateLiftMask)<0){stop("working_target_invalid");return;}
  const bool finalReturn=boundaryAt>=duration;
  if(finalReturn)hold=100; // Submit the final lifted pose, then release torque; no arrival wait.
  const uint8_t old=mask,oldLift=repeatLiftMask;repeatLiftMask=candidateLiftMask;mask=candidateMask;if((mask!=old||boundaryRepeatMask||repeatLiftMask!=oldLift)&&!sendPose())return;
  memcpy(endTimes,candidateEnds,sizeof(endTimes));playedEventCount+=candidateEventCount;
  if(finalReturn){Serial.printf("LIB_SCORE_COMPLETE {\"slot\":%d,\"score_index\":%u,\"score_total\":%u,\"score_clock\":\"continuous-v1\",\"timeline_complete\":true,\"arrival_checked\":false}\n",currentSlot,unsigned(playedEventCount),unsigned(count));stop("completed");return;}
  lastScoreBoundary=boundaryAt;boundaryPending=false;
 }
}
static void response(bool ok){web.sendHeader("Cache-Control","no-store");web.send(ok?200:400,"application/json",ok?"{\"ok\":true}":"{\"ok\":false,\"error\":\""+escape(failure)+"\"}");if(!ok&&running)failure="none";}
static bool httpInteger(const char*name,long minimum,long maximum,int&out){String value=web.arg(name);char*end=nullptr;long parsed=strtol(value.c_str(),&end,10);if(!value.length()||!end||size_t(end-value.c_str())!=value.length()||parsed<minimum||parsed>maximum){failure=String("request_parameter_invalid name=")+name;return false;}out=parsed;return true;}
static bool scoreReadAllowed(){if(running){failure="stop_before_score_read";return false;}if(incoming||uploadSlot){failure="upload_active_finish_or_abort_first";return false;}if(!ready){failure="storage_not_ready";return false;}return true;}
static void downloadScore(){int slot=web.arg("slot").toInt();File file;uint8_t h[128];if(!openScore(slot,file,h)){failure="score_missing_or_corrupt";response(false);return;}web.setContentLength(128+pgl::u32(h+8)*16);web.send(200,"application/octet-stream","");web.sendContent((const char*)h,128);EventReader reader(file,storageReadBuffer,sizeof(storageReadBuffer));uint8_t buffer[1024];size_t used=0;pgl::Event event;uint32_t prev=0;for(uint32_t i=0;i<pgl::u32(h+8);++i){if(!reader.event(prev,event))break;prev=event.t;pgl::bytes(event,buffer+used);used+=16;if(used==sizeof(buffer)){web.sendContent((const char*)buffer,used);used=0;delay(0);}}if(used)web.sendContent((const char*)buffer,used);file.close();}
static String statusJson(){String json=state();json.remove(json.length()-1);json+=",\"piano_ids\":[2,3,4,5,6],\"thumb_pose_id\":1,\"direction_source\":\"fixed_model\",\"press_directions\":[";for(int s=0;s<6;++s){if(s)json+=",";json+=librarytargets::pressMaximum(s,scs::profile().family==scs::Family::SCS)?"\"max\"":"\"min\"";}json+="]";json+=",\"test_mode\":\""+String(offhandTestMode?"OFFHAND":"NORMAL")+"\",\"recovery_mask\":"+String(recoveryMask);bool calibrated=glove::calibrated()&&glove::motionCalibrationSupported();for(int s=0;s<6;++s)calibrated=calibrated&&glove::slot(s).id==s+1&&calibrationValid(s);bool busy=running||exclusiveBusy||glove::autoActive()||glove::mountActive()||glove::benchActive()||glove::rateActive()||glove::sweepActive();const char*readinessError=!calibrated?"calibration_not_ready":busy?"motion_busy":(incoming||uploadSlot)?"upload_active_finish_or_abort_first":positionValidMask!=0x3f?"position_feedback_lost":"none";json+=",\"software_ready\":true,\"storage_ready\":"+String(ready?"true":"false")+",\"calibration_ready\":"+String(calibrated?"true":"false")+",\"motion_busy\":"+String(busy?"true":"false")+",\"motion_ready\":"+String(calibrated&&!busy&&!incoming&&!uploadSlot&&positionValidMask==0x3f?"true":"false")+",\"readiness_error\":\""+readinessError+"\",\"controller_id\":\""+escape(controller)+"\",\"upload_active\":"+String((incoming||uploadSlot)?"true":"false")+",\"upload_protocol\":\"chunks-v1\",\"upload_chunk_max\":"+String(librarystorage::chunkBytes);return json+",\"model\":\""+String(scs::profile().family==scs::Family::SCS?"SC09":"STS3032-C001")+"\",\"hold_adjustable\":"+String(scs::profile().family==scs::Family::STS?"true":"false")+",\"last_stop_reason\":\""+escape(lastStopReason)+"\",\"last_stop_at_ms\":"+String(lastStopAt)+",\"last_prepare_ms\":"+String(lastPrepareMs)+",\"last_pose_ms\":"+String(lastPoseMs)+"}";}
static void serveScore(){
 int slot=web.arg("slot").toInt();File f;uint8_t h[128];if(!openScore(slot,f,h)){failure="score_missing_or_corrupt";response(false);return;}
 String title;for(int i=0;i<pgl::u16(h+20);++i)title+=char(h[24+i]);web.setContentLength(CONTENT_LENGTH_UNKNOWN);
 web.send(200,"application/json","{\"version\":1,\"hand\":\"right\",\"title\":\""+escape(title)+"\",\"duration_ms\":"+String(pgl::u32(h+12))+",\"notes\":[");
 uint32_t prev=0;pgl::Event e;EventReader reader(f,storageReadBuffer,sizeof(storageReadBuffer));String buffer;buffer.reserve(2300);
 for(uint32_t i=0;i<pgl::u32(h+8);++i){if(!reader.event(prev,e))break;prev=e.t;
  buffer+=String(i?",":"")+"{\"t_ms\":"+String(e.t)+",\"duration_ms\":"+String(e.d)+",\"pitch\":"+String(e.pitch)+",\"finger\":"+String(e.finger)+",\"velocity\":"+String(e.velocity)+",\"amplitude_pct\":"+String(e.amplitude)+"}";
  if(buffer.length()>=2048){web.sendContent(buffer);buffer="";delay(0);}
 }buffer+="]}";web.sendContent(buffer);web.sendContent("");f.close();
}
// Keep serial readback's temporary formatting/header frame out of every LIB
// command, particularly upload commit/verification on the same loop stack.
static bool __attribute__((noinline)) readScoreUsb(int slot){
 if(!scoreReadAllowed())return false;
 File file;uint8_t header[128];if(!openScore(slot,file,header)){file.close();failure="score_missing_or_corrupt";return false;}
 char hex[257];for(int i=0;i<128;++i)sprintf(hex+2*i,"%02x",header[i]);Serial.printf("LIB_DATA hex=%s\n",hex);
 pgl::Event event;uint32_t previous=0;uint8_t bytes[16];EventReader reader(file,storageReadBuffer,sizeof(storageReadBuffer));bool ok=true;
 for(uint32_t i=0;i<pgl::u32(header+8);++i){if(!reader.event(previous,event)){ok=false;break;}previous=event.t;pgl::bytes(event,bytes);for(int j=0;j<16;++j)sprintf(hex+2*j,"%02x",bytes[j]);Serial.printf("LIB_DATA hex=%s\n",hex);if(!(i%64))delay(0);}
 ok=ok&&reader.exhausted();file.close();if(!ok)failure="score_read_error";return ok;
}
static const char PAGE[] PROGMEM=R"HTML(<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><meta charset="utf-8"><title>钢琴手套</title><style>body{font:17px system-ui;background:#13212b;color:#eef6fa;margin:24px;max-width:900px}button,input,select{font:inherit;padding:12px;border-radius:10px;margin:6px;background:#e6f8fb}button{cursor:pointer}#stop{background:#ff6c78}section{padding:18px;background:#233845;border-radius:16px;margin:14px 0}small{color:#a9c3cd}</style><h1>钢琴手套 · 手机控制</h1><small>连接手套热点即可操作，电脑无需开机。</small><section><h2>本地曲库</h2><button onclick="load()">刷新曲库</button><span id="capacity"></span><p><input id="slot" type="number" min="1" max="100" value="1"><input id="file" type="file" accept=".pgl"><button onclick="upload()">上传曲谱</button></p><select id="songs"></select><button onclick="play()">开始曲谱</button><button onclick="removeScore()">删除</button><p>速度 <input id="tempo" type="range" min="50" max="200" value="100" oninput="tempoText.textContent=this.value+'%' "><span id="tempoText">100%</span></p><p>幅度 <input id="amplitude" type="range" min="20" max="100" step="20" value="100" oninput="ampText.textContent=this.value+'%' "><span id="ampText">100%</span></p></section><section><h2>手指训练</h2><div id="fingers"></div><button onclick="training(0)">全部抬起</button><button onclick="training(31)">五指按下</button><small>未动手指保持抬起；拇指由 ID 2 驱动。</small></section><button id="stop" onclick="stop()">■ 停止</button><pre id="status">正在连接…</pre><script>
let timeline=[],audio,voices=new Map(),previousElapsed=-1;const $=x=>document.getElementById(x);async function api(path,data){let r=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(data)}:{});let j=await r.json();if(!r.ok)throw Error(j.error||r.status);return j}async function load(){let j=await api('/api/library');$('capacity').textContent=j.count+'/100 首 · 可用 '+Math.round(j.free/1024)+' KB';$('songs').innerHTML='';for(let s of j.slots){let o=document.createElement('option');o.value=s.slot;o.textContent=s.slot+' · '+s.title;$('songs').append(o)}}async function upload(){try{let f=$('file').files[0];if(!f)return;let r=await fetch('/api/upload?slot='+$('slot').value,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:await f.arrayBuffer()});let j=await r.json();if(!r.ok)throw Error(j.error);await load()}catch(e){$('status').textContent=e.message}}async function removeScore(){await api('/api/delete',{slot:$('songs').value});load()}function silence(){for(let v of voices.values()){v.g.gain.setTargetAtTime(0,audio.currentTime,.03);v.o.stop(audio.currentTime+.15)}voices.clear()}async function play(){try{audio=audio||new(window.AudioContext||window.webkitAudioContext)();await audio.resume();silence();timeline=(await api('/api/score?slot='+$('songs').value)).notes;previousElapsed=-1;await api('/api/play',{slot:$('songs').value,tempo:$('tempo').value,amplitude:$('amplitude').value})}catch(e){$('status').textContent=e.message}}async function stop(){await api('/api/stop',{});if(audio)silence()}async function training(mask){try{await api('/api/train',{mask,hold:100,amplitude:$('amplitude').value})}catch(e){$('status').textContent=e.message}}['拇指','食指','中指','无名指','小指'].forEach((name,i)=>{let b=document.createElement('button');b.textContent=name;b.onclick=()=>training(1<<i);$('fingers').append(b)});setInterval(async()=>{try{await api('/api/keep',{});let s=await api('/api/state');$('status').textContent=(s.active?'运行中':'已停止')+' · '+(s.elapsed_ms/1000).toFixed(2)+' s · '+s.error;if(audio){if(!s.active){silence();previousElapsed=-1}else if(s.mode==='score'){let t=s.elapsed_ms;for(let n of timeline){if(n.t_ms>previousElapsed&&n.t_ms<=t&&n.t_ms+n.duration_ms>t){let o=audio.createOscillator(),g=audio.createGain();o.type='triangle';o.frequency.value=440*Math.pow(2,(n.pitch-69)/12);g.gain.value=.11*n.velocity/127;o.connect(g).connect(audio.destination);o.start();voices.set(n,{o,g,end:n.t_ms+n.duration_ms})}}for(let[n,v]of voices)if(t>=v.end){v.g.gain.setTargetAtTime(0,audio.currentTime,.025);v.o.stop(audio.currentTime+.13);voices.delete(n)}previousElapsed=t}}}catch(e){$('status').textContent=e.message;if(audio)silence()}},200);load();</script>)HTML";
static bool blankStoragePartition(){
 const esp_partition_t *partition=esp_partition_find_first(ESP_PARTITION_TYPE_DATA,ESP_PARTITION_SUBTYPE_DATA_SPIFFS,nullptr);
 if(!partition)return false;uint8_t bytes[1024];
 for(size_t offset=0;offset<partition->size;offset+=sizeof(bytes)){size_t length=min(sizeof(bytes),size_t(partition->size-offset));if(esp_partition_read(partition,offset,bytes,length)!=ESP_OK)return false;for(size_t i=0;i<length;++i)if(bytes[i]!=0xff)return false;delay(0);}
 return true;
}
static void serviceMotion();
static void serviceHttpWait(){bool wasActive=running;serviceMotion();if(wasActive&&!running&&lastStopReason!="completed")web.cancelCurrentClient();}
static bool configurePortalDhcp(){
 esp_netif_t*netif=esp_netif_get_handle_from_ifkey("WIFI_AP_DEF");if(!netif){portalDhcpError=ESP_ERR_INVALID_STATE;return false;}
 esp_err_t stopped=esp_netif_dhcps_stop(netif);if(stopped!=ESP_OK&&stopped!=ESP_ERR_ESP_NETIF_DHCP_ALREADY_STOPPED){portalDhcpError=stopped;return false;}
 esp_netif_dhcps_option(netif,ESP_NETIF_OP_GET,ESP_NETIF_DOMAIN_NAME_SERVER,&portalDnsOfferBefore,sizeof(portalDnsOfferBefore));
 dhcps_offer_t offer=OFFER_DNS;esp_netif_dns_info_t info={};info.ip.type=ESP_IPADDR_TYPE_V4;info.ip.u_addr.ip4.addr=static_cast<uint32_t>(WiFi.softAPIP());
 esp_err_t configured=esp_netif_dhcps_option(netif,ESP_NETIF_OP_SET,ESP_NETIF_DOMAIN_NAME_SERVER,&offer,sizeof(offer));
 if(configured==ESP_OK)configured=esp_netif_set_dns_info(netif,ESP_NETIF_DNS_MAIN,&info);
 esp_err_t started=esp_netif_dhcps_start(netif);if(configured!=ESP_OK||started!=ESP_OK){portalDhcpError=configured!=ESP_OK?configured:started;return false;}
 esp_netif_dns_info_t observed={};esp_err_t option=esp_netif_dhcps_option(netif,ESP_NETIF_OP_GET,ESP_NETIF_DOMAIN_NAME_SERVER,&portalDnsOfferAfter,sizeof(portalDnsOfferAfter));
 esp_err_t address=esp_netif_get_dns_info(netif,ESP_NETIF_DNS_MAIN,&observed);
 // IDF 4.4 GET converts the internal OFFER_DNS bit to boolean 0/1; it does
 // not return the setter's bit mask. Keep address and API-error checks exact.
 if(option!=ESP_OK||address!=ESP_OK||portalDnsOfferAfter!=1||observed.ip.type!=ESP_IPADDR_TYPE_V4||observed.ip.u_addr.ip4.addr!=info.ip.u_addr.ip4.addr){portalDhcpError=option!=ESP_OK?option:address!=ESP_OK?address:ESP_FAIL;return false;}
 portalDhcpError=ESP_OK;return true;
}
static void servicePortalDns(){
 if(!portalDnsReady)return;int size=portalDns.parsePacket();if(size<=0)return;
 if(size>int(sizeof(portalQuery))){uint8_t discard[64];while(portalDns.available())portalDns.read(discard,sizeof(discard));return;}
 int read=portalDns.read(portalQuery,size);if(read!=size)return;
 const IPAddress address=WiFi.softAPIP();uint8_t ipBytes[4]={address[0],address[1],address[2],address[3]};uint16_t type;
 size_t responseBytes=libraryportal::dnsReply(portalQuery,size,portalAnswer,sizeof(portalAnswer),ipBytes,portalLastDns,sizeof(portalLastDns),type);
 if(!responseBytes)return;++portalDnsQueries;
 portalDns.beginPacket(portalDns.remoteIP(),portalDns.remotePort());portalDns.write(portalAnswer,responseBytes);portalDns.endPacket();
}
static void portalCacheHeaders(){web.sendHeader("Cache-Control","no-store, no-cache, must-revalidate, max-age=0");web.sendHeader("Pragma","no-cache");web.sendHeader("Expires","0");}
static void copyPortalText(char*out,size_t capacity,const String&value){size_t size=min(capacity-1,value.length());for(size_t i=0;i<size;++i){uint8_t c=value[i];out[i]=c>=32&&c!=127?char(c):'_';}out[size]=0;}
static void recordPortal(const char*kind){
 portalLastAt=millis();copyPortalText(portalLastPath,sizeof(portalLastPath),web.uri());copyPortalText(portalLastHost,sizeof(portalLastHost),web.header("Host"));copyPortalText(portalLastAgent,sizeof(portalLastAgent),web.header("User-Agent"));
 Serial.printf("LIB_PORTAL_HIT kind=%s path=%s host=%s\n",kind,portalLastPath,portalLastHost);
}
static String portalStatus(){return "{\"ap\":"+String(ap?"true":"false")+",\"stations\":"+String(WiFi.softAPgetStationNum())+",\"dhcp_dns_ready\":"+String(portalDhcpReady?"true":"false")+",\"dns_ready\":"+String(portalDnsReady?"true":"false")+",\"dhcp_dns_before\":"+String(portalDnsOfferBefore)+",\"dhcp_dns_after\":"+String(portalDnsOfferAfter)+",\"dhcp_error\":"+String(portalDhcpError)+",\"dns_queries\":"+String(portalDnsQueries)+",\"probe_hits\":"+String(portalProbes)+",\"landing_hits\":"+String(portalLandings)+",\"redirects\":"+String(portalRedirects)+",\"last_at_ms\":"+String(portalLastAt)+",\"last_path\":\""+escape(portalLastPath)+"\",\"last_host\":\""+escape(portalLastHost)+"\",\"last_agent\":\""+escape(portalLastAgent)+"\",\"last_dns\":\""+escape(portalLastDns)+"\",\"url\":\"http://"+ip()+"/\"}";}
static void __attribute__((noinline)) printPortalStatus(){Serial.printf("LIB_PORTAL %s\n",portalStatus().c_str());Serial.println("OK LIB PORTAL");}
static void redirectPortal(bool probe){if(probe){++portalProbes;recordPortal("probe");}else recordPortal("redirect");++portalRedirects;portalCacheHeaders();String url="http://"+ip()+"/";web.sendHeader("Location",url,true);web.send(302,"text/html; charset=utf-8","<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><meta http-equiv=refresh content=\"0;url="+url+"\"><title>钢琴手套</title><p>正在打开钢琴手套控制页面…</p>");}
static void servePortalPage(){++portalLandings;recordPortal("landing");portalCacheHeaders();web.send_P(200,"text/html; charset=utf-8",SOFTWARE_HTML);}
void begin(){
 ready=SPIFFS.begin(false);
 if(!ready){
  if(blankStoragePartition()){ready=SPIFFS.format()&&SPIFFS.begin(false);if(!ready)failure="blank_storage_initialize_failed";}
  else failure="storage_mount_failed_preserved";
 }
 if(ready){
  bool backups[101]={};File directory=SPIFFS.open("/");File file=directory.openNextFile();
  while(file){String name=file.name();int start=name.startsWith("/")?2:1;int slot=name.substring(start).toInt();if(name.endsWith(".pgc.bak")&&validSlot(slot))backups[slot]=true;file.close();file=directory.openNextFile();}directory.close();
  for(int slot=1;slot<=100;++slot)if(backups[slot])recoverStoredSlot(slot);
  SPIFFS.remove("/upload.tmp");SPIFFS.remove("/compressed.tmp");
  directory=SPIFFS.open("/");file=directory.openNextFile();
  while(file){String name=file.name();int start=name.startsWith("/")?2:1;int slot=name.substring(start).toInt();file.close();if(name.endsWith(".pgc")&&validSlot(slot)){File candidate;uint8_t h[128];if(openScore(slot,candidate,h))cacheEntry(slot,h,candidate.size());candidate.close();}file=directory.openNextFile();}directory.close();
 }
 uint64_t mac=ESP.getEfuseMac();snprintf(apName,sizeof(apName),"PIANO_GLOVE_%06X",unsigned(mac&0xffffff));
 // Phone setup uses an open AP; Arduino clears the previous AP password for nullptr.
 WiFi.mode(WIFI_AP);ap=WiFi.softAP(apName,nullptr);
 const char*headers[]={"X-Piano-Controller","Host","User-Agent"};web.collectHeaders(headers,3);
 web.setWaitHandler([]{serviceHttpWait();});
 if(ap){portalDnsReady=portalDns.begin(53)==1;portalDhcpReady=configurePortalDhcp();Serial.printf("LIB_PORTAL_READY dhcp_dns=%d dns=%d offer_before=%u offer_after=%u error=%d\n",portalDhcpReady,portalDnsReady,unsigned(portalDnsOfferBefore),unsigned(portalDnsOfferAfter),portalDhcpError);}
 for(const char*route:{"/generate_204","/gen_204","/generate204","/hotspot-detect.html","/library/test/success.html","/success.html","/connecttest.txt","/ncsi.txt","/fwlink","/redirect","/canonical.html","/check_network_status.txt","/mobile/status.php","/checknet","/check_network","/portal","/captive"})web.on(route,HTTP_ANY,[]{redirectPortal(true);});
 web.onNotFound([](){if(web.uri().startsWith("/api/"))web.send(404,"application/json","{\"error\":\"unknown_api\"}");else redirectPortal(false);});
 web.on("/",HTTP_GET,[]{servePortalPage();});
 web.on("/software.html",HTTP_GET,[]{servePortalPage();});
 web.on("/software.js",HTTP_GET,[]{web.send_P(200,"application/javascript; charset=utf-8",SOFTWARE_JS);});
 web.on("/software-audio.js",HTTP_GET,[]{web.send_P(200,"application/javascript; charset=utf-8",SOFTWARE_AUDIO_JS);});
 web.on("/software-pack.js",HTTP_GET,[]{web.send_P(200,"application/javascript; charset=utf-8",SOFTWARE_PACK_JS);});
 web.on("/software-review.js",HTTP_GET,[]{web.send_P(200,"application/javascript; charset=utf-8",SOFTWARE_REVIEW_JS);});
 web.on("/software-review.css",HTTP_GET,[]{web.send_P(200,"text/css; charset=utf-8",SOFTWARE_REVIEW_CSS);});
 web.on("/software.css",HTTP_GET,[]{web.send_P(200,"text/css; charset=utf-8",SOFTWARE_CSS);});
 web.on("/software-tempo.js",HTTP_GET,[]{web.send_P(200,"application/javascript; charset=utf-8",SOFTWARE_TEMPO_JS);});
 web.on("/software-tempo.css",HTTP_GET,[]{web.send_P(200,"text/css; charset=utf-8",SOFTWARE_TEMPO_CSS);});
 web.on("/software-upload.js",HTTP_GET,[]{web.send_P(200,"application/javascript; charset=utf-8",SOFTWARE_UPLOAD_JS);});
 web.on("/software-upload.css",HTTP_GET,[]{web.send_P(200,"text/css; charset=utf-8",SOFTWARE_UPLOAD_CSS);});

 web.on("/api/library",HTTP_GET,[]{web.send(200,"application/json",listing());});
 web.on("/api/state",HTTP_GET,[]{web.send(200,"application/json",statusJson());});
 web.on("/api/software/status",HTTP_GET,[]{web.sendHeader("Cache-Control","no-store");web.send(200,"application/json",statusJson());});
 web.on("/api/portal",HTTP_GET,[]{portalCacheHeaders();web.send(200,"application/json",portalStatus());});
 web.on("/api/score",HTTP_GET,[]{if(!scoreReadAllowed())response(false);else serveScore();});
 web.on("/api/download",HTTP_GET,[]{if(!scoreReadAllowed())response(false);else downloadScore();});
 web.on("/api/keep",HTTP_POST,[]{response(keep("wifi"));});
 web.on("/api/tempo",HTTP_POST,[]{int rate;response(httpInteger("tempo",50,1000,rate)&&changeTempo(rate,"wifi"));});
 web.on("/api/stop",HTTP_POST,[]{if(!motionOwnerMatches("wifi")){response(false);return;}stop();glove::safe();response(true);});
 web.on("/api/play",HTTP_POST,[]{int slot,rate,amplitude,resistance=100;response(httpInteger("slot",1,100,slot)&&httpInteger("tempo",50,1000,rate)&&httpInteger("amplitude",1,100,amplitude)&&(!web.hasArg("hold")||httpInteger("hold",0,100,resistance))&&startPlay(slot,rate,amplitude,"wifi",resistance));});
 web.on("/api/train",HTTP_POST,[]{int mask,resistance,amplitude;response(httpInteger("mask",0,31,mask)&&httpInteger("hold",0,100,resistance)&&httpInteger("amplitude",1,100,amplitude)&&train(mask,resistance,amplitude,"wifi"));});
 web.on("/api/pattern",HTTP_POST,[]{int pattern,repeats,rate,amplitude,resistance;response(httpInteger("pattern",0,2,pattern)&&httpInteger("repeats",1,20,repeats)&&httpInteger("tempo",0,1000,rate)&&httpInteger("amplitude",1,100,amplitude)&&httpInteger("hold",0,100,resistance)&&startPattern(pattern,repeats,rate,amplitude,resistance,"wifi"));});
 web.on("/api/delete",HTTP_POST,[]{int slot;response(validController("wifi")&&httpInteger("slot",1,100,slot)&&deleteScore(slot));});
 web.on("/api/upload/begin",HTTP_POST,[]{int slot,bytes;response(httpInteger("slot",1,100,slot)&&httpInteger("bytes",144,librarystorage::maximumRawBytes,bytes)&&startUpload(slot,bytes,"wifi"));});
 web.on("/api/upload/chunk",HTTP_POST,[]{if(!ownerMatches("wifi")){response(false);return;}String body=web.arg("plain");if(body.length()>librarystorage::chunkBytes){failure="upload_chunk_too_large";response(false);return;}response(chunk((const uint8_t*)body.c_str(),body.length()));});
 web.on("/api/upload/commit",HTTP_POST,[]{response(ownerMatches("wifi")&&commit());});
 web.on("/api/upload/abort",HTTP_POST,[]{if(!ownerMatches("wifi")){response(false);return;}abortUpload();failure="none";response(true);});
 web.on("/api/upload",HTTP_POST,[]{int slot;String body=web.arg("plain");if(body.length()>16384){failure="upload_use_chunks";response(false);return;}bool ok=httpInteger("slot",1,100,slot)&&startUpload(slot,body.length(),"wifi");if(ok)ok=chunk((const uint8_t*)body.c_str(),body.length());if(ok)ok=commit();response(ok);});
 web.begin();Serial.printf("LIB_READY ready=%d ap=%s ip=%s max=100\n",ready,apName,ip().c_str());
}
void tick(){
 if(ap)servicePortalDns();
 web.handleClient();if(incoming&&millis()-uploadLast>15000){failure="upload_timeout";abortUpload();}
 serviceMotion();
}
// Called only on the Arduino loop, including cooperative HTTP waits. It never
// enters WebServer or parses USB commands; servo traffic therefore stays serial.
static void serviceMotion(){
 if(!running)return;
 if(!glove::armed()){stop("external_stop");return;}
 if(librarycontroller::leaseExpired(millis(),keepAt,owner=="wifi",!training&&!patternRunning)){stop("controller_disconnected");return;}
 if(millis()-positionsAt>=20){
  const uint32_t sampled=positionsAt=millis();uint8_t ids[6]={1,2,3,4,5,6};uint16_t positions[6];
  if(scs::syncReadPos(ids,6,positions,scs::positionReadBudget(6))!=6||scs::lastError()){positionValidMask=0;stop("position_feedback_lost");return;}
  positionValidMask=0x3f;
  for(int s=0;s<6;++s){actual[s]=positions[s];positionSampleMs[s]=sampled;glove::slot(s).last=positions[s];}
  for(int s=0;s<6;++s){
   int pos=actual[s];
   if(pos<hardwareMinimum[s]||pos>hardwareMaximum[s]){stop("feedback_hardware_limit");return;}
   // Recorded calibration is advisory feedback, not a runtime stop boundary.
   // Commanded goals remain inside its inset intersection with hardware limits.
   int tol=scs::profile().family==scs::Family::SCS?35:114;int requested=int(poseTargets[s])-poseFrom[s],moved=pos-poseFrom[s];
   if(abs(requested)<=2*tol||abs(int(poseTargets[s])-pos)<=max(tol,abs(requested)/2))positionsReady|=1<<s;
   if(training&&millis()-axisPoseAt[s]>200&&((requested>0&&moved< -tol)||(requested<0&&moved>tol))){stop("movement_opposite_target");return;}
   if(training&&(enabledMask&(1<<s))&&!(positionsReady&(1<<s))&&millis()-axisPoseAt[s]>1800){stop("movement_below_half_target");return;}
   int outputTolerance=patternRunning&&!initializing&&(patternChangedMask&(1<<s))?librarypattern::phaseTolerance(abs(requested),tol):tol;
   if((movingMask&(1<<s))&&abs(int(poseTargets[s])-pos)<=outputTolerance){movingMask&=~(1<<s);if(!applyOutput(s))return;}
  }
 }
 if(millis()-feedbackAt>=100){
  const uint32_t sampled=feedbackAt=millis();int s=feedbackSlot;feedbackSlot=(feedbackSlot+1)%6;scs::Feedback fb;
  if(!scs::readFeedback(s+1,fb)||scs::lastError()||!fb.ok){healthValidMask&=~(1<<s);stop("health_feedback_lost");return;}
  volts[s]=fb.voltage;temps[s]=fb.temp;currentRaw[s]=fb.current;healthSampleMs[s]=sampled;healthValidMask|=1<<s;
  if(fb.temp>=65||fb.voltage<40||fb.voltage>65){stop("temperature_or_voltage");return;}
 }
 if(initializing){if(patternRunning?patternPreparationReady():positionsReady==0x3f){initializing=false;hold=requestedHold;started=millis();if(patternRunning){patternSequence.phaseStarted=started;mask=patternSequence.mask();}else scoreClock.start(started);if(!sendPose())return;}else{if(patternRunning&&millis()-poseAt>1800)stop("pattern_full_target_not_reached");return;}}
 if(patternRunning){const uint32_t now=millis();const bool arrived=patternPhaseReady();if(patternSequence.expired(now,arrived)){stop("pattern_full_target_not_reached");return;}if(patternSequence.due(now,arrived)){if(!patternSequence.advance(now)){stop("completed");return;}mask=patternSequence.mask();sendPose();}return;}
 if(training)return;
 tickScoreTimeline();
}
const char *ssid(){return apName;}String ip(){return ap?WiFi.softAPIP().toString():"0.0.0.0";}bool apReady(){return ap;}
static bool integer(const char*s,long min,long max,long&out){char*end=nullptr;out=strtol(s,&end,10);return *s&&end&&!*end&&out>=min&&out<=max;}
// cmdLine calls this on the same Arduino loop as HTTP preparation. No network
// handler can start/take ownership between the check and both cleanup calls.
static void releaseUsb(){
 if(owner=="wifi"&&(running||initializing)){Serial.println("OK LIB RELEASE skipped=1 owner=wifi");return;}
 stop();glove::safe();Serial.println("OK LIB RELEASE skipped=0");
}
bool command(int n,char**t){
 if(n<1||strcmp(t[0],"LIB"))return false;String action=n>=2?t[1]:"INFO";bool ok=false;
 if(action=="RELEASE"){if(n!=2){Serial.println("ERR LIB RELEASE usage");return true;}releaseUsb();return true;}
 if(action=="TEST"&&n==3&&(!strcmp(t[2],"OFFHAND")||!strcmp(t[2],"NORMAL"))){stop("test_mode_changed");glove::safe();offhandTestMode=!strcmp(t[2],"OFFHAND");recoveryMask=0;Serial.printf("OK LIB TEST mode=%s torque=off persistent=0\n",offhandTestMode?"OFFHAND":"NORMAL");return true;}
 if(action=="INFO"){Serial.printf("OK LIB INFO ready=%d count=%d max=100 release_usb=1 score_clock=continuous-v1 calibration_advisory=1 chunk_max=384 upload_owner=%s total=%u used=%u free=%u ap=%s ip=%s\n",ready,libraryCount(),uploadOwner.c_str(),unsigned(SPIFFS.totalBytes()),unsigned(SPIFFS.usedBytes()),unsigned(SPIFFS.totalBytes()-SPIFFS.usedBytes()),ssid(),ip().c_str());return true;}
 if(action=="LIST"){for(int s=1;s<=100;++s){const auto&m=meta[s];if(!m.valid)continue;char title[193]={};for(size_t j=0;j<strlen(m.title);++j)sprintf(title+j*2,"%02x",uint8_t(m.title[j]));Serial.printf("LIB_ITEM slot=%d bytes=%u stored=%u notes=%u duration_ms=%u title_hex=%s\n",s,unsigned(m.bytes),unsigned(m.stored),unsigned(m.notes),unsigned(m.duration),title);}Serial.printf("OK LIB LIST count=%d\n",cachedCount);return true;}
 if(action=="STATE"){Serial.printf("LIB_STATE %s\n",compactState().c_str());Serial.println("OK LIB STATE");return true;}
 if(action=="PORTAL"){printPortalStatus();return true;}
 if((action=="BEGIN"||action=="CHUNK"||action=="COMMIT"||action=="ABORT")&&!ownerMatches("usb")){Serial.printf("ERR LIB %s %s\n",action.c_str(),failure.c_str());return true;}
 if(action=="KEEP"){ok=keep("usb");}
 else if(action=="STOP"){stop();glove::safe();ok=true;}
 else if(action=="ABORT"){abortUpload();ok=true;}
 else if(action=="COMMIT")ok=commit();
 else if(action=="CHUNK"&&n==3){size_t size=strlen(t[2]);ok=size>0&&!(size%2)&&size<=768;for(size_t i=0;ok&&i<size;i+=2){char a=t[2][i],b=t[2][i+1];auto nibble=[](char c)->int{if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;if(c>='A'&&c<='F')return c-'A'+10;return -1;};int x=nibble(a),y=nibble(b);ok=x>=0&&y>=0;if(ok)usbChunkBuffer[i/2]=x*16+y;}if(ok)ok=chunk(usbChunkBuffer,size/2);else failure="invalid_hex";}
 else{long slot=0,a=0,b=0,c=0,d=0;if(action=="BEGIN"&&n==4&&integer(t[2],1,100,slot)&&integer(t[3],144,960128,a))ok=startUpload(slot,a,"usb");
  else if(action=="DELETE"&&n==3&&integer(t[2],1,100,slot))ok=deleteScore(slot);
  else if(action=="PLAY"&&(n==5||n==6)&&integer(t[2],1,100,slot)&&integer(t[3],50,1000,a)&&integer(t[4],1,100,b)){long resistance=100;if(n==5||integer(t[5],0,100,resistance))ok=startPlay(slot,a,b,"usb",resistance);}
  else if(action=="TEMPO"&&n==3&&integer(t[2],50,1000,a))ok=changeTempo(a,"usb");
  else if(action=="TRAIN"&&n==5&&integer(t[2],0,31,slot)&&integer(t[3],0,100,a)&&integer(t[4],1,100,b))ok=train(slot,a,b,"usb");
  else if(action=="PATTERN"&&n==7&&integer(t[2],0,2,slot)&&integer(t[3],1,20,a)&&integer(t[4],0,1000,b)&&integer(t[5],1,100,c)&&integer(t[6],0,100,d))ok=startPattern(slot,a,b,c,d,"usb");
  else if(action=="READ"&&n==3&&integer(t[2],1,100,slot))ok=readScoreUsb(slot);
  else failure="usage_or_busy";
 }
  Serial.printf("%s LIB %s%s%s\n",ok?"OK":"ERR",action.c_str(),ok?"":" ",ok?"":failure.c_str());if(!ok&&running)failure="none";return true;
}
}

#pragma once
namespace librarytargets {
// Same physical assembly for both versions: ID1 pose, ID2 piano thumb, ID3..6 fingers.
// Direction is structural, never inferred from movement order or stale NVS.
// User confirmed the STS piano-thumb axis (ID2) was inverted in the old table.
// Both assemblies press toward the low endpoint. ID1 still holds its high/lift
// posture and is not the piano-thumb press axis.
inline bool pressMaximum(int slot,bool scs){(void)slot;(void)scs;return false;}
inline int target(int slot,bool scs,int calibratedLo,int calibratedHi,int hardwareLo,int hardwareHi,bool pressed,int amplitude){
 if(slot<0||slot>5||calibratedLo>=calibratedHi||hardwareLo>hardwareHi||amplitude<0||amplitude>100)return -1;
 const int span=calibratedHi-calibratedLo;
 const int inset=scs?(span/4<6?span/4:6):span*5/100;
 const int low=calibratedLo+inset>hardwareLo?calibratedLo+inset:hardwareLo;
 const int high=calibratedHi-inset<hardwareHi?calibratedHi-inset:hardwareHi;
 if(low>high)return -1;
 const int released=pressMaximum(slot,scs)?low:high;
 const int down=pressMaximum(slot,scs)?high:low;
 return pressed?released+(down-released)*amplitude/100:released;
}
// Software training/score goals keep at least 5% inside each calibrated end.
// Legacy/debug/benchmark target arithmetic above remains unchanged.
inline int softwareTarget(int slot,bool scs,int calibratedLo,int calibratedHi,int hardwareLo,int hardwareHi,bool pressed,int amplitude){
 if(slot<0||slot>5||calibratedLo>=calibratedHi||hardwareLo>hardwareHi||amplitude<0||amplitude>100)return -1;
 const int span=calibratedHi-calibratedLo;
 int inset=(span+19)/20;const int legacyScs=scs?(span/4<6?span/4:6):0;if(legacyScs>inset)inset=legacyScs;
 const int low=calibratedLo+inset>hardwareLo?calibratedLo+inset:hardwareLo;
 const int high=calibratedHi-inset<hardwareHi?calibratedHi-inset:hardwareHi;
 if(low>high)return -1;
 const int released=pressMaximum(slot,scs)?low:high,down=pressMaximum(slot,scs)?high:low;
 return pressed?released+(down-released)*amplitude/100:released;
}
// A repeated piano finger may use its recorded lift endpoint, never beyond
// calibration or hardware travel. The pose axis and normal goals stay inset.
inline int repeatedReleaseTarget(int slot,bool scs,int calibratedLo,int calibratedHi,int hardwareLo,int hardwareHi){
 const int normal=softwareTarget(slot,scs,calibratedLo,calibratedHi,hardwareLo,hardwareHi,false,100);
 if(normal<0||slot==0)return normal;
 return pressMaximum(slot,scs)?(calibratedLo>hardwareLo?calibratedLo:hardwareLo):(calibratedHi<hardwareHi?calibratedHi:hardwareHi);
}
}

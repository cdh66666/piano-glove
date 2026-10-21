#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace libraryportal {
inline uint16_t be16(const uint8_t*p){return uint16_t(p[0])<<8|p[1];}
inline void put16(uint8_t*p,uint16_t value){p[0]=value>>8;p[1]=value;}
// One ordinary DNS question, with optional EDNS additional records. Keep the
// copied question, discard additional records, and answer only IN A. IPv6 /
// HTTPS / other types get NOERROR+NODATA so resolvers can fall back to IPv4.
// Do not send IPv4 data as an answer to an AAAA query.
inline size_t dnsReply(const uint8_t*query,size_t length,uint8_t*out,size_t capacity,const uint8_t ip[4],char*name,size_t nameCapacity,uint16_t&type){
 if(nameCapacity)name[0]=0;type=0;
 if(length<17||length>512||capacity<12||be16(query+4)!=1||be16(query+6)||be16(query+8)||(query[2]&0xf8))return 0;
 size_t at=12,named=0,wireName=0;
 while(at<length){uint8_t label=query[at++];++wireName;if(!label)break;if(label>63||label>length-at||wireName+label>255)return 0;
  if(named&&named+1<nameCapacity)name[named++]='.';
  for(size_t i=0;i<label;++i){char value=query[at+i];if(named+1<nameCapacity)name[named++]=(value>32&&value<127)?value:'_';}
  at+=label;wireName+=label;
 }
 if(nameCapacity)name[named]=0;
 if(!wireName||at+4>length||query[at-1]!=0)return 0;
 type=be16(query+at);uint16_t cls=be16(query+at+2);size_t questionEnd=at+4;
 bool answer=cls==1&&(type==1||type==255);size_t size=questionEnd+(answer?16:0);if(size>capacity)return 0;
 memcpy(out,query,questionEnd);out[2]=uint8_t(0x84|(query[2]&1));out[3]=cls==1?0x80:0x85;put16(out+4,1);put16(out+6,answer?1:0);put16(out+8,0);put16(out+10,0);
 if(answer){uint8_t*p=out+questionEnd;const uint8_t fixed[12]={0xc0,0x0c,0,1,0,1,0,0,0,1,0,4};memcpy(p,fixed,12);memcpy(p+12,ip,4);}
 return size;
}
}

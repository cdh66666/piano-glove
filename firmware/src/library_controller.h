#pragma once
#include <stddef.h>
#include <string.h>
#include <stdint.h>

namespace librarycontroller {
constexpr size_t maximumTokenLength=64;
// Phone Wi-Fi can briefly stall one request while a native score continues on
// the board clock. Give scores a bounded grace period; direct/manual control
// retains its existing shorter lease.
inline uint32_t leaseTimeoutMs(bool wireless,bool scorePlayback){
 return wireless&&scorePlayback?5000u:2000u;
}
inline bool leaseExpired(uint32_t now,uint32_t lastKeep,bool wireless,bool scorePlayback){
 return uint32_t(now-lastKeep)>leaseTimeoutMs(wireless,scorePlayback);
}
inline bool validToken(const char *token,size_t length){
 if(length>maximumTokenLength)return false;
 for(size_t i=0;i<length;++i){char c=token[i];if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'))return false;}
 return true;
}
inline bool matches(bool active,bool sameTransport,const char *saved,size_t savedLength,const char *request,size_t requestLength){
 return !active||(sameTransport&&savedLength==requestLength&&!memcmp(saved,request,savedLength));
}
}

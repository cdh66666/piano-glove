#pragma once
#include <stddef.h>
#include <string.h>

namespace librarycontroller {
constexpr size_t maximumTokenLength=64;
inline bool validToken(const char *token,size_t length){
 if(length>maximumTokenLength)return false;
 for(size_t i=0;i<length;++i){char c=token[i];if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'))return false;}
 return true;
}
inline bool matches(bool active,bool sameTransport,const char *saved,size_t savedLength,const char *request,size_t requestLength){
 return !active||(sameTransport&&savedLength==requestLength&&!memcmp(saved,request,savedLength));
}
}

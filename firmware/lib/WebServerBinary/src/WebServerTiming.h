#pragma once
#include <stddef.h>
#include <stdint.h>

// Shared with native tests. Clock/idle/service and the client stay on the
// calling loop: no task, lock, HTTP recursion or concurrent servo access.
namespace webservertiming {
inline bool expired(uint32_t now,uint32_t started,uint32_t budget){return uint32_t(now-started)>=budget;}
template<class Client,class Clock,class Idle,class Service>
bool byte(Client&client,uint8_t&out,uint32_t started,uint32_t budget,Clock now,Idle idle,Service service){
 for(;;){service();if(expired(now(),started,budget))return false;if(client.available()){int value=client.read();if(value>=0){out=uint8_t(value);return true;}}if(!client.connected())return false;idle();}
}
template<class Client,class Text,class Clock,class Idle,class Service>
bool line(Client&client,Text&out,size_t maximum,uint32_t started,uint32_t budget,Clock now,Idle idle,Service service){
 out="";uint8_t value;
 while(byte(client,value,started,budget,now,idle,service)){
  if(value=='\r'){if(!byte(client,value,started,budget,now,idle,service))return false;return value=='\n';}
  if(value=='\n'||!value||out.length()>=maximum)return false;
  out+=char(value);
 }return false;
}
template<class Client,class Clock,class Idle,class Service>
bool body(Client&client,char*out,size_t length,size_t&received,uint32_t started,uint32_t budget,Clock now,Idle idle,Service service){
 received=0;uint8_t value;while(received<length){if(!byte(client,value,started,budget,now,idle,service))return false;out[received++]=char(value);}out[received]=0;return true;
}
// tryWrite must perform one nonblocking send. -1 is retryable, -2 fatal.
template<class Writer,class Clock,class Idle,class Service>
size_t write(const char*data,size_t length,uint32_t responseStarted,uint32_t responseBudget,uint32_t idleBudget,Writer tryWrite,Clock now,Idle idle,Service service){
 size_t sent=0;uint32_t progress=now();
 while(sent<length){
  service();uint32_t sampled=now();if(expired(sampled,responseStarted,responseBudget)||expired(sampled,progress,idleBudget))break;
  size_t amount=length-sent;if(amount>1436)amount=1436;int result=tryWrite(data+sent,amount);
  if(result>0){if(size_t(result)>amount)break;sent+=result;progress=now();}
  else if(result==-2)break;else idle();
 }return sent;
}
}

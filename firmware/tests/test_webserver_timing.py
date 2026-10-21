"""Execute shared HTTP timing code and actual wait service callback natively.

Tests deterministic clients, not the ESP32 Wi-Fi stack or handset reception.
"""
from pathlib import Path
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
server=root.parent/'lib/WebServerBinary/src'
source=(server/'WebServer.cpp').read_text(encoding='utf-8')
service=source[source.index('void WebServer::_serviceWait(){'):source.index('size_t WebServer::_currentClientWrite(')]
library=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
motion_wait=library[library.index('static void serviceHttpWait(){'):library.index('static bool configurePortalDhcp(){')]
parser=(server/'Parsing.cpp').read_text(encoding='utf-8')
request=parser[parser.index('bool WebServer::_parseRequest('):parser.index('bool WebServer::_collectHeader(')]
assert 'readStringUntil' not in request and 'readBytes(' not in request and 'client.flush()' not in request
assert '_parseForm(client' not in request
assert source.count('_currentClient.write(footer')==0
assert 'MSG_DONTWAIT' in source and '_currentClient.setTimeout(' not in source
cpp=root/'webserver_timing_generated.cpp';exe=root/'webserver_timing_generated.exe'
cpp.write_text(r'''
#include "../lib/WebServerBinary/src/WebServerTiming.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <vector>
#include <functional>
#include <algorithm>
uint32_t tick=0;uint32_t millis(){return tick;}
bool running=true,finishInWait=false;std::string lastStopReason="none";
void serviceMotion(){if(finishInWait)running=false;}
struct PendingClient{int cancels=0;void cancelCurrentClient(){++cancels;}}web;
''' + motion_wait + r'''
class WebServer{
public:
 std::function<void()>_waitHandler;bool _waitServicing=false;uint32_t _lastWaitService=0;
 void _serviceWait();
};
''' + service + r'''
struct Client{
 std::vector<std::pair<uint32_t,uint8_t>>bytes;size_t at=0;bool online=true;
 int available(){return at<bytes.size()&&uint32_t(tick-bytes[at].first)<0x80000000u;}
 int read(){return available()?bytes[at++].second:-1;}bool connected(){return online;}
 void add(const std::string&s,uint32_t start,uint32_t spacing=0){for(size_t i=0;i<s.size();++i)bytes.push_back({start+uint32_t(i)*spacing,uint8_t(s[i])});}
};
int main(){
 WebServer server;int calls=0,maxDepth=0,depth=0;bool motionActive=true;uint32_t lastService=0,maxGap=0;
 server._waitHandler=[&]{++depth;maxDepth=std::max(maxDepth,depth);++calls;maxGap=std::max(maxGap,uint32_t(tick-lastService));lastService=tick;if(tick>=2000)motionActive=false;server._serviceWait();--depth;};
 auto now=[](){return tick;};auto idle=[](){++tick;};auto service=[&](){server._serviceWait();};
 Client normal;normal.add("GET /api/state HTTP/1.1\r\n",0,5);std::string line;
 assert(webservertiming::line(normal,line,2048,0,500,now,idle,service)&&line=="GET /api/state HTTP/1.1"&&tick==5*(normal.bytes.size()-1));
 assert(calls>=5&&maxDepth==1&&maxGap<=20);
 tick=0;Client slow;slow.add("GET /api/state HTTP/1.1\r\n",0,100);
 assert(!webservertiming::line(slow,line,2048,0,500,now,idle,service)&&tick==500);
 tick=0;Client stopped;assert(!webservertiming::line(stopped,line,2048,0,500,now,idle,service)&&tick==500);
 tick=0;Client oversized;oversized.add(std::string(2049,'x')+"\r\n",0);assert(!webservertiming::line(oversized,line,2048,0,500,now,idle,service));
 tick=0;Client bareLF;bareLF.add("GET /\n",0);assert(!webservertiming::line(bareLF,line,2048,0,500,now,idle,service));
 tick=0;Client badCRLF;badCRLF.add("GET /\rx",0);assert(!webservertiming::line(badCRLF,line,2048,0,500,now,idle,service));
 tick=0;Client binary;std::string payload;for(int i=0;i<384;++i)payload+=char(i%256);binary.add(payload,100,1);char body[385];size_t received=0;
 assert(webservertiming::body(binary,body,384,received,0,500,now,idle,service)&&received==384&&std::string(body,384)==payload&&tick==483);
 tick=0;Client truncated;truncated.add(payload.substr(0,100),0);assert(!webservertiming::body(truncated,body,384,received,0,500,now,idle,service)&&received==100&&tick==500);
 tick=0xfffffff0u;uint32_t start=tick;Client wrap;wrap.add("GET /\r\n",start+100);
 assert(webservertiming::line(wrap,line,2048,start,500,now,idle,service)&&uint32_t(tick-start)==100);
 tick=0;server._lastWaitService=0;calls=0;lastService=0;maxGap=0;motionActive=true;
 std::string asset(262144,'a');size_t counted=0;
 auto accepts=[&](const char*p,size_t n)->int{assert(n<=1436&&p[0]=='a');++tick;counted+=n;return int(n);};
 assert(webservertiming::write(asset.data(),asset.size(),0,2500,500,accepts,now,idle,service)==asset.size()&&counted==asset.size()&&tick<500);
 tick=0;server._lastWaitService=0;lastService=0;maxGap=0;calls=0;
 auto congested=[](const char*,size_t)->int{return -1;};
 assert(webservertiming::write(asset.data(),asset.size(),0,2500,500,congested,now,idle,service)==0&&tick==500&&calls==25&&maxGap<=20);
 tick=0;server._lastWaitService=0;lastService=0;maxGap=0;calls=0;motionActive=true;uint32_t lastProgress=0;
 auto trickle=[&](const char*,size_t)->int{if(tick-lastProgress>=400){lastProgress=tick;return 1;}return -1;};
 size_t sent=webservertiming::write(asset.data(),asset.size(),0,2500,500,trickle,now,idle,service);
 assert(sent==6&&tick==2500&&!motionActive&&calls>=100&&maxGap<=20); // 2s lease still executes inside response wait.
 tick=0;auto fatal=[](const char*,size_t)->int{return -2;};assert(webservertiming::write(asset.data(),asset.size(),0,2500,500,fatal,now,idle,service)==0&&tick==0);
 tick=20;WebServer costly;int costlyCalls=0;costly._waitHandler=[&]{++costlyCalls;tick+=75;};costly._serviceWait();assert(costlyCalls==1&&tick==95);costly._serviceWait();assert(costlyCalls==1);tick+=19;costly._serviceWait();assert(costlyCalls==1);++tick;costly._serviceWait();assert(costlyCalls==2); // Bus time cannot cause re-service on every received byte.
 running=true;finishInWait=false;serviceHttpWait();assert(web.cancels==0);
 finishInWait=true;lastStopReason="completed";serviceHttpWait();assert(!running&&web.cancels==0);
 running=true;lastStopReason="position_feedback_lost";serviceHttpWait();assert(!running&&web.cancels==1);
 serviceHttpWait();assert(web.cancels==1); // Idle does not continually abort normal page loads.
 running=true;lastStopReason="controller_disconnected";serviceHttpWait();assert(!running&&web.cancels==2);
 puts("PASS actual HTTP wait service + shared timing: 500ms absolute parse incl slow trickle, 384B NUL body in delayed fragments, truncation/oversize/CRLF/wrap; nonblocking 256KB asset, 500ms congested send cutoff, 2500ms whole-response cap; motion lease serviced every20ms during send with no callback reentry");
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
subprocess.run([str(exe)],check=True)

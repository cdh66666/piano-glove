"""Execute actual portal HTTP redirect/page/diagnostic helpers without I/O."""
from pathlib import Path
import json
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
source=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
helpers=source[source.index('static void portalCacheHeaders(){'):source.index('void begin(){')]
helpers=helpers.replace('__attribute__((noinline)) ', '')
cpp=root/'library_portal_http_generated.cpp';exe=root/'library_portal_http_generated.exe'
cpp.write_text(r'''
#include <stdint.h>
#include <string>
#include <map>
#include <algorithm>
#include <assert.h>
#include <iostream>
using std::min;
class String{
 std::string value;
public:
 String(){}String(const char*s):value(s){}String(std::string s):value(s){}String(int n):value(std::to_string(n)){}String(unsigned n):value(std::to_string(n)){}
 String operator+(const String&other)const{return String(value+other.value);}friend String operator+(const char*a,const String&b){return String(std::string(a)+b.value);}
 String&operator+=(const String&other){value+=other.value;return *this;}size_t length()const{return value.size();}char operator[](size_t i)const{return value[i];}const char*c_str()const{return value.c_str();}
};
String escape(String s){std::string out;for(size_t i=0;i<s.length();++i){char c=s[i];if(c=='"'||c=='\\')out+='\\';out+=c;}return out;}
String ip(){return "192.168.4.1";}uint32_t millis(){return 700;}
bool ap=true,portalDnsReady=true,portalDhcpReady=true;uint8_t portalDnsOfferBefore=0,portalDnsOfferAfter=1;int portalDhcpError=0;
uint32_t portalDnsQueries=3,portalProbes=0,portalLandings=0,portalRedirects=0,portalLastAt=0;
char portalLastPath[97]={},portalLastHost[97]={},portalLastAgent[161]={},portalLastDns[97]="connectivitycheck.gstatic.com";
const char SOFTWARE_HTML[]="<!doctype html><title>actual control UI fixture</title>";
struct Wifi{int softAPgetStationNum(){return 1;}}WiFi;
struct SerialMock{int lines=0;void printf(const char*,...){++lines;}void println(const char*){++lines;}}Serial;
struct Web{
 std::string path="/generate_204",host="connectivitycheck.platform.hicloud.com",agent="Android \"Honor\"\nNetwork",body,type;int code=0;std::map<std::string,std::string>headers;
 String uri(){return path;}String header(const char*name){return std::string(name)=="Host"?host:agent;}
 void sendHeader(String key,String value,bool=false){headers[key.c_str()]=value.c_str();}
 void send(int c,const char*t,String b){code=c;type=t;body=b.c_str();}void send_P(int c,const char*t,const char*b){send(c,t,b);}
}web;
''' + helpers + r'''
int main(){
 redirectPortal(true);assert(web.code==302&&web.headers["Location"]=="http://192.168.4.1/"&&web.type=="text/html; charset=utf-8");
 assert(web.headers["Cache-Control"].find("no-store")!=std::string::npos&&web.headers["Pragma"]=="no-cache"&&web.headers["Expires"]=="0");
 assert(web.body.find("http-equiv=refresh")!=std::string::npos&&web.body.find("0;url=http://192.168.4.1/")!=std::string::npos&&portalProbes==1&&portalRedirects==1);
 assert(std::string(portalLastAgent).find('\n')==std::string::npos);std::cout<<portalStatus().c_str()<<"\n";
 web.path="/";servePortalPage();assert(web.code==200&&web.body==SOFTWARE_HTML&&portalLandings==1&&portalProbes==1&&std::string(portalLastPath)=="/");std::cout<<portalStatus().c_str()<<"\n";
 web.path="/vendor-unknown-probe";redirectPortal(false);assert(portalRedirects==2&&portalProbes==1&&portalLandings==1);printPortalStatus();assert(Serial.lines==5);
 char tiny[4];copyPortalText(tiny,sizeof(tiny),"abcdef\n");assert(std::string(tiny)=="abc");
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17','/utf-8',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
states=[json.loads(line) for line in subprocess.check_output([str(exe)],text=True).splitlines()]
assert len(states)==2
assert states[0]['dhcp_dns_ready'] and states[0]['dns_ready'] and states[0]['dhcp_dns_after']==1
assert states[0]['probe_hits']==1 and states[0]['landing_hits']==0 and states[0]['last_path']=='/generate_204'
assert states[0]['last_host']=='connectivitycheck.platform.hicloud.com' and states[0]['stations']==1
assert states[0]['last_agent']=='Android "Honor"_Network'
assert states[1]['landing_hits']==1 and states[1]['last_path']=='/' and states[1]['url']=='http://192.168.4.1/'
print('PASS actual portal HTTP helpers: no-cache302 with automatic redirect+HTML fallback,200 same control page, separate probe/landing counts, bounded sanitized logs and readonly JSON diagnostics; no arm or control command')

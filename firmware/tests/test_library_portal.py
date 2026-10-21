"""Execute actual DHCP setup and bounded raw DNS reply code natively.

Fake ESP netif checks ordering/failure handling; actual DHCP OFFER and phone
captive-browser behavior require the separate board/handset records.
"""
from pathlib import Path
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
source=(root.parent/'src/device_library.cpp').read_text(encoding='utf-8')
dhcp=source[source.index('static bool configurePortalDhcp(){'):source.index('static void servicePortalDns(){')]
cpp=root/'library_portal_generated.cpp';exe=root/'library_portal_generated.exe'
cpp.write_text(r'''
#include "../src/library_portal_dns.h"
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>
using Bytes=std::vector<uint8_t>;
using esp_err_t=int;struct esp_netif_t{}interface;
struct esp_netif_dns_info_t{struct{int type;struct{struct{uint32_t addr;}ip4;}u_addr;}ip;};
using dhcps_offer_t=uint8_t;
const int ESP_OK=0,ESP_FAIL=-1,ESP_ERR_INVALID_STATE=1,ESP_ERR_ESP_NETIF_DHCP_ALREADY_STOPPED=2,ESP_NETIF_OP_GET=3,ESP_NETIF_OP_SET=4,ESP_NETIF_DOMAIN_NAME_SERVER=6,ESP_NETIF_DNS_MAIN=0,ESP_IPADDR_TYPE_V4=0;
const uint8_t OFFER_DNS=2;
bool missing=false;int failStage=0,portalDhcpError=0;uint8_t portalDnsOfferBefore=0,portalDnsOfferAfter=0,offer=0;uint32_t dns=0;std::vector<std::string>calls;
struct Wifi{uint32_t softAPIP(){return 0x0104a8c0;}}WiFi;
esp_netif_t*esp_netif_get_handle_from_ifkey(const char*key){assert(!strcmp(key,"WIFI_AP_DEF"));return missing?nullptr:&interface;}
esp_err_t esp_netif_dhcps_stop(esp_netif_t*){calls.push_back("stop");return failStage==1?42:failStage==2?ESP_ERR_ESP_NETIF_DHCP_ALREADY_STOPPED:ESP_OK;}
esp_err_t esp_netif_dhcps_start(esp_netif_t*){calls.push_back("start");return failStage==5?45:ESP_OK;}
// Match actual IDF4.4: SET nonzero toggles OFFER_DNS; GET returns boolean1/0.
esp_err_t esp_netif_dhcps_option(esp_netif_t*,int op,int key,void*value,size_t length){assert(key==6&&length==1);calls.push_back(op==ESP_NETIF_OP_GET?"get-offer":"set-offer");if(op==ESP_NETIF_OP_SET){if(failStage==3)return 43;offer=*static_cast<uint8_t*>(value)?OFFER_DNS:0;}else *static_cast<uint8_t*>(value)=failStage==6?0:uint8_t((offer&OFFER_DNS)!=0);return ESP_OK;}
esp_err_t esp_netif_set_dns_info(esp_netif_t*,int type,esp_netif_dns_info_t*info){assert(type==ESP_NETIF_DNS_MAIN&&info->ip.type==ESP_IPADDR_TYPE_V4);calls.push_back("set-dns");if(failStage==4)return 44;dns=info->ip.u_addr.ip4.addr;return ESP_OK;}
esp_err_t esp_netif_get_dns_info(esp_netif_t*,int,esp_netif_dns_info_t*info){calls.push_back("get-dns");info->ip.type=ESP_IPADDR_TYPE_V4;info->ip.u_addr.ip4.addr=failStage==7?0:dns;return ESP_OK;}
''' + dhcp + r'''
void reset(){missing=false;failStage=portalDhcpError=0;portalDnsOfferBefore=portalDnsOfferAfter=offer=0;dns=0;calls.clear();}
Bytes query(const std::string&host,uint16_t type,bool edns=false){Bytes p(12,0);p[0]=0x12;p[1]=0x34;p[2]=1;p[5]=1;p[11]=edns?1:0;size_t start=0;for(;;){size_t dot=host.find('.',start);size_t end=dot==std::string::npos?host.size():dot;p.push_back(uint8_t(end-start));for(size_t i=start;i<end;++i)p.push_back(host[i]);if(dot==std::string::npos)break;start=end+1;}p.push_back(0);p.push_back(type>>8);p.push_back(type);p.push_back(0);p.push_back(1);if(edns){const uint8_t opt[11]={0,0,41,4,208,0,0,0,0,0,0};p.insert(p.end(),opt,opt+11);}return p;}
int main(){
 reset();assert(configurePortalDhcp()&&portalDhcpError==0&&offer==2&&dns==WiFi.softAPIP()&&portalDnsOfferBefore==0&&portalDnsOfferAfter==1);
 const std::vector<std::string>expected={"stop","get-offer","set-offer","set-dns","start","get-offer","get-dns"};assert(calls==expected);
 reset();offer=OFFER_DNS;assert(configurePortalDhcp()&&portalDnsOfferBefore==1&&portalDnsOfferAfter==1);
 reset();missing=true;assert(!configurePortalDhcp()&&portalDhcpError==ESP_ERR_INVALID_STATE&&calls.empty());
 reset();failStage=1;assert(!configurePortalDhcp()&&portalDhcpError==42&&calls.size()==1);
 reset();failStage=2;assert(configurePortalDhcp());
 for(int stage:{3,4,5}){reset();failStage=stage;assert(!configurePortalDhcp()&&portalDhcpError==40+stage);bool restarted=false;for(auto&step:calls)restarted|=step=="start";assert(restarted);}
 for(int stage:{6,7}){reset();failStage=stage;assert(!configurePortalDhcp()&&portalDhcpError==ESP_FAIL);}
 const uint8_t address[4]={192,168,4,1};uint8_t answer[512];char host[97];uint16_t type=0;
 for(bool edns:{false,true})for(const char*name:{"connectivitycheck.gstatic.com","captive.apple.com","connectivitycheck.platform.hicloud.com","connectivitycheck.cbg-app.huawei.com","www.msftconnecttest.com"}){
  Bytes p=query(name,1,edns);size_t n=libraryportal::dnsReply(p.data(),p.size(),answer,sizeof(answer),address,host,sizeof(host),type);size_t questionEnd=p.size()-(edns?11:0);
  assert(n==questionEnd+16&&!strcmp(host,name)&&type==1&&answer[0]==0x12&&answer[1]==0x34&&answer[2]==0x85&&answer[3]==0x80);
  assert(libraryportal::be16(answer+4)==1&&libraryportal::be16(answer+6)==1&&libraryportal::be16(answer+10)==0);
  assert(answer[questionEnd]==0xc0&&answer[questionEnd+1]==12&&libraryportal::be16(answer+questionEnd+2)==1&&libraryportal::be16(answer+questionEnd+10)==4);
  assert(answer[questionEnd+6]==0&&answer[questionEnd+7]==0&&answer[questionEnd+8]==0&&answer[questionEnd+9]==1&&memcmp(answer+questionEnd+12,address,4)==0);
 }
 for(uint16_t wanted:{uint16_t(28),uint16_t(65),uint16_t(16)}){Bytes p=query("captive.apple.com",wanted,true);size_t n=libraryportal::dnsReply(p.data(),p.size(),answer,sizeof(answer),address,host,sizeof(host),type);assert(n==p.size()-11&&type==wanted&&libraryportal::be16(answer+6)==0&&(answer[3]&15)==0&&libraryportal::be16(answer+10)==0);}
 Bytes valid=query("connectivitycheck.gstatic.com",1,true);
 for(size_t cut=0;cut<valid.size()-11;++cut)assert(!libraryportal::dnsReply(valid.data(),cut,answer,sizeof(answer),address,host,sizeof(host),type));
 assert(!libraryportal::dnsReply(valid.data(),valid.size(),answer,16,address,host,sizeof(host),type));
 Bytes malformed=valid;malformed[12]=0xc0;malformed[13]=12;assert(!libraryportal::dnsReply(malformed.data(),malformed.size(),answer,sizeof(answer),address,host,sizeof(host),type)); // compression/self-loop rejected.
 malformed=valid;malformed[12]=64;assert(!libraryportal::dnsReply(malformed.data(),malformed.size(),answer,sizeof(answer),address,host,sizeof(host),type));
 malformed=valid;malformed[5]=2;assert(!libraryportal::dnsReply(malformed.data(),malformed.size(),answer,sizeof(answer),address,host,sizeof(host),type));
 malformed=valid;malformed[2]|=0x80;assert(!libraryportal::dnsReply(malformed.data(),malformed.size(),answer,sizeof(answer),address,host,sizeof(host),type));
 malformed.resize(513);assert(!libraryportal::dnsReply(malformed.data(),malformed.size(),answer,sizeof(answer),address,host,sizeof(host),type));
 char tiny[3];assert(libraryportal::dnsReply(valid.data(),valid.size(),answer,sizeof(answer),address,tiny,sizeof(tiny),type)>0&&tiny[2]==0);
 puts("PASS actual DHCP+raw DNS: stop/configure DNS option6/OFFER_DNS/main address/restart/readback; missing/stop/set/start/readback failures; A+EDNS for Android/Apple/Huawei/Honor/MS hosts, exact IPv4/TTL1, proper AAAA/HTTPS NODATA, malformed/compressed/truncated/oversize bounds");
}
''',encoding='utf-8')
environment=os.environ.copy();vcvars=Path('D:/AI_Workspace/ai-models/vs-build-tools/VC/Auxiliary/Build/vcvars64.bat')
for line in subprocess.check_output(['cmd','/d','/c',f'call {vcvars} >nul && set'],encoding='utf-8',errors='replace').splitlines():
    if '=' in line and not line.startswith('='):
        key,value=line.split('=',1);environment[key.upper()]=value
compiler=shutil.which('cl.exe',path=environment['PATH']);assert compiler
subprocess.run([compiler,'/nologo','/EHsc','/std:c++17',str(cpp),'/Fe:'+str(exe)],cwd=root,env=environment,check=True)
subprocess.run([str(exe)],check=True)

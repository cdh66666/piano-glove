from pathlib import Path
r=Path(__file__).resolve().parent;s=(r.parent/'src/main.cpp').read_text(encoding='utf-8')
a=s.index('static void cmdLine(char *raw) {')+len('static void cmdLine(char *raw) {');tokenizer=s[a:s.index('  glove::markCommand();',a)]
a=s.index('    if(n>=2&&!strcasecmp(t[1],"GROUP"))');branch=s[a:s.index('    if(n!=5||strcasecmp(t[1],"MOVE"))',a)]
prefix=r'''
#include <stdint.h>
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include <string>
#define strcasecmp _stricmp
int calls=0,stops=0,errors=0;uint8_t savedMask=0;uint16_t savedPos[6],savedSpeed=0;
bool expire=false;std::string ack;
namespace glove{void safe(){++stops;}void benchTick(){}bool armed(){return !expire;}bool benchActive(){return !expire;}const char*benchFailure(){return "none";}bool benchGroup(uint8_t mask,const uint16_t pos[6],uint16_t speed){++calls;savedMask=mask;memcpy(savedPos,pos,12);savedSpeed=speed;return true;}}
int bitcount(uint8_t m){int n=0;for(;m;m>>=1)n+=m&1;return n;}
void errf(const char*,...){++errors;}void okf(const char*f,...){char b[256];va_list a;va_start(a,f);vsnprintf(b,sizeof(b),f,a);va_end(a);ack=b;}
void parser(char*raw){
'''
tests=r'''
}
void input(const char*text){char raw[512];strncpy(raw,text,511);raw[511]=0;parser(raw);}
void rejected(const char*text){int old=calls,oldErrors=errors;input(text);assert(calls==old&&errors>oldErrors);}
int main(){
input("BENCH GROUP 0x3F 100 200 300 400 500 600 1000");assert(calls==1&&savedMask==63&&savedSpeed==1000&&savedPos[5]==600);
assert(ack.find("armed=1 bench_active=1")!=std::string::npos);
input("  BENCH   GROUP  0x3f   100  200  300  400  500  600   1000   ");assert(calls==2);
input("\tBENCH\tGROUP\t0x05\t100\t200\t300\t400\t500\t600\t50\t");assert(calls==3&&savedMask==5&&savedSpeed==50);
rejected("BENCH GROUP 0x3f 100 200 300 400 500 600");
rejected("BENCH GROUP 0x3f 100 200 300 400 500 600 1000 extra");
rejected("BENCH GROUP 0x3f 100 200 300 400 500 600 1000 x1 x2 x3 x4 x5 x6 x7");
rejected("BENCH GROUP 0 100 200 300 400 500 600 1000");
rejected("BENCH GROUP 0x40 100 200 300 400 500 600 1000");
rejected("BENCH GROUP 0x3f 100 200 300 400 500 1024 1000");
rejected("BENCH GROUP 0x3f 100 200 300 400 500 junk 1000");
rejected("BENCH GROUP 0x3f 100 200 300 400 500 600 1001");
int old=calls;input(" \t  ");assert(calls==old);
expire=true;ack.clear();int oldErrors=errors;input("BENCH GROUP 0x3F 100 200 300 400 500 600 1000");assert(errors>oldErrors&&ack.empty());
puts("actual cmdLine tokenization+GROUP PASS: raw10tokens, tabs/spaces, missing/extra/17overflow, invalidmask/target/speed");
}
'''
(r/'bench_group_parser_generated.cpp').write_text(prefix+tokenizer+'\nif(!strcasecmp(t[0],"BENCH")){\n'+branch+'\n}\n'+tests,encoding='utf-8')

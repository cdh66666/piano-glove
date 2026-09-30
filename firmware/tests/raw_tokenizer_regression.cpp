#include <cstring>
#include <cassert>
#include <cstdio>
int stops=0;namespace glove{void safe(){++stops;}} void errf(const char*,...){ }
void parse(char*raw,int expected){
  char  buf[256];
  strncpy(buf, raw, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = 0;

  char *t[16];
  int   n = 0;
  char *p = buf;
  while (*p && n < int(sizeof(t)/sizeof(t[0]))) {
    while (*p == ' ' || *p == '\t') ++p;
    if (!*p) break;
    t[n++] = p;
    while (*p && *p != ' ' && *p != '\t') ++p;
    if (*p) *p++ = 0;
  }
  while (*p == ' ' || *p == '\t') ++p;
  if (*p) { glove::safe(); errf("COMMAND too_many_arguments"); return; }
  if (n == 0) return;

assert(n==expected);if(n==10){assert(!strcmp(t[9],"1000"));assert(!strcmp(t[8],"721"));}}
int main(){char a[]="BENCH GROUP 0x3f 708 561 707 712 723 721 1000";parse(a,10);char b[]="BENCH\tGROUP  0x3f 708 561 707 712 723 721 1000  ";parse(b,10);char c[]="a b c d e f g h i j k l m n o p q";parse(c,0);assert(stops==1);puts("actual raw tokenizer PASS: ten tokens, whitespace, overflow rejected");}

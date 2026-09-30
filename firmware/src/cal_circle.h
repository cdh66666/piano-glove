#pragma once
// Raw encoder interval, inclusive. lo>hi is the positive interval through zero.
namespace calcircle {
inline int span(int lo,int hi,int range){return (hi-lo+range+1)%(range+1);}
inline bool contains(int lo,int hi,int p,int range){return lo>=0&&hi>=0&&lo<=range&&hi<=range&&p>=0&&p<=range&&(lo<=hi?(p>=lo&&p<=hi):(p>=lo||p<=hi));}
inline int delta(int from,int to,int range){int n=range+1,d=(to-from)%n;if(d>n/2)d-=n;if(d< -n/2)d+=n;return d;}
inline int wrap(int p,int range){int n=range+1;return (p%n+n)%n;}
// Record observed intervals up to 90%; recording validity does not authorize wrapped motion.
inline bool valid(int lo,int st,int hi,int range){int n=span(lo,hi,range);return n>0&&contains(lo,hi,st,range)&&n*10<=range*9;}
}

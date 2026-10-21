#pragma once
namespace libraryhold {
inline int limit(int original,int slot,bool pressed,bool moving,int hold){
 if(slot==0||pressed||moving)return original;
 if(hold<0)hold=0;if(hold>100)hold=100;
 int value=original*hold/100;return value>0?value:1;
}
inline bool enabled(int slot,bool pressed,bool moving,int hold){return slot==0||pressed||moving||hold!=0;}
}

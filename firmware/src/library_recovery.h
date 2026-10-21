#pragma once
namespace librarypolicy {
inline int margin(int lo,int hi,bool scs){int percent=(hi-lo)*15/100,tolerance=scs?35:114;return percent>tolerance?percent:tolerance;}
inline int deviation(int lo,int hi,int position,int slack){return position<lo-slack?lo-slack-position:(position>hi+slack?position-hi-slack:0);}
inline bool recoverAllowed(int lo,int hi,int position,int slack,int initialDeviation,int hardwareLo,int hardwareHi){return position>=hardwareLo&&position<=hardwareHi&&deviation(lo,hi,position,slack)<=initialDeviation+3;}
inline bool inwardTarget(int lo,int hi,int position,int slack,int goal){return position<lo-slack?goal>position:(position>hi+slack?goal<position:true);}
}

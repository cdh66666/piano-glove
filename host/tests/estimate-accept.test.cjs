'use strict';
// 位置是软件猜的：小白看谱确认不了，不进「待查」（软件按猜的弹），提醒文字保留；时值没定或有冲突的仍要查。
const test=require('node:test');const assert=require('node:assert/strict');
const R=require('../software-review.js');
const note=()=>({id:'p1-n9',hand:'right',pitch:'E5',finger:3,beat:11,duration_beats:.25,timing_estimated:true,automatic_ready:true,automatic_reasons:[],timing_warning:'此处开始时间为估计值，后续已按右手节奏接排；修改此音起拍或时值后，后续时间自动更新。'});
test('猜的开始位置不进待查，提醒照旧',()=>{const n=note();assert.equal(R.hasTimingWarning(n),true);assert.equal(R.estimateOnly(n),true);assert.equal(R.timingNeedsAction(n),false);});
test('点过就这样弹：记住当时起拍，起拍变了重新算',()=>{const n=note();n.start_estimate_ok=n.beat;assert.equal(R.estimateAccepted(n),true);assert.equal(R.hasTimingWarning(n),false);n.beat=11.5;assert.equal(R.estimateAccepted(n),false);});
test('时值也没定、或有冲突时仍要查',()=>{
 const a={...note(),timing_warning:'装饰音无固定时值，主拍位置保留；可设置时值与开始位置。'};assert.equal(R.estimateOnly(a),false);
 const b={...note(),timing_warning:'同组音的手动起拍不同，已保留输入，请核对。'};assert.equal(R.estimateOnly(b),false);assert.equal(R.timingNeedsAction(b),true);
});

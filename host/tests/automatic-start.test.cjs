const test=require('node:test'),assert=require('node:assert/strict'),Review=require('../software-review.js');
const state=(kind='source_timing')=>({kind,group_id:kind+':a',realized:true,estimated:true,warning_root:true,reviewed:false,parameters:{timing_source_id:'a'},editable_fields:[]});
const note=(extra={})=>({id:'a',hand:'right',beat:9,duration_beats:.5,finger:2,pitch:'Bb4',automatic_ready:true,automatic_reasons:[],timing_estimated:true,timing_source_id:'a',timing_warning:'此处开始时间为估计值，后续已按右手节奏接排；修改此音起拍或时值后，后续时间自动更新。',performance_state:{...state(),items:[state()]},...extra});
test('a realized automatic onset is optional without inventing manual review or changing its source',()=>{
 const n=note(),before=JSON.stringify(n);assert.equal(Review.automaticStartHandled(n),true);assert.equal(Review.hasPerformanceWarning(n),false);assert.equal(Review.timingNeedsAction(n),false);assert.equal(Review.hasTimingWarning(n),true);assert.match(Review.timingWarningLabel(n),/已自动安排.*估计.*不用填写/);assert.equal(JSON.stringify(n),before);assert.equal(n.manual_fields,undefined);assert.equal(n.performance_override,undefined);assert.equal(n.performance_state.reviewed,false);
});
test('actual conflicting positions and overflowing measures remain actionable even if estimated and compiled',()=>{
 for(const warning of ['同组音的手动起拍不同，已保留输入，请核对。','本小节超过4拍，请核对音长和末尾休止。']){
  const n=note({timing_warning:warning});assert.equal(Review.automaticStartHandled(n),false);assert.equal(Review.timingNeedsAction(n),true);assert.equal(Review.hasPerformanceWarning(n),true);
  n.performance_state.items[0].reviewed=true;assert.equal(Review.timingNeedsAction(n),true,'A prior accepted estimate cannot hide a new real conflict');
 }
});
test('missing starts incomplete validation and unresolved note durations are never passed as finished timing',()=>{
 for(const value of [{beat:null},{beat:-1},{automatic_ready:false},{validation_pending:true},{automatic_reasons:['确定开始位置']},{performance_state:{...state(),realized:false,items:[{...state(),realized:false}]}}])assert.equal(Review.automaticStartHandled(note(value)),false);
 assert.equal(Review.timingNeedsAction(note({duration_beats:null})),true);
});
test('other ornament estimates remain pending and are shown in preference to a completed timing item',()=>{
 const n=note({performance_state:{...state(),items:[state(),state('grace_short')]}});assert.equal(Review.automaticStartHandled(n),true);assert.equal(Review.hasPerformanceWarning(n),true);assert.equal(Review.performanceInfo(n).kind,'grace_short');assert.equal(n.performance_state.items.length,2);
});
test('beginner seconds come from the first real audio event including repeats and ornament timing',()=>{
 const n=note(),p={automatic_mode:true,performance:{audio_events:[{t_ms:18000,source_note_ids:['a']},{t_ms:4300,source_note_ids:['a']},{t_ms:100,source_note_ids:['b']}]}};
 const info=Review.automaticStartSummary(p,n);assert.equal(info.available,true);assert.equal(info.first_ms,4300);assert.match(info.text,/估计.*4\.3秒/);assert.match(info.detail,/不用填写拍数/);assert.equal(Review.automaticStartSummary(p,note({timing_warning:'本小节超过4拍'})).available,false);
});
test('the real lightweight project summary needs no audio-event expansion or invented seconds for a known source position',()=>{
 const n=note({timing_estimated:false,timing_warning:null,performance_state:undefined}),p={automatic_mode:true,performance:{version:1,mode:'practice',features:[],coverage:{}}},before=JSON.stringify(p);
 const info=Review.automaticStartSummary(p,n);assert.equal(info.available,true);assert.match(info.text,/已按原谱自动安排/);assert.doesNotMatch(info.text,/秒/);assert.equal(info.first_ms,null);assert.equal(JSON.stringify(p),before);
});
test('one-click recovery removes only this source measure RH beat pins, preserving fingers durations and later manual anchors',()=>{
 const first=note({page:1,system:1,measure:1,manual_fields:['finger','beat','duration_beats'],timing_anchor_scope:'measure'}),second=note({id:'b',page:1,system:1,measure:1,manual_fields:['beat']}),later=note({id:'c',page:1,system:1,measure:2,manual_fields:['beat']}),left=note({id:'left',hand:'left',page:1,system:1,measure:1,manual_fields:['beat']});
 const p={notes:[first,second,later,left],rests:[],right_hand_timing:{basis:{measures:[{page:1,system:1,measure:1,groups:[{events:[{id:'a'},{id:'b'},{id:'left'}]}]}]}}};
 const r=Review.restoreMeasureAutomaticStart(p,first);assert.equal(r.restored,2);assert.deepEqual(first.manual_fields,['finger','duration_beats']);assert.equal(first.timing_anchor_scope,undefined);assert.equal(first.finger,2);assert.equal(first.duration_beats,.5);assert.deepEqual(second.manual_fields,[]);assert.deepEqual(later.manual_fields,['beat']);assert.deepEqual(left.manual_fields,['beat']);
});
test('no source timing basis means no pretend automatic repair; authored timing stays intact',()=>{
 const n=note({manual_fields:['beat']}),p={notes:[n]};assert.equal(Review.restoreMeasureAutomaticStart(p,n),null);assert.deepEqual(n.manual_fields,['beat']);
 p.right_hand_timing={basis:{measures:[{page:undefined,system:undefined,measure:undefined,groups:[]}]}};p.source_kind='manual';p.recognition_performed=false;assert.equal(Review.restoreMeasureAutomaticStart(p,n),null);
});

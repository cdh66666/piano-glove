/* Local score review and screen/audio tutorial. No serial or motor control. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.GloveReview=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const FINGERS=['拇指','食指','中指','无名指','小指'];
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const short=value=>finite(value)?String(Math.round(value*1000)/1000):'—';
const NOTE_VALUES=[{beats:4,label:'全音符',symbol:'𝅝'},{beats:2,label:'二分',symbol:'𝅗𝅥'},{beats:1,label:'四分',symbol:'♩'},{beats:.5,label:'八分',symbol:'♪'},{beats:.25,label:'十六分',symbol:'𝅘𝅥𝅯'},{beats:.125,label:'三十二分',symbol:'𝅘𝅥𝅰'}];
const unmeasuredGrace=n=>['unmeasured_prefix','slashed','unmeasured'].includes(n?.grace_kind)&&(!finite(n?.duration_beats)||n.duration_beats<=0);
function noteValueFor(beats){for(const mode of ['plain','dotted','triplet'])for(const value of NOTE_VALUES){const factor=mode==='dotted'?1.5:mode==='triplet'?2/3:1;if(finite(beats)&&Math.abs(value.beats*factor-beats)<1e-5)return {...value,mode,label:value.label+(mode==='dotted'?' · 附点':mode==='triplet'?' · 三连音':''),symbol:value.symbol+(mode==='dotted'?'·':mode==='triplet'?'₃':'')};}return {beats:null,mode:'custom',label:finite(beats)?'自定义音值':'音值待补',symbol:'?'};}
function measureContext(n){const local=finite(n?.measure_beat)&&n.measure_beat>=0?n.measure_beat:null,base=finite(n?.measure_start_beat)&&n.measure_start_beat>=0?n.measure_start_beat:finite(n?.beat)&&local!==null&&n.beat>=local?n.beat-local:null;return {base,local:local??(base!==null&&finite(n?.beat)?n.beat-base:null),number:n?.global_measure_index??n?.measure??null,length:finite(n?.meter_beats)&&n.meter_beats>0?n.meter_beats:null};}
function precedingGroup(notes,n){if(!n)return null;if(n.voice==null&&notes.some(x=>x.page===n.page&&x.system===n.system&&x.measure===n.measure&&x.issues?.includes('multiple_voices_require_review')))return null;const same=notes.filter(x=>x!==n&&!x.excluded&&x.hand===n.hand&&x.page===n.page&&x.system===n.system&&x.measure===n.measure&&(x.voice??null)===(n.voice??null)&&(n.voice!=null||(x.staff??null)===(n.staff??null))&&finite(x.beat)&&finite(x.duration_beats)&&x.duration_beats>0);const xOf=x=>Array.isArray(x.bbox)?(x.bbox[0]+x.bbox[2])/2:Array.isArray(x.origin)?x.origin[0]:null,nx=xOf(n);const earlier=same.filter(x=>finite(n.beat)?x.beat<n.beat-1e-5:finite(nx)&&finite(xOf(x))&&xOf(x)<nx-1);if(!earlier.length)return null;const beat=Math.max(...earlier.map(x=>x.beat)),group=earlier.filter(x=>Math.abs(x.beat-beat)<1e-5),ends=[...new Set(group.map(x=>Math.round((x.beat+x.duration_beats)*1e6)/1e6))];return {beat,end:ends.length===1?ends[0]:null,ids:group.map(x=>x.id)};}
function quickOnsets(notes,n){const context=measureContext(n),previous=precedingGroup(notes,n);return {start:context.base,simultaneous:previous?.beat??null,after:previous?.end??null,previous:previous?.ids||[]};}
function editorPosition(anchor,width,height,viewport){const margin=10,w=Math.min(width,viewport.width-2*margin),h=Math.min(height,viewport.height-2*margin),a=anchor||{left:viewport.width/2,right:viewport.width/2,top:80,bottom:100};let left=a.right+10,top=a.top-22;if(left+w>viewport.width-margin)left=a.left-w-10;if(left<margin){left=Math.min(Math.max(margin,a.left),viewport.width-w-margin);top=a.bottom+10;}return {left:Math.max(margin,Math.min(left,viewport.width-w-margin)),top:Math.max(margin,Math.min(top,viewport.height-h-margin)),width:w};}
function validFinger(n){return Number.isInteger(n?.finger)&&n.finger>=1&&n.finger<=5;}
function unfingered(n){return n?.source_fingering_state==='unmarked'&&n.finger==null;}
function fingerLabel(n){return validFinger(n)?n.finger+' '+FINGERS[n.finger-1]:unfingered(n)?'— 未设指法':'? 待补指法';}
function holdLabel(n,bpm){return finite(n?.duration_beats)&&n.duration_beats>0&&finite(bpm)&&bpm>0?'按 '+short(n.duration_beats*60/bpm)+' 秒':'时长待补';}
function validPitch(value){const m=/^([A-Ga-g])(##|bb|#|b|)(-?\d+)$/.exec(String(value??''));if(!m)return false;const midi=(Number(m[3])+1)*12+{C:0,D:2,E:4,F:5,G:7,A:9,B:11}[m[1].toUpperCase()]+{'':0,'#':1,b:-1,'##':2,bb:-2}[m[2]];return midi>=0&&midi<=127;}
function missingFields(note){const missing=[];if(!validPitch(note?.pitch))missing.push('音高');if(!validFinger(note)&&!unfingered(note))missing.push('指法');if(!finite(note?.beat)||note.beat<0)missing.push('开始');if((!finite(note?.duration_beats)||note.duration_beats<=0)&&!(unfingered(note)&&unmeasuredGrace(note)))missing.push('时长');if(!['right','left'].includes(note?.hand))missing.push('左右手');return missing;}
const PERFORMANCE_LABELS={grace_unspecified:'无斜线小音符',source_timing:'开始位置估计',fingering:'练习指法',grace_long:'长倚音',grace_short:'短倚音',grace_cluster:'复倚音',grace_after:'后倚音',mordent_upper:'上波音',mordent_lower:'下波音',turn:'顺回音',inverted_turn:'逆回音',trill:'颤音',trill_with_lower_mordent:'颤音接下波音',arpeggio:'琶音',broken_chord:'分解和弦',glissando:'滑音',tremolo_single:'同音震音',tremolo_alternating:'交替震音',tuplet:'连音组',dots:'附点',syncopation:'切分音',tie:'延音线',slur:'连音线',fermata:'延长记号',staccato:'跳音',staccatissimo:'极短跳音',tenuto:'保持音',accent:'重音',ottava:'八度移位',pedal:'延音踏板'};
function performanceItems(n){const primary=n?.performance_state,states=Array.isArray(primary?.items)&&primary.items.length?primary.items:primary?[primary]:[];const accepted=states.filter(x=>PERFORMANCE_LABELS[x?.kind]||x?.parameters?.finger_origin==='estimated').map(state=>({kind:state.kind,label:state.label||PERFORMANCE_LABELS[state.kind]||'练习指法',group_id:state.group_id||String(n.id),realized:state.realized===true,estimated:state.estimated===true,warning_root:state.warning_root===true,reviewed:state.reviewed===true,message:typeof state.message==='string'?state.message:'',parameters:state.parameters&&typeof state.parameters==='object'?state.parameters:{},editable_fields:Array.isArray(state.editable_fields)?state.editable_fields:null,key:String(state.group_id||n.id)+':'+state.kind}));if(accepted.length)return accepted;return (Array.isArray(n?.performance_marks)?n.performance_marks:[]).filter(m=>PERFORMANCE_LABELS[m?.kind]).map(m=>({kind:m.kind,label:PERFORMANCE_LABELS[m.kind],group_id:m.group_id||String(n.id),key:String(m.group_id||n.id)+':'+m.kind,parameters:{},realized:false,estimated:false,warning_root:false,reviewed:false,message:'',editable_fields:[]}));}
function performanceInfo(n,key=null){const items=performanceItems(n);return items.find(x=>x.key===key)||items.find(x=>!(x.kind==='source_timing'&&automaticStartHandled(n)))||items[0]||null;}
// 小白点了「按软件估的」：记下当时的起拍；之后起拍变了就重新要查。
// 点过「就这样弹」：记下当时的起拍；之后起拍变了就重新要查。
// estimateOnly：11-04 用户——位置是猜的这种，小白看谱也确认不了 → 不进「待查」，软件按猜的弹（提醒文字照旧保留）。
function estimateAccepted(n){return !!n&&n.timing_estimated===true&&finite(n.beat)&&finite(n.start_estimate_ok)&&Math.abs(n.beat-n.start_estimate_ok)<1e-6&&!timingConflict(n);}
function estimateOnly(n){return !!n&&n.timing_estimated===true&&finite(n.beat)&&n.beat>=0&&!timingConflict(n)&&!durationNeedsReviewRaw(n);}
function canAcceptEstimate(n){return !!n&&!n.excluded&&n.hand!=='left'&&!n.validation_pending&&n.timing_estimated===true&&finite(n.beat)&&n.beat>=0&&!timingConflict(n)&&!estimateAccepted(n)&&!durationNeedsReviewRaw(n);}
function timingConflict(n){return /本小节超过|同组音.*(?:不同|冲突)|手动起拍不同|起拍.*(?:冲突|不一致)/.test(String(n?.timing_warning||'')+'；'+(n?.automatic_reasons||[]).join('；'));}
function automaticStartHandled(n){
 if(!n||n.excluded||n.hand!=='right'||n.validation_pending||n.automatic_ready!==true||!finite(n.beat)||n.beat<0||!n.timing_estimated||timingConflict(n)||(n.automatic_reasons||[]).length)return false;
 return performanceItems(n).some(p=>p.kind==='source_timing'&&p.realized);
}
function timingNeedsAction(n){return hasTimingWarning(n)&&!/^此小节省略连音编号/.test(String(n.timing_warning||'').trim())&&!estimateOnly(n)&&(!automaticStartHandled(n)||durationNeedsReview(n));}
function automaticStartSummary(project,n){
 const events=project?.performance?.audio_events;
 const attacks=Array.isArray(events)?events.filter(e=>Array.isArray(e.source_note_ids)&&e.source_note_ids.some(id=>String(id)===String(n?.id))&&finite(e.t_ms)&&e.t_ms>=0):[];
 const first=attacks.length?Math.min(...attacks.map(e=>e.t_ms)):null;
 const manual=(n?.manual_fields||[]).includes('beat');
 const knownSource=project?.performance?.version===1&&finite(n?.beat)&&n.beat>=0&&!n.timing_estimated&&n.automatic_ready===true&&!n.validation_pending&&!(n.automatic_reasons||[]).length;
 const available=project?.automatic_mode===true&&!n?.excluded&&n?.hand==='right'&&!timingConflict(n)&&(knownSource||(finite(first)&&n?.automatic_ready===true&&!n.validation_pending)||automaticStartHandled(n));
 return {available,estimated:!!n?.timing_estimated,first_ms:first,
  text:available?(manual?'已保留你的开始位置':n.timing_estimated?'已自动安排（估计）':'已按原谱自动安排')+(finite(first)?' · 首次'+(n.timing_estimated?'约':'')+short(first/1000)+'秒开始':''):'',
  detail:available?'不用填写拍数；前面的节奏改动后，未单独固定的后续音会自动跟随。':''};
}
function automaticMeasurePlan(project,n){
 if(!project?.right_hand_timing?.basis||project.source_kind==='manual'&&project.recognition_performed===false)return null;
 return (project.right_hand_timing.basis.measures||[]).find(m=>m.page===n?.page&&m.system===n?.system&&m.measure===n?.measure)||null;
}
function restoreMeasureAutomaticStart(project,n){
 const plan=automaticMeasurePlan(project,n);if(!plan)return null;
 const ids=new Set((plan.groups||[]).flatMap(g=>(g.events||[]).map(e=>String(e.id))));let restored=0;
 for(const event of [...(project.notes||[]),...(project.rests||[])])if(event.hand==='right'&&ids.has(String(event.id))&&(event.manual_fields||[]).includes('beat')){
  event.manual_fields=event.manual_fields.filter(field=>field!=='beat');delete event.timing_anchor_scope;
  event.human_reviewed=false;event.confirmed=false;event.validation_pending=true;event.automatic_reasons=[];restored++;
 }
 return {restored,page:n.page,system:n.system,measure:n.measure};
}

/* 11-04 用户：软件已按通用弹法编好的记号（倚音、连线、踏板、琶音、颤音、附点、延长…）不再问人；143 首里这类占了九成要问的 */const SETTLED_KINDS=new Set(['grace_short','grace_unspecified','grace_cluster','grace_long','grace_after','slur','pedal','arpeggio','broken_chord','mordent_upper','mordent_lower','trill','turn','inverted_turn','dots','fermata','staccato','staccatissimo','tenuto','accent','syncopation','ottava','tremolo_single','tremolo_alternating','fingering','glissando','tie','tuplet','finger_overlap']);
const settledEstimate=p=>SETTLED_KINDS.has(p.kind)&&!/冲突|超出|溢出|不明确|无法|选一种|请在/.test(String(p.message||''));
/* 要不要排进「要查」：通用记号已编好就不问 */function askPerformance(n){return hasPerformanceWarning(n)&&performanceItems(n).some(p=>p.realized&&p.estimated&&p.warning_root&&!p.reviewed&&!settledEstimate(p)&&!(p.kind==='source_timing'&&(automaticStartHandled(n)||estimateAccepted(n)||estimateOnly(n)||unmeasuredGrace(n)&&/^装饰音无固定/.test(String(p.message||'')))));}
function hasPerformanceWarning(n){return !!n&&!n.excluded&&n.hand!=='left'&&!n.validation_pending&&performanceItems(n).some(p=>p.realized&&p.estimated&&p.warning_root&&!p.reviewed&&!(p.kind==='source_timing'&&(automaticStartHandled(n)||estimateAccepted(n)||estimateOnly(n))));}
function performanceReady(n){return !!performanceInfo(n)?.realized&&n?.automatic_ready===true&&!n.validation_pending;}
function reviewMissingFields(n,automaticMode=false){const fields=missingFields(n);if(automaticMode&&!performanceReady(n)){const q=performanceInfo(n)?.parameters||{},guessed=q.finger_origin==='estimated'&&Number.isInteger(q.performance_finger)&&q.performance_finger>=1&&q.performance_finger<=5&&n.source_fingering_state!=='unresolved'; /* 11-05：附近有数字没分出去（拿不准）的照样问，只有谱上真没印的才用估的 */ /* 11-04：软件已估好练习指法的，别的音没补完时也不再问指法 */if(unmeasuredGrace(n)||guessed)return fields.filter(field=>!(field==='时长'&&unmeasuredGrace(n))&&!(field==='指法'&&guessed));} /* 11-04：小音符由练习编排自动弹，别的音没补完前也不算缺时长 */if(!automaticMode||!performanceReady(n))return fields;const p=performanceInfo(n),estimatedFinger=p.parameters.finger_origin==='estimated'&&Number.isInteger(p.parameters.performance_finger)&&p.parameters.performance_finger>=1&&p.parameters.performance_finger<=5&&n.source_fingering_state!=='unresolved';return fields.filter(field=>field!=='时长'&&!(field==='指法'&&estimatedFinger));}
function boxFor(note,page,includeFinger=false){if(!page||!finite(page.width)||!finite(page.height)||page.width<=0||page.height<=0)return null;const b=note?.bbox;if(!Array.isArray(b)||b.length!==4||!b.every(finite)||b[2]<=b[0]||b[3]<=b[1])return null;let [x0,y0,x1,y1]=b;if(includeFinger&&Array.isArray(note.finger_bbox)&&note.finger_bbox.length===4&&note.finger_bbox.every(finite)){x0=Math.min(x0,note.finger_bbox[0]);y0=Math.min(y0,note.finger_bbox[1]);x1=Math.max(x1,note.finger_bbox[2]);y1=Math.max(y1,note.finger_bbox[3]);}x0=Math.max(0,Math.min(page.width,x0));y0=Math.max(0,Math.min(page.height,y0));x1=Math.max(x0,Math.min(page.width,x1));y1=Math.max(y0,Math.min(page.height,y1));return x1>x0&&y1>y0?{x:x0,y:y0,width:x1-x0,height:y1-y0}:null;}
function sourceMarkBoxes(note,page){if(!page)return [];const result=[];for(const mark of note?.performance_marks||[]){const source=mark?.source,b=source?.bbox;if(!source||source.page!=null&&Number(source.page)!==Number(note.page)||source.system!=null&&Number(source.system)!==Number(note.system)||!Array.isArray(b)||b.length!==4||!b.every(finite)||b[2]<=b[0]||b[3]<=b[1])continue;const x=Math.max(0,b[0]),y=Math.max(0,b[1]),right=Math.min(page.width,b[2]),bottom=Math.min(page.height,b[3]);if(right>x&&bottom>y)result.push({kind:mark.kind,group_id:mark.group_id,x,y,width:right-x,height:bottom-y,near:Math.abs((y+bottom)/2-((note.bbox?.[1]||0)+(note.bbox?.[3]||0))/2)<=8*Math.max(3,(note.bbox?.[3]||0)-(note.bbox?.[1]||0))});}return result;}
function sourceInkBox(note,page){const head=boxFor(note,page,true),g=note?.glyph_bbox;if(!head)return null;const pieces=[head,...sourceMarkBoxes(note,page).filter(b=>b.near)];if(Array.isArray(g)&&g.length===4&&g.every(finite)&&g[2]>g[0]&&g[3]>g[1])pieces.push({x:Math.max(0,g[0]),y:Math.max(0,g[1]),width:g[2]-g[0],height:g[3]-g[1]});const x=Math.max(0,Math.min(...pieces.map(b=>b.x))),y=Math.max(0,Math.min(...pieces.map(b=>b.y))),right=Math.min(page.width,Math.max(...pieces.map(b=>b.x+b.width))),bottom=Math.min(page.height,Math.max(...pieces.map(b=>b.y+b.height)));return {x,y,width:right-x,height:bottom-y};}
function cropFor(note,page){const b=sourceInkBox(note,page);if(!b)return null;const width=Math.min(page.width,Math.max(95,b.width+70)),height=Math.min(page.height,Math.max(60,b.height+42));return {x:Math.min(page.width-width,Math.max(0,b.x+b.width/2-width/2)),y:Math.min(page.height-height,Math.max(0,b.y+b.height/2-height/2)),width,height};}
function timelineFor(notes,current){if(!current||!finite(current.beat))return null;const same=notes.filter(n=>n.hand===current.hand&&n.page===current.page&&(current.system==null||n.system===current.system)&&finite(n.beat)&&finite(n.duration_beats)&&n.duration_beats>0);if(!same.length)return null;const start=Math.max(0,Math.floor(Math.min(current.beat,...same.map(n=>n.beat)))),end=Math.max(start+4,...same.map(n=>n.beat+n.duration_beats));const windowStart=Math.max(start,Math.floor(current.beat/16)*16),windowEnd=Math.min(end,windowStart+16);return {start:windowStart,end:Math.max(windowStart+4,windowEnd),notes:same.filter(n=>n.beat<windowEnd&&n.beat+n.duration_beats>windowStart)};}
function pitchLabel(pitch){if(!validPitch(pitch))return '例如 C4，中央 Do';const m=/^([A-Ga-g])(##|bb|#|b|)(-?\d+)$/.exec(pitch);const name={C:'Do',D:'Re',E:'Mi',F:'Fa',G:'Sol',A:'La',B:'Si'}[m[1].toUpperCase()];return (m[2]?{'#':'升 ',b:'降 ','##':'重升 ',bb:'重降 '}[m[2]]:'')+name+' · 第 '+m[3]+' 组'+(pitch==='C4'?' · 中央 Do':'');}
const rowKey=(page,system)=>Number.isInteger(Number(page))&&Number(page)>0&&Number.isInteger(Number(system))&&Number(system)>0?Number(page)+':'+Number(system):null;
function rowsFor(project){const map=new Map();const get=(page,system)=>{const key=rowKey(page,system);if(!key)return null;if(!map.has(key))map.set(key,{key,page:Number(page),system:Number(system),notes:[],staves:[]});return map.get(key);};for(const s of project?.staves||[])if(s.hand==='right')get(s.page,s.system)?.staves.push(s);for(const s of project?.staves||[])if(s.hand==='left'){const r=map.get(rowKey(s.page,s.system));if(r)(r.leftStaves||=[]).push(s);} /* 11-04 用户：左手那行也显示，数字印在两行中间时好对照 */for(const n of project?.notes||[])if(n.hand!=='left')get(n.page,n.system)?.notes.push(n);return [...map.values()].sort((a,b)=>a.page-b.page||a.system-b.system);}
function rowCropFor(row,page){if(!row||!page||!finite(page.width)||!finite(page.height)||page.width<=0||page.height<=0)return null;const staves=row.staves.map(s=>s.bbox).filter(b=>Array.isArray(b)&&b.length===4&&b.every(finite)&&b[2]>b[0]&&b[3]>b[1]),heads=row.notes.map(n=>sourceInkBox(n,page)).filter(Boolean);if(!staves.length&&!heads.length)return null;const gap=staves.length?Math.max(3,(staves[0][3]-staves[0][1])/4):6;let x0=staves.length?Math.min(...staves.map(b=>b[0]))-2*gap:0,x1=staves.length?Math.max(...staves.map(b=>b[2]))+2*gap:page.width,y0=staves.length?Math.min(...staves.map(b=>b[1]))-5*gap:Math.min(...heads.map(b=>b.y))-5*gap,y1=staves.length?Math.max(...staves.map(b=>b[3]))+5*gap:Math.max(...heads.map(b=>b.y+b.height))+5*gap;for(const b of heads){x0=Math.min(x0,b.x-gap);x1=Math.max(x1,b.x+b.width+gap);y0=Math.min(y0,b.y-2*gap);y1=Math.max(y1,b.y+b.height+2*gap);}for(const st of row.leftStaves||[]){const b=st.bbox;if(Array.isArray(b)&&b.length===4&&b.every(finite)&&b[3]>y1-gap)y1=Math.max(y1,b[3]+3*gap);}for(const n of row.notes){const stem=n.rhythm_evidence?.stem;if(Array.isArray(stem)&&stem.length===3&&stem.every(finite)){y0=Math.min(y0,stem[1]-gap,stem[2]-gap);y1=Math.max(y1,stem[1]+gap,stem[2]+gap);}}x0=Math.max(0,x0);x1=Math.min(page.width,x1);y0=Math.max(0,y0);y1=Math.min(page.height,y1);return x1>x0&&y1>y0?{x:x0,y:y0,width:x1-x0,height:y1-y0}:null;}
function noteConcern(n,automaticMode=false){return !n?.excluded&&n?.hand!=='left'&&(reviewMissingFields(n,automaticMode).length>0||(!n.validation_pending&&Array.isArray(n.automatic_reasons)&&n.automatic_reasons.length>0));}
function hasTimingWarning(n){if(n?.excluded||n?.hand==='left'||n?.validation_pending||typeof n?.timing_warning!=='string')return false;if(estimateAccepted(n)&&!durationNeedsReviewRaw(n))return false;if(!timingConflict(n)&&performanceItems(n).some(p=>p.kind==='source_timing'&&p.realized&&p.reviewed))return false;const value=unmeasuredGrace(n)?n.timing_warning.split(/[；。]/).filter(t=>!/^装饰音无固定|^主拍位置保留|^可设置时值与开始位置/.test(t)).join('；'):n.timing_warning;return !!value.trim();}
function timingWarningLabel(n){if(!hasTimingWarning(n))return '';if(automaticStartHandled(n))return '≈ 已自动安排（估计），后续自动跟随；不用填写拍数。';const message=n.timing_warning.trim()
 .replace('此处开始时间为估计值，后续已按右手节奏接排；修改此音起拍或时值后，后续时间自动更新。','开始位置是估计的，请核对。')
 .replace('相邻休止时长未确定，此处开始时间暂作估计；修改此音起拍后，后续时间自动更新。','前面休止时长不确定，开始位置待核对。');return '⚠ '+message;}
function startNeedsReview(n){
 if(!n||automaticStartHandled(n))return false;
 const reported=!n.validation_pending&&Array.isArray(n.automatic_reasons)&&n.automatic_reasons.some(r=>/开始位置|起拍/.test(r));
 const warning=hasTimingWarning(n)&&/(?:开始时间|开始位置|起首位置|起拍)[^；。]*(?:估计|未定|不确定|核对|确认|不同)|(?:估计|不确定|核对|确认)[^；。]*(?:开始时间|开始位置|起首位置|起拍)/.test(n.timing_warning);
 return !finite(n.beat)||n.beat<0||reported||warning;
}
/* 11-04 用户：别让人一个个标小音符的时值。装饰音（斜杠小音符、小音符组）按钢琴通用弹法由练习编排自动弹（短倚音快速带过、主音不动），不再当成要问的时值 */function durationNeedsReviewRaw(n){const grace=unmeasuredGrace(n);const missing=(!finite(n?.duration_beats)||n.duration_beats<=0)&&!grace;const reasons=!n?.validation_pending&&Array.isArray(n?.automatic_reasons)&&n.automatic_reasons.some(r=>/音值|音长|时值|时长/.test(r));const warning=!grace&&typeof n?.timing_warning==='string'&&n.timing_warning.split(/[；。]/).some(s=>/(?:核对|确认)[^；。]*(?:音长|音值|时值|时长)|(?:音长|音值|时值|时长)[^；。]*(?:未定|未知|不确定|待核对)|无固定(?:音长|音值|时值|时长)/.test(s));return missing||reasons||warning;}
function durationNeedsReview(n){const grace=unmeasuredGrace(n);const missing=(!finite(n?.duration_beats)||n.duration_beats<=0)&&!grace;const reasons=!n?.validation_pending&&Array.isArray(n?.automatic_reasons)&&n.automatic_reasons.some(r=>/音值|音长|时值|时长/.test(r));const warning=!grace&&hasTimingWarning(n)&&n.timing_warning.split(/[；。]/).some(s=>/(?:核对|确认)[^；。]*(?:音长|音值|时值|时长)|(?:音长|音值|时值|时长)[^；。]*(?:未定|未知|不确定|待核对)|无固定(?:音长|音值|时值|时长)/.test(s));return missing||reasons||warning;}
function pitchNeedsReview(n){return !validPitch(n?.pitch)||(!n?.validation_pending&&Array.isArray(n?.automatic_reasons)&&n.automatic_reasons.some(r=>/音高/.test(r)));}
function humanProgress(project){const notes=(project?.notes||[]).filter(n=>n.hand==='right'&&!n.excluded);return {total:notes.length,reviewed:notes.filter(n=>n.human_reviewed===true).length};}
function softwareHint(n,automaticMode=true){return noteConcern(n,automaticMode)||timingNeedsAction(n)||askPerformance(n);}
// 自动检查无提示和明确人工确认合并计数；同一个音只算一次。
function combinedProgress(project){
 const notes=(project?.notes||[]).filter(n=>n.hand==='right'&&!n.excluded),automaticMode=project?.automatic_mode!==false;
 let checked=0,human=0,modified=0,softwareIssues=0,checking=!!project?.validation_pending;
 for(const n of notes){const hint=softwareHint(n,automaticMode),manual=n.human_reviewed===true;if(hint)softwareIssues++;if(n.validation_pending)checking=true;if(manual)human++;if((Array.isArray(n.manual_fields)&&n.manual_fields.length)||String(n.id||'').startsWith('manual-'))modified++;if(manual||(!n.validation_pending&&!hint))checked++;}
 return {total:notes.length,checked,pending:notes.length-checked,human,modified,softwareIssues,checking};
}
function rowCandidates(row,{page=null,problemsOnly=false,automaticMode=false}={}){return row?.notes.filter(n=>rowKey(n.page,n.system)===row.key&&n.hand==='right'&&!n.excluded&&!missingFields(n).length&&!n.confirmed&&Array.isArray(n.bbox)&&n.bbox.length===4&&n.bbox.every(finite)&&n.bbox[2]>n.bbox[0]&&n.bbox[3]>n.bbox[1]&&(!page||boxFor(n,page))&&(!problemsOnly||noteConcern(n,automaticMode)))||[];}
function rowAnnotationLayout(notes,crop,width=800,{labelWidth=38,laneStep=32,laneGap=5,top=7,boxHeight=27}={}){
 /* 同一位置的音排成一列；只缩小空间不足的列，不让最挤的位置压小整行。 */
 const renderWidth=Math.max(1,Number(width)||800),items=[];
 const valid=notes.filter(n=>Array.isArray(n.bbox)&&n.bbox.length===4&&n.bbox.every(finite)&&n.bbox[2]>n.bbox[0]&&n.bbox[3]>n.bbox[1]);
 const at=n=>Math.max(0,Math.min(renderWidth,((n.bbox[0]+n.bbox[2])/2-crop.x)/crop.width*renderWidth));
 const sorted=valid.map(n=>({n,x:at(n)})).sort((a,b)=>a.x-b.x||a.n.bbox[1]-b.n.bbox[1]);
 const columns=[];
 for(const item of sorted){const last=columns[columns.length-1];if(last&&item.x-last.x<Math.max(3,labelWidth*.35))last.notes.push(item);else columns.push({x:item.x,notes:[item]});}
 for(const c of columns){c.notes.sort((a,b)=>a.n.bbox[1]-b.n.bbox[1]);c.x=c.notes.reduce((t,i)=>t+i.x,0)/c.notes.length;} /* 一列对准这几个音的中间 */
 const count=columns.length,gap=count>1?Math.min(4,laneGap,Math.max(0,(renderWidth-count)/(count-1))):0;
 const minimum=count?Math.min(labelWidth,18,Math.max(.1,(renderWidth-gap*(count-1))/count)):0;
 // 先给每列保留一个可读的最小宽度；只在拥挤处轻微移动，不改变音符顺序。
 const lefts=columns.map(c=>Math.max(0,Math.min(renderWidth-minimum,c.x-minimum/2)));
 for(let i=1;i<count;i++)lefts[i]=Math.max(lefts[i],lefts[i-1]+minimum+gap);
 if(count&&lefts[count-1]+minimum>renderWidth){lefts[count-1]=renderWidth-minimum;for(let i=count-2;i>=0;i--)lefts[i]=Math.min(lefts[i],lefts[i+1]-minimum-gap);}
 // 超密的整行不把标签整体推到一边；允许的位移有限，放不下的列各自变窄。
 const shiftLimit=Math.min(10,Math.max(3,minimum*.55));
 const centers=lefts.map((x,i)=>Math.max(0,Math.min(renderWidth,Math.max(columns[i].x-shiftLimit,Math.min(columns[i].x+shiftLimit,x+minimum/2)))));
 for(const indices of [columns.map((_,i)=>i),columns.map((_,i)=>count-1-i)])for(const i of indices){const lo=Math.max(0,columns[i].x-shiftLimit,i?centers[i-1]+minimum+gap:minimum/2),hi=Math.min(renderWidth,columns[i].x+shiftLimit,i+1<count?centers[i+1]-minimum-gap:renderWidth-minimum/2);if(lo<=hi)centers[i]=Math.max(lo,Math.min(hi,columns[i].x));}
 const pairGaps=centers.slice(1).map((center,i)=>Math.min(gap+.01,Math.max(0,center-centers[i]-1))),band=4*laneStep+boxHeight;let lanes=0,height=0;
 columns.forEach((c,i)=>{
  const center=centers[i],leftSpace=i?(center-centers[i-1]-pairGaps[i-1])/2:center,rightSpace=i+1<count?(centers[i+1]-center-pairGaps[i])/2:renderWidth-center;
  const w=Math.max(.1,Math.min(labelWidth,2*leftSpace,2*rightSpace));
  // 一般列保持原来的 27px 高；窄列按比例变矮，避免变成细长条。
  let h=Math.min(boxHeight,Math.max(Math.min(16,boxHeight),w)),step=laneStep;
  if(c.notes.length>5){h=Math.min(h,Math.max(10,(band-2*(c.notes.length-1))/c.notes.length));step=Math.max(h+2,(band-h)/(c.notes.length-1));}
  c.notes.forEach((item,lane)=>{const y=top+lane*step;lanes=Math.max(lanes,lane+1);height=Math.max(height,y+h+1);items.push({note:item.n,anchor:item.x,left:center-w/2,width:w,lane,top:y,height:h});});
 });
 return {items,lanes,width:renderWidth,height,laneStep,top,boxHeight};
}
// Keep each finger below its printed note. Dense material uses spatial pieces,
// never an evenly spaced replacement strip.
function rowScreenPlan(row,page,width,height){
 let crop=rowCropFor(row,page);if(!crop)return null;
 width=Math.max(220,Number(width)||800);height=Math.max(120,Number(height)||300);
 const gaps=(row.staves||[]).map(s=>(s.bbox?.[3]-s.bbox?.[1])/4).filter(v=>finite(v)&&v>0),gap=gaps.length?Math.min(...gaps):6;
 const located=row.notes.filter(n=>boxFor(n,page));
 const ink=located.map(n=>sourceInkBox(n,page)).filter(Boolean),staves=[...(row.staves||[]),...(row.leftStaves||[])].map(s=>s.bbox).filter(b=>Array.isArray(b)&&b.length===4&&b.every(finite)),stems=located.map(n=>n.rhythm_evidence?.stem).filter(s=>Array.isArray(s)&&s.length===3&&s.every(finite));
 if(ink.length||staves.length){const top=Math.max(crop.y,Math.min(...ink.map(b=>b.y-gap),...staves.map(b=>b[1]-2*gap),...stems.map(s=>Math.min(s[1],s[2])-gap))),bottom=Math.min(crop.y+crop.height,Math.max(...ink.map(b=>b.y+b.height+gap),...staves.map(b=>b[3]+2*gap),...stems.map(s=>Math.max(s[1],s[2])+gap)));crop={...crop,y:top,height:bottom-top};}
 const fit=(part,minGap=5.5)=>{
  let best=null;
  for(const settings of [{labelWidth:38,laneStep:32,laneGap:5,top:7},{labelWidth:24,laneStep:28,laneGap:2,top:5}]){
   let scale=width/part.width;
   for(let attempt=0;attempt<12&&scale>0;attempt++){
    const layout=rowAnnotationLayout(part.notes,part,part.width*scale,settings),budget=(height-layout.height-4)/part.height;
    if(budget+1e-7>=scale){if(gap*scale>=minGap-1e-7&&(!best||scale>best.scale+1e-7))best={...part,scale,renderWidth:part.width*scale,renderHeight:part.height*scale,layout,staffGap:gap*scale};break;}
    if(budget<=0||Math.abs(scale-budget)<1e-7)break;scale=Math.min(scale,budget);
   }
  }
  return best;
 };
 {
  const part={...crop,notes:located};let scale=width/part.width,layout=null;
  // 普通列保持原尺寸；只有超过五个音的列单独缩小。
  // 极端密集时保留可滚动区域，不把末尾的音裁掉。
  for(let attempt=0;attempt<8;attempt++){
   layout=rowAnnotationLayout(located,part,part.width*scale);
   const next=Math.min(width/part.width,Math.max(70,height-layout.height-4)/part.height);
   if(Math.abs(next-scale)<.001){scale=next;break;}scale=next;
  }
  // 再按最终谱宽算一次，防止缩放改变列数后少留空间。
  layout=rowAnnotationLayout(located,part,part.width*scale);
  return {crop,fragments:[{...part,scale,renderWidth:part.width*scale,renderHeight:part.height*scale,layout,staffGap:gap*scale}],width,height,scrollable:Math.max(70,part.height*scale)+layout.height>height};
 }
 const all=fit({...crop,notes:located});if(all)return {crop,fragments:[all],width,height};
 // 用户要看整行、听整行：只要缩小后还看得清（五线谱线距≥3.5 像素）就整行显示；
 // 高度不够时横着切段也放不大，只会切成一两个音的小块。实在太小才切段。
 const whole=fit({...crop,notes:located},3.5);
 if(whole)return {crop,fragments:[whole],width,height};
 {// 指法标签层太高也放不下时：谱子按高度缩小、整行照样显示，标签多出来的部分让框上下滚动
  const part={...crop,notes:located},scale=Math.min(width/part.width,Math.max(1,height-40)/part.height);
  if(scale<width/part.width-1e-7&&gap*scale>=3.5-1e-7){const layout=rowAnnotationLayout(located,part,part.width*scale,{labelWidth:24,laneStep:28,laneGap:2,top:5});return {crop,fragments:[{...part,scale,renderWidth:part.width*scale,renderHeight:part.height*scale,layout,staffGap:gap*scale}],width,height};}
 }
 {// 11-04 用户：不要切成一小段一小段。实在矮也整行按宽度显示，框里上下滚动
  const part={...crop,notes:located},scale=width/part.width;
  const layout=rowAnnotationLayout(located,part,part.width*scale,{labelWidth:24,laneStep:28,laneGap:2,top:5});
  return {crop,fragments:[{...part,scale,renderWidth:part.width*scale,renderHeight:part.height*scale,layout,staffGap:gap*scale}],width,height};
 }
 const groups=[];
 for(const n of located.slice().sort((a,b)=>(a.bbox[0]+a.bbox[2])-(b.bbox[0]+b.bbox[2])||a.bbox[1]-b.bbox[1])){
  const b=boxFor(n,page),x=b.x+b.width/2,last=groups.at(-1);
  if(last&&Math.abs(last.x-x)<gap*.5)last.notes.push(n);else groups.push({x,notes:[n]});
 }
 const partFor=notes=>{
  const boxes=notes.map(n=>sourceInkBox(n,page)),left=Math.max(crop.x,Math.min(...boxes.map(b=>b.x))-3*gap),right=Math.min(crop.x+crop.width,Math.max(...boxes.map(b=>b.x+b.width))+3*gap);
  return {x:left,y:crop.y,width:right-left,height:crop.height,notes};
 };
 const fragments=[];let pending=[];
 const finish=()=>{if(pending.length){fragments.push(fit(partFor(pending)));pending=[];}};
 for(const group of groups){
  if(fit(partFor([...pending,...group.notes]))){pending.push(...group.notes);continue;}
  finish();
  for(const n of group.notes){if(pending.length&&!fit(partFor([...pending,n])))finish();pending.push(n);}
 }
 finish();
 // A single unusually tall source region still keeps its true horizontal
 // geometry; it is never flattened into unrelated note positions.
 for(let i=0;i<fragments.length;i++)if(!fragments[i]){
  const notes=groups.flatMap(g=>g.notes),part=partFor(notes),scale=Math.min(width/part.width,Math.max(1,(height-40))/part.height),layout=rowAnnotationLayout(notes,part,part.width*scale,{labelWidth:24,laneStep:28,laneGap:2,top:5});
  return {crop,fragments:[{...part,scale,renderWidth:part.width*scale,renderHeight:part.height*scale,layout,staffGap:gap*scale}],width,height};
 }
 return {crop,fragments,width,height};
}

const label=(x,y,t,size=16,fill='#20333e')=>`<text x="${x}" y="${y}" text-anchor="middle" font-size="${size}" fill="${fill}">${esc(t)}</text>`;
const line=(x1,y1,x2,y2,stroke='#778891',width=1)=>`<path d="M${x1} ${y1}H${x2}" transform="${y1===y2?'':`rotate(${Math.atan2(y2-y1,x2-x1)*180/Math.PI} ${x1} ${y1})`}" stroke="${stroke}" stroke-width="${width}"/>`;
const staff=(y=65,x=30,w=350)=>`<g data-staff-top="${y}" data-staff-gap="12">`+[0,1,2,3,4].map(i=>`<path d="M${x} ${y+i*12}h${w}" stroke="#8c969b" stroke-width="1"/>`).join('')+'</g>';
const clef=y=>`<text data-clef="treble" x="28" y="${y+51}" font-size="62" font-family="Segoe UI Symbol,serif">𝄞</text>`;
const accidental=(x,y,kind)=>`<g data-accidental="${kind}" data-center-y="${y}" transform="translate(${x} ${y})" fill="none" stroke="#20333e" stroke-width="2.3">${kind==='sharp'?'<path d="M-4-16v32M5-18v32M-10-5L11-9M-10 5L11 1"/>':kind==='flat'?'<path d="M-4-26v35Q14-1 6-7Q2-10-4-3"/>':'<path d="M-5-18v26L5 4V-9L-5-5M5 4v14"/>'}</g>`;
const note=(x,y,{open=false,stem=true,flag=false,color='#20333e',pitch=''}={})=>`<ellipse${pitch?' data-pitch="'+esc(pitch)+'"':''} cx="${x}" cy="${y}" rx="8" ry="5.5" transform="rotate(-20 ${x} ${y})" fill="${open?'white':color}" stroke="${color}" stroke-width="2"/>${stem?`<path d="M${x+7} ${y}v-38${flag?'q19 6 5 25':''}" stroke="${color}" stroke-width="2" fill="none"/>`:''}`;
const svg=inside=>`<svg viewBox="0 0 420 200" role="img" aria-label="读谱示意图，非原谱" xmlns="http://www.w3.org/2000/svg"><rect width="420" height="200" fill="white"/><g font-family="Microsoft YaHei, PingFang SC, sans-serif">${inside}</g></svg>`;
const notationReferences=[
{title:'先分清：右手与指法',body:'只检查右手声部。钢琴谱通常上行是右手、下行是左手；遇到交叉或特殊标记，要按原谱确认。',tip:'音符旁的 1–5 是手指编号，不是 Do、Re、Mi。',art:svg(staff(40)+staff(122)+label(49,76,'右',14,'#008c88')+label(49,158,'左',14,'#657b89')+note(132,76)+label(132,26,'2',16,'#008c88')+note(225,64)+label(225,26,'4',16,'#008c88')+note(312,82)+label(312,26,'3',16,'#008c88')+label(228,191,'只导出已核对的右手音符',12))},
{title:'五个数字，五根手指',body:'1 拇指、2 食指、3 中指、4 无名指、5 小指。左右手都这样编号。',tip:'原谱没有写指法时，先留空；请懂钢琴的人补定，不按音高猜。',art:svg(`<path d="M123 148L83 119Q73 111 67 122Q64 129 73 137L118 177Q133 192 200 188Q267 187 270 155L275 99Q275 88 265 88Q254 88 254 99V131L243 129V58Q243 46 232 46Q221 46 221 58V126L208 125V36Q208 22 196 22Q185 22 185 36V126L172 128V55Q172 43 160 43Q148 43 148 55V141Z" fill="#d6f4f0" stroke="#278e89" stroke-width="2"/>`+label(86,143,'1')+label(160,79,'2')+label(196,60,'3')+label(232,83,'4')+label(264,118,'5'))},
{title:'音越高，位置越高',body:'高音谱号下，音符沿线与间逐级升高。C D E F G A B 对应 Do Re Mi Fa Sol La Si。',tip:'C4 是中央 Do；C5 高一个八度。上方 8va 高八度，下方 8vb 低八度，虚线结束后恢复。',art:svg(staff(58)+clef(58)+[0,1,2,3,4,5,6,7].map((i)=>{const x=91+i*40,y=118-i*6;return(i===0?`<path d="M79 118h25" stroke="#20333e"/>`:'')+note(x,y,{stem:false,pitch:['C4','D4','E4','F4','G4','A4','B4','C5'][i]})+label(x,153,['C4','D4','E4','F4','G4','A4','B4','C5'][i],12);}).join('')+label(213,182,'从下往上：线、间、线、间……',12))},
{title:'升、降、还原要一起看',body:'♯ 升半音，♭ 降半音，♮ 还原。写在谱号后的是调号；写在音旁的临时记号通常管本小节同音名、同八度。',tip:'F♯4 在输入框写 F#4，B♭4 写 Bb4；跨小节恢复调号。',art:svg(staff(64)+clef(64)+accidental(82,106,'sharp')+note(110,106,{pitch:'F#4'})+label(111,157,'F#4',17)+accidental(204,88,'flat')+note(232,88,{pitch:'Bb4'})+label(232,157,'Bb4',17)+accidental(322,106,'natural')+note(349,106,{pitch:'F4'})+label(349,157,'F4',17))},
{title:'拍号管分组，速度管快慢',body:'2/4、3/4、4/4：每小节分别有 2、3、4 个四分音符拍。6/8 有 6 个八分音符，通常按 3+3 分成两大拍。',tip:'本软件 120 BPM = 四分音符每拍 0.5 秒；6/8 一小节填 3 拍。若原谱速度以附点四分音符计，输入 BPM × 1.5。',art:svg(label(70,60,'2/4',27)+label(203,60,'3/4',27)+label(343,60,'6/8',27)+[40,90,160,204,248].map((x)=>`<circle cx="${x}" cy="104" r="10" fill="#52bfb5"/>`).join('')+[299,318,337,359,378,397].map((x,i)=>`<circle cx="${x}" cy="104" r="6" fill="${i<3?'#278e89':'#91c9c3'}"/>`).join('')+label(69,143,'1　2',15)+label(204,143,'1　2　3',15)+label(347,143,'1 2 3  4 5 6',12)+label(209,183,'同一速度下，先保留原谱的长短关系',12))},
{title:'看符头、符干、符尾',body:'全音符 4 拍，二分 2 拍，四分 1 拍，八分 0.5 拍，十六分 0.25 拍。连在一起的横梁也表示符尾。',tip:'这里的拍都按四分音符 = 1 计算。空心和实心不能看漏。',art:svg(note(45,90,{open:true,stem:false})+note(125,90,{open:true})+note(205,90)+note(285,90,{flag:true})+note(365,90,{flag:true})+`<path d="M372 62q18 6 5 24" stroke="#20333e" stroke-width="2" fill="none"/>`+[4,2,1,.5,.25].map((v,i)=>label(45+i*80,145,v+' 拍',16)).join(''))},
{title:'空白也有节奏',body:'休止符表示不发音。全休止表示整小节时按拍号计时：2/4 中是 2 拍。附点加一半，1 拍变 1.5 拍。',tip:'休止要保留，下一音晚些开始。三连音：3 个音占 2 个同类音的时间。',art:svg(`<g data-rest="whole"><path data-reference-line="63" d="M47 63h45" stroke="#8c969b"/><rect x="57" y="63" width="25" height="7" fill="#20333e"/></g><g data-rest="half"><path data-reference-line="82" d="M123 82h45" stroke="#8c969b"/><rect x="133" y="75" width="25" height="7" fill="#20333e"/></g><path d="M217 53l-9 16 17 13-15 13 13 13" stroke="#20333e" stroke-width="5" fill="none"/><path d="M285 74q17 0 10-14q-9-6-11 4q-2 9 14 6l-12 36" stroke="#20333e" stroke-width="3" fill="none"/>`+note(363,96)+`<circle cx="380" cy="95" r="3" fill="#20333e"/>`+label(70,146,'全休止*',14)+label(146,146,'休 2 拍',14)+label(217,146,'休 1 拍',14)+label(290,146,'休 0.5 拍',13)+label(365,146,'1.5 拍',14)+label(210,184,'* 整小节休止：时长跟随拍号',12))},
{title:'同一列，一起按',body:'上下叠着的音通常同时弹，就是和弦。每个音各填一行，但“开始”相同。',tip:'不同声部可能有不同长度；竖着的波浪线是琶音，需要额外核对先后。',art:svg(staff(55)+clef(55)+note(112,73,{pitch:'C5'})+note(112,61,{pitch:'E5'})+note(112,49,{pitch:'G5'})+label(110,151,'同时开始',15)+label(299,63,'C5　开始 0　时长 1',14)+label(299,99,'E5　开始 0　时长 1',14)+label(299,135,'G5　开始 0　时长 1',14))},
{title:'弧线不是一回事',body:'相同音高用延音线连接：时长相加，中间不重弹。连接不同音的圆滑线只提示连贯奏法，仍保留各个音。',tip:'确认音高相同、确为延音线后，再勾“合并延音线”。',art:svg(staff(72)+note(73,96)+note(152,96)+`<path d="M75 108Q111 139 152 108" fill="none" stroke="#20333e" stroke-width="2"/>`+note(267,96)+note(345,78)+`<path d="M268 61Q300 30 348 43" fill="none" stroke="#20333e" stroke-width="2"/>`+label(116,166,'同音：延长',15)+label(307,166,'不同音：连贯',15))},
{title:'遇到反复，看房号',body:'到反复记号时回到前面的反复起点；没有起点时通常回曲首。第一遍进 1 房，第二遍跳过 1 房进 2 房。',tip:'先对照整段，再决定“展开反复”。不确定的跳转先请人确认。',art:svg(staff(79)+`<path d="M71 79v48" stroke="#20333e" stroke-width="3"/><path d="M79 79v48M270 79v48M380 79v48" stroke="#20333e"/><path data-repeat="end" d="M278 79v48" stroke="#20333e" stroke-width="3"/><circle cx="89" cy="97" r="3"/><circle cx="89" cy="109" r="3"/><circle cx="260" cy="97" r="3"/><circle cx="260" cy="109" r="3"/><path data-ending="1" d="M220 61V45H278" fill="none" stroke="#20333e"/><path data-ending="2" d="M292 61V45H380" fill="none" stroke="#20333e"/>`+label(238,62,'1.',14)+label(313,62,'2.',14)+label(207,165,'第一遍 → 1 房　第二遍 → 2 房',14))},
{title:'点黄色音，在下方修改',body:'先点原谱上的黄色音，再看下方黄色项目。指法点 1～5，音长选相同样式；开始位置按本小节第 1 拍起算，1.5 在第 1、2 拍中间。',tip:'不确定先保留，点“下一处”继续；没有黄色也要对照原谱抽查。',art:svg(`<rect x="24" y="28" width="372" height="139" rx="7" fill="#edf7f5"/>`+label(107,69,'指法 1～5',21)+label(303,69,'音长 1 拍',21)+label(107,119,'开始 1.5 拍',21)+label(303,119,'下一处',21)+label(210,188,'按本小节算开始位置；音长单独选择',12))}
];
// Beginner examples use the same keyboard and colour for a key and its score note.
const KEY_NAMES=['Do','Re','Mi','Fa','Sol','La','Si','Do'];
const WHITE_MIDI=[60,62,64,65,67,69,71,72];
const NOTE_NAMES={60:'C4',61:'C#4',62:'D4',63:'D#4',64:'E4',65:'F4',66:'F#4',67:'G4',68:'G#4',69:'A4',70:'Bb4',71:'B4',72:'C5'};
const guideSvg=content=>`<svg viewBox="0 0 520 360" role="img" aria-label="琴键与读谱示意，非原谱" xmlns="http://www.w3.org/2000/svg"><rect width="520" height="360" fill="white"/><g font-family="Microsoft YaHei,PingFang SC,sans-serif">${content}</g></svg>`;
function keyX(midi){const white=WHITE_MIDI.indexOf(midi);if(white>=0)return 50+(white+.5)*52.5;const left={61:0,63:1,66:3,68:4,70:5}[midi];return left===undefined?76:50+(left+1)*52.5;}
function keys(pressed=[],group=false){
 let out='<g data-keyboard="C4-C5">';
 WHITE_MIDI.forEach((m,i)=>{const x=50+i*52.5,on=pressed.includes(m);out+=`<g data-key="${m}" data-pressed="${on}"><rect x="${x}" y="206" width="52.5" height="112" rx="3" fill="${on?'#62d7ce':'#fff'}" stroke="#566b76" stroke-width="1.5"/>${label(x+26.25,302,KEY_NAMES[i],20)}</g>`;});
 [61,63,66,68,70].forEach(m=>{const on=pressed.includes(m);out+=`<rect data-key="${m}" data-pressed="${on}" x="${keyX(m)-16}" y="206" width="32" height="64" rx="3" fill="${on?'#00a79e':group&&m<64?'#287f7b':'#20333e'}" stroke="${group&&m<64?'#00a79e':'#20333e'}" stroke-width="${group&&m<64?4:1}"/>`;});
 return out+'</g>';
}
function guideStaff(pitches,words=[],options={}){
 const top=50,gap=16;
 let out=`<g data-staff-top="${top}" data-staff-gap="${gap}" data-clef="treble">`+[0,1,2,3,4].map(i=>`<path d="M70 ${top+i*gap}h380" stroke="#9ca8ae"/>`).join('')+`<text x="52" y="${top+70}" font-size="85" font-family="Segoe UI Symbol,serif">𝄞</text>`;
 pitches.forEach((m,i)=>{
  const pitch=options.noteNames?.[i]||NOTE_NAMES[m],letter=pitch[0],oct=Number(pitch.at(-1)),y=top+(38-(oct*7+'CDEFGAB'.indexOf(letter)))*gap/2,x=options.stacked?268:(pitches.length===1?268:170+i*110);
  if(y>=top+5*gap)out+=`<path d="M${x-17} ${top+5*gap}h34" stroke="#20333e" stroke-width="2"/>`;
  if(pitch.includes('#'))out+=accidental(x-25,y,'sharp');else if(pitch.includes('b'))out+=accidental(x-25,y,'flat');else if(options.natural)out+=accidental(x-25,y,'natural');
  out+=note(x,y,{pitch,color:'#008c88',open:!!options.open,stem:true});
  if(options.dot)out+=`<circle cx="${x+19}" cy="${y-3}" r="4" fill="#008c88"/>`;
  if(!options.stacked)out+=label(x,180,words[i]||pitch,22,'#008c88');
 });
 if(options.stacked)out+=label(268,180,words.join(' ＋ '),22,'#008c88');
 return out+'</g>';
}
function board(pressed,caption,options={}){
 return guideSvg((options.top||guideStaff(options.pitches||pressed,options.words||[],options))+keys(pressed,!!options.group)+label(260,345,caption,21,'#008c88'));
}
function centreKeyboard(){
 const whites=[];for(let m=21;m<=108;m++)if([0,2,4,5,7,9,11].includes(m%12))whites.push(m);
 let art=label(260,29,'88 键钢琴：中央 Do 在这里',21),width=440/52;
 whites.forEach((m,i)=>{art+=`<rect x="${40+i*width}" y="50" width="${width}" height="49" fill="${m===60?'#62d7ce':'white'}" stroke="#6c808a" stroke-width=".7"/>`;});
 for(let m=22;m<108;m++)if([1,3,6,8,10].includes(m%12)){const i=whites.filter(v=>v<m).length;art+=`<rect x="${40+i*width-2.6}" y="50" width="5.2" height="29" fill="#20333e"/>`;}
 const x=40+(whites.indexOf(60)+.5)*width;
 return art+`<path d="M${x} 136V105m-5 6 5-6 5 6" fill="none" stroke="#008c88" stroke-width="3"/>`+label(x,165,'中央 Do',23,'#008c88');
}
const makeFrame=(labelText,text,art,tones=[],ms=1300,extra={})=>({label:labelText,text,art,tones,ms,...extra});
const makeLesson=(id,title,body,frames,reference,extra={})=>({id,title,body,frames,art:frames[0].art,reference,tip:'先点下面的小步骤看，再点“播放演示”。',...extra});
const lessons=[
 makeLesson('right-hand','先看哪一行？','本例先看标成“右”的这一行。',[makeFrame('看右手这一行','绿色“右”标出的，是本例要检查的部分。',notationReferences[0].art)],0),
 makeLesson('fingers','数字 2，就是食指','数字只告诉你用哪根手指，不告诉你按哪个琴键。',[makeFrame('认五根手指','从拇指开始：1、2、3、4、5。',notationReferences[1].art)],1),
 makeLesson('find-do','先找到一个键：中央 Do','先认住这个白键，再看谱上的圆点。',[
  makeFrame('① 找中央区域','整架钢琴有好几个 Do。我们先找箭头所指的中央 Do。',board([60],'下面是中央区域的放大图',{top:centreKeyboard()}),[],1800),
  makeFrame('② 找两个黑键','看这组挨在一起的两个黑键；它们左边紧挨的白键就是 Do。',board([60],'两个黑键左边的白键',{top:label(260,75,'先看这两个黑键',25)+`<path d="M102 172v-12h53v12" stroke="#008c88" stroke-width="4" fill="none"/>`+label(260,120,'绿色白键 = 中央 Do',24,'#008c88'),group:true}),[60],1800),
  makeFrame('③ 对上谱上的点','谱上这条短横线中的圆点，和绿色琴键，是同一个音。',board([60],'这个键，在软件里写作 C4',{words:['中央 Do']}),[60],1600)
 ],2),
 makeLesson('pitch-step','往右换一个白键，听听变化','本例没有升降号：Do、Re、Mi 是三个相邻白键。',[
  makeFrame('Do','先看绿色 Do，再听它的声音。',board([60],'本例用拇指（1）',{words:['Do']}),[60]),
  makeFrame('Re','换到右边下一个白键；谱上的点也上去一格。',board([62],'本例用食指（2）',{words:['Re']}),[62]),
  makeFrame('Mi','再往右一个白键；声音更尖一点。',board([64],'本例用中指（3）',{words:['Mi']}),[64])
 ],2,{tip:'这里的指法只是例子；Do 不一定总用拇指。'}),
 makeLesson('accidentals','看到升号，换到紧挨着的右键','先看普通 Do，再看升 Do。',[
  makeFrame('普通 Do','先按这个白键。',board([60],'普通 Do',{words:['Do']}),[60]),
  makeFrame('♯ 升 Do','升号让你向右挪到紧挨着的键。这一次是黑键。',board([61],'右边紧挨的黑键：升 Do',{words:['升 Do']}),[61]),
  makeFrame('♭ 降 Re','换个例子：Re 左边紧挨的键，就是降 Re；它恰好也是刚才那个黑键。',board([61],'降 Re：从 Re 向左挪一个键',{pitches:[61],noteNames:['Db4'],words:['降 Re']}),[61]),
  makeFrame('♮ 还原','回到普通 Do，取消这个例子里的升号。',board([60],'回到这个白键',{words:['Do'],natural:true}),[60])
 ],3,{tip:'升、降看的是紧挨着的琴键；不一定每次都是黑键。'}),
 makeLesson('beat','一拍有多久？先跟着数','这个演示里，一拍就是一秒。',Array.from({length:4},(_,i)=>makeFrame('数 '+(i+1),'跟着亮点，每秒数一下：'+(i+1)+'。',guideSvg(label(260,42,'演示：每秒亮一下',24)+[0,1,2,3].map(n=>`<circle cx="${110+n*100}" cy="106" r="32" fill="${n===i?'#62d7ce':'#e6edef'}"/>`+label(110+n*100,115,String(n+1),26)).join('')+keys([60])+label(260,345,'每亮一次，弹一下 Do',21)),[60],1000)),4,{tip:'真实曲谱可能快一些或慢一些。先在这里感受均匀的“一下、一下”。'}),
 makeLesson('duration','什么时候松开？看它要按多久','在这个每拍一秒的例子里，比一比短音和长音。',[
  makeFrame('短音：按 1 秒','黑色、带竖线的这个音，按住一秒。',board([60],'按下，保持 1 秒',{words:['这个音：1 拍']}),[60],1000),
  makeFrame('短音：松开','一秒到了，松开。',board([],'松开',{pitches:[60],words:['1 拍结束']}),[],700),
  makeFrame('长音：按 2 秒','空心、带竖线的这个音，按住两秒。',board([60],'按下，保持 2 秒',{words:['这个音：2 拍'],open:true}),[60],2000),
  makeFrame('长音：松开','两秒到了，再松开。',board([],'松开',{pitches:[60],words:['2 拍结束'],open:true}),[],700)
 ],5),
 makeLesson('rest','休止：松手，也要等够时间','休止符像一个“先别弹”的指令。',[
  makeFrame('先弹 Do','第 0 秒：按 Do 一秒。',board([60],'先按 1 秒',{words:['Do']}),[60],1000),
  makeFrame('松手等 1 秒','第 1 秒：不按任何键，安静地等一秒。',board([],'松手，安静等待 1 秒',{top:label(260,40,'看到这个符号：先别弹',22)+`<path d="M260 65l-13 25 25 19-22 20 18 18" fill="none" stroke="#20333e" stroke-width="7"/>`}),[],1000),
  makeFrame('再弹 Re','第 2 秒到了，才按下 Re。',board([62],'现在才按下一个音',{words:['Re']}),[62],1000)
 ],6),
 makeLesson('chord','两个点叠在一起：一起按','本例用拇指和中指，同时按 Do 与 Mi。',[
  makeFrame('一起按下','两颗绿色谱点、两个绿色琴键，一起开始。',board([60,64],'本例：拇指 1 ＋ 中指 3',{words:['Do','Mi'],stacked:true}),[60,64],1500),
  makeFrame('一起松开','这个例子的两个音一样长，所以一起松开。',board([],'两个键一起松开',{pitches:[60,64],words:['Do','Mi'],stacked:true}),[],900)
 ],7),
 makeLesson('dotted','后面加个小点：多按一半','原来按一秒，加点后要按一秒半。',[
  makeFrame('原来 1 秒','先听没有小点的一秒。',board([60],'原来：1 秒',{words:['没有点']}),[60],1000),
  makeFrame('加点后 1.5 秒','多出来的半秒，要继续按住。',board([60],'1 秒 ＋ 半秒 = 1.5 秒',{words:['注意右边的小点'],dot:true}),[60],1500),
  makeFrame('到时间再松开','等满一秒半，再松开。',board([],'现在松开',{pitches:[60],words:['加点音结束'],dot:true}),[],700)
 ],6),
 makeLesson('tie','同一个音连起来：中间别再按','这个例子里的两颗 Do，连成一次两秒的长按。',[
  makeFrame('第 0 秒：按下','只在这里按下 Do 一次。',board([60],'按下 Do',{top:staff(62,60,400)+clef(62)+note(180,122)+note(330,122)+`<path d="M180 134Q255 177 330 134" fill="none" stroke="#008c88" stroke-width="3"/>`+label(260,35,'同一个音，用延音线连住',22)}),[60],1000),
  makeFrame('第 1 秒：继续按','走到第二颗 Do，也不松手、不重新按。',board([60],'继续按住，不重新弹',{words:['仍然是 Do']}),[60],1000,{sustain:true}),
  makeFrame('第 2 秒：松开','总共两秒结束，现在松开。',board([],'两秒到，松开',{pitches:[60],words:['Do']}),[],800)
 ],8),
 makeLesson('slur','不同的音连起来：仍然换键','这个例子从 Do 换到 Re，两个音都要弹。',[
  makeFrame('先按 Do','先弹第一颗音。',board([60],'先弹 Do',{words:['Do']}),[60],1000),
  makeFrame('换到 Re','尽量连贯地换键，不把两个音合成一个。',board([62],'换到 Re',{top:staff(62,60,400)+clef(62)+note(180,122)+note(330,116)+`<path d="M182 78Q255 35 332 72" fill="none" stroke="#008c88" stroke-width="3"/>`+label(260,178,'弧线提示连贯，仍然弹两个音',20)}),[62],1000),
  makeFrame('最后松开','第二个音结束后，再松开。',board([],'结束，松开',{pitches:[62],words:['Re']}),[],700)
 ],8),
 makeLesson('repeat','反复：照着路线再走一遍','这个例子的路线是 A → B → A → C。',['A','B','A','C'].map((part,i)=>makeFrame(['先走 A','第一遍走 B','回到 A','第二遍走 C'][i],['先弹公共的一段 A。','第一遍进入标着 1 的结尾 B。','遇到反复记号，回去再弹 A。','第二遍跳过 B，进入标着 2 的结尾 C。'][i],guideSvg(label(260,38,'完整路线：A → B → A → C',24)+['A','B','A','C'].map((p,n)=>`<rect x="${48+n*119}" y="88" width="88" height="90" rx="8" fill="${i===n?'#62d7ce':'#eaf0f2'}"/>`+label(92+n*119,143,p,30)+(n<3?label(151+n*119,141,'→',25):'')).join('')+label(211,211,'1 号结尾',19)+label(449,211,'2 号结尾',19)+label(260,285,['第一遍：开始','第一遍：进 1 号结尾','返回公共段 A','第二遍：跳过 B，进 C'][i],23,'#008c88')),[],1500,{part})),9),
 makeLesson('review','回到软件：只核对四件事','哪个键、哪根手指、什么时候按、按多久。',[
  makeFrame('看一个具体例子','本例：拇指按中央 Do，从第 0 秒开始，按一秒。',board([60],'本例：拇指按中央 Do 一秒',{words:['中央 Do']}),[60],1000),
  makeFrame('对应软件的四个框','音高、指法、开始、时长，分别对应这四件事。',guideSvg([['哪个键','音高：C4'],['哪根手指','指法：1 拇指'],['什么时候按','开始：0 拍'],['按多久','时长：1 拍']].map(([a,b],i)=>{const y=48+i*73;return `<rect x="30" y="${y-25}" width="460" height="62" rx="6" fill="#edf7f5"/>`+label(144,y+8,a,21)+label(363,y+8,b,22,'#008c88');}).join('')),[],2000)
 ],10,{tip:'示例是每拍一秒。真正填写时，看原谱并核对，不要把这里的秒数直接套进去。'})
];
// 课程文案：直接讲结论，一课一个知识点。图和声音沿用上面的演示。
const LESSON_COPY={
 fingers:{title:'指法：数字对应手指',body:'谱上音符旁的 1～5 是手指编号，不代表琴键。',tip:'谱上没印数字的音，软件显示灰色，手套不会替它按。',frames:[['1～5 号手指','1 拇指、2 食指、3 中指、4 无名指、5 小指。']]},
 'find-do':{title:'音高：先定位中央 Do',body:'两个黑键一组，左边紧挨的白键就是 Do。',tip:'中央 Do 写作 C4，其他键都从它往左右数。',frames:[['钢琴中部','键盘上有很多个 Do，先看中间这一个。'],['两黑键左边','一组两个黑键左边的白键就是 Do。'],['谱上的位置','高音谱表下方加一条短线，就是中央 Do。']]},
 'pitch-step':{title:'音高：谱上升一格，键右移一个',body:'五线谱上每升高一格（线或间），琴键就向右移一个白键。',tip:'C D E F G A B 依次对应 Do Re Mi Fa Sol La Si。',frames:[['Do · C4','短横线上：中央 Do。'],['Re · D4','升一格，右移一个白键。'],['Mi · E4','再升一格，再右移一个白键。']]},
 accidentals:{title:'升降号：移到紧挨着的键',body:'♯ 向右移一个键，♭ 向左移一个键，♮ 取消升降。',tip:'紧挨着的键不一定是黑键，比如 Mi 升高后就是 Fa 的白键。',frames:[['原音 Do','没有记号，弹白键。'],['♯ 升 Do','向右紧挨的键。'],['♭ 降 Re','Re 向左紧挨的键，和升 Do 是同一个键。'],['♮ 还原','取消升降，回到白键。']]},
 beat:{title:'节拍：均匀的基本单位',body:'音乐按均匀的拍子走，音的长短都用「几拍」来算。',tip:'一拍的实际快慢由曲谱速度决定，这里演示每秒一拍。',frames:[['第 1 拍','每拍时间相等。'],['第 2 拍','每拍时间相等。'],['第 3 拍','每拍时间相等。'],['第 4 拍','每拍时间相等。']]},
 duration:{title:'时值：看音符样子定按多久',body:'实心带杆 1 拍，空心带杆 2 拍，空心无杆 4 拍；每多一条尾巴或横梁，时长减半。',tip:'1 条尾巴半拍，2 条 ¼ 拍。',frames:[['实心：1 拍','按住 1 拍。'],['松开','到时松开。'],['空心：2 拍','按住 2 拍。'],['松开','到时松开。']]},
 dotted:{title:'附点：时长加一半',body:'音符右边的小圆点，让时长变成 1.5 倍。',tip:'注意区分：音符上下方的小点是跳音，不是附点。',frames:[['不带点：1 拍','按住 1 拍。'],['带点：1 拍半','多按半拍。'],['松开','到时松开。']]},
 rest:{title:'休止符：这段时间不弹',body:'休止符占时间但不发声，到点后再弹下一个音。',tip:'',frames:[['弹 Do','按住 1 拍。'],['休止 1 拍','松手等待。'],['弹 Re','休止结束后弹。']]},
 chord:{title:'和弦：上下叠着的音同时弹',body:'竖着对齐的音同时按下。',tip:'各音的指法从上到下分别对应。',frames:[['同时按下','两个音一起开始。'],['同时松开','时值相同就一起松开。']]},
 tie:{title:'延音线：相同的音连起来只弹一次',body:'两个相同音之间的弧线，表示按下后一直按住。',tip:'手指不要重新按，总时长相加。',frames:[['按下','只按这一次。'],['继续按住','第二个音不重新按。'],['松开','总时长结束后松开。']]},
 slur:{title:'连音线：不同的音连贯地弹',body:'不同音之间的弧线表示连贯，每个音都要弹。',tip:'外观和延音线相似：看弧线两端的音是否相同。',frames:[['弹 Do','第一个音。'],['换到 Re','连贯地换键。'],['松开','最后一个音结束后松开。']]},
 repeat:{title:'反复记号：按路线再弹一遍',body:'反复记号之间的段落弹两遍，带 1、2 编号的结尾各走一次。',tip:'软件可以自动展开反复。',frames:[['A 段','公共段落。'],['第 1 结尾','第一遍走这里。'],['返回 A 段','遇到反复记号回去。'],['第 2 结尾','第二遍跳过第 1 结尾。']]}
};
for(let index=lessons.length-1;index>=0;index--){const lesson=lessons[index],copy=LESSON_COPY[lesson.id];if(!copy){lessons.splice(index,1);continue;}lesson.title=copy.title;lesson.body=copy.body;lesson.tip=copy.tip;copy.frames.forEach(([labelText,text],frame)=>{if(lesson.frames[frame]){lesson.frames[frame].label=labelText;lesson.frames[frame].text=text;}});}
const lessonOrder=Object.keys(LESSON_COPY);lessons.sort((a,b)=>lessonOrder.indexOf(a.id)-lessonOrder.indexOf(b.id));

function create(host){
 const $=id=>document.getElementById(id);let selectedId=null,lastProject=null,filter='right',guideStep=0,rendering=false,activeRowKey=null,rowMode=true,editorOpen=false,problemsOnly=false,suppressAutoSelect=false,editorAnchor=null,editorPinned=null,retainedNoteId=null,localInputInvalid=false,pendingAutoNext=null,fragmentIndex=0,fragmentRowKey=null,fragmentSelectedId=null,fragmentCount=1,initialIssueSelection=null,displayFragments=[],rowLayoutQueued=false,lastRowWidth=-1,lastRowHeight=-1,pendingDurationChoice=null;
 const organizeTools=()=>{const panel=$('review-tools-panel'),toolbar=document.querySelector?.('.review-toolbar');if(!panel||!toolbar)return;for(const id of ['native-score-catalog','add-note']){const e=$(id);if(e&&e.parentElement===toolbar)panel.appendChild(e);}const mode=$('review-row-mode');if(mode&&mode.parentElement!==panel)panel.appendChild(mode);const options=$('review-more');if(options&&options.parentElement!==panel)panel.appendChild(options);};
 organizeTools();
 const currentProject=()=>host.project();
 let performancePanel=null,performanceModeControl=null,selectedTechniqueKey=null,pendingPerformanceEdit=null;const performanceNodes={};
 const perf$=id=>performanceNodes[id];
 function performanceNode(tag,id,text='',cls=''){const node=document.createElement(tag);node.id=id;if(text)node.textContent=text;if(cls)node.className=cls;performanceNodes[id]=node;return node;}
 function buildPerformanceControls(){
  const section=$('review-duration-section'),tools=$('review-tools-panel');if(!section||!tools)return;
  performancePanel=performanceNode('div','review-performance-controls','','review-performance-controls');performancePanel.hidden=true;
  const heading=performanceNode('div','review-performance-heading','','review-performance-heading');heading.appendChild(performanceNode('strong','review-performance-label'));heading.appendChild(performanceNode('select','review-performance-kind'));heading.appendChild(performanceNode('select','review-performance-interpretation'));heading.appendChild(performanceNode('span','review-performance-status'));performancePanel.appendChild(heading);const context=performanceNode('div','review-performance-context','','review-performance-context');context.appendChild(performanceNode('p','review-performance-message'));const inset=performanceNode('button','review-performance-inset','','review-performance-inset');inset.type='button';inset.hidden=true;context.appendChild(inset);performancePanel.appendChild(context);
  const fields=performanceNode('div','review-performance-parameters','','review-performance-parameters');
  const choices=[['placement','落点',[['before','拍前带过'],['on','从拍点开始'],['after','主音后收尾']]],['borrow','长短',[[.0625,'很短'],[.125,'较短'],[.25,'¼ 适中'],[.5,'½ 较长'],[.666667,'⅔ 保持']]],['rate','快慢',[[4,'慢'],[8,'适中'],[12,'快'],[16,'很快']]],['aux','配合手指',[['','自动练习指法'],...[1,2,3,4,5].map(n=>[n,n+' 指'])]],['lower-aux','下邻手指',[['','自动'],...[1,2,3,4,5].map(n=>[n,n+' 指'])]],['hold','多停一会',[[1.25,'稍停'],[1.5,'适中'],[2,'较长'],[3,'更长']]],['gate','触键',[[.25,'很短'],[.5,'短'],[.9,'普通'],[1,'保持到尾'],[1.05,'连贯']]],['velocity','声音强弱',[[64,'柔和'],[96,'普通'],[112,'突出'],[127,'强']]]];
  for(const [id,text,options] of choices){const field=performanceNode('label','review-performance-'+id+'-field',text),control=performanceNode('select','review-performance-'+id);for(const [value,label]of options){const option=document.createElement('option');option.value=String(value);option.textContent=label;control.appendChild(option);}field.appendChild(control);fields.appendChild(field);}performancePanel.appendChild(fields);
  const actions=performanceNode('div','review-performance-actions','','review-performance-actions');for(const [id,text] of [['auto','采用练习编排'],['reset','恢复自动'],['written','书面音符']]){const b=performanceNode('button','review-performance-'+id,text);b.type='button';actions.appendChild(b);}performancePanel.appendChild(actions);
  section.insertBefore?section.insertBefore(performancePanel,section.firstChild):section.appendChild(performancePanel);
  const label=performanceNode('label','review-performance-mode-field','装饰音处理 ','review-performance-mode'),mode=performanceNode('select','review-performance-mode');for(const [value,text]of [['practice','练习编排'],['strict','只按书面音符']]){const option=document.createElement('option');option.value=value;option.textContent=text;mode.appendChild(option);}label.appendChild(mode);tools.appendChild(label);performanceModeControl=label;
  perf$('review-performance-inset').onclick=()=>{selectedTechniqueKey=perf$('review-performance-inset').dataset.techniqueKey||null;renderPerformanceEditor(current());renderRow();};
  perf$('review-performance-interpretation').onchange=()=>{const kind=perf$('review-performance-interpretation').value;return editPerformance({...(kind?{kind}:{}),mode:'auto',reviewed:false},false,kind?[]:['kind']);};
  perf$('review-performance-reset').onclick=resetPerformance;
  perf$('review-performance-kind').onchange=()=>{selectedTechniqueKey=perf$('review-performance-kind').value;renderPerformanceEditor(current());renderRow();};
  perf$('review-performance-mode').onchange=()=>setPerformancePolicy(perf$('review-performance-mode').value);
  perf$('review-performance-auto').onclick=()=>editPerformance({mode:'auto',reviewed:true},true);
  perf$('review-performance-written').onclick=()=>{if(unmeasuredGrace(current())){host.notice('这个装饰音没有固定书面时长，请用练习编排或明确排除。');return false;}return editPerformance({mode:'written',reviewed:true});};
  for(const [id,key] of [['placement','placement'],['borrow','borrow_ratio'],['rate','rate_hz'],['aux','aux_finger'],['lower-aux','lower_aux_finger'],['hold','hold_factor'],['gate','gate_ratio'],['velocity','velocity']])perf$('review-performance-'+id).onchange=()=>{const value=perf$('review-performance-'+id).value;return editPerformance({[key]:key==='placement'?value:value===''?null:Number(value),mode:'auto',reviewed:false});};
 }
 function setPerformancePolicy(mode){if(!['practice','strict'].includes(mode)||!commitPendingEdits())return false;pendingPerformanceEdit=null;pendingAutoNext=null;const p=currentProject();if(!p)return false;p.performance_policy={...(p.performance_policy||{}),mode};for(const n of p.notes||[])n.validation_pending=true;host.changed();renderInspector();refreshValidation();return true;}
 function ownsKindFamily(note,kind){const kinds=(note.performance_marks||[]).map(m=>m.kind);if(kind==='trill_with_lower_mordent')return kinds.includes('trill')&&kinds.includes('mordent_lower');if(/^grace_/.test(kind||''))return !!note.grace_kind||kinds.some(k=>/^grace_/.test(k));if(['mordent_upper','mordent_lower'].includes(kind))return kinds.some(k=>['mordent_upper','mordent_lower'].includes(k));if(['turn','inverted_turn'].includes(kind))return kinds.some(k=>['turn','inverted_turn'].includes(k));return kinds.includes(kind);}
 function editPerformance(values,enablePractice=false,removeKeys=[]){if(!commitPendingEdits())return false;const n=current(),p=currentProject();if(!n||!p||n.excluded)return false;rememberAutoNext(n);if(values.reviewed===true){pendingPerformanceEdit=null;if(autoSkippingRows())pendingAutoNext={project:p,id:String(n.id),wrapOnce:true};}else pendingPerformanceEdit={project:p,id:String(n.id)};if(enablePractice)p.performance_policy={...(p.performance_policy||{}),mode:'practice'};const group=performanceInfo(n,selectedTechniqueKey)?.group_id,ids=new Set((p.performance?.features||[]).filter(f=>f.group_id===group).flatMap(f=>f.source_note_ids||[]).map(String)),members=group?(p.notes||[]).filter(x=>performanceItems(x).some(v=>v.group_id===group)||ids.has(String(x.id))):[n];for(const item of members.length?members:[n]){const ownFamily=ownsKindFamily(item,performanceInfo(n,selectedTechniqueKey)?.kind),incoming={...values};if('kind'in incoming&&!ownsKindFamily(item,incoming.kind))delete incoming.kind;if(/^grace_/.test(performanceInfo(n,selectedTechniqueKey)?.kind||'')&&!ownFamily)delete incoming.mode;item.human_reviewed=false;item.performance_override={...(item.performance_override||{}),...incoming};for(const key of removeKeys)if(key!=='kind'||ownFamily)delete item.performance_override[key];item.validation_pending=true;item.automatic_reasons=[];}host.changed();renderInspector();refreshValidation();return true;}
 const keysForInterpret=info=>info.editable_fields||Object.keys(info.parameters||{});
 function originalPerformanceKind(n,info){return (n?.performance_marks||[]).find(m=>m.group_id===info?.group_id)?.kind||info?.kind;}
 function interpretationChoices(kind,candidates){const explicit=Array.isArray(candidates)?[...new Set(candidates)].filter(k=>['mordent_upper','mordent_lower','turn','inverted_turn','trill','trill_with_lower_mordent','tremolo_single'].includes(k)):[];if(explicit.length>1)return explicit.map(k=>[k,PERFORMANCE_LABELS[k]]);if(/^grace_/.test(kind||''))return [['grace_short','快速带过'],['grace_long','占主音一部分'],['grace_after','主音后收尾'],['grace_cluster','整组带过']];if(['mordent_upper','mordent_lower'].includes(kind))return [['mordent_upper','往上绕一下'],['mordent_lower','往下绕一下']];if(['turn','inverted_turn'].includes(kind))return [['turn','从上往下绕'],['inverted_turn','从下往上绕']];return [];}
 function resetPerformance(){const n=current(),info=performanceInfo(n,selectedTechniqueKey);if(!n||!info)return false;const keys=[...(info.editable_fields||[]),...(info.parameters.candidates?.includes('trill_with_lower_mordent')?['lower_aux_finger','borrow_ratio']:[]),'mode','reviewed'];return editPerformance({mode:'auto',reviewed:false},false,keys.filter(k=>!['mode','reviewed'].includes(k)));}
 function renderFarSymbolInset(n,info){
  const target=perf$('review-performance-inset');target.replaceChildren();target.hidden=true;const page=currentProject()?.pages?.find(p=>Number(p.page)===Number(n?.page)),preview=trustedPreview(n?.page);if(!page||!preview||!document.createElementNS)return;
  const far=sourceMarkBoxes(n,page).filter(b=>!b.near),box=far.find(b=>String(b.group_id||n.id)+':'+b.kind===info.key)||far[0];if(!box)return;
  const gap=Math.max(3,(n.bbox?.[3]||0)-(n.bbox?.[1]||0)),padding=gap*.65,crop={x:Math.max(0,box.x-padding),y:Math.max(0,box.y-padding)};crop.width=Math.min(page.width-crop.x,box.width+2*padding);crop.height=Math.min(page.height-crop.y,box.height+2*padding);
  const position=box.y>(n.bbox?.[1]||0)?'下方':'上方',caption='原谱'+position+(PERFORMANCE_LABELS[box.kind]||'符号'),text=document.createElement('span');text.textContent=caption;target.appendChild(text);
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),image=document.createElementNS(ns,'image');svg.setAttribute('viewBox',[crop.x,crop.y,crop.width,crop.height].join(' '));svg.setAttribute('preserveAspectRatio','xMidYMid meet');svg.setAttribute('aria-label',caption);image.setAttribute('href',preview.data);image.setAttribute('width',String(page.width));image.setAttribute('height',String(page.height));svg.appendChild(image);target.appendChild(svg);target.dataset.techniqueKey=String(box.group_id||n.id)+':'+box.kind;target.dataset.sourceBox=JSON.stringify([box.x,box.y,box.width,box.height]);target.title=caption+'；点击修改此类编排';target.setAttribute('aria-label',target.title);target.hidden=false;
 }
 function renderPerformanceEditor(n){
  if(!performancePanel)return;const visibleItems=performanceItems(n).filter(item=>!(item.kind==='source_timing'&&automaticStartHandled(n))),info=visibleItems.find(item=>item.key===selectedTechniqueKey)||visibleItems[0]||null,p=currentProject(),mode=p?.performance_policy?.mode==='practice'?'practice':'strict',written=mode!=='practice'||n?.performance_override?.mode==='written',active=!!info&&!n.excluded&&n.hand!=='left';if(info)selectedTechniqueKey=info.key;
  perf$('review-performance-mode').value=mode;performanceModeControl.hidden=!p;
  const basic=active&&['fingering','source_timing'].includes(info.kind),target=basic?$(info.kind==='fingering'?'review-finger-section':'review-time-section'):$('review-duration-section');if(active&&performancePanel.parentElement!==target)target.appendChild(performancePanel);performancePanel.hidden=!active;performancePanel.classList.toggle('review-performance-base-estimate',!!basic);$('review-duration-section').classList.toggle('performance-auto',active&&!written&&!basic);
  if(!active)return;const pending=!!n.validation_pending||!!p.validation_pending,params=info.parameters,override=n.performance_override||{};
  const items=visibleItems,detectedKind=originalPerformanceKind(n,info),types=perf$('review-performance-kind');types.replaceChildren();for(const item of items){const option=document.createElement('option');option.value=item.key;option.textContent=PERFORMANCE_LABELS[originalPerformanceKind(n,item)]||item.label;types.appendChild(option);}types.value=info.key;types.hidden=items.length<2;const kindParent=basic?perf$('review-performance-actions'):perf$('review-performance-heading');if(types.parentElement!==kindParent){if(kindParent.insertBefore)kindParent.insertBefore(types,kindParent.firstChild);else kindParent.appendChild(types);}perf$('review-performance-label').hidden=items.length>1;perf$('review-performance-label').textContent='原谱：'+(PERFORMANCE_LABELS[detectedKind]||info.label);perf$('review-performance-label').title=perf$('review-performance-label').textContent;perf$('review-performance-status').textContent=written?'原谱':info.estimated?'练习估计':'按谱编排';
  const interpret=perf$('review-performance-interpretation'),choices=interpretationChoices(detectedKind,params.candidates);interpret.replaceChildren();const auto=document.createElement('option');auto.value='';auto.textContent='自动：'+(PERFORMANCE_LABELS[params.kind]||info.label);interpret.appendChild(auto);for(const [value,text]of choices){const option=document.createElement('option');option.value=value;option.textContent=text;interpret.appendChild(option);}interpret.value=override.kind||'';interpret.hidden=written||!keysForInterpret(info).includes('kind')||choices.length<2;interpret.disabled=pending;interpret.setAttribute('aria-label','练习弹法，不改原谱检测类型');interpret.title='练习按另一种方式编排，原谱检测类型保留';perf$('review-performance-status').hidden=!interpret.hidden;
  perf$('review-performance-message').textContent=pending?'正在生成练习编排…':written?'只按书面音符；装饰音效果请用练习版。':info.message||(info.estimated?'演奏值是练习估计，原谱数字保留。':'已按这个符号生成演奏。');
  perf$('review-performance-message').title=info.message;renderFarSymbolInset(n,info);
  performancePanel.classList.toggle('review-performance-estimated',!written&&info.estimated&&info.warning_root&&!info.reviewed);
  const keys=info.editable_fields||Object.keys(params),settings=[['placement','placement'],['borrow','borrow_ratio'],['rate','rate_hz'],['aux','aux_finger'],['lower-aux','lower_aux_finger'],['hold','hold_factor'],['gate','gate_ratio'],['velocity','velocity']];
  for(const [id,key] of settings){const field=perf$('review-performance-'+id+'-field'),control=perf$('review-performance-'+id);field.hidden=written||!keys.includes(key);control.disabled=pending||written;const value=key in override?override[key]:params[key];if(value!=null){const values=Array.from(control.options||[]).map(o=>String(o.value));if(values.length&&!values.includes(String(value))){let option=control.querySelector?.('[data-actual]');if(!option){option=document.createElement('option');option.dataset.actual='1';control.appendChild(option);}option.value=String(value);option.textContent='当前';}control.value=String(value);}else control.value='';}
  const aux=perf$('review-performance-aux');if(aux.options?.[0])aux.options[0].textContent=params.kind==='trill_with_lower_mordent'?'自动':'自动'+(Number.isInteger(params.aux_finger)?'（'+params.aux_finger+' 指）':'练习指法');
  const a=perf$('review-performance-auto'),b=perf$('review-performance-written'),reset=perf$('review-performance-reset');a.disabled=pending;b.disabled=pending||unmeasuredGrace(n);b.title=unmeasuredGrace(n)?'这个装饰音没有固定书面时长，请用练习编排或下方不要这个音':'只按已有书面音符，不展开装饰音';reset.disabled=pending||mode!=='practice';reset.title='恢复这个符号的自动练习参数；原谱音高、指法和书面时值不变';a.classList.toggle('selected',!written);b.classList.toggle('selected',written);a.textContent=mode==='practice'?'采用练习编排':'本谱练习版';
 }
 buildPerformanceControls();

 const durationChoiceFor=n=>pendingDurationChoice&&pendingDurationChoice.project===currentProject()&&String(pendingDurationChoice.id)===String(n?.id)?pendingDurationChoice:null;
 const automatic=()=>currentProject()?.automatic_mode===true;
 function renderGlobalWarning(){const project=currentProject(),messages=project?.automatic?.messages||[],error=project?.validation_error||'',pending=!!project?.validation_pending,text=pending?'正在检查修改…':error||[...new Set(messages.map(m=>typeof m==='string'?m:m?.message||'').filter(Boolean))].join('；');$('review-global-warning').textContent=text;$('review-global-warning').title=text;$('review-global-warning').dataset.state=pending?'pending':'error';$('review-global-warning').hidden=!text;if(project?.automatic?.unsupported&&project.source_has_printed_fingering===false)$('review-count').textContent='当前 PDF 不支持';}
 const inScope=n=>n.in_export_scope!==false;
 const needsCheck=n=>inScope(n)&&noteConcern(n,automatic());
 const needsAttention=n=>needsCheck(n)||(inScope(n)&&(timingNeedsAction(n)||askPerformance(n)));
 const matchesFilter=n=>filter==='pending'?needsAttention(n):filter==='unfingered'?n.hand!=='left'&&!n.excluded&&unfingered(n):filter==='excluded'?n.hand!=='left'&&!!n.excluded:filter==='right'?n.hand!=='left':true;
 const visibleNote=n=>matchesFilter(n)||String(n.id)===retainedNoteId;
 const list=()=>{const notes=currentProject()?.notes||[];return notes.filter(matchesFilter);};
 const orderedNotes=()=>[...(currentProject()?.notes||[])].sort((a,b)=>Number(a.page||0)-Number(b.page||0)||Number(a.system||0)-Number(b.system||0)||Number(a.origin?.[0]??a.bbox?.[0]??0)-Number(b.origin?.[0]??b.bbox?.[0]??0)||Number(a.origin?.[1]??a.bbox?.[1]??0)-Number(b.origin?.[1]??b.bbox?.[1]??0));
 function issueTarget(delta){const notes=orderedNotes(),index=notes.findIndex(n=>String(n.id)===selectedId);return delta<0?notes.slice(0,index<0?notes.length:index).filter(needsAttention).at(-1):notes.slice(index+1).find(needsAttention);}
 function autoIssueTarget(wrapOnce=false){const notes=orderedNotes(),index=notes.findIndex(n=>String(n.id)===selectedId),after=notes.slice(index+1);return after.find(needsAttention)||(wrapOnce?notes.find(needsAttention):null);}
 function nextProblem(){return issueTarget(1)||orderedNotes().find(n=>String(n.id)!==selectedId&&needsAttention(n));}
 function refreshIssueNavigation(){for(const [id,delta] of [['review-issue-prev',-1],['review-issue-next',1]]){const button=$(id),target=issueTarget(delta);button.disabled=!target;button.title=target?'第 '+target.page+' 页 · 第 '+target.system+' 行：'+noteWarning(target):'没有更多待查音符';}const button=$('review-next-problem'),next=issueTarget(1),target=nextProblem();button.disabled=!target;button.textContent=next?'下一处':target?'回到前面待查':current()&&needsAttention(current())?'仅此处待查':'已检查完';button.title=target?'保留本处，查看第 '+target.page+' 页第 '+target.system+' 行':current()&&needsAttention(current())?'当前问题仍需核对，不会自动确认':'当前范围没有待查项；仍可对照原谱抽查';}
 function refreshSkipExport(){
  const p=currentProject(),button=$('review-export-skip-pending'),count=Number(p?.automatic?.attention_notes)||0;
  const available=(p?.notes||[]).some(n=>n.hand==='right'&&!n.excluded&&inScope(n)&&n.automatic_ready===true&&validFinger(n));
  button.hidden=!automatic()||count<=0;
  button.disabled=button.hidden||!!p?.validation_pending||!!p?.validation_error||!available;
  button.textContent=count>0?'跳过待处理音导出（预计 '+count+'）':'跳过待处理音导出';
  button.title=count>0?'生成部分动作谱：预计跳过 '+count+' 个待处理音，导出时重新检查并显示实际数量；灰色未设指法音仍不产生独立动作。':'没有待处理音';
 }
 function focusIssue(id){const n=id==null?orderedNotes().find(needsAttention):(currentProject()?.notes||[]).find(n=>String(n.id)===String(id));return n?select(n.id,true):false;}
 function navigateIssue(delta){if(!commitPendingEdits())return false;const target=issueTarget(delta);return target?focusIssue(target.id):false;}
 function skipPreference(project){
  if(typeof project?.selection?.auto_skip_processed==='boolean')return project.selection.auto_skip_processed;
  try{const saved=globalThis.localStorage?.getItem('piano-review-auto-next');if(saved==='0'||saved==='1')return saved==='1';}catch{}return project?.automatic_mode===true;
 }
 const autoSkippingRows=()=>$('review-auto-next').checked&&(filter==='right'||filter==='pending');
 function rememberAutoNext(note){
  if(!autoSkippingRows()||!note)return;
  if(needsAttention(note)||(pendingAutoNext?.project===currentProject()&&pendingAutoNext.id===String(note.id)))
   pendingAutoNext={project:currentProject(),id:String(note.id),wrapOnce:true};
 }
 function editingConvertInput(active){
  if(!active||!['INPUT','SELECT','TEXTAREA'].includes(active.tagName))return false;
  if(active.tagName==='INPUT'&&!['text','number','search','email','url','tel'].includes(String(active.type||'text').toLowerCase()))return false;
  return !!($('convert')?.contains?.(active)||$('review-inspector')?.contains?.(active));
 }
 // fast：改指法不牵动节奏，不用等整首重新检查（约 2 秒）就跳下一处（11-04 用户：校对完切下一个会卡）
 function runPendingAutoAdvance(fast=false){
  const job=pendingAutoNext,p=currentProject(),n=current(),active=document.activeElement;
  if(!job||!autoSkippingRows()||p!==job.project||String(n?.id)!==job.id||rendering)return;
  if(automatic()&&!fast&&(p.validation_pending||p.validation_error||n.validation_pending))return;
  if(automatic()&&fast&&p.validation_error)return;
  if(durationChoiceFor(n)||pendingPerformanceEdit?.project===p&&pendingPerformanceEdit.id===String(n?.id))return;
  if(needsAttention(n))return;
  if(editingConvertInput(active))return;
  if(!commitPendingEdits())return;
  const target=autoIssueTarget(!!job.wrapOnce);pendingAutoNext=null;
  if(target){focusIssue(target.id);if(!job.silent)host.notice('✓ 好了'+(lastSimilar?'（一样的 '+lastSimilar+' 处也改了）':'')+' · 还剩 '+leftGroups());lastSimilar=0;}
  else if(!job.silent){if(orderedNotes().some(needsAttention)){host.notice('✓ 好了'+(lastSimilar?'（一样的 '+lastSimilar+' 处也改了）':'')+' · 还剩 '+leftGroups());lastSimilar=0;}else{closeEditor();render();host.notice('✓ 好了 · 都看完了');lastSimilar=0;}}
 }
 function hasExportRange(){const q=currentProject()?.selection||{};return Number(q.start_beat)>0||q.end_beat!==null&&q.end_beat!==undefined||Number(q.start_page)>1||q.end_page!==null&&q.end_page!==undefined;}
 function commitPendingEdits(){const active=document.activeElement;if(localInputInvalid&&active?.id!=='review-local-beat'){host.notice('开始位置还未应用，请改正本小节拍位，或关闭编辑框取消该输入。');return false;}if(!active||!$('review-inspector').contains?.(active)||!['INPUT','SELECT','TEXTAREA'].includes(active.tagName)||String(active.id||'').startsWith('review-performance-'))return true;const result=active.onchange?.({target:active});if(result===false)return false;active.blur?.();return true;}

 const current=()=>currentProject()?.notes.find(n=>String(n.id)===selectedId)||null;
 // 撤销：每次改音前存一份该音的快照，Ctrl+Z 或「撤销」按钮恢复最近一次，并重新校验。
 const undoStack=[];
 function rememberUndo(n){undoStack.push({project:currentProject(),id:String(n.id),note:JSON.parse(JSON.stringify(n))});if(undoStack.length>100)undoStack.shift();refreshUndo();}
 function rememberAddition(id){undoStack.push({project:currentProject(),id:String(id),added:true,previousId:selectedId,previousRow:activeRowKey,previousPage:host.page(),previousOpen:editorOpen});if(undoStack.length>100)undoStack.shift();refreshUndo();}
 function refreshUndo(){const button=$('review-undo');if(button)button.disabled=!undoStack.some(u=>u.project===currentProject());}
 function undo(){const p=currentProject();while(undoStack.length&&undoStack.at(-1).project!==p)undoStack.pop();const last=undoStack.pop();refreshUndo();if(!last)return false;const index=p.notes.findIndex(x=>String(x.id)===last.id);if(index<0)return false;if(last.added){p.notes.splice(index,1);const previous=p.notes.find(n=>String(n.id)===last.previousId);selectedId=previous?String(previous.id):null;retainedNoteId=selectedId;activeRowKey=last.previousRow;editorOpen=!!previous&&last.previousOpen;if(Number.isInteger(last.previousPage))host.setPage(last.previousPage);host.changed();render();host.notice('✓ 已撤销补录');return true;}const n=p.notes[index];for(const key of Object.keys(n))if(!(key in last.note))delete n[key];Object.assign(n,last.note,{validation_pending:true});select(last.id);host.changed();renderInspector();refreshValidation();positionEditor();host.notice('✓ 已撤销');return true;}
 const navigableRows=()=>rowsFor(currentProject()).filter(r=>r.notes.some(autoSkippingRows()?()=>true:matchesFilter)); /* 11-04 用户：上一行/下一行/行列表要能走遍整首；只跳要查的用「下一处」 */
 const compareRows=(a,b)=>a.page-b.page||a.system-b.system;
 const activeRow=()=>rowsFor(currentProject()).find(r=>r.key===activeRowKey)||rowsFor(currentProject()).find(r=>r.key===rowKey(current()?.page,current()?.system))||rowsFor(currentProject()).find(r=>r.page===host.page()+1)||null;
 const trustedPreview=page=>{const preview=host.previews().find(p=>Number(p.page)===Number(page));return preview&&typeof preview.data==='string'&&/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(preview.data)?preview:null;};
 function timingKinds(n){return [...new Set((currentProject()?.right_hand_timing?.basis?.measures||[]).flatMap(m=>m.roots||[]).filter(r=>String(r.id)===String(n?.id)).map(r=>r.kind))];}
 function onlyDurationTimingCause(n){const kinds=timingKinds(n);return durationNeedsReview(n)&&kinds.length>0&&kinds.every(k=>k==='duration'||k==='grace');}
 function timeFieldNeedsAction(n){return startNeedsReview(n)&&!onlyDurationTimingCause(n);}
 function select(id,scroll=true,anchor=null){if(!commitPendingEdits())return false;initialIssueSelection=null;const p=currentProject(),n=p?.notes.find(n=>String(n.id)===String(id));if(!n)return;if(String(n.id)!==selectedId){selectedTechniqueKey=null;pendingPerformanceEdit=null;$('review-time-section').classList.remove('manual-start-open');}if(pendingDurationChoice&&(pendingDurationChoice.project!==p||String(pendingDurationChoice.id)!==String(n.id)))pendingDurationChoice=null;if(pendingAutoNext&&String(n.id)!==pendingAutoNext.id)pendingAutoNext=null;if(anchor?.getBoundingClientRect){const r=anchor.getBoundingClientRect();editorAnchor={left:r.left,right:r.right,top:r.top,bottom:r.bottom};editorPinned=null;}else{editorAnchor=null;editorPinned=null;}if(!editorOpen||String(n.id)!==selectedId){$('review-editor-more').hidden=true;$('review-duration-picker').hidden=false;$('review-time-control').hidden=false;}$('review-hand-repair').hidden=n.hand==='right';selectedId=String(n.id);retainedNoteId=String(n.id);const key=rowKey(n.page,n.system);if(key)activeRowKey=key;else rowMode=false;editorOpen=true;host.setPage(Math.max(0,(Number(n.page)||1)-1));render();if(scroll&&!rowMode){const hit=$('review-overlay').querySelector?.('.current');hit?.scrollIntoView?.({block:'nearest',inline:'nearest',behavior:'auto'});}return true;}
 function closeEditor(){if(!commitPendingEdits()||localInputInvalid){localInputInvalid=false;renderInspector();host.notice('未应用无效的开始位置。');}pendingDurationChoice=null;pendingPerformanceEdit=null;editorOpen=false;editorAnchor=null;editorPinned=null;$('review-editor-more').hidden=true;$('review-duration-picker').hidden=true;$('review-time-control').hidden=true;$('review-workspace').classList.remove('row-editing');renderInspector();positionEditor();}
 function positionEditor(){const panel=$('review-inspector'),open=editorOpen&&!!current(),more=!$('review-editor-more').hidden,picker=!$('review-duration-picker').hidden,time=!$('review-time-control').hidden;panel.classList.add('fixed-editor');panel.classList.toggle('quick-open',open);panel.classList.toggle('editor-idle',!open);$('review-workspace').classList.toggle('editor-idle',!open);panel.classList.toggle('more-open',more);$('review-workspace').classList.toggle('advanced-note',more);panel.classList.toggle('value-open',picker);$('review-inspector-content').hidden=!open;$('review-editor-empty').hidden=open;$('review-editor-close').hidden=!open;$('review-more-toggle').textContent=more?'收起其他设置':'其他设置';$('review-more-toggle').setAttribute('aria-expanded',String(more));$('review-duration-toggle').setAttribute('aria-expanded',String(picker));$('review-time-toggle').setAttribute('aria-expanded',String(time));$('review-pitch-settings').hidden=!(more||pitchNeedsReview(current()));Object.assign(panel.style,{left:'',top:'',width:'',height:'',maxHeight:''});scheduleRowFit();}

 function appendSymbolHits(container,n,page,crop){if(!container||!n||String(n.id)!==selectedId)return;for(const symbol of sourceMarkBoxes(n,page)){if(symbol.x<crop.x||symbol.y<crop.y||symbol.x+symbol.width>crop.x+crop.width||symbol.y+symbol.height>crop.y+crop.height)continue;const hit=document.createElement('button');hit.type='button';hit.className='review-symbol-hit';hit.dataset.performanceNoteId=String(n.id);hit.dataset.performanceKind=symbol.kind;hit.title='编辑'+(PERFORMANCE_LABELS[symbol.kind]||'特殊符号');hit.setAttribute('aria-label',hit.title);hit.classList.toggle('current',selectedTechniqueKey===String(symbol.group_id||n.id)+':'+symbol.kind);Object.assign(hit.style,{left:(symbol.x-crop.x)/crop.width*100+'%',top:(symbol.y-crop.y)/crop.height*100+'%',width:symbol.width/crop.width*100+'%',height:symbol.height/crop.height*100+'%'});hit.onclick=()=>{if(select(n.id,false,hit)===false)return;selectedTechniqueKey=String(symbol.group_id||n.id)+':'+symbol.kind;renderInspector();renderRow();};container.appendChild(hit);}}
 function bindNoteActions(element,n){element.dataset.noteId=String(n.id);element.onclick=()=>{select(n.id,false,element);$('review-inspector').focus?.({preventScroll:true});};element.oncontextmenu=event=>{event?.preventDefault?.();event?.stopPropagation?.();setExcluded(n,!n.excluded);};}
 function noteWarning(n){
  if(!n)return '';if(n.excluded)return '已排除，右键可恢复';if(n.hand==='left')return '左手音符，不会导出';if(!inScope(n))return '当前导出范围外，仍可修改';
  const missing=reviewMissingFields(n,automatic()),reasons=!n.validation_pending&&Array.isArray(n.automatic_reasons)?n.automatic_reasons:[],timing=hasTimingWarning(n)&&onlyDurationTimingCause(n)?'⚠ 先核对黄色音长，相关开始位置会重新计算。':timingWarningLabel(n);
  const other=[...new Set(reasons)].filter(r=>!(missing.includes('指法')&&/选择指法/.test(r))&&!(missing.includes('时长')&&/选择音值|选择时长/.test(r))&&!(missing.includes('音高')&&/选择音高/.test(r)));
  const grace=unmeasuredGrace(n)&&!performanceReady(n)?(unfingered(n)?'未设指法的装饰音，补号后可设置时值':'装饰音时长未定'):'';
  const practice=hasPerformanceWarning(n)?'练习估计：'+(performanceInfo(n).message||performanceInfo(n).label):'';
  return [practice,grace,missing.length?'还缺：'+missing.join('、'):'',...other,timing].filter(Boolean).join('；')||(unfingered(n)?'未标或未读到，可补号；不产生独立动作':'');
 }
 function renderFieldActions(n){
  const active=!!n&&!n.excluded&&n.hand!=='left'&&inScope(n),reasons=active&&!n.validation_pending&&Array.isArray(n.automatic_reasons)?n.automatic_reasons:[];
  const flags={finger:active&&((!performanceReady(n)&&!validFinger(n)&&!unfingered(n))||reasons.some(r=>/指法|同一手指|同指/.test(r))),duration:active&&!performanceReady(n)&&durationNeedsReview(n),time:active&&timeFieldNeedsAction(n),pitch:active&&pitchNeedsReview(n)};
  const currentEstimate=performanceInfo(n,selectedTechniqueKey);if(active&&hasPerformanceWarning(n)&&currentEstimate?.kind==='fingering')flags.finger=true;if(active&&hasPerformanceWarning(n)&&currentEstimate?.kind==='source_timing')flags.time=true;
  for(const [field,id,hint] of [['finger','review-finger-section','review-finger-action'],['duration','review-duration-section','review-duration-action'],['time','review-time-section','review-time-action'],['pitch','review-pitch-settings','review-pitch-action']]){const on=!!flags[field];$(id).classList.toggle('review-needs-action',on);$(id).dataset.needsAction=String(on);$(hint).hidden=!on;}
  const labels=[flags.finger?'手指':'',flags.duration?'音长':'',flags.time?'开始位置':'',flags.pitch?'音高':''].filter(Boolean),instruction=$('review-edit-instruction');
  const precise=String(n?.timing_warning||'').split(/[；。]/).find(t=>/本小节超过|同组音.*(?:不同|冲突)/.test(t));
  instruction.textContent=!n?'':n.validation_pending?'正在检查刚才的修改…':n.excluded?'这个音已排除；下方点“恢复这个音”可恢复。':n.hand==='left'?'这个音没有计入右手；只有原谱确属右手才找回。':precise?precise+'。':onlyDurationTimingCause(n)?'音长还没确定，先核对黄色音长；相关开始位置会重新计算。':labels.length?(labels.length===1&&flags.time?(hasTimingWarning(n)&&/估计/.test(n.timing_warning)?'位置是软件估的，听着顺就不用改。':'开始位置待核对；不确定先保留，不要猜着改。'):reasons.some(r=>/重叠/.test(r))?'这个'+(n.finger||'?')+'指和另一个音的时间撞了。先核对原谱指法；指法相同再核对音长、开始位置。':'看上方圈出的音，对照原谱修改黄色的'+labels.join('、')+'；不确定先点下一处。'):hasTimingWarning(n)?noteWarning(n):unfingered(n)?'原谱没有指法数字可以不改；有数字时可在下方补号。':'这个音没有检测到待处理项；需要时也可修改。';
  if(hasPerformanceWarning(n))instruction.textContent='黄色部分是'+performanceInfo(n).label+'的练习估计；可直接采用，或修改后自动跳下一处。';
  instruction.classList.toggle('review-needs-action',active&&needsAttention(n));
  renderPerformanceEditor(n);
  $('review-selected-note').textContent=n?'第 '+(n.page??'?')+' 页 · 第 '+(n.system??'?')+' 行 · '+(n.pitch||'音高待补'):'';
  const exclude=$('review-exclude-note');exclude.disabled=!n||!!n.validation_pending||!!currentProject()?.validation_pending;exclude.textContent=n?.excluded?'恢复这个音':'不要这个音';exclude.setAttribute('aria-pressed',String(!!n?.excluded));exclude.title=n?.excluded?'恢复选中音，与谱面右键恢复相同':'排除选中音，与谱面右键排除相同';
  if(editorOpen){$('review-duration-picker').hidden=false;$('review-time-control').hidden=false;}scheduleRowFit();
 }
 function renderNoteWarning(n){const text=noteWarning(n),warning=$('review-note-warning');warning.textContent=text;warning.title=text;warning.classList.toggle('is-problem',!!n&&needsAttention(n));renderFieldActions(n);}

 function paintNote(element,n){const excluded=!!n.excluded,unmarked=unfingered(n),missingFinger=!validFinger(n),attention=needsAttention(n);element.classList.toggle('excluded',excluded);element.classList.toggle('unfingered',!excluded&&unmarked);element.classList.toggle('uncertain',!excluded&&inScope(n)&&missingFinger&&!unmarked);element.classList.toggle('outside-scope',!inScope(n));element.classList.toggle('attention',!excluded&&attention);element.classList.toggle('confirmed',!automatic()&&!excluded&&!attention&&!!n.confirmed);element.dataset.excluded=String(excluded);element.dataset.unfingered=String(unmarked);element.classList.toggle('timing-warning',!excluded&&inScope(n)&&hasTimingWarning(n));element.hidden=!visibleNote(n);const title=(excluded?'已排除 · 再次右键恢复':unmarked?'未设指法 · 点击可补号':'左键改指法 · 右键排除')+'；指法 '+fingerLabel(n)+'；'+noteValueFor(n.duration_beats).label+(attention||!inScope(n)||unmarked?'；'+noteWarning(n):'');element.title=title;element.setAttribute('aria-label',title);if(String(element.className).split(/\s+/).includes('review-row-label')){const digit=element.querySelector?.('.review-finger-primary b'),duration=element.querySelector?.('small'),alert=element.querySelector?.('.review-note-alert');if(digit)digit.textContent=unmarked?'—':missingFinger?'?':String(n.finger);if(duration)duration.textContent=element.dataset.compact==='true'?(n.pitch||'?'):unmeasuredGrace(n)?'饰':noteValueFor(n.duration_beats).symbol;if(alert){const autoStart=automaticStartHandled(n)&&hasTimingWarning(n);alert.hidden=excluded||(!attention&&!autoStart);alert.textContent=autoStart?'≈':hasTimingWarning(n)?'⚠':'!';alert.title=noteWarning(n);}}}
 function refreshRowStatus(){const row=activeRow();if(!row)return;const eligible=row.notes.filter(n=>!n.excluded&&n.hand!=='left'&&inScope(n)),ready=eligible.filter(n=>!needsCheck(n)&&!n.validation_pending).length,attention=eligible.filter(needsCheck).length,timingWarnings=eligible.filter(hasTimingWarning).length,unmarked=eligible.filter(unfingered).length,actions=eligible.filter(validFinger).length,excluded=row.notes.filter(n=>n.excluded&&inScope(n)).length;$('review-row-status').textContent=(hasExportRange()?'本行所选范围 ':'本行 ')+attention+' 待处理'+(timingWarnings?' · 时间提醒 '+timingWarnings:'')+(unmarked?' · 未设指法 '+unmarked:'')+(excluded?' · '+excluded+' 音已忽略':'');if($('review-row-help'))$('review-row-help').textContent=unmarked?'灰色未设：含未标/未读到，可补号；导出跳过动作，保留时间':'左键改指法 · 右键排除 / 恢复';const page=currentProject()?.pages?.find(p=>p.page===row.page),candidates=rowCandidates(row,{page,problemsOnly,automaticMode:automatic()});$('review-row-confirm').hidden=automatic();$('review-row-confirm').disabled=!candidates.length;$('review-row-confirm').textContent=candidates.length?'确认本行 · '+candidates.length+' 音':'暂无可确认音符';renderRowNavigation(rowsFor(currentProject()),row);}

 function refreshValidation(){refreshCounts();renderGlobalWarning();const notes=new Map((currentProject()?.notes||[]).map(n=>[String(n.id),n]));for(const id of ['review-row-hits','review-row-annotations','review-overlay','review-timeline-track']){const parent=$(id);const elements=parent?.querySelectorAll?parent.querySelectorAll('[data-note-id]'):Array.from(parent?.children||[]).filter(e=>e.dataset?.noteId);for(const element of elements){const n=notes.get(element.dataset.noteId);if(n)paintNote(element,n);}}refreshRowStatus();refreshIssueNavigation();refreshSkipExport();renderNoteWarning(current());if(initialIssueSelection===currentProject()&&!currentProject()?.validation_pending&&!currentProject()?.validation_error&&!editingConvertInput(document.activeElement)){initialIssueSelection=null;const first=orderedNotes().find(needsAttention);if(first&&String(first.id)!==selectedId){focusIssue(first.id);return;}}runPendingAutoAdvance();}
 function setExcluded(n,value){if(!n)return;pendingPerformanceEdit=null;if(!commitPendingEdits())return false;if(!!n.excluded!==!!value)rememberUndo(n);pendingDurationChoice=null;rememberAutoNext(n);if(value&&autoSkippingRows()&&String(n.id)===selectedId)pendingAutoNext={project:currentProject(),id:String(n.id),wrapOnce:true};retainedNoteId=String(n.id);n.excluded=!!value;n.human_reviewed=false;n.excluded_manual=true;n.validation_pending=true;n.automatic_reasons=[];host.changed();renderInspector();refreshValidation();positionEditor();host.notice(n.excluded?'已排除该音；选回该音可恢复。':'已恢复该音。');return true;}
 const valueButtons=NOTE_VALUES.map(value=>{const button=document.createElement('button');button.type='button';button.className='review-note-value';button.setAttribute('aria-label',value.label);button.innerHTML='<b>'+value.symbol+'</b><span>'+({4:'4拍',2:'2拍',1:'1拍',0.5:'半拍',0.25:'¼拍',0.125:'⅛拍'}[value.beats])+'</span>';button.onclick=()=>{if(!commitPendingEdits())return false;const n=current(),mode=durationChoiceFor(n)?.mode||noteValueFor(n?.duration_beats).mode;pendingDurationChoice=null;edit('duration_beats',value.beats*(mode==='dotted'?1.5:mode==='triplet'?2/3:1));};$('review-note-values').appendChild(button);return {button,value};});
 function renderDurationChoice(n){
  const notation=noteValueFor(n?.duration_beats),choice=durationChoiceFor(n);
  for(const {button,value} of valueButtons)button.classList.toggle('selected',notation.beats===value.beats);
  for(const mode of ['plain','dotted','triplet'])$('review-value-'+mode).classList.toggle('selected',(choice?.mode||notation.mode)===mode);
  $('review-value-caption').textContent=choice?'已选'+{plain:'普通',dotted:'附点',triplet:'三连音'}[choice.mode]+'，请点音长保存':notation.label+(finite(n?.duration_beats)?' · '+holdLabel(n,Number($('bpm').value)):'');
 }
 function renderQuickEditor(n){
  const notation=noteValueFor(n.duration_beats),context=measureContext(n),onsets=quickOnsets(currentProject()?.notes||[],n),startWarning=startNeedsReview(n);
  $('review-duration-toggle').textContent=(unmeasuredGrace(n)?'装饰音':notation.symbol+' '+notation.label)+' ▾';
  $('review-finger-source').textContent=unfingered(n)?'未标/未读到 · 可补号':!validFinger(n)?'指法待补':n.finger_source==='printed'?'原谱指法':n.finger_source==='manual'?'手动指法':'';
  renderDurationChoice(n);
  const localDisplay=context.local===null?null:String(Math.round((context.local+1)*1000000)/1000000);
  $('review-time-toggle').textContent=localDisplay!==null?'开始 · 本小节第 '+localDisplay+' 拍'+(startWarning?(finite(n.beat)&&n.timing_estimated===true?'（估计）':'（待确认）'):'')+' ▾':'开始 · 位置待确定 ▾';
  $('review-start-summary').textContent='1 = 小节开头；1.5 = 两拍之间';
  const autoStart=automaticStartSummary(currentProject(),n),plan=automaticMeasurePlan(currentProject(),n),section=$('review-time-section'),manual=(n.manual_fields||[]).includes('beat');
  const automaticPanel=autoStart.available||!!plan&&timingConflict(n);
  section.classList.toggle('auto-start-available',automaticPanel);
  $('review-auto-start-summary').hidden=!automaticPanel;
  $('review-auto-start-summary').textContent=autoStart.available?autoStart.text:'开始位置有冲突，可让软件按原谱重新排这一小节。';
  $('review-auto-start-detail').hidden=!automaticPanel;
  $('review-auto-start-detail').textContent=autoStart.available?autoStart.detail:'只恢复开始位置；手指、音高和你修改的音长会保留。';
  $('review-start-manual-toggle').hidden=!automaticPanel;
  $('review-start-manual-toggle').textContent=section.classList.contains('manual-start-open')?'收起微调':'手动微调';
  $('review-start-automatic').hidden=!plan||!(manual||timingConflict(n));
  $('review-start-automatic').disabled=!!n.validation_pending||!!currentProject()?.validation_pending;

  $('review-local-beat').value=localDisplay??'';
  $('review-local-beat').disabled=context.base===null;$('review-local-confirm').disabled=context.base===null;$('review-local-help').classList.toggle('is-unavailable',context.base===null);
  $('review-local-help').textContent=context.base===null?'小节位置未知，请先处理前面的时间问题。':currentProject()?.right_hand_timing?'后续未固定的音会跟随；前音按钮仅设置一次。':'只修改这个音；前音选项仅设置一次。';
  $('review-hand-repair').hidden=n.hand==='right';
  for(const mode of ['after','simultaneous','start']){
   $('review-onset-'+mode).disabled=context.base===null||!finite(onsets[mode]);
   $('review-onset-'+mode).title=context.base===null?'本小节位置尚未确定':finite(onsets[mode])?(mode==='after'?'按当前前音结束位置设置一次，不保留中间休止，也不会永久绑定前音。':mode==='simultaneous'?'按当前前音位置设置一次，不会永久绑定前音。':currentProject()?.right_hand_timing?'未单独固定的后续音会跟随':'只修改当前音符'):mode==='start'?'本小节的位置尚未确定':'没有位置明确的同声部前音';
  }
 }

 function setOnset(value,explicit=false){if(!finite(value)||value<0)return false;const n=current();if(!n)return false;const context=measureContext(n);if(context.base===null){host.notice('小节位置未知，请先处理前面的时间问题。');return false;}if(value<context.base||(context.length!==null&&value>=context.base+context.length-1e-5)){localInputInvalid=true;host.notice('该位置超出当前小节，请核对小节内位置。');return false;}localInputInvalid=false;const same=finite(n.beat)&&Math.abs(n.beat-value)<0.5001e-6,pendingLocal=n.validation_pending&&n.timing_anchor_scope==='measure'&&Array.isArray(n.manual_fields)&&n.manual_fields.includes('beat');if(!same||(explicit&&!pendingLocal)){const local=same&&finite(context.local)?context.local:Math.round((value-context.base)*1000000)/1000000;edit('beat',same?n.beat:value,{scope:'measure',local});}return true;}

 function renderRowNavigation(rows,row){
  const available=navigableRows(),before=row&&available.some(r=>compareRows(r,row)<0),after=row&&available.some(r=>compareRows(r,row)>0),index=available.findIndex(r=>r.key===row?.key),kind=filter==='pending'?'待查行':filter==='unfingered'?'未设行':filter==='excluded'?'忽略行':'行';
  $('review-row-prev').disabled=!before;$('review-row-next').disabled=!after;
  const idleNext=$('proof-idle-next');if(idleNext){idleNext.disabled=!after;idleNext.title=after?'查看下一行':'已经是最后一行';idleNext.textContent=after?'下一行 →':'已到最后一行';}
  const pendingHere=!!row?.notes.some(needsAttention),idle=$('proof-idle'),idleLabel=idle?.querySelector('span');if(idleLabel)idleLabel.textContent=pendingHere?'软件提示本行有待查':'软件暂无提示，请对照原谱校对';idle?.classList.toggle('has-pending',pendingHere);
  $('review-row-position').textContent=available.length?(index<0?'当前行 / ':index+1+' / ')+available.length+' '+kind:'';
  $('review-row-boundary').textContent=!row?'暂无可定位的谱行':!available.length?(autoSkippingRows()||filter==='pending'?'没有待查音符':filter==='excluded'?'没有已忽略音符':'暂无谱行'):index<0?'本行已处理':!after?'已到最后一行':!before?'这是第一行':'';
  $('review-row-prev').title=before?'查看前一行':'前面没有'+kind;$('review-row-next').title=after?'查看后一行':'后面没有'+kind;
  const picker=$('review-row-select');picker.replaceChildren();const choices=available.some(r=>r.key===row?.key)?available:row?[...available,row].sort(compareRows):available;
  for(const r of choices){const option=document.createElement('option');option.value=r.key;option.textContent='第 '+r.page+' 页 · 第 '+r.system+' 行';picker.appendChild(option);}picker.value=row?.key||'';picker.disabled=!choices.length;
 }

 // 放大镜：把当前音附近的原谱放大显示在音符对面一侧，不接收点击，所以不挡谱面操作。
 var lensSize=40; /* 11-05 放大镜框多大（原谱单位），滚轮调，换音也保留 */
 function appendRowLens(n,page,crop,preview){if(!document.body?.classList?.contains('comic-theme'))return;const box=n&&String(n.id)===selectedId?boxFor(n,page):null;if(!box||box.x<crop.x||box.x>crop.x+crop.width){const dock=$('comic-guide-lens');if(dock){dock.replaceChildren();if(n&&String(n.id).startsWith('manual-')){const label=document.createElement('div');label.className='manual-note-placeholder';label.textContent='手动补录\n未定位到原谱';dock.appendChild(label);}}return;}const size=Math.min(page.width,page.height,Math.max(14,lensSize)),width=size,height=size,view={x:Math.min(page.width-width,Math.max(0,box.x+box.width/2-width/2)),y:Math.min(page.height-height,Math.max(0,box.y+box.height/2-height*.62)),width,height}/* 11-05 用户：放大镜要真放大——默认只框音符附近一小块，滚轮调大小，按住拖 */,center=(box.x+box.width/2-crop.x)/crop.width,lens=document.createElement('div');lens.className='review-row-lens '+(center<.5?'on-right':'on-left');lens.setAttribute('aria-hidden','true');const dock=$('comic-guide-lens');lens.innerHTML=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${view.x} ${view.y} ${view.width} ${view.height}"><image href="${esc(host.previewHref?host.previewHref(preview):preview.data)}" width="${page.width}" height="${page.height}"/><g class="lens-arrow"><polygon points="${box.x-.9},${box.y+box.height/2} ${box.x-5.6},${box.y+box.height/2-2.7} ${box.x-5.6},${box.y+box.height/2+2.7}" fill="#FF1493" stroke="#fff" stroke-width=".5" stroke-linejoin="round"/><animateTransform attributeName="transform" type="translate" values="-3 0;.4 0;-3 0" dur=".8s" repeatCount="indefinite"/></g></svg>`;if(dock)dock.replaceChildren(lens);else $('review-row-hits').appendChild(lens);sharpenLens(lens,n,view);dragLens(lens,n,page,view);}
 /* 11-05 用户：按住鼠标拖动放大镜看别处；松手后再要一张高清 */
 function dragLens(lens,n,page,view){const svg=lens.querySelector('svg');if(!svg)return;lens.title='按住拖动看旁边 · 滚轮放大缩小';svg.addEventListener('wheel',e=>{e.preventDefault();const r=svg.getBoundingClientRect(),fx=(e.clientX-r.left)/Math.max(1,r.width),fy=(e.clientY-r.top)/Math.max(1,r.height),k=e.deltaY>0?1.2:1/1.2,size=Math.min(page.width,page.height,Math.max(14,Math.min(160,view.width*k)));const cx=view.x+view.width*fx,cy=view.y+view.height*fy;view.width=view.height=lensSize=size;view.x=Math.min(page.width-size,Math.max(0,cx-size*fx));view.y=Math.min(page.height-size,Math.max(0,cy-size*fy));svg.setAttribute('viewBox',view.x+' '+view.y+' '+size+' '+size);clearTimeout(dragLens.t);dragLens.t=setTimeout(()=>sharpenLens(lens,n,view),250);},{passive:false});lens.style.cursor='grab';lens.style.pointerEvents='auto';lens.title='按住拖动，看旁边';let start=null;svg.addEventListener('pointerdown',e=>{e.preventDefault();start={x:e.clientX,y:e.clientY,vx:view.x,vy:view.y};svg.setPointerCapture?.(e.pointerId);lens.style.cursor='grabbing';});svg.addEventListener('pointermove',e=>{if(!start)return;const r=svg.getBoundingClientRect(),k=view.width/Math.max(1,r.width);view.x=Math.min(page.width-view.width,Math.max(0,start.vx-(e.clientX-start.x)*k));view.y=Math.min(page.height-view.height,Math.max(0,start.vy-(e.clientY-start.y)*k));svg.setAttribute('viewBox',view.x+' '+view.y+' '+view.width+' '+view.height);});const end=()=>{if(!start)return;start=null;lens.style.cursor='grab';sharpenLens(lens,n,view);};svg.addEventListener('pointerup',end);svg.addEventListener('pointercancel',end);}
 // 预览图分辨率有限：放大镜再向后端要一小块高清原谱，拿不到就继续用预览图。
 const lensCache=new Map();
 // 11-05 用户：整行也要高清 —— 先用预览图马上显示，再向后端要这一行的高清原谱换上
 const rowSharpCache=new Map();
 function sharpenRow(row,crop){const api=globalThis.pywebview?.api,digest=currentProject()?.source_sha256;if(!api?.source_row||!digest||!row||!crop)return;const key=[digest,row.page,crop.x.toFixed(1),crop.y.toFixed(1),crop.width.toFixed(1),crop.height.toFixed(1)].join(':'),apply=sharp=>{const image=$('review-row-image')?.querySelector('image');if(!image||$('review-row-image').dataset.sharpKey!==key)return;image.setAttribute('href',sharp.data);for(const field of ['x','y','width','height'])image.setAttribute(field,sharp[field]);};$('review-row-image').dataset.sharpKey=key;if(rowSharpCache.has(key)){apply(rowSharpCache.get(key));return;}Promise.resolve(api.source_row(digest,row.page,crop.x,crop.y,crop.width,crop.height)).then(sharp=>{if(rowSharpCache.size>=40)rowSharpCache.delete(rowSharpCache.keys().next().value);rowSharpCache.set(key,sharp);apply(sharp);}).catch(()=>{});}
 function sharpenLens(lens,n,view){const api=globalThis.pywebview?.api,digest=currentProject()?.source_sha256;if(!api?.source_crop||!digest)return;const key=[digest,n.page,view.x,view.y].join(':'),apply=crop=>{const image=lens.querySelector('image');if(!image||!lens.isConnected)return;image.setAttribute('href',crop.data);for(const field of ['x','y','width','height'])image.setAttribute(field,crop[field]);};if(lensCache.has(key)){apply(lensCache.get(key));return;}Promise.resolve(api.source_crop(digest,n.page,view.x,view.y,view.width,view.height)).then(crop=>{if(lensCache.size>=60)lensCache.delete(lensCache.keys().next().value);lensCache.set(key,crop);apply(crop);}).catch(()=>{});}
 function renderRow(){const p=currentProject(),rows=rowsFor(p),row=activeRow();if(row)activeRowKey=row.key;const metadata=p?.pages?.find(x=>Number(x.page)===row?.page),preview=trustedPreview(row?.page);let crop=rowCropFor(row,metadata);$('review-workspace').classList.toggle('row-review',rowMode);$('review-workspace').classList.toggle('row-editing',rowMode&&editorOpen);$('review-row-mode').textContent=rowMode?'完整 PDF':'整行对照';$('review-row-panel').hidden=!rowMode;$('review-page-tools').hidden=rowMode;$('original').hidden=rowMode;$('review-paper-caption').hidden=rowMode;$('review-editor-close').hidden=!editorOpen;renderRowNavigation(rows,row);$('review-row-label').textContent=row?'第 '+row.page+' 页 · 第 '+row.system+' 行':'整行对照';$('review-row-image').innerHTML='';$('review-row-hits').replaceChildren();$('review-row-annotations').replaceChildren();$('review-row-annotations').style.height='0px';$('review-row-confirm').disabled=true;if(!rowMode)return;if(!row||!crop||!preview){$('review-row-image').innerHTML='<p class="review-row-empty">'+(!preview?'选择对应 PDF，恢复原谱':'本页无可定位的右手行，可查看完整 PDF')+'</p>';$('review-row-status').textContent='原谱定位尚未就绪';return;}
  const region=$('review-score-region'),plan=rowScreenPlan(row,metadata,Math.max(220,(region.clientWidth||800)-20),Math.max(120,(region.clientHeight||300)-16));
  if(fragmentRowKey!==row.key){fragmentRowKey=row.key;fragmentIndex=0;fragmentSelectedId=null;}
  const found=plan.fragments.findIndex(f=>f.notes.some(n=>String(n.id)===selectedId));if(found>=0)fragmentIndex=found;fragmentSelectedId=selectedId;
  displayFragments=plan.fragments;fragmentCount=plan.fragments.length;fragmentIndex=Math.max(0,Math.min(fragmentIndex,fragmentCount-1));const part=plan.fragments[fragmentIndex];crop=part;const layout=part.layout;
  $('review-fragments').hidden=fragmentCount<2;$('review-fragment-prev').disabled=fragmentIndex===0;$('review-fragment-next').disabled=fragmentIndex===fragmentCount-1;$('review-fragment-label').textContent='第 '+(fragmentIndex+1)+' / '+fragmentCount+' 段';
  const canvas=$('review-row-canvas'),annotations=$('review-row-annotations');region.classList.toggle('annotations-overflow',!!plan.scrollable);canvas.style.width=part.renderWidth+'px';canvas.style.height=part.renderHeight+'px';annotations.style.width=part.renderWidth+'px';annotations.style.setProperty('--finger-height',(layout.boxHeight||27)+'px');annotations.classList.remove('compact-note-strip');canvas.dataset.staffGap=String(part.staffGap);canvas.dataset.fragment=String(fragmentIndex+1);canvas.dataset.fragments=String(fragmentCount);
  $('review-row-image').innerHTML=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${crop.x} ${crop.y} ${crop.width} ${crop.height}" role="img" aria-label="原 PDF 第 ${row.page} 页第 ${row.system} 行${fragmentCount>1?'第'+(fragmentIndex+1)+'段':'右手整行'}"><image href="${esc(host.previewHref?host.previewHref(preview):preview.data)}" width="${metadata.width}" height="${metadata.height}"/></svg>`;sharpenRow(row,crop);
  for(const item of layout.items){const n=item.note,concern=noteConcern(n,automatic()),state=n.excluded?' excluded':unfingered(n)?' unfingered':!validFinger(n)?' uncertain':n.confirmed?' confirmed':'',chosen=editorOpen&&String(n.id)===selectedId,box=boxFor(n,metadata);if(box){const hit=document.createElement('button');hit.type='button';hit.className='review-row-hit'+(chosen?' current':'');hit.setAttribute('aria-label','编辑原谱指法 '+fingerLabel(n));Object.assign(hit.style,{left:(box.x-crop.x)/crop.width*100+'%',top:(box.y-crop.y)/crop.height*100+'%',width:box.width/crop.width*100+'%',height:box.height/crop.height*100+'%'});bindNoteActions(hit,n);paintNote(hit,n);$('review-row-hits').appendChild(hit);}const stem=document.createElement('span');stem.dataset.noteId=String(n.id);stem.setAttribute('aria-hidden','true');stem.className='review-row-link'+state;const linkY=item.top,linkX=item.left+item.width/2-item.anchor;Object.assign(stem.style,{left:item.anchor/layout.width*100+'%',height:Math.hypot(linkX,linkY)+'px',transform:'rotate('+(-Math.atan2(linkX,linkY)*180/Math.PI)+'deg)',transformOrigin:'top center'});paintNote(stem,n);$('review-row-annotations').appendChild(stem);const button=document.createElement('button');button.type='button';button.className='review-row-label'+state+(chosen?' current':'');button.dataset.compact='false';Object.assign(button.style,{left:item.left/layout.width*100+'%',width:item.width/layout.width*100+'%',top:item.top+'px'});button.style.setProperty('--finger-height',item.height+'px');button.style.setProperty('--finger-font',Math.max(7,Math.min(17,item.height*.82,item.width-4))+'px');const primary=document.createElement('strong');primary.className='review-finger-primary';const digit=document.createElement('b');digit.textContent=validFinger(n)?String(n.finger):unfingered(n)?'—':'?';const name=document.createElement('span');name.textContent='';primary.appendChild(digit);primary.appendChild(name);const details=document.createElement('small');details.textContent=noteValueFor(n.duration_beats).symbol;button.appendChild(primary);button.appendChild(details);button.title='左键改指法 · 右键排除 / 恢复；'+'指法 '+fingerLabel(n)+'；'+noteValueFor(n.duration_beats).label+'；'+holdLabel(n,Number($('bpm').value))+(concern?'；需要检查':'');button.setAttribute('aria-label',button.title);button.setAttribute('aria-pressed',String(chosen));const alert=document.createElement('span');alert.className='review-note-alert';alert.textContent='!';button.appendChild(alert);bindNoteActions(button,n);paintNote(button,n);$('review-row-annotations').appendChild(button);}appendSymbolHits($('review-row-hits'),current(),metadata,crop);appendRowLens(current(),metadata,crop,preview);
  $('review-row-annotations').style.height=layout.height+'px';const relevant=row.notes.filter(n=>!n.excluded),right=relevant.filter(n=>n.hand==='right'),done=right.filter(n=>n.confirmed&&!missingFields(n).length).length,missing=relevant.filter(n=>missingFields(n).length||n.hand!=='right').length;$('review-row-status').textContent=automatic()?'本行 '+right.filter(n=>!noteConcern(n,true)).length+' 音就绪 · '+right.filter(n=>noteConcern(n,true)).length+' 音需检查':done+' / '+right.length+' 已确认'+(missing?' · '+missing+' 音待补':'')+(problemsOnly&&!layout.items.length?' · 本行无疑点':'');const candidates=rowCandidates(row,{page:metadata,problemsOnly,automaticMode:automatic()});$('review-row-confirm').disabled=!candidates.length;$('review-row-confirm').textContent=candidates.length?(automatic()?'标记本行已检查 · ':problemsOnly?'确认疑点 · ':'确认本行 · ')+candidates.length+' 音':problemsOnly?'暂无可确认疑点':done===right.length&&!missing?'本行已确认':'请逐音补充';
  refreshRowStatus();
 }
 function openRow(row){if(!row||!commitPendingEdits())return;pendingDurationChoice=null;pendingAutoNext=null;retainedNoteId=null;activeRowKey=row.key;// Only open the editor on a note that needs checking; a clean row stays closed (beginners took an auto-selected note for a problem).
 const issue=row.notes.find(needsAttention)||null,first=issue||row.notes.find(matchesFilter)||row.notes[0]||null;selectedId=first?String(first.id):null;editorOpen=!!issue;fragmentRowKey=null;host.setPage(row.page-1);suppressAutoSelect=true;try{render();}finally{suppressAutoSelect=false;}if(first&&!issue)host.notice('本行暂无软件提示，仍需对照原谱校对');}
 function navigateRow(delta){const row=activeRow(),rows=navigableRows();if(!row||!delta)return;openRow(delta<0?rows.filter(r=>compareRows(r,row)<0).at(-1):rows.find(r=>compareRows(r,row)>0));}
 function confirmRow(){if(automatic())return;const row=activeRow(),page=currentProject()?.pages?.find(p=>Number(p.page)===row?.page);if(!row||!trustedPreview(row.page)||!rowCropFor(row,page))return;const candidates=rowCandidates(row,{page,problemsOnly,automaticMode:automatic()});if(!candidates.length)return;for(const n of candidates)n.confirmed=true;host.changed();render();host.notice('已确认'+(problemsOnly?'疑点 ':'本行 ')+candidates.length+' 音；缺项保留待核对。');}
 function humanRowState(){const row=activeRow(),right=(row?.notes||[]).filter(n=>n.hand==='right'&&!n.excluded);const marked=right.filter(n=>n.human_reviewed===true),markable=right.filter(n=>n.human_reviewed!==true&&!n.validation_pending&&!noteConcern(n,automatic())&&!timingNeedsAction(n)&&!askPerformance(n));return {marked:marked.length,markable:markable.length,total:right.length};}
 function markHumanRow(){if(!commitPendingEdits())return false;const row=activeRow();if(!row||!trustedPreview(row.page))return false;const state=humanRowState(),right=row.notes.filter(n=>n.hand==='right'&&!n.excluded);let count=0;if(state.markable){for(const n of right)if(n.human_reviewed!==true&&!n.validation_pending&&!noteConcern(n,automatic())&&!timingNeedsAction(n)&&!askPerformance(n)){n.human_reviewed=true;count++;}host.notice('已标记本行 '+count+' 个音符；仍有提示的音请继续核对。');}else if(state.marked){for(const n of right)if(n.human_reviewed===true){n.human_reviewed=false;count++;}host.notice('已撤销本行 '+count+' 个音符的校对标记。');}else return false;if(host.progressChanged)host.progressChanged();else host.changed();return true;}
 function pageChanged(){if(rendering)return;const page=host.page()+1,rows=rowsFor(currentProject()),row=rows.find(r=>r.key===activeRowKey&&r.page===page)||rows.find(r=>r.page===page);if(row&&row.key===activeRowKey&&Number(current()?.page)===page){renderRow();return;}pendingAutoNext=null;pendingDurationChoice=null;activeRowKey=row?.key||null;const first=row?.notes.find(n=>!n.excluded&&n.hand!=='left')||(currentProject()?.notes||[]).find(n=>Number(n.page)===page&&n.hand!=='left');selectedId=first?String(first.id):null;editorOpen=false;suppressAutoSelect=true;try{render();}finally{suppressAutoSelect=false;}}

 // 11-04 用户：相同的问题算一个，标一个其余跟着改。指法：同音高、同一个和弦（同拍同页的音高一样）；音长：长得一样（小音符种类、符头、横梁、附点）。
 function similarKey(n,field){
  if(!n||n.excluded||n.hand==='left')return null;
  if(field==='finger'){if(validFinger(n))return null;const chord=(currentProject()?.notes||[]).filter(x=>x.hand==='right'&&!x.excluded&&x.page===n.page&&finite(x.beat)&&finite(n.beat)&&Math.abs(x.beat-n.beat)<1e-6).map(x=>x.pitch).sort().join(',');return 'f|'+n.pitch+'|'+chord;}
  if(field==='duration_beats'){if(!durationNeedsReview(n))return null; /* 11-04 用户：时值也一样，长得一样的音（符头、横梁、附点、符尾、有没有找到符干）改一个其余跟着改 */ // 只有小音符按长相成组；普通音改音长会牵动后面的节奏，不跟着改
  const r=n.rhythm_evidence||{};return 'd|'+(n.grace_kind||'')+'|'+(r.head||'')+'|'+(r.beams||0)+'|'+(r.dots||0)+'|'+(r.flag_bboxes?.length||0)+'|'+(Array.isArray(r.stem)?'stem':'nostem');}
  return null;
 }
 let lastSimilar=0;const leftGroups=()=>new Set(orderedNotes().filter(needsAttention).map(attentionKey)).size;
 function attentionKey(n){if(!needsAttention(n))return null;if(durationNeedsReview(n))return similarKey(n,'duration_beats')||'one|'+n.id;return similarKey(n,'finger')||'one|'+n.id;} // 和卡片先问的一样：先音长再指法
 function applyToSimilar(n,field,key){
  if(!key)return 0;let count=0;
  for(const m of currentProject()?.notes||[]){if(m===n||!needsAttention(m)||similarKey(m,field)!==key)continue;
   m[field]=n[field];m.human_reviewed=false;m.confirmed=false;m.validation_pending=true;m.automatic_reasons=[];m.manual_fields=[...new Set([...(Array.isArray(m.manual_fields)?m.manual_fields:[]),field])];if(field==='finger'){m.finger_source='manual';m.unfingered=unfingered(m);}count++;}
  return count;
 }
 function edit(field,value,anchor=null){const n=current();if(!n)return;if(field==='excluded'){setExcluded(n,!!value);return;}const similar=['finger','duration_beats'].includes(field)&&needsAttention(n)?similarKey(n,field):null;rememberUndo(n);rememberAutoNext(n);const context=measureContext(n);n[field]=value;n.human_reviewed=false;n.confirmed=false;n.validation_pending=true;n.automatic_reasons=[];const allowed=['pitch','finger','beat','duration_beats','hand'];n.manual_fields=[...new Set([...(Array.isArray(n.manual_fields)?n.manual_fields:[]).filter(f=>allowed.includes(f)),field])];if(field==='finger'){n.finger_source='manual';n.unfingered=unfingered(n);}if(field==='beat'){if(anchor?.scope==='measure'&&finite(anchor.local)&&anchor.local>=0){n.timing_anchor_scope='measure';n.measure_beat=anchor.local;}else{delete n.timing_anchor_scope;if(context.base!==null)n.measure_beat=finite(value)&&value>=context.base?value-context.base:null;}}{const k=applyToSimilar(n,field,similar);lastSimilar=k;if(k)host.notice('✓ 一样的 '+k+' 处也一起改了');}if(field==='finger'&&validFinger(n))setTimeout(()=>runPendingAutoAdvance(true),0);host.changed();renderInspector();refreshValidation();positionEditor();}
 function refreshCounts(){const project=currentProject();{const found=project?.source_name||project?.name||'',chosen=globalThis.GloveProof?.chosenName?.()||'',nice=t=>String(t).replace(/^\d{5,}_\d+_/,'').replace(/_(五线谱|带指法|黑键标注?|简谱)/g,'').replace(/\.pdf$/i,'');$('review-current-file').textContent=!found?'先选择一份曲谱':chosen&&chosen!==found?'你选的：'+chosen+'（软件认出是：'+nice(found)+'）':nice(found);$('review-current-file').title=$('review-current-file').textContent;}const notes=currentProject()?.notes||[],eligible=notes.filter(n=>!n.excluded&&n.hand!=='left'&&inScope(n)),ready=eligible.filter(n=>!needsCheck(n)&&!n.validation_pending).length,attention=eligible.filter(needsCheck).length,pending=eligible.filter(n=>n.validation_pending).length,timingWarnings=eligible.filter(hasTimingWarning).length,unmarked=eligible.filter(unfingered).length,actions=eligible.filter(validFinger).length,excluded=notes.filter(n=>n.excluded&&inScope(n)).length;const blocking=automatic()&&Number.isFinite(Number(project?.automatic?.attention_notes))?Number(project.automatic.attention_notes):attention,advisory=Math.max(0,eligible.filter(needsAttention).length-blocking);$('review-simple-status').textContent=eligible.length?(blocking?'要补 '+blocking+' 个':'软件暂无提示')+(advisory?' · 待查 '+advisory+'（可不管）':''):'';$('review-simple-status').title=eligible.length?'待处理：缺少字段或识别有疑点，会阻止完整导出（与「跳过待处理音导出」同一口径）。建议看：练习估计或时间提醒，可直接导出，按需核对。':'';$('review-count').textContent=(hasExportRange()?'所选范围 · ':'')+'可处理 '+ready+' · 需检查 '+attention;$('review-progress').max=Math.max(1,eligible.length);$('review-progress').value=ready;$('review-pending-count').textContent=[timingWarnings?'时间提醒 '+timingWarnings+' 处':'',unmarked?'未设 '+unmarked:'',pending?'检查修改中 '+pending:'',excluded?'已忽略 '+excluded:''].filter(Boolean).join(' · ');}

 function renderOverlay(){const p=currentProject(),page=host.page(),metadata=p?.pages?.find(x=>Number(x.page)===page+1),previews=host.previews();$('review-paper').style.width=$('original-zoom').value+'%';$('review-overlay').replaceChildren();if(!metadata||!previews[page])return;for(const n of p.notes){if(Number(n.page)!==page+1)continue;const box=boxFor(n,metadata);if(!box)continue;const hit=document.createElement('button');hit.type='button';hit.className='review-hit'+(n.confirmed?' confirmed':'')+(n.excluded?' excluded':'')+(editorOpen&&String(n.id)===selectedId?' current':'');hit.title=(n.hand==='left'?'左手 · ':'')+'指法 '+fingerLabel(n);hit.setAttribute('aria-label','原谱音符 '+String(n.id)+'，'+hit.title);hit.setAttribute('aria-pressed',String(String(n.id)===selectedId));Object.assign(hit.style,{left:box.x/metadata.width*100+'%',top:box.y/metadata.height*100+'%',width:box.width/metadata.width*100+'%',height:box.height/metadata.height*100+'%'});bindNoteActions(hit,n);paintNote(hit,n);$('review-overlay').appendChild(hit);}const wholePage={x:0,y:0,width:metadata.width,height:metadata.height};appendSymbolHits($('review-overlay'),current(),metadata,wholePage);if(!rowMode&&editorOpen)appendRowLens(current(),metadata,wholePage,previews[page]);}

 function renderTimeline(n){const timeline=timelineFor(currentProject()?.notes||[],n);$('review-timeline-track').replaceChildren();$('review-timeline-label').textContent=timeline?'本行右手 · 第 '+short(timeline.start)+'–'+short(timeline.end)+' 拍':'开始时间待核对';if(!timeline)return;const width=Math.max(300,(timeline.end-timeline.start)*42),inner=document.createElement('div');inner.className='review-timeline-content';inner.style.width=width+'px';for(let beat=Math.floor(timeline.start);beat<=timeline.end;beat++){const tick=document.createElement('span');tick.className='review-beat-tick';tick.style.left=(beat-timeline.start)/(timeline.end-timeline.start)*100+'%';tick.textContent=beat;inner.appendChild(tick);}const rows=[-Infinity,-Infinity,-Infinity];for(const note of timeline.notes){let row=rows.findIndex(end=>end<=note.beat);if(row<0)row=2;rows[row]=note.beat+note.duration_beats;const button=document.createElement('button');button.className='review-time-note'+(String(note.id)===selectedId?' current':'')+(note.confirmed?' confirmed':'');button.style.left=Math.max(0,note.beat-timeline.start)/(timeline.end-timeline.start)*100+'%';button.style.width=(Math.min(timeline.end,note.beat+note.duration_beats)-Math.max(timeline.start,note.beat))/(timeline.end-timeline.start)*100+'%';button.style.top=22+row*22+'px';button.textContent=fingerLabel(note);button.title='指法 '+fingerLabel(note)+' · '+holdLabel(note,Number($('bpm').value));button.setAttribute('aria-label',button.title);bindNoteActions(button,note);paintNote(button,note);inner.appendChild(button);}$('review-timeline-track').appendChild(inner);}
 function renderInspector(){const n=current();$('review-inspector-content').hidden=!n||!editorOpen;$('review-editor-empty').hidden=editorOpen&&!!n;if(!n){renderFieldActions(null);return;}for(const field of ['pitch','finger','beat','duration_beats'])$('review-'+field).value=n[field]??'';$('review-beat').placeholder=finite(n.written_beat??n.section_beat_candidate)?'候选 '+short(n.written_beat??n.section_beat_candidate):'待核对';$('review-pitch-help').textContent=pitchLabel(n.pitch);$('review-finger-help').textContent=FINGERS[n.finger-1]||(unfingered(n)?'未设指法，点击数字可补号':'按原谱数字填写');$('review-duration-help').textContent=finite(n.duration_beats)?short(n.duration_beats*60/(Number($('bpm').value)||120))+' 秒':'按原谱长短填写';$('review-hand').value=n.hand||'';$('review-excluded').checked=!!n.excluded;for(let i=1;i<=5;i++)$('review-finger-'+i).classList.toggle('selected',n.finger===i);renderTimeline(n);renderQuickEditor(n);renderNoteWarning(n);}
 function render(){if(rendering)return;rendering=true;try{const p=currentProject(),changed=p!==lastProject;if(changed){organizeTools();$("review-time-section").classList.remove("manual-start-open");selectedTechniqueKey=null;pendingPerformanceEdit=null;lastProject=p;pendingAutoNext=null;pendingDurationChoice=null;fragmentRowKey=null;initialIssueSelection=p?.validation_pending?p:null;$('review-auto-next').checked=skipPreference(p);localInputInvalid=false;selectedId=null;activeRowKey=null;editorOpen=false;editorAnchor=null;editorPinned=null;$('review-editor-more').hidden=true;$('review-duration-picker').hidden=true;$('review-time-control').hidden=true;rowMode=true;retainedNoteId=null;filter='right';problemsOnly=false;$('review-filter').value='right';}if(!current()&&!suppressAutoSelect){const notes=list();const first=(!p?.validation_pending&&notes.find(needsAttention))||notes[0];selectedId=first?String(first.id):null;editorOpen=!!first&&needsAttention(first);if(first&&Number(first.page)>0)host.setPage(Number(first.page)-1);}if(changed&&p&&$('review-auto-next').checked&&current()&&!needsAttention(current()))pendingAutoNext={project:p,id:selectedId,silent:true};refreshCounts();renderGlobalWarning();renderOverlay();renderInspector();renderRow();refreshValidation();positionEditor();}finally{rendering=false;}}
 let guideScene=0,guideTimer=null,guideRun=0,guidePlaying=false,guideAudio=null,guideVoices=[];
 function silenceGuide(){for(const voice of guideVoices){try{voice.gain.gain.setValueAtTime(0,guideAudio.currentTime);voice.osc.stop();}catch{}}guideVoices=[];}
 function stopGuideDemo(){guideRun++;guidePlaying=false;if(guideTimer!==null){clearTimeout(guideTimer);guideTimer=null;}silenceGuide();$('guide-play').textContent='播放演示';$('guide-progress').classList.toggle('running',false);}
 function showGuideFrame(index){
  const lesson=lessons[guideStep];guideScene=Math.max(0,Math.min(lesson.frames.length-1,index));const frame=lesson.frames[guideScene];
  $('guide-picture').innerHTML=frame.art;$('guide-demo-status').textContent=frame.text;
  $('guide-scenes').replaceChildren();lesson.frames.forEach((f,i)=>{const b=document.createElement('button');b.textContent=f.label;b.className=i===guideScene?'selected':'';b.setAttribute('aria-pressed',String(i===guideScene));b.onclick=()=>{stopGuideDemo();showGuideFrame(i);};$('guide-scenes').appendChild(b);});
 }
 function guideTones(frame){
  const pitches=$('guide-sound').checked!==false?frame.tones:[];
  if(frame.sustain&&pitches.length===guideVoices.length&&pitches.every((m,i)=>guideVoices[i]?.midi===m))return;
  silenceGuide();if(!guideAudio||!pitches.length)return;
  for(const midi of pitches){const osc=guideAudio.createOscillator(),gain=guideAudio.createGain();osc.type='triangle';osc.frequency.value=440*Math.pow(2,(midi-69)/12);gain.gain.setValueAtTime(0,guideAudio.currentTime);gain.gain.linearRampToValueAtTime(.065/Math.sqrt(pitches.length),guideAudio.currentTime+.02);osc.connect(gain);gain.connect(guideAudio.destination);osc.start();guideVoices.push({midi,osc,gain});}
 }
 async function playGuide(){
  if(guidePlaying){stopGuideDemo();return;}
  stopGuideDemo();const run=guideRun;guidePlaying=true;$('guide-play').textContent='停止演示';
  if($('guide-sound').checked!==false){
   const Audio=globalThis.AudioContext||globalThis.webkitAudioContext||globalThis.window?.AudioContext;
   if(Audio){try{guideAudio ||= new Audio();await guideAudio.resume?.();}catch{silenceGuide();}}
  }
  if(run!==guideRun||$('score-guide').hidden)return;
  const advance=index=>{
   if(run!==guideRun||$('score-guide').hidden)return;
   const frames=lessons[guideStep].frames;
   if(index>=frames.length){guideTimer=null;guidePlaying=false;silenceGuide();$('guide-play').textContent='再看一遍';$('guide-progress').classList.toggle('running',false);return;}
   showGuideFrame(index);const frame=frames[index];guideTones(frame);const progress=$('guide-progress');progress.classList.toggle('running',false);void progress.offsetWidth;progress.style.animationDuration=frame.ms+'ms';progress.classList.toggle('running',true);
   guideTimer=setTimeout(()=>advance(index+1),frame.ms);
  };
  advance(0);
 }
 function showGuide(step=guideStep){
  stopGuideDemo();guideStep=Math.max(0,Math.min(lessons.length-1,step));const lesson=lessons[guideStep],reference=notationReferences[lesson.reference];
  $('score-guide').hidden=false;$('guide-title').textContent=lesson.title;$('guide-body').textContent=lesson.body;$('guide-tip').textContent=lesson.tip;
  $('guide-count').textContent=(guideStep+1)+' / '+lessons.length;$('guide-prev').disabled=guideStep===0;$('guide-next').textContent=guideStep===lessons.length-1?'开始校对':'下一课';
  $('guide-play').disabled=lesson.frames.length<2;$('guide-play').textContent=lesson.frames.length<2?'这一课只有图，不用播放':'播放演示';$('guide-details').open=false;$('guide-reference-text').textContent=reference.body+' '+reference.tip;$('guide-reference').innerHTML=reference.art;
  $('guide-dots').replaceChildren();for(let i=0;i<lessons.length;i++){const b=document.createElement('button');b.className=i===guideStep?'selected':'';b.setAttribute('aria-label','第 '+(i+1)+' 课：'+lessons[i].title);b.onclick=()=>showGuide(i);$('guide-dots').appendChild(b);}
  showGuideFrame(0);
 }
 $('review-row-select').onchange=()=>openRow(rowsFor(currentProject()).find(r=>r.key===$('review-row-select').value));
 $('review-options-close').onclick=()=>{$('review-more').open=false;};
 $('review-show-all-notes').onclick=()=>{if(!commitPendingEdits())return;pendingAutoNext=null;filter='all';$('review-filter').value='all';problemsOnly=false;retainedNoteId=null;closeEditor();rowMode=false;$('review-more').open=false;render();host.notice('已显示全部音符；点误判的音，再选择“改为右手音”。');};
 $('review-row-prev').onclick=()=>navigateRow(-1);$('review-row-next').onclick=()=>navigateRow(1);if(!$('review-undo')&&typeof $('review-row-next')?.after==='function'&&typeof document.addEventListener==='function'){const button=document.createElement('button');button.type='button';button.id='review-undo';button.textContent='↶ 撤销';button.title='撤销上一次改音（Ctrl+Z）';button.disabled=true;$('review-row-next').after(button);button.onclick=()=>{if(commitPendingEdits())undo();};document.addEventListener('keydown',event=>{if(!(event.ctrlKey||event.metaKey)||event.shiftKey||event.altKey||String(event.key).toLowerCase()!=='z')return;if(['INPUT','SELECT','TEXTAREA'].includes(event.target?.tagName)||event.target?.isContentEditable)return;if(!$('review-workspace')?.getClientRects().length)return;if(commitPendingEdits()&&undo())event.preventDefault();});}$('review-row-confirm').onclick=confirmRow;$('review-issue-prev').onclick=()=>navigateIssue(-1);$('review-issue-next').onclick=()=>navigateIssue(1);$('review-row-mode').onclick=()=>{if(!commitPendingEdits())return;closeEditor();rowMode=!rowMode;if(rowMode&&filter==='all'){filter='right';$('review-filter').value='right';}if(!rowMode){$('original-zoom').value='100';if(typeof Event==='function')$('original-zoom').dispatchEvent(new Event('input',{bubbles:true}));else $('original-zoom').oninput?.();$('review-score-region').scrollTop=0;}if($('review-tools').open)$('review-tools').open=false;render();};$('review-editor-close').onclick=closeEditor;
 $('review-exclude-note').onclick=()=>{const n=current();return n?setExcluded(n,!n.excluded):false;};
 $('review-next-problem').onclick=()=>{if(!commitPendingEdits())return false;const target=nextProblem();return target?focusIssue(target.id):false;};const changeFragment=delta=>{if(!commitPendingEdits())return false;const target=fragmentIndex+delta;if(target<0||target>=displayFragments.length)return false;const part=displayFragments[target],first=part.notes.find(needsAttention)||part.notes[0];if(!first)return false;fragmentIndex=target;return select(first.id,false);};$('review-fragment-prev').onclick=()=>changeFragment(-1);$('review-fragment-next').onclick=()=>changeFragment(1);
 $('review-auto-next').onchange=()=>{const p=currentProject(),box=$('review-auto-next');if(!commitPendingEdits()){box.checked=skipPreference(p);return;}if(p){p.selection||={};p.selection.auto_skip_processed=!!box.checked;}try{globalThis.localStorage?.setItem('piano-review-auto-next',box.checked?'1':'0');}catch{}window.GloveWorkspace?.queueSave?.();pendingAutoNext=null;if(autoSkippingRows()&&current()){if(p?.validation_pending||current().validation_pending)pendingAutoNext={project:p,id:selectedId,wrapOnce:true};else if(!needsAttention(current())){pendingAutoNext={project:p,id:selectedId,wrapOnce:true};runPendingAutoAdvance();}}renderRow();};
 $('review-export-skip-pending').onclick=()=>{if(!$('review-export-skip-pending').disabled&&commitPendingEdits())return host.exportSkippingPending?.();};
 document.addEventListener?.('focusout',()=>setTimeout(runPendingAutoAdvance,0));
 $('review-filter').onchange=()=>{if(!commitPendingEdits()){$('review-filter').value=filter;return;}pendingAutoNext=null;filter=$('review-filter').value;problemsOnly=filter==='pending';retainedNoteId=null;closeEditor();if(filter==='all')rowMode=false;render();};
 for(const field of ['pitch','finger','beat','duration_beats'])$('review-'+field).onchange=()=>{const value=$('review-'+field).value;const parsed=value===''?null:field==='pitch'?value.trim():Number(value);if(current()?.[field]!==parsed)edit(field,parsed);return true;};
 $('review-hand').onchange=()=>{const value=$('review-hand').value||null;if(current()?.hand!==value)edit('hand',value);return true;};$('review-excluded').onchange=()=>{const n=current();if(n&&n.excluded!==$('review-excluded').checked){pendingDurationChoice=null;rememberAutoNext(n);n.excluded=$('review-excluded').checked;n.human_reviewed=false;n.excluded_manual=true;n.validation_pending=true;n.automatic_reasons=[];retainedNoteId=String(n.id);host.changed();refreshValidation();}return true;};
 $('review-hand-repair').onclick=()=>{if(current()?.hand==='right')return;edit('hand','right');if(filter==='all'){filter='right';$('review-filter').value='right';rowMode=true;render();}};
 for(let i=1;i<=5;i++)$('review-finger-'+i).onclick=()=>edit('finger',i);
 for(const mode of ['plain','dotted','triplet'])$('review-value-'+mode).onclick=()=>{const n=current();if(!n)return false;pendingDurationChoice={project:currentProject(),id:String(n.id),mode};renderDurationChoice(n);scheduleRowFit();return true;};
 for(const mode of ['after','simultaneous','start'])$('review-onset-'+mode).onclick=()=>setOnset(quickOnsets(currentProject()?.notes||[],current())[mode],true);
 $('review-local-beat').onchange=()=>{const context=measureContext(current()),value=Number($('review-local-beat').value);if(context.base===null||!finite(value)||value<1){localInputInvalid=true;host.notice('需要先确定本小节位置，再填写从第 1 拍开始的位置。');return false;}return setOnset(context.base+value-1);};
 $('review-local-confirm').onclick=()=>{const context=measureContext(current()),value=Number($('review-local-beat').value);if(context.base===null||!finite(value)||value<1){localInputInvalid=true;host.notice('请先填写本小节从第 1 拍开始的位置。');return false;}return setOnset(context.base+value-1,true);};
 $('review-time-toggle').onclick=()=>{$('review-time-control').hidden=false;positionEditor();};
 $('review-start-manual-toggle').onclick=()=>{$('review-time-section').classList.toggle('manual-start-open');renderQuickEditor(current());scheduleRowFit();};
 $('review-start-automatic').onclick=()=>{if(!commitPendingEdits())return false;const p=currentProject(),n=current(),result=restoreMeasureAutomaticStart(p,n);if(!result){host.notice('当前没有可恢复的原谱节奏依据，不能随意改开始位置。');return false;}pendingAutoNext=null;pendingPerformanceEdit=null;localInputInvalid=false;$('review-time-section').classList.remove('manual-start-open');host.changed();renderInspector();refreshValidation();host.notice('软件重排中…');return true;};

 $('review-duration-toggle').onclick=()=>{$('review-duration-picker').hidden=false;positionEditor();};$('review-more-toggle').onclick=()=>{$('review-editor-more').hidden=!$('review-editor-more').hidden;positionEditor();};
 $('review-advanced-back').onclick=()=>{$('review-editor-more').hidden=true;positionEditor();renderRow();};$('review-tools-back').onclick=()=>{$('review-tools').open=false;renderRow();};$('review-tools').ontoggle=()=>{if(!$('review-tools').open)renderRow();};
 $('review-note-more').ontoggle=positionEditor;
 $('review-inspector').oncontextmenu=event=>{event?.preventDefault?.();};
 $('review-row-panel').oncontextmenu=event=>{event?.preventDefault?.();};
 $('review-inspector').onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();closeEditor();return;}const typing=['INPUT','SELECT','TEXTAREA'].includes(event.target?.tagName);if(!typing&&/^[1-5]$/.test(event.key)){event.preventDefault();edit('finger',Number(event.key));}else if(!typing&&event.key==='Enter'){event.preventDefault();closeEditor();}};
 $('review-help').onclick=()=>showGuide();$('guide-close').onclick=()=>{stopGuideDemo();$('score-guide').hidden=true;$('review-help').focus?.();};$('guide-prev').onclick=()=>showGuide(guideStep-1);$('guide-next').onclick=()=>{if(guideStep===lessons.length-1){stopGuideDemo();$('score-guide').hidden=true;$('review-filter').focus?.();}else showGuide(guideStep+1);};$('guide-play').onclick=playGuide;$('guide-sound').onchange=()=>{if(!$('guide-sound').checked)silenceGuide();};if(typeof document.addEventListener==='function')document.addEventListener('visibilitychange',()=>{if(document.hidden)stopGuideDemo();});
 function scheduleRowFit(){
  if(rowLayoutQueued||!currentProject()||!rowMode||typeof $('review-score-region')?.getClientRects!=='function')return;
  rowLayoutQueued=true;
  const enqueue=typeof queueMicrotask==='function'?queueMicrotask:callback=>Promise.resolve().then(callback);
  enqueue(()=>{rowLayoutQueued=false;const region=$('review-score-region');if(currentProject()&&rowMode&&region?.getClientRects?.().length&&region.clientWidth>0&&region.clientHeight>0)renderRow();});
 }
 // Validation and translated glyphs can change the dock after the initial row
 // render. Fit once after all DOM changes in this turn, even in hidden native
 // windows that suspend animation/observer frames. Never touch the inspector,
 // its focused input or musical data while fitting the final remaining area.
 if(typeof ResizeObserver==='function'){
  const region=$('review-score-region'),observer=new ResizeObserver(()=>{const width=region.clientWidth,height=region.clientHeight;if(width===lastRowWidth&&height===lastRowHeight)return;lastRowWidth=width;lastRowHeight=height;if(currentProject()&&rowMode&&width>0&&height>0)scheduleRowFit();});
  observer.observe(region);
 }
 if(typeof window!=='undefined')window.addEventListener('resize',()=>{if(currentProject()&&rowMode){renderRow();positionEditor();scheduleRowFit();}});
 function refreshTiming(){
  const active=document.activeElement,preserve=active&&$('review-inspector').contains?.(active)&&['INPUT','SELECT','TEXTAREA'].includes(active.tagName),draft=preserve?{value:active.value,checked:active.checked,start:active.selectionStart,end:active.selectionEnd}:null;
  renderInspector();
  if(draft){active.value=draft.value;active.checked=draft.checked;if(typeof active.setSelectionRange==='function'&&Number.isInteger(draft.start))active.setSelectionRange(draft.start,draft.end);}
 }
 globalThis.GloveReviewActive={current,project:currentProject,attention:()=>orderedNotes().filter(needsAttention),humanRowState,markHumanRow,select:id=>select(id,true),openFirstRow:()=>{if(!commitPendingEdits())return false;initialIssueSelection=null;const row=rowsFor(currentProject())[0];if(row)openRow(row);return !!row;},openNextRow:()=>{const row=activeRow(),next=row&&rowsFor(currentProject()).find(r=>compareRows(r,row)>0);if(!next||!commitPendingEdits())return false;initialIssueSelection=null;openRow(next);return true;},rowAttention:()=>{const row=activeRow();return row?row.notes.filter(needsAttention).length:0;},advance:()=>{if(!commitPendingEdits())return null;const target=nextProblem();if(target&&focusIssue(target.id)!==false)return 'next';closeEditor();render();return 'done';},close:()=>{if(!commitPendingEdits())return false;closeEditor();render();return true;},attentionKey,canAcceptEstimate:()=>canAcceptEstimate(current()),setLocalBeat:local=>{const n=current(),c=measureContext(n);if(!n||c.base===null||!finite(local))return false;if(!commitPendingEdits())return false;return setOnset(c.base+local,true);},measureContext:n=>measureContext(n),acceptEstimate:()=>{const n=current();if(!canAcceptEstimate(n)||!commitPendingEdits())return false;n.start_estimate_ok=n.beat;pendingAutoNext=null;render();refreshValidation();host.changed();return true;}};
 return {render,renderOverlay,setPerformancePolicy,editPerformance,renderPerformanceEditor,refreshValidation,refreshTiming,select,setExcluded,current,showGuide,lessons,pageChanged,confirmRow,navigateRow,commitPendingEdits,focusIssue,navigateIssue,rememberAddition,rememberEdit:id=>{const note=currentProject()?.notes.find(n=>String(n.id)===String(id));if(note)rememberUndo(note);}};
}
return {create,humanProgress,combinedProgress,softwareHint,estimateAccepted,estimateOnly,canAcceptEstimate,automaticStartHandled,timingConflict,timingNeedsAction,automaticStartSummary,restoreMeasureAutomaticStart,performanceInfo,performanceItems,sourceMarkBoxes,sourceInkBox,performanceReady,hasPerformanceWarning,askPerformance,reviewMissingFields,PERFORMANCE_LABELS,validFinger,unfingered,fingerLabel,holdLabel,missingFields,validPitch,boxFor,cropFor,timelineFor,pitchLabel,lessons,notationReferences,rowsFor,rowCropFor,rowCandidates,rowAnnotationLayout,rowScreenPlan,noteConcern,hasTimingWarning,timingWarningLabel,NOTE_VALUES,noteValueFor,measureContext,precedingGroup,quickOnsets,editorPosition};
});

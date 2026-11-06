/* Local Web Audio transport, with continuous score time on capable firmware. */
(function(root,factory){'use strict';const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.GloveAudio=api;})(typeof globalThis==='object'?globalThis:this,function(){
'use strict';
const valid = value => typeof value==='number' && Number.isFinite(value);
// Sound events may differ from the PGL motor projection (pedal, articulation,
// ornaments and original gray notes). Never replace a declared rich timeline
// with motor pitches when its metadata is invalid.
function audioNotesFor(score){
  const data=score?.performance??score?.source_preview?.performance;
  if(data!=null){
    if(data.version!==1||!['practice','strict'].includes(data.mode)||!Array.isArray(data.audio_events)||data.audio_events.length>60000||!Number.isInteger(data.duration_ms)||data.duration_ms<1||data.duration_ms>86400000)throw Error('演奏编排数据不正确，请重新导出随谱包');
    return data.audio_events.map((n,index)=>{
      if(!n||!Number.isInteger(n.t_ms)||n.t_ms<0||!Number.isInteger(n.duration_ms)||n.duration_ms<1||n.t_ms+n.duration_ms>data.duration_ms||!Number.isInteger(n.pitch)||n.pitch<0||n.pitch>127||!Number.isInteger(n.velocity)||n.velocity<1||n.velocity>127||!(n.finger==null||Number.isInteger(n.finger)&&n.finger>=1&&n.finger<=5))throw Error('演奏编排音符不正确，请重新导出随谱包');
      return {...n,index,finger:n.finger??null,audio_only:n.finger==null};
    }).sort((a,b)=>a.t_ms-b.t_ms||a.index-b.index);
  }
  if(/（练习·[0-9a-f]{16}）$/.test(String(score?.title||'')))return [];
  return (score?.notes||[]).map((n,index)=>({...n,index})).filter(n=>valid(n.t_ms)&&valid(n.duration_ms)&&n.duration_ms>0&&valid(n.pitch)&&n.pitch>=0&&n.pitch<=127&&Number.isInteger(n.finger)&&n.finger>=1&&n.finger<=5).sort((a,b)=>a.t_ms-b.t_ms||a.index-b.index);
}
class DeviceClock {
  constructor(){this.state=null;this.anchor=0;this.rtt=0;}
  sync(state,began,ended){this.state={...state};this.anchor=(began+ended)/2;this.rtt=Math.max(0,ended-began);}
  position(now){const s=this.state;if(!s)return 0;let ms=Number(s.elapsed_ms)||0;if(!this.paused)ms+=Math.max(0,now-this.anchor)*this.rate;return Math.min(Math.max(0,ms),this.limit);}
  get rate(){return Math.max(.01,Number(this.state?.tempo)||100)/100;}
  get continuous(){return this.state?.score_clock==='continuous-v1';}
  get paused(){return !this.state?.active||!!this.state.initializing||(!this.continuous&&!!this.state.clock_paused);}
  get limit(){if(this.continuous){const duration=this.state?.duration_ms;return valid(duration)&&duration>0?duration:Infinity;}const value=this.state?.clock_limit_ms;return valid(value)&&value>=0?Math.max(-.001,value-.001):Infinity;}
  permitted(note){const s=this.state;return this.continuous||note.audio_only===true||!(s?.clock_paused&&Number.isInteger(s.mask)&&s.mask>=0&&s.mask<=31&&!(s.mask&(1<<(note.finger-1))));}
}
class Voice {
  constructor(context,note,when){this.context=context;this.startAt=when;this.releaseAt=null;this.closed=false;this.level=.14*Math.max(1,Math.min(127,Number(note.velocity)||96))/127;this.gain=context.createGain();this.osc=context.createOscillator();this.harm=context.createOscillator();this.overtone=context.createGain();this.osc.type='triangle';this.harm.type='sine';this.osc.frequency.value=440*Math.pow(2,(note.pitch-69)/12);this.harm.frequency.value=this.osc.frequency.value*2;this.overtone.gain.value=.14;this.osc.connect(this.gain);this.harm.connect(this.overtone);this.overtone.connect(this.gain);this.gain.connect(context.destination);this.gain.gain.setValueAtTime(0,when);this.gain.gain.linearRampToValueAtTime(this.level,when+.004);this.gain.gain.setTargetAtTime(this.level*.38,when+.035,.65);this.osc.start(when);this.harm.start(when);}
  scheduleRelease(when){if(this.closed||this.releaseAt===when)return;this.cancelRelease();this.releaseAt=when;this.gain.gain.setTargetAtTime(0,when,.012);}
  cancelRelease(){if(this.releaseAt===null||this.closed)return;const now=this.context.currentTime,from=Math.max(now,this.startAt);this.gain.gain.cancelScheduledValues(from);if(now<this.startAt+.004){this.gain.gain.setValueAtTime(0,from);this.gain.gain.linearRampToValueAtTime(this.level,Math.max(from+.001,this.startAt+.004));this.gain.gain.setTargetAtTime(this.level*.38,Math.max(from+.002,this.startAt+.035),.65);}else this.gain.gain.setTargetAtTime(this.level*.38,from,.012);this.releaseAt=null;}
  mute(){if(this.closed)return;const now=this.context.currentTime;this.gain.gain.cancelScheduledValues(now);this.gain.gain.setValueAtTime(0,now);this.osc.stop(now);this.harm.stop(now);this.closed=true;}
}
class Transport {
  constructor(context,{now=()=>performance.now(),lookaheadMs=60,maxStateAgeMs=1000,voiceFactory=(ctx,n,when)=>new Voice(ctx,n,when)}={}){this.context=context;this.now=now;this.lookaheadMs=lookaheadMs;this.maxStateAgeMs=maxStateAgeMs;this.makeVoice=voiceFactory;this.clock=new DeviceClock();this.notes=[];this.voices=new Map();this.enabled=true;this.synced=false;this.lastPosition=0;this.lastRate=1;this.offsetMs=0;}
  // Positive delays the sound, negative plays it early (speaker latency vs finger travel).
  setOffset(ms){const v=Number(ms);this.offsetMs=Number.isFinite(v)?Math.max(-500,Math.min(500,v)):0;this.pump();}
  load(score){this.stop();this.notes=audioNotesFor(score);let end=0;this.prefixEnd=this.notes.map(n=>end=Math.max(end,n.t_ms+n.duration_ms));}
  sync(state,began=this.now(),ended=began){
    // Each continuous poll bounds the device start to [began-e, ended-e] (score time e
    // at the current speed); a ~0.3 s round trip makes its midpoint unreliable. Keep the
    // intersection over the run so fast replies tighten it and slow ones cannot drag it.
    // The delay is almost all on the way in (queued behind the serial port); the reply
    // leaves ~30 ms after the device reads its clock, so estimate near the upper edge.
    const s=state,speed=Math.max(.01,Number(s?.tempo)||100)/100,e=Number(s?.elapsed_ms)||0;
    if(s?.score_clock==='continuous-v1'&&s.active&&!s.initializing&&s.slot!==undefined&&!(e>=Number(s.duration_ms))){const key=[s.slot,s.tempo,s.duration_ms].join('|');let lo=began-e/speed,hi=ended-e/speed;const w=this.window;if(w&&w.key===key&&Math.max(lo,w.lo)<=Math.min(hi,w.hi)+5){lo=Math.max(lo,w.lo);hi=Math.max(lo,Math.min(hi,w.hi));}this.window={key,lo,hi};state={...s,elapsed_ms:Math.max(0,(ended-Math.max(lo,hi-30))*speed)};began=ended;}else this.window=null;
    const previous=this.clock.state,previousPaused=this.clock.paused,oldPosition=this.clock.position(ended);this.clock.sync(state,began,ended);const position=this.clock.position(ended),rate=this.clock.rate;this.synced=true;if(previous&&(Math.abs(position-oldPosition)>100||rate!==this.lastRate||previousPaused!==this.clock.paused)){for(const entry of this.voices.values())entry.voice.cancelRelease();}if(position<this.lastPosition-1){for(const [key,entry]of this.voices)if(entry.note.t_ms>position||entry.note.t_ms+entry.note.duration_ms<=position){entry.voice.mute();this.voices.delete(key);}}this.lastRate=rate;this.pump();}
  setEnabled(value){this.enabled=!!value;if(!this.enabled)this.mute();else this.pump();}
  mute(){for(const entry of this.voices.values())entry.voice.mute();this.voices.clear();}
  stop(){this.mute();this.clock.state=null;this.synced=false;this.lastPosition=0;this.window=null;}
  pump(){if(!this.synced||!this.enabled||!this.clock.state?.active||this.clock.state.initializing){this.mute();return;}const wall=this.now();if(wall-this.clock.anchor>this.maxStateAgeMs){this.mute();return;}const paused=this.clock.paused,rate=this.clock.rate,position=this.clock.position(wall)-(paused?0:this.offsetMs*rate),audioNow=this.context.currentTime;
    // Continuous firmware plays by score time. Legacy firmware retains its
    // acknowledged event boundaries. No note makes an HTTP write.
    const horizon=paused?position:Math.min(this.clock.limit,position+this.lookaheadMs*rate),wanted=new Set();
    let left=0,right=this.notes.length;while(left<right){const mid=(left+right)>>>1;if(this.notes[mid].t_ms<=horizon)left=mid+1;else right=mid;}const endIndex=left;while(left>0&&this.prefixEnd[left-1]>position)left--;for(let i=left;i<endIndex;i++){const note=this.notes[i],end=note.t_ms+note.duration_ms;if(end<=position||!this.clock.permitted(note))continue;wanted.add(note.index);let entry=this.voices.get(note.index);const when=audioNow+Math.max(0,(note.t_ms-position)/rate)/1000;if(entry&&entry.voice.startAt>audioNow+.001&&Math.abs(entry.voice.startAt-when)>.005){entry.voice.mute();this.voices.delete(note.index);entry=null;}if(!entry){entry={note,voice:this.makeVoice(this.context,note,when)};this.voices.set(note.index,entry);}if(paused||end>horizon)entry.voice.cancelRelease();else entry.voice.scheduleRelease(audioNow+(end-position)/rate/1000);}
    for(const [key,entry]of this.voices){if(wanted.has(key))continue;const note=entry.note,end=note.t_ms+note.duration_ms;if(note.t_ms>horizon||!this.clock.permitted(note)){entry.voice.mute();this.voices.delete(key);continue;}if(end<=position){if(entry.voice.releaseAt===null)entry.voice.scheduleRelease(audioNow);if(audioNow>=entry.voice.releaseAt+.09){entry.voice.mute();this.voices.delete(key);}}}
    this.lastPosition=position;
  }
  get soundingCount(){const p=this.clock.position(this.now());let count=0;for(const entry of this.voices.values())if(entry.note.t_ms<=p&&p<entry.note.t_ms+entry.note.duration_ms&&this.clock.permitted(entry.note))count++;return count;}
}
return {DeviceClock,Voice,Transport,audioNotesFor};
});

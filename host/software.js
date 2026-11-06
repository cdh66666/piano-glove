(() => {
'use strict';
let pausedAt=null; // 播放页暂停位置（毫秒，曲谱时间）
const $ = id => document.getElementById(id), names=['拇指','食指','中指','无名指','小指'];
let active=false, mask=0, generation=0, project=null, score=null, state=null, clock=0, audio=null, voices=new Map(), available=false, originalPage=0,pollBusy=false,keepBusy=false,lastStatePoll=-Infinity,lastElapsed=0,originalSourceSha='',originalPreviews=[],manualCounter=0,motionQueue=Promise.resolve(),tempoQueue=Promise.resolve(),tempoRevision=0,stateRevision=0,audioReady=false,playbackView=null,patternActive=false,audioTransport=null,playerScore=null,playerSong=null,playerSource=null,playerSourcePage=0,playerShowSource=false,playerRenderKey='',uploadCapabilities=null,uploadInProgress=false;
// A fresh document token also separates duplicated tabs, which clone sessionStorage.
let visualReview=null,reviewTablePage=0,reviewMode=false;
let projectProgressGeneration=0;
let projectProgressCacheToken=null;
let projectProgressScope=null;
let reviewRevision=0,reviewCheckTimer=null;
let exportingReview=false,deviceWasConnected=false;
let nativeClosing=false,motionPending=0;
const controllerToken=window.crypto?.randomUUID?.()||'pc-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
const deviceClock=new GloveAudio.DeviceClock();let playerNotes=[],playerPrefixEnd=[],playerDuration=0,lastVisualFrame=-Infinity;
const sourceCache=new GlovePack.Cache();
const originalPreviewUrls=new Map();
function releaseOriginalPreviewUrls(){for(const row of originalPreviewUrls.values())URL.revokeObjectURL?.(row.url);originalPreviewUrls.clear();}
function originalPreviewHref(preview){
 if(!preview||typeof preview.data!=='string'||typeof URL.createObjectURL!=='function'||!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(preview.data))return preview?.data||'';
 const known=originalPreviewUrls.get(preview);if(known?.data===preview.data){originalPreviewUrls.delete(preview);originalPreviewUrls.set(preview,known);return known.url;}
 if(known){URL.revokeObjectURL?.(known.url);originalPreviewUrls.delete(preview);}
 const url=URL.createObjectURL(new Blob([bytes64(preview.data.slice(22))],{type:'image/png'}));originalPreviewUrls.set(preview,{data:preview.data,url});
 while(originalPreviewUrls.size>3){const first=originalPreviewUrls.keys().next().value;URL.revokeObjectURL?.(originalPreviewUrls.get(first).url);originalPreviewUrls.delete(first);}return url;
}
let lastStatePacketAt=-Infinity,feedbackObservedAt=-Infinity,cachedFeedback=null,stateConnectionLost=false,connectionBeforeLoss='',libraryReady=false,libraryRecoveryBusy=false,lastLibraryRetry=-Infinity,connectionEpoch=0,connectionInfoReady=false,libraryRevision=0;
let pollPromise=null,recoveryStateBusy=false,songDeleteRequest=null;
let wirelessConnection=false,wirelessRetryPending=false;
let scoreReadBusy=false,scoreTransferVerb='读取',waitLibraryShown=false;
function capability(value){value=!!value&&!scoreReadBusy&&!nativeClosing;available=value;document.querySelectorAll('#train button,#fingers button,#upload,#songs button').forEach(b=>b.disabled=!value);$('upload').disabled=!value||uploadInProgress;$('player-replay').disabled=!value||!!playbackView?.pending;if(playbackView?.pending)playbackView.play.disabled=true;if(songDeleteRequest)songDeleteRequest.trigger.disabled=true;const status=$('review-play-status');if(value&&status?.classList.contains('problem')){status.textContent='';status.classList.remove('problem');}}
function lostState(invalidatePending=true){if(invalidatePending)connectionEpoch++;cancelStaleSongDelete();connectionInfoReady=false;libraryReady=false;if(stateConnectionLost)return;stateConnectionLost=true;lastLibraryRetry=-Infinity;connectionBeforeLoss=$('connection').textContent.replace(/ · (已就绪|连接中断)$/,'');if(active)finishLocal('连接中断');capability(false);$('connection').textContent=deviceWasConnected?connectionBeforeLoss+' · 连接中断':'手套未连接';$('sync').textContent='连接中断';const offline={...cachedFeedback,feedback:(cachedFeedback?.feedback||[]).map(axis=>({...axis,position_valid:false,pos_valid:false}))};showFeedback(offline);for(let id=1;id<=6;id++){$('meter-status-'+id).textContent='连接中断';$('meter-status-'+id).hidden=false;}message('连接中断，请检查数据线或手套热点',true,'hardware');}
function transientTransport(error){return error?.name==='TypeError'||error?.name==='SyntaxError'||/Failed to fetch|NetworkError|fetch failed|Load failed|连接等待超时/.test(String(error?.message||''));}
function wirelessScore(){return wirelessConnection&&active&&!!score&&!patternActive;}
function wirelessGrace(){return wirelessScore()&&Number.isFinite(lastStatePacketAt)&&performance.now()-lastStatePacketAt<=4000;}
function retryNotice(){wirelessRetryPending=true;$('sync').textContent='无线连接重试中';message('无线信号短暂波动，正在重试…',false,'link');}
function deferWirelessFailure(error){if(!transientTransport(error)||!wirelessGrace())return false;retryNotice();return true;}
function expireFeedback(){
 if(scoreReadBusy){scoreReadFeedback();return;}
 const now=performance.now();
 if(Number.isFinite(lastStatePacketAt)&&now-lastStatePacketAt>1000){
  if(wirelessGrace())retryNotice();
  else{const wasActive=active;lostState(false);if(wasActive)stopBeacon();return;}
 }
 if(!stateConnectionLost&&cachedFeedback){const age=Math.max(0,now-feedbackObservedAt);showFeedback({...cachedFeedback,feedback:cachedFeedback.feedback.map(axis=>({...axis,sample_age_ms:Number(axis.sample_age_ms??axis.position_age_ms)+age}))});}
}
function rememberFeedback(s){if(stateConnectionLost&&!validRecovery(s))return;if(Array.isArray(s.feedback)){cachedFeedback=s;feedbackObservedAt=performance.now();}showFeedback(s);}
function validRecovery(s){return typeof s.active==='boolean'&&Array.isArray(s.feedback)&&s.feedback.some(axis=>(axis.position_valid===true||axis.position_valid===1||axis.pos_valid===true||axis.pos_valid===1)&&Number.isFinite(Number(axis.sample_age_ms??axis.position_age_ms))&&Number(axis.sample_age_ms??axis.position_age_ms)<=1000);}
function waitingForServos(s){deviceWasConnected=true;if(active)finishLocal('舵机未就绪');capability(false);cancelStaleSongDelete();connectionInfoReady=true;libraryReady=false;stateConnectionLost=false;lastStatePacketAt=performance.now();$('connection').textContent='手套（USB）· 等待舵机通电';$('connection').title='USB '+(s.port||'');$('activity').textContent='等待舵机就绪';$('sync').textContent='USB 通信正常';if(waitLibraryShown){waitLibraryDownloads();message('主控已连接，正在等待舵机；曲谱可以查看和下载，通电后才能训练。',false,'hardware');}else{$('capacity').textContent='舵机通电后自动读取手套曲库';message('主控已连接，正在等待舵机；请检查舵机供电和连接。',false,'hardware');}}
// Firmware r29.3+ serves score files while servos are unpowered; only downloads stay usable then.
function waitLibraryDownloads(){document.querySelectorAll('#songs .song-download').forEach(b=>b.disabled=scoreReadBusy||nativeClosing);}
function recoveredState(s){if(typeof s.active!=='boolean')return;lastStatePacketAt=performance.now();if(s.connection_state==='waiting_servos'){waitingForServos(s);return;}if(!validRecovery(s))return;if(!stateConnectionLost&&connectionInfoReady&&libraryReady){if(!available&&!scoreReadBusy){capability(true);$('connection').textContent=connectionBeforeLoss+' · 已就绪';}return;}recoverConnection();}
// Reconnection restores read-only metadata, never the page's previous motion.
// A failed state request invalidates in-flight identity/library responses. Local
// feedback expiry still disables controls, but a long library read may finish
// once a new state packet has independently proved that the device is back.
async function recoverConnection(initial=false){
 const now=performance.now();if(scoreReadBusy||libraryRecoveryBusy||(!initial&&now-lastLibraryRetry<2000))return;
 libraryRecoveryBusy=true;lastLibraryRetry=now;const epoch=connectionEpoch,current=()=>epoch===connectionEpoch;
 try{
  const info=await api('/api/software/status');if(!current())return;
  if(info.bridge!==undefined&&!info.connected)throw Error('未连接，请检查数据线');
  if(info.enrollment_active){waitingForServos(info);if(info.library_during_wait&&!waitLibraryShown&&await refresh(current)&&current()){libraryReady=false;waitLibraryShown=true;waitingForServos(info);}return;}
  waitLibraryShown=false;
  if(!await refresh(current)||!current())return;
  if(!initial){
   recoveryStateBusy=true;
   try{if(pollPromise)await pollPromise;if(!current())return;const fresh=await sampleState();if(!current())return;if(!fresh||!validRecovery(fresh))throw Error('等待有效的位置反馈');}
   finally{recoveryStateBusy=false;}
  }
  if(!current())return;
  const raw=info.device_info||'',model=info.model||raw.match(/(?:model|profile|servo_model)=([^ ]+)/)?.[1]||(/STS3032/.test(raw)?'STS3032-C001':/SC09/.test(raw)?'SC09':'型号待识别');
  deviceWasConnected=true;wirelessConnection=info.bridge===undefined;uploadCapabilities=info;connectionInfoReady=true;libraryReady=true;stateConnectionLost=false;
  connectionBeforeLoss=info.bridge!==undefined?'手套（USB）':'手套（热点）';$('connection').title=(info.bridge!==undefined?'USB '+info.port:'手套热点')+' · '+model;
  $('connection').textContent=connectionBeforeLoss+' · 已就绪';
  const mobile=info.bridge===undefined;$('convert-tab').hidden=mobile;document.querySelector('nav a').hidden=mobile;
  applyState({...info,...state,model});capability(true);
  if(!active&&/^(正在读取曲库|曲库尚未就绪|连接中断|正在恢复连接|等待舵机就绪)$/.test($('activity').textContent))$('activity').textContent='待机';
  if($('message').dataset.messageScope==='hardware')message('');
 }catch(error){
  if(!current())return;connectionInfoReady=false;libraryReady=false;capability(false);
  if(!stateConnectionLost){$('connection').textContent=reviewMode&&!deviceWasConnected?'手套未连接 · 可离线转换':'等待设备连接';fetch('/api/status').then(r=>r.json()).then(st=>{if(/PermissionError|拒绝访问|被别的程序占|驱动栈卡住/.test(String(st.error||''))&&!st.connected)$('connection').textContent='USB 口被卡住 · 拔插一下 USB 线';}).catch(()=>{}); /* 11-05：强关软件后驱动不放口，直接告诉用户怎么办 */$('capacity').textContent='曲库尚未就绪';if(!active)$('activity').textContent='曲库尚未就绪';}
  message(/UNKNOWN_COMMAND|未知接口|404/.test(error.message)?'设备固件需更新，软件功能暂不可用':error.message,true,'hardware');
 }finally{libraryRecoveryBusy=false;}
}
function friendly(s){const text=String(s||'');const stage=text.match(/(?:^|\s)stage=([^ ]+)/)?.[1];if(stage){const id=Number(text.match(/(?:^|\s)id=(-?\d+)/)?.[1]),slot=Number(text.match(/(?:^|\s)slot=(-?\d+)/)?.[1]);const axes=['拇指侧摆','拇指','食指','中指','无名指','小指'];const finger=Number.isInteger(id)&&id>=1&&id<=6?axes[id-1]:Number.isInteger(slot)&&slot>=0&&slot<6?axes[slot]:'手指';if(/hardware.*outside|hardware_limits_invalid|target_intersection/.test(stage))return finger+'的位置不在舵机允许范围内，动作已停止';if(/outside/.test(stage)){const observed=Number(text.match(/(?:^|\s)observed=(-?\d+)/)?.[1]);return finger+'当前位置超出校准允许余量，先回到范围内再试'+(Number.isFinite(observed)&&observed>=0?'（当前位置 '+observed+'）':'')+'；动作已停止';}if(/feedback|read/.test(stage))return finger+'的位置反馈未读到，动作已停止；请检查该舵机连接和供电';if(/calibration|wrapped_motion/.test(stage))return finger+'的行程校准未通过，请重新确认范围';if(/torque/.test(stage))return finger+'的驱动力状态未通过检查，动作已停止';if(/moved|settle/.test(stage))return finger+'未到准备位置，动作已停止';if(/profile/.test(stage))return '当前舵机型号未通过检查，请确认所选型号';return finger+'的动作准备检查未通过，已停止';}const reasons={pattern_parameters_or_busy:'设备正在执行其他动作，或训练参数不正确；请先停止再试',pattern_full_target_not_reached:'本步未完成完整目标行程，训练已停止',score_motion_interval_too_short:'曲谱节奏过快，上一动作尚未完成半程；请降低整体速度',score_retrigger_interval_too_short:'同一手指重复过快，没有足够抬起时间；请降低整体速度',score_event_deadline_missed:'曲谱节奏超出当前处理速度；请降低整体速度',completed:'已完成',controller_disconnected:'控制连接中断，动作已停止',external_stop:'动作已停止',sc09_hold_supports_0_or_100:'SC09 只支持卸力或保持',storage_full:'存储空间不足，请删除不需要的曲谱',score_missing_or_corrupt:'曲谱不存在或损坏，请重新上传',initialization_timeout:'手指未到准备位置，动作已停止',calibration_or_other_motion_busy:'尚未完成校准，或调试台正在执行其他动作',train_parameters_or_busy:'当前动作被其他控制页面占用，或训练参数不正确；请先停止再试',busy_or_parameters:'设备已有动作在运行，或参数不正确；请先停止再试',tempo_bounds_or_owner:'当前动作由其他控制页面操作，请回到该页面调整速度',upload_owned_by_other_transport:'另一个控制页面正在上传曲谱，请等上传结束',upload_active_finish_or_abort_first:'正在上传曲谱，请等上传结束后再训练',upload_bounds_or_busy:'当前正在训练或曲目位置、文件大小不正确；请先停止动作再上传',upload_timeout:'上传等待超时，请检查连接后重新上传',busy_or_slot_missing:'曲谱不存在，或正在播放，请先停止后再删除',feedback_lost:'舵机位置反馈丢失，动作已停止；请检查连接和供电',position_feedback_lost:'舵机位置反馈丢失，动作已停止；请检查连接和供电',health_feedback_lost:'舵机电压或温度反馈丢失，动作已停止；请检查连接和供电',feedback_hardware_limit:'舵机位置超出硬件行程限制，动作已停止',outside_calibrated_range_slack:'手指超出允许的校准范围余量，动作已停止',recovery_moved_farther_outside:'恢复过程中手指继续向范围外移动，动作已停止；请核对方向',outside_calibrated_range_15pct:'手指超出允许的校准范围，动作已停止',movement_opposite_target:'手指朝相反方向移动，动作已停止；请核对按下与抬起方向',movement_below_half_target:'手指未完成目标行程的一半，动作已停止',temperature_or_voltage:'舵机温度或供电电压异常，动作已停止',stop_before_score_read:'请先停止当前动作，再读取或下载曲谱',hold_register_not_verified:'保持阻力设置未通过检查',hold_limit_write_readback_failed:'保持阻力设置失败，动作已停止',hold_limit_restore_failed:'原保持阻力未恢复，动作已停止',sync_write_failed:'动作指令未成功发送，请检查舵机连接',speed_register_incompatible:'舵机速度设置不兼容，请确认型号',invalid_pgl_crc_or_events:'曲谱文件校验失败，请重新导出并上传',compressed_readback_crc_failed:'曲谱写入后的校验失败，请重新上传',storage_mount_failed_preserved:'曲库存储无法读取，原资料已保留',none:'待机',user_stop:'已停止'};for(const [key,value] of Object.entries(reasons))if(new RegExp('(^|[^a-z_])'+key+'($|[^a-z_])').test(text))return value;if(/UNKNOWN_COMMAND|未知接口|404/.test(text))return '设备固件需更新，软件功能暂不可用';if(/Failed to fetch|NetworkError|fetch failed/.test(text))return '连接中断，请检查数据线或手套热点';if(/[A-Za-z_]{3,}/.test(text)&&!/[\u4e00-\u9fff]/.test(text))return '设备未完成操作，请停止后重试；具体原因尚未读到';
 // Never show a bare device code such as foo_bar_baz to a beginner inside a Chinese sentence.
 if(/\b[a-z]+(?:_[a-z0-9]+){2,}\b/.test(text))return text.replace(/[：:]?\s*\b[a-z]+(?:_[a-z0-9]+){2,}\b/g,'').trim()||'设备未完成操作，请停止后重试';return text;}
function conversionMessage(text){if(/permission|access.+denied|EACCES|WinError 5/i.test(text))return '没有写入权限，请换一个保存位置后重试';if(/disk full|no space|WinError 112/i.test(text))return '磁盘空间不足，请释放空间后重试保存';const translated=friendly(text);return translated==='设备未完成操作，请停止后重试；具体原因尚未读到'?'曲谱操作未完成：'+text:translated;}
const message=(s,error=false,scope='action')=>{if(scope==='hardware'&&reviewMode&&(!deviceWasConnected||($('message').dataset.messageScope==='action'&&$('message').textContent)))return;const text=String(s||'');$('message').dataset.messageScope=scope;$('message').textContent=/controller_mismatch|owned_elsewhere|owned_by_other|owner_mismatch|not_owner/.test(text)?'另一页面正在控制手套，请先在该页面停止':/controller_required|controller_token/.test(text)?'请刷新页面，重新建立控制连接':reviewMode&&scope==='action'?conversionMessage(text):friendly(text);$('message').style.color=error?'var(--error, #ffc1b3)':'';};
async function fetchJson(path,options,timeout){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);try{const r=await fetch(path,{...options,headers:{...options?.headers,'X-Piano-Controller':controllerToken},signal:controller.signal}),j=await r.json();if(!r.ok||j.ok===false)throw Error(j.error||'设备请求失败');return j;}catch(error){if(controller.signal.aborted)throw Error('连接等待超时，请检查连接后重试');throw error;}finally{clearTimeout(timer);}}
function scoreReadFeedback(){
 const previous=cachedFeedback||{};showFeedback({...previous,feedback:(previous.feedback||[]).map(axis=>({...axis,position_valid:false,pos_valid:false}))});
 for(let id=1;id<=6;id++){$('meter-status-'+id).textContent=scoreTransferVerb+'曲谱，反馈暂缓';$('meter-status-'+id).hidden=false;}
}
function usbConnectionKey(info=uploadCapabilities){return String(info?.port||'')+':'+String(info?.connectedAt??'');}
async function usbScoreTransfer(operation,verb='读取',expectedIdentity=usbConnectionKey()){
 if(active)throw Error('请先停止当前动作，再读取或下载曲谱');
 if(scoreReadBusy)throw Error('正在传输曲谱，请稍候');
 const token=generation,epoch=connectionEpoch,previousActivity=$('activity').textContent,previousPoll=pollPromise;
 scoreTransferVerb=verb;scoreReadBusy=true;stateRevision++;capability(false);scoreReadFeedback();
 $('activity').textContent=verb+'曲谱中…';$('sync').textContent='USB 曲谱传输中，位置反馈暂缓';
 $('connection').textContent=connectionBeforeLoss+' · '+verb+'曲谱';
 message('');
 let result,readError=null,fresh=null,stateError=null;
 try{
  // Bulk reads and upload/commit occupy the serial stream while idle. Drain
  // the current poll, then resume only after independent identity and STATE.
  if(previousPoll)await previousPoll;
  if(token!==generation)throw Error('曲谱'+verb+'已取消');
  if(epoch!==connectionEpoch)throw Error('设备连接已变化，请重新选择曲谱');
  result=await operation();
 }catch(error){readError=error;}
 try{
  const link=await api('/api/status');window.__gloveLink={connected:!!link.connected,info:String(link.device_info||''),at:Date.now()}; /* 11-05：给“固件太旧”提示用 */
  if(epoch!==connectionEpoch||!link.connected||usbConnectionKey(link)!==expectedIdentity)throw Error('设备连接已变化，请重新选择曲谱');
  fresh=await sampleState();
 }catch(error){stateError=error;lostState();}
 try{
  if(!stateError&&(!fresh||!validRecovery(fresh)))stateError=Error('曲谱已'+verb+'，但尚未收到新鲜的位置反馈，请稍后重试');
  if(!stateError&&fresh.active)stateError=Error('设备正在执行其他动作，请先停止后重试');
 }finally{
  scoreReadBusy=false;
  const ready=!stateError&&connectionInfoReady&&libraryReady&&!stateConnectionLost;
  capability(ready);
  if($('activity').textContent===verb+'曲谱中…')$('activity').textContent=previousActivity;
  if(ready){$('connection').textContent=connectionBeforeLoss+' · 已就绪';}
  else if(!stateConnectionLost&&fresh?.connection_state!=='waiting_servos'){$('connection').textContent=connectionBeforeLoss+' · 等待位置反馈';$('sync').textContent='等待新位置反馈';}
 }
 if(readError)throw readError;
 if(stateError)throw stateError;
 if(token!==generation)throw Error('曲谱'+verb+'已取消');
 if(!available)throw Error('曲谱已'+verb+'，正在恢复设备状态，请稍后重试');
 message('曲谱'+verb+'完成');
 return result;
}
function readUsbScore(path,options,prepared=null,expectedIdentity=usbConnectionKey()){return usbScoreTransfer(()=>prepared||fetchJson(path,options,120000),'读取',expectedIdentity);}
async function api(path,body,raw=false){const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':raw?'application/octet-stream':'application/x-www-form-urlencoded'},body:raw?body:new URLSearchParams(body)};if(!wirelessConnection&&body===undefined&&/^\/api\/score(?:\?|$)/.test(path))return readUsbScore(path,options);return fetchJson(path,options,/^\/api\/(upload|score)/.test(path)?120000:wirelessConnection&&/^\/api\/(state|keep)$/.test(path)?1200:5000);}
async function jsonApi(path,body){return fetchJson(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},90000);}
async function checkReviewProject(data){
 if(!window.NativeApp?.checkProject)return jsonApi('/api/software/check',{project:data});
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),90000);
 try{return await NativeApp.checkProject(data,{signal:controller.signal,headers:{'X-Piano-Controller':controllerToken}});}
 catch(error){if(controller.signal.aborted)throw Error('连接等待超时，请检查连接后重试');throw error;}
 finally{clearTimeout(timer);}
}
// Write commands share one ordered stream. A cancelled response may not send a
// second STOP after a newer action has started.
function motionApi(path,body,token=generation,force=false){motionPending++;const pending=motionQueue.catch(()=>{}).then(()=>((token===generation||force)&&(!nativeClosing||path==='/api/stop'))?api(path,body):null).finally(()=>motionPending--);motionQueue=pending;return pending;}
function stopBeacon(){navigator.sendBeacon('/api/stop',new Blob([new URLSearchParams({controller:controllerToken,scope:'owned'}).toString()],{type:'application/x-www-form-urlencoded'}));}
async function failMotion(error){error.motionHandled=true;if(/controller_mismatch|owned_elsewhere|owner_mismatch|owned_by_other|not_owner/.test(error.message)){finishLocal();message('另一页面正在控制手套，请先在该页面停止',true);return;}try{await stop();}catch{stopBeacon();}message(error.message,true);}
function guarded(fn,terminal=false){return async()=>{try{await fn();}catch(e){if(terminal&&!e.motionHandled)await failMotion(e);else message(e.message,true);}};}
// Continuous-clock firmware starts the score at LIB PLAY. Start the sound from the
// acknowledgement (measured within ~25 ms of the device start) instead of the first state poll, which arrives ~0.5 s later and
// used to skip or delay the opening notes.
function startClockAtPlay(at,from=0){if(uploadCapabilities?.score_clock!=='continuous-v1'||!score)return;const s={active:true,initializing:false,mode:'score',elapsed_ms:from,tempo:Number($('tempo').value)||100,duration_ms:Number(score.duration_ms)||0,score_clock:'continuous-v1',clock_paused:false};deviceClock.sync(s,at,at);if(audioReady&&$('sound').checked)audioTransport?.sync(s,at,at);}
function soundOffset(){const v=Number($('sound-offset').value)||0;$('sound-offset-label').textContent=(v>0?'+':'')+v+' ms';audioTransport?.setOffset(v);}
$('sound-offset').oninput=()=>{soundOffset();queueNativeSave();};
function settings(){return {tempo:$('tempo').value,amplitude:$('amplitude').value,hold:100};}
function continuousScore(s=state){return s?.score_clock==='continuous-v1'||(!s?.score_clock&&uploadCapabilities?.score_clock==='continuous-v1');}
function meterHTML(id){return `<div id="meter-${id}" class="position-meter"><div class="meter-scale"><span id="meter-encoder-${id}" class="encoder-top">—</span><div id="meter-water-${id}" class="meter-water"></div><div id="meter-allowed-${id}" class="meter-allowed" hidden></div><div id="meter-cal-${id}" class="meter-cal" hidden></div><div id="meter-line-${id}" class="meter-line" hidden></div><strong id="meter-value-${id}" class="meter-value">—</strong><span id="meter-zero-${id}" class="encoder-bottom">—</span></div><div class="meter-limits" hidden><span id="meter-max-${id}">上限 —</span><span id="meter-min-${id}">下限 —</span></div><small id="meter-margin-${id}" class="meter-margin" hidden>范围未读取</small><span id="meter-range-${id}" class="meter-range" title="范围未读取">—</span><span id="meter-status-${id}" class="meter-status">反馈未读取</span></div>`;}
function showFeedback(s){for(let id=1;id<=6;id++){const axis=s.feedback?.find(f=>Number(f.id)===id),range=Number(s.encoder_range),valid=axis&&(axis.position_valid===true||axis.position_valid===1||axis.pos_valid===true||axis.pos_valid===1),age=Number(axis?.sample_age_ms??axis?.position_age_ms),position=Number(axis?.position),fresh=valid&&Number.isFinite(age)&&age<=1000&&Number.isFinite(position),bounds=axis&&(axis.calibration_valid===true||axis.calibration_valid===1)&&Number.isFinite(axis.min)&&Number.isFinite(axis.max)&&axis.max>axis.min&&Number.isFinite(axis.allowed_min)&&Number.isFinite(axis.allowed_max)&&range>0;const percent=n=>Math.max(0,Math.min(100,n/range*100));$('meter-encoder-'+id).textContent=range>0?range:'—';$('meter-zero-'+id).textContent=range>0?'0':'—';$('meter-value-'+id).textContent=fresh?position:'—';$('meter-status-'+id).textContent=fresh?(bounds?'':'范围未读取'):valid?'反馈过期':'反馈未读取';$('meter-water-'+id).style.height=fresh&&range>0?percent(position)+'%':'0%';$('meter-line-'+id).hidden=!fresh||!(range>0);$('meter-line-'+id).style.bottom=fresh&&range>0?percent(position)+'%':'0%';for(const name of ['cal','allowed'])$('meter-'+name+'-'+id).hidden=!bounds;$('meter-max-'+id).textContent=bounds?'上限 '+axis.max:'上限 —';$('meter-min-'+id).textContent=bounds?'下限 '+axis.min:'下限 —';$('meter-margin-'+id).textContent=bounds?'余量 '+axis.allowed_min+'–'+axis.allowed_max:'范围未读取';$('meter-range-'+id).textContent=bounds?axis.min+'–'+axis.max:'—';$('meter-range-'+id).title=bounds?'校准 '+axis.min+'–'+axis.max+'；允许 '+axis.allowed_min+'–'+axis.allowed_max:'范围未读取';$('meter-range-'+id).setAttribute('aria-label',$('meter-range-'+id).title);for(const name of ['min','max','margin'])$('meter-'+name+'-'+id).hidden=true;if(bounds){$('meter-cal-'+id).style.bottom=percent(axis.min)+'%';$('meter-cal-'+id).style.height=(percent(axis.max)-percent(axis.min))+'%';$('meter-allowed-'+id).style.bottom=percent(axis.allowed_min)+'%';$('meter-allowed-'+id).style.height=(percent(axis.allowed_max)-percent(axis.allowed_min))+'%';}const outside=!!(fresh&&bounds&&(position<axis.allowed_min||position>axis.allowed_max)),hardwareOutside=!!(fresh&&range>0&&(position<0||position>range));$('meter-'+id).classList.toggle('outside',hardwareOutside);$('meter-'+id).classList.toggle('calibration-warning',outside&&!hardwareOutside);if(outside)$('meter-status-'+id).textContent=position>axis.allowed_max?'校准偏高 '+(position-axis.allowed_max):'校准偏低 '+(axis.allowed_min-position);if(hardwareOutside)$('meter-status-'+id).textContent='位置反馈异常';$('meter-status-'+id).hidden=!$('meter-status-'+id).textContent;}}
function showSong(view,text,error=false,pending=false){view.pending=pending;view.status.textContent=/controller_mismatch|owned_elsewhere|owner_mismatch/.test(text)?'另一页面正在控制手套，请先在该页面停止':error?friendly(text):text;view.status.style.color=error?'var(--error, #ffb3a9)':'';view.play.disabled=pending||!available;view.play.textContent=pending?'准备中':view.play.id==='native-ready-play'?'播放':'开始训练';$('player-replay').disabled=pending||!available;}
async function resolvePlayerSource(loaded){if(loaded.source_preview?.available&&loaded.source_preview.pages?.every(p=>typeof p.image_url==='string'&&/^\/api\/software\/source\//.test(p.image_url)))return attachPerformance(loaded);try{const bytes=loaded.base64?bytes64(loaded.base64):encodeScore(loaded),hash=await GlovePack.sha256(bytes),preview=await sourceCache.preview(hash);return attachPerformance(preview?{...loaded,source_preview:preview}:loaded);}catch(error){if(motionOnlyScore(loaded))return loaded;return attachPerformance(loaded);}}
// 11-05 用户：每次开始弹之前，大大的 3 2 1，给人准备时间；按停止/Esc 立刻取消
async function countdown(token){
 let box=document.getElementById('play-countdown');
 if(!box){box=document.createElement('div');box.id='play-countdown';box.setAttribute('aria-live','assertive');document.body.append(box);
  const css=document.createElement('style');css.textContent='#play-countdown{position:fixed;inset:0;z-index:250;display:grid;place-items:center;background:#1d273399;pointer-events:none}#play-countdown[hidden]{display:none}#play-countdown b{font:900 min(42vh,320px)/1 system-ui,sans-serif;color:#fff;-webkit-text-stroke:6px #1d2733;paint-order:stroke;animation:cd-pop .9s ease-out both}#play-countdown small{position:absolute;bottom:18vh;font:800 28px system-ui,sans-serif;color:#fff;text-shadow:0 2px 6px #000}@keyframes cd-pop{0%{transform:scale(1.6);opacity:0}25%{transform:scale(1);opacity:1}100%{transform:scale(.9);opacity:.85}}';document.head.append(css);}
 const beep=hi=>{try{const c=window.__cdAudio||(window.__cdAudio=new (window.AudioContext||window.webkitAudioContext)()),o=c.createOscillator(),g=c.createGain();o.frequency.value=hi?1320:880;g.gain.setValueAtTime(.18,c.currentTime);g.gain.exponentialRampToValueAtTime(.001,c.currentTime+.18);o.connect(g);g.connect(c.destination);o.start();o.stop(c.currentTime+.2);}catch{}};
 try{for(const n of [3,2,1]){if(token!==generation)return;box.hidden=false;box.innerHTML='<b>'+n+'</b><small>手放好，准备…</small>';beep(false);await new Promise(r=>setTimeout(r,900));}}
 finally{box.hidden=true;box.innerHTML='';}
}
async function playSong(song,play,status,verifiedRead=null,from=0){pausedAt=null;if(verifiedRead&&(wirelessConnection||verifiedRead.token!==generation||verifiedRead.epoch!==connectionEpoch||verifiedRead.identity!==usbConnectionKey()||Number(verifiedRead.slot)!==Number(song.slot)))throw Error('曲谱读取已过期，请重新点击播放');if(!available)throw Error('连接尚未恢复，请等待设备信息和曲库就绪');const before=++generation;message('');startAudio();if(before!==generation)return;const stopping=stop(),token=generation,view={play,status};playbackView=view;playerSong={song,play,status};showSong(view,'读取中…',false,true);openPlayer({title:song.title||'曲谱',notes:[]});$('player-note').textContent='读取中';try{await stopping;if(token!==generation)return;const raw=verifiedRead?await readUsbScore(null,{},verifiedRead.loaded,verifiedRead.identity):await api('/api/score?slot='+song.slot);if(token!==generation)return;const loaded=await resolvePlayerSource(raw);if(token!==generation){sourceCache.release(loaded.source_preview);return;}openPlayer(loaded);showSong(view,'准备中…',false,true);$('player-note').textContent='准备中';await countdown(token);if(token!==generation)return;const result=await motionApi('/api/play',{slot:song.slot,...settings(),...(from>0?{from_ms:from}:{})},token),acked=performance.now();if(!result||token!==generation)return;message('');score=loaded;audioTransport?.load(score);if(motionOnlyScore(score)){$('audio-status').textContent='待导入完整琴声';message('仅手套动作；请导入配套随谱包恢复完整琴声');}else if(audioReady&&$('sound').checked)$('audio-status').textContent='';lastElapsed=from;active=true;pauseLabel();startClockAtPlay(acked,from);if(from)message('从 '+clockText(from)+' 接着弹');const next=await sampleState(token);if(next&&!next.active)finishLocal('已停止：'+friendly(next.error||'none'));}catch(error){if(token!==generation)return;await failMotion(error);showSong(view,error.message,true);throw error;}}
function applyState(s){if(s.model){$('connection').textContent=$('connection').textContent.replace(/型号待识别/,s.model);if(/SC09|SCS/.test(s.model)){$('hold').step='100';if(!['0','100'].includes($('hold').value))$('hold').value='100';$('hold-label').textContent=$('hold').value==='0'?'卸力':'保持';}else{$('hold').step='10';}}rememberFeedback(s);if(active&&score){const text=s.initializing?'准备中':!continuousScore(s)&&s.clock_paused?'请求'+(s.tempo||100)+'% · 等待到位':'演奏中';$('activity').textContent=text;if(playbackView)showSong(playbackView,text,false,!!s.initializing);}else if(active&&s.mode==='pattern'){fingers(s.initializing?0:Number(s.mask)||0);trainingTones();const labels=['逐指','组合','交替'];const text=s.initializing?'准备中':(labels[s.pattern]||'训练')+' '+(Number(s.pattern_step)+1)+'/'+s.pattern_total+(s.fastest?' · 最快':'');$('activity').textContent=text;$('training-status').textContent=text;}}
async function enableAudio(){if(!$('sound').checked)return;audio ||= new (window.AudioContext||window.webkitAudioContext)({latencyHint:'interactive'});audioTransport ||= new GloveAudio.Transport(audio);audioTransport.setOffset(Number($('sound-offset').value)||0);if(audio.state&&audio.state!=='running')audioReady=false;await audio.resume();audioReady=true;$('audio-status').textContent=score&&motionOnlyScore(score)?'待导入完整琴声':'';audioTransport.setEnabled(true);if(score){audioTransport.load(score);if(state)audioTransport.sync(state,clock,clock);}return audio;}
function startAudio(){return enableAudio().then(()=>{if(active&&!score)trainingTones();}).catch(()=>{audioReady=false;$('audio-status').textContent='点击声音开启';message('声音尚未开启，请再点击声音');});}
function tone(key,pitch,velocity=96){if(!audio||!audioReady||voices.has(key)||!$('sound').checked)return;const gain=audio.createGain(),osc=audio.createOscillator(),harm=audio.createOscillator();const freq=440*Math.pow(2,(pitch-69)/12);osc.type='triangle';osc.frequency.value=freq;harm.type='sine';harm.frequency.value=freq*2;const overtone=audio.createGain();overtone.gain.value=.16;osc.connect(gain);harm.connect(overtone);overtone.connect(gain);gain.connect(audio.destination);gain.gain.setValueAtTime(0,audio.currentTime);gain.gain.linearRampToValueAtTime(.1*velocity/127,audio.currentTime+.015);osc.start();harm.start();voices.set(key,{osc,harm,gain});}
function release(key){const v=voices.get(key);if(!v)return;v.gain.gain.cancelScheduledValues(audio.currentTime);v.gain.gain.setTargetAtTime(0,audio.currentTime,.05);v.osc.stop(audio.currentTime+.3);v.harm.stop(audio.currentTime+.3);voices.delete(key);}
function silenceVoices(){for(const key of [...voices.keys()]){const v=voices.get(key);v.gain.gain.cancelScheduledValues(audio.currentTime);v.gain.gain.setValueAtTime(0,audio.currentTime);v.osc.stop(audio.currentTime);v.harm.stop(audio.currentTime);voices.delete(key);}}
function silence(){audioTransport?.stop();silenceVoices();}
function fingers(value){mask=value;for(let i=0;i<5;i++){const b=$('finger-'+i);b.classList.toggle('down',!!(value&(1<<i)));b.setAttribute('aria-pressed',String(!!(value&(1<<i))));$('finger-action-'+i).textContent=value&(1<<i)?'按下':'抬起';$('hand-finger-'+i).classList.toggle('down',!!(value&(1<<i)));}$('player-finger-cue').textContent=names.filter((_,i)=>value&(1<<i)).join('、')||'抬起';}
function scoreCompleted(s){const index=Number(s?.score_index),total=Number(s?.score_total);return s?.error==='completed'&&Number.isFinite(index)&&Number.isFinite(total)&&total>0&&index===total;}
function finishLocal(text='已停止'){if(text==='已停止：'+friendly('completed'))text='已完成'; // 练完不写“已停止：已完成”
if(text==='已停止'&&!active&&!patternActive&&!mask&&!motionPending)text='待机';if(text==='待机'&&active&&score&&playerDuration>0&&lastElapsed>=playerDuration-600)text='已完成'; // Y3：本来就没在动，就别写“已停止”
if(active&&score){if(scoreCompleted(state)){lastElapsed=playerDuration;text='已完成';}else if(state?.error==='completed')text='已停止，完成进度未确认';else if(state?.active&&performance.now()-deviceClock.anchor<=1000)lastElapsed=deviceClock.position(performance.now());renderPlayer(lastElapsed,false);}generation++;active=false;patternActive=false;score=null;state=null;silence();fingers(0);$('activity').textContent=text;$('player-note').textContent=text;if(playbackView)showSong(playbackView,text);$('training-status').textContent=text;pauseLabel();}
async function stop(owned=true){finishLocal();const token=generation;if(uploadInProgress){uploadInProgress=false;try{await uploadApi('/api/upload/abort',{},token,false,true);}catch{}}await motionApi('/api/stop',owned?{scope:'owned'}:{},token,true);return token;}
async function prepareNativeClose(){
 const needsStop=active||motionPending>0||uploadInProgress;
 nativeClosing=true;capability(false);
 // stop() cancels queued starts and silences locally before waiting for an
 // already-dispatched command, then appends the owned STOP after that command.
 if(!needsStop){finishLocal();return;}
 try{await stop();}catch(error){stopBeacon();throw error;}
}
function cancelNativeClose(){nativeClosing=false;capability(connectionInfoReady&&libraryReady&&!stateConnectionLost);}
async function sampleState(token=generation){const revision=++stateRevision,began=performance.now(),next=await api('/api/state'),ended=performance.now();if(token!==generation||revision!==stateRevision)return null;if(active&&score&&state?.active&&ended-deviceClock.anchor<=1000)lastElapsed=deviceClock.position(ended);if(!next.score_clock&&uploadCapabilities?.score_clock)next.score_clock=uploadCapabilities.score_clock;state=next;clock=(began+ended)/2;deviceClock.sync(next,began,ended);if(active&&score&&audioReady)audioTransport?.sync(next,began,ended);recoveredState(next);applyState(next);try{window.dispatchEvent(new CustomEvent('glove-state',{detail:next}));}catch{}if(active&&score){if(next.active){lastElapsed=deviceClock.position(ended);renderPlayer(lastElapsed);}else{if(scoreCompleted(next))lastElapsed=playerDuration;renderPlayer(lastElapsed,false);}}if(wirelessRetryPending){wirelessRetryPending=false;if($('message').dataset.messageScope==='link')message('');}$('sync').textContent=stateConnectionLost?'连接中断，等待新反馈':'通信 '+Math.round(ended-began)+' ms · 设备时钟同步';return next;}
function trainingTones(){for(let i=0;i<5;i++)mask&(1<<i)?tone('finger'+i,[60,62,64,65,67][i]):release('finger'+i);}
function timeLabel(ms){const seconds=Math.floor(Math.max(0,ms)/1000);return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');}
function pitchLabel(pitch){return ['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'][pitch%12]+(Math.floor(pitch/12)-1);}
function showTab(tab){reviewMode=tab==='convert';document.body.classList.toggle('review-view',tab==='convert');document.body.classList.toggle('playing-view',false);$('player').hidden=true;$('player-hand').hidden=true;$('player-finger-cue').hidden=true;$('feedback-home').appendChild($('feedback-panel'));document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b.dataset.tab===tab));['train','library','convert'].forEach(id=>$(id).hidden=id!==tab);$('feedback-panel').hidden=tab==='convert';if(reviewMode&&!deviceWasConnected){if($('message').dataset.messageScope==='hardware')message('');$('connection').textContent='手套未连接 · 可离线转换';}queueNativeSave(false);}
function practiceMessage(value){if(value?.version!==1||!['practice','strict'].includes(value.mode))return '';const groups=Array.isArray(value.estimates)?value.estimates.length:0;return value.mode==='practice'?'练习编排'+(groups?' · '+groups+'组估计，可在校对区修改':''):'';}
function attachPerformance(loaded){const value=loaded?.performance??loaded?.source_preview?.performance;return value!=null?{...loaded,performance:value}:loaded;}
// The device title keeps the arrangement id; people only need to know it is the practice version.
const plainTitle=title=>String(title).replace(/（练习·[0-9a-f]{16}）$/,'（练习版）').replace(/^\d{5,}_\d+_/,'').replace(/_(五线谱|带指法|黑键标注?|简谱)/g,'').replace(/\.pdf(?=（|$)/i,'').replace(/^(第\d+首（完整）)$/,'车尔尼练习曲 $1'); // 曲名给人看：去掉网站编号和文件名尾巴；内置的“第N首”都是车尔尼练习曲
const motionOnlyScore=loaded=>!loaded?.performance&&!loaded?.source_preview?.performance&&/（练习·[0-9a-f]{16}）$/.test(String(loaded?.title||''));
function performanceMessage(value){return value?.version===1&&value.basis==='detected-source-markers'&&typeof value.message==='string'&&value.message.length<=240?value.message:'';}
function sourcePerformanceMessage(){return practiceMessage(playerScore?.performance||playerScore?.source_preview?.performance)||performanceMessage(playerScore?.source_preview?.performance_notice||playerScore?.performance_notice);}
function sourceFallback(){$('player-source-toggle').hidden=true;sourceCache.release(playerSource);window.NativeApp?.releasePreview(playerSource);playerSource=null;$('player-source').hidden=true;for(const id of ['player-source-prev','player-source-next'])$(id).hidden=true;$('player-source-page').textContent='';$('player-source-label').textContent='音符进度';$('player-source-hint').textContent=(motionOnlyScore(playerScore)?'仅手套动作；导入配套随谱包才能恢复完整琴声':'未关联原谱，显示曲谱中的音符与指法')+(sourcePerformanceMessage()?'；'+sourcePerformanceMessage():'');$('player-source-hint').hidden=false;$('player-source-cursor').hidden=true;}
// Every song plays over the same note timeline; an attached original is rendered only
// on request so opening a long score is not held up by its PDF pages.
function renderPlayerSource(){if(!playerSource?.pages?.length)return sourceFallback();$('player-source-toggle').hidden=false;$('player-source-toggle').textContent=playerShowSource?'收起原谱':'看原谱';if(!playerShowSource){$('player-source').hidden=true;for(const id of ['player-source-prev','player-source-next'])$(id).hidden=true;$('player-source-label').textContent='音符进度';$('player-source-page').textContent='';const performance=practiceMessage(playerSource.performance)||performanceMessage(playerSource.performance_notice);$('player-source-hint').textContent=performance||'显示曲谱中的音符与指法；点「看原谱」查看原谱';$('player-source-hint').hidden=false;$('player-source-cursor').hidden=true;return;}const page=playerSource.pages[playerSourcePage];$('player-source-image').src=page.image_url;$('player-source').hidden=false;$('player-source-label').textContent='原谱';$('player-source-page').textContent=(page.page||playerSourcePage+1)+' / '+playerSource.pages.length+' 页';const performance=practiceMessage(playerSource.performance)||performanceMessage(playerSource.performance_notice);$('player-source-hint').textContent=performance||'未关联原谱，显示曲谱中的音符与指法';$('player-source-hint').hidden=!performance;for(const id of ['player-source-prev','player-source-next'])$(id).hidden=playerSource.pages.length<2;$('player-source-prev').disabled=playerSourcePage===0;$('player-source-next').disabled=playerSourcePage===playerSource.pages.length-1;$('player-source-cursor').hidden=true;}
function focusOriginalCursor(){const box=$('player-source-cursor'),viewport=$('player-source'),height=$('player-source-image').clientHeight;if(!box.hidden&&height>0&&viewport.clientHeight>0)viewport.scrollTop=Math.max(0,(parseFloat(box.style.top)+parseFloat(box.style.height)/2)/100*height-viewport.clientHeight/2);}
let playerAudioNotes=[],playerAudioPrefixEnd=[];
function openPlayer(loaded){loaded=attachPerformance(loaded);const richAudio=GloveAudio.audioNotesFor?GloveAudio.audioNotesFor(loaded):loaded.notes||[];playerAudioNotes=richAudio;let audioEnd=0;playerAudioPrefixEnd=richAudio.map(n=>audioEnd=Math.max(audioEnd,n.t_ms+n.duration_ms));reviewMode=false;document.body.classList.toggle('review-view',false);if(playerSource!==loaded.source_preview){sourceCache.release(playerSource);window.NativeApp?.releasePreview(playerSource);}playerScore=loaded;playerNotes=(loaded.notes||[]).map((n,index)=>({...n,index})).sort((a,b)=>a.t_ms-b.t_ms||a.index-b.index);let end=0;playerPrefixEnd=playerNotes.map(n=>end=Math.max(end,n.t_ms+n.duration_ms));playerDuration=Number(loaded.duration_ms)||end;playerSource=loaded.source_preview?.available&&Array.isArray(loaded.source_preview.pages)&&loaded.source_preview.pages.every(p=>typeof p.image_url==='string'&&(/^\/api\/software\/source\//.test(p.image_url)||sourceCache.ownsUrl(p.image_url)||window.NativeApp?.ownsPreviewUrl(p.image_url)))?loaded.source_preview:null;playerSourcePage=0;playerShowSource=false;playerRenderKey='';document.body.classList.toggle('playing-view',true);['train','library','convert'].forEach(id=>$(id).hidden=true);$('player').hidden=false;$('feedback-panel').hidden=false;$('player-feedback').appendChild($('feedback-panel'));$('player-hand').hidden=false;$('player-finger-cue').hidden=false;$('player-title').textContent=plainTitle(loaded.performance?.display_title||loaded.display_title||loaded.title||'曲谱演奏');renderPlayerSource();renderPlayer(-.001);}
function noteUpperBound(time){let l=0,r=playerNotes.length;while(l<r){const m=(l+r)>>>1;if(playerNotes[m].t_ms<=time)l=m+1;else r=m;}return l;}
function audioNoteUpperBound(time){let left=0,right=playerAudioNotes.length;while(left<right){const mid=(left+right)>>>1;if(playerAudioNotes[mid].t_ms<=time)left=mid+1;else right=mid;}return left;}
function playerAudioAt(time,highlight=true,passed=audioNoteUpperBound(time)){if(!highlight)return [];let left=passed;while(left>0&&playerAudioPrefixEnd[left-1]>time)left--;return playerAudioNotes.slice(left,passed).filter(n=>time<n.t_ms+n.duration_ms&&(n.audio_only||continuousScore()||!state?.clock_paused||!Number.isInteger(state.mask)||!!(state.mask&(1<<(n.finger-1)))));}
function sourceForAudio(current,motorCurrent){const ids=new Set(current.slice().sort((a,b)=>b.t_ms-a.t_ms||a.index-b.index).flatMap(n=>n.source_note_ids||[]).map(String)),map=playerSource?.performance?.source_map||playerScore?.performance?.source_map||{};for(const id of ids){const row=map[id],location=row?.location;if(location&&Number.isInteger(location.page))return {...location,index:id};}return playerSource?.note_pages?.find(n=>Array.isArray(n.source_note_ids)&&n.source_note_ids.some(id=>ids.has(String(id)))||motorCurrent.some(note=>note.index===n.index));}
function renderPlayer(elapsed,highlight=true){if(!playerScore)return;const notes=playerNotes,duration=playerDuration,position=Math.max(0,elapsed),passed=noteUpperBound(elapsed);let first=passed;while(first>0&&playerPrefixEnd[first-1]>elapsed)first--;const current=highlight?notes.slice(first,passed).filter(n=>elapsed<n.t_ms+n.duration_ms&&!(!continuousScore()&&state?.clock_paused&&Number.isInteger(state.mask)&&!(state.mask&(1<<(n.finger-1))))):[];$('player-time').textContent=timeLabel(position)+' / '+timeLabel(duration);$('player-progress').max=Math.max(1,duration);$('player-progress').value=Math.min(duration,position);const audioPassed=audioNoteUpperBound(elapsed),sounding=playerAudioAt(elapsed,highlight,audioPassed);$('player-note').textContent=motionOnlyScore(playerScore)?'手套动作 · '+passed+'/'+notes.length:sounding.length?sounding.map(n=>pitchLabel(n.pitch)).join(' + ')+' · '+audioPassed+'/'+playerAudioNotes.length:position>=duration&&notes.length?'已完成':state?.initializing?'准备中':!continuousScore()&&state?.clock_paused?'等待到位':'休止（这会儿不用按） · '+passed+'/'+notes.length;let m=0;for(const n of current)m|=1<<(n.finger-1);if(active&&score)fingers(m);
  const match=sourceForAudio(sounding,current);if(match){const pageIndex=playerSource.pages.findIndex(p=>p.page===match.page),changed=playerRenderKey!==String(match.index);if(pageIndex>=0&&changed){playerSourcePage=pageIndex;renderPlayerSource();playerRenderKey=String(match.index);}const page=playerSource.pages[playerSourcePage],box=$('player-source-cursor');const fields=['x','y','width','height'];if(page.page===match.page&&fields.every(k=>Number.isFinite(match[k]))&&page.width>0&&page.height>0){box.style.left=(match.x/page.width*100)+'%';box.style.top=(match.y/page.height*100)+'%';box.style.width=(match.width/page.width*100)+'%';box.style.height=(match.height/page.height*100)+'%';box.hidden=false;if(changed)focusOriginalCursor();}else box.hidden=true;}else $('player-source-cursor').hidden=true;
  const rate=Number(state?.tempo||100)/100,span=Math.max(4000,Math.min(16000,6000*rate)),start=position-span*.2,x=t=>Math.max(65,Math.min(960,65+(t-start)/span*895)),cursor=x(position);let svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 250" preserveAspectRatio="none">';for(let i=0;i<5;i++)svg+='<line class="timeline-lane" x1="65" x2="960" y1="'+(i*46+42)+'" y2="'+(i*46+42)+'"/><text class="timeline-finger" x="8" y="'+(i*46+30)+'">'+names[i]+'</text>';let visible=noteUpperBound(start);while(visible>0&&playerPrefixEnd[visible-1]>start)visible--;const visibleEnd=noteUpperBound(start+span);for(let index=visible;index<visibleEnd;index++){const n=notes[index],end=n.t_ms+n.duration_ms;if(end<start)continue;const left=x(n.t_ms),width=Math.max(5,x(end)-left),y=(n.finger-1)*46+9,isCurrent=current.some(v=>v.index===n.index);svg+='<rect class="timeline-note'+(isCurrent?' current':end<=position?' past':'')+'" x="'+left.toFixed(1)+'" y="'+y+'" width="'+width.toFixed(1)+'" height="29" rx="4"/>';if(width>27&&!motionOnlyScore(playerScore)&&!playerScore.performance)svg+='<text class="timeline-text" x="'+(left+5).toFixed(1)+'" y="'+(y+20)+'">'+pitchLabel(n.pitch)+'</text>';}svg+='<line class="timeline-current" x1="'+cursor.toFixed(1)+'" x2="'+cursor.toFixed(1)+'" y1="0" y2="245"/></svg>';$('player-timeline').innerHTML=svg;
}
$('player-source-image').onerror=sourceFallback;$('player-source-image').onload=focusOriginalCursor;$('player-source-toggle').onclick=()=>{playerShowSource=!playerShowSource;renderPlayerSource();};$('player-source-prev').onclick=()=>{playerSourcePage=Math.max(0,playerSourcePage-1);renderPlayerSource();};$('player-source-next').onclick=()=>{playerSourcePage=Math.min(playerSource.pages.length-1,playerSourcePage+1);renderPlayerSource();};$('player-back').onclick=guarded(async()=>{pausedAt=null;await stop();showTab('library');});// O3 暂停 / 继续：暂停 = 安全停下并记住位置；继续 = 从那里（往回退一点）接着弹（需要固件 r29.5 的 play_from）。
function clockText(ms){const s=Math.max(0,Math.floor(ms/1000));return Math.floor(s/60)+':'+String(s%60).padStart(2,'0');}
function pauseLabel(){const b=$('player-pause');if(!b)return;b.textContent=pausedAt!=null?'▶ 继续':'⏸ 暂停';b.disabled=pausedAt==null&&!active;b.classList.toggle('paused',pausedAt!=null);}
$('player-pause').onclick=guarded(async()=>{
 if(pausedAt!=null){const at=pausedAt;if(playerSong)await playSong(playerSong.song,playerSong.play,playerSong.status,null,at);return;}
 if(!active||!score)return;
 const now=performance.now(),pos=state?.active&&now-deviceClock.anchor<=1000?deviceClock.position(now):lastElapsed;
 if(!uploadCapabilities?.play_from){await stop();const text='已停下（这台手套的固件还不能从中间继续，升级固件后就可以）';$('player-note').textContent=text;$('activity').textContent='已停下';message(text);return;}
 await stop();pausedAt=Math.max(0,Math.round(pos)-400);pauseLabel();
 const text='已暂停在 '+clockText(pos)+' · 点「▶ 继续」接着弹';$('player-note').textContent=text;$('activity').textContent='已暂停';if(playbackView)showSong(playbackView,'已暂停');
});
$('player-replay').onclick=guarded(async()=>{pausedAt=null;if(playerSong)await playSong(playerSong.song,playerSong.play,playerSong.status);});
async function train(value,token=generation){if(token!==generation)return;message('');if(!available)throw Error(stateConnectionLost?'连接中断，请等待新反馈后再开始':'设备固件需更新，软件功能暂不可用');try{const result=await motionApi('/api/train',{mask:value,...settings()},token);if(!result||token!==generation)return;}catch(error){if(token!==generation)return;await failMotion(error);throw error;}message('');active=true;patternActive=false;score=null;state=null;fingers(value);trainingTones();$('activity').textContent='手指训练';}
$('thumb-pose').innerHTML=meterHTML(1);
for(let i=0;i<5;i++){const b=document.createElement('button');b.id='finger-'+i;b.className='finger-card';b.innerHTML=`<span class="finger-name">${names[i]} <small>ID${i+2}</small></span><span id="finger-action-${i}" class="finger-action">抬起</span>${meterHTML(i+2)}`;b.onclick=guarded(async()=>{const token=++generation;startAudio();if(token!==generation)return;if(active&&score){const next=await stop();if(next===generation)await train(1<<i,next);}else await train(mask^(1<<i),token);});$('fingers').appendChild(b);const digit=$('hand-finger-'+i);if(digit?.addEventListener){digit.style.cursor='pointer';digit.addEventListener('click',()=>{if(!b.disabled)b.click();});}}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
['tempo','amplitude','hold'].forEach(id=>$(id).oninput=()=>{$(id+'-label').textContent=id==='hold'&&$('hold').step==='100'?($(id).value==='0'?'卸力':'保持'):$(id).value+'%';});
$('tempo').onchange=guarded(async()=>{const token=generation,revision=++tempoRevision,rate=$('tempo').value;if(!active||!score)return;const pending=tempoQueue.catch(()=>{}).then(async()=>{if(token!==generation||revision!==tempoRevision)return;try{const result=await motionApi('/api/tempo',{tempo:rate},token);if(result&&token===generation)await sampleState(token);}catch(error){if(deferWirelessFailure(error)){message('调速结果未确认，请待连接恢复后重新调整',false,'link');return;}throw error;}});tempoQueue=pending;await pending;},true);
['amplitude','hold'].forEach(id=>$(id).onchange=guarded(async()=>{if(active&&!score&&!patternActive)await train(mask);else if(active)message('幅度和保持阻力在下次开始时生效');}));
$('sound').onchange=()=>{if(!$('sound').checked){audioTransport?.setEnabled(false);silenceVoices();$('audio-status').textContent='声音已关闭';return;}return startAudio();};
async function startPattern(name){const start=++generation;message('');startAudio();if(start!==generation)return;const token=await stop();if(token!==generation)return;const codes={single:0,combination:1,alternating:2};$('training-status').textContent='准备中';const repeats=Math.min(20,Math.max(1,Number($('repeats').value)||1));try{const result=await motionApi('/api/pattern',{pattern:codes[name],repeats,...settings(),tempo:$('tempo').value},token);if(!result||token!==generation)return;message('');active=true;patternActive=true;score=null;state=null;const next=await sampleState(token);if(next&&!next.active)finishLocal('已停止：'+friendly(next.error||'none'));}catch(error){if(token!==generation)return;await failMotion(error);$('training-status').textContent=friendly(error.message);throw error;}}
document.querySelectorAll('[data-pattern]').forEach(b=>b.onclick=guarded(()=>startPattern(b.dataset.pattern)));
$('fastest-training').onclick=()=>{$('tempo').value=$('tempo').max;$('tempo-label').textContent=$('tempo').max+'%';$('training-status').textContent='速度已设为最快 '+$('tempo').max+'%';return $('tempo').onchange();};
$('max-score-tempo').onclick=async()=>{$('tempo').value='1000';$('tempo-label').textContent='1000%';await $('tempo').onchange();};
$('stop').onclick=guarded(()=>{pausedAt=null;pauseLabel();return stop(false);}); // 红色停止＝彻底停，不再留「继续」
function closeSongDelete(){const request=songDeleteRequest;if(!request||request.busy)return;songDeleteRequest=null;$('song-delete-dialog').hidden=true;request.trigger.disabled=!available;(request.trigger.isConnected===false?$('refresh'):request.trigger).focus();}
function cancelStaleSongDelete(){if(songDeleteRequest&&!songDeleteRequest.busy)closeSongDelete();}
function askSongDelete(song,trigger){
 if(songDeleteRequest||!available||trigger.disabled)return;
 songDeleteRequest={slot:song.slot,title:song.title||'曲谱',trigger,epoch:connectionEpoch,revision:libraryRevision,busy:false};
 trigger.disabled=true;$('song-delete-name').textContent='第 '+song.slot+' 首 · '+songDeleteRequest.title;$('song-delete-status').textContent='';$('song-delete-confirm').disabled=false;$('song-delete-cancel').disabled=false;$('song-delete-cancel').textContent='取消';$('song-delete-dialog').hidden=false;$('song-delete-cancel').focus();
}
$('song-delete-cancel').onclick=closeSongDelete;
$('song-delete-confirm').onclick=guarded(async()=>{
 const request=songDeleteRequest;if(!request||request.busy||$('song-delete-confirm').disabled)return;
 if(!available||request.epoch!==connectionEpoch||request.revision!==libraryRevision){closeSongDelete();message('曲库已变化，请重新选择要删除的曲谱',true);return;}
 request.busy=true;$('song-delete-confirm').disabled=true;$('song-delete-cancel').disabled=true;$('song-delete-status').textContent='正在删除…';
 try{await api('/api/delete',{slot:request.slot});await refresh();request.busy=false;closeSongDelete();message('已删除“'+request.title+'”');}
 catch(error){request.busy=false;$('song-delete-status').textContent=friendly(error.message);$('song-delete-cancel').disabled=false;$('song-delete-cancel').textContent='关闭';$('song-delete-cancel').focus();throw error;}
});
document.addEventListener('keydown',event=>{
 if(!songDeleteRequest)return;
 if(event.key==='Escape'){event.preventDefault();closeSongDelete();}
 if(event.key==='Tab'){event.preventDefault();const cancel=$('song-delete-cancel'),confirm=$('song-delete-confirm');if(!cancel.disabled)(!confirm.disabled&&document.activeElement===cancel?confirm:cancel).focus();}
});
async function refresh(current=()=>true){const epoch=connectionEpoch,revision=++libraryRevision;cancelStaleSongDelete();const lib=await api('/api/library');if(epoch!==connectionEpoch||revision!==libraryRevision||!current())return false;const c=lib.capacity||lib;if(c.ready===false||c.ready===0){libraryReady=false;throw Error('曲库存储尚未就绪');}libraryReady=true;if(!Number.isFinite(lastStatePacketAt))lastStatePacketAt=performance.now();const entries=lib.slots||lib.songs||[];$('capacity').textContent=`已存 ${c.count??entries.length} / ${c.max??100} 首 · 剩余 ${((c.free||0)/1024).toFixed(0)} KB`;$('songs').replaceChildren();{const used=new Set(entries.map(s=>Number(s.slot)));let free=1;while(used.has(free)&&free<100)free++;if(document.activeElement!==$('slot'))$('slot').value=String(free);}if(!entries.length)$('songs').textContent='手套里还没有曲子。点上面「＋ 从软件自带挑曲子送进来」。';for(const s of entries){const row=document.createElement('div');row.className='song';row.dataset.slot=String(s.slot);row.dataset.title=plainTitle(s.title||'曲谱');const title=document.createElement('div');title.className='song-title';title.textContent=`${s.slot}. ${plainTitle(s.title||'曲谱')}`;const sub=document.createElement('small');sub.textContent=`${s.notes} 音 · ${((s.duration_ms||0)/1000).toFixed(1)} 秒 · ${s.stored||s.bytes} 字节`;title.appendChild(sub);row.appendChild(title);const play=document.createElement('button');play.textContent='开始训练';const songState=document.createElement('small');songState.className='song-state';songState.setAttribute('role','status');songState.setAttribute('aria-live','polite');title.appendChild(songState);play.onclick=guarded(()=>playSong(s,play,songState));const del=document.createElement('button');del.textContent='删除';del.onclick=()=>{if(epoch===connectionEpoch&&revision===libraryRevision)askSongDelete(s,del);};const download=document.createElement('button');download.textContent='下载';download.className='song-download';download.onclick=guarded(async()=>{const j=await api('/api/score?slot='+s.slot);if(j.base64)await downloadBlob(bytes64(j.base64),s.title+'.pgl','application/octet-stream');else await downloadBlob(encodeScore(j),s.title+'.pgl','application/octet-stream');});for(const button of [play,del,download])button.disabled=!available;row.append(play,del,download);$('songs').appendChild(row);}return true;}
function uploadApi(path,body,token,raw=false,force=false){const pending=motionQueue.catch(()=>{}).then(()=>token===generation||force?api(path,body,raw):null);motionQueue=pending;return pending;}
async function writeScoreData(data,slot,chunks,token){
  try{
   if(chunks){
    const size=Math.max(1,Math.min(16384,Number(uploadCapabilities.upload_chunk_max)||384));
    const begin=await uploadApi('/api/upload/begin',{slot,bytes:data.byteLength},token);if(!begin||token!==generation)return;
    for(let offset=0;offset<data.byteLength;offset+=size){
     if(token!==generation)return;const chunk=await uploadApi('/api/upload/chunk',data.slice(offset,offset+size),token,true);if(!chunk||token!==generation)return;
     message('上传 '+Math.min(100,Math.round((offset+Math.min(size,data.byteLength-offset))/data.byteLength*100))+'%');
    }
    if(token!==generation)return;const committed=await uploadApi('/api/upload/commit',{},token);if(!committed||token!==generation)return;
   }else{const saved=await uploadApi('/api/upload?slot='+slot,data,token,true);if(!saved||token!==generation)return;}
  }catch(error){
   if(chunks&&token===generation&&!/controller_mismatch|owned_elsewhere|owned_by_other|owner_mismatch/.test(error.message)){try{await uploadApi('/api/upload/abort',{},token,false,true);}catch{}}
   throw error;
  }
  if(token===generation)await refresh();
}
async function cacheScoreSource(pack){if(!pack)return '';try{const stored=await sourceCache.put(pack);return stored.persistent?'；原谱已保存在此浏览器':'；原谱在本页可用';}catch{return '；原谱未保存，请重新导入';}}
async function uploadScore(){
 const f=$('pgl').files[0];if(!f)throw Error('请选择 .pgl 或 .pglpack 文件');if(active)throw Error('请先停止动作，再上传曲谱');if(uploadInProgress)throw Error('正在写入曲谱，请稍候');if(Number(f.size)>GlovePack.MAX_PACK)throw Error('曲谱包须不超过32 MB');
 const token=generation;uploadInProgress=true;$('upload').disabled=true;
 const transfer=async()=>{
  const input=await f.arrayBuffer(),bytes=new Uint8Array(input),isPack=/\.pglpack$/i.test(f.name||'')||(bytes[0]===80&&bytes[1]===75&&bytes[2]===3&&bytes[3]===4),pack=isPack?await GlovePack.unpack(input):null,data=pack?pack.score.slice().buffer:input;
  if(token!==generation)return;GlovePack.validatePgl(new Uint8Array(data));
  await writeScoreData(data,Number($('slot').value),uploadCapabilities?.upload_protocol==='chunks-v1',token);
  if(token!==generation)return;return cacheScoreSource(pack);
 };
 try{
  const sourceStatus=wirelessConnection?await transfer():await usbScoreTransfer(transfer,'写入');
  if(token!==generation)return;message('曲谱已写入手套'+(sourceStatus||''));
 }finally{uploadInProgress=false;$('upload').disabled=!available;}
}
$('refresh').onclick=guarded(refresh);$('upload').onclick=guarded(uploadScore);
function bytes64(s){return Uint8Array.from(atob(s),c=>c.charCodeAt(0));}function as64(buffer){const bytes=new Uint8Array(buffer);let text='';for(let at=0;at<bytes.length;at+=16384)text+=String.fromCharCode(...bytes.subarray(at,at+16384));return btoa(text);}async function downloadBlob(data,name,type){if(window.NativeApp)return NativeApp.save(data,name);const u=URL.createObjectURL(new Blob([data],{type})),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
function encodeScore(s){const title=new TextEncoder().encode(s.title),notes=s.notes;if(s.version!==1||s.hand!=='right'||!title.length||title.length>96||!Array.isArray(notes)||!notes.length||notes.length>60000)throw Error('设备曲谱格式不正确');const out=new Uint8Array(128+16*notes.length),v=new DataView(out.buffer);out.set([80,71,76,49]);v.setUint16(4,1,true);v.setUint16(6,128,true);v.setUint32(8,notes.length,true);v.setUint32(12,s.duration_ms,true);v.setUint16(20,title.length,true);out.set(title,24);notes.forEach((n,i)=>{const k=128+16*i;v.setUint32(k,n.t_ms,true);v.setUint32(k+4,n.duration_ms,true);out[k+8]=n.pitch;out[k+9]=n.finger;out[k+10]=n.velocity??96;out[k+11]=n.amplitude_pct??100;});let crc=0xffffffff;for(const byte of out){crc^=byte;for(let bit=0;bit<8;bit++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}v.setUint32(16,(crc^0xffffffff)>>>0,true);return out;}
function renderOriginal(){const pages=originalSourceSha&&project?.source_sha256===originalSourceSha?originalPreviews:[];if(!pages.length){$('original-image').hidden=true;$('original-empty').hidden=false;return;}originalPage=Math.min(pages.length-1,Math.max(0,originalPage));$('original-image').src=originalPreviewHref(pages[originalPage]);$('original-image').hidden=false;$('original-image').style.width=$('original-zoom').value+'%';$('original-empty').hidden=true;$('original-page-label').textContent='第 '+(originalPage+1)+' / '+pages.length+' 页';$('original-prev').disabled=originalPage===0;$('original-next').disabled=originalPage===pages.length-1;visualReview?.renderOverlay();}
function changeOriginalPage(delta){originalPage+=delta;renderOriginal();visualReview?.pageChanged?.();}
$('original-prev').onclick=()=>changeOriginalPage(-1);$('original-next').onclick=()=>changeOriginalPage(1);$('original-zoom').oninput=renderOriginal;
function review(){
 $('review-summary').hidden=false;$('review-workspace').hidden=false;$('review-export').hidden=false;renderOriginal();
 const filename=project.source_name||project.name||'';$('review-filename').textContent=filename;$('review-filename').title=filename;
 $('bpm').title=Number.isFinite(project.source_tempo_bpm)?'原谱速度 '+project.source_tempo_bpm+' BPM，可按需要调整':'原谱未读到数字速度，新谱初始为 120 BPM，可按需要调整';
 const r=project.report||{},automatic=project.automatic_mode===true,right=project.notes.filter(n=>n.hand==='right'&&!n.excluded),unsupported=project.automatic?.unsupported===true;
 $('report').textContent=unsupported?(project.automatic?.messages?.[0]||'这份 PDF 没有右手印刷指法，当前不支持'):project.notes.length?(automatic?`${r.pages||project.pages?.length||0} 页 · ${right.length} 个右手音符`:`${r.pages||project.pages?.length||0} 页 · ${project.notes.length} 个候选音符`):'未自动识别到音符，可对照原谱补录。';
 if(project.unmatched_review_notes?.length)$('report').textContent+=' · '+project.unmatched_review_notes.length+' 处旧修改未能对应，已保留在复核文件中';
 const approval=$('range-reviewed').parentElement;if(approval)approval.hidden=automatic;
 reviewExportState();
 visualReview?.render();if($('review-full-list').open||!visualReview)renderReviewTable();
}
function reviewTimingLabel(n){return n?.timing_warning?(n.timing_estimated===false?'⚠ '+n.timing_warning:'⚠ 起拍约 '+n.beat+' 拍；'+n.timing_warning+'；修改此处，后续自动跟随'):'';}
function renderReviewTable(){if(!project)return;const automatic=project.automatic_mode===true; $('review-notes').replaceChildren();const head=document.createElement('div');head.className='note review-head'+(automatic?' review-auto-table':'');(automatic?['页 / 音','音高','指法','起拍','时值','手','忽略']:['页 / 音','音高','指法','起拍','时值','手','确认','排除']).forEach(t=>{const x=document.createElement('span');x.textContent=t;head.appendChild(x);});$('review-notes').appendChild(head);reviewTablePage=Math.min(Math.max(0,reviewTablePage),Math.max(0,Math.ceil(project.notes.length/100)-1));$('review-table-page').textContent=(reviewTablePage+1)+' / '+Math.max(1,Math.ceil(project.notes.length/100));$('review-table-prev').disabled=reviewTablePage===0;$('review-table-next').disabled=(reviewTablePage+1)*100>=project.notes.length;for(const n of project.notes.slice(reviewTablePage*100,reviewTablePage*100+100)){const row=document.createElement('div');row.className='note'+(automatic?' review-auto-table':'')+((automatic?!n.excluded&&n.in_export_scope!==false&&(n.automatic_reasons?.length||n.timing_warning):n.issues?.length)?' problem':'');row.dataset.noteId=String(n.id);row.title=[reviewTimingLabel(n),...(automatic?n.automatic_reasons||[]:n.issues||[])].filter(Boolean).map(x=>x==='manual_entry_requires_review'?'手动补录，请对照原谱核对':x).join('；');const id=document.createElement('span');id.textContent=String(n.id).startsWith('manual-')?`${n.page}/补${String(n.id).split('-').at(-1)}`:`${n.page}/${n.id}`;id.title=String(n.id);row.appendChild(id);for(const field of ['pitch','finger','beat','duration_beats']){const inp=document.createElement('input');inp.value=n[field]??'';if(field==='beat'&&inp.value===''){const candidate=n.written_beat??n.section_beat_candidate;if(Number.isFinite(candidate))inp.placeholder='候选 '+candidate;}if(field!=='pitch'){inp.type='number';inp.step=field==='finger'?'1':'0.25';}inp.onchange=()=>{n[field]=inp.value===''?null:field==='pitch'?inp.value:Number(inp.value);n.confirmed=false;markManualChange(n,field);confirmed.checked=false;invalidateRange();scheduleReviewCheck();visualReview?.render();};row.appendChild(inp);}const hand=document.createElement('select');[['right','右手'],['left','左手'],['','待核对']].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.textContent=t;hand.appendChild(o);});hand.value=n.hand||'';hand.onchange=()=>{n.hand=hand.value||null;n.confirmed=false;markManualChange(n,'hand');confirmed.checked=false;invalidateRange();scheduleReviewCheck();visualReview?.render();};row.appendChild(hand);const confirmed=document.createElement('input');confirmed.type='checkbox';confirmed.checked=!!n.confirmed;confirmed.title='已核对该音';confirmed.onchange=()=>{n.confirmed=confirmed.checked;invalidateRange();visualReview?.render();};const excluded=document.createElement('input');excluded.type='checkbox';excluded.checked=!!n.excluded;excluded.title='明确排除该候选';excluded.onchange=()=>{n.excluded=excluded.checked;n.human_reviewed=false;n.excluded_manual=true;n.validation_pending=true;n.automatic_reasons=[];invalidateRange();scheduleReviewCheck();visualReview?.render();};if(automatic)row.append(excluded);else row.append(confirmed,excluded);$('review-notes').appendChild(row);}}
$('review-full-list').ontoggle=()=>{if($('review-full-list').open)renderReviewTable();};$('review-table-prev').onclick=()=>{reviewTablePage--;renderReviewTable();};$('review-table-next').onclick=()=>{reviewTablePage++;renderReviewTable();};
let recognizingPdf=false;
async function recognizePdf(){const f=$('pdf').files?.[0];if(!f||recognizingPdf)return;recognizingPdf=true;$('pdf').disabled=true;$('recognize').disabled=true;$('review-step').textContent='正在识别…';$('report').textContent='正在读取 '+f.name;message('正在识别原谱…');try{if(await flushNativeSave()===false)throw Error('当前修改尚未保存，请先处理编辑框或保存错误');const r=await jsonApi('/api/software/convert',{filename:f.name,base64:as64(await f.arrayBuffer()),bpm:120});const same=acceptRecognized(r);message(same?'原谱已恢复，已保留复核和补录内容。':project.notes.length?'原谱已打开，点音符即可修改':'原谱已打开，可直接补录音符');}catch(e){if(project)review();else $('report').textContent='识别未完成，在“更多”中重试。';throw e;}finally{recognizingPdf=false;$('pdf').disabled=false;$('recognize').disabled=false;$('review-step').textContent='选谱 → 校对 → 导出';}}
$('pdf').onchange=guarded(recognizePdf);
$('recognize').onclick=guarded(recognizePdf);
function updateReviewScope(){const parts=[],start=$('start-beat').value,end=$('end-beat').value,first=$('start-page').value,last=$('end-page').value;if(end!=='')parts.push((start||'0')+'–'+end+' 拍');else if(Number(start)>0)parts.push(start+' 拍起');if(first!==''&&last!=='')parts.push(first===last?'第 '+first+' 页':'第 '+first+'–'+last+' 页');else if(first!=='')parts.push('第 '+first+' 页起');else if(last!=='')parts.push('至第 '+last+' 页');const s=project?.selection||{};if(s.start_system&&s.start_system===s.end_system)parts.push('第 '+s.start_system+' 行');$('review-export-summary').textContent='导出范围与反复 · '+(parts.join(' / ')||'全部');$('review-export-scope').textContent='导出：'+(parts.join(' / ')||'全部右手')+($('repeat-unfold').checked?' · 含反复':'');}
function exportFilenameSuffix(s){
 const parts=[];if(s.start_page&&s.start_page===s.end_page)parts.push('第'+s.start_page+'页');else if(s.start_page||s.end_page)parts.push('第'+(s.start_page||1)+'至'+(s.end_page||'末')+'页');
 if(s.start_system&&s.start_system===s.end_system)parts.push('第'+s.start_system+'行');
 if(s.end_beat!=null||Number(s.start_beat)>0)parts.push((s.start_beat||0)+'至'+(s.end_beat??'末')+'拍');
 return parts.length?'-'+parts.join('-'):'';
}
function setExportPreset(){
 if(!project)return;
 const choice=$('review-export-preset').value,settings=project.selection||={};
 if(!commitReviewEdits()){$('review-export-preset').value=settings.export_preset||'all';return;}
 if(choice==='custom'){$('review-more').open=true;$('review-range-options').open=true;settings.export_preset='custom';queueNativeSave();return;}
 const row=String($('review-row-select').value||'').match(/^(\d+):(\d+)$/);
 if(choice==='row'&&!row){message('请先选择要导出的谱行',true);$('review-export-preset').value=settings.export_preset||'all';return;}
 for(const key of ['start_system','end_system','start_measure','end_measure'])delete settings[key];
 $('start-beat').value='0';$('end-beat').value='';$('start-page').value='';$('end-page').value='';
 if(choice==='row'||choice==='page'){const page=choice==='row'?Number(row[1]):originalPage+1;$('start-page').value=$('end-page').value=String(page);if(choice==='row')settings.start_system=settings.end_system=Number(row[2]);}
 settings.export_preset=choice;invalidateRange();scheduleReviewCheck();visualReview?.refreshValidation?.();
}
$('review-export-preset').onchange=setExportPreset;
function invalidateRange(){queueNativeSave();updateReviewScope();$('range-reviewed').checked=false;$('ties-reviewed').checked=false;$('repeats-reviewed').checked=false;if(project){project.selection ||= {};project.selection.range_reviewed=false;project.selection.ties_reviewed=false;project.selection.repeats_reviewed=false;}}
function commitReviewEdits(){if(visualReview?.commitPendingEdits?.()===false){message('当前输入尚未应用，请修正，或关闭编辑框取消这次输入',true);return false;}return true;}
function reviewExportState(){
 if(!project)return;
 const unsupported=project.automatic?.unsupported===true,hasNotes=project.notes.some(n=>!n.excluded&&n.hand!=='left');
 $('export').disabled=exportingReview||unsupported||!hasNotes;$('review-play-glove').disabled=$('export').disabled;
 $('export').title=unsupported?'请选择带右手印刷指法的 PDF':!hasNotes?'右键恢复至少一个音符后再导出':'';
}
function cancelReviewCheck(){reviewRevision++;clearTimeout(reviewCheckTimer);reviewCheckTimer=null;}
function signalReviewProgress(){if(typeof window!=='undefined'&&typeof Event==='function')window.dispatchEvent(new Event('glove-review-progress'));}
function refreshReviewTableTiming(){
 for(const row of $('review-notes').children){const n=project?.notes.find(n=>String(n.id)===row.dataset?.noteId);if(!n)continue;for(const [index,field] of [[3,'beat'],[4,'duration_beats']]){const input=row.children[index];if(input&&input!==document.activeElement)input.value=n[field]??'';}row.title=reviewTimingLabel(n)||(project?.automatic_mode?n.automatic_reasons||[]:n.issues||[]).join('；');}
}
// Used by both the open editor and the background progress calculation.
function applyReviewValidation(target,result){
 if(!Array.isArray(result.notes)||!result.automatic)throw Error('检查结果不完整');
 const states=new Map(result.notes.map(n=>[String(n.id),n]));
 for(const n of target.notes){const status=states.get(String(n.id));if(status){n.automatic_ready=status.automatic_ready;n.automatic_reasons=status.automatic_reasons||[];n.in_export_scope=status.in_export_scope;if('unfingered' in status)n.unfingered=status.unfingered;if('source_fingering_state' in status)n.source_fingering_state=status.source_fingering_state;for(const key of ['timing_warning','timing_estimated','timing_source_id'])if(key in status)n[key]=status[key];if('performance_state'in status)n.performance_state=status.performance_state;else delete n.performance_state;if(result.right_hand_timing){if(n.human_reviewed===true&&'beat' in status&&n.beat!==status.beat)n.human_reviewed=false;for(const field of ['beat','start_beat','written_beat','measure_beat','measure_start_beat','main_anchor_beat'])if(field in status)n[field]=status[field];for(const field of Object.keys(status))if(field.startsWith('timing_'))n[field]=status[field];}}n.validation_pending=false;}
 if(result.right_hand_timing){for(const field of ['right_hand_timing','written_duration_beats','repeat_sections','repeat_markers','ending_brackets','rests'])if(field in result)target[field]=result[field];}
 if(result.performance?.version===1)target.performance=result.performance;else delete target.performance;target.automatic=result.automatic;target.export_scope=result.scope;target.report={...target.report,...result.report};target.validation_pending=false;target.validation_error='';
 return states;
}
async function checkCurrentReview(checkedProject=project,revision=reviewRevision){
 if(!checkedProject||checkedProject!==project||revision!==reviewRevision||!checkedProject.automatic_mode)return false;
 const {page_previews,...data}=selection();
 try{
  const result=await checkReviewProject(data);
  if(checkedProject!==project||revision!==reviewRevision)return false;
  const states=applyReviewValidation(project,result);
  reviewExportState();if(result.right_hand_timing){visualReview?.refreshTiming?.();refreshReviewTableTiming();notationOptions();}visualReview?.refreshValidation?.();for(const row of $('review-notes').children){const status=states.get(row.dataset?.noteId);if(status)row.classList.toggle('problem',status.in_export_scope!==false&&!!(status.automatic_reasons?.length||status.timing_warning));}queueNativeSave();signalReviewProgress();return true;
 }catch(error){
  if(checkedProject!==project||revision!==reviewRevision)return false;
  project.validation_pending=false;project.validation_error='检查暂未完成，导出时会再次校验';
  for(const n of project.notes)n.validation_pending=false;
  visualReview?.refreshValidation?.();signalReviewProgress();return false;
 }
}
function scheduleReviewCheck(){
 cancelReviewCheck();if(!project?.automatic_mode)return;
 const checkedProject=project,revision=reviewRevision;project.validation_pending=true;
 reviewExportState();reviewCheckTimer=setTimeout(()=>checkCurrentReview(checkedProject,revision),150);
}
function reviewChanged(){invalidateRange();scheduleReviewCheck();signalReviewProgress();if($('review-full-list').open)renderReviewTable();}
function markManualChange(note,field){
 note.human_reviewed=false;
 note.manual_fields=[...new Set([...(note.manual_fields||[]),field])];
 note.validation_pending=true;note.automatic_reasons=[];
 if(field==='beat')delete note.timing_anchor_scope;
 if(field==='finger')note.finger_source='manual';
}
function notationOptions(){if(!project)return;for(const id of ['ties-reviewed','repeats-reviewed']){const parent=$(id).parentElement;if(parent)parent.hidden=project.automatic_mode===true;}const repeats=project.repeat_sections||[],ties=project.notes.filter(n=>n.tie_to_candidate);$('repeat-options').hidden=!repeats.length;$('tie-options').hidden=!ties.length;$('notation-options').hidden=!repeats.length&&!ties.length;$('repeat-summary').textContent=repeats.map(r=>Number.isFinite(r.first_ending_start_beat)&&Number.isFinite(r.second_ending_end_beat)?'反复 '+r.start_beat+'–'+r.first_ending_start_beat+' 拍；一房候选 '+r.first_ending_start_beat+'–'+r.end_beat+'；二房候选 '+r.end_beat+'–'+r.second_ending_end_beat:'第 '+r.start_beat+'–'+r.end_beat+' 拍 ×'+(r.count||2)).join('；');$('repeat-summary').title=(project.repeat_review_issues||[]).join('；');$('tie-summary').textContent=ties.length+' 处候选；需核对同音连接';}
$('repeat-unfold').onchange=()=>{invalidateRange();if(project)project.selection.repeat_mode=$('repeat-unfold').checked?'unfold':'written';scheduleReviewCheck();};$('tie-apply').onchange=()=>{invalidateRange();if(project)project.selection.apply_tie_candidates=$('tie-apply').checked;scheduleReviewCheck();};
function manualPitch(value){
 const match=/^([A-Ga-g])(##|bb|#|b|)(-?\d+)$/.exec(value.trim());if(!match)return null;
 const note=match[1].toUpperCase()+match[2]+match[3],base={C:0,D:2,E:4,F:5,G:7,A:9,B:11}[match[1].toUpperCase()];
 const accidental={'':0,'#':1,'##':2,b:-1,bb:-2}[match[2]],midi=(Number(match[3])+1)*12+base+accidental;
 return Number.isInteger(midi)&&midi>=0&&midi<=127?{pitch:note,midi}:null;
}
function openManualNote(){
 if(!project||!Array.isArray(project.notes))throw Error('请先选择并识别 PDF，或导入复核文件');
 if(!commitReviewEdits())return;
 let dialog=$('manual-note-dialog');
 if(!dialog){
  dialog=document.createElement('dialog');dialog.id='manual-note-dialog';dialog.className='manual-note-dialog';
  dialog.innerHTML=`<form id="manual-note-form"><h2>补录音符</h2><p>先在原谱里点靠近漏音的一个音，确认它所在的小节；再填写下面的信息。手动补录不会在原谱上伪造位置。</p>
   <label>已有补录<select id="manual-existing"><option value="">新增一个音</option></select></label>
   <p id="manual-context" class="manual-context"></p>
   <div class="manual-fields"><label>音高<input id="manual-pitch" placeholder="例如 C4 或 F#4" autocomplete="off" required></label>
    <label>手指<select id="manual-finger" required><option value="">请选择</option><option value="1">1 拇指</option><option value="2">2 食指</option><option value="3">3 中指</option><option value="4">4 无名指</option><option value="5">5 小指</option></select></label>
    <label>小节里第几拍<input id="manual-local" type="number" min="1" step="any" placeholder="例如 1 或 1.5" required></label>
    <label>弹多长<select id="manual-duration" required><option value="">请选择</option><option value="4">4 拍 · 全音符</option><option value="2">2 拍 · 二分音符</option><option value="1">1 拍 · 四分音符</option><option value="0.5">半拍 · 八分音符</option><option value="0.25">1/4 拍 · 十六分音符</option><option value="0.125">1/8 拍 · 三十二分音符</option></select></label></div>
   <p id="manual-error" role="status" aria-live="polite"></p><div class="manual-actions"><button type="button" id="manual-cancel">取消</button><button type="submit" id="manual-save">保存这个音</button></div></form>`;
  document.body.appendChild(dialog);
  $('manual-cancel').onclick=()=>dialog.close();
 }
 const anchor=visualReview?.current?.(),existing=$('manual-existing'),form=$('manual-note-form');
 const manualNotes=()=>project.notes.filter(n=>String(n.id).startsWith('manual-'));
 existing.replaceChildren(new Option('新增一个音',''),...manualNotes().map(n=>new Option(`第 ${n.page||'?'} 页 · ${n.pitch||'音高未填'} · ${n.excluded?'已排除':'补录'}`,String(n.id))));
 const fill=()=>{
  const note=manualNotes().find(n=>String(n.id)===existing.value),base=note&&Number.isFinite(note.measure_start_beat)?note:anchor;
  dialog._anchor=base||null;dialog._editing=note||null;
  $('manual-context').textContent=base&&Number.isFinite(base.measure_start_beat)&&Number.isFinite(base.meter_beats)?`所在位置：第 ${base.page} 页 · 第 ${base.system||'?'} 行 · 本行第 ${base.measure||'?'} 小节（共 ${base.meter_beats} 拍）`:'请先关闭窗口，在要补录的小节里点一个已有音，再回来补录。';
  $('manual-pitch').value=note?.pitch||'';$('manual-finger').value=note?.finger??'';
  $('manual-local').value=note&&Number.isFinite(note.beat)&&Number.isFinite(base?.measure_start_beat)?String(Math.round((note.beat-base.measure_start_beat+1)*1000)/1000):'';
  $('manual-duration').value=note?.duration_beats??'';$('manual-error').textContent='';
 };
 existing.onchange=fill;fill();
 form.onsubmit=event=>{
  event.preventDefault();const base=dialog._anchor,note=dialog._editing,pitch=manualPitch($('manual-pitch').value),finger=Number($('manual-finger').value),local=Number($('manual-local').value),duration=Number($('manual-duration').value);
  if(!base||!Number.isFinite(base.measure_start_beat)||!Number.isFinite(base.meter_beats)||!base.page||!base.system||!base.measure){$('manual-error').textContent='请先点选漏音附近已有的音，确定所在小节。';return;}
  if(!pitch){$('manual-error').textContent='请填写音名，例如 C4 或 F#4。';return;}
  if(!Number.isInteger(finger)||finger<1||finger>5||!Number.isFinite(local)||local<1||local>=base.meter_beats+1||!Number.isFinite(duration)||duration<=0){$('manual-error').textContent='请选好手指、音长，并填写这个小节里的起拍位置。';return;}
  const fields={page:base.page,system:base.system,measure:base.measure,staff:base.staff,global_measure_index:base.global_measure_index,measure_start_beat:base.measure_start_beat,meter_beats:base.meter_beats,hand:'right',pitch:pitch.pitch,midi:pitch.midi,finger,finger_source:'manual',beat:base.measure_start_beat+local-1,measure_beat:local-1,duration_beats:duration,confirmed:false,validation_pending:true,manual_fields:['pitch','finger','beat','duration_beats'],timing_anchor_scope:'measure',issues:['manual_entry_requires_review']};
  let target=note;
  if(target){visualReview?.rememberEdit?.(target.id);Object.assign(target,fields);target.human_reviewed=false;}
  else{let id;do{id='manual-'+Date.now()+'-'+(++manualCounter);}while(project.notes.some(n=>n.id===id));target={id,...fields};project.notes.push(target);visualReview?.rememberAddition?.(id);}
  dialog.close();$('review-tools').open=false;reviewChanged();review();visualReview?.select(target.id);message('已保存手动补录；可用“撤销”取消这次修改');
 };
 if(!dialog.open)dialog.showModal();
}
$('add-note').onclick=guarded(async()=>openManualNote());
['start-beat','end-beat','start-page','end-page'].forEach(id=>{$(id).oninput=$(id).onchange=()=>{if(project){project.selection||={};for(const key of ['start_system','end_system','start_measure','end_measure'])delete project.selection[key];project.selection.export_preset='custom';$('review-export-preset').value='custom';}invalidateRange();scheduleReviewCheck();};});
function selection(){if(!project)throw Error('请先识别或导入复核文件');project.selection={...project.selection,bpm:Number($('bpm').value),start_beat:Number($('start-beat').value),end_beat:$('end-beat').value===''?null:Number($('end-beat').value),start_page:$('start-page').value===''?null:Number($('start-page').value),end_page:$('end-page').value===''?null:Number($('end-page').value),range_reviewed:$('range-reviewed').checked,repeat_mode:$('repeat-unfold').checked?'unfold':'written',repeats_reviewed:$('repeats-reviewed').checked,apply_tie_candidates:$('tie-apply').checked,ties_reviewed:$('ties-reviewed').checked};return project;}
$('save-review').onclick=guarded(async()=>{if(!commitReviewEdits())return;await downloadBlob(JSON.stringify(selection(),null,2),project.name+'-复核.json','application/json');});
function restoreSelection(){const s=project.selection||{};$('bpm').value=s.bpm||120;$('start-beat').value=s.start_beat||0;$('end-beat').value=s.end_beat??'';$('start-page').value=s.start_page??'';$('end-page').value=s.end_page??'';$('range-reviewed').checked=!!s.range_reviewed;$('repeat-unfold').checked=s.repeat_mode==='unfold';$('repeats-reviewed').checked=!!s.repeats_reviewed;$('tie-apply').checked=!!s.apply_tie_candidates;$('ties-reviewed').checked=!!s.ties_reviewed;$('review-export-preset').value=s.export_preset||(['start_page','end_page','start_system','end_system','end_beat'].some(k=>s[k]!=null)||Number(s.start_beat)>0?'custom':'all');notationOptions();updateReviewScope();}
function loadReview(next){if(!next||!Array.isArray(next.notes))throw Error('复核文件不正确');cancelReviewCheck();if(!originalSourceSha||next.source_sha256!==originalSourceSha){releaseOriginalPreviewUrls();originalSourceSha='';originalPreviews=[];$('original-empty').textContent='请选择对应的 PDF 并识别，显示原谱';}project=next;projectProgressGeneration=-1;projectProgressCacheToken=null;projectProgressScope=null;project.automatic_mode=true;project.manual_review_import=true;originalPage=0;restoreSelection();review();scheduleReviewCheck();queueNativeSave();message('已载入复核进度'+(originalSourceSha&&next.source_sha256===originalSourceSha?'':'；选择对应 PDF 恢复原谱'));}
$('bpm').oninput=()=>{visualReview?.render();scheduleReviewCheck();queueNativeSave();};
$('review-file').onchange=guarded(async()=>{const input=$('review-file'),file=input.files?.[0];if(!file)return;try{if(await flushNativeSave()===false)return;loadReview(JSON.parse(await file.text()));}finally{input.value='';}});
async function exportReview(skipPending=false){
 if(exportingReview||!project||!commitReviewEdits())return;
 const sourceProject=project,selected=selection(),baseFilename=selected.name+exportFilenameSuffix(selected.selection);
 exportingReview=true;reviewExportState();$('export').textContent='正在导出…';
 try{
  const r=await jsonApi('/api/software/export',{project:selected,skip_pending:skipPending,page_previews:selected.source_sha256&&selected.source_sha256===originalSourceSha?originalPreviews:[]});
  const skipped=Number.isInteger(r.skipped_pending_count)?r.skipped_pending_count:0;
  const filename=baseFilename+(skipped?'（部分动作，跳过'+skipped+'处）':'');
  const packaged=!!r.package_base64&&r.package_extension==='pglpack';if(r.preferred_extension==='pglpack'&&!packaged)throw Error(r.package_error||'这份练习编排需要随谱包，未能完整打包，请重试');const saved=await downloadBlob(bytes64(packaged?r.package_base64:r.base64),filename+(packaged?'.pglpack':'.pgl'),'application/octet-stream');
  if(saved===false){message('已取消保存');return;}
  const performance=practiceMessage(r.performance_summary)||performanceMessage(r.performance_notice);
  message((skipped?'已导出部分动作谱，跳过 '+skipped+' 处待处理；原谱中的位置仍可修改':packaged?(r.performance_summary?.mode==='practice'?'已导出练习编排曲谱包':'已导出带原谱曲谱，可传到手机'):r.package_error?(/超过|过大/.test(r.package_error)?'原谱包过大，已导出曲谱':'原谱未打包，已导出曲谱'):'已导出 '+r.bytes+' 字节曲谱')+(performance?'；'+performance:''));
 }catch(error){
  if(project===sourceProject){await checkCurrentReview();const first=project.automatic?.attention_note_ids?.[0];if(first)visualReview?.focusIssue?.(first);}
  throw error;
 }finally{exportingReview=false;$('export').textContent='导出曲谱';reviewExportState();}
}
$('export').onclick=guarded(()=>exportReview(true)); // 11-04：只留一个导出，待查的音自动跳过（同「送到手套」）
// One step from a recognised PDF to the glove: package, store in a free slot, play.
let reviewPlayProblemTimer=null;
function reviewPlayProblem(status,text){
 clearTimeout(reviewPlayProblemTimer);status.textContent=text;status.classList.add('problem');
 reviewPlayProblemTimer=setTimeout(()=>{if(status.classList.contains('problem')&&status.textContent===text){status.textContent='';status.classList.remove('problem');}},6000);
}
async function playReviewOnGlove(){
 if(exportingReview||!project||!commitReviewEdits())return;
 const selected=selection(),button=$('review-play-glove'),status=$('review-play-status');
 if(!available){reviewPlayProblem(status,'请先连接手套，等待舵机和曲库就绪');return;}
 clearTimeout(reviewPlayProblemTimer);
 status.classList.remove('problem');
 exportingReview=true;reviewExportState();button.textContent='正在准备…';status.textContent='';
 try{
  const r=await jsonApi('/api/software/export',{project:selected,skip_pending:true,page_previews:selected.source_sha256&&selected.source_sha256===originalSourceSha?originalPreviews:[]});
  const packaged=!!r.package_base64&&r.package_extension==='pglpack',skipped=Number.isInteger(r.skipped_pending_count)?r.skipped_pending_count:0;
  await playBuiltin({base64:packaged?r.package_base64:r.base64,name:selected.name+(packaged?'.pglpack':'.pgl')},button,status);
  if(skipped)message('有 '+skipped+' 个音软件没认准，这次先跳过了；想补上就回到「PDF 识谱」按提示改');
 }catch(error){reviewPlayProblem(status,friendly(error.message));throw error;
 }finally{exportingReview=false;button.textContent='▶ 送到手套，开始弹';reviewExportState();}
}
$('review-play-glove').onclick=guarded(playReviewOnGlove);
document.addEventListener('pointerdown',event=>{if(event.target.closest?.('#review-play-glove'))return;const status=$('review-play-status');if(status?.classList.contains('problem')){clearTimeout(reviewPlayProblemTimer);status.textContent='';status.classList.remove('problem');}},true);
setInterval(async()=>{if(!active||keepBusy)return;keepBusy=true;const token=generation;try{await api('/api/keep',{});}catch(e){if(token===generation&&active&&!deferWirelessFailure(e))await failMotion(e);}finally{keepBusy=false;}},500);
setInterval(async()=>{expireFeedback();const now=performance.now();if(scoreReadBusy||pollBusy||recoveryStateBusy||now-lastStatePoll<(wirelessConnection?(active?120:300):(active?50:200)))return;lastStatePoll=now;pollBusy=true;const token=generation;try{pollPromise=sampleState(token);const next=await pollPromise;if(!next)return;if(!next.active&&active){finishLocal(next.error&&next.error!=='none'?'已停止：'+friendly(next.error):'待机');}}catch(e){if(token===generation&&!deferWirelessFailure(e)){const wasActive=active;lostState();if(wasActive)stopBeacon();}}finally{pollBusy=false;pollPromise=null;}},50);
function audioTick(){if(active&&score&&audioReady&&$('sound').checked)audioTransport?.pump();}
setInterval(audioTick,20);
function frame(){const now=performance.now();if(active&&score&&state?.active&&now-lastVisualFrame>=30){lastVisualFrame=now;lastElapsed=deviceClock.position(now);renderPlayer(lastElapsed);}requestAnimationFrame(frame);}requestAnimationFrame(frame);
async function init(){capability(false);$('activity').textContent='正在读取曲库';$('capacity').textContent='正在读取曲库';await recoverConnection(true);}
// Remember whether the beginner proofreading guide was folded away.
(()=>{const guide=$('proof-guide');if(!guide)return;try{if(localStorage.getItem('pg-proof-guide')==='closed')guide.open=false;}catch{}const close=$('proof-guide-close');if(close)close.onclick=()=>{guide.open=false;};guide.ontoggle=()=>{try{localStorage.setItem('pg-proof-guide',guide.open?'open':'closed');}catch{}};})();
for(const button of document.querySelectorAll?.('.tempo-quick [data-tempo]')||[])button.onclick=()=>{const tempo=$('tempo');tempo.value=button.dataset.tempo;for(const type of ['input','change'])tempo.dispatchEvent(new Event(type,{bubbles:true}));};
function releasePage(){const wasActive=active;finishLocal(wasActive?'软件窗口被切走或最小化，为了安全手套已停下；回来后再点开始即可':'待机');if(wasActive)stopBeacon();}
if(typeof GloveReview!=='undefined')visualReview=GloveReview.create({project:()=>project,page:()=>originalPage,previews:()=>originalSourceSha&&project?.source_sha256===originalSourceSha?originalPreviews:[],previewHref:originalPreviewHref,setPage:value=>{originalPage=value;renderOriginal();},changed:reviewChanged,progressChanged:()=>queueNativeSave(),notice:text=>{message(text);if(/^✓/.test(text)&&!/^✓ 这一行没问题/.test(text))window.ComicGuide?.toast?.(text);},exportSkippingPending:guarded(()=>exportReview(true))});

let nativeSaveTimer=null,nativeRestoring=false,nativeSaveChain=Promise.resolve(true),nativeSaveRevision=0,nativeSavedUiRevision=-1,nativeQueuedUiRevision=-1,nativeMusicRevision=0,nativeSavedMusic=new WeakMap(),nativeQueuedMusic=new WeakMap();
function currentWorkspace(includeProject=true){
 const tab=document.querySelector('[data-tab].selected')?.dataset.tab||'train';let saved=null,proofProgress=null;
 if(includeProject&&project){const {page_previews,...fields}=selection();saved=fields;if(!project.validation_pending&&!project.validation_error){proofProgress={...GloveReview.combinedProgress(project),unmatched:(project.unmatched_review_notes||[]).length};}}
 return {project:saved,proof_progress:proofProgress,proof_generation:projectProgressGeneration,proof_cache_token:projectProgressCacheToken,proof_scope:projectProgressScope,ui:{tab,row:$('review-row-select').value,page:originalPage,rowMode:!$('review-row-panel').hidden,zoom:$('original-zoom').value,settings:{tempo:$('tempo').value,amplitude:$('amplitude').value,hold:$('hold').value,sound:$('sound').checked,soundOffset:$('sound-offset').value}}};
}
async function flushNativeSave(){
 if(!window.NativeApp||nativeRestoring)return true;
 clearTimeout(nativeSaveTimer);nativeSaveTimer=null;const badge=$('native-review-save');
 if(!commitReviewEdits()){if(badge)badge.textContent='当前输入尚未保存';return false;}
 clearTimeout(nativeSaveTimer);nativeSaveTimer=null;
 const wanted={project,revision:nativeMusicRevision},isSaved=token=>!token.project||nativeSavedMusic.get(token.project)>=token.revision,musicDirty=!isSaved(wanted),alreadyQueued=!!wanted.project&&nativeQueuedMusic.get(wanted.project)>=wanted.revision;
 const saveMusic=musicDirty&&!alreadyQueued,saveUi=nativeSaveRevision>nativeSavedUiRevision&&nativeSaveRevision>nativeQueuedUiRevision;
 if(!saveMusic&&!saveUi)return nativeSaveChain;
 const value=JSON.stringify(currentWorkspace(saveMusic)),revision=nativeSaveRevision,musicToken=saveMusic?wanted:null;
 if(musicToken)nativeQueuedMusic.set(musicToken.project,musicToken.revision);
 nativeQueuedUiRevision=Math.max(nativeQueuedUiRevision,revision);
 const pending=nativeSaveChain.catch(()=>{}).then(async()=>{
  try{
   if(!musicToken&&!isSaved(wanted))throw Error('曲谱修改尚未保存，请重试');
   const api=await NativeApp.ready;if(typeof api.save_workspace_json==='function')await api.save_workspace_json(value);else await api.save_workspace(JSON.parse(value));
   if(musicToken)nativeSavedMusic.set(musicToken.project,musicToken.revision);
   nativeSavedUiRevision=Math.max(nativeSavedUiRevision,revision);
   if(badge&&revision===nativeSaveRevision){badge.textContent='已自动保存';badge.classList?.remove?.('error');}return true;
  }catch(error){if(musicToken&&nativeQueuedMusic.get(musicToken.project)===musicToken.revision)nativeQueuedMusic.delete(musicToken.project);if(nativeQueuedUiRevision===revision)nativeQueuedUiRevision=nativeSavedUiRevision;if(badge&&revision===nativeSaveRevision){badge.textContent='保存失败，请重试';badge.classList?.add?.('error');}message('校对进度未保存：'+(error.message||String(error)),true);return false;}
 });
 nativeSaveChain=pending;return pending;
}
function queueNativeSave(projectChanged=true){if(!window.NativeApp)return;if(projectChanged&&project)nativeMusicRevision++;nativeSaveRevision++;if(nativeRestoring)return;const badge=$('native-review-save');if(badge)badge.textContent='正在保存…';if(projectChanged||nativeSaveTimer===null){clearTimeout(nativeSaveTimer);nativeSaveTimer=setTimeout(()=>{nativeSaveTimer=null;flushNativeSave();},250);}}
function mergeRecognized(fresh,remembered,restoring=false){
 const {page_previews,...freshFields}=fresh,same=!!remembered?.source_sha256&&remembered.source_sha256===fresh.source_sha256;
 if(same){
  // The API result is a new owned tree; reuse it instead of serializing the
  // entire score a second time when opening a saved review.
  const next=freshFields,tieRestores=[];
  next.unmatched_review_notes=[];const oldEdits=new Map([...(remembered.notes||[]),...(remembered.unmatched_review_notes||[])].map(n=>[String(n.id)+'|'+JSON.stringify(n.origin||n.bbox),n]));
  const byPage=new Map();for(const n of next.notes){const page=Number(n.page);if(!byPage.has(page))byPage.set(page,[]);byPage.get(page).push(n);}
  const placeMatches=prior=>{const a=prior.origin||prior.bbox,candidates=byPage.get(Number(prior.page))||[];if(!Array.isArray(a)&&remembered.recognizer===fresh.recognizer)return candidates.filter(current=>String(current.id)===String(prior.id)&&!Array.isArray(current.origin||current.bbox));return candidates.filter(current=>{const b=current.origin||current.bbox;return Array.isArray(a)&&Array.isArray(b)&&Math.abs(a[0]-b[0])<=2&&Math.abs(a[1]-b[1])<=2;});};
  const rememberTie=(prior,current)=>{if((prior.tie_to!==undefined||prior.tie_reviewed!==undefined)&&(prior.confirmed||String(prior.id).startsWith('manual-')||(prior.manual_fields||[]).some(field=>field==='tie_to'||field==='tie_reviewed'))){if(prior.tie_to===undefined&&prior.tie_reviewed===false)current.tie_reviewed=false;else tieRestores.push({prior,current});}};
  for(const prior of oldEdits.values()){
   const fields=new Set(prior.manual_fields||[]),hadManualBeat=fields.has('beat'),manualEntry=String(prior.id).startsWith('manual-');
   const hasPerformanceOverride=prior.performance_override&&typeof prior.performance_override==='object'&&!Array.isArray(prior.performance_override)&&Object.keys(prior.performance_override).length>0;
   const excludedManually=prior.excluded_manual===true||(prior.excluded===true&&!prior.issues?.includes('excluded_non_piano_staff'));
   const acceptedEstimate=typeof prior.start_estimate_ok==='number'&&Number.isFinite(prior.start_estimate_ok); // 点过「就这样弹」
   const humanReviewed=prior.human_reviewed===true;
   if(!humanReviewed&&!prior.confirmed&&!fields.size&&!excludedManually&&!manualEntry&&!hasPerformanceOverride&&!acceptedEstimate)continue;
   const matches=placeMatches(prior),current=matches.length===1?matches[0]:null;
   if(current&&acceptedEstimate)current.start_estimate_ok=prior.start_estimate_ok;
   if(!humanReviewed&&!prior.confirmed&&!fields.size&&!excludedManually&&!manualEntry&&!hasPerformanceOverride)continue;
   if(current){
    rememberTie(prior,current);
    if(hasPerformanceOverride)current.performance_override=JSON.parse(JSON.stringify(prior.performance_override));
    for(const field of ['pitch','finger','beat','duration_beats','hand','confirmed','excluded'])if(prior[field]!==undefined&&(prior.confirmed||manualEntry||fields.has(field)||(field==='excluded'&&excludedManually)))current[field]=prior[field];
    if(prior.confirmed||manualEntry)for(const field of ['pitch','finger','beat','duration_beats','hand'])if(prior[field]!==undefined)fields.add(field);
    if(fields.has('beat')){
     delete current.timing_anchor_scope;
     if(hadManualBeat&&prior.timing_anchor_scope==='measure'&&Number.isFinite(prior.beat)&&prior.beat>=0&&Number.isFinite(prior.measure_beat)&&prior.measure_beat>=0){current.timing_anchor_scope='measure';current.measure_beat=prior.measure_beat;}
    }
    current.manual_fields=[...fields];if(excludedManually)current.excluded_manual=true;
    if(prior.confirmed||manualEntry||fields.has('finger'))current.finger_source='manual';
    if(humanReviewed){
     const unchanged=['pitch','finger','beat','duration_beats','hand'].every(field=>(prior[field]??null)===(current[field]??null));
     if(unchanged)current.human_reviewed=true;
     else{current.human_reviewed=false;const saved=JSON.parse(JSON.stringify(prior));saved.review_merge_issue='human_review_values_changed';next.unmatched_review_notes.push(saved);}
    }
   }else if(manualEntry&&!matches.length){const added=JSON.parse(JSON.stringify(prior));next.notes.push(added);const page=Number(added.page);if(!byPage.has(page))byPage.set(page,[]);byPage.get(page).push(added);rememberTie(prior,added);}
   else next.unmatched_review_notes.push(JSON.parse(JSON.stringify(prior)));
  }
  for(const {prior,current} of tieRestores){
   // A saved tie refers to old note IDs. Restore only a unique source-geometry
   // target after all manually inserted notes have been restored as well.
   if(prior.tie_to===null){current.tie_to=null;if(prior.tie_reviewed!==undefined)current.tie_reviewed=prior.tie_reviewed;continue;}
   const targets=prior.review_merge_tie_target?[prior.review_merge_tie_target]:[...oldEdits.values()].filter(note=>String(note.id)===String(prior.tie_to));
   const matches=targets.length===1?placeMatches(targets[0]):[],target=matches.length===1?matches[0]:null;
   if(target&&target!==current){current.tie_to=target.id;if(prior.tie_reviewed!==undefined)current.tie_reviewed=prior.tie_reviewed;}
   else{
    delete current.tie_to;current.tie_reviewed=false;current.confirmed=false;current.human_reviewed=false;
    const saved=JSON.parse(JSON.stringify(prior));saved.review_merge_issue='manual_tie_target_unresolved';
    if(targets.length===1)saved.review_merge_tie_target=JSON.parse(JSON.stringify(targets[0]));
    next.unmatched_review_notes.push(saved);
   }
  }
  next.selection={...next.selection,...remembered.selection};
  // Absence is the legacy effective written mode, not an explicit user choice.
  // An active new conversion keeps fresh.practice; startup restoration does not upgrade it.
  if(remembered.performance_policy!==undefined)next.performance_policy=JSON.parse(JSON.stringify(remembered.performance_policy));
  else if(restoring)delete next.performance_policy;
  if(typeof remembered.name==='string'&&remembered.name.trim())next.name=remembered.name;
  if(remembered.manual_review_import)next.manual_review_import=true;
  return {project:next,same};
 }
 return {project:freshFields,same:false};
}
function canReuseNativeValidation(result,same){
 const fresh=result.project,receipt=result.native_validation;
 return !same&&!result.review&&receipt?.version===1&&fresh.automatic_mode===true&&fresh.validation_pending!==true&&receipt.source_sha256===fresh.source_sha256&&receipt.recognizer===fresh.recognizer&&receipt.notes===fresh.notes.length&&receipt.automatic_version===fresh.automatic?.version&&JSON.stringify(receipt.selection)===JSON.stringify(fresh.selection||{})&&JSON.stringify(receipt.performance_policy??null)===JSON.stringify(fresh.performance_policy??null);
}
function normalizeProgressSelection(target){
 const s=target.selection||{},optional=v=>v==null||v===''?null:Number(v);
 target.selection={...s,bpm:Number(s.bpm||120),start_beat:Number(s.start_beat||0),end_beat:optional(s.end_beat),start_page:optional(s.start_page),end_page:optional(s.end_page),range_reviewed:!!s.range_reviewed,repeat_mode:s.repeat_mode==='unfold'?'unfold':'written',repeats_reviewed:!!s.repeats_reviewed,apply_tie_candidates:!!s.apply_tie_candidates,ties_reviewed:!!s.ties_reviewed};
}
async function calculateCatalogProgress(result){
 if(!result?.project||!Array.isArray(result.project.notes))throw Error('曲谱数据不完整');
 const {project:target,same}=mergeRecognized(result.project,result.review,false),reuseValidation=canReuseNativeValidation(result,same);
 if(!reuseValidation&&target.automatic_mode===true){normalizeProgressSelection(target);const checked=await checkReviewProject(target);applyReviewValidation(target,checked);}
 if(target.validation_pending||target.validation_error)throw Error('曲谱检查尚未完成');
 const progress=GloveReview.combinedProgress(target);
 return {...progress,unmatched:(target.unmatched_review_notes||[]).length};
}
// Library playback must use the same full score + saved edits as the editor.
// catalog_open returns only the edited notes in review, never a complete score.
async function packageCatalogScore(scoreId,title){
 if(await flushNativeSave()===false)throw Error('校对修改尚未保存，请重试');
 const native=await NativeApp.ready,result=await native.catalog_open(String(scoreId),120,false);
 if(!result?.project||!Array.isArray(result.project.notes))throw Error('曲谱数据不完整');
 const previews=result.project.page_previews||[];
 const {project:target,same}=mergeRecognized(result.project,result.review,false);
 if(result.review&&!same)throw Error('保存的校对与原谱不一致，请打开曲谱校对');
 if(target.unmatched_review_notes?.length)throw Error('有 '+target.unmatched_review_notes.length+' 处旧修改未能对应，请打开曲谱校对');
 normalizeProgressSelection(target);
 const exported=await jsonApi('/api/software/export',{project:target,skip_pending:true,page_previews:previews});
 const packaged=!!exported.package_base64&&exported.package_extension==='pglpack';
 return {name:String(title||target.name||scoreId)+(packaged?'.pglpack':'.pgl'),
  base64:packaged?exported.package_base64:exported.base64,skipped:Number(exported.skipped_pending_count)||0};
}
function acceptRecognized(result){
 cancelReviewCheck();
 const fresh=result.project,freshPreviews=fresh.page_previews||[],remembered=result.review||project;
 const {project:next,same}=mergeRecognized(fresh,remembered,nativeRestoring),reuseValidation=canReuseNativeValidation(result,same);
 project=next;projectProgressGeneration=Number.isInteger(result.progress_generation)?result.progress_generation:0;projectProgressCacheToken=result.progress_cache_token??null;projectProgressScope=result.progress_scope??null;restoreSelection();
 releaseOriginalPreviewUrls();originalPreviews=freshPreviews;originalSourceSha=originalPreviews.length?fresh.source_sha256||'':'';originalPage=0;review();
 if(!project.notes.length&&$('review-workspace').classList.contains('row-review'))$('review-row-mode').click();queueNativeSave();if(!reuseValidation)scheduleReviewCheck();return same;
}
function restoreNativeWorkspace(value){
 if(!value)return;nativeRestoring=true;
 try{
  if(value.project)acceptRecognized(value);
  const preferences=value.ui?.settings;
  for(const id of ['tempo','amplitude'])if(preferences?.[id]!==undefined){$(id).value=preferences[id];$(id+'-label').textContent=preferences[id]+'%';}
  if(preferences?.sound!==undefined)$('sound').checked=preferences.sound;if(preferences?.soundOffset!==undefined){$('sound-offset').value=preferences.soundOffset;soundOffset();}
  if(value.ui?.row&&[...$('review-row-select').options].some(o=>o.value===value.ui.row)){$('review-row-select').value=value.ui.row;$('review-row-select').dispatchEvent(new Event('change'));}
  if(project&&Number.isInteger(value.ui?.page)){originalPage=Math.max(0,Math.min((project.pages?.length||1)-1,value.ui.page));renderOriginal();visualReview?.pageChanged();}
  if(value.ui?.rowMode===false&&!$('review-row-panel').hidden)$('review-row-mode').click();
  if(value.ui?.zoom){$('original-zoom').value=value.ui.zoom;renderOriginal();}
  showTab(['train','library','convert'].includes(value.ui?.tab)?value.ui.tab:'train');
 }finally{nativeRestoring=false;}queueNativeSave(false);
}
async function playBuiltin(bundle,button,status,options={}){
 if(!available)throw Error('请先连接手套，等待舵机和曲库就绪');
 if(uploadInProgress)throw Error('正在写入曲谱，请稍候');
 if(active)await stop();
 const token=generation,identity=usbConnectionKey(),usb=!wirelessConnection;
 const prepare=async()=>{
  const loadedBundle=typeof bundle==='function'?await bundle():bundle;
  if(token!==generation)return;
  // A recognised PDF can arrive as a bare .pgl when its source could not be packed.
  const bytes=bytes64(loadedBundle.base64),zipped=bytes[0]===80&&bytes[1]===75,pack=zipped?await GlovePack.unpack(bytes.buffer):{score:bytes},meta=GlovePack.validatePgl(pack.score),hash=await GlovePack.sha256(pack.score);
  if(loadedBundle.score_sha256&&hash!==loadedBundle.score_sha256)throw Error('内置曲谱校验失败');
  if(token!==generation)return;
  const listing=await api('/api/library'),songs=listing.slots||listing.songs||[];
  let existing=null,verifiedRead=null;
  for(const song of songs.filter(s=>s.title===meta.title&&Number(s.notes)===meta.count)){
   if(token!==generation)return;status.textContent='正在读取已存曲谱并核对…';
   const path='/api/score?slot='+song.slot,loaded=usb?await fetchJson(path,{},120000):await api(path),data=loaded.base64?bytes64(loaded.base64):encodeScore(loaded);
   if(await GlovePack.sha256(data)===hash){existing=song;if(usb)verifiedRead={loaded,slot:song.slot,token,epoch:connectionEpoch,identity};break;}
  }
  if(token!==generation)return;
  if(!existing){
   const occupied=new Set(songs.map(s=>Number(s.slot)));let slot=1;while(occupied.has(slot)&&slot<=100)slot++;
   if(slot>100)throw Error('手套曲库已满，请先删除一首曲谱');
   $('slot').value=String(slot);const transfer=new DataTransfer();transfer.items.add(new File([bytes],loadedBundle.name));$('pgl').files=transfer.files;
   status.textContent='首次准备，正在存入手套…';uploadInProgress=true;
   try{await writeScoreData(pack.score.slice().buffer,slot,uploadCapabilities?.upload_protocol==='chunks-v1',token);}
   finally{uploadInProgress=false;}
   if(token!==generation)return;existing={slot,title:meta.title,notes:meta.count,duration_ms:meta.duration_ms};
  }
  if(zipped)await cacheScoreSource(pack);
  return {existing,verifiedRead};
 };
 const prepared=usb?await usbScoreTransfer(prepare,'准备',identity):await prepare();
 if(token!==generation||!prepared)return;
 if(options.storeOnly)return prepared.existing; // 11-04 批量存进手套：只存不播
 await playSong(prepared.existing,button,status,prepared.verifiedRead);
}
// 11-04 用户：曲库要能多选、一键下载/删除
async function libraryBulk(action,slots){
 if(!available)throw Error('请先连接手套，等待舵机和曲库就绪');
 if(active)await stop();
 const done=[];
 if(action==='delete'){
  for(const slot of slots){message('正在删除第 '+slot+' 首…');await api('/api/delete',{slot});done.push(slot);}
  await refresh();message('已删除 '+done.length+' 首');return done;
 }
 if(action==='download'){
  const files=[];
  for(const slot of slots){
   message('正在读取第 '+slot+' 首…');const row=document.querySelector('#songs .song[data-slot="'+slot+'"]'),title=row?.dataset.title||('第'+slot+'首');
   const j=await api('/api/score?slot='+slot),data=j.base64?bytes64(j.base64):encodeScore(j);
   files.push({name:String(slot).padStart(2,'0')+' '+title.replace(/[\\/:*?"<>|]/g,'_')+'.pgl',base64:as64(data)});
  }
  const result=window.NativeApp?await (await NativeApp.ready).save_many(files):null;
  if(!result){for(const f of files)await downloadBlob(bytes64(f.base64),f.name,'application/octet-stream');message('已下载 '+files.length+' 首');return files.length;}
  message(result.saved?'已下载 '+result.count+' 首到 '+result.folder:'已取消下载');return result.count||0;
 }
 throw Error('不支持的操作');
}
window.GloveWorkspace={openProject:acceptRecognized,calculateCatalogProgress,packageCatalogScore,progressIdentity:()=>({generation:projectProgressGeneration,cacheToken:projectProgressCacheToken,scope:projectProgressScope}),show:showTab,notice:message,playBuiltin,libraryBulk,gloveReady:()=>!!available,refreshLibrary:()=>refresh(),importReview:value=>{loadReview(value);},restore:restoreNativeWorkspace,queueSave:queueNativeSave,prepareClose:prepareNativeClose,cancelClose:cancelNativeClose,flush:flushNativeSave};

init();window.addEventListener('pagehide',releasePage);document.addEventListener('visibilitychange',()=>{if(document.hidden)releasePage();});
})();

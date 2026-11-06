const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../native-transport.js'),'utf8');
function harness(api,delayed=false){
 const listeners={},docListeners={},calls=[],window={location:{href:'file:///C:/piano/software.html'},addEventListener:(name,fn)=>listeners[name]=fn},navigator={},document={addEventListener:(name,fn)=>docListeners[name]=fn,getElementById:()=>null};
 const exposed={request:async(...args)=>{calls.push(args);return api?.request?api.request(...args):{status:200,headers:{'content-type':'application/json'},body:{ok:true},binary:false};},save_file:async(...args)=>api?.save_file?api.save_file(...args):{saved:true},stage_files:async rows=>{calls.push(['stage',rows]);return true;},open_page:async page=>{calls.push(['page',page]);return true;},open_runtime_download:async()=>{calls.push(['runtime-download']);return {opened:true}}};
 if(!delayed)window.pywebview={api:exposed};
 const jsonStringifies=[];const scopedJson={parse:JSON.parse,stringify(value){jsonStringifies.push(value);return JSON.stringify(value)}};
 vm.runInNewContext(code,{window,navigator,document,URL,URLSearchParams,Headers,Response,Blob,ArrayBuffer,Uint8Array,DOMException,atob,btoa,Error,Set,Promise,JSON:scopedJson});
 return {window,navigator,calls,docListeners,jsonStringifies,ready(){window.pywebview={api:exposed};listeners.pywebviewready();}};
}
test('form requests preserve controller, query, method and real response status',async()=>{
 const h=harness({request:async()=>({status:409,headers:{'content-type':'application/json'},body:{ok:false,error:'busy'},binary:false})});
 const response=await h.window.fetch('/api/play?slot=2',{method:'POST',headers:{'X-Piano-Controller':'native-owner','Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({tempo:100})});
 assert.equal(h.calls[0][0],'/api/play?slot=2');assert.equal(h.calls[0][1],'POST');assert.equal(h.calls[0][2],'tempo=100');assert.equal(h.calls[0][4]['x-piano-controller'],'native-owner');assert.equal(response.status,409);assert.equal(response.ok,false);assert.equal((await response.json()).error,'busy');
});
test('a file drop in the main window directly reaches the import workflow',async()=>{
 const h=harness(),files=[{name:'测试.pdf'}];let imported,prevented=false;h.window.GloveWorkspace={importFiles:async value=>imported=value};await h.docListeners.drop({dataTransfer:{files},preventDefault:()=>prevented=true});assert.equal(prevented,true);assert.equal(imported[0],files[0]);assert.equal(h.calls.length,0);
});
test('a drop in debug stages exact bytes and returns to the main workspace',async()=>{
 const h=harness(),file={name:'曲谱.pdf',arrayBuffer:async()=>new Uint8Array([0,128,255]).buffer};await h.docListeners.drop({dataTransfer:{files:[file]},preventDefault(){}});assert.equal(h.calls[0][0],'stage');assert.equal(h.calls[0][1][0].name,'曲谱.pdf');assert.deepEqual([...Buffer.from(h.calls[0][1][0].content,'base64')],[0,128,255]);assert.deepEqual(h.calls[1],['page','software']);
});
test('raw chunk bytes and typed-array offsets cross the JSON boundary unchanged',async()=>{
 const h=harness();const bytes=new Uint8Array([9,11,22,33,8]);await h.window.fetch('/api/upload/chunk',{method:'POST',body:bytes.subarray(1,4)});
 assert.equal(h.calls[0][3],true);assert.deepEqual([...Buffer.from(h.calls[0][2],'base64')],[11,22,33]);
});
test('initial requests wait for pywebview readiness rather than reporting false offline',async()=>{
 const h=harness(undefined,true),pending=h.window.fetch('/api/status');await Promise.resolve();assert.equal(h.calls.length,0);h.ready();assert.equal((await pending).status,200);assert.equal(h.calls.length,1);
});
test('an aborted request waiting for the native bridge is never sent later',async()=>{
 const h=harness(undefined,true),abort=new AbortController(),pending=h.window.fetch('/api/train',{method:'POST',body:'mask=1',signal:abort.signal});abort.abort();h.ready();await assert.rejects(pending,{name:'AbortError'});assert.equal(h.calls.length,0);
});
test('beacon cleanup retains scoped controller data and its form content type',async()=>{
 const h=harness();assert.equal(h.navigator.sendBeacon('/api/stop',new Blob(['controller=mine&scope=owned'],{type:'application/x-www-form-urlencoded'})),true);for(let i=0;i<10&&!h.calls.length;i++)await new Promise(r=>setImmediate(r));
 assert.equal(h.calls[0][4]['content-type'],'application/x-www-form-urlencoded');assert.equal(Buffer.from(h.calls[0][2],'base64').toString(),'controller=mine&scope=owned');
});
test('native source images become owned blob URLs and are revoked on release',async()=>{
 const source='/api/software/source/'+'a'.repeat(64)+'/1';const h=harness({request:async p=>p===source?{status:200,headers:{'content-type':'image/png'},body:'iVBORw0KGgo=',binary:true}:{status:200,headers:{'content-type':'application/json'},body:{source_preview:{available:true,pages:[{image_url:source}]}},binary:false}});
 const response=await h.window.fetch('/api/score?slot=2'),json=await response.json(),url=json.source_preview.pages[0].image_url;
 assert.match(url,/^blob:/);assert.equal(h.window.NativeApp.ownsPreviewUrl(url),true);assert.equal(h.window.NativeApp.ownsPreviewUrl('blob:forged'),false);h.window.NativeApp.releasePreview(json.source_preview);assert.equal(h.window.NativeApp.ownsPreviewUrl(url),false);
});
test('native save preserves bytes and reports cancellation without false success',async()=>{
 let saved;const h=harness({save_file:async(...args)=>{saved=args;return {saved:false};}});assert.equal(await h.window.NativeApp.save(new Uint8Array([0,128,255]),'曲谱.pgl'),false);assert.deepEqual([...Buffer.from(saved[0],'base64')],[0,128,255]);assert.equal(saved[1],'曲谱.pgl');
});
test('internal navigation waits for owned stop before replacing the application page',async()=>{
 const h=harness();await h.window.fetch('/api/status',{headers:{'X-Piano-Controller':'mine'}});await h.window.NativeApp.navigate('debug');assert.equal(h.calls[1][0],'/api/stop');assert.match(h.calls[1][2],/controller=mine&scope=owned/);assert.deepEqual(h.calls[2],['page','debug']);
});
test('page replacement waits for outstanding native callbacks to finish',async()=>{
 let finish;const h=harness({request:async()=>new Promise(resolve=>finish=resolve)});
 const request=h.window.fetch('/api/state');await new Promise(r=>setImmediate(r));const navigation=h.window.NativeApp.navigate('guide');await Promise.resolve();assert.equal(h.calls.some(c=>c[0]==='page'),false);
 finish({status:200,headers:{'content-type':'application/json'},body:{active:false},binary:false});await request;await navigation;assert.deepEqual(h.calls.at(-1),['page','guide']);
});

test('large native check and export JSON text reaches Response without rebuilding or stringify while preserving values',async()=>{
 const value={name:'合成',notes:Array.from({length:6000},(_,i)=>({id:i,beat:i/3,finger:i%5+1,pitch:'C#5',detail:'synthetic '.repeat(25)})),package_base64:'A'.repeat(1024*1024)},text=JSON.stringify(value);
 const h=harness({request:async()=>({status:200,headers:{'content-type':'application/json','content-length':String(text.length)},body:text,binary:false,body_encoding:'json-text'})});
 for(const route of ['/api/software/check','/api/software/export']){
  const response=await h.window.fetch(route,{method:'POST',headers:{'X-Piano-Controller':'same-owner','Content-Type':'application/json'},body:'{"project":{}}'});
  assert.deepEqual(await response.json(),value);assert.equal(response.headers.get('content-length'),null);assert.equal(h.calls.at(-1)[4]['x-piano-json-text'],'1');assert.equal(h.calls.at(-1)[4]['x-piano-controller'],'same-owner');
 }
 assert.equal(h.jsonStringifies.length,0);
});

test('native object fallback, errors and preview-dependent routes retain their existing behavior',async()=>{
 const value={ok:false,error:'unchanged'},h=harness({request:async()=>({status:400,headers:{'content-type':'application/json'},body:value,binary:false})});
 const response=await h.window.fetch('/api/software/check',{method:'POST'});assert.equal(response.status,400);assert.deepEqual(await response.json(),value);assert.equal(h.jsonStringifies.length,1);
 const legacy=harness();await legacy.window.fetch('/api/software/convert',{method:'POST'});await legacy.window.fetch('/api/score?slot=2');
 assert.ok(legacy.calls.every(c=>c[4]['x-piano-json-text']===undefined),'convert registration and source-preview remapping remain object paths');
 const api=await legacy.window.NativeApp.ready;await api.request('/api/software/check','POST',{},false,{});assert.equal(legacy.calls.at(-1)[4]['x-piano-json-text'],undefined,'direct API callers are not opted in');
});

test('only an explicit click on the fixed Microsoft entry opens its runtime download API',async()=>{
 const h=harness();assert.equal(h.calls.length,0);const anchor=href=>({hasAttribute:()=>false,getAttribute:()=>href});let blocked=false;
 await h.docListeners.click({target:{closest:()=>anchor('https://example.com/')},preventDefault(){blocked=true}});assert.equal(blocked,true);assert.equal(h.calls.length,0);
 await h.docListeners.click({target:{closest:()=>anchor('https://developer.microsoft.com/en-us/microsoft-edge/webview2/')},preventDefault(){blocked=true}});assert.deepEqual(h.calls,[['runtime-download']]);
});

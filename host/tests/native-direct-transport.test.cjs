const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../native-transport.js'),'utf8');
function harness({direct,request,delayed=false}={}){
 const listeners={},calls=[],jsonStringifies=[],window={location:{href:'file:///C:/piano/software.html'},addEventListener:(name,f)=>listeners[name]=f},document={addEventListener(){},getElementById:()=>null},navigator={};
 const api={request:async(...args)=>{calls.push(['request',...args]);return request?request(...args):{status:200,headers:{'content-type':'application/json'},body:{ok:true,notes:[]},binary:false}},open_page:async page=>calls.push(['page',page])};
 if(direct)api.check_project=project=>{calls.push(['direct',project]);return direct(project)};
 if(!delayed)window.pywebview={api};
 vm.runInNewContext(code,{window,document,navigator,URL,URLSearchParams,Headers,Response,Blob,ArrayBuffer,Uint8Array,DOMException,atob,btoa,Error,Set,Promise,JSON:{parse:JSON.parse,stringify(value){jsonStringifies.push(value);return JSON.stringify(value)}}});
 return {window,calls,jsonStringifies,ready(){window.pywebview={api};listeners.pywebviewready()}};
}

test('ready native API receives complete original object and no faux Response/stringify',async()=>{
 const project={notes:Array.from({length:1000},(_,id)=>({id,finger:id%5+1,pitch:'C4',detail:'synthetic '.repeat(100)})),source_sha256:'a'.repeat(64)},result={ok:true,notes:[{id:0,automatic_ready:true}],automatic:{ready:true}};
 const h=harness({direct:async input=>{assert.equal(input,project);return result}});
 assert.equal(await h.window.NativeApp.checkProject(project),result);assert.equal(h.jsonStringifies.length,0);assert.equal(h.calls.length,1);assert.equal(h.calls[0][0],'direct');
});

test('legacy API fallback preserves controller/json route and server error',async()=>{
 const h=harness({request:async()=>({status:400,headers:{'content-type':'application/json'},body:{ok:false,error:'原样错误'},binary:false})});
 await assert.rejects(h.window.NativeApp.checkProject({notes:[]},{headers:{'X-Piano-Controller':'same-owner'}}),/原样错误/);
 const call=h.calls[0];assert.equal(call[1],'/api/software/check');assert.equal(call[2],'POST');assert.deepEqual(JSON.parse(call[3]),{project:{notes:[]}});assert.equal(call[5]['x-piano-controller'],'same-owner');assert.equal(call[5]['x-piano-json-text'],'1');
});

test('not-yet-ready fallback freezes input at call time and starts once readiness arrives',async()=>{
 const h=harness({delayed:true}),project={notes:[{finger:1}]};const pending=h.window.NativeApp.checkProject(project);project.notes[0].finger=5;await Promise.resolve();assert.equal(h.calls.length,0);h.ready();await pending;
 assert.equal(JSON.parse(h.calls[0][3]).project.notes[0].finger,1);
});

test('aborting before direct call never starts validation',async()=>{
 const h=harness({direct:async()=>({ok:true})}),controller=new AbortController();controller.abort();await assert.rejects(h.window.NativeApp.checkProject({}, {signal:controller.signal}),{name:'AbortError'});assert.equal(h.calls.length,0);
});

test('abort leaves actual native operation tracked until settled so navigation cannot outrun it',async()=>{
 let finish;const h=harness({direct:()=>new Promise(resolve=>finish=resolve)}),controller=new AbortController();
 const checking=h.window.NativeApp.checkProject({notes:[]},{signal:controller.signal,headers:{'X-Piano-Controller':'owned-test'}});checking.catch(()=>{});
 controller.abort();await assert.rejects(checking,{name:'AbortError'});
 const navigation=h.window.NativeApp.navigate('guide');await new Promise(r=>setImmediate(r));assert.equal(h.calls.some(c=>c[0]==='page'),false);
 assert.equal(h.calls.find(c=>c[0]==='request')[1],'/api/stop');assert.match(h.calls.find(c=>c[0]==='request')[3],/controller=owned-test/);
 finish({ok:true});await navigation;assert.deepEqual(h.calls.at(-1),['page','guide']);
});

test('native validation failure propagates and removes in-flight tracking',async()=>{
 const h=harness({direct:async()=>{throw Error('shared validator failure')}});await assert.rejects(h.window.NativeApp.checkProject({notes:[]}),/shared validator failure/);await h.window.NativeApp.navigate('guide');assert.deepEqual(h.calls.at(-1),['page','guide']);
});

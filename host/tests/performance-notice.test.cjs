const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{createRequire}=require('node:module');
const ROOT=__dirname,HOST=path.resolve(ROOT,'../../../repo/host'),CAND=fs.existsSync(path.join(ROOT,'candidate/software-pack.js'))?path.join(ROOT,'candidate'):HOST;
const Pack=require(path.join(CAND,'software-pack.js')),{fixture,score}=require(path.join(HOST,'tests/software-pack-fixture.cjs'));
const notice={version:1,basis:'detected-source-markers',features:[{kind:'arpeggio',rendering:'written-attacks',source_note_ids:['a']}],message:'基础音符已导出，琶音未展开'};
function harness(){
 const testFile=path.join(HOST,'tests/software-ui.test.cjs');let source=fs.readFileSync(testFile,'utf8').split('\ntest(')[0];
 for(const file of ['software.js','software-pack.js'])source=source.replace(`path.join(__dirname,'../${file}')`,JSON.stringify(path.join(CAND,file)));
 const module={exports:{}},ctx={require:createRequire(testFile),__dirname:path.dirname(testFile),module,console,setImmediate,setTimeout,clearTimeout,URL,URLSearchParams,Blob,Uint8Array,TextEncoder,TextDecoder,DataView,AbortController,atob,btoa};
 vm.runInNewContext(source+'\nmodule.exports={harness};',ctx);return module.exports.harness();
}
test('optional performance metadata survives package import and cache preview without changing PGL',async()=>{
 const pack=await Pack.unpack(fixture({manifest:{performance_notice:notice}}));
 assert.deepEqual(pack.source.performance_notice,notice);assert.deepEqual(Buffer.from(pack.score),score);
 const cache=new Pack.Cache({indexedDB:null,url:{createObjectURL:()=> 'blob:notice',revokeObjectURL(){}}});
 await cache.put(pack);assert.deepEqual((await cache.preview(pack.scoreHash)).performance_notice,notice);
});
test('package metadata ignores injected message and extra fields and uses fixed capability wording',async()=>{
 const malicious={...notice,message:'<script>send()</script>',html:'<img>',features:[{...notice.features[0],script:'unsafe'}]};
 assert.deepEqual((await Pack.unpack(fixture({manifest:{performance_notice:malicious}}))).source.performance_notice,notice);
});
test('malformed optional notices do not break an otherwise valid legacy score',async()=>{
 for(const value of [null,{...notice,version:2},{...notice,features:[]},{...notice,features:[{kind:'trill',rendering:'written-attacks',source_note_ids:['a']}]},{...notice,features:[{...notice.features[0],source_note_ids:['a','a']}]}]){
  const pack=await Pack.unpack(fixture({manifest:{performance_notice:value}}));assert.equal(pack.source.performance_notice,undefined);assert.deepEqual(Buffer.from(pack.score),score);
 }
});
test('actual export success appends one capability notice and preserves legacy text otherwise',async()=>{
 for(const special of [false,true]){
  const h=harness();await h.flush();h.subject.loadReview({name:'基础音符',notes:[],selection:{}});const previous=h.context.fetch;
  h.context.fetch=async(url,opts)=>url==='/api/software/export'?{ok:true,json:async()=>({bytes:144,base64:score.toString('base64'),...(special?{performance_notice:notice}:{})})}:previous(url,opts);
  await h.nodes.export.onclick();assert.equal(h.nodes.message.textContent,'已导出 144 字节曲谱'+(special?'；'+notice.message:''));
 }
});
test('actual player source hint shows optional notice and clears it for ordinary and source-free scores',async()=>{
 const h=harness();await h.flush();const pages=[{page:1,image_url:'/api/software/source/test/1'}];
 h.subject.openPlayer({notes:[],source_preview:{available:true,pages,performance_notice:notice}});
 assert.equal(h.nodes['player-source-hint'].hidden,false);assert.equal(h.nodes['player-source-hint'].textContent,notice.message);
 h.subject.openPlayer({notes:[],source_preview:{available:true,pages}});assert.equal(h.nodes['player-source-hint'].hidden,true);
 h.subject.openPlayer({notes:[]});assert.equal(h.nodes['player-source-hint'].textContent,'未关联原谱，显示曲谱中的音符与指法');
});

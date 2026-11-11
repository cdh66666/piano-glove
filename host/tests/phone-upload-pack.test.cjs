'use strict';
// 11-11 用户：手机热点必须能上传。手机页要能选到 .pgl/.pglpack（不能用 accept 过滤，安卓/苹果会把未知后缀变灰），
// .pglpack 要在手机上取出 score.pgl；电脑「送到手套」批量时每首都等手套恢复就绪，不直接报错。
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const phone=path.join(__dirname,'..','..','firmware','phone-ui');
const js=fs.readFileSync(path.join(phone,'software.js'),'utf8'),html=fs.readFileSync(path.join(phone,'software.html'),'utf8');
const src=/function pickScore\(buffer\)\{[\s\S]*?\n/.exec(js)[0];
const pickScore=new Function(src+'return pickScore;')();

function storedZip(files){
 const parts=[];for(const [name,data] of files){const n=Buffer.from(name),h=Buffer.alloc(30);h.writeUInt32LE(0x04034b50,0);h.writeUInt16LE(20,4);h.writeUInt16LE(0,8);h.writeUInt32LE(data.length,18);h.writeUInt32LE(data.length,22);h.writeUInt16LE(n.length,26);parts.push(h,n,data);}
 const b=Buffer.concat(parts);return b.buffer.slice(b.byteOffset,b.byteOffset+b.length);
}

test('pglpack: phone takes score.pgl out of the stored zip, byte for byte',()=>{
 const score=Buffer.from([0x50,0x47,0x4c,1,2,3,4,5,250]);
 const out=new Uint8Array(pickScore(storedZip([['source.json',Buffer.from('{}')],['score.pgl',score],['pages/1.png',Buffer.alloc(40,7)]])));
 assert.deepEqual([...out],[...score]);
});
test('plain .pgl passes through unchanged; a zip without score.pgl is refused in plain words',()=>{
 const raw=new Uint8Array([1,2,3]).buffer;assert.equal(pickScore(raw),raw);
 assert.throws(()=>pickScore(storedZip([['other.txt',Buffer.from('x')]])),/不是钢琴手套曲谱/);
});
test('file box does not filter by extension and the hotspot mini window offers the browser',()=>{
 const input=/<input id="pgl"[^>]*>/.exec(html)[0];assert.doesNotMatch(input,/accept=/);
 assert.match(html,/id="mini-window"/);assert.match(html,/id="mini-open"/);assert.match(js,/intent:\/\//);
});
test('desktop send waits for the glove to be ready before every score instead of failing',()=>{
 const list=fs.readFileSync(path.join(__dirname,'..','score-list.js'),'utf8'),send=/async function send\(ids\)\{[\s\S]*?\n\}/.exec(list)[0];
 assert.match(send,/for\(const id of ids\)[\s\S]*await waitGloveReady\(\)/);
 const soft=fs.readFileSync(path.join(__dirname,'..','software.js'),'utf8');
 assert.match(soft,/fresh=await sampleState\(\);\s*\/\/[^\n]*\n\s*for\(let i=0;i<10&&fresh&&!validRecovery\(fresh\)/);
});

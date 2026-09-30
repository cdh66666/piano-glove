const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {songs}=require('../delivery-demo.js');
test('reviewed excerpts retain original right-hand provenance and fit the short timeline',()=>{
  assert.equal(songs.length,3);assert.equal(new Set(songs.map(s=>s.style)).size,3);
  const source=JSON.parse(fs.readFileSync(path.join(__dirname,'../action_files/document-rhythm-excerpts.json'),'utf8')).songs;
  for(const song of songs){
    const original=source.find(s=>s.id===song.id);assert(original);assert.deepEqual(song.events,original.events);
    assert.equal(song.hand,'right');assert.equal(song.source.hand,'right');assert(song.rhythmDemo&&song.fullStroke);
    assert(song.duration_ms<=8500);assert(fs.statSync(path.join(__dirname,'..',song.scoreImage)).size>1000);
    const last={};for(const event of song.events){assert(event.finger>=1&&event.finger<=5);assert.equal(event.finger_source,'printed_on_source_pdf');assert(event.t_ms+event.duration_ms<=song.duration_ms);const beatsPerBar=song.id==='1003497'?4:2,beat=(event.source_measure-song.source.measures[0])*beatsPerBar+event.source_beat;assert(Math.abs(event.t_ms-beat*60000/song.tempo_bpm)<=1);if(last[event.finger]!=null)assert(event.t_ms>last[event.finger]);last[event.finger]=event.t_ms;}
  }
});

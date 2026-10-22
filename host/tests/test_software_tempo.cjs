'use strict';
const assert=require('node:assert/strict');
const tempo=require('../software-tempo.js');
assert.equal(tempo.percent(101.4),101);assert.equal(tempo.percent(101.6),102);
assert.equal(tempo.percent(49),50);assert.equal(tempo.percent(1001),1000);assert.equal(tempo.percent(NaN),50);
assert.deepEqual(tempo.fineWindow(100),{min:75,max:125});
assert.deepEqual(tempo.fineWindow(50),{min:50,max:100});
assert.deepEqual(tempo.fineWindow(1000),{min:950,max:1000});
assert.deepEqual(tempo.fineWindow(100,50,60),{min:50,max:60});
let value=100,input=0,change=0;
const edit=tempo.session({getValue:()=>value,setValue:n=>value=n,emitInput:()=>input++,emitChange:()=>change++});
// A drag may produce hundreds of local input samples, but one completed gesture
// emits only one change for the existing ordered tempo command queue.
for(let n=100;n<=125;n++)edit.preview(n);
assert.equal(value,125);assert.equal(input,26);assert.equal(change,0);
assert.equal(edit.commit(),true);assert.equal(change,1);assert.equal(edit.commit(),false);assert.equal(change,1);
edit.preview(126);assert.equal(value,126);edit.cancel();assert.equal(value,125);assert.equal(change,1);
edit.preview(126);edit.commit();assert.equal(value,126);assert.equal(change,2);
value=1000;edit.reset();edit.preview(1001);assert.equal(value,1000);assert.equal(edit.commit(),false);
value=50;edit.reset();edit.preview(49);assert.equal(value,50);assert.equal(edit.commit(),false);
const interaction=tempo.editingState();
assert.equal(interaction.isEditing(),false);interaction.begin('coarse-pointer');assert.equal(interaction.isEditing(),true);
interaction.begin('number');interaction.end('coarse-pointer');assert.equal(interaction.isEditing(),true);
interaction.end('number');assert.equal(interaction.isEditing(),false);
interaction.begin('fine-keyboard');interaction.clear();assert.equal(interaction.isEditing(),false);
assert.equal(tempo.isEditing(),false);assert.equal(tempo.sync(),undefined);
console.log('PASS precision tempo: integer 1% steps, bounded fine window, preview-only drag, one commit, cancel, bounds and edit ownership');

const test=require('node:test'),assert=require('node:assert/strict'),Helper=require('../software-upload.js');
class Element{
 constructor(doc){this.ownerDocument=doc;this.children=[];this.listeners={};this.dataset={};this.attrs={};this.files=[];this.value='';this.classList={add:()=>{}};this.textContent='';}
 appendChild(child){this.children.push(child);child.parentElement=this;return child;}
 setAttribute(key,value){this.attrs[key]=value;}removeAttribute(key){delete this.attrs[key];}
 addEventListener(name,fn){this.listeners[name]=fn;}fire(name){return this.listeners[name]?.({});}
 focus(){this.focused=true;}select(){this.selected=true;}
}
function fixture({copyResult=true}={}){
 const events={},doc={defaultView:{isSecureContext:false,addEventListener(name,fn){events[name]=fn;}},createElement(){return new Element(doc);},execCommand(name){assert.equal(name,'copy');return copyResult;}};
 const host=new Element(doc),input=new Element(doc);host.appendChild(input);input.setAttribute('accept','.pgl,.pglpack');
 return {input,host,events,ui:Helper.attach(input)};
}
test('native input stays directly usable and Android extension filter is removed',()=>{
 const {input,host,ui}=fixture();assert.equal(input.attrs.accept,undefined);assert.equal(input.attrs['aria-label'],'选择曲谱文件');assert.equal(input.listeners.click instanceof Function,true);assert.equal(host.children.length,2);assert.equal(ui.details.open,undefined);assert.equal(Helper.attach(input),null);
});
test('selection displays a filename as text and cancellation clears stale selection',()=>{
 const {input,ui}=fixture();input.fire('click');assert.equal(ui.getState(),'awaiting');assert.match(ui.status.textContent,/如果没有弹出/);
 input.files=[{name:'<score>.pglpack',size:2048}];input.fire('change');assert.equal(ui.getState(),'selected');assert.equal(ui.status.textContent,'已选择：<score>.pglpack · 2.0 KB');
 input.value='old';input.fire('cancel');assert.equal(input.value,'');assert.equal(ui.getState(),'cancelled');assert.match(ui.status.textContent,/已取消/);
});
test('returning without selection offers conditional guidance, never asserts picker failure',()=>{
 const {input,events,ui}=fixture();input.fire('click');events.focus();assert.equal(ui.getState(),'empty');assert.match(ui.status.textContent,/如果刚才没有弹出/);assert.doesNotMatch(ui.status.textContent,/不支持|失败/);
});
test('HTTP clipboard fallback copies only after a user click and offers manual copying when blocked',async()=>{
 for(const copied of [true,false]){const {host,ui}=fixture({copyResult:copied});const details=host.children[1].children[1],copy=details.children[3].children[0],status=details.children[4];assert.equal(ui.address.selected,undefined);await copy.fire('click');assert.equal(ui.address.selected,true);assert.match(status.textContent,copied?/地址已复制/:/请长按/);assert.equal(ui.address.value,'http://192.168.4.1/software.html');}
});

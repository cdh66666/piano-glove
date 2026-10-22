(function(root,factory){
  'use strict';
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else{root.GloveTempo=api;if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',()=>api.attach(root.document),{once:true});else api.attach(root.document);}
})(typeof globalThis==='object'?globalThis:this,function(){
  'use strict';
  let attached=null;
  function percent(value,min=50,max=1000){const n=Number(value);return Math.max(min,Math.min(max,Number.isFinite(n)?Math.round(n):min));}
  function fineWindow(value,min=50,max=1000,radius=25){
    const center=percent(value,min,max),width=Math.min(max-min,radius*2);
    const low=Math.max(min,Math.min(max-width,center-radius));
    return {min:low,max:low+width};
  }
  // Preview never emits a command. Only a completed fine adjustment commits.
  function session({getValue,setValue,emitInput,emitChange,min=50,max=1000}){
    let committed=percent(getValue(),min,max);
    return {
      preview(value){const next=percent(value,min,max);setValue(next);emitInput();return next;},
      commit(){const next=percent(getValue(),min,max);if(next===committed)return false;committed=next;emitChange();return true;},
      reset(){committed=percent(getValue(),min,max);},
      cancel(){setValue(committed);emitInput();}
    };
  }
  function editingState(){
    const sources=new Set();
    return {begin:source=>sources.add(source),end:source=>sources.delete(source),clear:()=>sources.clear(),isEditing:()=>sources.size>0};
  }
  function attach(doc){
    const main=doc.getElementById('tempo'),label=doc.getElementById('tempo-label');
    if(!main||!label||main.dataset.precisionTempo)return null;
    main.dataset.precisionTempo='1';main.step='1';main.setAttribute('aria-label','速度');
    const min=Number(main.min)||50,max=Number(main.max)||1000;
    main.closest('label')?.classList.add('tempo-setting');
    const panel=doc.createElement('section');panel.id='tempo-precision';panel.className='tempo-precision';panel.hidden=true;
    panel.setAttribute('role','region');panel.setAttribute('aria-label','速度精细调节');
    panel.innerHTML='<div class="tempo-precision-heading"><strong>速度精调</strong><output id="tempo-large-value">100%</output><button id="tempo-close" type="button" aria-label="收起速度精调">收起</button></div><div class="tempo-precision-scale"><span id="tempo-fine-min"></span><input id="tempo-fine" type="range" step="1" aria-label="速度精调，每格百分之1"><span id="tempo-fine-max"></span></div><div class="tempo-precision-actions"><button id="tempo-minus" type="button" aria-label="速度降低百分之1">−1%</button><label class="tempo-number-label"><span>速度</span><input id="tempo-number" type="number" inputmode="numeric" step="1" aria-label="输入速度百分比"><span>%</span></label><button id="tempo-plus" type="button" aria-label="速度增加百分之1">+1%</button></div><small>大条选范围，放大条逐格调节；松手生效</small>';
    doc.body.appendChild(panel);
    const find=id=>panel.querySelector('#'+id),fine=find('tempo-fine'),number=find('tempo-number'),large=find('tempo-large-value');
    number.min=String(min);number.max=String(max);
    label.tabIndex=0;label.setAttribute('role','button');label.setAttribute('aria-controls',panel.id);label.setAttribute('aria-expanded','false');label.title='点击放大，按 1% 精调';
    let forwarding=false,windowRange=fineWindow(main.value,min,max);
    const interaction=editingState();
    const EventClass=doc.defaultView.Event;
    const editor=session({min,max,getValue:()=>main.value,setValue:value=>main.value=String(value),emitInput:()=>{forwarding=true;try{main.dispatchEvent(new EventClass('input',{bubbles:true}));}finally{forwarding=false;}},emitChange:()=>main.dispatchEvent(new EventClass('change',{bubbles:true}))});
    function sync(recenter=false){
      const value=percent(main.value,min,max);
      if(recenter||value<windowRange.min||value>windowRange.max)windowRange=fineWindow(value,min,max);
      fine.min=String(windowRange.min);fine.max=String(windowRange.max);fine.value=String(value);
      find('tempo-fine-min').textContent=windowRange.min+'%';find('tempo-fine-max').textContent=windowRange.max+'%';
      large.value=value+'%';large.textContent=value+'%';
      if(doc.activeElement!==number)number.value=String(value);
      find('tempo-minus').disabled=value<=min;find('tempo-plus').disabled=value>=max;
    }
    function open(){if(panel.hidden){editor.reset();sync(true);panel.hidden=false;label.setAttribute('aria-expanded','true');}}
    function close(){panel.hidden=true;label.setAttribute('aria-expanded','false');editor.reset();interaction.clear();}
    main.addEventListener('pointerdown',()=>{interaction.begin('coarse-pointer');open();});main.addEventListener('focus',open);
    main.addEventListener('input',()=>{if(!forwarding){editor.reset();sync(true);}else sync();});
    main.addEventListener('change',()=>{editor.reset();sync();});
    label.addEventListener('click',event=>{event.preventDefault();open();});
    label.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();fine.focus();}});
    fine.addEventListener('pointerdown',()=>interaction.begin('fine-pointer'));
    fine.addEventListener('input',()=>{editor.preview(fine.value);sync();});
    fine.addEventListener('change',()=>editor.commit());
    fine.addEventListener('pointercancel',()=>{interaction.end('fine-pointer');editor.cancel();sync();});
    main.addEventListener('pointercancel',()=>interaction.end('coarse-pointer'));
    doc.addEventListener('pointerup',()=>{interaction.end('coarse-pointer');interaction.end('fine-pointer');});
    for(const [slider,source] of [[main,'coarse-keyboard'],[fine,'fine-keyboard']]){
      slider.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'].includes(event.key))interaction.begin(source);});
      slider.addEventListener('keyup',()=>interaction.end(source));slider.addEventListener('blur',()=>interaction.end(source));
    }
    function step(delta){editor.preview(Number(main.value)+delta);editor.commit();sync();}
    find('tempo-minus').addEventListener('click',()=>step(-1));find('tempo-plus').addEventListener('click',()=>step(1));
    function enterNumber(){if(number.value===''){number.value=main.value;interaction.end('number');return;}number.value=String(editor.preview(number.value));editor.commit();sync(true);interaction.end('number');}
    number.addEventListener('focus',()=>interaction.begin('number'));number.addEventListener('input',()=>interaction.begin('number'));number.addEventListener('blur',()=>interaction.end('number'));
    number.addEventListener('change',enterNumber);number.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();enterNumber();number.blur();}});
    find('tempo-close').addEventListener('click',close);
    doc.addEventListener('pointerdown',event=>{if(!panel.hidden&&!panel.contains(event.target)&&event.target!==main&&event.target!==label)close();});
    doc.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden){close();label.focus({preventScroll:true});}});
    if(doc.defaultView.MutationObserver)new doc.defaultView.MutationObserver(()=>{if(!panel.hidden)sync();}).observe(label,{childList:true,subtree:true,characterData:true});
    sync();attached={open,close,sync,panel,isEditing:()=>interaction.isEditing()};return attached;
  }
  return {percent,fineWindow,session,editingState,attach,isEditing:()=>!!attached?.isEditing(),sync:()=>attached?.sync()};
});

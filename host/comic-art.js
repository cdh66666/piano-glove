/* 漫画风原创插画：手套角色「小音」与少量装饰。纯 SVG，离线可用，不驱动设备。 */
(function(root){
'use strict';
const INK='#1E1A2E';
// mood: idle | happy | worried | sing | think
function mascot(mood='idle',label='小音'){
 const eyes={
  idle:'<ellipse cx="50" cy="66" rx="5.2" ry="7" fill="'+INK+'"/><ellipse cx="72" cy="66" rx="5.2" ry="7" fill="'+INK+'"/><circle cx="51.8" cy="63.2" r="2" fill="#fff"/><circle cx="73.8" cy="63.2" r="2" fill="#fff"/>',
  happy:'<path d="M44 67q6-8 12 0M66 67q6-8 12 0" stroke="'+INK+'" stroke-width="4" fill="none" stroke-linecap="round"/>',
  worried:'<ellipse cx="50" cy="67" rx="5" ry="6.4" fill="'+INK+'"/><ellipse cx="72" cy="67" rx="5" ry="6.4" fill="'+INK+'"/><circle cx="51.6" cy="64.6" r="1.8" fill="#fff"/><circle cx="73.6" cy="64.6" r="1.8" fill="#fff"/><path d="M42 55l13 3M80 55l-13 3" stroke="'+INK+'" stroke-width="3.4" stroke-linecap="round"/>',
  sing:'<path d="M44 66q6-7 12 0M66 66q6-7 12 0" stroke="'+INK+'" stroke-width="4" fill="none" stroke-linecap="round"/>',
  think:'<ellipse cx="50" cy="66" rx="5" ry="6.6" fill="'+INK+'"/><ellipse cx="72" cy="66" rx="5" ry="6.6" fill="'+INK+'"/><circle cx="52.4" cy="62.8" r="1.9" fill="#fff"/><circle cx="74.4" cy="62.8" r="1.9" fill="#fff"/><path d="M66 54l13-2" stroke="'+INK+'" stroke-width="3.4" stroke-linecap="round"/>'
 }[mood]||'';
 const mouth={
  idle:'<path d="M54 79q7 7 14 0" stroke="'+INK+'" stroke-width="3.6" fill="none" stroke-linecap="round"/>',
  happy:'<path d="M52 77q9 12 18 0z" fill="#FF6B6B" stroke="'+INK+'" stroke-width="3.2" stroke-linejoin="round"/>',
  worried:'<path d="M54 82q7-6 14 0" stroke="'+INK+'" stroke-width="3.6" fill="none" stroke-linecap="round"/>',
  sing:'<ellipse cx="61" cy="81" rx="6" ry="7" fill="#FF6B6B" stroke="'+INK+'" stroke-width="3.2"/>',
  think:'<path d="M55 80h12" stroke="'+INK+'" stroke-width="3.6" stroke-linecap="round"/>'
 }[mood]||'';
 const extra={
  sing:'<g class="comic-mascot-notes" fill="'+INK+'"><path d="M104 18v20a6 5 0 1 1-3-4V22l12-3v4z"/><path d="M8 36v16a5 4 0 1 1-3-3.4V36z"/></g>',
  worried:'<path class="comic-mascot-sweat" d="M92 44q5 8 0 11q-5-3 0-11z" fill="#7CC7FF" stroke="'+INK+'" stroke-width="2.4"/>',
  think:'<g class="comic-mascot-dots" fill="'+INK+'"><circle cx="100" cy="26" r="3"/><circle cx="108" cy="16" r="4"/></g>',
  happy:'<g class="comic-mascot-spark" stroke="'+INK+'" stroke-width="3" stroke-linecap="round"><path d="M104 22l6-6M108 34h8M96 14l1-8"/></g>'
 }[mood]||'';
 return '<svg class="comic-mascot comic-mascot-'+mood+'" viewBox="0 0 120 120" role="img" aria-label="'+label+'">'+
  '<g class="comic-mascot-body">'+
  '<path d="M31 64q-10-9-17-3.5t1.5 15.5l15.5 16" fill="#fff" stroke="'+INK+'" stroke-width="4.5" stroke-linejoin="round" stroke-linecap="round"/>'+
  '<path d="M30 96V50q0-9 8-9t8 9V30q0-9 8-9t8 9v-5q0-9 8-9t8 9v6q0-9 8-9t8 9V96z" fill="#fff" stroke="'+INK+'" stroke-width="4.5" stroke-linejoin="round"/>'+
  '<path d="M46 50v7M62 30v9M78 31v8" stroke="'+INK+'" stroke-width="3" stroke-linecap="round"/>'+
  '<path d="M36 47q2-3 4-1M52 27q2-3 4-1M68 22q2-3 4-1M84 28q2-3 4-1" stroke="#C9C2DA" stroke-width="2.4" fill="none" stroke-linecap="round"/>'+
  '<rect x="26" y="92" width="70" height="18" rx="6" fill="#FFC83D" stroke="'+INK+'" stroke-width="4.5"/>'+
  '<path d="M40 93v16M54 93v16M68 93v16M82 93v16" stroke="'+INK+'" stroke-width="2.6" opacity=".55"/>'+
  '<ellipse cx="41" cy="76" rx="5.5" ry="3.6" fill="#FFB3B3"/><ellipse cx="82" cy="76" rx="5.5" ry="3.6" fill="#FFB3B3"/>'+
  eyes+mouth+'</g>'+extra+'</svg>';
}
function burst(text,cls=''){
 let d='';for(let i=0;i<28;i++){const a=Math.PI*i/14,r=i%2?37:49;d+=(i?'L':'M')+(50+r*Math.cos(a)).toFixed(1)+' '+(50+r*Math.sin(a)*.72).toFixed(1);}
 return '<span class="comic-burst '+cls+'" aria-hidden="true"><svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="'+d+'z" fill="#FFC83D" stroke="'+INK+'" stroke-width="3" stroke-linejoin="round"/></svg><b>'+text+'</b></span>';
}
// Line icons in the comic ink weight (24px grid).
const paths={
 home:'<path d="M3.5 11 12 4l8.5 7"/><path d="M6 9.5V20h12V9.5"/><path d="M10 20v-5h4v5"/>',
 hand:'<path d="M7 13V7.5a1.5 1.5 0 0 1 3 0V12M10 11V5.5a1.5 1.5 0 0 1 3 0V11M13 11V6.5a1.5 1.5 0 0 1 3 0V12M16 12V9a1.5 1.5 0 0 1 3 0v5c0 4-3 7-7 7-3 0-4.5-1.4-6-4l-2.2-3.8a1.5 1.5 0 0 1 2.6-1.5L7 14"/>',
 music:'<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
 score:'<path d="M5 3.5h10l4 4V20.5H5z"/><path d="M15 3.5v4h4"/><path d="M8 12h8M8 15.5h8M8 8.5h4"/>',
 gear:'<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.6M12 18.6v2.6M21.2 12h-2.6M5.4 12H2.8M18.5 5.5l-1.8 1.8M7.3 16.7l-1.8 1.8M18.5 18.5l-1.8-1.8M7.3 7.3 5.5 5.5"/>',
 wrench:'<path d="M14.5 6.5a4 4 0 0 0 5 5l-9 9a2.1 2.1 0 0 1-3-3l9-9a4 4 0 0 1-2-2z"/><path d="M15 3.5a4 4 0 0 1 5.5 5.5L18 6.5z"/>',
 plug:'<path d="M9 3v5M15 3v5M6.5 8h11v3a5.5 5.5 0 0 1-11 0z"/><path d="M12 16.5V21"/>',
 phone:'<rect x="7" y="2.8" width="10" height="18.4" rx="2"/><path d="M11 18h2"/>',
 book:'<path d="M4 5.5C6 4.5 9 4.5 12 6c3-1.5 6-1.5 8-.5v13c-2-1-5-1-8 .5-3-1.5-6-1.5-8-.5z"/><path d="M12 6v13"/>',
 stop:'<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
 play:'<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>',
 upload:'<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v4h16v-4"/>',
 folder:'<path d="M3.5 6.5h6l2 2h9v10.5h-17z"/>',
 check:'<path d="m5 12.5 4.5 4.5L19 7.5"/>',
 spark:'<path d="M12 3v5M12 16v5M3 12h5M16 12h5M6 6l3 3M15 15l3 3M18 6l-3 3M9 15l-3 3"/>',
 help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.6 2.6 0 1 1 3.6 2.4c-.8.4-1.1 1-1.1 1.8v.6"/><circle cx="12" cy="17.2" r=".6" fill="currentColor"/>'
};
function icon(name){return '<svg class="comic-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(paths[name]||'')+'</svg>';}
root.ComicArt={mascot,burst,icon};
})(typeof window!=='undefined'?window:globalThis);

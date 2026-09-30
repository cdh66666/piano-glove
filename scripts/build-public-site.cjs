const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),dest=path.join(root,'dist');
fs.mkdirSync(dest,{recursive:true});
for(const name of ['index.html','style.css','app.js'])fs.copyFileSync(path.join(root,'site',name),path.join(dest,name));
const songs=require(path.join(root,'host','delivery-demo.js')).songs;
for(const song of songs){if(song.source.hand!=='right')throw Error('Only right-hand excerpts are allowed');const target=path.join(dest,song.scoreImage);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(path.join(root,'host',song.scoreImage),target);}
fs.writeFileSync(path.join(dest,'songs.json'),JSON.stringify({songs},null,2));
fs.writeFileSync(path.join(dest,'.nojekyll'),'');
console.log(`Built public preview with ${songs.length} right-hand excerpts`);

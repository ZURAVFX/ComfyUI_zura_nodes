import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8');
const start=source.indexOf('let registeredStudio;'),end=source.indexOf('\nasync function openDesktopAESession',start);
assert.ok(start>=0&&end>start);
const body=source.slice(start,end).replace('export async function','async function').replaceAll('import.meta.url',JSON.stringify(new URL('../web/studio.js',import.meta.url).href));
let release;const gate=new Promise(resolve=>release=resolve),navigation=[];let constructed=0;
class ArtistStudio{constructor(options={}){constructed++;this.aeSession=options.aeSession;this.container={isConnected:false,querySelector:()=>({})};this.creative={owner:this};}async open(){await gate;this.container.isConnected=true;}}
const context={ArtistStudio,URL,studioLaunchStorage:()=>({}),navigateStudioMode:async(creative,mode)=>navigation.push({owner:creative.owner,mode})};
const api=vm.runInNewContext(`(()=>{${body};return{open:openZuraStudio,initial:initialStudio,get:()=>registeredStudio,set:value=>registeredStudio=value};})()`,context);
const opening=api.open('image'),original=api.get();
assert.equal(api.initial(null),original,'Late extension setup reuses the normal workspace already opened by a launcher');
assert.equal(constructed,1);
const replacement=new ArtistStudio({aeSession:{id:'new-ae'}});api.set(replacement);release();
assert.equal(await opening,original,'An in-flight open returns the instance it actually opened');
assert.deepEqual(navigation,[{owner:original,mode:'image'}],'Late normal navigation cannot mutate the replacement AE workspace');
assert.equal(api.get(),replacement);assert.notEqual(api.initial(null),replacement,'An AE workspace is not reused as a normal instance');
console.log('Studio startup retains one normal workspace and fences async navigation from a replacement AE instance');

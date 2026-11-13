import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioDisplaySettings,displayPresetKey} from '../web/studio_display_settings.js';

const {document,window}=parseHTML('<html><head></head><body><main id="genj-studio"><span id="display-host"></span><div id="image-host" class="gs-canvas"><img id="media"></div><div id="video-host" class="gs-canvas"><video id="video"></video></div><button id="outside">Outside</button></main></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
Object.defineProperty(window,'innerWidth',{value:700,configurable:true});Object.defineProperty(window,'innerHeight',{value:500,configurable:true});
const root=document.getElementById('genj-studio'),media=document.getElementById('media'),video=document.getElementById('video');
media.getBoundingClientRect=video.getBoundingClientRect=()=>({left:40,top:80,right:440,bottom:305,width:400,height:225});
video.paused=true;video.currentTime=.16;video.duration=1;
const records=new Map(),storage={getItem:key=>records.get(key)||null,setItem:(key,value)=>records.set(key,value)};
let source={file:'images/source.exr',frameCount:9},raw=null;
const owner={mode:'image',storage,studio:{},state:{prompt:'keep me',seed:42},close(){}};
const inputOverrides={'images/source.exr':{input:'hdr',space:'acescg'}};
const presets=[
 {config:'ocio://studio-config-latest',display:'sRGB - Display',view:'Un-tone-mapped',label:'sRGB'},
 {config:'ocio://studio-config-latest',display:'sRGB - Display',view:'ACES 2.0 - SDR 100 nits (Rec.709)',label:'sRGB · ACES 2.0'},
 {config:'ocio://studio-config-v2.2.0_aces-v1.3_ocio-v2.4',display:'sRGB - Display',view:'ACES 1.0 - SDR Video',label:'sRGB · ACES 1.0'},
 {config:'ocio://studio-config-latest',display:'Display P3 - Display',view:'Raw',label:'Display P3 · Raw'},
];
const config={config:'ocio://studio-config-latest',configs:[{name:'ocio://studio-config-latest'}],display:'sRGB - Display',view:'Un-tone-mapped',displays:[{name:'sRGB - Display',views:['Un-tone-mapped']}],presets};
const calls=[],revoked=[];let serial=0,delayedInfo=null,delayedFrame=null,failFrame=false;
URL.createObjectURL=()=>`blob:menu-${++serial}`;URL.revokeObjectURL=value=>revoked.push(value);
const delivery={displayHost:document.getElementById('display-host'),inputOverrides,workspace:()=>owner,source:()=>source,
 input:()=>({input:'hdr',space:'acescg',detected:true}),sourceKey:()=>source?.file||'',raw:()=>raw,outputFor:(_mode,value)=>value,
 changeInput(){throw Error('Display settings must never change processing interpretation');},save(){throw Error('Display settings must never save generation preferences');},sync(){}};
const api={fetchApi:async(path,options={})=>{
 const call={path,options,body:options.body?JSON.parse(options.body):null};calls.push(call);
 if(path.includes('/display/config'))return {ok:true,json:async()=>config};
 if(path==='/zura/studio/display/info'){
  if(delayedInfo){const pending=delayedInfo;delayedInfo=null;return pending;}
  return {ok:true,json:async()=>({kind:'video',frame_count:9,frame_rate:{numerator:25,denominator:1}})};
 }
 if(delayedFrame){const pending=delayedFrame;delayedFrame=null;return pending;}
 if(failFrame)return {ok:false,json:async()=>({error:'Source is not mapped in this view'})};
 return {ok:true,blob:async()=>new Blob(['ocio-frame']),headers:{get:()=>null}};
}};
const flush=async()=>{await new Promise(resolve=>setTimeout(resolve,120));for(let i=0;i<5;i++)await new Promise(resolve=>setTimeout(resolve,0));};
const display=new StudioDisplaySettings(root,api,owner,delivery),menu=display.menu;
menu.mount();let focused=null;menu.element.focus=()=>{};menu.presetSelect.focus=()=>{focused=menu.presetSelect;};
const snapshot=JSON.stringify({source,raw,state:owner.state,inputOverrides});
const context=target=>{const event=new window.Event('contextmenu',{bubbles:true,cancelable:true});Object.defineProperties(event,{clientX:{value:650},clientY:{value:460}});target.dispatchEvent(event);return event;};
const frames=()=>calls.filter(call=>call.path==='/zura/studio/display/frame');
assert.equal(context(media).defaultPrevented,true);await flush();
assert.equal(menu.element.querySelectorAll('select').length,1);assert.equal(menu.element.querySelector('[data-colour-file]'),null);assert.equal(menu.element.querySelector('[data-colour-apply]'),null);assert.equal(menu.element.querySelector('[data-colour-open]'),null);
assert.equal(focused,menu.presetSelect);assert.equal(menu.presetSelect.querySelectorAll('option').length,4);
assert.equal(menu.presetSelect.value,displayPresetKey(presets[0]));assert.ok(menu.inline,'Opening the display selector applies its actual sRGB default directly');
assert.equal(frames().at(-1).body.colour_space,'acescg');assert.equal(menu.element.style.left,'388px');assert.equal(menu.element.style.top,'302px');
menu.close();display.button.getBoundingClientRect=()=>({left:20,bottom:40});await display.openMenu();await flush();assert.equal(menu.active.media,media);assert.equal(root.querySelector('.zc-display'),null,'The global View button opens the same in-viewport settings rather than a separate preview window');
menu.presetSelect.value=displayPresetKey(presets[2]);menu.presetSelect.onchange();await flush();
assert.equal(frames().at(-1).body.config,presets[2].config);assert.equal(frames().at(-1).body.view,presets[2].view);
assert.equal(menu.inline.overlay.style.width,'400px');assert.match(menu.status.textContent,/Display only/);
assert.equal(JSON.stringify({source,raw,state:owner.state,inputOverrides}),snapshot,'Changing display transforms cannot change source, masters, processing colour or generation settings');
assert.equal(calls.some(call=>/prompt|save-output|hdr\/jobs/.test(call.path)),false);
// A burst of choices submits only the final debounced tuple.
const beforeBurst=frames().length;menu.selectPreset(presets[1]);menu.selectPreset(presets[2]);menu.selectPreset(presets[3]);await flush();
assert.equal(frames().length,beforeBurst+1);assert.equal(frames().at(-1).body.view,'Raw');
// An older response that ignores abort cannot allocate or replace a later view.
let releaseFrame;delayedFrame=new Promise(resolve=>releaseFrame=resolve);menu.selectPreset(presets[1]);await flush();
menu.selectPreset(presets[2]);await flush();const latest=menu.inline.url,allocated=serial;
releaseFrame({ok:true,blob:async()=>new Blob(['stale'])});await flush();assert.equal(menu.inline.url,latest);assert.equal(serial,allocated);
menu.element.querySelector('[data-colour-reset]').click();await flush();assert.equal(frames().at(-1).body.view,'Un-tone-mapped');assert.equal(display.button.textContent,'View: sRGB');
const originalOverlay=menu.inline.url;menu.close();assert.equal(menu.element.hidden,true);assert.equal(menu.inline.url,originalOverlay,'Dismissing settings retains the viewport view');
const outside=context(document.getElementById('outside'));assert.equal(outside.defaultPrevented,false);
source={file:'images/source.mov'};display.saved.which='source';context(video);await flush();
assert.equal(frames().at(-1).body.frame,4,'Paused video time maps from verified rational cadence');
menu.close();const seekURL=menu.inline.url;video.currentTime=.28;video.dispatchEvent(new window.Event('seeking'));assert.equal(menu.inline,null);assert.ok(revoked.includes(seekURL));
video.dispatchEvent(new window.Event('seeked'));await flush();assert.equal(frames().at(-1).body.frame,7);assert.ok(menu.inline,'Paused seeking updates the chosen view after the menu closes');
video.paused=false;video.dispatchEvent(new window.Event('play'));assert.equal(menu.inline,null);
assert.match(display.button.textContent,/paused only/,'The persistent View control must not imply continuous transformed playback');
const playbackRequests=frames().length;menu.selectPreset(presets[1]);await flush();assert.equal(frames().length,playbackRequests);assert.match(menu.status.textContent,/Pause/);
video.paused=true;video.dispatchEvent(new window.Event('pause'));await flush();assert.equal(frames().length,playbackRequests+1);
// A source change fences pending metadata before it can request a frame.
source={file:'images/first.exr'};context(media);await flush();let releaseInfo;delayedInfo=new Promise(resolve=>releaseInfo=resolve);menu.selectPreset(presets[2]);await flush();
source={file:'images/second.exr'};display.sync();context(media);await flush();const afterNew=frames().length,newURL=menu.inline.url;
releaseInfo({ok:true,json:async()=>({frame_count:9,frame_rate:{numerator:25,denominator:1}})});await flush();assert.equal(frames().length,afterNew);assert.equal(menu.inline.url,newURL);
// AE metadata and frame calls keep the capability in a header, never preferences.
const aeCalls=[];owner.studio.aeBridge={source:{frameCount:1},session:{id:'a'.repeat(32),capability:'b'.repeat(64)},closed:false,
 api:{fetchApi:async(path,options)=>{aeCalls.push({path,options});return path.includes('/display-config')?{ok:true,json:async()=>config}:{ok:true,blob:async()=>new Blob(['verified-ae'])};}}};
context(media);await flush();assert.ok(menu.inline);assert.ok(aeCalls.some(call=>call.path.includes('/display-config')));
for(const call of aeCalls){assert.equal(call.options.headers['X-ComfyLink-Studio-Session'],'b'.repeat(64));assert.equal(call.path.includes('b'.repeat(64)),false);}
assert.equal(JSON.stringify([...records]).includes('b'.repeat(64)),false);
let releaseAEFrame;owner.studio.aeBridge.api.fetchApi=async()=>await new Promise(resolve=>releaseAEFrame=resolve);menu.selectPreset(presets[1]);await flush();const beforeRevocation=serial;owner.studio.aeBridge.closed=true;releaseAEFrame({ok:true,blob:async()=>new Blob(['revoked'])});await flush();assert.equal(serial,beforeRevocation,'An ended AE session cannot attach a late display frame');
owner.studio.aeBridge=undefined;raw={kind:'hdr_sequence',master:{type:'output',filename:'master.exr',subfolder:'results'},colour:{encoding:'acescg'}};display.saved.which='result';const masterBefore=JSON.stringify(raw);context(media);await flush();menu.selectPreset(presets[2]);await flush();assert.equal(JSON.stringify(raw),masterBefore);assert.equal(frames().at(-1).body.source.file.filename,'master.exr');
failFrame=true;menu.selectPreset(presets[1]);menu.close();await flush();assert.equal(menu.inline,null);assert.match(display.button.textContent,/View unavailable/,'A failed transform remains visible after dismissing settings');failFrame=false;context(media);await flush();assert.ok(menu.inline);assert.doesNotMatch(display.button.textContent,/unavailable/);
const escape=new window.Event('keydown',{bubbles:true,cancelable:true});escape.key='Escape';menu.element.dispatchEvent(escape);assert.equal(menu.element.hidden,true);assert.equal(escape.defaultPrevented,true);
display.close();assert.equal(menu.element,null);assert.equal(root.querySelector('.zc-colour-inline'),null);
console.log('Display-only presets: automatic viewport updates, debounce/races, paused seek, playback clearing, unchanged generation and scoped AE authentication passed');

import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioDisplaySettings,studioDisplaySource} from '../web/studio_display_settings.js';
import {AEFloatDisplay} from '../web/studio_ae_display.js';

const {document,window}=parseHTML('<html><head></head><body><main id="studio"><span id="display-host"></span></main></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.selected=option.value===String(value);}});
const config={config:'ocio://studio-config-latest',configs:[{name:'ocio://studio-config-latest',label:'Studio'}],
  displays:[{name:'sRGB - Display',views:['Un-tone-mapped','ACES 2.0']},{name:'P3-D65',views:['ACES 2.0']}],display:'sRGB - Display',view:'Un-tone-mapped'};
const records=new Map(),storage={getItem:key=>records.get(key)||null,setItem:(key,value)=>records.set(key,value)};
const root=document.getElementById('studio'),owner={mode:'image',storage,studio:{},close(){}};
let source={file:'images/source.png',filename:'source.png',subfolder:'images',width:64,height:64},raw=null;
const delivery={displayHost:document.getElementById('display-host'),inputOverrides:{},workspace:()=>owner,
  source:()=>source,input:()=>({space:'srgb_display',detected:true}),sourceKey:()=>source?.file||'',raw:()=>raw,outputFor:(_mode,value)=>value,sync(){}};
const calls=[],revoked=[];let serial=0,delayedFrame=null;
URL.createObjectURL=()=>`blob:display-${++serial}`;URL.revokeObjectURL=url=>revoked.push(url);
const api={fetchApi:async(path,options={})=>{
  calls.push({path,options});
  if(path.includes('/config'))return {ok:true,json:async()=>config};
  if(delayedFrame){const promise=delayedFrame;delayedFrame=null;return promise;}
  return {ok:true,headers:{get:name=>name==='X-Zura-Display-Frames'?'9':null},blob:async()=>new Blob(['verified-display'],{type:'image/png'})};
}};
const flush=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setTimeout(resolve,0));};
const display=new StudioDisplaySettings(root,api,owner,delivery);
assert.equal(display.button.textContent,'View: sRGB');
await display.open();
assert.equal(display.view.selectDisplay.value,'sRGB - Display');assert.equal(display.view.selectView.value,'Un-tone-mapped');
const first=calls.find(call=>call.path==='/zura/studio/display/frame');
assert.deepEqual(JSON.parse(first.options.body).source,{file:{filename:'source.png',subfolder:'images',type:'input'}});
assert.equal(JSON.parse(first.options.body).colour_space,'auto','Default source detection must not invent an explicit colour override');
assert.equal(display.view.slider.max,'8','Original media metadata controls the full preview range');
display.view.slider.value='7';display.view.slider.oninput();clearTimeout(display.view.timer);assert.equal(display.view.position.textContent,'8 / 9');
assert.equal(display.view.image.hidden,false);
display.view.selectDisplay.value='P3-D65';display.view.selectDisplay.onchange();await flush();
assert.equal(display.button.textContent,'View: P3-D65');
assert.equal(JSON.parse(records.get('zura-studio-display-view-v1')).display,'P3-D65');
assert.equal(calls.some(call=>/prompt|result|save-output/.test(call.path)),false,'Viewing cannot queue generation or change a master');

assert.deepEqual(studioDisplaySource({native_hdr:{asset_id:'a'.repeat(32)},file:'clipped-proxy.png'}),{asset_id:'a'.repeat(32)},'HDR marker selects the original rather than its viewing PNG');
assert.deepEqual(studioDisplaySource({native_hdr:{source_id:'a'.repeat(32),start_seconds:1.5},file:'proxy.png'}),{asset_id:'a'.repeat(32),frame_time:1.5},'A video-derived HDR image retains its selected original frame');
assert.deepEqual(studioDisplaySource({display_source:'selected-source',media_url:'/zura/paintout/media?token=other'}),{source_token:'selected-source'});
assert.equal(studioDisplaySource({file:'C:/private/frame.exr'}),null,'An absolute path is never sent to the new preview endpoint');

let release;
delayedFrame=new Promise(resolve=>release=resolve);
display.view.selectView.value='ACES 2.0';display.view.selectView.onchange();await flush();
const oldView=display.view;
display.closeViewer();source={file:'images/other.png',filename:'other.png',subfolder:'images'};
await display.open();const shown=display.view.image.src,count=serial;
release({ok:true,headers:{get:()=>null},blob:async()=>new Blob(['stale'])});await flush();
assert.equal(oldView.root,null);assert.equal(display.view.image.src,shown);assert.equal(serial,count,'A stale preview cannot allocate or show a new object URL');
assert.ok(revoked.length>=1);
source={file:'images/third.png'};display.sync();assert.equal(display.view,null,'A source switch closes the old colour preview');

const privateCalls=[],bridge={closed:false,studio:{container:root},source:{frameCount:2},session:{id:'b'.repeat(32),capability:'c'.repeat(64)},
  api:{fetchApi:async(path,options)=>{privateCalls.push({path,options});return path.includes('/display-config')?{ok:true,json:async()=>config}:{ok:true,blob:async()=>new Blob(['ae-source'])};}}};
bridge.display=new AEFloatDisplay(bridge);owner.studio.aeBridge=bridge;source={precision:{sourceBitDepth:32}};
await display.open();assert.equal(display.view,bridge.display,'AE source reuses its scoped original FLOAT viewer');
assert.equal(privateCalls.find(call=>call.path.includes('/display-frame')).options.headers['X-ComfyLink-Studio-Session'],bridge.session.capability);
assert.equal(JSON.stringify([...records]).includes(bridge.session.capability),false,'A capability never enters saved display preferences');
display.close();assert.equal(bridge.closed,false,'Closing the viewer does not leave the AE session');
assert.equal(root.querySelector('.zc-display'),null);assert.equal(root.querySelector('.zc-display-trigger'),null);
console.log('Persistent Studio View: real preview routing, sRGB default, HDR-original selection, exact range, scoped AE reuse and stale-request cleanup passed');

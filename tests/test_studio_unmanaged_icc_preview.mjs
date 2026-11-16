import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioDisplayBinding,StudioImageAreaDisplayBinding} from '../web/studio_display_binding.js';
import {StudioDisplaySettings} from '../web/studio_display_settings.js';
import {AEFloatDisplay} from '../web/studio_ae_display.js';
import {UNMANAGED_ICC_DISPLAY,createDisplayTransformStore,inverseSRGBPreviewPixels,isUnmanagedICCDisplay,verifiedICCPreviewSource} from '../web/studio_display_state.js';

const profile='a'.repeat(64),source={colour:{management:'icc',encoding:'ae_project_icc',sceneLinear:true,profileSha256:profile},
  processingInput:{conversion:'verified_icc_to_sdr8',sourceProfileSha256:profile,sourceEncoding:'scene_linear_rec709'}};
assert.equal(verifiedICCPreviewSource(source),true);
assert.equal(verifiedICCPreviewSource({...source,processingInput:{...source.processingInput,sourceProfileSha256:'b'.repeat(64)}}),false);
assert.equal(verifiedICCPreviewSource({...source,processingInput:{...source.processingInput,conversion:'raw_numeric_to_sdr8'}}),false);
const values=Uint8ClampedArray.from([99,102,105,77,0,12,255,128]);
assert.equal(inverseSRGBPreviewPixels(values),values);
assert.deepEqual([...values],[32,34,36,77,0,1,255,128],'IEC inverse acts on RGB only and preserves alpha');

const {document,window}=parseHTML('<html><body><main id="studio"><img id="source" src="/view?filename=first.png&type=input"><video id="video" src="/view?filename=source.mp4&type=input"></video></main></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},
  set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
const root=document.getElementById('studio'),media=document.getElementById('source'),video=document.getElementById('video');
Object.defineProperty(media,'naturalWidth',{value:2});Object.defineProperty(media,'naturalHeight',{value:2});
Object.defineProperty(video,'videoWidth',{value:2});Object.defineProperty(video,'videoHeight',{value:2});
Object.defineProperty(video,'paused',{value:false,configurable:true});video.currentTime=.25;
for(const element of [media,video])element.getBoundingClientRect=()=>({left:20,top:30,width:200,height:120});
const originalCreate=document.createElement.bind(document),drawn=[];let lastPixels;
document.createElement=name=>{
  const element=originalCreate(name);
  if(name==='canvas'){
    const ctx={drawImage(image){drawn.push(image);},getImageData(){return {data:Uint8ClampedArray.from([99,102,105,77,99,102,105,77,99,102,105,77,99,102,105,77])};},
      putImageData(image){lastPixels=[...image.data];}};
    element.getContext=()=>ctx;element.toBlob=callback=>callback(new Blob(['preview'],{type:'image/png'}));
  }
  return element;
};
const oldCreate=URL.createObjectURL,oldRevoke=URL.revokeObjectURL,revoked=[];
URL.createObjectURL=()=>`blob:unmanaged-${revoked.length+1}`;URL.revokeObjectURL=url=>revoked.push(url);
let state={selection:UNMANAGED_ICC_DISPLAY,revision:1};const aeBridge={source,closed:false};
const owner={studio:{aeBridge}},selected={key:'qa-frame',ae:aeBridge};
const settings={root,owner,closed:false,displayStore:{get:()=>state},currentFor:()=>selected,sync(){},status:originalCreate('output')};
const config={config:'adobe-ae://fixture',configs:[{name:'adobe-ae://fixture'}],display:'sRGB',view:'Raw',displays:[{name:'sRGB',views:['Raw','Display']}],adobePresets:[{config:'adobe-ae://fixture',display:'sRGB',view:'Raw',label:'None'}]};
const catalogue=Object.assign(Object.create(StudioDisplaySettings.prototype),{owner});
assert.equal(catalogue.presetsFor(config).some(isUnmanagedICCDisplay),true,'The option reaches the one shared toolbar and context menu catalogue.');
owner.studio.aeBridge.source={...source,processingInput:{conversion:'raw_numeric_to_sdr8'}};
assert.equal(catalogue.presetsFor(config).some(isUnmanagedICCDisplay),false,'Other AE sources do not offer this ICC-only view.');
owner.studio.aeBridge.source=source;
const boundSource={...source,processingInput:{...source.processingInput,stills:{first:{filename:'first.png',subfolder:'AE',type:'input'}}}};
owner.studio.aeBridge.source=boundSource;owner.studio.aeBridge.session={id:'qa-session'};
catalogue.delivery={workspace:()=>owner,source:()=>null,input:()=>({}),sourceKey:()=>'',raw:()=>null,outputFor:()=>null};
catalogue.saved={which:'source'};
assert.equal(catalogue.choices().original.aeModelView,true,'The main AE source receives the verified unmanaged baseline.');
owner.studio.aeBridge.source={...boundSource,colour:{encoding:'acescg',management:'ocio',sceneLinear:true}};
assert.equal(catalogue.choices().original.aeModelView,false,'An HDR source without the verified ICC SDR view remains untouched.');
owner.studio.aeBridge.source=boundSource;
assert.equal(catalogue.aeModelInputFile({filename:'first.png',subfolder:'AE',type:'input'}),true);
assert.equal(catalogue.aeModelInputFile({filename:'other.png',subfolder:'AE',type:'input'}),false);
const sdrResult={image_layers:{schemaVersion:1},ae_frame_contract:{sessionId:'qa-session'},
  preview:{filename:'preview.png',type:'output'},colour:{encoding:'srgb_display',sceneLinear:false}};
assert.equal(catalogue.aeModelViewResult(sdrResult),true);
assert.equal(catalogue.aeModelViewResult({...sdrResult,ae_frame_contract:{sessionId:'other'}}),false);
assert.equal(catalogue.aeModelViewResult({...sdrResult,preview:{filename:'master.exr',type:'output'},colour:{encoding:'acescg',sceneLinear:true}}),false,
  'An HDR EXR result must never receive the SDR inverse display baseline.');
owner.studio.aeBridge.source=source;
const flush=async(ms=20)=>{await new Promise(resolve=>setTimeout(resolve,ms));await new Promise(resolve=>setImmediate(resolve));};
const binding=new StudioDisplayBinding(settings,media);binding.refresh();await flush();
assert.equal(media.getAttribute('src'),'/view?filename=first.png&type=input');
assert.equal(root.querySelectorAll('.zc-colour-inline').length,1,'The still receives one display-only overlay.');
assert.deepEqual(lastPixels.slice(0,4),[32,34,36,77]);assert.equal(drawn[0],media);
const drawnBeforeSourceChange=drawn.length;media.setAttribute('src','/view?filename=next.png&type=input');binding.refresh();await flush();
assert.ok(drawn.length>drawnBeforeSourceChange,'Replacing an image under the same AE session refreshes its display overlay.');
state={selection:null,revision:2};binding.refresh();assert.equal(root.querySelector('.zc-colour-inline'),null);binding.close();

state={selection:null,revision:2};selected.aeModelView=true;
const resultBinding=new StudioDisplayBinding(settings,media);resultBinding.refresh();await flush();
assert.equal(root.querySelectorAll('.zc-colour-inline').length,1,'None retains the verified AE unmanaged baseline on an AE Image Edit result');
assert.deepEqual(lastPixels.slice(0,4),[32,34,36,77]);resultBinding.close();selected.aeModelView=false;

state={selection:UNMANAGED_ICC_DISPLAY,revision:3};
owner.studio.aeBridge.source=boundSource;
const area={host:{hidden:false},source:()=>({filename:'first.png',subfolder:'AE',type:'input'})},paintRoot=originalCreate('section');root.append(paintRoot);
const viewer={root:paintRoot,image:media,displaySourceURL:'/view?filename=first.png&type=input',clearColourDisplay(){this.cleared=(this.cleared||0)+1;},
  async setColourDisplayImage(url,sourceURL){this.applied={url,sourceURL,image:this.image};return true;}};
area.viewer=viewer;owner.imageArea=area;settings.aeModelInputFile=catalogue.aeModelInputFile.bind(catalogue);
const paint=new StudioImageAreaDisplayBinding(settings,area,viewer);await flush();
assert.equal(viewer.applied?.image,media,'Paint retains its actual source bitmap.');
assert.equal(viewer.applied?.sourceURL,viewer.displaySourceURL);assert.deepEqual(lastPixels.slice(0,4),[32,34,36,77]);
state={selection:null,revision:4};paint.refresh();await flush();
assert.equal(viewer.applied?.sourceURL,viewer.displaySourceURL,'None keeps the AE unmanaged baseline on the source paint canvas');
area.source=()=>({filename:'other.png',subfolder:'AE',type:'input'});paint.refresh();assert.ok(viewer.cleared>=1,'An unrelated source clears the baseline.');paint.close();

let scheduledVideoFrames=0,cancelledVideoFrame=null;
video.requestVideoFrameCallback=()=>++scheduledVideoFrames;video.cancelVideoFrameCallback=id=>cancelledVideoFrame=id;
state={selection:UNMANAGED_ICC_DISPLAY,revision:5};const playback=new StudioDisplayBinding(settings,video);playback.refresh();await flush(45);
assert.equal(video.getAttribute('src'),'/view?filename=source.mp4&type=input');assert.equal(video.currentTime,.25);
assert.equal(root.querySelectorAll('.zc-colour-inline').length,1,'Playing video uses an overlay without replacing source playback.');
assert.deepEqual(lastPixels.slice(0,4),[32,34,36,77]);assert.equal(scheduledVideoFrames,1,'Playback waits for an actual decoded video frame.');
playback.close();assert.equal(cancelledVideoFrame,1,'Closing cancels the pending preview frame.');assert.equal(root.querySelector('.zc-colour-inline'),null);
const previewStore=createDisplayTransformStore({getItem:()=>null,setItem(){}}),queries=[];
const originalBridge={closed:false,source:{...source,frameCount:1},studio:{container:root},session:{id:'a'.repeat(32),capability:'b'.repeat(64)},
  api:{fetchApi:async path=>path.includes('/display-config')?{ok:true,json:async()=>config}:{ok:true,blob:async()=>new Blob(['raw'])}}};
const originalView=new AEFloatDisplay(originalBridge,{store:previewStore,frameCount:1});await originalView.openInline(root);
previewStore.choose(UNMANAGED_ICC_DISPLAY);await flush();
assert.equal(originalView.selectView.value,'Raw','An original AE FLOAT preview uses the real Raw view for unmanaged display.');
originalView.close();
const oldBitmap=globalThis.createImageBitmap;let closedBitmaps=0;
globalThis.createImageBitmap=async()=>({width:2,height:2,close(){closedBitmaps++;}});
const localStore=createDisplayTransformStore({getItem:()=>null,setItem(){}}),local={closed:false,source:{frameCount:1},studio:{container:root}};
const resultView=new AEFloatDisplay(local,{store:localStore,frameCount:1,unmanagedICC:true,defaultAEModelView:true,
  configRequest:async()=>({ok:true,json:async()=>config}),
  frameRequest:async query=>{queries.push(query.toString());return {ok:true,blob:async()=>new Blob(['sdr-preview'])};}});
await resultView.openInline(root);assert.equal(closedBitmaps,1,'None includes only the verified AE unmanaged baseline for this result');
localStore.choose(UNMANAGED_ICC_DISPLAY);await flush();
assert.match(queries.at(-1),/view=Raw/,'Expanded SDR preview requests a real backend view.');
assert.equal(closedBitmaps,2,'The explicit AE viewer choice uses the same display-only inverse.');
assert.deepEqual(lastPixels.slice(0,4),[32,34,36,77]);resultView.close();globalThis.createImageBitmap=oldBitmap;
URL.createObjectURL=oldCreate;URL.revokeObjectURL=oldRevoke;
console.log('Verified ICC unmanaged display: exact EOTF, shared option, still/video overlays, Paint Area bitmap below mask, unchanged sources passed');

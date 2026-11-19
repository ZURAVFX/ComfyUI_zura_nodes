import assert from 'node:assert/strict';
import fs from 'node:fs';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';
import {WatermarkWorkspace} from '../web/paintout_studio/watermark_workspace.js';
import {PaintoutEditor} from '../web/paintout_studio/paintout_editor.js';
import {PaintoutMaskViewer} from '../web/paintout_studio/paintout_viewer.js';
import {PanoramaCameraWorkspace} from '../web/studio_panorama.js';
import {StudioAEBridge} from '../web/studio_comfylink.js';
import {STUDIO_MODE_ADAPTERS,studioModeAdapter,isRawNumericProcessingInput,studioProcessingInput} from '../web/studio_mode_adapters.js';

const {document,window}=parseHTML('<html><head></head><body></body></html>');
Object.assign(globalThis,{document,window,ResizeObserver:class{observe(){}disconnect(){}}});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
window.HTMLElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:512,height:320});
window.HTMLElement.prototype.pause=function(){this.paused=true;};
window.HTMLElement.prototype.load=function(){};
window.HTMLCanvasElement.prototype.getContext=()=>({setTransform(){},clearRect(){}});
const store={getItem(){return null;},setItem(){},removeItem(){}};
const asset={id:'captured-video',file:'ComfyLink/capture/source.mkv',name:'Captured shot',width:512,height:320,frames:17,fps:30000/1001,duration:17*1001/30000,preview_file:'ComfyLink/capture/display.mp4',preview_url:'/view?filename=display.mp4&type=input',preview_status:'ready'};
const media={path:'C:/comfy/input/'+asset.file,kind:'video',frames:17,width:512,height:320,fps:30000/1001,resolved_colour:'srgb_display',media_url:asset.preview_url,thumbnail_url:'/zura/paintout/frame-preview?file=source.mkv&space=auto&frame=0'};
const colour={encoding:'ae_project_icc',management:'icc',sceneLinear:true,profileSha256:'a'.repeat(64)};
const source={width:512,height:320,frameCount:17,fps:30000/1001,precision:{sampleType:'float32',sourceBitDepth:32},colour,alpha:'straight',
  manifest:{schemaVersion:1,sampleType:'float32',sourceBitDepth:32,alphaAssociation:'straight',colour,frameRate:{numerator:30000,denominator:1001},frames:Array.from({length:17},(_,index)=>({index}))},
  processingInput:{schemaVersion:1,precision:{sampleType:'uint8',sourceBitDepth:8},conversion:'raw_numeric_to_sdr8',sourceProcessingPrecision:'sdr8',samplePolicy:'clamp_round_unorm8',colourAssignment:'numeric_sdr8_code_values',sourceManifestSha256:'b'.repeat(64),sourceColour:colour,colour:{encoding:'srgb_display',sceneLinear:false},alphaAssociation:'straight',returnPolicy:'unqualified_raw_numeric',studioAsset:asset,mediaInfo:media,stills:{first:{file:'ComfyLink/capture/first.png'},last:{file:'ComfyLink/capture/last.png'}}}};
const original=JSON.stringify(source);

function maskViewer(){
  const root=document.createElement('div'),calls=[];let maskWrites=0;
  root.focus=()=>{};root.setPointerCapture=()=>{};root.hasPointerCapture=()=>false;
  const context={getImageData:()=>({data:new Uint8ClampedArray(512*320*4)}),save(){},restore(){},beginPath(){},moveTo(){},lineTo(){},stroke(){maskWrites++;},arc(){},fill(){maskWrites++;}};
  const viewer=Object.assign(Object.create(PaintoutMaskViewer.prototype),{root,width:512,height:320,cssWidth:512,cssHeight:320,frame:0,zoom:1,pan:{x:0,y:0},tool:'include',positive:[],negative:[],history:[],maskVersion:0,brushSize:24,maskCtx:context,sketchCtx:context,draw(){},onChange:event=>calls.push(event),onCommit:()=>calls.push('commit'),
    async setFrame(url,width,height,frame){this.image={};this.width=width;this.height=height;this.frame=frame;this.loadedURL=url;},async setMask(){},setGrow(){},setOpacity(){}});
  return {viewer,calls,get maskWrites(){return maskWrites;}};
}
function paintout(Workspace=PaintoutWorkspace){
  const page=document.createElement('section');page.innerHTML='<div class="zf-viewer"></div>';
  const fields=new Map(),events=[],nativeMask=maskViewer();
  const field=id=>{if(!fields.has(id)){const node=document.createElement(['colour','processing','output'].includes(id)?'select':id==='video'?'video':'div');if(id==='video'){Object.assign(node,{readyState:2,videoWidth:512,videoHeight:320});Object.defineProperty(node,'src',{get(){return this.getAttribute('src');},set(src){this.setAttribute('src',src);}});}if(id==='colour')node.innerHTML='<option value="auto">Auto</option><option value="srgb_display">sRGB</option>';if(id==='processing')node.innerHTML='<option>SDR (sRGB)</option><option>HDR (ACEScct)</option>';if(id==='output')node.innerHTML='<option>SDR video</option><option>EXR + HLG video</option>';node.pause=()=>{};fields.set(id,node);page.append(node);}return fields.get(id);};
  const w=Object.assign(Object.create(Workspace.prototype),{page,storage:store,loras:{value:()=>[],setBusy(){}},state:{source:'',mode:'targeted',anchors:[],sourceColour:'auto'},sourceInfo:null,playhead:0,modelInfo:{},busy:()=>false,$:field,url:path=>path,render(){},save(){},renderAnchors(){},changed(){},message(text){this.lastMessage=text;},requestError:error=>error.message,
    pick:async()=>{events.push('picker');return [media.path];},info:async()=>{events.push('probe');return media;}});
  const editor=Object.assign(Object.create(PaintoutEditor.prototype),{w,stage:'trim',active:false,sequence:0,previewSequence:0,maskEditVersion:0,viewer:nativeMask.viewer,
    flushManual:async()=>events.push('flush'),persist:async()=>events.push('persist'),update(){},updateControls(){},selected:()=>null,maskSegment:()=>null,authoritativePreview:async()=>{},status(text){throw Error(text);},$:(id)=>field('editor-'+id)});
  field('editor-opacity').value=45;w.editor=editor;
  return {w,events,nativeMask};
}
function creative(paint=paintout().w){
  const plain=()=>({state:{},config:{engine:'h3',fps:24},assets:{images:[]},references:[],draft:{clips:[]},save(){},render(){},syncForm(){},preview(){},showMedia(){},selectAvailability(){},setSource(info){this.source=info;},setSourceAsset(value){this.source=value;},setOwnAsset(value){this.ownAsset=value;},setImageOperation(){},clearImageResult(){},$(id){this.fields??=new Map();if(!this.fields.has(id))this.fields.set(id,{value:''});return this.fields.get(id);}});
  const c={...plain(),mode:'paintout',studio:plain(),paintout:paint,watermark:paintout(WatermarkWorkspace).w,ripple:plain(),alpha:plain(),outpaint:plain(),panorama:plain(),frames:plain(),referencesVideo:plain(),director:plain(),show(id){this.mode=id;},openHDR(){this.mode='hdr';},selectRelightEngine(){this.mode='video';this.studio.config.workflow_mode='relight';},videoComposer:{selectWorkflow(id){c.mode='video';c.studio.config.workflow_mode=id;}}};
  c.studio.hdrTool=plain();c.studio.creative=c;for(const w of [c.paintout,c.watermark,c.ripple,c.alpha,c.outpaint,c.panorama]){w.owner=c;w.studio=c.studio;}return c;
}

assert.equal(isRawNumericProcessingInput(source),true);
assert.equal(studioProcessingInput(source,'hdr'),source.processingInput,'An explicit SDR processing copy uses HDR mode’s normal uploaded-video path');
for(const mutate of [s=>s.processingInput.sourceProcessingPrecision='float32',s=>s.processingInput.colourAssignment='verified_icc_to_srgb',s=>s.processingInput.sourceColour.profileSha256='c'.repeat(64),s=>s.processingInput.precision.sourceBitDepth=16,s=>s.alpha='premultiplied']){
  const altered=JSON.parse(JSON.stringify(source));mutate(altered);assert.throws(()=>isRawNumericProcessingInput(altered),/no longer matches/);
}
for(const adapter of STUDIO_MODE_ADAPTERS){
  const c=creative();
  if(adapter.id==='paint_vfx'){await assert.rejects(adapter.acceptInput(c,source,{sessionId:'raw-session'}),/independent asset/);continue;}
  if(adapter.id==='image'){await assert.rejects(adapter.acceptInput(c,source,{sessionId:'raw-session'}),/one frame/);continue;}
  await adapter.acceptInput(c,source,{sessionId:'raw-session'});
  assert.equal(adapter.matchesInput(c,source),true,`${adapter.id} receives its real normal input`);
  assert.equal(adapter.resolveWorkspace(c).aeFrameBase,undefined,`${adapter.id} does not acquire a future raw-return constraint`);
}

for(const Workspace of [PaintoutWorkspace,WatermarkWorkspace]){
  const manual=paintout(Workspace),received=paintout(Workspace);
  assert.equal(await manual.w.pickSource('footage'),true);
  const c=creative();c[Workspace===WatermarkWorkspace?'watermark':'paintout']=received.w;received.w.owner=c;received.w.studio=c.studio;
  await studioModeAdapter(Workspace===WatermarkWorkspace?'watermark':'paintout').acceptInput(c,source,{sessionId:'raw-session'});
  assert.deepEqual(received.w.state,manual.w.state,'Prepared AE and manual source use the same normal state transition');
  assert.equal(received.w.sourceInfo,media,'Native inspection metadata is not rewritten');
  assert.deepEqual(received.events,manual.events.filter(event=>!['picker','probe'].includes(event)),'The prepared real clip skips only the picker/probe');
  assert.equal(received.w.state.source,media.path);assert.equal(received.w.state.clipTrimConfirmed,false);assert.equal(received.w.state.editorStage,'trim');
  assert.equal(received.w.$('video').getAttribute('src'),asset.preview_url,'The ordinary HTML player uses the normal browser proxy');
  assert.equal(received.w.$('video').hidden,false);assert.equal(received.w.aeFrameBase,undefined,'The held raw return does not constrain normal processing');
  await received.w.editor.confirmClipTrim();assert.equal(received.w.editor.stage,'mask');assert.equal(received.w.editor.active,true);
  assert.match(received.nativeMask.viewer.loadedURL,/space=srgb_display/);assert.ok(received.nativeMask.viewer.image,'The native editor receives its real frame');
  received.nativeMask.viewer.setTool('brush');const pointer={button:0,pointerId:1,clientX:120,clientY:90,preventDefault(){}};
  received.nativeMask.viewer.startPointer(pointer);received.nativeMask.viewer.endPointer(pointer);
  assert.equal(received.nativeMask.viewer.maskPresent,true);assert.ok(received.nativeMask.maskWrites>0,'The native brush writes the ordinary mask canvas');assert.ok(received.nativeMask.calls.some(value=>value?.kind==='paint'));assert.equal(received.nativeMask.calls.at(-1),'commit');
}
{
  const {w}=paintout(),before=structuredClone(w.state);let release;w.editor.flushManual=()=>new Promise(resolve=>release=resolve);let active=true;
  const pending=w.pickSource('footage',media,{isActive:()=>active});active=false;release();assert.equal(await pending,false);assert.deepEqual(w.state,before,'A departed workspace does not receive a late prepared source');
}
{
  const {w}=paintout(),c=creative(w);w.editor.flushManual=async()=>{throw Error('Save the mask first');};
  await assert.rejects(studioModeAdapter('paintout').acceptInput(c,source,{sessionId:'raw-session'}),/Save the mask first/);assert.equal(w.state.source,'','A failed normal source load is not accepted');
}
{
  const root=document.createElement('section');document.body.append(root);
  const make=()=>new PanoramaCameraWorkspace({root,storage:store,api:{},app:{},studio:{},fetch:async()=>({})});
  const manual=make(),received=make();manual.status=received.status={ready:true};manual.$('size').value=received.$('size').value='source';
  manual.api.fetchApi=async()=>({ok:true,json:async()=>asset});await manual.upload('source',new Blob(['fixture'],{type:'video/x-matroska'}));
  const c=creative();c.panorama=received;await studioModeAdapter('camera').acceptInput(c,source,{sessionId:'raw-session'});
  assert.deepEqual(received.state,manual.state,'Camera uses its exact ordinary upload acceptance method');
  assert.equal(received.$('result').src,asset.preview_url);assert.equal(received.$('generate').disabled,false,'Real source plus ready setup enables the normal geometry step');
  received.status={ready:false};received.render();assert.equal(received.$('generate').disabled,true,'Missing setup is not bypassed');
  manual.modelDownloads.dispose();received.modelDownloads.dispose();
}
{
  const c=creative();c.mode='video';c.studio.config.workflow_mode='swap';c.studio.config.engine='local';
  const bridge=Object.assign(Object.create(StudioAEBridge.prototype),{studio:c.studio,session:{id:'raw-session'},source,originalSource:source,loaded:new Map(),closed:false,revision:0,sourceButton:{},send:{},status:{},meta:{},request(){throw Error('Unexpected transfer request');}});c.studio.aeBridge=bridge;
  await bridge.loadSource();assert.equal(c.studio.source,asset);assert.equal(c.studio.aeFrameBase,undefined);assert.equal(c.studio.config.fps,24,'Normal model frame rate is not overwritten by future AE return timing');
  assert.equal(bridge.frameContract.frameCount,17);assert.deepEqual(bridge.frameContract.frameRate,{numerator:30000,denominator:1001});assert.equal(bridge.send.disabled,true);
  c.studio.project={edited:true};await bridge.loadSource();assert.deepEqual(c.studio.project,{edited:true},'Returning to the same real asset preserves edits');
  c.mode='paintout';await bridge.loadSource();const mask=c.paintout.state.mask='saved-mask.png';c.mode='video';await bridge.loadSource();c.mode='paintout';await bridge.loadSource();assert.equal(c.paintout.state.mask,mask,'Mode switching does not reload the same clip or remove masks');
  c.paintout.state.source='different.mkv';await bridge.loadSource();assert.equal(c.paintout.state.source,media.path,'A stale inspection record does not hide a replaced Paintout input');
  await bridge.sendResult();assert.match(bridge.status.textContent,/not qualified/);
  c.studio.source={...asset,id:'other'};c.mode='video';await bridge.loadSource();assert.equal(c.studio.source,asset,'A substituted source is replaced through the normal loader');
  c.mode='hdr';await bridge.loadSource();assert.equal(c.studio.hdrTool.ownAsset,asset);assert.equal(c.studio.hdrTool.sequenceAsset,undefined,'The 8-bit copy is not represented as native float HDR');
  c.mode='image';await bridge.loadSource();assert.match(bridge.status.textContent,/one frame/,'A video range is not silently reduced to a still');assert.equal(bridge.frameContract.frameCount,17);
}
assert.equal(JSON.stringify(source),original,'Source master, colour identity, policy and media metadata remain immutable');
for(const name of ['studio_comfylink.js','studio_ae_frame_contract.js','studio_plate_surface.js'])assert.doesNotMatch(fs.readFileSync(new URL('../web/'+name,import.meta.url),'utf8'),/studio_ae_source_presentation|aeSourcePreview|sourcePreview\.openInline/,'No replacement AE source presentation remains');
console.log('AE normal clip: strict numeric-copy authority, genuine manual loader parity, native player and brush, camera readiness, cached mode inputs, immutable source and raw-return hold passed');

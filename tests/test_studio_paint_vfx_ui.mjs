import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintVFXWorkspace,paintVfxSlots} from '../web/studio_paint_vfx.js';
import {PAINT_VFX_CAPABILITIES as caps,PAINT_VFX_ADAPTER as adapter} from '../web/studio_paint_vfx_recipes.js';
import {LTX_FRAME_VIDEO_MODELS as models} from '../web/ltx_frame_video_recipes.js';
import {studioModeAdapter} from '../web/studio_mode_adapters.js';
import {memoryStorage} from '../web/studio_storage.js';
const {document,window}=parseHTML('<html><head></head><body><main></main></body></html>');Object.assign(globalThis,{document,window});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(option=>option.selected)?.value||this.options[0]?.value||'';},set(value){for(const option of this.options)option.selected=option.value===String(value);}});
const originalCreate=document.createElement.bind(document),canvases=[];
document.createElement=(tag)=>{const element=originalCreate(tag);if(tag==='canvas'){element.draws=[];element.getContext=()=>({fillRect(){},drawImage(image){element.draws.push(image);}});element.toDataURL=()=> 'data:image/png;base64,background';element.toBlob=callback=>callback(new Blob(['opaque-frame'],{type:'image/png'}));canvases.push(element);}return element;};
class Viewer{constructor(host,events){this.events=events;this.root=document.createElement('div');host.append(this.root);this.sketchCanvas=document.createElement('canvas');this.sketchCanvas.tag='paint-only';this.maskCanvas={tag:'mask-never-export'};this.history=[];}async setFrame(url,width,height,frame){Object.assign(this,{width,height,frame,image:{tag:'background-raster'}});}async setSketch(){this.sketchPresent=true;}setOpacity(value){this.opacity=value;}setTool(value){this.tool=value;}setDrawColor(){}setBrushSize(){}resize(){}fit(){}dispose(){this.root.remove();}clear(){this.sketchPresent=false;this.events.onChange();}paint(){this.sketchPresent=true;this.events.onChange();this.events.onCommit();}}
const info=Object.fromEntries(caps.nodeTypes.map(node=>[node,{input:{required:{}}}]));
info.UNETLoader.input.required.unet_name=[[models.model]];info.CLIPLoader.input.required.clip_name=[[models.text]];info.CLIPLoader.input.required.type=[['ltxv']];info.VAELoader.input.required.vae_name=[[models.videoVae,models.audioVae]];info.LTXICLoRALoaderModelOnly.input.required.lora_name=[[adapter.file]];info.KSamplerSelect.input.required.sampler_name=[['euler_ancestral']];
let uploads=0,submitted,history={},posts=[];const storage=memoryStorage();
const owner={mode:'paint_vfx',root:document.querySelector('main'),studio:{},app:{},storage,api:{apiURL:value=>value,clientId:'fixture',async fetchApi(path){assert.equal(path,'/upload/image');return {ok:true,json:async()=>({name:'key'+(++uploads)+'.png',subfolder:'zura_paint_vfx'})};}},async fetch(path,body){posts.push([path,body]);if(path==='/object_info')return info;if(path==='/prompt'){submitted=body.prompt;return {prompt_id:'owned-vfx-job'};}if(path.startsWith('/history/'))return history;if(path==='/queue')return {queue_running:[],queue_pending:[]};return {};}};
const w=new PaintVFXWorkspace(owner,{Viewer});owner.paint_vfx=w;w.startPolling=()=>{};await w.open();assert.equal(w.viewer.tool,'draw','Entering Paint VFX is immediately drawable');assert.equal(w.$('generate').disabled,true);assert.match(w.$('readiness').textContent,/First frame/);
assert.equal(w.page.querySelector('.zvfx-workbench > .zvfx-tools').getAttribute('aria-label'),'Painting tools');
assert.equal(w.page.querySelectorAll('.zvfx-tool-group button svg').length,3,'Paint, Eraser and Pan have real icons in the left rail');
assert.equal(w.page.querySelectorAll('[data-vfx-swatch]').length,10,'Reference paint colours are directly available');
assert(w.$('background').closest('details.zvfx-background'),'Background controls have their own disclosure');
assert.equal(w.$('add-key').querySelectorAll('svg').length,1,'Frame actions use the same icon system');
assert.equal(w.page.querySelector('[data-vfx=remove-key]'),null,'Frame removal belongs to the frame card');
assert.equal(w.$('key-frame').parentElement,w.$('add-key').parentElement,'Frame selection and Add form one grouped control');
w.state.keys.push({frame:8});w.render();
const remove=w.page.querySelector('[aria-label="Remove frame 8"]');assert(remove,'An intermediate frame has a corner removal button');
await remove.onclick();assert(!w.state.keys.some(key=>key.frame===8),'Removing a frame keeps endpoint frames intact');
assert(w.state.keys.some(key=>key.frame===0)&&w.state.keys.some(key=>key.frame===w.state.frames-1));
w.page.querySelector('[data-vfx-swatch="#1976d2"]').click();assert.equal(w.state.colour,'#1976d2');assert.equal(w.$('colour').value,'#1976d2');
w.$('brush-number').value='80';w.$('brush-number').dispatchEvent(new window.Event('change'));assert.equal(w.state.brush,80);assert.equal(w.$('brush').value,'80');
w.$('brush').value='48';w.$('brush').dispatchEvent(new window.Event('input'));assert.equal(w.state.brush,48);assert.equal(w.$('brush-number').value,'48');
w.page.querySelector('[data-tool=pan]').click();assert.equal(w.viewer.tool,'pan');w.page.querySelector('[data-tool=draw]').click();
w.state.prompt='A rising smoke plume';w.$('prompt').value=w.state.prompt;w.viewer.paint();await w.flushKey();assert.equal(w.key().painted,true);assert.ok(w.key().image.file);assert.equal(w.viewer.opacity,0,'No selection tint in asset painting');
const firstKeyFile=w.key().image.file;await w.selectKey(120);w.viewer.paint();await w.flushKey();assert.equal(w.config().keys.length,2);assert.equal(w.$('generate').disabled,false);
assert.ok(canvases.filter(canvas=>canvas.draws.length).every(canvas=>canvas.draws.every(asset=>asset.tag!=='mask-never-export')),'Only background and actual sketch are flattened');
assert.ok(!storage.getItem('zura-paint-vfx-v1').includes('data:image'),'Storage contains asset refs, never full canvas PNG data');
await w.generate();assert.equal(w.job.id,'owned-vfx-job');assert.equal(submitted.guide.class_type,'LTXAddVideoICLoRAGuide');assert.deepEqual(JSON.parse(submitted.control.inputs.keys).map(key=>key.frame),[0,120]);
w.state.prompt='Later draft';assert.equal(w.job.config.prompt,'A rising smoke plume','Submitted generation owns an immutable key/prompt snapshot');
history={'owned-vfx-job':{status:{completed:true},outputs:{save:{images:[{filename:'effect.mp4',subfolder:'zura/paint_vfx',type:'output'}]}}}};await w.poll();assert.equal(w.items.length,1);assert.equal(w.review,true);assert.equal(w.$('download').hidden,false);
const out=studioModeAdapter('paint_vfx').getSelectedOutput(owner);assert.equal(out.width,512);assert.equal(out.frameCount,121);assert.equal(out.fps,24);assert.equal(out.colour.encoding,'srgb_display');
await assert.rejects(studioModeAdapter('paint_vfx').acceptInput(owner,{frameCount:121,width:512,height:512}),/independent asset/);
w.$('edit').click();w.viewer.clear();await w.flushKey();assert.equal(w.config().keys.length,1);assert.equal(w.$('generate').disabled,true,'Clearing a required key invalidates generation');
w.viewer.paint();await w.flushKey();w.state.background='#444444';w.invalidateControls();assert.ok(w.state.keys.every(key=>!key.image));await w.generate();assert.ok(w.state.keys.every(key=>key.image),'All painted keys rebuild after a background change');
assert.notEqual(w.state.keys.find(key=>key.frame===0).image.file,firstKeyFile);
w.job=null;owner.studio.aeBridge={closed:false};const retainedBridge=owner.studio.aeBridge;await w.generate();assert.equal(posts.filter(([path])=>path==='/prompt').length,3,'A stable AE connection does not block independent painted VFX');assert.equal(owner.studio.aeBridge,retainedBridge,'Generating VFX retains the AE connection');assert.equal(w.job.config.ae_frame_contract,undefined,'The generated asset keeps its own dimensions and duration');
assert.deepEqual(paintVfxSlots(17),[0,1,9,16]);w.close();await new Promise(resolve=>setImmediate(resolve));
console.log('Paint VFX UI: draw, asset-only persistence, first/last controls, owned generation, result fidelity, clear/rebuild and AE safeguards pass.');

const {VideoComposer,VIDEO_WORKFLOWS}=await import('../web/studio_composer.js');
assert.ok(VIDEO_WORKFLOWS.some(([id])=>id==='paint_vfx'));let navigated;
VideoComposer.prototype.selectWorkflow.call({studio:{},workspace:{show:value=>navigated=value}},'paint_vfx');assert.equal(navigated,'paint_vfx','Create a shot picker opens the independent workspace');

// Actual controller deferred uploads/preparation must never cross workspace ownership.
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const begin=async()=>{delete owner.studio.aeBridge;delete owner.studio.aeSession;owner.mode='paint_vfx';w.job=null;w.pendingSubmission=null;w.preparing=false;w.submitting=false;await w.open();w.state.prompt='A white steam plume';w.$('prompt').value=w.state.prompt;};
const promptCount=()=>posts.filter(([path])=>path==='/prompt').length;
const originalUpload=w.upload.bind(w),originalFlush=w.flushKey.bind(w);
for(const change of ['close','mode','ae','ae_pending','revision']){
  await begin();const transfer=deferred(),started=deferred(),prior=w.state.backgroundImage;
  w.upload=async()=>{started.resolve();return transfer.promise;};
  const pending=w.importBackground(new File(['png'],'background.png',{type:'image/png'}));await started.promise;
  if(change==='close')w.close();if(change==='mode'){w.deactivate();owner.mode='image';owner.mode='paint_vfx';await w.open();}if(change==='ae')owner.studio.aeBridge={closed:false,source:{id:'new-ae'}};if(change==='ae_pending')owner.studio.aeSession={sessionId:'pending-ae'};if(change==='revision')w.revision++;
  transfer.resolve({filename:'late-background.png',file:'late-background.png'});await pending;
  assert.equal(w.state.backgroundImage,prior,`Late background cannot attach after ${change}`);w.upload=originalUpload;
}
for(const change of ['close','mode','ae','ae_pending','revision']){
  await begin();const preparation=deferred(),started=deferred(),beforePrompts=promptCount();
  w.flushKey=()=>{started.resolve();return preparation.promise;};const pending=w.generate();await started.promise;
  if(change==='close')w.close();if(change==='mode'){w.deactivate();owner.mode='image';}if(change==='ae')owner.studio.aeBridge={closed:false,source:{id:'handoff'}};if(change==='ae_pending')owner.studio.aeSession={sessionId:'pending-ae'};if(change==='revision')w.revision++;
  preparation.resolve();await pending;await new Promise(resolve=>setImmediate(resolve));w.flushKey=originalFlush;
  assert.equal(promptCount(),beforePrompts,`No prompt submission after preparation crosses ${change}`);
}
// The shared submitter itself awaits AE preparation. Recheck at final admission,
// including a synchronous navigation callback during pending-job UI setup.
await begin();const beforeAdmission=promptCount();w.startPolling=()=>{w.deactivate();owner.mode='image';};await w.generate();
assert.equal(promptCount(),beforeAdmission);assert.equal(w.pendingSubmission,null,'A final admission rejection clears its provisional pending record');w.startPolling=()=>{};
await begin();const {cancelOwnedJob}=await import('../web/studio_owned_jobs.js');w.job={id:'cancel-vfx',config:w.config(),started:Date.now()};await cancelOwnedJob(w);
assert.ok(posts.some(([path,body])=>path==='/queue'&&body?.delete?.includes('cancel-vfx')),'Shared cancellation uses the scoped job ID and the real progress control');
w.close();await new Promise(resolve=>setImmediate(resolve));
console.log('Paint VFX deferred admission: close, mode roundtrip, AE handoff and revision fence uploads/preparation; final queue admission and cancellation pass.');

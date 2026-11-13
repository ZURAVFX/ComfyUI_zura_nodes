import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';
import {StudioModelDownloads} from '../web/studio_model_download.js';
import {execFileSync} from 'node:child_process';
let PlateWorkspace;
if(process.env.REMOVE_FLOW_BASELINE==='1'){
  const oldSurface=execFileSync('git',['show','HEAD:web/studio_plate_surface.js'],{encoding:'utf8'}).replaceAll('import.meta.url',JSON.stringify(new URL('../web/studio_plate_surface.js',import.meta.url).href));
  const surfaceURL='data:text/javascript;base64,'+Buffer.from(oldSurface).toString('base64');
  const oldPlate=execFileSync('git',['show','HEAD:web/studio_plate.js'],{encoding:'utf8'}).replace(/from ['\"]\.\/([^'\"]+)['\"]/g,(_,file)=>'from '+JSON.stringify(file==='studio_plate_surface.js'?surfaceURL:new URL('../web/'+file,import.meta.url).href));
  ({PlateWorkspace}=await import('data:text/javascript;base64,'+Buffer.from(oldPlate).toString('base64')));
}else ({PlateWorkspace}=await import('../web/studio_plate.js'));
import {buildPaintoutGraph,PAINTOUT_MODELS} from '../web/paintout_studio/paintout_recipes.js';
import {FRAME_EDIT_MODELS,buildFrameEditGraph} from '../web/paintout_studio/paintout_frame_recipes.js';

// The real workspace, editor and rebuilt surface run against deterministic media
// and HTTP fixtures. No model, GPU, server or saved user workflow is touched.
const {document,window}=parseHTML('<html><head></head><body><main id="genj-studio" data-workspace="paintout"><div class="gs-workspace"></div></main></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(v){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(v));}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(v){this.toggleAttribute('checked',!!v);}});
window.HTMLElement.prototype.pause=()=>{};window.HTMLElement.prototype.load=()=>{};window.HTMLElement.prototype.scrollIntoView=()=>{};
window.HTMLElement.prototype.getBoundingClientRect=()=>({left:0,top:0,right:512,bottom:288,width:512,height:288});
window.HTMLInputElement.prototype.checkValidity=function(){return this.value!==''&&Number.isFinite(Number(this.value));};
window.HTMLCanvasElement.prototype.toDataURL=()=> 'data:image/png;base64,fixture';
window.HTMLCanvasElement.prototype.getContext=function(){if(this._fixtureContext)return this._fixtureContext;const context={canvas:this,_fixtureMask:false,getImageData(){return {data:new Uint8ClampedArray(512*288*4).fill(this._fixtureMask?255:0)};},fillRect(){this._fixtureMask=['white','#fff','#ffffff'].includes(this.fillStyle);},drawImage(image){this._fixtureMask=/mask|blob:/.test(image.src||'');},clearRect(){this._fixtureMask=false;},createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),measureText:()=>({width:20})};return this._fixtureContext=new Proxy(context,{get:(o,k)=>k in o?o[k]:()=>{}});};
class FixtureImage{constructor(){this.width=512;this.height=288;}set src(value){this._src=value;queueMicrotask(()=>this.onload?.());}get src(){return this._src;}}
const stored={};const storage={getItem:k=>stored[k]??null,setItem:(k,v)=>stored[k]=String(v),removeItem:k=>delete stored[k]};
Object.assign(globalThis,{document,window,innerWidth:1396,innerHeight:1046,Image:FixtureImage,Event:window.Event,ResizeObserver:class{observe(){}disconnect(){}},localStorage:storage});
const source='C:/fixtures/removal-shot.mp4',calls=[],jobs=new Map(),info={};
let picked=[source],nextJob=0;
const doc={id:'fixture-project',revision:1,data:{},mask_revision:null,mask_history:[],mask_coverage:[]};
for(const config of [{source,mask:'C:/fixtures/mask.mp4',anchors:[{file:'C:/fixtures/frame.exr',frame:0}],mode:'targeted'}, {source,mode:'full'}]){
  for(const node of Object.values(buildPaintoutGraph(config)))info[node.class_type]??={input:{required:{},optional:{}}};
}
for(const type of ['ZuraPaintoutColourCheck','ZuraPaintoutEditorCrop','ZuraPaintoutMaskSource','ZuraPaintoutFrameCrop','ZuraPaintoutFrameComposite','UNETLoader','CLIPLoader','VAELoader','CLIPTextEncode','ReferenceMultiLatent','KSampler','VAEDecode','TextGenerate','ModelSamplingFlux','ConditioningZeroOut','BatchImagesNode','ResizeAndPadImage','SAM3_Detect','SAM3_VideoTrack'])info[type]??={input:{required:{},optional:{}}};
for(const [type,key,values] of [['UNETLoader','unet_name',[PAINTOUT_MODELS.model,FRAME_EDIT_MODELS.model]],['CLIPLoader','clip_name',[PAINTOUT_MODELS.text,FRAME_EDIT_MODELS.text,FRAME_EDIT_MODELS.upsampler]],['VAELoader','vae_name',[PAINTOUT_MODELS.videoVae,PAINTOUT_MODELS.audioVae,FRAME_EDIT_MODELS.vae]],['LoraLoaderModelOnly','lora_name',[PAINTOUT_MODELS.targetedLora]],['LTXICLoRALoaderModelOnly','lora_name',[PAINTOUT_MODELS.fullLora]],['KSampler','scheduler',['linear_quadratic']]]){info[type]??={input:{required:{},optional:{}}};info[type].input.required[key]=[values];}
info.ZuraPaintoutFrameCrop.input.optional.base_file=['STRING',{}];
info.CLIPLoader.input.required.type=[['flux3']];info.CheckpointLoaderSimple={input:{required:{ckpt_name:[['sam3.1_multiplex_fp16.safetensors']]}}};
info.LTXAddVideoICLoRAGuideAdvanced.input.optional.use_streaming=['BOOLEAN',{}];
const api={clientId:'fixture',apiURL:p=>p,addEventListener(){},removeEventListener(){},fetchApi:async(path,options)=>{calls.push({path,options});return {ok:true,status:200,json:async()=>({}),blob:async()=>new Blob(['fixture'],{type:'image/png'})};}};
const owner={root:document.querySelector('#genj-studio'),studio:{close(){}},api,app:{},storage,mode:'paintout',videoComposer:{syncWorkflow(){}},rippleImage:{request:null,importing:false},items:[],selectedImage:-1,references:[],models:[],
  $(id){return document.querySelector('#zc-'+id)||{value:'',disabled:false};},show(mode){this.mode=mode;},
  async fetch(path,body){
    calls.push({path,body});
    if(path==='/object_info')return info;
    if(path==='/zura/paintout/pick')return {paths:picked};
    if(path.startsWith('/zura/paintout/info'))return {path:source,name:'removal-shot.mp4',kind:'video',frames:9,width:512,height:288,fps:24,resolved_colour:'srgb_display'};
    if(path==='/zura/paintout/editor/project'){if(body?.data){doc.data=structuredClone(body.data);doc.revision++;}return structuredClone(doc);}
    if(path==='/zura/paintout/model-downloads')return {models:[]};
    if(path==='/prompt'){const id='fixture-'+(++nextJob);jobs.set(id,{status:{completed:false,status_str:'running'},outputs:{}});return {prompt_id:id};}
    if(path.startsWith('/history/')){const id=path.slice('/history/'.length);return jobs.has(id)?{[id]:jobs.get(id)}:{};}
    if(path==='/queue')return {queue_running:[...jobs].filter(([,j])=>!j.status.completed).map(([id])=>[0,id]),queue_pending:[]};
    if(path==='/interrupt')return {};
    if(path==='/zura/studio/loras/validate')return {loras:body?.loras||[]};
    throw Error('Unexpected fixture request: '+path);
  }};
const ui=new PaintoutWorkspace(owner,{paintoutOnly:true});owner.paintout=ui;ui.modelInfo=info;
const plate=new PlateWorkspace(owner);owner.plate=plate;plate.attach(ui);
const editor=ui.editor,surface=plate.surface;
const visible=node=>!!node?.isConnected&&!node.closest('[hidden],.zplate-legacy');
const settle=async()=>{for(let i=0;i<50;i++){await new Promise(resolve=>setTimeout(resolve,0));if(!editor.frameLoading&&!editor.loadingProject&&!editor.saving&&!editor.manualSaving)break;}};
try{
  await ui.$('model-setup').onclick();await settle();
  assert.equal(ui.modelDownloads.root.open,true,'Set up models opens the existing catalogue');
  assert.ok(visible(ui.modelDownloads.root),'Model setup must not remain in the hidden legacy heading');
  assert.equal(calls.filter(call=>call.path==='/zura/paintout/model-downloads'&&call.body).length,0,'Opening setup never starts a model download');
  ui.modelDownloads.close();
  const originalRunner=plate.ensureRunner,panel=document.createElement('details'),setupRequests=[];
  ui.page.querySelector('.zf-heading').append(panel);
  const downloads=new StudioModelDownloads(panel,async(path,body)=>{setupRequests.push({path,body});return {models:[]};},()=>{});
  const runner={modelDownloads:downloads,checkModels:async()=>downloads.setContext({route:'ltx_ripple',files:[],missingNodes:[]})};
  plate.action='paint';plate.ensureRunner=()=>runner;
  await ui.$('model-setup').onclick();
  assert.ok(visible(panel),'Paint model setup must leave its hidden runner workspace');assert.equal(panel.open,true);
  assert.equal(downloads.select.value,'__workflow__');assert.equal(setupRequests.some(request=>request.body),false,'Paint setup only inspects installed models');
  plate.action='remove';plate.ensureRunner=originalRunner;plate.syncControls();panel.open=false;
  await ui.pickSource('footage');await settle();
  assert.equal(editor.stage,'trim');assert.equal(ui.state.clipTrimConfirmed,false);
  assert.ok(visible(editor.nav),'Remove stage navigation must remain in the visible rebuilt surface');
  assert.ok(visible(surface.$('trim')));assert.equal(surface.$('trim').textContent,'Use clip');
  await surface.$('trim').onclick();await settle();
  assert.equal(editor.stage,'mask');assert.equal(ui.state.clipTrimConfirmed,true);
  assert.ok(visible(editor.$('track')),'Track must be reachable after confirming the clip');
  assert.equal(editor.$('track').disabled,true,'An empty selection cannot queue tracking');
  assert.equal(visible(surface.$('edit')),false,'Remove must not offer a shortcut which bypasses masking');
  assert.equal(visible(surface.$('run')),false,'Video generation stays at the Render step');
  assert.ok(visible(editor.guideActions),'Next-step actions cannot remain under hidden legacy navigation');
  editor.viewer.maskPresent=true;editor.viewer.maskCtx._fixtureMask=true;editor.viewer.frame=0;editor.selectionDirty=false;editor.subjectChanged=false;editor.updateControls();
  assert.equal(editor.$('track').disabled,false);
  await editor.runMask(false);assert.equal(editor.toolJob?.kind,'mask');assert.ok(visible(surface.$('stop')),'Mask jobs can be cancelled from the visible surface');
  const maskJob=editor.toolJob.id;
  doc.mask_revision=1;doc.mask_history=[{revision:1,start_frame:0,frame_count:9}];doc.mask_coverage=Array.from({length:9},(_,i)=>i);doc.mask_segments=[{id:'mask-one',start:0,end:8,tracked:true}];
  jobs.set(maskJob,{status:{completed:true,status_str:'success'},outputs:{save:{zura_mask:[{project:doc.id,revision:1,segment_id:'mask-one'}]}}});
  await editor.poll();await settle();
  assert.equal(editor.$('continue').disabled,false);assert.ok(visible(editor.$('continue')),'The completed mask exposes Next: clean frames');
  await editor.$('continue').onclick();await settle();assert.equal(editor.stage,'clean');
  assert.ok(visible(editor.frameActions),'Clean-frame actions must leave the hidden legacy composer');
  assert.ok(visible(editor.$('clean')),'Generate clean frame must be visible');
  assert.equal(ui.state.anchors.length,1,'Entering Clean frames creates a selected source-frame card');assert.equal(ui.state.anchors[0].frame,0);
  assert.equal(editor.$('clean').disabled,false);
  editor.createFrame(0);await settle();
  editor.viewer.maskPresent=true;editor.viewer.maskCtx._fixtureMask=true;editor.viewer.frame=0;editor.updateControls();
  surface.$('prompt').value='Remove only the bollard';surface.$('prompt').oninput();
  assert.equal(editor.$('instruction').value,'Remove only the bollard','The visible prompt controls the clean-frame instruction');
  assert.equal(ui.$('prompt').value,'Remove only the bollard','The removal instruction carries forward to the video render');
  assert.equal(editor.$('clean').disabled,false);await editor.cleanFrame();
  assert.equal(editor.toolJob?.kind,'frame',editor.$('status').textContent);const frameJob=editor.toolJob.id;
  jobs.set(frameJob,{status:{completed:true,status_str:'success'},outputs:{save:{zura_frame:[{file:'C:/fixtures/clean.exr',png_file:'C:/fixtures/clean.png',frame:0,colour_space:'srgb_display',layer_mask:'data:image/png;base64,fixture'}]}}});
  await editor.poll();await settle();
  assert.equal(ui.state.anchors[0].status,'accepted');assert.equal(editor.$('render-next').disabled,false);
  assert.ok(visible(editor.$('render-next')),'A completed clean frame exposes Review & render');
  await editor.$('render-next').onclick();await settle();assert.equal(editor.stage,'render');
  assert.equal(surface.$('prompt').value,'Remove only the bollard','Review and render keeps the accepted clean-frame instruction');
  assert.ok(visible(editor.maskSummary),'Render includes a reachable mask summary/review action');
  assert.ok(visible(surface.$('run')));assert.equal(surface.$('run').disabled,false);
  surface.$('prompt').value='Preserve the original camera movement';surface.$('prompt').oninput();assert.equal(ui.$('prompt').value,'Preserve the original camera movement');
  await surface.$('run').onclick();assert.ok(ui.job,'The visible render action reaches the native video controller: '+JSON.stringify({message:ui.$('message').textContent,validation:ui.validationError,setup:ui.$('setup').textContent}));
  assert.equal(calls.filter(call=>call.path==='/prompt').length,3,'Exactly one tracking, one frame edit and one video request');
  const queued=ui.job;ui.job=null;ui.stopPolling();
  await editor.setStage('clean');await settle();
  const anchors=ui.state.anchors;
  plate.action='paint';plate.syncControls();assert.equal(visible(editor.nav),false);
  ui.state.mask='';ui.state.maskProject=null;ui.state.maskRevision=null;doc.mask_revision=null;editor.document.mask_revision=null;
  await plate.select('remove');await settle();assert.equal(editor.stage,'mask','Switching from Paint without a tracked removal mask returns to selection');
  assert.equal(ui.state.anchors,anchors,'Switching operations keeps accepted edited frames');assert.ok(visible(editor.$('track')));
  ui.job=queued;ui.render();assert.equal(surface.$('source').disabled,true);assert.equal(surface.$('trim').disabled,true);
  console.log('Remove flow: visible source/trim/mask/track/clean/render controls, exact request sequence, cancellation access, prompt routing and Paint-to-Remove recovery passed');
}finally{ui.close();clearTimeout(editor.saveTimer);clearTimeout(editor.autoPreviewTimer);}

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {CreativeWorkspace} from '../web/studio_create.js';
import {IMAGE_MODELS,buildImageGraph,imageAvailability} from '../web/image_recipes.js';
import {ContentDetection} from '../web/studio_content.js';
import {ClipTrimmer} from '../web/studio_trim.js';
import {clipLength,recoverClipLength} from '../web/studio_length.js';
import {stageProgress} from '../web/studio_progress.js';
import {OpeningLoraControl} from '../web/studio_opening_loras.js';
import {installStudioRestartNavigation} from '../web/studio_restart.js';

const {document,window}=parseHTML('<html><body></body></html>');
// This DOM fixture checks navigation and state, not canvas pixels.
class ResizeObserver {observe(){} disconnect(){}}
window.HTMLElement.prototype.getBoundingClientRect=()=>({x:0,y:0,left:0,top:0,width:960,height:540,right:960,bottom:540});
window.HTMLCanvasElement.prototype.getContext=()=>({setTransform(){},clearRect(){}});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(v){for(const o of this.querySelectorAll('option'))o.removeAttribute('selected');this.querySelectorAll('option').forEach(o=>{if(o.value===String(v))o.setAttribute('selected','');});}});
Object.defineProperty(window.HTMLSelectElement.prototype,'selectedOptions',{configurable:true,get(){return [...this.querySelectorAll('option')].filter(o=>o.selected);}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(v){v?this.setAttribute('checked',''):this.removeAttribute('checked');}});
for(const method of ['pause','play','load'])window.HTMLElement.prototype[method]=()=>{};
let storage={};const localStorage={getItem:k=>storage[k]||null,setItem:(k,v)=>storage[k]=v,removeItem:k=>delete storage[k]};
Object.assign(globalThis,{document,window,localStorage,ResizeObserver,createImageBitmap:async()=>({width:1024,height:1024,close(){}})});
{
  const host=document.createElement('div'); document.body.append(host);
  const state={config:{opening_model:'klein9b',opening_loras:[],custom_loras:[]},lookMode:'build',loraCatalog:[{name:'portrait.safetensors',usable:true,metadata_family:'flux2_klein9b'}],directViewport:()=>false,headSwap:()=>false,readConfig(){return this.config;},perform(fn){return fn(0);},render(){},resetEpoch:0};
  const control=new OpeningLoraControl(state,host);control.sync('image');
  assert.equal(control.el.hidden,false,'Generated starting images offer their own LoRAs');
  const picker=control.el.querySelector('[data-picker]');picker.value='portrait.safetensors';control.el.querySelector('[data-add]').click();
  assert.equal(state.config.opening_loras[0].name,'portrait.safetensors');
  assert.deepEqual(state.config.custom_loras,[],'Image LoRAs do not affect video LoRAs');
  control.sync('video');assert.equal(control.el.hidden,true,'Image LoRA control stays out of video generation');
  state.lookMode='ready';control.sync('image');assert.equal(control.el.hidden,true,'No image LoRA is offered for a supplied frame');
  host.remove();
}
const info={};
for(const m of IMAGE_MODELS)for(const n of Object.values(buildImageGraph({model:m.id,prompt:'test',references:m.minReferences?[{file:'source.png'}]:[]})))info[n.class_type]={input:{required:{}}};
info.UNETLoader.input.required.unet_name=[IMAGE_MODELS.map(m=>m.model)];info.CLIPLoader.input.required={clip_name:[IMAGE_MODELS.flatMap(m=>[m.text,m.upsampler].filter(Boolean))],type:[IMAGE_MODELS.map(m=>m.type)]};info.VAELoader.input.required.vae_name=[IMAGE_MODELS.map(m=>m.vae)];info.LoraLoaderModelOnly.input.required.lora_name=[IMAGE_MODELS.map(m=>m.lora).filter(Boolean)];info.LoraLoaderBypassModelOnly.input.required.lora_name=[IMAGE_MODELS.map(m=>m.lora).filter(Boolean)];
assert.ok(imageAvailability(info).every(m=>m.ready));
assert.throws(()=>buildImageGraph({prompt:' '}),/Describe/);
assert.throws(()=>buildImageGraph({prompt:'test',seed:NaN}),/Seed/);
assert.throws(()=>buildImageGraph({prompt:'test',shape:'huge'}),/Choose/);
const missing=structuredClone(info);missing.UNETLoader.input.required.unet_name=[[]];assert.ok(imageAvailability(missing).filter(m=>!m.provider).every(m=>!m.ready));
assert.ok(imageAvailability(missing).filter(m=>m.provider).every(m=>m.ready),'Browser models do not require local UNET files');
info.ReferenceMultiLatent={};info.LoadImage={};
const calls=[];let history={},queue={queue_running:[],queue_pending:[]},reject=false;
const apiEvents=new Map();
const api={apiURL:p=>p,addEventListener(name,handler){const previous=apiEvents.get(name);apiEvents.set(name,event=>{previous?.(event);handler(event);});},fetchApi:async(path,options)=>{if(path==='/upload/image'){calls.push({path});return {ok:true,json:async()=>({name:'ref-'+calls.length+'.png',subfolder:'zura_images/references'})};}const body=options?.body?JSON.parse(options.body):undefined;calls.push({path,body});if(path.startsWith('/object_info/')){const name=path.split('/').at(-1);return {ok:true,json:async()=>({[name]:info[name]})};}if(path==='/prompt'){if(reject)return {ok:false,status:400,json:async()=>({error:{message:'Model failed validation'}})};queue.queue_pending=[[0,'own-run']];return {ok:true,json:async()=>({prompt_id:'own-run'})};}if(path.startsWith('/history/'))return {ok:true,json:async()=>history};if(path==='/queue'&&!body)return {ok:true,json:async()=>queue};return {ok:true,json:async()=>({})};}};
const app={};
const context={installStudioRestartNavigation,document,window,localStorage,api,app,CreativeWorkspace,ContentDetection,ClipTrimmer,clipLength,recoverClipLength,stageProgress,setTimeout,clearTimeout,setInterval,clearInterval,crypto:globalThis.crypto,URLSearchParams,AbortController,FormData};
vm.createContext(context);
const source=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'').split('app.registerExtension({')[0];
vm.runInContext(source+'\nthis.Studio=ArtistStudio;',context);
const studio=new context.Studio(),ui=studio.creative;
assert.equal(studio.$('working').parentElement,studio.container.querySelector('.gs-main'),'Progress is outside the video preview');
assert.equal(studio.$('live-preview').parentElement,studio.$('canvas'),'Live image keeps the full canvas');
assert.equal(ui.$('progress').closest('.zc-image-scroll'),null,'Image progress never covers the comparison or result');
{
  const probe=Object.create(context.Studio.prototype),elements={models:{classList:{toggle(){}}},'model-checklist':{}};
  Object.assign(probe,{config:{engine:'h3',workflow_mode:'swap',opening_model:'flux3',delivery_mode:'base',edit_area:'mask'},lookMode:'build',project:null,
    modelStatus:{engine_ready:{h3:true},model_files:{h3:[{folder:'diffusion_models',filename:'video.safetensors',ready:true}]},missing_h3_nodes:[],opening_models:{flux3:{ready:false,model_files:[{folder:'diffusion_models',filename:'flux3-image-klein-int8-convrot.safetensors',ready:false}],missing_nodes:['ImageNode']}}},
    modelDownloads:{setContext(value){this.context=value;}},$:id=>elements[id],openjutsu:()=>false,headSwap:()=>false,directViewport:()=>false});
  probe.updateModelStatus();assert.deepEqual(Array.from(probe.modelDownloads.context.files,f=>f.filename),['flux3-image-klein-int8-convrot.safetensors','video.safetensors']);
  assert.deepEqual(Array.from(probe.modelDownloads.context.missingNodes),['ImageNode']);
  probe.lookMode='ready';probe.updateModelStatus();assert.deepEqual(Array.from(probe.modelDownloads.context.files,f=>f.filename),['video.safetensors'],'supplied image does not require an image generator');
  probe.lookMode='build';probe.headSwap=()=>true;probe.modelStatus.h3_head_swap={model_files:[],missing_nodes:[]};probe.updateModelStatus();assert.equal(probe.modelDownloads.context.files.length,0,'head swap skips the starting-image generator');
}
studio.project={id:'preview-project',phase:'working',actions:[{id:'preview-action',stage:'h3'}]};studio.config.engine='h3';
apiEvents.get('minimax_h3_preview')({detail:{node_id:'h3_live_preview_preview-project',webp:'Ynl0ZXM=',step:3,total_steps:8}});
assert.equal(studio.$('live-preview').hidden,false,'A matching H3 sampler event shows a live sample during its render');
assert.equal(studio.$('live-preview-image').getAttribute('src'),'data:image/webp;base64,Ynl0ZXM=');
assert.equal(studio.$('live-preview-step').textContent,'Step 3/8');
studio.project.actions[0].id='other-action';
apiEvents.get('minimax_h3_preview')({detail:{node_id:'foreign-node',webp:'Zm9yZWlnbg==',step:1,total_steps:8}});
assert.equal(studio.$('live-preview-image').getAttribute('src'),'data:image/webp;base64,Ynl0ZXM=','Unmatched preview events are ignored');
studio.project.phase='done';studio.renderLiveH3Preview(false);
assert.equal(studio.$('live-preview').hidden,true,'Live samples are hidden after the render completes');
studio.project=null;studio.config.engine='wan';
assert.equal(studio.container.dataset.workspace,'video','Studio opens directly in the working video canvas');
assert.equal(studio.container.querySelectorAll('#gs-primary').length,1);
assert.ok(studio.$('primary').closest('.gs-composer'));
assert.ok(studio.container.querySelector('.gs-settings').closest('.zc-video-settings'));
assert.ok(ui.$('generate').classList.contains('zu-btn-primary'));
assert.ok(ui.$('width').classList.contains('zu-input'));
assert.ok(ui.$('prompt').classList.contains('zu-textarea'));
assert.deepEqual([...ui.root.querySelectorAll('.zc-choices [data-space] strong')].map(label=>label.textContent),['Image','Video']);
assert.ok(!ui.root.querySelector('.zc-choices button').classList.contains('zu-btn'),'Home choices keep their full-width list-row layout instead of DaisyUI compact-button sizing');
assert.equal(ui.root.querySelectorAll('.zc-card-art').length,0,'Home uses direct Image and Video choices without placeholder cards');
ui.show('video');studio.render();
assert.ok(studio.container.querySelector('#zc-video-task').closest('.zc-prompt-tools'),'Workflow choice sits in the model tool row');assert.equal(studio.container.querySelector('#zc-video-task').closest('.zc-task-control').previousElementSibling,ui.videoComposer.model);
assert.equal(studio.container.querySelector('.gs-workflow-choice').hidden,true,'The cramped legacy mode grid has no second visible copy');
for(const id of ['zc-attach-source','zc-attach-refs','zc-video-model','gs-resolution','gs-duration','gs-audio-mode'])assert.ok(studio.container.querySelector('#'+id).closest('.gs-composer'),id+' belongs to the compact composer');
assert.equal(studio.container.querySelector('#zc-attach-source').closest('.zc-source-choice'),studio.container.querySelector('.zc-source-hdr').closest('.zc-source-choice'),'Source and HDR import are presented as one choice');
assert.equal(studio.container.querySelector('.zc-source-hdr').textContent,'LTX HDR');
assert.match(studio.container.querySelector('.zc-source-hdr').title,/H3 video generation is SDR/);
assert.equal(studio.container.querySelector('.zc-source-hdr').hidden,true,'Wan does not advertise HDR input');
const originalEngine=studio.config.engine,originalMode=studio.config.workflow_mode;
studio.config.engine='h3';ui.videoComposer.sync();
assert.equal(studio.container.querySelector('.zc-source-hdr').hidden,true,'H3 does not advertise HDR input');
assert.equal(studio.container.querySelector('.zc-source-or').hidden,true,'The unused HDR separator is hidden');
studio.config.engine='local';studio.config.workflow_mode='motion';ui.videoComposer.sync();
assert.equal(studio.container.querySelector('.zc-source-hdr').hidden,false,'LTX offers its HDR conversion tool');
studio.config.workflow_mode='relight';ui.videoComposer.sync();
assert.equal(studio.container.querySelector('.zc-source-hdr').hidden,true,'Wan relight never advertises LTX HDR input');
studio.config.engine=originalEngine;studio.config.workflow_mode=originalMode;ui.videoComposer.sync();
assert.equal(ui.imageTask.previousElementSibling,ui.$('model').closest('.zc-model-control'),'Image mode uses the second toolbar slot too');
const workflowMenu=ui.videoComposer.task;
assert.equal(workflowMenu.tagName,'DETAILS');
assert.equal(workflowMenu.querySelector('select').hidden,true,'OS-native workflow dropdown is hidden behind the styled menu');
assert.equal(workflowMenu.querySelectorAll('[role="menuitemradio"]').length,11);
assert.equal(workflowMenu.querySelector('[data-workflow="inpaint"]'),null,'Edited-frame work has one Ripple route, without a duplicate Inpaint preview');
assert.ok(workflowMenu.querySelector('[data-workflow="outpaint"]'),'Frame extension is available as a preview workflow');
assert.equal(workflowMenu.querySelector('[data-workflow="swap"]').getAttribute('aria-checked'),'true');
const removedInputs=[],savedRemoveInput=studio.removeInput;studio.removeInput=type=>removedInputs.push(type);
for(const id of ['source','refs','frame'])studio.container.querySelector('#zc-remove-'+id).onclick();
assert.deepEqual(removedInputs,['source','character','ready'],'Each attachment has its own clear action, independent of the upload action');studio.removeInput=savedRemoveInput;
const dropped=[],originalUpload=studio.upload;studio.upload=(type,file)=>dropped.push({type,file});
for(const [id,name] of [['source','clip.mp4'],['refs','look.png']])studio.container.querySelector('#zc-attach-'+id).ondrop({preventDefault(){},stopPropagation(){},dataTransfer:{files:[{name}]}});
assert.equal(dropped[0].type,'source');assert.equal(dropped[0].file.name,'clip.mp4');assert.equal(dropped[1].type,'character');assert.equal(dropped[1].file[0].name,'look.png');studio.upload=originalUpload;
assert.equal(studio.container.querySelector('input[name="gs-workflow"][value="relight"]').closest('label').hidden,false,'Relight is visible from the Video source step');
assert.doesNotMatch(ui.$('generate').innerHTML,/[↗]/,'Image actions use consistent inline icons');
assert.equal(studio.$('preserve-identity-setting').hidden,true,'The H3 identity option stays out of unrelated modes');
assert.equal(studio.container.querySelectorAll('wa-tooltip').length,5);
const originalConfig={...studio.config};
for(const workflow of ['swap','viewport','camera','relight']){
  studio.config.workflow_mode=workflow;studio.selectWorkflow();studio.syncForm();studio.render();
  if(!studio.container.querySelector('input[name="gs-look"][value="ready"]').disabled)
    assert.equal(studio.container.querySelector('#zc-attach-frame').parentElement.hidden,false,workflow+' exposes a supplied frame when supported');
}
studio.config.workflow_mode='relight';studio.selectWorkflow();studio.syncForm();studio.render();
assert.equal(studio.container.querySelector('input[value="relight"]').closest('label').hidden,false);
assert.equal(studio.config.engine,'h3');assert.equal(studio.$('audio-settings').hidden,true);
assert.equal(studio.$('preserve-identity-setting').hidden,true,'Wan relight hides the H3 identity guide');
assert.equal(studio.config.relight_engine,'wan21','Relight defaults to the supplied Wan recipe');
assert.equal(studio.container.querySelector('#zc-attach-frame').parentElement.hidden,false,'Relight offers a finished frame directly in the composer');
{
  const fetch=api.fetchApi;api.fetchApi=async(path,options)=>path==='/zura/studio/upload?kind=image'?{ok:true,json:async()=>({id:'finished-lighting',file:'genj_studio/lighting.png',name:'lighting.png'})}:fetch(path,options);
  const file=Object.assign(new Blob(['image'],{type:'image/png'}),{name:'lighting.png'});
  studio.source={id:'temporary-source',duration:3};await studio.upload('ready',file);api.fetchApi=fetch;
  assert.equal(studio.lookMode,'ready');assert.equal(studio.readyAsset.id,'finished-lighting');assert.equal(studio.projectBody().starting_image,'finished-lighting');
  studio.removeInput('ready');studio.source=null;
}
assert.match(studio.container.querySelector('#zc-tool-resolution').textContent,/\d+ × \d+/,'Relight shows its output dimensions');
assert.doesNotMatch(studio.container.querySelector('#zc-tool-resolution').textContent,/H3/i,'Wan 2.1 relight must not show H3 in the resolution control');
assert.equal(studio.container.querySelector('input[name="gs-engine"][value="h3"]').closest('label').hidden,true,'H3 relight video is removed from Studio');
assert.equal(studio.$('image-editor').hidden,false);
assert.equal(studio.$('head-replacement-setting').hidden,true);
assert.equal(studio.$('content-badge').hidden,true);
assert.doesNotMatch(studio.$('selection-note').textContent,/character change/);
studio.source={id:'relight-source',duration:3,has_audio:true};studio.references=[];
studio.config.image_prompt='';studio.config.prompt='';studio.syncForm();studio.render();
assert.equal(studio.$('primary').disabled,true);
assert.match(studio.$('action-note').textContent,/Describe the lighting/);
studio.$('image_prompt').value='Warm sunset from the left';
studio.$('image_prompt').dispatchEvent(new window.Event('input',{bubbles:true}));
assert.equal(studio.$('primary').disabled,false,'Typing lighting enables prompt-only generation without blur or references');
assert.match(studio.$('primary').textContent,/Create lighting frame/);
studio.config.length_mode='original';studio.config.image_prompt='Warm sunset from the left';studio.source.duration=7.37;studio.syncForm();studio.render();
assert.equal(studio.$('primary').disabled,false,'Wan relight can use the full source without the old H3 five-second limit');
assert.match(studio.$('primary').textContent,/Create lighting frame/);
assert.doesNotMatch(studio.$('action-note').textContent,/up to 5 seconds/);
studio.modelStatus={engine_ready:{h3:false,design:true,wan21_relight:true},missing_h3_nodes:[],model_files:{design:[],wan21_relight:[]},wan21_relight:{model_files:[],missing_nodes:[]}};
studio.config.relight_engine='wan21';studio.config.image_prompt='Warm sunset from the left';studio.syncForm();studio.render();
assert.equal(studio.container.querySelectorAll('input[name="gs-engine"][value="wan21"]').length,1,'Wan 2.1 appears exactly once in the relight model choices');
assert.equal(studio.container.querySelector('input[name="gs-engine"][value="wan21"]').checked,true);
assert.equal(studio.container.querySelector('#zc-video-model').value,'wan21','Relight composer names the actual video model');
assert.doesNotMatch(studio.$('resolution').querySelector('option[value="1280"]').textContent,/H3/,'Relight resolution must not be labelled as H3');
assert.equal(studio.$('primary').disabled,false,'The 7.37-second approved source is allowed by chained Wan 2.1 relight');
assert.equal(studio.$('sampling-setting').hidden,true,'H3 sampling controls do not appear on the fixed-step Wan recipe');
assert.equal(studio.$('h3-steps-setting').hidden,true);
assert.equal(studio.$('resolution').closest('label').hidden,true,'The fixed Wan output size is explained instead of shown as an unavailable selector');
assert.match(studio.$('output-note').textContent,/81-frame sections/);
assert.match(studio.$('models').textContent,/Wan 2.1 · Relight ready/);
assert.equal(studio.$('graph-stage').querySelector('option[value="wan21_relight"]').disabled,false,'The matching editable graph is available');
studio.config.relight_engine='h3';studio.modelStatus=null;studio.syncForm();studio.render();
ui.selectPanel('look');assert.equal(ui.$('panel-look').hidden,false);assert.equal(ui.$('panel-source').hidden,true);
ui.revealTarget(studio.$('head-replacement'));assert.equal(ui.$('panel-source').hidden,false);
assert.ok(studio.$('takes').closest('.zc-take-drawer'),'Takes open in a drawer instead of stealing canvas height');
assert.ok(studio.$('library-list').closest('.zc-recent-shots'),'History is outside the canvas flow');
for(const selector of ['#zc-video-controls','.zc-viewer-views>summary','.zc-video-timing>summary','.zc-recent-shots>summary']){
  const trigger=studio.container.querySelector(selector);
  assert.ok(trigger.classList.contains('zc-viewer-trigger')&&trigger.querySelector('svg')&&trigger.getAttribute('aria-label'),'Viewer tool uses a compact icon with an accessible text label');
}
assert.ok(studio.$('trimmer').closest('.zc-trim-popup'),'The existing filmstrip timeline is directly available from the time selector');
assert.ok(studio.$('duration-setting').closest('#gs-trim-precision'),'Numeric timing is secondary to visual trim handles');
studio.container.querySelector('.zc-video-timing>summary').onclick({preventDefault(){}});assert.equal(ui.videoComposer.length.open,true,'Viewer Trim footage opens the same time selector');ui.videoComposer.length.open=false;
assert.equal(studio.container.querySelector('.gs-preview-scroll').children.length,4,'Viewer contains only toolbar, comparison, canvas and notice');
studio.project={id:'viewer',phase:'working',review:'review',opening_url:'/view/approved.png',opening_input:{file:'approved.png'},actions:[],config:{...studio.config}};studio.preview='look';studio.render();
assert.equal(studio.$('opening').hidden,false,'The approved image remains visible while video is sampling');
assert.equal(studio.$('opening').getAttribute('src'),'/view/approved.png');assert.equal(studio.$('empty').hidden,true);
studio.project.phase='error';studio.project.error='Stopped job';studio.render();assert.equal(studio.$('working').hidden,true,'Stopped jobs cannot keep an active progress overlay');
assert.equal(studio.$('opening').hidden,false,'A failed job retains the last approved frame');
studio.container.querySelector('.zc-viewer-notice>button').click();studio.render();assert.equal(studio.$('message').hidden,true,'Dismissed recovery messages stay dismissed');
studio.project=null;studio.message('');
studio.source=null;studio.config=originalConfig;studio.syncForm();studio.render();


studio.source={id:'private-source',name:'keep.mp4'};studio.references=[{id:'reference'}];
ui.show('image');await ui.loadModels();

// First show starts loading. Wait for that bounded set of mocked requests.
for(let i=0;i<10&&ui.loading;i++)await Promise.resolve();
assert.equal(ui.models.length,IMAGE_MODELS.length);
{
  const global=studio.modelDownloads={setMissingContext(route,missing,label){this.context={route,missing,label};},setContext(context){this.context=context;}};
  ui.render();
  assert.equal(global.context.route,'image','Global Models follows the Image workspace');
  assert.equal(global.context.label,ui.models.find(m=>m.id===ui.$('model').value).name);
  const previousModel=ui.$('model').value;const alternate=ui.models.find(m=>!m.edit&&!m.provider&&m.id!==previousModel);ui.$('model').value=alternate.id;ui.render();
  assert.equal(global.context.label,alternate.name,'Global Models follows the selected image model');
  ui.$('model').value=previousModel;ui.render();
  studio.updateModelStatus();
  assert.equal(global.context.route,'image','Video readiness refresh cannot overwrite image context');
  ui.show('video');assert.notEqual(global.context?.route,'image','Returning to Video clears the image context until video readiness is known');
  ui.show('image');assert.equal(global.context.route,'image','Returning to Image restores the selected image context');
  studio.modelDownloads=undefined;
}

const originalFetch=ui.fetch;
{
  // Refresh must use the task and model the artist chose while the catalogue was loading.
  let resume,waiting;const pending=new Promise(resolve=>resume=resolve),started=new Promise(resolve=>waiting=resolve);
  ui.fetch=async function(path,body){if(path==='/zura/studio/model-downloads'){waiting();return pending;}return originalFetch.call(this,path,body);};
  await ui.setImageOperation('create',{useCanvas:false});
  const refreshing=ui.loadModels();await started;
  await ui.setImageOperation('edit',{useCanvas:false});
  ui.$('model').value='ph3edit';ui.$('model').dispatchEvent(new window.Event('change'));
  resume({models:[]});await refreshing;
  assert.equal(ui.imageOperation,'edit');assert.equal(ui.$('model').value,'ph3edit');
  assert.equal(ui.$('model').querySelector('option[value="ph3edit"]').hidden,false);
  assert.equal(ui.$('model').querySelector('option[value="flux2"]').hidden,true);
  ui.fetch=originalFetch;await ui.setImageOperation('create',{useCanvas:false});
}
ui.fetch=async function(path,body){if(path==='/object_info/Flux2Scheduler')return {};return originalFetch.call(this,path,body);};
await ui.loadModels();
assert.ok([...ui.$('setup').querySelectorAll('a')].some(a=>a.href==='https://github.com/Comfy-Org/ComfyUI'),'Image setup points missing core image nodes to ComfyUI');
assert.match(ui.$('setup').textContent,/Update ComfyUI and restart/);
const missingImageModel=ui.models.find(model=>!model.ready&&!model.edit);assert.ok(missingImageModel);
const missingOption=ui.$('model').querySelector(`option[value="${missingImageModel.id}"]`);assert.equal(missingOption.hasAttribute('disabled'),false,'An uninstalled model can be selected for setup');
ui.$('model').value=missingImageModel.id;ui.$('model').dispatchEvent(new window.Event('change'));
assert.equal(ui.$('generate').disabled,true,'A missing model cannot start generation');assert.equal(ui.imageModelSetup.quick.hidden,false,'Selecting it shows setup beside the image prompt');
await ui.loadModels();assert.equal(ui.$('model').value,missingImageModel.id,'Refreshing preserves the selected model needing setup');
ui.fetch=originalFetch;
ui.fetch=async function(path,body){if(path==='/zura/studio/model-downloads')return {models:[{id:'flux2_klein_9b',remaining_bytes:123,files:[{filename:'flux2-vae.safetensors',size_bytes:123,incomplete:true}]}]};return originalFetch.call(this,path,body);};
await ui.loadModels();
assert.equal(ui.models.find(model=>model.id==='flux2').ready,true,'A different pinned download size alone must not disable an available local model');
assert.equal(ui.$('setup').querySelector('[data-download-model="flux2_klein_9b"]').disabled,true,'An alternate local model must never be overwritten');
assert.match(ui.$('setup').textContent,/file size alone does not establish compatibility/);
assert.doesNotMatch(ui.$('setup').textContent,/wrong size/);
ui.fetch=originalFetch;
ui.fetch=async function(path,body){if(path==='/zura/studio/model-downloads')return {models:[{id:'qwen2511',license_url:'https://huggingface.co/Qwen/Qwen-Image-Edit-2511',note:'Review model source terms.',remaining_bytes:181,files:[{filename:'qwen.safetensors',repo:'gree9515/Qwen-Image-Edit-2511-ConvRot',size_bytes:181,installed:false}]}]};return originalFetch.call(this,path,body);};
await ui.loadModels();
assert.ok(ui.$('setup').querySelector('[data-download-model="qwen2511"]'),'Qwen edit exposes the verified model package');
assert.match(ui.$('setup').textContent,/Review model source terms/);
assert.ok([...ui.$('setup').querySelectorAll('a')].some(a=>a.href==='https://huggingface.co/gree9515/Qwen-Image-Edit-2511-ConvRot'));
let imagePolls=0,imageStarts=0;
const setupFetch=ui.fetch;
ui.fetch=async function(path,body){
  if(path==='/zura/studio/model-downloads'&&body){imageStarts++;return {id:'image-download'};}
  if(path==='/zura/studio/model-downloads/image-download'){if(++imagePolls===1)throw Error('Network unavailable');return {phase:'done'};}
  return setupFetch.call(this,path,body);
};
const imageDownload=ui.startModelDownload('qwen2511');
await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(ui.modelDownloadJob,'image-download');assert.equal(ui.modelDownloadActive,true);
assert.match(ui.$('setup').querySelector('[data-download-status="qwen2511"]').textContent,/Reconnecting/);
await imageDownload;assert.equal(imageStarts,1);assert.equal(imagePolls,2);assert.equal(ui.modelDownloadActive,false);
let releaseImageStatus;const imageStatus=new Promise(resolve=>{releaseImageStatus=resolve;});let resumedImageStarts=0;
ui.fetch=async function(path,body){
  if(path==='/zura/studio/model-downloads'&&body){resumedImageStarts++;throw Error('must not submit');}
  if(path==='/zura/studio/model-downloads'&&!body){const catalogue=await setupFetch.call(this,path,body);return {...catalogue,active:releaseImageStatus?{id:'existing-image',model_id:'qwen2511'}:null};}
  if(path==='/zura/studio/model-downloads/existing-image')return imageStatus;
  return setupFetch.call(this,path,body);
};
await ui.loadModels();assert.equal(ui.modelDownloadJob,'existing-image');assert.equal(ui.modelDownloadActive,true);
assert.match(ui.$('setup').querySelector('[data-download-status="qwen2511"]').textContent,/Reconnecting/);
const finishImage=releaseImageStatus;releaseImageStatus=null;finishImage({phase:'done'});await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(ui.modelDownloadActive,false);assert.equal(resumedImageStarts,0);
let finishPost,finishRecovery,recoverPosts=0,recoverActive=true;const pendingImagePost=new Promise(resolve=>{finishPost=resolve;}),recoveredImageStatus=new Promise(resolve=>{finishRecovery=resolve;});
ui.fetch=async function(path,body){
  if(path==='/zura/studio/model-downloads'&&body){recoverPosts++;await pendingImagePost;throw Error('Connection lost');}
  if(path==='/zura/studio/model-downloads'&&!body){const catalogue=await setupFetch.call(this,path,body);return {...catalogue,active:recoverActive?{id:'recovered-image',model_id:'qwen2511'}:null};}
  if(path==='/zura/studio/model-downloads/recovered-image')return recoveredImageStatus;
  return setupFetch.call(this,path,body);
};
const recoveringImage=ui.startModelDownload('qwen2511');await ui.startModelDownload('qwen2511');assert.equal(recoverPosts,1,'Repeated image download clicks submit once');finishPost();await new Promise(resolve=>setTimeout(resolve,10));assert.equal(ui.modelDownloadJob,'recovered-image','Lost image download response reconnects to the active job');recoverActive=false;finishRecovery({phase:'done'});await recoveringImage;assert.equal(ui.modelDownloadActive,false);
ui.fetch=originalFetch;
ui.setImageOperation('edit');assert.equal(ui.$('model').value,'qwen2511');assert.equal(ui.$('generate').disabled,true,'Editing needs a source image');
assert.equal(ui.$('model').querySelector('option[value="flux3"]').hidden,true);
ui.references=[{file:'edit-source.png',name:'source.png'}];ui.$('prompt').value='Make the wall blue';ui.render();assert.equal(ui.$('generate').disabled,false);
assert.match(ui.$('generate').textContent,/Apply edit/);assert.match(ui.$('reference-hint').textContent,/Image 1: source/);
// The edited plate is a separate slot; references cannot silently replace it.
{
  const savedRefs=ui.references,savedItems=ui.items;
  assert.ok(ui.$('model').closest('.zi-output-tools'));
  assert.ok(ui.$('quick-settings').closest('.zi-output-tools'));
  assert.ok(ui.$('settings-toggle').closest('.zi-output-tools'));
  const workflowGroup=ui.$('model').closest('[aria-label="Model and workflow"]');
  assert.ok(workflowGroup);
  assert.equal(workflowGroup.children[1],ui.imageTask,'Image mode follows the model in the same toolbar slot as Video');
  assert.ok(ui.$('quick-settings').closest('[aria-label="Image size and settings"]'),'Image output controls form a separate group');
  assert.equal(ui.root.querySelector('.zc-image-heading h2').textContent,'Edit image');
  assert.ok(ui.$('new').closest('.zi-image-actions'));
  assert.equal(ui.root.querySelectorAll('#zc-new').length,1);
  ui.$('settings-toggle').click();assert.equal(ui.$('settings-toggle').getAttribute('aria-expanded'),'true');
  ui.$('settings-close').click();assert.equal(ui.$('settings-toggle').getAttribute('aria-expanded'),'false');
  ui.references=[];ui.items=[];ui.editMainMissing=false;ui.renderGallery();ui.render();
  await ui.uploadReferences([new File(['plate'],'plate.png',{type:'image/png'}),new File(['style'],'style.png',{type:'image/png'})]);
  const plate=ui.references[0],guide=ui.references[1],inputs=ui.editInputs;
  assert.equal(inputs.source.hidden,false,'First uploaded image immediately appears on the canvas');
  assert.match(inputs.source.querySelector('img').src,new RegExp(plate.filename));
  const imageCss=fs.readFileSync(new URL('../web/studio_create.css',import.meta.url),'utf8');
  assert.match(imageCss,/\.zc-image-source\{[^}]*position:relative[^}]*min-height:0[^}]*height:100%[^}]*overflow:hidden/,'The source is contained within its allocated viewer');
  assert.match(imageCss,/\.zc-image-source figure\{[^}]*position:absolute;inset:0[^}]*overflow:hidden/,'Large source dimensions cannot expand the workspace grid');
  assert.match(imageCss,/\.zc-image-source figure>img\{[^}]*position:absolute;inset:0[^}]*object-fit:contain/,'Portrait and landscape sources fit the viewer without stretching');
  ui.submitting=true;ui.render();
  assert.equal(inputs.source.hidden,false,'Submitting keeps the original source in the viewer');
  assert.equal(ui.$('progress').hidden,false,'Generation progress remains available when submitting an edit');
  assert.ok(ui.$('prompt').closest('.zc-image-composer'),'Prompt and actions remain in the composer during generation');
  ui.submitting=false;ui.render();
  assert.equal(ui.$('reference-list').querySelector('.zc-edit-main [data-remove-ref]').dataset.removeRef,'0');
  assert.equal(ui.$('reference-list').querySelector('.zc-edit-guides [data-remove-ref]').dataset.removeRef,'1');
  assert.equal(ui.$('add-references').closest('.zi-reference-panel')!==null,true);
  assert.equal(ui.$('reference-list').querySelector('[data-move-ref="1"]').hidden,true,'Guidance cannot be moved into the main slot');
  ui.$('reference-list').querySelector('[data-remove-ref="0"]').click();
  assert.equal(ui.editMainMissing,true);assert.deepEqual(ui.references,[guide]);
  assert.equal(inputs.source.hidden,true,'Removing the plate does not promote a guidance image');
  assert.equal(ui.$('generate').disabled,true);
  assert.equal(ui.$('image-empty').hidden,false,'Removing the only plate returns to the empty canvas');
  await ui.uploadReferences([new File(['replacement'],'replacement.png',{type:'image/png'})],{main:true});
  assert.equal(ui.editMainMissing,false);assert.equal(ui.references[1],guide);
  assert.equal(inputs.source.hidden,false);
  await ui.uploadReferences([new File(['new plate'],'newplate.png',{type:'image/png'})],{main:true});
  assert.equal(ui.references.length,2,'Replacing the plate retains guidance without adding a third input');assert.equal(ui.references[1],guide);
  ui.items=[{file:{filename:'edited-result.png'},references:ui.references.map(r=>({...r}))}];ui.selectedImage=0;ui.renderGallery();
  assert.equal(inputs.source.hidden,true,'A new generation displays its result');
  assert.equal(ui.$('gallery').hidden,false);
  inputs.toggle.click();assert.equal(inputs.source.hidden,false,'The original plate remains available for inspection');
  ui.$('compare-image').click();assert.equal(inputs.source.hidden,true);assert.equal(ui.imageComparison.host.hidden,false,'Compare uses the same main image and result');
  ui.imageComparison.active=false;
  await ui.setImageOperation('create',{useCanvas:false});
  assert.equal(ui.$('reference-list').querySelector('.zc-edit-main'),null);
  assert.equal(ui.$('add-references').parentElement,inputs.addHome,'Create mode restores the ordinary reference toolbar');
  assert.match(ui.$('add-references').textContent,/Add reference images/);
  ui.references=savedRefs;ui.items=savedItems;ui.editMainMissing=false;await ui.setImageOperation('edit',{useCanvas:false});ui.renderGallery();ui.render();
}
ui.$('model').value='klein9b';ui.render();assert.equal(ui.$('generate').disabled,false);
ui.references=[];ui.setImageOperation('create');ui.$('prompt').value='';ui.render();
ui.items=[{model:'klein9b',prompt:'Change the wall',references:[{file:'source.png'}],shape:'square',width:1024,height:1024,seed:7,file:{filename:'edit.png'}}];ui.renderGallery();
ui.$('gallery').querySelector('[data-reuse]').click();
assert.equal(ui.imageOperation,'edit','Reusing an edited image returns to Edit instead of selecting a hidden model in Create');assert.equal(ui.$('model').value,'klein9b');
ui.items=[];ui.references=[];ui.setImageOperation('create');ui.$('prompt').value='';ui.renderGallery();ui.render();
{
  const fetchApi=api.fetchApi,extra={file:'identity.png',filename:'identity.png',name:'Identity'};
  ui.items=[{file:{filename:'newest.png',subfolder:'zura_images'}},{file:{filename:'selected.png',subfolder:'zura_images'}}];
  ui.selectedImage=1;ui.autoCanvasSuppressed=false;ui.references=[extra];let copies=0,requested='';
  api.fetchApi=async(path,options)=>{
    if(path.startsWith('/view?')){requested=path;return {ok:true,blob:async()=>new Blob(['canvas'],{type:'image/png'})};}
    if(path==='/upload/image'){copies++;assert.equal(options.body.get('type'),'input');return {ok:true,json:async()=>({name:'canvas.png',subfolder:'zura_images/references'})};}
    return fetchApi(path,options);
  };
  await ui.setImageOperation('edit');
  assert.match(requested,/filename=selected.png/,'Edit takes the displayed image, not the newest history entry');
  assert.equal(ui.references[0].file,'zura_images/references/canvas.png');assert.equal(ui.references[1],extra,'Existing references are preserved after Image 1');
  await ui.setImageOperation('create');await ui.setImageOperation('edit');
  assert.equal(copies,1,'Returning to Edit reuses the uploaded canvas reference');assert.equal(ui.references.length,2);
  ui.references.reverse();await ui.setImageOperation('edit');assert.equal(ui.references[0].filename,'canvas.png','Existing canvas source is promoted back to Image 1');
  ui.items=[{file:{filename:'unavailable.png'}}];ui.renderGallery();api.fetchApi=async()=>({ok:false});
  const before=ui.references.slice();await ui.setImageOperation('edit');assert.deepEqual(ui.references,before);assert.match(ui.$('message').textContent,/Could not load the canvas/);assert.equal(ui.uploading,false);
  api.fetchApi=fetchApi;
  ui.items=[{file:{filename:'retained.png'}}];ui.selectedImage=0;ui.references=[{file:'main.png',filename:'main.png'},extra];ui.editMainMissing=false;ui.renderGallery();ui.render();
  ui.$('reference-list').querySelector('[data-remove-ref="0"]').click();
  await ui.setImageOperation('create');await ui.setImageOperation('edit');
  assert.deepEqual(ui.references,[extra],'A removed main image is not recreated from an old result on a mode switch');
  assert.equal(ui.editMainMissing,true,'Guidance stays guidance after switching modes');
  assert.equal(ui.selectedImage,-1,'Removing the main image does not expose an unrelated old result');
  ui.$('clear-references').click();
  await ui.setImageOperation('create');await ui.setImageOperation('edit');
  assert.deepEqual(ui.references,[],'Removing all images stays empty when returning to Edit');
  ui.references=[{file:'main.png',filename:'main.png'}];ui.editMainMissing=false;ui.selectedImage=0;ui.renderGallery();ui.render();
  const prompt=ui.$('prompt').value;
  ui.editInputs.clear.click();
  assert.equal(ui.items.length,1,'Clear result retains history and saved files');
  assert.equal(ui.$('gallery').querySelector('img'),null);
  assert.equal(ui.editInputs.source.hidden,false,'Clearing an edit result returns to the main image');
  assert.equal(ui.$('prompt').value,prompt);
  assert.equal(JSON.parse(storage['zura-image-workspace-v1']).selectedImage,-1,'Cleared selection persists across reloads');
  assert.equal(JSON.parse(storage['zura-image-workspace-v1']).draft.autoCanvasSuppressed,true);
  await ui.setImageOperation('create');await ui.setImageOperation('edit');
  assert.equal(ui.$('gallery').querySelector('img'),null,'Mode changes do not restore a cleared result');
  ui.$('image-history').querySelector('[data-view-image="0"]').click();
  assert.equal(ui.selectedImage,0,'An explicit history selection can restore a cleared result');
  assert.equal(ui.autoCanvasSuppressed,false);
  ui.items=[];ui.references=[];ui.selectedImage=0;await ui.setImageOperation('create');ui.message('');ui.renderGallery();ui.render();
}
assert.equal(ui.$('settings-panel').hidden,true);
ui.$('settings-toggle').onclick();
assert.equal(ui.$('settings-panel').hidden,false);
assert.equal(ui.$('settings-toggle').getAttribute('aria-expanded'),'true');
const dismiss=new window.Event('keydown',{bubbles:true,cancelable:true});
Object.defineProperty(dismiss,'key',{value:'Escape'});
ui.$('model').dispatchEvent(dismiss);
assert.equal(ui.$('settings-panel').hidden,true);
assert.equal(ui.$('settings-toggle').getAttribute('aria-expanded'),'false');

assert.ok(ui.$('generate').disabled);
ui.$('prompt').value='Sunlit train carriage';ui.$('prompt').oninput();
assert.equal(ui.$('generate').disabled,false);
ui.show('video');assert.equal(studio.source.id,'private-source');assert.equal(studio.references[0].id,'reference');
ui.show('image');assert.equal(ui.$('prompt').value,'Sunlit train carriage');
await ui.uploadReferences([new File(['image fixture'],'ref.png',{type:'image/png'}),new File(['second image'],'second.png',{type:'image/png'})]);
assert.equal(ui.references.length,2);assert.equal(ui.$('reference-list').querySelectorAll('img').length,2);
let prevented=0,stopped=0;
const paste={clipboardData:{items:[{kind:'file',type:'image/png',getAsFile:()=>new File(['clipboard fixture'],'image',{type:'image/png'})}]},preventDefault(){prevented++;},stopPropagation(){stopped++;}};
await ui.root.onpaste(paste);assert.equal(ui.references.length,3);assert.equal(prevented,1);assert.equal(stopped,1);assert.equal(ui.references[2].name,'Pasted image.png');
await ui.root.onpaste({clipboardData:{items:[{kind:'string',type:'text/plain'}]},preventDefault(){throw Error('Text paste intercepted');}});
let pastedVideoReferences=null;const uploadVideo=studio.upload.bind(studio);studio.upload=async(type,files)=>{pastedVideoReferences={type,files};};
ui.show('video');await ui.root.onpaste(paste);assert.equal(prevented,2);assert.equal(stopped,2);assert.equal(pastedVideoReferences.type,'character');assert.equal(pastedVideoReferences.files[0].name,'Pasted image.png');assert.equal(ui.references.length,3);studio.upload=uploadVideo;ui.show('image');
ui.uploading=true;await ui.root.onpaste(paste);assert.equal(ui.references.length,3);assert.match(ui.$('message').textContent,/Wait/);ui.uploading=false;
await ui.root.onpaste({clipboardData:{files:[new File(['fallback'],'fallback.webp',{type:'image/webp'})]},preventDefault(){},stopPropagation(){}});assert.equal(ui.references.length,4);

assert.equal(buildImageGraph(ui.config()).references.inputs['images.image1'][0],'reference_2');
const count=calls.filter(c=>c.path==='/upload/image').length;
await ui.uploadReferences(Array.from({length:10},()=>new File(['x'],'extra.png',{type:'image/png'})));
assert.equal(calls.filter(c=>c.path==='/upload/image').length,count,'Oversize selection never silently truncates');
ui.$('model').value='zimage';ui.render();assert.equal(ui.$('generate').disabled,true);assert.throws(()=>buildImageGraph(ui.config()),/supports 0/);
ui.$('model').value='flux3';ui.render();
ui.$('width').value='1280';ui.$('height').value='720';ui.$('width').oninput();
assert.equal(ui.$('generate').disabled,false);
assert.deepEqual(buildImageGraph(ui.config()).size.inputs,{width:1280,height:720,batch_size:1});
ui.$('width').value='1279';ui.$('width').oninput();assert.equal(ui.$('generate').disabled,true);
assert.throws(()=>buildImageGraph(ui.config()),/multiples/);
ui.$('width').value='1280';ui.$('width').oninput();
ui.$('swap-size').onclick();assert.equal(Number(ui.$('width').value),720);assert.equal(Number(ui.$('height').value),1280);
ui.setTheme('light');assert.equal(studio.container.dataset.theme,'light');assert.equal(storage['zura-studio-theme'],'light');
ui.show('video');assert.equal(studio.container.dataset.theme,'light');ui.show('image');
ui.job={started:Date.now()-10000,config:{model:'flux3',width:1024,height:1024}};
assert.match(ui.elapsed(),/Timing this render · 10s elapsed/,'First image runs show honest elapsed time without inventing an ETA');
ui.items=[{model:'flux3',width:1024,height:1024,seconds:30},{model:'flux3',width:1024,height:1024,seconds:40}];
assert.match(ui.elapsed(),/About \d+s left · estimate from 2 recent renders/,'Repeat image runs estimate remaining time from matching local render history');
ui.items=[];ui.job=null;
await ui.generate();await ui.generate();
assert.equal(calls.filter(c=>c.path==='/prompt').length,1,'Double click queues only once');
assert.equal(ui.job.id,'own-run');
apiEvents.get('execution_start')({detail:{prompt_id:'own-run'}});apiEvents.get('executing')({detail:'model'});assert.equal(ui.$('progress-title').textContent,'Loading image model','Modern Comfy string events show the current image-loading stage');
await ui.cancel();
assert.deepEqual(calls.find(c=>c.path==='/interrupt').body,{prompt_id:'own-run'},'Never interrupt another user job');
assert.deepEqual(calls.find(c=>c.path==='/queue'&&c.body).body,{delete:['own-run']});
assert.equal(ui.$('cancel').disabled,true);const cancelCount=calls.filter(c=>c.path==='/interrupt').length;await ui.cancel();assert.equal(calls.filter(c=>c.path==='/interrupt').length,cancelCount);apiEvents.get('progress')({detail:{prompt_id:'own-run',node:'sample',value:2,max:8}});apiEvents.get('executing')({detail:'decode'});assert.match(ui.$('progress-title').textContent,/Cancelling/,'Late image events do not replace cancellation');
history={'own-run':{status:{completed:true,messages:[['execution_start',{timestamp:1000}],['execution_success',{timestamp:4000}]]},outputs:{save:{images:[{filename:'image.png',subfolder:'zura_images',type:'output'}]}}}};
while(ui.polling)await new Promise(r=>setTimeout(r,1));
await ui.poll();
assert.equal(ui.job,null);assert.equal(ui.items.length,1);assert.equal(ui.items[0].seconds,3);assert.equal(ui.$('gallery').querySelectorAll('img').length,1);assert.equal(ui.timer,null);
reject=true;await ui.generate();assert.match(ui.$('message').textContent,/validation/);assert.equal(ui.job,null);assert.equal(ui.$('generate').disabled,false);
const ids=[...studio.container.querySelectorAll('[id]')].map(n=>n.id);assert.equal(ids.length,new Set(ids).size);
// Image review is an explicit, local step before motion and video generation.
const flow=new context.Studio();
const modelPicker=flow.container.querySelector('#zc-video-model');modelPicker.value='h3';modelPicker.onchange({target:modelPicker});while(flow.busy)await new Promise(resolve=>setTimeout(resolve,1));assert.equal(flow.config.engine,'h3','The composer model picker updates the existing workflow configuration');
assert.equal(flow.creative.videoComposer.model.hidden,false,'Choosing H3 must keep the video model selector visible at the image stage');
assert.equal(flow.container.querySelector('#zc-video-model').disabled,false,'Video model selection remains usable before image approval');
flow.config={...originalConfig};
flow.source={id:'flow-source',duration:2,has_audio:true,url:'/source.mp4'};flow.references=[{id:'flow-ref',url:'/ref.png'}];
flow.project={id:'guided-flow',phase:'opening',config:{...flow.config},review:'shot',approval:'prep',prepared_key:'prep',opening_key:'image-one',opening_input:{file:'one.png'},opening_url:'/one.png'};
flow.syncForm();flow.render();
assert.equal(flow.$('model-prompt').hidden,true,'Video direction stays hidden while the image awaits review');
assert.equal(flow.$('image-editor').hidden,true,'Review has one clear decision, not two competing prompt tabs');
assert.equal(flow.$('frame-review').hidden,false);assert.match(flow.$('primary').textContent,/Use image & continue/);
assert.equal(flow.$('video-options').hidden,true);assert.equal(flow.container.querySelectorAll('[data-prompt-stage]').length,0);
const priorRequests=calls.length;await flow.primary();
assert.equal(calls.length,priorRequests,'Approving an image never queues a render');
assert.equal(flow.$('model-prompt').hidden,false);assert.equal(flow.$('frame-review').hidden,true);
assert.match(flow.$('prompt-heading').textContent,/Direct your video/);assert.match(flow.$('primary').textContent,/Generate video/);
flow.$('prompt').value='Slow dolly in';flow.$('edit-frame').click();
assert.equal(flow.$('model-prompt').hidden,true);assert.equal(flow.$('image-editor').hidden,false);
assert.match(flow.$('primary').textContent,/Regenerate image/);assert.equal(flow.$('prompt').value,'Slow dolly in','Returning to the image preserves the motion prompt');
let regenerated=0;flow.$('redesign').onclick=()=>regenerated++;await flow.primary();assert.equal(regenerated,1);
flow.project={...flow.project,opening_key:'image-two',opening_input:{file:'two.png'},opening_url:'/two.png'};flow.render();
assert.equal(flow.composerStage(),'review','A regenerated image must be reviewed again');
assert.equal(flow.$('model-prompt').hidden,true);await flow.primary();
let animations=0;flow.primaryRecipe=async()=>animations++;await flow.primary();assert.equal(animations,1,'Only the next Generate video action starts video generation');
flow.promptStage=null;flow.render();assert.equal(flow.composerStage(),'video','Approval survives repainting and restoring the current image');
flow.creative.close();
// The frame workspace can be left through every visible route, with both
// workspaces' media and prompt drafts retained. No generation is submitted.
const navStudio=new context.Studio(),navUi=navStudio.creative;
navStudio.source={id:'retained-video',name:'source.mp4'};navStudio.references=[{id:'retained-reference'}];
const navRequests=calls.filter(c=>c.path==='/prompt').length;
const task=navStudio.container.querySelector('#zc-video-task');task.value='frames';task.dispatchEvent(new window.Event('change'));
assert.equal(navUi.mode,'frames');assert.equal(navUi.frames.page.hidden,false);assert.equal(navUi.frames.page.querySelector('#zc-video-task'),task,'The same selector remains in the frame composer');assert.equal(task.value,'frames');assert.ok(task.closest('.zc-task-control').previousElementSibling.classList.contains('zf-model'));assert.equal(navUi.frames.page.querySelector('#zf-back'),null);assert.equal(navStudio.container.querySelector('.gs-workspace').hidden,true);
const hdrRoot=document.createElement('section');hdrRoot.className='zf-page zh-page';hdrRoot.innerHTML='<button data-hdr="back">Back</button><button data-hdr="use-video"></button><select data-hdr="mode"><option value="sdr">SDR</option><option value="native">HDR</option></select><select data-hdr="source-kind"><option value="own">Choose another video</option><option value="upload">Source footage</option></select>';navStudio.container.append(hdrRoot);
navStudio.hdrTool={root:hdrRoot,setOutput(ref){this.output=ref;},$(id){return hdrRoot.querySelector(`[data-hdr="${id}"]`);},updateMode(){},activate(){this.active=true;},deactivate(){this.active=false;},sourceChanged(){},close(){}};
const ltxTake={type:'output',subfolder:'zura/first_last',filename:'ltx.mp4'},h3Take={type:'output',subfolder:'zura/first_last',filename:'h3.mp4'};navUi.frames.items=[{file:ltxTake,config:{engine:'ltx'}},{file:h3Take,config:{engine:'h3'}}];
navUi.frames.showResult(h3Take);assert.equal(navUi.frames.$('convert-hdr').hidden,true,'The LTX conversion action is not shown for another engine');
navUi.frames.showResult(ltxTake);assert.equal(navUi.frames.$('convert-hdr').hidden,false,'An LTX result offers HDR conversion at the result');
navStudio.hdrTool.$('mode').value='native';
navUi.frames.$('convert-hdr').click();assert.equal(navUi.mode,'hdr');assert.equal(navStudio.hdrTool.output,ltxTake);assert.equal(hdrRoot.hidden,false);assert.equal(navStudio.hdrTool.active,true);
assert.equal(navStudio.hdrTool.$('mode').value,'sdr','An SDR first/last take must not inherit a previous HDR-import mode');
navStudio.hdrTool.$('back').click();assert.equal(navUi.mode,'frames');assert.equal(navStudio.hdrTool.active,false);assert.equal(navUi.frames.page.hidden,false);navStudio.container.querySelector('#zc-open-hdr').click();
const outpaintTake={type:'output',subfolder:'genj/outpaint',filename:'extended.mp4'};navUi.mode='outpaint';navUi.outpaint={result:{hidden:false},outputRef:outpaintTake,outputIsHDR:false};navStudio.hdrTool.$('mode').value='native';navStudio.container.querySelector('#zc-open-hdr').click();assert.equal(navStudio.hdrTool.output,outpaintTake);assert.equal(navStudio.hdrTool.$('mode').value,'sdr');
navUi.mode='outpaint';navUi.outpaint.outputIsHDR=true;navStudio.hdrTool.$('mode').value='sdr';navStudio.container.querySelector('#zc-open-hdr').click();assert.equal(navStudio.hdrTool.$('mode').value,'native');
const paintTake={type:'output',subfolder:'genj/paintout',filename:'clean.mp4'};navUi.mode='paintout';navUi.paintout={view:'result',result:{file:paintTake}};navStudio.container.querySelector('#zc-open-hdr').click();assert.equal(navStudio.hdrTool.output,paintTake);
let imported;navUi.mode='paintout';navUi.paintout={view:'source',importStudioHDR:async(...args)=>{imported=args;},importStudioHDROutput:async(...args)=>{imported=args;}};navStudio.modelStatus={hdr_paintout_handoff:true};navStudio.container.querySelector('#zc-open-hdr').click();await navStudio.hdrTool.onUseVideo({id:'hdr-source'},'hlg_rec2020','hlg_and_exr');assert.deepEqual(imported,['hdr-source','hlg_rec2020','EXR + HLG video']);assert.equal(navUi.mode,'paintout');navUi.paintout.importStudioHDROutput=async(...args)=>{imported=args;};navStudio.container.querySelector('#zc-open-hdr').click();await navStudio.hdrTool.onUseResult({type:'output',filename:'converted.mp4'},'hlg_video');assert.deepEqual(imported,[{type:'output',filename:'converted.mp4'},'HLG video']);assert.equal(navUi.mode,'paintout');
navUi.mode='video';navStudio.config.engine='local';navStudio.project=null;navStudio.hdrTool.$('source-kind').value='own';navUi.openHDR();
assert.equal(navStudio.hdrTool.$('source-kind').value,'upload','Opening HDR from a loaded video uses that video, not an earlier HDR import');
navUi.mode='video';navStudio.project={results:[{asset:{type:'output',filename:'old-render.mp4'}}]};navUi.openHDR({preferSource:true});
assert.equal(navStudio.hdrTool.output,null,'HDR import ignores an earlier render');assert.equal(navStudio.hdrTool.$('source-kind').value,'upload');
navUi.mode='frames';navUi.frames.$('result').hidden=true;navStudio.hdrTool.$('source-kind').value='upload';navUi.openHDR();
assert.equal(navStudio.hdrTool.$('source-kind').value,'own','A workspace without a video does not inherit another workspace source');
let extendedImport;const outpaintPage=document.createElement('section');outpaintPage.innerHTML='<span class="zo-model"></span>';navStudio.container.append(outpaintPage);navUi.mode='outpaint';navUi.outpaint={page:outpaintPage,result:{hidden:true},source:null,capabilities:{hdr_expand_experiment:true},importStudioHDR:async(...args)=>{extendedImport=args;},open(){}};
navUi.openHDR({preferSource:true});assert.equal(navStudio.hdrTool.$('mode').value,'native');assert.equal(navStudio.hdrTool.$('use-video').textContent,'Use in frame extension');await navStudio.hdrTool.onUseVideo({id:'extension-hdr'},'pq_rec2020','hlg_and_exr');assert.deepEqual(extendedImport,[{id:'extension-hdr'},'pq_rec2020']);assert.equal(navUi.mode,'outpaint');
navUi.outpaint=null;navUi.paintout=null;
navUi.show('frames');
navUi.frames.assets.first={file:'retained-first.png',filename:'retained-first.png'};navUi.frames.$('prompt').value='A slow camera move';navUi.frames.save();
navUi.frames.loras.setValue([{name:'h3-style.safetensors',strength:.6,confirm_unknown:true}]);
assert.equal(navUi.frames.config().custom_loras[0].name,'h3-style.safetensors');
navUi.frames.$('engine').value='wan';navUi.frames.$('engine').dispatchEvent(new window.Event('change'));
assert.equal(navUi.frames.loras.family(),null,'Wan high and low noise cannot silently share one generic adapter');
assert.equal(navUi.frames.wanHighLoras.family(),'wan22_high');assert.equal(navUi.frames.wanLowLoras.family(),'wan22_low');
assert.equal(navUi.frames.wanHighLoras.root.hidden,false);assert.equal(navUi.frames.wanLowLoras.root.hidden,false);
const phases=[];for(const control of [navUi.frames.wanHighLoras,navUi.frames.wanLowLoras])control.request=async(path,body)=>{phases.push(body.family);return {graph:body.graph};};
navUi.frames.wanHighLoras.setValue([{name:'high.safetensors',strength:1,confirm_unknown:true}]);navUi.frames.wanLowLoras.setValue([{name:'low.safetensors',strength:1,confirm_unknown:true}]);
await navUi.frames.patchLoras({model:{}},navUi.frames.config());assert.deepEqual(phases,['wan22_high','wan22_low']);
assert.equal(navUi.frames.config().custom_loras[0].confirm_unknown,false,'Changing the model requires new compatibility confirmation');
navUi.frames.loras.setValue([]);navUi.frames.wanHighLoras.setValue([]);navUi.frames.wanLowLoras.setValue([]);navUi.frames.$('engine').value='h3';navUi.frames.$('engine').dispatchEvent(new window.Event('change'));
navUi.frames.$('engine').value='ltx';navUi.frames.render();assert.equal(navUi.frames.$('two-stage-control').hidden,false);
navUi.frames.$('two-stage').checked=true;navUi.frames.$('two-stage').dispatchEvent(new window.Event('change'));assert.equal(navUi.frames.config().twoStage,true);assert.equal(navUi.frames.config().fast,false);
navUi.frames.$('fast').checked=true;navUi.frames.$('fast').dispatchEvent(new window.Event('change'));assert.equal(navUi.frames.config().twoStage,false);assert.equal(navUi.frames.config().fast,true,'Fast and two-stage are distinct options');
navUi.frames.$('engine').value='h3';navUi.frames.render();assert.equal(navUi.frames.$('two-stage-control').hidden,true);assert.equal(navUi.frames.config().twoStage,false);
task.value='swap';task.dispatchEvent(new window.Event('change'));assert.equal(navUi.mode,'video');assert.equal(navUi.frames.page.hidden,true);assert.equal(navStudio.container.querySelector('.gs-workspace').hidden,false);
while(navStudio.busy)await new Promise(resolve=>setTimeout(resolve,1));
for(const mode of ['home','image','video']){
  navUi.show('frames');navStudio.container.querySelector(`.zc-nav [data-space="${mode}"]`).click();assert.equal(navUi.mode,mode);assert.equal(navUi.frames.page.hidden,true,mode+' must hide the frame page');
}
navUi.show('frames');navStudio.render();assert.equal(task.value,'frames','Legacy repaints cannot reset the current workflow selection');task.value='camera';task.dispatchEvent(new window.Event('change'));
assert.equal(navUi.mode,'panorama');assert.equal(navStudio.container.querySelectorAll('select[aria-label="Video workflow"]').length,1);assert.equal(task.closest('.zc-task-control').previousElementSibling,navUi.panorama.page.querySelector('.zpc-model'),'The selector stays beside the camera model');assert.equal(task.value,'camera');assert.equal(navUi.frames.page.hidden,true);task.value='swap';task.dispatchEvent(new window.Event('change'));assert.equal(navUi.mode,'video','The camera workspace has the same way back to character video');
navUi.show('panorama');
navUi.panorama.status={ready:true};navUi.panorama.state={source:{id:'fixture-source',name:'Camera source',duration:2},geometry:{ready:true},camera:'native-state'};navUi.panorama.render();
assert.equal(navUi.panorama.$('generate').textContent,'Choose camera angle','Preparing geometry must not silently approve the neutral camera');
let cameraOpened=false;const editCamera=navUi.panorama.editCamera;navUi.panorama.editCamera=async()=>{cameraOpened=true;};await navUi.panorama.generate();assert.equal(cameraOpened,true,'The next primary action opens the camera editor before queuing a warp');navUi.panorama.editCamera=editCamera;
navUi.panorama.state={};navUi.panorama.render();navUi.show('video');
navUi.show('frames');assert.equal(navUi.frames.assets.first.file,'retained-first.png');assert.equal(navUi.frames.$('prompt').value,'A slow camera move');
task.value='references';task.dispatchEvent(new window.Event('change'));
assert.equal(navUi.mode,'references');assert.equal(navUi.referencesVideo.page.hidden,false);assert.equal(navUi.frames.page.hidden,true);
assert.equal(navUi.referencesVideo.page.querySelector('#zc-video-task'),task,'The same workflow selector remains next to the reference model');
navUi.referencesVideo.assets.images=[{file:'ingredient.png',filename:'ingredient.png'}];navUi.referencesVideo.$('prompt').value='Use <Picture 1> in a quiet scene.';navUi.referencesVideo.save();
assert.equal(navStudio.container.querySelectorAll('#zf-prompt').length,1);assert.equal(navStudio.container.querySelectorAll('#zr-prompt').length,1);
task.value='frames';task.dispatchEvent(new window.Event('change'));assert.equal(navUi.mode,'frames');assert.equal(navUi.referencesVideo.page.hidden,true);
task.value='references';task.dispatchEvent(new window.Event('change'));assert.equal(navUi.referencesVideo.assets.images[0].file,'ingredient.png');assert.match(navUi.referencesVideo.$('prompt').value,/<Picture 1>/);
while(navStudio.busy)await new Promise(resolve=>setTimeout(resolve,1));
task.value='swap';task.dispatchEvent(new window.Event('change'));assert.equal(navUi.mode,'video');assert.equal(navUi.referencesVideo.page.hidden,true);
task.value='outpaint';task.dispatchEvent(new window.Event('change'));
assert.equal(navUi.mode,'outpaint');assert.equal(navUi.outpaint.page.hidden,false);
assert.equal(navUi.outpaint.page.querySelector('#zc-video-task'),task,'Frame extension retains the same workflow selector');
assert.equal(task.closest('.zc-task-control').previousElementSibling,navUi.outpaint.page.querySelector('.zo-model'));
while(navStudio.busy)await new Promise(resolve=>setTimeout(resolve,1));
task.value='swap';task.dispatchEvent(new window.Event('change'));assert.equal(navUi.mode,'video');assert.equal(navUi.outpaint.page.hidden,true);
task.value='paintout';task.dispatchEvent(new window.Event('change'));
assert.equal(navUi.mode,'paintout');assert.equal(navUi.paintout.page.hidden,false);assert.equal(navUi.frames.page.hidden,true);assert.equal(navUi.referencesVideo.page.hidden,true);
assert.equal(navUi.paintout.page.querySelector('#zc-video-task'),task,'Paintout retains the workflow menu beside its model');
assert.equal(task.closest('.zc-task-control').previousElementSibling,navUi.paintout.page.querySelector('.zf-model'),'Paintout uses the same second toolbar slot');
navUi.paintout.setMode('inpaint');navUi.videoComposer.syncWorkflow();
assert.equal(task.value,'paintout','A restored legacy Inpaint draft keeps a valid Paintout selector');
assert.match(navUi.paintout.$('prompt').value,/Add the object/,'Legacy masked drafts remain available without rewriting their conditioning');
navUi.videoComposer.selectWorkflow('inpaint');
assert.equal(navUi.mode,'ripple','Old Inpaint navigation opens the shared edited-frame timeline');
assert.equal(navUi.ripple.page.hidden,false);assert.equal(navUi.paintout.page.hidden,true);
assert.equal(navUi.paintout.state.mode,'inpaint','Opening Ripple does not rewrite the legacy draft');
assert.equal(task.value,'ripple','The shared workflow menu identifies the consolidated Ripple workspace');
task.value='paintout';task.dispatchEvent(new window.Event('change'));
assert.equal(navUi.paintout.state.mode,'targeted','Returning to paintout restores removal conditioning');
navUi.paintout.loras.setValue([{name:'ltx-style.safetensors',strength:.7,confirm_unknown:true}]);
let paintLoraRequest;navUi.paintout.loras.request=async(path,body)=>{paintLoraRequest={path,body};return {graph:{...body.graph,custom_test:{class_type:'LoraLoaderModelOnly',inputs:{}}}};};
assert.equal((await navUi.paintout.loras.patch({model:{class_type:'UNETLoader',inputs:{}}})).custom_test.class_type,'LoraLoaderModelOnly');
assert.equal(paintLoraRequest.body.family,'ltx25');assert.equal(navUi.paintout.config().custom_loras[0].strength,.7);
navUi.paintout.loras.setValue([]);
const paintTools=navUi.paintout.editor.tools,advanced=paintTools.querySelector('[data-editor=tracking-options]');
assert.equal(advanced.hasAttribute('open'),false,'Precise tracking controls start collapsed');
for(const key of ['range-start','range-end','direction','operation'])assert.ok(advanced.querySelector(`[data-editor=${key}]`),'Advanced tracking retains '+key);
assert.ok(!paintTools.querySelector('[data-editor=track]').closest('details'),'Tracking stays visible without opening advanced options');
assert.ok(!paintTools.querySelector('[data-editor=add-segment]').closest('details'),'Adding another mask stays directly accessible');
let escapedTextEvents=0;const input=navUi.paintout.editor.$('instruction');
for(const type of ['mousedown','dblclick','keydown','selectstart','copy']){
 const listener=()=>escapedTextEvents++;navUi.paintout.page.addEventListener(type,listener);
 const event=new window.Event(type,{bubbles:true,cancelable:true});Object.defineProperty(event,'key',{value:'a'});
 input.dispatchEvent(event);assert.equal(event.defaultPrevented,false,'Native text editing remains enabled for '+type);
 navUi.paintout.page.removeEventListener(type,listener);
}
assert.equal(escapedTextEvents,0,'Text editing cannot reach graph selection/shortcut handlers');
navUi.paintout.state.anchors=[{file:'Z:/painted_42.png',frame:42,strength:.75,enabled:true}];navUi.paintout.renderAnchors();navUi.paintout.save();
task.value='frames';task.dispatchEvent(new window.Event('change'));assert.equal(navUi.paintout.page.hidden,true);assert.equal(navUi.frames.page.hidden,false);
task.value='paintout';task.dispatchEvent(new window.Event('change'));assert.equal(navUi.paintout.state.anchors[0].frame,42,'Leaving Paintout retains artist anchor IDs');
while(navStudio.busy)await new Promise(resolve=>setTimeout(resolve,1));
task.value='swap';task.dispatchEvent(new window.Event('change'));assert.equal(navUi.mode,'video');assert.equal(navUi.paintout.page.hidden,true);
assert.equal(navStudio.source.id,'retained-video');assert.equal(navStudio.references[0].id,'retained-reference');
assert.equal(calls.filter(c=>c.path==='/prompt').length,navRequests,'Navigation cannot queue a render');navUi.close();
// Graph view detaches the UI. Returning must restore light dismissal and the
// active video workspace's sample stream and job tracking without resubmission.
document.body.append(navStudio.container);
const popup=document.createElement('details');popup.className='zc-tool-popup';navStudio.container.append(popup);
for(const mode of ['frames','references']){
  navUi.show(mode);const workspace=mode==='frames'?navUi.frames:navUi.referencesVideo;
  const previousPreview=workspace.nativeSamplePreview;
  navUi.close();assert.equal(workspace.nativeSamplePreview,null);
  let resumed=0;const priorStart=workspace.startPolling;workspace.startPolling=()=>resumed++;workspace.job={id:'retained-job'};
  navUi.open();assert.equal(navUi.mode,mode);assert.ok(workspace.nativeSamplePreview);assert.notEqual(workspace.nativeSamplePreview,previousPreview);assert.equal(resumed,1);
  popup.open=true;document.body.dispatchEvent(new window.Event('pointerdown',{bubbles:true}));assert.equal(popup.open,false,'Outside clicks still dismiss after reopening');
  workspace.job=null;workspace.startPolling=priorStart;
}
assert.match(source,/this\.creative\?\.open\(\)/,'Opening Studio restores the retained creative workspace');
// Studio reuses its workspace controllers. Temporary close must not destroy
// retained panels, zoom controls or setup handlers needed on the next open.
const retainedExtension=navUi.outpaint.page,retainedFrames=navUi.frames,retainedReferences=navUi.referencesVideo;
navStudio.hdrTool.close=()=>hdrRoot.remove();
navStudio.close();
assert.equal(hdrRoot.parentElement,navStudio.container,'HDR remains in the retained Studio shell');
assert.equal(retainedExtension.parentElement,navStudio.container,'Frame extension remains in the retained shell');
assert.equal(retainedFrames.modelDownloads.closed,true);
assert.ok(retainedFrames.modelDownloads.panel.ontoggle,'Temporary close keeps model setup interactive');
for(const workspace of [retainedFrames,retainedReferences])assert.ok(workspace.previewZoom.toolbar.parentElement,'Zoom controls survive closing Studio');
document.body.append(navStudio.container);navUi.open();
for(const mode of ['frames','references','outpaint','hdr']){
  navUi.show(mode);
  const page=mode==='frames'?retainedFrames.page:mode==='references'?retainedReferences.page:mode==='outpaint'?retainedExtension:hdrRoot;
  assert.equal(page.hidden,false,mode+' can be shown after reopening');
  assert.equal(page.isConnected,true,mode+' remains attached after reopening');
}
assert.equal(retainedFrames.modelDownloads.closed,false);assert.equal(retainedReferences.modelDownloads.closed,false);
navStudio.close();navUi.outpaint.dispose();
// Generation and Graph view both use the same backend-validated LoRA graph.
const oldImageFetch=ui.fetch.bind(ui),imageLoraCalls=[];
ui.fetch=async(path,body)=>{if(path==='/zura/studio/image-loras/validate'){imageLoraCalls.push(body);if(!body.loras[0].confirm_unknown)throw new Error('Confirm compatibility');return {loras:[{name:body.loras[0].name,strength:body.loras[0].strength}]};}return oldImageFetch(path,body);};
const imageLoraConfig={model:'flux2',prompt:'An image',loras:[{name:'face.safetensors',strength:.8,confirm_unknown:true}]};
const imageLoraGraph=await ui.imageGraph(imageLoraConfig);
assert.equal(imageLoraGraph.custom_image_lora_1.inputs.lora_name,'face.safetensors');
assert.equal(imageLoraCalls[0].model,'flux2');
await assert.rejects(ui.imageGraph({...imageLoraConfig,loras:[{name:'face.safetensors',strength:1,confirm_unknown:false}]}),/Confirm compatibility/);
ui.fetch=oldImageFetch;
// Browser choices use existing account nodes, never paid API keys or local LoRAs.
const browserRequests=[],originalModel=ui.$('model').value,originalPrompt=ui.$('prompt').value,originalLoras=ui.imageLoras;
let browserState='disconnected';
ui.fetch=async(path,body)=>{if(path.startsWith('/zura/browser_image_')){browserRequests.push({path,body});if(path.endsWith('_login')){browserState='connected';return {ok:true};}return {state:browserState,message:browserState==='connected'?'Connected':'Connect your Firefox account'};}return oldImageFetch(path,body);};
ui.show('image');await ui.setImageOperation('create',{useCanvas:false});ui.$('model').value='chatgpt';ui.$('prompt').value='A graphite drawing';ui.imageLoras=[{name:'local.safetensors',strength:1}];ui.render();
await new Promise(resolve=>setImmediate(resolve));
assert.equal(ui.browserConnection.host.hidden,false);assert.equal(ui.$('generate').disabled,true,'Connection is required');
assert.equal(browserRequests.filter(r=>r.path.endsWith('_login')).length,0,'Selecting a provider never initiates account access');
assert.equal(ui.$('image-lora-settings').hidden,true);assert.equal(ui.$('seed').closest('details').hidden,true);
assert.deepEqual(ui.config().loras,[]);assert.match(ui.$('size').textContent,/website determines/);
await ui.browserConnection.connect();assert.equal(ui.$('generate').disabled,false);
assert.deepEqual(browserRequests.find(r=>r.path.endsWith('_login')).body,{provider:'chatgpt'});
const browserGraph=await ui.imageGraph(ui.config());assert.equal(browserGraph.browser_image.class_type,'ZuraChatGPTImage');assert.ok(!browserGraph.model);assert.ok(!browserGraph.custom_image_lora_1);
await ui.setImageOperation('edit',{useCanvas:false});ui.$('model').value='geminiedit';ui.render();await new Promise(resolve=>setImmediate(resolve));
assert.equal(ui.browserConnection.button.textContent,'Reconnect account');
const geminiGraph=await ui.imageGraph(ui.config());assert.equal(geminiGraph.browser_image.class_type,'ZuraGeminiImage');assert.deepEqual(geminiGraph.browser_image.inputs.reference_1,['reference_1',0]);
ui.browserConnection.close();assert.equal(ui.browserConnection.timer,null);ui.browserConnection.open();await new Promise(resolve=>setImmediate(resolve));assert.ok(ui.browserConnection.timer,'Returning to Image restarts status updates');
ui.$('model').value=originalModel;ui.$('prompt').value=originalPrompt;ui.imageLoras=originalLoras;ui.fetch=oldImageFetch;ui.render();assert.equal(ui.browserConnection.host.hidden,true);assert.equal(ui.$('image-lora-settings').hidden,false);
ui.close();
assert.equal(JSON.parse(storage['zura-image-workspace-v1']).items.length,1);
const oldFiles=ui.items.map(i=>i.file.filename);ui.$('clear-history').onclick();assert.equal(ui.items.length,0);assert.equal(ui.$('gallery').querySelectorAll('img').length,0);assert.equal(ui.$('image-empty').hidden,!ui.editInputs.source.hidden,'Clearing history keeps the supplied main image visible');ui.$('undo-history').onclick();assert.deepEqual(ui.items.map(i=>i.file.filename),oldFiles);ui.$('clear-history').onclick();
const reopened=new context.Studio();assert.equal(reopened.creative.items.length,0);assert.equal(reopened.container.dataset.theme,'light');assert.equal(Number(reopened.creative.$('width').value),720);assert.equal(Number(reopened.creative.$('height').value),1280);reopened.creative.close();
const relightUi=new context.Studio();relightUi.source={id:'long-source',duration:15,width:1080,height:1920,url:'/source.mp4'};
relightUi.config={...relightUi.config,workflow_mode:'relight',engine:'h3',relight_engine:'wan21',length_mode:'original',edit_area:'scene'};
relightUi.lookMode='ready';relightUi.readyAsset={id:'lighting',url:'/light.png'};relightUi.syncForm();relightUi.render();
assert.doesNotMatch(relightUi.$('resolution').querySelector('option[value="1280"]').textContent,/H3/,'Relight resolution must never claim H3');
assert.doesNotMatch(relightUi.$('action-note').textContent,/H3|5 seconds/,'Long relight should not show H3 limits');
assert.equal(relightUi.container.querySelector('#zc-video-model').value,'wan21','The model selector reflects the actual relight model');
// Backwards step navigation must change the real preview and active step,
// even when the project already has a finished take.
relightUi.project={id:'nav-completed',phase:'done',opening_input:'light.png',opening_url:'/light.png',results:[{url:'/finished.mp4'}],actions:[]};
relightUi.render();
relightUi.container.querySelector('[data-step="1"]').click();
assert.equal(relightUi.navigationStep,1);
assert.equal(relightUi.$('opening').getAttribute('src'),'/light.png');
assert.equal(relightUi.$('player').hidden,true);
assert.equal(relightUi.container.querySelector('[data-step="1"]').getAttribute('aria-current'),'step');
relightUi.container.querySelector('[data-step="0"]').click();
assert.equal(relightUi.navigationStep,0);
assert.equal(relightUi.$('player').src,'/source.mp4');
assert.equal(relightUi.$('opening').hidden,true);
relightUi.restartNavigation.dispose();
relightUi.creative.close();
// Choosing the original HDR source frame needs no dummy reference. The source
// is reviewed first; only the next explicit action approves it and reads the
// selected native frame. No image or video generation is queued here.
const hdrFlow=new context.Studio();hdrFlow.source={id:'hdr-video',name:'hdr.mp4',duration:2,width:1280,height:720,url:'/hdr.mp4',native_hdr_video:{asset_id:'a'.repeat(32),sha:'b'.repeat(64),colour_space:'auto'}};
hdrFlow.modelStatus={...(hdrFlow.modelStatus||{}),native_hdr_performance:true};
hdrFlow.config={...hdrFlow.config,engine:'local',workflow_mode:'motion',edit_area:'scene',background:'restyle',ltx_output:'hlg_and_exr',duration:1,start:0};
hdrFlow.syncForm();hdrFlow.render();await hdrFlow.creative.videoComposer.ltxOutput.useSourceFrame();
assert.equal(hdrFlow.hdrSourceLook,true);assert.equal(hdrFlow.hasLook(),true);
assert.equal(hdrFlow.projectBody().look_mode,'source_hdr');assert.deepEqual([...hdrFlow.projectBody().references],[]);
let hdrProject=null;const hdrCalls=[],priorFetch=api.fetchApi;
api.fetchApi=async(path,options)=>{
  const body=options?.body?JSON.parse(options.body):undefined;hdrCalls.push({path,body});
  if(path==='/zura/studio/projects'){hdrProject={id:'hdr-project',source:hdrFlow.source,config:hdrFlow.config,look_mode:'source_hdr',references:[],character:null,actions:[],results:[],phase:'new'};return {ok:true,json:async()=>hdrProject};}
  if(path.endsWith('/config'))return {ok:true,json:async()=>hdrProject};
  if(path.endsWith('/action')){if(body.action==='prepare')hdrProject={...hdrProject,phase:'review',review:'shot',prepared_key:'prep',approval:null};else if(body.action==='approve')hdrProject={...hdrProject,phase:'approved',approval:'prep'};return {ok:true,json:async()=>hdrProject};}
  if(path.endsWith('/hdr-source-opening')){hdrProject={...hdrProject,phase:'opening',look_mode:'ready',opening_key:'key',opening_input:{file:'frame.png',native_hdr:{source_id:'hdr-video'}},starting_asset:{id:'frame',file:'frame.png',native_hdr:{source_id:'hdr-video'}}};return {ok:true,json:async()=>hdrProject};}
  return priorFetch(path,options);
};
await hdrFlow.primaryRecipe();assert.equal(hdrFlow.project.phase,'review');assert.equal(hdrFlow.project.approval,null);
assert.deepEqual(hdrCalls.filter(x=>x.path.endsWith('/action')).map(x=>x.body.action),['prepare']);
assert.ok(!hdrCalls.some(x=>x.path.endsWith('/hdr-source-opening')),'Preparation never auto-approves the review');
await hdrFlow.primaryRecipe();assert.equal(hdrFlow.project.phase,'opening');assert.equal(hdrFlow.lookMode,'ready');
assert.deepEqual(hdrCalls.filter(x=>x.path.endsWith('/action')).map(x=>x.body.action),['prepare','approve']);
assert.equal(hdrCalls.filter(x=>x.path.endsWith('/hdr-source-opening')).length,1);
assert.ok(!hdrCalls.some(x=>x.path==='/prompt'),'The flow does not start image or video generation');
api.fetchApi=priorFetch;hdrFlow.creative.close();
console.log('Reference upload/limits, safe history clearing/undo, saved theme and exact dimensions, Image/Video home, state preservation, native recipe readiness, prompt/action, targeted cancel, history and error recovery pass.');

navUi.panorama?.close();

for(const [mode,modelSelector] of [['video','.zc-model-control'],['frames','.zf-model'],['references','.zf-model'],['paintout','.zf-model'],['outpaint','.zo-model'],['panorama','.zpc-model']]){
 navUi.show(mode);const group=task.closest('.zc-workflow-controls');assert.ok(group,mode+' has a shared toolbar group');
 assert.equal(group.children[1],task.closest('.zc-task-control'),mode+' keeps the workflow in slot two');
 assert.ok(group.firstElementChild.matches(modelSelector),mode+' keeps the model in slot one');
}
navUi.panorama?.close();

if(process.env.ZURA_NAV_PREVIEW){
 const css=['studio.css','studio_create.css','studio_composer.css','studio_panorama.css','studio_outpaint.css','paintout_studio/studio_paintout.css','paintout_studio/paintout_integrated.css','paintout_studio/paintout_editor.css','studio_polish.css'];
 for(const mode of ['image','video','frames','references','paintout','outpaint','panorama']){
  navUi.show(mode);fs.writeFileSync(process.env.ZURA_NAV_PREVIEW+'/'+mode+'.html','<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'+css.map(name=>'<link rel="stylesheet" href="/web/'+name+'">').join('')+'<title>Studio toolbar check</title>'+navStudio.container.outerHTML);
 }
 navUi.panorama?.close();
}

navUi.show('watermark');
assert.equal(navUi.mode,'watermark');
assert.equal(navUi.watermark.page.querySelector('.zf-model').parentElement.children[1],navUi.videoComposer.task);
assert.equal(navUi.paintout.page.hidden,true);
const wm=navUi.watermark,ed=wm.editor;
const watermarkRestart=installStudioRestartNavigation(navStudio);
assert.equal(wm.config().anchors.length,0,'Watermark never reuses hidden guided Paintout anchors');
assert.equal(ed.$('segment-draft').parentElement,ed.tools.querySelector('.zp-editor-mask-actions'));
assert.equal(ed.$('tracking-options').parentElement.hidden,true,'Unused tracking settings are outside the visible action row');
assert.equal(ed.tools.querySelector('.zp-editor-segments').hidden,true);
assert.ok(wm.$('reference-control'));assert.equal(wm.$('reference-control').hidden,false);
wm.state.targetedMethod='light';wm.render();
assert.equal(wm.config().targetedMethod,'automatic','Old ProPainter projects migrate to LTX');
assert.equal(wm.state.targetedMethod,'automatic');
assert.equal(wm.$('reference-control').hidden,false);
assert.equal(wm.$('method'),null,'No redundant one-option model selector');
assert.match(wm.$('method-control').textContent,/LTX 2.5/);
assert.doesNotMatch(wm.page.textContent,/ProPainter/);
wm.state.colourPipeline='hdr_hdr';wm.render();assert.equal(wm.config().targetedMethod,'automatic');
wm.state.colourPipeline='sdr_sdr';wm.render();
let setupOpened=0;wm.openModelSetup=()=>setupOpened++;
wm.availability={ready:false,missing:['LTXVInpaintPreprocess']};wm.reviewSetup();
assert.equal(setupOpened,0,'Missing nodes do not open model downloads');
assert.equal(wm.$('render-settings').open,true,'Missing nodes open actionable settings');
wm.availability={ready:false,missing:['needed.safetensors']};wm.reviewSetup();
assert.equal(setupOpened,1,'Missing model files use model setup');
wm.state.referenceEnabled=true;wm.state.referenceImage=null;
assert.equal(wm.config().referenceEnabled,false,'An empty optional reference never blocks rendering');
let referencePicks=0;wm.pickWatermarkReference=async()=>referencePicks++;
await wm.toggleWatermarkReference(true);
assert.equal(referencePicks,1,'Enabling an optional guide opens its image picker immediately');
assert.equal(wm.state.referenceEnabled,false,'Cancelling the picker leaves the optional guide disabled');
wm.state.referenceImage={file:'C:/clean.png'};await wm.toggleWatermarkReference(true);
assert.equal(wm.state.referenceEnabled,true,'A supplied guide can be enabled');
await wm.toggleWatermarkReference(false);assert.equal(wm.state.referenceEnabled,false);
assert.equal(wm.$('progress').parentElement,wm.page,'Render progress sits beneath the picture, never over it');
assert.equal(wm.page.querySelector('.zf-viewer').contains(wm.$('progress')),false);
const flush=ed.flushManual,persist=ed.persist;let preserved=0;
ed.flushManual=async()=>{};ed.persist=async()=>{preserved++;};
Object.assign(wm.state,{source:'C:/old.mp4',mask:'C:/old-mask.png',maskProject:'old',maskRevision:8,maskCoverage:[0,1],referenceImage:{file:'C:/clean.png'},referenceEnabled:true,anchors:[{file:'old.png',frame:0}],editorStage:'render',clipTrimConfirmed:true});
Object.assign(ed,{source:wm.state.source,project:'old',projectSource:wm.state.source,document:{mask_segments:[{id:'stale'}]},stage:'render',active:false});
wm.result={file:{filename:'old.mp4'}};wm.playhead=10;
wm.job={id:'active'};
await navStudio.restartNavigation.button.onclick();
assert.equal(navStudio.restartNavigation.confirmation.hidden,false,'Watermark runs use the shared cancellation guard');
assert.equal(wm.state.source,'C:/old.mp4','An active job never loses its clip');
wm.job=null;
await navStudio.restartNavigation.button.onclick();
assert.equal(preserved,1,'The previous project is saved before its draft is cleared');
assert.equal(wm.state.source,'');assert.equal(wm.state.mask,'');assert.deepEqual(wm.state.anchors,[]);
assert.equal(wm.state.referenceEnabled,false);assert.equal(wm.state.referenceImage,null);
assert.equal(wm.state.editorStage,'trim');assert.equal(ed.stage,'trim');assert.equal(ed.project,null);assert.equal(ed.document,null);
assert.equal(wm.result,null);assert.equal(wm.playhead,0);assert.equal(wm.$('empty').hidden,false);
assert.equal(JSON.parse(storage[wm.storageKey]).draft.source,'','Reloading cannot bring back the cleared clip');
assert.equal(navUi.mode,'watermark');
wm.page.querySelector('.zps-back-video').click();assert.equal(navUi.mode,'video','Back to video leaves the watermark workspace');
ed.flushManual=flush;ed.persist=persist;
watermarkRestart.dispose();
wm.close();
console.log('PASS separate Watermark navigation, static mask actions, optional LTX reference and ProPainter migration');

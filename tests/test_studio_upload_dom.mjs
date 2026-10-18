// Exercise the real Studio HTML and render lifecycle. A mocked render misses
// removed DOM elements that can lock the UI before an upload even starts.
// Uses the same external, test-only linkedom install as test_wan_graph.mjs.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {ContentDetection} from '../web/studio_content.js';
import {clipLength,recoverClipLength} from '../web/studio_length.js';
import {stageProgress} from '../web/studio_progress.js';

const {document,window}=parseHTML('<html><body></body></html>');
// linkedom does not implement browser select setters/selectedOptions or media
// playback. Supply those host APIs, without mocking Studio render or binding.
Object.defineProperties(window.HTMLSelectElement.prototype,{
  value:{configurable:true,get(){return this.querySelector('option[selected]')?.value ?? this.querySelector('option')?.value ?? '';},set(value){for(const option of this.querySelectorAll('option'))option.selected=option.value===String(value);}},
  selectedOptions:{configurable:true,get(){return [...this.querySelectorAll('option')].filter(option=>option.selected);}},
});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{
  configurable:true,get(){return this.hasAttribute('checked');},set(value){
    if(value){if(this.type==='radio'&&this.name)for(const other of this.ownerDocument.querySelectorAll('input[type=radio]'))if(other!==this&&other.name===this.name)other.removeAttribute('checked');this.setAttribute('checked','');}
    else this.removeAttribute('checked');
  },
});
for(const method of ['load','pause','play'])window.HTMLElement.prototype[method]=()=>{};
const source=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').split('app.registerExtension({')[0];
const status={engine_ready:{wan:true,h3:true,local_scene:true,h3_viewport:true},model_files:{wan:[{ready:true,path:'wan-test.safetensors'}],h3:[{ready:true,path:'h3-test.safetensors'}],local_scene:[{ready:true,path:'ltx-test.safetensors'}]}};
const calls=[];let rejectUpload=false;
const api={apiURL:path=>path,fetchApi:async(path,options)=>{
  calls.push(path);
  if(path.endsWith('/status'))return {ok:true,json:async()=>status};
  if(path.endsWith('/projects'))return {ok:true,json:async()=>[]};
  assert.equal(path,'/zura/studio/upload?kind=video');
  if(rejectUpload)throw new Error('Test transfer failed');
  const file=options.body.get('file');
  return {ok:true,json:async()=>({id:'source-video',name:file.name,file:'genj_studio/test/source.mp4',duration:3,width:1280,height:720,thumbnail_url:'/view?test-thumbnail'})};
}};
const context={document,window,Event:window.Event,api,ContentDetection,clipLength,recoverClipLength,stageProgress,FormData,URLSearchParams,AbortController,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},crypto:globalThis.crypto,localStorage:{getItem:()=>null,removeItem(){},setItem(){}}};
vm.createContext(context);vm.runInContext(source+'\nthis.Studio=ArtistStudio;',context);
const ui=new context.Studio(),checklist=ui.$('model-checklist');
await ui.open();
assert.equal(ui.$('model-checklist'),checklist,'First render must preserve the model checklist until status arrives');
assert.match(checklist.textContent,/wan-test/);
assert.equal(ui.$('message').hidden,true,'Status arrival must not throw a hidden render error');
for(let i=0;i<3;i++)ui.render();
assert.equal(ui.busy,false);

// The actual bound drop handler must reach the HTTP client after startup/status.
let stopped=false,prevented=false;
const file=new File(['offline video fixture'],'source.mp4',{type:'video/mp4'});
await ui.$('source-drop').ondrop({dataTransfer:{files:[file]},stopPropagation(){stopped=true;},preventDefault(){prevented=true;}});
assert.ok(stopped && prevented);
assert.equal(calls.filter(path=>path.includes('/upload?')).length,1);
assert.equal(ui.source.name,'source.mp4');
assert.equal(ui.$('source-poster').hidden,false);
assert.equal(ui.$('source-poster').getAttribute('src'),'/view?test-thumbnail');
assert.equal(ui.$('player').src,'/view?filename=source.mp4&subfolder=genj_studio%2Ftest&type=input');
assert.equal(ui.$('source').disabled,false);
assert.equal(ui.busy,false);

// Switching model help must preserve the same live checklist, its contents and
// the installation guide, including across repeated renders and later uploads.
for(const engine of ['h3','local','wan']){
  Object.assign(ui.config,{engine,workflow_mode:engine==='local'?'motion':'swap',edit_area:engine==='local'?'scene':'mask'});
  ui.syncForm();ui.render();ui.render();
  assert.equal(ui.$('model-checklist'),checklist);
  assert.match(checklist.textContent,new RegExp(engine==='local'?'ltx-test':engine+'-test'));
  assert.ok(ui.container.querySelector('.gs-model-help a[href*="INSTALL_STUDIO"]'));
}

rejectUpload=true;
await ui.upload('source',file);
assert.equal(ui.busy,false);
assert.match(ui.$('message').textContent,/Test transfer failed/);
assert.equal(ui.$('source').disabled,false);
rejectUpload=false;
await ui.$('source').onchange({target:{files:[file],value:'source.mp4'},stopPropagation(){}});
assert.equal(ui.$('message').hidden,true);
assert.equal(ui.busy,false);

// A future render failure must never leave the busy flag stuck. It must be
// reported, skip the action safely and allow a later healthy upload to succeed.
const render=ui.render;let actionReached=false;
ui.render=()=>{throw new Error('Test rendering failed');};
await ui.perform(()=>{actionReached=true;});
assert.equal(actionReached,false);
assert.equal(ui.busy,false);
assert.match(ui.$('message').textContent,/Test rendering failed/);
ui.render=render;
await ui.upload('source',file);
assert.equal(ui.busy,false);
assert.equal(ui.$('source').disabled,false);
assert.equal(ui.$('message').hidden,true);
console.log('Studio actual-DOM startup/status, repeated render, model switch, drop/picker upload, thumbnail and failure recovery pass.');

// The approved head route is an explicit H3 choice, never inferred from the
// historical selection scope. Test its real controls, render and HTTP action.
ui.project=null;ui.source={...ui.source,has_audio:true,duration:3};
ui.references=[{id:'portrait',name:'portrait.png',url:'/portrait.png'}];
ui.character=ui.references[0];ui.lookMode='build';
ui.modelStatus={...status,engine_ready:{...status.engine_ready,h3_head_swap:true}};
Object.assign(ui.config,{engine:'h3',workflow_mode:'swap',scope:'head',h3_head_swap:false,edit_area:'mask',duration:2,length_mode:'custom'});
ui.syncForm();ui.render();
assert.equal(ui.$('head-replacement').value,'character','Legacy head scope must not opt into a different recipe');
ui.$('head-replacement').value='head';
await ui.$('head-replacement').onchange();
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(ui.config.h3_head_swap,true);
assert.equal(ui.readConfig().scope,'head');
assert.equal(ui.readConfig().h3_attention,'kitchen');
assert.equal(ui.readConfig().h3_steps,8);
assert.equal(ui.$('audio-settings').hidden,true);
assert.equal(ui.$('quality-setting').hidden,true);
assert.equal(ui.$('image-editor').hidden,true);
assert.equal(ui.$('selection-options').hidden,true);
assert.equal(ui.$('primary').disabled,false);
assert.match(ui.$('primary').textContent,/Generate head swap/);
assert.ok([...ui.$('graph-stage').options].filter(o=>!o.hidden).every(o=>['auto','h3'].includes(o.value)));
for(const [patch,message] of [[{has_audio:false},/original video audio/],[{has_audio:true,duration:3},/0.21 to 2 seconds/]]){
  Object.assign(ui.source,patch);ui.config.length_mode=patch.has_audio?'original':'custom';ui.syncForm();ui.render();
  assert.equal(ui.$('primary').disabled,true);assert.match(ui.$('action-note').textContent,message);
}
delete ui.source.has_audio;ui.config.length_mode='custom';ui.syncForm();ui.render();
assert.equal(ui.$('primary').disabled,false,'Older video metadata is checked by the backend without forcing a reupload');
ui.source.has_audio=true;ui.config.length_mode='custom';ui.config.duration=2;ui.syncForm();
const headCalls=[];api.fetchApi=async(path,options)=>{
  const body=options?.body?JSON.parse(options.body):null;headCalls.push({path,body});
  if(path==='/zura/studio/projects')return {ok:true,json:async()=>({id:'head-project',phase:'new',config:body.config,references:ui.references,source:ui.source})};
  if(path.endsWith('/action'))return {ok:true,json:async()=>({...ui.project,phase:'done',results:[],actions:[]})};
  throw new Error('Unexpected head-swap request '+path);
};
await ui.primary();
assert.equal(ui.busy,false);assert.equal(ui.$('message').hidden,true,ui.$('message').textContent);
assert.deepEqual(headCalls.map(c=>c.body?.action).filter(Boolean),['h3'],'No prepare, approve or image-generation stage');
assert.equal(headCalls[0].body.config.h3_head_swap,true);
assert.equal(headCalls[0].body.character,'portrait');
ui.project=null;ui.$('head-replacement').value='character';await ui.$('head-replacement').onchange();
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(ui.config.h3_head_swap,false);assert.equal(ui.config.scope,'person');
assert.equal(ui.$('audio-settings').hidden,false);assert.equal(ui.$('quality-setting').hidden,false);
console.log('H3 head-swap actual-DOM opt-in, compatibility reset, audio/length gates, direct render, graph stages and full-character recovery pass.');

// A single forward path: the image prompt belongs to Look, and video tuning
// appears only after an actual frame exists. Selection remains inspectable.
Object.assign(ui.config,{engine:'wan',workflow_mode:'swap',scope:'person',edit_area:'mask',h3_head_swap:false});
ui.project=null;ui.lookMode='build';ui.syncForm();ui.render();
assert.equal(ui.$('image-editor').closest('.gs-look'),ui.container.querySelector('.gs-look'));
assert.equal(ui.$('image-editor').hidden,false);
assert.equal(ui.$('redesign').hidden,true,'No duplicate first-frame action');
assert.equal(ui.$('video-options').hidden,true);
assert.match(ui.$('primary').textContent,/Create starting frame/);
ui.project={id:'flow',phase:'opening',review:'shot',approval:'key',prepared_key:'key',opening_input:{file:'frame.png'},opening_key:'frame',opening_url:'/frame.png',mask_url:'/mask.mp4',guide_url:'/guide.mp4',selected_url:'/source.mp4',actions:[]};
ui.render();
assert.equal(ui.$('video-options').hidden,false);
assert.equal(ui.$('opening').hidden,false);
assert.match(ui.$('primary').textContent,/Generate video/);
assert.equal(ui.$('redesign').hidden,false);
ui.$('preview-tabs').querySelector('[data-view="mask"]').click();
assert.equal(ui.$('player').src,'/mask.mp4');
assert.equal(ui.$('opening').hidden,true);
ui.$('preview-tabs').querySelector('[data-view="look"]').click();
assert.equal(ui.$('opening').hidden,false);
assert.match(ui.$('primary').textContent,/Generate video/);
console.log('One starting-frame action, staged video controls and selection/frame review pass.');

// The newer full-frame Wan model is an explicit choice, not the masked Wan recipe.
ui.project=null;Object.assign(ui.config,{engine:'wan2',workflow_mode:'motion',edit_area:'scene',h3_head_swap:false});
ui.syncForm();ui.render();
const wan2=ui.container.querySelector('input[name="gs-engine"][value="wan2"]');
assert.equal(wan2.closest('label').hidden,false);
const wan2Config=ui.readConfig();
assert.equal(wan2Config.engine,'wan2');assert.equal(wan2Config.workflow_mode,'motion');assert.equal(wan2Config.edit_area,'scene');assert.equal(wan2Config.resolution,832);
assert.equal(ui.$('selection-options').hidden,true);assert.equal(ui.$('audio-settings').hidden,true);
ui.project={id:'wan2',phase:'opening',review:'review',approval:'key',prepared_key:'key',opening_input:{file:'frame.png'},opening_key:'frame2',opening_url:'/frame.png',actions:[]};
ui.render();assert.equal(ui.$('primary').disabled,true,'Missing Animate 2 weights must gate video generation');
ui.modelStatus={...status,engine_ready:{...status.engine_ready,wan2:true}};ui.render();
assert.equal(ui.$('primary').disabled,false);
console.log('Wan Animate 2 visible full-frame option, safe payload and model setup gate pass.');

// Model handoffs must clear the previous sampler's metrics immediately. The
// operation stays visible while the native substatus explains the current wait.
ui.project={...ui.project,phase:'working',actions:[{id:'video-action',stage:'wan2',state:'running'}],progress:{action_id:'old-frame-action',action_stage:'design',state:'running',stage_label:'Sampling image',stage_percent:80,step:8,total_steps:10,stage_remaining_seconds:12,eta_confidence:'measured'}};
ui.render();
assert.equal(ui.$('working').hidden,false);
assert.match(ui.$('working-title').textContent,/Generating video.*Wan Animate 2/);
assert.equal(ui.$('working-percent').textContent,'');
assert.equal(ui.$('working-progress').hasAttribute('aria-valuenow'),false);
assert.equal(ui.$('working-progress').classList.contains('is-indeterminate'),true);
assert.doesNotMatch(ui.$('working-meta').textContent,/Step/);
assert.doesNotMatch(ui.$('working-detail').textContent,/left/);
ui.project.progress={action_id:'video-action',action_stage:'wan2',state:'preparing',stage_label:'Loading inputs',stage_elapsed_seconds:9,stage_percent:80,step:8,total_steps:10,stage_remaining_seconds:12,eta_confidence:'measured'};
ui.render();
assert.equal(ui.$('working-detail').textContent,'Loading inputs');
assert.equal(ui.$('working-percent').textContent,'');
assert.equal(ui.$('working-meta').textContent,'9s elapsed');
assert.equal(ui.$('live-cancel').hidden,false);
assert.equal(ui.$('live-cancel').disabled,false);
ui.project.progress={...ui.project.progress,state:'running',stage_label:'Generating video',stage_percent:25,step:2,total_steps:8,stage_remaining_seconds:30};
ui.render();
assert.equal(ui.$('working-percent').textContent,'25%');
assert.equal(ui.$('working-progress').getAttribute('aria-valuenow'),'25');
assert.match(ui.$('working-detail').textContent,/About 30s left in this step/);
assert.match(ui.$('working-meta').textContent,/Step 2 of 8/);
console.log('Actual-DOM image-to-video handoffs clear stale progress; loaders and live sampling remain distinct and cancellable.');

// Camera direction is a separate guided task: no mask, no character required,
// and animation waits for the camera still to exist and be reviewed.
ui.project=null;ui.references=[];ui.character=null;ui.readyAsset=null;ui.lookMode='build';
ui.source={...ui.source,has_audio:true,duration:2};
Object.assign(ui.config,{engine:'wan',workflow_mode:'camera',audio_id:'stale-audio',lip_sync:true,remove_text:true});
ui.modelStatus={...status,engine_ready:{...status.engine_ready,h3_camera:true}};
ui.selectWorkflow();ui.syncForm();ui.render();
assert.equal(ui.config.engine,'h3');
assert.equal(ui.hasLook(),true,'A camera preset can create a still without appearance references');
assert.equal(ui.$('camera-look').hidden,false);
assert.equal(ui.$('selection-options').hidden,true);
assert.equal(ui.$('audio-settings').hidden,true);
assert.equal(ui.$('image-editor').hidden,true,'Camera direction replaces the generic image prompt');
assert.equal(ui.$('video-options').hidden,true);
assert.match(ui.$('primary').textContent,/Create camera still/);
assert.match(ui.$('engine-hint').textContent,/preview mode/);
for(const engine of ui.container.querySelectorAll('input[name="gs-engine"]'))assert.equal(engine.closest('label').hidden,engine.value!=='h3');
ui.$('camera_preset').value='Custom prompt only';ui.render();
assert.equal(ui.$('primary').disabled,true);
ui.$('camera_prompt').value='A left profile view at eye level.';ui.$('camera_prompt').oninput();
assert.equal(ui.$('primary').disabled,false);
const cameraCalls=[];api.fetchApi=async(path,options)=>{
  const body=options?.body?JSON.parse(options.body):{};cameraCalls.push({path,body});
  if(path==='/zura/studio/projects')return {ok:true,json:async()=>({id:'camera-project',phase:'new',source:ui.source,config:body.config,references:[],actions:[]})};
  if(path.endsWith('/config'))return {ok:true,json:async()=>({...ui.project,config:body.config})};
  if(path.endsWith('/action'))return {ok:true,json:async()=>({...ui.project,phase:body.action==='animate'?'done':'opening',review:null,approval:null,prepared_key:null,opening_key:'camera-frame',opening_input:{file:'camera.png'},opening_url:'/camera.png',actions:[],results:[]})};
  throw new Error('Unexpected camera request '+path);
};
await ui.primary();
assert.equal(ui.$('message').hidden,true,ui.$('message').textContent);
assert.equal(ui.$('opening').hidden,false,JSON.stringify(cameraCalls));
assert.equal(ui.$('camera-regenerate').hidden,false);
assert.match(ui.$('primary').textContent,/Generate video/);
assert.match(ui.$('preview-title').textContent,/Review your camera still/);
await ui.primary();
assert.deepEqual(cameraCalls.map(c=>c.body.action).filter(Boolean),['create_look','animate']);
const cameraConfig=cameraCalls[0].body.config;
assert.equal(cameraConfig.camera_preset,'Custom prompt only');
assert.equal(cameraConfig.camera_prompt,'A left profile view at eye level.');
assert.equal(cameraConfig.edit_area,'scene');assert.equal(cameraConfig.audio_id,'');assert.equal(cameraConfig.lip_sync,false);assert.equal(cameraConfig.remove_text,false);
ui.project=null;ui.source.has_audio=false;ui.render();
assert.equal(ui.$('primary').disabled,true);
assert.match(ui.$('action-note').textContent,/original audio track/);
console.log('Camera actual-DOM optional references, presets, source-audio gate and still-review-before-video flow pass.');

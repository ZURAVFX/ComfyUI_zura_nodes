import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {UpscaleWorkspace} from '../web/studio_upscale.js';
import {buildUpscaleGraph,upscaleAvailability} from '../web/studio_upscale_recipes.js';
import {workflowProgress} from '../web/studio_workflow_progress.js';

const {document,window}=parseHTML('<html><head></head><body><main id="genj-studio"></main></body></html>');
Object.assign(globalThis,{document,window});
for(const method of ['pause','play','load'])window.HTMLElement.prototype[method]=()=>{};
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},
  set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===value);}});
const info=Object.fromEntries(['LoadVideo','Video Slice','GetVideoComponents','RelayVSRConditioning','VSRDecode','KSampler','CreateVideo','ZuraSaveProRes4444'].map(name=>[name,{}]));
info.UNETLoader={input:{required:{unet_name:['COMBO',{options:['Relay/relayvsr_x2_lightx2v_int8_convrot.safetensors']}]}}};
info.VAELoader={input:{required:{vae_name:[['Relay\\relayvsr_flash_vae_x2_fp32.safetensors']]}}};
const missing={...info};delete missing.RelayVSRConditioning;
assert.deepEqual(upscaleAvailability(missing),{ready:false,missing:['RelayVSRConditioning']});
const full=buildUpscaleGraph({file:'genj_studio/local/reference.mov'},info);
assert.equal(full.trim,undefined);
assert.deepEqual(full.components.inputs.video,['source',0]);
assert.deepEqual(full.video.inputs.fps,['components',2]);
assert.deepEqual(full.video.inputs.audio,['components',1]);
assert.equal(full.save.class_type,'ZuraSaveProRes4444');
assert.equal(full.sample.inputs.steps,1);
const cut=buildUpscaleGraph({file:'clip.mov',start:1/30,duration:2/30,detail:.5},info);
assert.equal(cut.trim.inputs.start_time,1/30);
assert.deepEqual(cut.components.inputs.video,['trim',0]);
assert.equal(cut.decode.inputs.detail,.5);

const draft=new Map();
const owner={root:document.querySelector('main'),mode:'upscale',api:{apiURL:path=>path},
 storage:{getItem:key=>draft.get(key)||null,setItem:(key,value)=>draft.set(key,value)},
 fetch:async(path)=>{
   if(path==='/object_info')return info;
   if(path==='/history/owned')return {owned:{status:{completed:true,status_str:'success'},outputs:{save:{images:[{filename:'up.mov',type:'output',preview:{filename:'up.mp4',type:'output'}}]}}}};
   throw Error(path);
 }};
const ui=owner.upscale=new UpscaleWorkspace(owner);
assert.equal(ui.$('generate').disabled,true);
assert.equal(workflowProgress(owner).active,0);
ui.source={file:'genj_studio/local/reference.mov',name:'Original',width:540,height:304,frames:150,fps:30,duration:5};
await ui.checkModels();
assert.match(ui.$('resolution').textContent,/1080 × 608/);
ui.setFrames(7,51);
assert.deepEqual(ui.config(),{file:ui.source.file,start:6/30,duration:45/30,detail:1});
ui.job={id:'owned',config:ui.config()};
assert.equal(workflowProgress(owner).active,1);
await ui.poll();
assert.equal(workflowProgress(owner).active,2);
assert.match(ui.$('download').href,/up.mov/);
assert.match(ui.video.src,/up.mp4/);
assert.equal(ui.$('compare').hidden,false);
assert.equal(ui.reset(),true);
assert.equal(ui.$('generate').disabled,true);
ui.close();
console.log('Upscale navigation state, full-source and exact trim graph, audio/rate links, preview and ProRes delivery passed.');

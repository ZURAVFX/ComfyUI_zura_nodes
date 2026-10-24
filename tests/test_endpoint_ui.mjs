import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {FrameVideoWorkspace} from '../web/studio_frames.js';
import {ENDPOINT_RECIPES,endpointLengths} from '../web/video_recipe_catalog.js';
import {FRAME_VIDEO_MODELS as h3} from '../web/frame_video_recipes.js';
import {WAN_FRAME_VIDEO_MODELS as wan} from '../web/wan_frame_video_recipes.js';
import {LTX_FRAME_VIDEO_MODELS as ltx} from '../web/ltx_frame_video_recipes.js';

const {document,window}=parseHTML('<html><body><section id="root"></section></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(v){for(const o of this.querySelectorAll('option'))o.toggleAttribute('selected',o.value===String(v));}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(v){this.toggleAttribute('checked',!!v);}});
window.HTMLElement.prototype.pause=()=>{};
const stored={};Object.assign(globalThis,{document,window,localStorage:{getItem:k=>stored[k],setItem:(k,v)=>stored[k]=v}});
const info=Object.fromEntries(ENDPOINT_RECIPES.flatMap(c=>c.nodeTypes).map(n=>[n,{input:{required:{}}}]));
const combo=(node,key,values)=>{info[node].input.required[key]=['COMBO',{options:values}];};
combo('UNETLoader','unet_name',[h3.model,wan.high,wan.low,ltx.model]);combo('UNETLoader','weight_dtype',['default','fp8_e4m3fn_fast']);
combo('CLIPLoader','clip_name',[h3.text,wan.text,ltx.text]);combo('VAELoader','vae_name',[h3.videoVae,h3.audioVae,wan.vae,ltx.videoVae,ltx.audioVae]);
combo('LoraLoaderModelOnly','lora_name',[h3.lora,wan.highLora,wan.lowLora]);combo('ModelAttentionBackend','attention',['comfy kitchen attention']);combo('KSamplerSelect','sampler_name',['res_multistep','euler_ancestral']);
const submissions=[],events=new Map();let missingLtx=false;
const owner={root:document.querySelector('#root'),studio:{close(){}},app:{},api:{apiURL:p=>p,clientId:'test',addEventListener:(n,h)=>events.set(n,h)},fetch:async(path,body)=>{
  if(path.startsWith('/object_info/')){const type=path.split('/').at(-1);if(missingLtx&&type==='LTXVAddGuide')throw new Error('Node not installed');return {[type]:info[type]};}
  if(path==='/prompt'){submissions.push(body.prompt);return {prompt_id:'job-'+submissions.length};}
  if(path.startsWith('/history/'))return {};
  if(path==='/queue')return {queue_running:[[0,'job-'+submissions.length]],queue_pending:[]};
  return {};
}};
const ui=new FrameVideoWorkspace(owner);await ui.loadModels();
ui.assets={first:{file:'first.png',filename:'first.png'},last:{file:'last.png',filename:'last.png'},audio:{file:'voice.wav',filename:'voice.wav'}};
ui.$('prompt').value='The character turns towards the camera.';ui.$('random').checked=false;ui.$('audio-enabled').checked=true;ui.render();
assert.equal(ui.$('generate').disabled,false);const assets=ui.assets;
const change=id=>{ui.$('engine').value=id;ui.$('engine').dispatchEvent(new window.Event('change'));};
change('wan');assert.equal(ui.assets,assets);assert.equal(ui.$('prompt').value,'The character turns towards the camera.');
assert.equal(ui.config().frames,81);assert.equal(ui.config().steps,4);assert.equal(ui.$('steps').disabled,true);
assert.equal(ui.$('audio-enabled').checked,false);assert.equal(ui.$('audio-enabled').closest('label').hidden,true);assert.equal(ui.$('audio-file-button').hidden,true);
assert.equal(ui.assets.audio.file,'voice.wav','Switching to silent Wan retains the audio asset for other engines');
assert.deepEqual(Array.from(ui.$('length').querySelectorAll('option')).map(o=>Number(o.value)),endpointLengths('wan'));
ui.$('size-preset').value='custom';ui.$('width').value=721;ui.$('height').value=416;ui.$('width').dispatchEvent(new window.Event('input'));
assert.equal(ui.config().width,720);assert.match(ui.$('size-hint').textContent,/16 pixels/);assert.equal(ui.$('generate').disabled,false);
ui.startPolling=()=>{};await ui.generate();assert.equal(submissions[0].high_model.inputs.unet_name,wan.high);assert.equal(submissions[0].low_sample.inputs.steps,4);assert.ok(!('audio' in submissions[0].video.inputs));
assert.equal(ui.$('engine').disabled,true);assert.equal(ui.job.config.engine,'wan');
events.get('executing')({detail:{prompt_id:ui.job.id,node:'low_sample'}});assert.match(ui.$('progress-title').textContent,/low-noise/);
ui.job=null;ui.render();change('ltx');assert.equal(ui.config().width,736);assert.equal(ui.config().frames,49);assert.equal(ui.config().steps,8);assert.equal(ui.$('steps').disabled,true);assert.equal(ui.$('audio-enabled').closest('label').hidden,false);
ui.$('audio-enabled').checked=true;ui.render();await ui.generate();assert.equal(submissions[1].model.inputs.unet_name,ltx.model);assert.equal(submissions[1].guide_last.inputs.frame_idx,48);assert.deepEqual(submissions[1].video.inputs.audio,['trim_audio',0]);
ui.job=null;ui.render();ui.save();const restored=new FrameVideoWorkspace({...owner,root:document.createElement('section')});assert.equal(restored.config().engine,'ltx');assert.equal(restored.config().frames,49);assert.equal(restored.config().width,736);restored.close();
// A missing optional engine must not prevent H3 or Wan from being used.
missingLtx=true;await ui.loadModels();assert.equal(ui.availability.ready,false);assert.match(ui.$('setup').textContent,/LTXVAddGuide/);
change('h3');assert.equal(ui.availability.ready,true);assert.equal(ui.$('generate').disabled,false);assert.equal(ui.config().frames,73);assert.equal(ui.$('steps').disabled,false);
await ui.generate();assert.equal(submissions[2].model.inputs.unet_name,h3.model);assert.equal(submissions[2].endpoints.inputs.length,73);
ui.job=null;ui.close();
console.log('Endpoint UI: model switching, native lengths/steps, per-model grid, audio restrictions, draft recovery, selected graph submission and partial node availability pass.');

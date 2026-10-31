import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioModelDownloads} from '../web/studio_model_download.js';

const {document,window}=parseHTML('<html><body><details id="setup"></details></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value ?? this.querySelector('option')?.value ?? '';},set(value){for(const option of this.querySelectorAll('option')){if(option.value===String(value))option.setAttribute('selected','');else option.removeAttribute('selected');}}});
globalThis.document=document;
const paths=[];
const pack={id:'wan_animate_2',name:'Wan Animate 2',note:'Separate nodes required.',remaining_bytes:1000000000,
  files:[{repo:'Comfy-Org/Wan-Animate-2',filename:'model.safetensors',size_bytes:1000000000,installed:false}]};
const availablePackages=['sam31','fasth3_draft','h3_reference_core','wan21_relight','wan22_animate_core','wan22_pose','wan22_style','wan22_first_last','h3_birefnet','h3_head_acceleration','h3_head_adapters','h3_taomate','h3_dmd_ref2va','h3_first_last','ltx25_text_encoder','ltx25_text_int8','ltx25_clean_plate','ltx25_outpaint','ltx25_in_outpaint','ltx_control','h3_int8_vae','h3_control','h3_crossview','flux3_klein','qwen2511','qwen21'];
const ltxPackages=[...availablePackages,'ltx25_layout'].map(id=>({...pack,id,name:id}));
const request=async(path,body)=>{paths.push([path,body]);if(path==='/model-downloads' && !body)return {models:[pack,...ltxPackages]};if(path==='/model-downloads' && body)return {id:'job'};if(path==='/model-downloads/job'){pack.remaining_bytes=0;pack.files[0].installed=true;return {phase:'done',done_bytes:1000000000,total_bytes:1000000000};}throw Error(path);};
const popup=document.createElement('details');popup.className='zc-tool-popup';document.body.append(popup);
const compact=new StudioModelDownloads(popup,request,()=>{});
assert.equal(popup.querySelector('summary').textContent,'Models');
assert.ok(popup.querySelector('.zc-tool-panel'),'composer setup uses the compact popup');
assert.equal(paths.length,0,'constructing setup must not start a request');compact.dispose();
let refreshed=false;const component=new StudioModelDownloads(document.querySelector('#setup'),request,()=>{refreshed=true;});
await component.load();
assert.deepEqual([...component.select.querySelectorAll('option')].map(o=>o.value),['__workflow__','wan_animate_2',...availablePackages],'the rejected LTX viewport package remains hidden');
assert.equal(paths.length,1,'Listing must not start a download');
assert.match(component.files.textContent,/1.00 GB to download/);
assert.match(component.files.textContent,/Separate nodes required/);
assert.equal(component.files.querySelector('a').href,'https://huggingface.co/Comfy-Org/Wan-Animate-2');
const sam={folder:'checkpoints',filename:'sam3.1_multiplex_fp16.safetensors',repo:'Comfy-Org/sam3.1',size_bytes:1745546848,installed:false};
component.packages=[{...pack,id:'openjutsu_h3',name:'OpenJutsu',remaining_bytes:20000000000,files:[sam,{folder:'diffusion_models',filename:'h3.safetensors',size_bytes:18000000000,installed:false}]},
  {...pack,id:'sam31',name:'SAM 3.1',remaining_bytes:sam.size_bytes,files:[sam]}];
component.setContext({route:'wan',files:[{folder:'checkpoints',filename:sam.filename,ready:false}],missingNodes:[]});
assert.match(component.files.textContent,/SAM 3.1/);assert.doesNotMatch(component.files.textContent,/OpenJutsu/,'A missing SAM checkpoint should not require the H3 bundle');
const wanStyle=[{folder:'loras',filename:'WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors',repo:'Kijai/WanVideo_comfy',size_bytes:272805784,installed:false},
  {folder:'loras',filename:'Wan14B_RealismBoost.safetensors',repo:'vrgamedevgirl84/Wan14BT2VFusioniX',size_bytes:306848616,installed:false}];
component.packages=[{...pack,id:'wan22_style',name:'Wan adapters',remaining_bytes:579654400,files:wanStyle}];
component.setContext({route:'wan',files:wanStyle.map(file=>({...file,ready:false})),missingNodes:[]});
assert.match(component.files.textContent,/Wan adapters/);assert.match(component.files.textContent,/0.58 GB/);
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://huggingface.co/vrgamedevgirl84/Wan14BT2VFusioniX'));
const endpointFiles=[{folder:'diffusion_models',filename:'WAN\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors',repo:'Comfy-Org/Wan-2.2',size_bytes:14294742832,installed:false},
  {folder:'diffusion_models',filename:'WAN\\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors',repo:'Comfy-Org/Wan-2.2',size_bytes:14294742832,installed:false}];
component.packages=[{...pack,id:'wan22_first_last',name:'Wan 2.2 endpoints',remaining_bytes:28589485664,files:endpointFiles}];
component.setMissingContext('wan_first_last',endpointFiles.map(file=>file.filename));
assert.match(component.files.textContent,/Wan 2.2 endpoints/);assert.match(component.files.textContent,/28.59 GB/);
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://huggingface.co/Comfy-Org/Wan-2.2'));
component.packages=[{...pack,files:[{folder:'loras',filename:'required.safetensors',repo:'Comfy-Org/Wan-Animate-2',size_bytes:1000000000,installed:false}]}];
component.setMissingContext('h3_first_last',['required.safetensors','unlisted.safetensors','MissingNode']);
assert.equal(component.select.value,'__workflow__');assert.match(component.files.textContent,/H3 first & last frame/);
assert.match(component.files.textContent,/required.safetensors/);assert.match(component.files.textContent,/unlisted.safetensors/);assert.match(component.files.textContent,/MissingNode/);
assert.equal(component.files.querySelectorAll('.gs-model-package').length,1,'matched files map to their verified package');
component.setMissingContext('ltx_outpaint_long',['LTXVInpaintPreprocess']);
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://github.com/Lightricks/ComfyUI-LTXVideo'),'missing LTX nodes link to their verified pack');
component.setContext({route:'hdr_native',files:[],missingNodes:['ZuraHDRReadChunkAnchor','LTXVAddGuide']});
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://github.com/ZURAVFX/ComfyUI_zura_nodes'));
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://github.com/Comfy-Org/ComfyUI'));
component.setContext({route:'ltx_outpaint_expand',files:[],missingNodes:['GenjSelectClip','ZuraOutpaintTemporalHold','ZuraHDRLoadNativeSource']});
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://github.com/ZURAVFX/ComfyUI_zura_nodes'));
assert.doesNotMatch(component.files.textContent,/Other nodes:/,'Zura-owned preparation nodes should have actionable update guidance');
component.packages=[{...pack,id:'fasth3_draft',name:'FastH3 draft',remaining_bytes:690592992,files:[{folder:'latent_upscale_models',filename:'minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors',repo:'LBH-123-AI/Minimax_h3_latent_Upscaler',size_bytes:690592992,installed:false}]}];
component.setMissingContext('h3_reference',['minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors','SelfLiftH3Sampler']);
assert.match(component.files.textContent,/FastH3 draft/);assert.match(component.files.textContent,/0.69 GB/);
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://github.com/facok/comfyui-SelfLift'));
const coreFile={folder:'diffusion_models',filename:'minimax_h3_ref2va_pruned_int8_convrot.safetensors',repo:'Comfy-Org/MiniMax-H3',size_bytes:1000000000,installed:false};
component.packages=[{...pack,id:'openjutsu_h3',name:'OpenJutsu',remaining_bytes:3000000000,files:[coreFile,{folder:'checkpoints',filename:'sam.safetensors',size_bytes:2000000000,installed:false}]},{...pack,id:'h3_reference_core',name:'H3 reference video',remaining_bytes:1000000000,files:[coreFile]}];
component.setMissingContext('h3_reference',[coreFile.filename]);
assert.match(component.files.textContent,/H3 reference video/);assert.doesNotMatch(component.files.textContent,/OpenJutsu/);
component.setMissingContext('h3_head_swap',['MVEx_SubjectCrop','MVEx_SubjectUncrop','LayerUtility: Pad Image Batch to 8n+1','DWPreprocessor','NKDMaskOps','NKDAVLatent','NKDSigmasCurve']);
for(const url of ['https://github.com/drozbay/MaskVidExperiments','https://github.com/chflame163/ComfyUI_LayerStyle','https://github.com/Fannovel16/comfyui_controlnet_aux','https://github.com/Nekodificador/ComfyUI-NKD-Basic-Tools','https://github.com/Nekodificador/ComfyUI-NKD-Sigmas-Curve'])
  assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href===url),`missing head-swap nodes link to ${url}`);
assert.doesNotMatch(component.files.textContent,/Other nodes:/);
component.setMissingContext('wan21_relight',['ForLoopOpen','ForLoopClose','SimpleMath+','easy int']);
for(const url of ['https://github.com/akatz-ai/ComfyUI-Execution-Inversion','https://github.com/cubiq/ComfyUI_essentials','https://github.com/yolain/ComfyUI-Easy-Use'])
  assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href===url),`missing relight nodes link to ${url}`);
assert.doesNotMatch(component.files.textContent,/Other nodes:/,'All required relight helpers have actionable package links');
// Route-specific setup uses real readiness evidence, deduplicates shared files,
// and reports unsupported dependencies instead of claiming complete setup.
component.packages=[{...pack,files:[{folder:'diffusion_models',filename:'model.safetensors',repo:'Comfy-Org/Wan-Animate-2',size_bytes:1000000000,installed:false}],license_url:'https://huggingface.co/Comfy-Org/Wan-Animate-2'},
  {...pack,id:'h3_control',name:'Alternate',files:[{folder:'diffusion_models',filename:'model.safetensors',repo:'x/y',size_bytes:1000000000,installed:false}]}];
component.setContext({route:'wan2',files:[{folder:'diffusion_models',filename:'model.safetensors',ready:false},{folder:'loras',filename:'custom-lora.safetensors',ready:false}],missingNodes:['OnnxDetectionModelLoader','UnmappedNode']});
component.select.value='__workflow__';component.render();
assert.match(component.files.textContent,/Wan Animate 2/);assert.match(component.files.textContent,/1.00 GB in available packages/);
assert.equal(component.files.querySelectorAll('.gs-model-package').length,1,'shared model must not appear as duplicate packages');
assert.match(component.files.textContent,/custom-lora.safetensors/);assert.match(component.files.textContent,/UnmappedNode/);
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://github.com/kijai/ComfyUI-WanAnimatePreprocess'));
assert.match(component.files.textContent,/restart ComfyUI/);
component.setContext({route:'local_scene',files:[{filename:'yolox_l.onnx',path:'custom_nodes/comfyui_controlnet_aux/ckpts/yzd-v/DWPose/yolox_l.onnx',ready:false},{filename:'dw-ll_ucoco_384_bs5.torchscript.pt',path:'D:/aux/hr16/DWPose-TorchScript-BatchSize5/dw-ll_ucoco_384_bs5.torchscript.pt',ready:false}],missingNodes:[]});
assert.match(component.files.textContent,/216\.75 MB/);assert.match(component.files.textContent,/135\.06 MB/);assert.match(component.files.textContent,/D:\/aux\/hr16/);
for(const url of ['https://huggingface.co/yzd-v/DWPose/blob/main/yolox_l.onnx','https://huggingface.co/hr16/DWPose-TorchScript-BatchSize5/blob/main/dw-ll_ucoco_384_bs5.torchscript.pt'])assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href===url));
component.setContext({route:'openjutsu',files:[],missingNodes:['H3CharacterSwapController','H3CharacterSwapPrepareVideo']});
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://github.com/akatz-labs/h3-character-swap-tool/tree/0670e4fdf95adf2262caa4b81afed2a9c4ae4b7b/worker_nodes/h3_character_swap'));
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://github.com/Comfy-Org/comfy-openjutsu/blob/70ec62df0eda7c58697ea3ac2050588513651583/build/h3_character_swap.patch'));
assert.match(component.files.textContent,/compatibility patch before installation/);assert.doesNotMatch(component.files.textContent,/Other nodes:/);
component.packages=[{...pack,id:'h3_dmd_ref2va',name:'H3 eight-step adapter',license_url:'https://huggingface.co/RunningHubAI/rh-minimax-h3-dmd-ref2va-8step-turbo-pruned.safetensors-lora',files:[{folder:'loras',filename:'minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors',repo:'RunningHubAI/test',size_bytes:2285989092,installed:false}]}];
component.setContext({route:'h3',files:[{folder:'loras',filename:'minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors',ready:false}],missingNodes:[]});
assert.match(component.files.textContent,/H3 eight-step adapter/);
assert.match(component.files.textContent,/2.29 GB/);
assert.match(component.files.textContent,/Download missing files/);
component.packages=[{...pack,id:'h3_taomate',name:'H3 TaoMate adapter',remaining_bytes:181697688,files:[{folder:'loras',filename:'minimax_h3_taomate_3step_lora_avg_rank_19_bf16.safetensors',repo:'Kijai/MiniMax-H3_comfy',size_bytes:181697688,installed:false}]}];
component.setMissingContext('h3_head_swap',['minimax_h3_taomate_3step_lora_avg_rank_19_bf16.safetensors']);
assert.match(component.files.textContent,/H3 TaoMate adapter/);assert.match(component.files.textContent,/0.18 GB/);
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://huggingface.co/Kijai/MiniMax-H3_comfy'));
component.packages=[pack];
component.select.value='wan_animate_2';component.render();
component.setContext({route:'h3_camera',files:[],missingNodes:[]});
assert.equal(component.select.value,'__workflow__','changing workflow returns setup to the current route');
assert.match(component.files.textContent,/H3 camera angle/);
component.select.value='wan_animate_2';component.render();
await component.start('wan_animate_2');
assert.ok(refreshed);assert.equal(component.progress.textContent,'Download complete.');
assert.equal(paths.filter(([path,body])=>path==='/model-downloads' && body).length,1);
component.job='cancel-visibility';component.setContext(null);component.select.value='__workflow__';component.render();
const cancelAction=[...component.actions.querySelectorAll('button')].find(button=>button.textContent==='Cancel download');
assert.ok(cancelAction,'An active download can be cancelled even while workflow setup is unavailable');
component.request=async path=>{paths.push([path]);return {};};await cancelAction.onclick();assert.ok(paths.some(([path])=>path==='/model-downloads/cancel-visibility/cancel'));component.job=null;component.render();
let polls=0,starts=0;
component.request=async(path,body)=>{
  if(path==='/model-downloads'&&body){starts++;return {id:'reconnect-job'};}
  if(path==='/model-downloads/reconnect-job'){if(++polls===1)throw Error('Network unavailable');return {phase:'done',total_bytes:1,done_bytes:1};}
  if(path==='/model-downloads')return {models:[pack]};throw Error(path);
};
const reconnect=component.start('wan_animate_2');
await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(component.job,'reconnect-job');assert.equal(component.select.disabled,true);
assert.match(component.progress.textContent,/Reconnecting/);
await reconnect;assert.equal(starts,1);assert.equal(polls,2);assert.equal(component.progress.textContent,'Download complete.');
let releaseStatus;const resumedStatus=new Promise(resolve=>{releaseStatus=resolve;});let resumedStarts=0;
const resumedPanel=document.createElement('details');document.body.append(resumedPanel);
const resumed=new StudioModelDownloads(resumedPanel,async(path,body)=>{
  if(path==='/model-downloads'&&!body)return {models:[pack],active:releaseStatus?{id:'existing',model_id:'wan_animate_2'}:null};
  if(path==='/model-downloads'&&body){resumedStarts++;throw Error('must not submit');}
  if(path==='/model-downloads/existing')return resumedStatus;throw Error(path);
});
await resumed.load();assert.equal(resumed.job,'existing');assert.equal(resumed.select.disabled,true);
assert.match(resumed.progress.textContent,/Reconnecting/);assert.equal(resumedStarts,0);
const finish=releaseStatus;releaseStatus=null;finish({phase:'done'});await new Promise(resolve=>setTimeout(resolve,10));
assert.equal(resumed.job,null);assert.equal(resumedStarts,0);resumed.dispose();
let releasePost,postCount=0,releaseRecovered,recoveredActive=true;const pendingPost=new Promise(resolve=>{releasePost=resolve;}),recoveredStatus=new Promise(resolve=>{releaseRecovered=resolve;});
const lostPanel=document.createElement('details');document.body.append(lostPanel);
const lost=new StudioModelDownloads(lostPanel,async(path,body)=>{
  if(path==='/model-downloads'&&body){postCount++;await pendingPost;throw Error('Connection lost');}
  if(path==='/model-downloads')return {models:[pack],active:recoveredActive?{id:'recovered',model_id:'wan_animate_2'}:null};
  if(path==='/model-downloads/recovered')return recoveredStatus;throw Error(path);
});
lost.packages=[pack];lost.select.value='wan_animate_2';const firstStart=lost.start('wan_animate_2');await lost.start('wan_animate_2');assert.equal(postCount,1,'Double clicks cannot create duplicate requests');
releasePost();await firstStart;assert.equal(lost.job,'recovered','A lost start response reconnects to the server job');assert.equal(postCount,1);recoveredActive=false;releaseRecovered({phase:'done'});await new Promise(resolve=>setTimeout(resolve,10));lost.dispose();
const offlinePanel=document.createElement('details');document.body.append(offlinePanel);
const offline=new StudioModelDownloads(offlinePanel,async()=>{throw Error('Offline');});offline.packages=[pack];offline.select.value='wan_animate_2';await offline.start('wan_animate_2');assert.equal(offline.uncertain,true);assert.match(offline.progress.textContent,/confirm whether/);assert.ok([...offline.actions.querySelectorAll('button')].some(b=>b.textContent==='Check download status'));offline.dispose();
component.dispose();
// Closing Studio pauses observation, not the server-side download or its setup UI.
const reopenPanel=document.createElement('details');document.body.append(reopenPanel);
let pendingStatus,observations=0,submissions=0;
const reopened=new StudioModelDownloads(reopenPanel,async(path,body)=>{
  if(body){submissions++;throw Error('Must reconnect, never resubmit');}
  if(path==='/model-downloads')return {models:[pack]};
  observations++;return new Promise(resolve=>{pendingStatus=resolve;});
});
reopened.job='running-download';reopened.resume();await Promise.resolve();
reopened.close();assert.equal(reopened.closed,true);assert.ok(reopenPanel.ontoggle);
reopened.resume();reopened.resume();assert.equal(observations,1,'Only one status poll may be in flight');
pendingStatus({phase:'done',done_bytes:1,total_bytes:1});
while(reopened.polling)await new Promise(resolve=>setTimeout(resolve,1));
assert.equal(reopened.job,null);assert.equal(reopened.closed,false);assert.equal(submissions,0);
assert.equal(reopened.progress.textContent,'Download complete.');
reopened.packages=[];reopenPanel.open=true;await reopenPanel.ontoggle();
assert.ok(reopened.packages.length,'Reopening still loads setup through its toggle handler');reopened.dispose();
console.log('Video package sizes, source licences, explicit download, retained setup, single-poll recovery and completion refresh pass.');

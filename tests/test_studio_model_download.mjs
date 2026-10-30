import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioModelDownloads} from '../web/studio_model_download.js';

const {document,window}=parseHTML('<html><body><details id="setup"></details></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value ?? this.querySelector('option')?.value ?? '';},set(value){for(const option of this.querySelectorAll('option')){if(option.value===String(value))option.setAttribute('selected','');else option.removeAttribute('selected');}}});
globalThis.document=document;
const paths=[];
const pack={id:'wan_animate_2',name:'Wan Animate 2',note:'Separate nodes required.',remaining_bytes:1000000000,
  files:[{repo:'Comfy-Org/Wan-Animate-2',filename:'model.safetensors',size_bytes:1000000000,installed:false}]};
const availablePackages=['wan21_relight','wan22_animate_core','wan22_pose','h3_birefnet','h3_head_acceleration','h3_head_adapters','h3_taomate','h3_dmd_ref2va','h3_first_last','ltx25_text_encoder','ltx25_text_int8','ltx25_clean_plate','ltx25_outpaint','ltx25_in_outpaint','ltx_control','h3_int8_vae','h3_control','h3_crossview'];
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
component.packages=[{...pack,files:[{folder:'loras',filename:'required.safetensors',repo:'Comfy-Org/Wan-Animate-2',size_bytes:1000000000,installed:false}]}];
component.setMissingContext('h3_first_last',['required.safetensors','unlisted.safetensors','MissingNode']);
assert.equal(component.select.value,'__workflow__');assert.match(component.files.textContent,/H3 first & last frame/);
assert.match(component.files.textContent,/required.safetensors/);assert.match(component.files.textContent,/unlisted.safetensors/);assert.match(component.files.textContent,/MissingNode/);
assert.equal(component.files.querySelectorAll('.gs-model-package').length,1,'matched files map to their verified package');
component.setMissingContext('ltx_outpaint_long',['LTXVInpaintPreprocess']);
assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href==='https://github.com/Lightricks/ComfyUI-LTXVideo'),'missing LTX nodes link to their verified pack');
component.setMissingContext('h3_head_swap',['MVEx_SubjectCrop','MVEx_SubjectUncrop','LayerUtility: Pad Image Batch to 8n+1','DWPreprocessor','NKDMaskOps','NKDAVLatent','NKDSigmasCurve']);
for(const url of ['https://github.com/drozbay/MaskVidExperiments','https://github.com/chflame163/ComfyUI_LayerStyle','https://github.com/Fannovel16/comfyui_controlnet_aux','https://github.com/Nekodificador/ComfyUI-NKD-Basic-Tools','https://github.com/Nekodificador/ComfyUI-NKD-Sigmas-Curve'])
  assert.ok([...component.files.querySelectorAll('a')].some(a=>a.href===url),`missing head-swap nodes link to ${url}`);
assert.doesNotMatch(component.files.textContent,/Other nodes:/);
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
component.dispose();
console.log('Video package sizes, source licences, explicit download and completion refresh pass.');

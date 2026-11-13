import {runStudioVMInContext} from './studio_vm_fixture.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {HDRSourceTool} from '../web/studio_hdr.js';
import {CreativeWorkspace} from '../web/studio_create.js';
import {IMAGE_MODELS,buildImageGraph,imageAvailability} from '../web/image_recipes.js';
import {ContentDetection} from '../web/studio_content.js';
import {ClipTrimmer} from '../web/studio_trim.js';
import {clipLength,recoverClipLength} from '../web/studio_length.js';
import {stageProgress} from '../web/studio_progress.js';
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
const info={};
for(const m of IMAGE_MODELS)for(const n of Object.values(buildImageGraph({model:m.id,prompt:'test',references:m.minReferences?[{file:'source.png',width:1024,height:1024}]:[]})))info[n.class_type]={input:{required:{}}};
info.UNETLoader.input.required.unet_name=[IMAGE_MODELS.map(m=>m.model)];info.CLIPLoader.input.required={clip_name:[IMAGE_MODELS.flatMap(m=>[m.text,m.upsampler]).filter(Boolean)],type:[IMAGE_MODELS.map(m=>m.type)]};info.VAELoader.input.required.vae_name=[IMAGE_MODELS.map(m=>m.vae)];info.LoraLoaderModelOnly.input.required.lora_name=[IMAGE_MODELS.map(m=>m.lora).filter(Boolean)];
if(info.LoraLoaderBypassModelOnly)info.LoraLoaderBypassModelOnly.input.required.lora_name=[IMAGE_MODELS.map(m=>m.lora).filter(Boolean)];
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
const context={HDRSourceTool,installStudioRestartNavigation,document,window,localStorage,api,app,CreativeWorkspace,ContentDetection,ClipTrimmer,clipLength,recoverClipLength,stageProgress,setTimeout,clearTimeout,setInterval,clearInterval,crypto:globalThis.crypto,URLSearchParams,AbortController,FormData};
vm.createContext(context);
const source=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'').split('app.registerExtension({')[0];
runStudioVMInContext(source+'\nthis.Studio=ArtistStudio;',context);
const studio=new context.Studio(),ui=studio.creative;
const issues=[],counts={};
for(const mode of ['video','image','frames','references','paintout','watermark','outpaint','panorama','hdr','inpaint','objects','relight','viewport','swap']){
if(['inpaint','objects','relight','viewport','swap'].includes(mode))ui.videoComposer.selectWorkflow(mode);else ui.show(mode);
assert.equal(studio.$('models').hidden,ui.mode!=='video','Unrelated workspaces cannot show stale main-video readiness');await new Promise(resolve=>setTimeout(resolve,0));
for(const node of studio.container.querySelectorAll('button,input,select,textarea,progress,summary')){
 if(node.hidden||node.closest('[hidden]')||node.getAttribute('type')==='hidden'||node.getAttribute('aria-hidden')==='true')continue;
 const page=node.closest('.zf-page,.zc-image-page,.zo-page,.zpc-page,.gs-workspace,.gs-top')?.className||'shared';
 counts[page]=(counts[page]||0)+1;
 const label=node.getAttribute('aria-label')||node.getAttribute('aria-labelledby')||node.getAttribute('title')||node.closest('label')?.textContent||(node.id&&studio.container.querySelector(`label[for="${node.id}"]`)?.textContent)||(['BUTTON','SUMMARY'].includes(node.tagName)?node.textContent:'');
 if(!label?.trim())issues.push({mode,page,tag:node.tagName,id:node.id,html:node.outerHTML.slice(0,250)});
}
}
assert.deepEqual(issues,[],'Every mounted workflow control has an accessible name');
assert.equal(calls.filter(c=>c.path==='/prompt').length,0,'The UI audit never submits a generation');
console.log(JSON.stringify({counts,issues},null,2));
studio.close();process.exit(0);

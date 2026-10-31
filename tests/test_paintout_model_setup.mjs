import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';

const {document,window}=parseHTML('<html><body><section id="root"></section></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
window.HTMLCanvasElement.prototype.getContext=()=>({setTransform(){},clearRect(){}});
window.HTMLElement.prototype.pause=()=>{};
const storage={};
Object.assign(globalThis,{document,window,ResizeObserver:class {observe(){} disconnect(){}},localStorage:{getItem(key){return storage[key]||null;},setItem(key,value){storage[key]=value;}}});
const calls=[];
const models=[
  {id:'targeted',name:'Targeted repair',files:[{folder:'diffusion_models',filename:'repair.safetensors',size_bytes:100,installed:false}]},
  {id:'full',name:'Full-scene clean plate',files:[{folder:'loras',filename:'clean.safetensors',size_bytes:50,installed:false}]},
  {id:'hdr_conversion',name:'HDR conversion',files:[{folder:'loras',filename:'hdr.safetensors',size_bytes:25,installed:false}]},
];
const owner={root:document.querySelector('#root'),studio:{close(){}},app:{},api:{clientId:'test',apiURL:p=>p,addEventListener(){},removeEventListener(){}},async fetch(path,body){calls.push({path,body});if(path==='/zura/paintout/model-downloads')return {models};if(path==='/object_info')return {};throw Error(path);}};
const ui=new PaintoutWorkspace(owner);
ui.modelDownloads.positionPanel=()=>{};
assert.equal(ui.modelDownloads.root.querySelector('summary').textContent.trim(),'Models');
ui.modelInfo={};ui.render();
assert.equal(ui.modelDownloads.recommended(),'targeted');
assert.ok(ui.modelDownloads.context.missingNodes.length,'missing nodes come from actual workflow requirements');
await ui.modelDownloads.load();
assert.match(ui.modelDownloads.$('files').textContent,/repair.safetensors/);
ui.state.mode='full';ui.render();assert.equal(ui.modelDownloads.recommended(),'full');
ui.openModelSetup('video');
assert.equal(ui.$('workspace-menu').open,true,'Setup stays inside the shared workspace menu');
assert.equal(ui.modelDownloads.$('package').value,'full');
assert.match(ui.modelDownloads.$('files').textContent,/clean.safetensors/);
ui.modelDownloads.setContext({mode:'full',pipeline:'sdr_hdr'});
assert.equal(ui.modelDownloads.recommended(),'_sdr_hdr');
assert.deepEqual(ui.modelDownloads.models[0].model_ids,['full','hdr_conversion'],'SDR repair plus HDR lists both required packages');
assert.deepEqual(ui.modelDownloads.models[0].files.map(file=>file.filename),['clean.safetensors','hdr.safetensors']);
assert.equal(calls.filter(call=>call.body).length,0,'opening setup never starts a download');
ui.modelDownloads.setContext({mode:'targeted',pipeline:'hdr_hdr',missingNodes:['ZuraPaintoutFrameCrop','SAM3_Detect','LTXVVAEForceFloat32','BlockifyMask','UnknownNode']});
const nodeLinks=[...ui.modelDownloads.$('nodes').querySelectorAll('a')].map(link=>link.href);
for(const url of ['https://github.com/ZURAVFX/ComfyUI_zura_nodes','https://github.com/Comfy-Org/ComfyUI','https://github.com/Lightricks/ComfyUI-LTXVideo','https://github.com/kijai/ComfyUI-KJNodes'])assert.ok(nodeLinks.includes(url),url);
assert.match(ui.modelDownloads.$('nodes').textContent,/built-in nodes/,'SAM3 is a ComfyUI update, not another model download');
assert.match(ui.modelDownloads.$('nodes').textContent,/UnknownNode/,'Unrecognised requirements remain visible');
assert.equal(calls.filter(call=>call.body).length,0,'Setup guidance never installs extensions or submits downloads');
// Delayed cancellation is saved immediately and remains disabled on reopen.
ui.job={id:'own-paintout',started:Date.now(),phase:'complete',config:{source:'shot.mp4',outputMode:'SDR video'}};
let releaseDelete;const deletion=new Promise(resolve=>releaseDelete=resolve),cancelCalls=[];
ui.fetch=async(path,body)=>{cancelCalls.push({path,body});if(path==='/queue')await deletion;return {};};ui.poll=async()=>{};
ui.render();assert.equal(ui.$('cancel').disabled,false);
const pending=ui.cancel();assert.equal(ui.job.cancelPending,true);assert.equal(ui.$('cancel').disabled,true);assert.match(ui.$('progress-title').textContent,/Cancelling/);
await ui.cancel();assert.equal(cancelCalls.filter(call=>call.path==='/queue').length,1,'Repeated clicks do not send a second cancellation');
const reopened=new PaintoutWorkspace({...owner,root:document.createElement('section')});assert.equal(reopened.job.cancelPending,true);assert.equal(reopened.$('cancel').disabled,true,'Saved cancellation stays disabled when the workspace reopens');reopened.close();
releaseDelete();await pending;assert.deepEqual(cancelCalls.find(call=>call.path==='/interrupt').body,{prompt_id:'own-paintout'});
ui.fetch=async()=>{throw Error('offline');};ui.job.cancelPending=false;await ui.cancel();assert.equal(ui.job.cancelPending,false);assert.equal(ui.$('cancel').disabled,false,'An unconfirmed request allows retry');assert.match(ui.$('message').textContent,/Could not confirm cancellation/);
ui.close();
console.log('Integrated Paintout setup tracks the selected workflow without starting downloads.');

import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PanoramaCameraWorkspace} from '../web/studio_panorama.js';
import {StudioModelDownloads} from '../web/studio_model_download.js';
import {groupMissingNodes} from '../web/studio_node_setup.js';

const {document,window}=parseHTML('<html><body><div id="root"></div></body></html>');
Object.assign(globalThis,{document,window,localStorage:{getItem(){return null;},setItem(){}},ResizeObserver:class{observe(){}disconnect(){}}});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const o of this.querySelectorAll('option'))o.toggleAttribute('selected',o.value===value);}});
window.HTMLCanvasElement.prototype.getContext=()=>({setTransform(){},clearRect(){}});
window.HTMLElement.prototype.getBoundingClientRect=()=>({width:960,height:540});
const geometry={folder:'geometry_estimation',filename:'moge_3_vitg_fp16.safetensors',size_bytes:2501605198,installed:false};
const h3={folder:'diffusion_models',filename:'minimax_h3_ref2va_pruned_int8_convrot.safetensors',size_bytes:20970379616,installed:false};
const packs=[{id:'panorama_geometry',name:'MoGe 3',files:[geometry]},{id:'h3_reference_core',name:'H3',files:[h3]}];
let missingNodes=['PanoramaStudio','LoadMoGeModel'],posts=[];
const fetch=async(path,body)=>{
  if(path==='/zura/studio/panorama/status')return {ready:!missingNodes.length&&geometry.installed&&h3.installed,route:'panorama',files:[geometry,h3].map(f=>({...f,ready:f.installed})),missingNodes,errors:[]};
  if(path==='/zura/studio/model-downloads'&&!body)return {models:packs};
  if(path==='/zura/studio/model-downloads'&&body){posts.push(body);return {id:'camera-install'};}
  if(path==='/zura/studio/model-downloads/camera-install'){geometry.installed=h3.installed=true;return {phase:'done'};}
  throw Error(path);
};
const camera=new PanoramaCameraWorkspace({root:document.querySelector('#root'),api:{},app:{},studio:{},fetch});
await camera.open();await camera.modelDownloads.load();
assert.equal(posts.length,0,'Selecting a mode only checks requirements');
assert.equal(camera.modelDownloads.quick.hidden,false);
assert.match(camera.modelDownloads.quick.textContent,/Change camera angle/);
assert.equal(camera.modelDownloads.workflowPlan().manual.length,0,'MoGe is offered as an automatic install');
camera.modelDownloads.quick.querySelector('[data-quick-details]').onclick();
assert.match(camera.modelDownloads.files.textContent,/Panorama/);
assert.equal(groupMissingNodes(missingNodes).unknown.length,0,'Both extension and core update have specific guidance');
await camera.modelDownloads.startWorkflow();
assert.deepEqual(new Set(posts[0].file_keys),new Set([`geometry_estimation/${geometry.filename}`,`diffusion_models/${h3.filename}`]));
assert.equal(camera.$('generate').disabled,true,'Models alone cannot hide a missing extension');
missingNodes=[];camera.state.source={duration:2};
await camera.modelDownloads.quick.querySelector('[data-quick-refresh]').onclick();
assert.equal(camera.status.ready,true);assert.equal(camera.$('generate').disabled,false);
assert.equal(camera.modelDownloads.quick.hidden,true,'Setup clears after the complete mode is ready');
camera.close();

const panel=document.createElement('details');document.body.append(panel);
const setup=new StudioModelDownloads(panel,async()=>({models:packs}),()=>{});
setup.packages=packs;setup.setMissingContext('image',['old.safetensors']);
setup.setContext({route:'panorama',files:[{...geometry,ready:false}],missingNodes:[]});
await setup.load();assert.equal(setup.context.route,'panorama','Catalogue refresh must not restore an older mode');

let approve;setup.access.check=()=>new Promise(resolve=>approve=resolve);
let submitted=false;setup.request=async()=>{submitted=true;throw Error('Must not submit after switching modes');};
const waiting=setup.start('panorama_geometry');
setup.setContext({route:'image',files:[],missingNodes:[]});approve(true);await waiting;
assert.equal(submitted,false,'A late access check cannot start an abandoned mode install');
setup.dispose();
console.log('Fresh camera setup, exact-file install, extension recovery, stale-mode and late-access protection passed.');

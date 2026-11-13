import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';
import {PlateWorkspace} from '../web/studio_plate.js';
import {platePrompt} from '../web/studio_plate_prompts.js';

const {document,window}=parseHTML('<html><head></head><body><main id="genj-studio" data-workspace="paintout"><div class="gs-workspace"></div></main></body></html>');
window.HTMLElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:960,height:540});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(value){this.toggleAttribute('checked',!!value);}});
for(const method of ['pause','load'])window.HTMLElement.prototype[method]=()=>{};
window.HTMLCanvasElement.prototype.getContext=()=>new Proxy({},{get:()=>()=>{}});
const data=new Map(),storage={getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)};
Object.assign(globalThis,{document,window,Event:window.Event,innerWidth:1396,innerHeight:1046,localStorage:storage,ResizeObserver:class{observe(){}disconnect(){}}});
const owner={root:document.querySelector('main'),studio:{close(){}},app:{},storage,mode:'paintout',videoComposer:{syncWorkflow(){}},rippleImage:{request:null,importing:false},items:[],selectedImage:-1,references:[],models:[],
  api:{apiURL:path=>path,addEventListener(){},removeEventListener(){},fetchApi:async()=>({ok:true,json:async()=>({})})},
  fetch:async()=>({}),$(id){return document.querySelector('#zc-'+id)||{value:'',disabled:false};},show(mode){this.mode=mode;}};
const w=new PaintoutWorkspace(owner,{paintoutOnly:true});owner.paintout=w;w.modelInfo={};
w.state.platePrompt='add a fire hydrant';w.state.removalPrompt='replace the car';w.cleanupPrompt='an old unrelated edit';w.prompts.targeted='old backend prompt';
const p=new PlateWorkspace(owner);owner.plate=p;p.attach(w);
// Model discovery and disk persistence are outside this UI-only fixture.
p.ensureRunner=()=>({state:{},checkModels(){}});w.editor.persist=async()=>{};
try{
  assert.equal(w.$('prompt').value,'remove the ');
  assert.equal(w.editor.$('instruction').value,'remove the ');
  // Exercise the actual clean-frame input handler, then the final-render field.
  w.editor.$('instruction').value='remove the parked car and its shadow';w.editor.$('instruction').oninput();
  assert.equal(w.$('prompt').value,'remove the parked car and its shadow');
  w.$('prompt').value='remove the parked car only';w.$('prompt').dispatchEvent(new window.Event('input'));
  assert.equal(w.editor.cleanupInstruction(),'remove the parked car only');
  await p.select('paint');assert.equal(w.$('prompt').value,'');
  w.$('prompt').value='add a fire hydrant';w.$('prompt').dispatchEvent(new window.Event('input'));
  await p.select('replace');assert.equal(w.$('prompt').value,'');
  w.$('prompt').value='replace the car with a Ferrari';w.$('prompt').dispatchEvent(new window.Event('input'));
  await p.select('remove');assert.equal(w.$('prompt').value,'remove the parked car only');
  w.setMode('full');assert.equal(w.$('prompt').value,'remove the parked car only','Backend conditioning changes do not replace operation text');
  await p.select('paint');assert.equal(w.$('prompt').value,'add a fire hydrant');
  await p.select('replace');assert.equal(w.$('prompt').value,'replace the car with a Ferrari');
  w.prompts.inpaint='A saved legacy masked instruction';w.setMode('inpaint');p.syncControls();
  assert.equal(w.$('prompt').value,'A saved legacy masked instruction','Explicit legacy mode keeps its saved instruction');
  assert.equal(w.editor.cleanupInstruction(),'A saved legacy masked instruction');
  assert.equal(p.action,'replace','Compatibility mode does not reclassify the user operation');
  await p.select('remove');assert.equal(w.$('prompt').value,'remove the parked car only');
  assert.equal(w.prompts.inpaint,'A saved legacy masked instruction','Leaving legacy mode preserves its draft for reopening');
  await p.select('paint');w.setMode('inpaint');assert.equal(p.action,'paint','Legacy inpaint must not force a new Add to Replace');
  assert.equal(w.$('prompt').value,'A saved legacy masked instruction');
  await p.select('paint');assert.equal(w.$('prompt').value,'add a fire hydrant','New Add recovers its own draft after legacy access');
  await p.select('replace');assert.equal(w.$('prompt').value,'replace the car with a Ferrari');
  const restored=JSON.parse(JSON.stringify(w.state));assert.equal(platePrompt(restored,'remove'),'remove the parked car only');
  restored.source='a different shot.mp4';assert.equal(platePrompt(restored,'remove'),'remove the ');assert.equal(platePrompt(restored,'paint'),'');
  await w.resetSource();await p.select('remove');assert.equal(w.$('prompt').value,'remove the ');assert.equal(w.editor.cleanupInstruction(),'remove the ');
  await w.reset();assert.equal(w.$('prompt').value,'remove the ','Start over preserves the clear initial Remove instruction');
  // Hydrating a project bypasses setMode. Its explicit backend-mode prompt is
  // retained, but must never seed a fresh Remove operation on leaving it.
  delete w.state.platePrompts;w.state.mode='inpaint';w.prompts.inpaint='Replace the sculpture from this saved project';
  w.editor.hydrateControls();p.syncControls();
  assert.equal(w.$('prompt').value,'Replace the sculpture from this saved project');
  await p.select('remove');assert.equal(w.$('prompt').value,'remove the ');
  assert.equal(w.prompts.inpaint,'Replace the sculpture from this saved project');
}finally{w.close();}
console.log('Real Plate/clean-frame controls: legacy isolation, operation switching, clean-to-render prompt sync, save/reload, new-shot and reset defaults pass.');

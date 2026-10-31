import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutModels} from '../web/paintout_studio/paintout_models.js';

const {document,window}=parseHTML('<html><body><section><div class="zf-heading"></div></section></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
Object.assign(globalThis,{document,window});
const models=[{id:'targeted',name:'Targeted repair',files:[{filename:'model.safetensors',installed:false}],remaining_bytes:100}];
let posts=0,finish,offline=false,active=null;
const w={page:document.querySelector('section'),async fetch(path,body){
  if(body){posts++;return new Promise(resolve=>finish=resolve);}
  if(offline)throw Error('Connection lost');
  return {models,active};
}};
const ui=new PaintoutModels(w);await ui.load();
const pending=ui.start();await ui.start();assert.equal(posts,1,'Repeated clicks cannot submit twice');
finish({id:'accepted'});await pending;assert.equal(ui.job.id,'accepted');

ui.job=null;ui.w.fetch=async(path,body)=>{if(body){posts++;throw Error('Start response lost');}return {models,active:{id:'running',phase:'downloading'}};};
await ui.start();assert.equal(ui.job.id,'running');assert.equal(ui.error,'');assert.equal(posts,2,'Lost responses reconnect without a second POST');

ui.job=null;ui.w.fetch=async(path,body)=>{if(body)posts++;throw Error('Offline');};
await ui.start();assert.equal(ui.submissionUnknown,true);assert.equal(posts,3);assert.match(ui.$('status').textContent,/may have started/);assert.match(ui.$('download').textContent,/Check download status/);
await ui.start();assert.equal(posts,3,'An uncertain submission permits only a status check');
ui.w.fetch=async()=>({models,active:{id:'recovered',phase:'verifying'}});
await ui.start();assert.equal(ui.job.id,'recovered');assert.equal(ui.submissionUnknown,false);assert.equal(posts,3);
ui.destroy();
console.log('Paintout downloads prevent duplicate starts and recover lost start responses, including an offline retry.');

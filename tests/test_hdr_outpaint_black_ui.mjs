import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {OutpaintWorkspace} from '../web/studio_outpaint.js';

const {document,window}=parseHTML('<html><body><div id="genj-studio"></div></body></html>');
globalThis.document=document;
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},
  set(value){for(const option of this.querySelectorAll('option'))option.selected=option.value===String(value);}});
for(const name of ['load','pause','play'])window.HTMLElement.prototype[name]=()=>{};
const requests=[];
const owner={root:document.querySelector('#genj-studio'),api:{clientId:'test',apiURL:u=>u,addEventListener(){},removeEventListener(){}},show(){},openHDR(){},
  async fetch(path,body){requests.push({path,body});if(path==='/zura/studio/outpaint/review')return {id:'review',kind:'review',state:'queued'};throw Error(path);}};
const ui=new OutpaintWorkspace(owner);
ui.capabilities={hdr_expand_experiment:true,hdr_expand_long_experiment:true,hdr_black_experiment:true,
  hdr_black_long_experiment:true,hdr_black_dependencies:{ready:false,missing_files:['inpaint.safetensors'],missing_nodes:['CropMask']},
  hdr_black_long_dependencies:{ready:true,missing_files:[],missing_nodes:[]},
  hdr_expand_dependencies:{ready:true,missing_files:[],missing_nodes:[]}};
ui.source={id:'hdr-source',file:'input.mov',name:'input.mov',width:190,height:130,duration:10};
ui.isHDRSource=true;ui.sourceColour='pq_rec2020';ui.$('hdr-output').checked=true;
ui.$('mode').value='black';ui.$('mode').onchange();
assert.equal(ui.mode,'black');assert.equal(ui.$('hdr-output').checked,true,'HDR input remains HDR');
assert.equal(ui.$('hdr-option').hidden,false);assert.deepEqual(ui.dimensions(),{width:190,height:130});
assert.deepEqual(ui.box,{left:0,top:0,right:0,bottom:0});
assert.equal(ui.$('review').disabled,true,'Missing black-specific models cannot look ready');
assert.match(ui.$('method-info').textContent,/setup is incomplete/);
assert.equal(ui.modelDownloads.context.files[0].filename,'inpaint.safetensors');
assert.deepEqual(ui.modelDownloads.context.missingNodes,['CropMask']);
ui.capabilities.hdr_black_dependencies={ready:true,missing_files:[],missing_nodes:[]};ui.paint();
assert.equal(ui.$('review').disabled,false);assert.match(ui.$('method-info').textContent,/black-area preview/);
assert.match(ui.$('help').textContent,/dark clothing or shadows/);
ui.trim.commit({start:.5,duration:1});ui.poll=()=>{};
await ui.reviewSelection();
const submitted=requests.find(r=>r.path==='/zura/studio/outpaint/review').body;
assert.deepEqual({mode:submitted.mode,hdr:submitted.hdr,colour:submitted.colour_space,width:submitted.width,height:submitted.height,start:submitted.start,duration:submitted.duration},
  {mode:'black',hdr:true,colour:'pq_rec2020',width:190,height:130,start:.5,duration:1});
assert.equal(submitted.black_threshold,2/255);assert.equal(submitted.strategy,undefined);
ui.job=null;ui.trim.longMode.checked=true;ui.trim.commit({start:0,duration:5});ui.paint();
assert.equal(ui.trim.long,true);assert.equal(ui.config().strategy,'hdr_long');
assert.equal(ui.modelDownloads.context.route,'ltx_outpaint_hdr_long');
ui.capabilities.hdr_black_long_experiment=false;ui.trim.modeChanged();ui.paint();
assert.equal(ui.trim.long,false,'The long HDR black route requires its capability');
ui.capabilities.hdr_black_experiment=false;ui.$('mode').value='black';ui.$('mode').onchange();
assert.equal(ui.mode,'expand');assert.equal(ui.$('hdr-output').checked,true,'An unavailable method cannot silently turn HDR off');
ui.isHDRSource=false;ui.$('mode').value='black';ui.$('mode').onchange();
assert.equal(ui.mode,'black');assert.equal(ui.$('hdr-output').checked,false,'Existing SDR black behaviour is retained');
ui.dispose();
console.log('HDR black selection, setup gating, long capability, request and SDR fallback pass.');

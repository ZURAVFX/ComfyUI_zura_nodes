import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';
import {studioModeAdapter} from '../web/studio_mode_adapters.js';

const {document,window}=parseHTML('<html><head></head><body><main id="genj-studio"><div class="gs-workspace"></div></main></body></html>');
window.HTMLElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:960,height:540});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(value){this.toggleAttribute('checked',!!value);}});
for(const method of ['pause','load'])window.HTMLElement.prototype[method]=()=>{};
window.HTMLCanvasElement.prototype.getContext=()=>new Proxy({},{get:()=>()=>{}});
const store=new Map(),storage={getItem:key=>store.get(key)||null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)};
Object.assign(globalThis,{document,window,Event:window.Event,innerWidth:1396,innerHeight:1046,localStorage:storage,ResizeObserver:class{observe(){}disconnect(){}}});
const owner={root:document.querySelector('main'),studio:{close(){}},app:{},storage,mode:'paintout',
  api:{apiURL:path=>path,addEventListener(){},removeEventListener(){},fetchApi:async()=>({ok:true,json:async()=>({})})},fetch:async()=>({})};
const w=new PaintoutWorkspace(owner,{paintoutOnly:true});owner.paintout=w;w.modelInfo={};
const master={filename:'paintout_SDR_10bit.mp4',subfolder:'paintout/studio_0007',type:'output'},preview={filename:'motion_preview_SDR.mp4',subfolder:'paintout/studio_0007',type:'output'};
const usedMask={filename:'used_mask.mov',subfolder:master.subfolder,type:'output'},maskFrames={filename:'used_mask_png16.zip',subfolder:master.subfolder,type:'output'};
const config={...w.config(),source:'',outputMode:'SDR video'};
const filename=url=>new URL(url,'http://fixture.invalid').searchParams.get('filename');
try{
  w.job={id:'result-job',config,phase:'complete'};
  w.fetch=async path=>{assert.equal(path,'/history/result-job');return {'result-job':{status:{completed:true,status_str:'success'},outputs:{save:{images:[master,preview],zura_exports:[{role:'mask',file:usedMask},{role:'mask_sequence',file:maskFrames}],text:['Saved 18 frames']}}}};};
  await w.poll();
  assert.equal(w.job,null);assert.deepEqual(w.result.preview,preview);assert.deepEqual(w.result.master,master);
  assert.equal(w.result.exports.length,2,'Returned matte exports are retained with the result');assert.equal(w.items[0].exports[0].file.filename,usedMask.filename);
  assert.equal(w.resultExportsRow.querySelector('[data-result-export=mask]').download,usedMask.filename,'The finished result exposes its actual processing mask');
  assert.equal(filename(w.$('video').src),preview.filename,'Viewport uses the actual paired browser-compatible output');
  assert.equal(filename(w.$('download').href),master.filename,'Download remains the 10-bit master');
  assert.equal(studioModeAdapter('paintout').getSelectedOutput(owner).master.filename,master.filename,'AE receives the master');
  // Saved history keeps the explicit preview even if a generic result consumer
  // normalises file to the master. Never fabricate a companion filename.
  w.result=JSON.parse(JSON.stringify(w.items[0]));w.result.file={...master};w.preview('result');
  assert.equal(filename(w.$('video').src),preview.filename);
  w.sourceInfo={media_url:'/source.mp4',kind:'video',fps:29.97};let comparison;
  w.comparison={hide(){},show(...args){comparison=args;}};w.compare();assert.equal(filename(comparison[1]),preview.filename);
  delete w.result.preview;w.preview('result');assert.equal(filename(w.$('video').src),preview.filename,'Explicit returned files also retain preview provenance');
  delete w.result.files;w.preview('result');assert.equal(filename(w.$('video').src),master.filename,'A master-only legacy result cannot invent an unreturned preview');
  assert.equal(studioModeAdapter('paintout').getSelectedOutput(owner).master.filename,master.filename);
  async function complete(files,outputMode='SDR video'){
    w.sourceInfo=null;w.job={id:'next-job',config:{...config,outputMode},phase:'complete'};
    w.fetch=async()=>({'next-job':{status:{completed:true,status_str:'success'},outputs:{save:{images:files,text:['Saved result']}}}});
    await w.poll();
  }
  await complete([preview,master]);assert.deepEqual(w.result.master,master,'Output order never decides the delivery master');
  await complete([preview]);assert.equal(w.result.master,null);assert.equal(w.result.sdrMaster,null);assert.equal(w.result.hdrMaster,null);
  assert.equal(filename(w.$('video').src),preview.filename);assert.equal(w.$('download').hidden,true);assert.equal(w.$('download').hasAttribute('href'),false);
  assert.equal(studioModeAdapter('paintout').getSelectedOutput(owner),null);assert.match(w.$('message').textContent,/master was not returned.*retained/);
  const hlg={filename:'paintout_HLG_10bit.mp4',subfolder:master.subfolder,type:'output'},exr={filename:'paintout_EXR.zip',subfolder:master.subfolder,type:'output'};
  for(const files of [[preview,hlg,exr],[exr,hlg,preview]]){
    await complete(files,'EXR + HLG video');assert.deepEqual(w.result.preview,preview);assert.deepEqual(w.result.hdrMaster,exr);assert.deepEqual(w.result.master,exr);
    assert.equal(filename(w.$('video').src),preview.filename);assert.equal(filename(w.$('download').href),exr.filename);
    let returned=studioModeAdapter('paintout').getSelectedOutput(owner);assert.equal(returned.master.filename,exr.filename);assert.equal(returned.kind,'hdr_sequence');
    owner.outputSettings={delivery:{readingOutput:true}};
    const raw=studioModeAdapter('paintout').getSelectedOutput(owner);assert.equal(raw.files.length,3,'Delivery selection retains all explicit asset roles');assert.equal(raw.sdrMaster,null);assert.equal(raw.hdrMaster.filename,exr.filename);
    owner.outputSettings.delivery={output:'hdr',hdrFormat:'hlg_video'};
    returned=studioModeAdapter('paintout').getSelectedOutput(owner);assert.equal(returned.master.filename,hlg.filename);assert.equal(returned.colour.encoding,'hlg_rec2020');
    owner.outputSettings.delivery={output:'sdr',outputFor(){throw Error('A display preview must not be promoted to SDR master');}};
    assert.equal(studioModeAdapter('paintout').getSelectedOutput(owner),null,'HDR-to-SDR selection requires an actual SDR master');delete owner.outputSettings;
  }
  await complete([preview,hlg,exr],'HLG video');assert.equal(w.result.master.filename,hlg.filename);
  await complete([exr],'EXR sequence');assert.equal(w.result.master.filename,exr.filename);assert.equal(w.$('video').hidden,true,'EXR archives are never loaded as browser video');
  await complete([preview],'EXR + HLG video');assert.equal(studioModeAdapter('paintout').getSelectedOutput(owner),null,'An 8-bit preview cannot be labelled HDR');
  await complete([preview,master]);w.result.colour={encoding:'acescg',sceneLinear:true};
  assert.equal(studioModeAdapter('paintout').getSelectedOutput(owner).colour,undefined,'Stale HDR metadata cannot relabel the returned SDR master');
  // Repair old records whose fallback incorrectly put the preview in master.
  w.result={file:preview,master:preview,config};w.render();assert.equal(w.resultMasterFile(),null);assert.equal(w.$('download').hidden,true);assert.equal(studioModeAdapter('paintout').getSelectedOutput(owner),null);
}finally{w.close();}
console.log('Paintout paired outputs: live result, saved history and comparison use the explicit 8-bit preview; download and AE retain the 10-bit master.');

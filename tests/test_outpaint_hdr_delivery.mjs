import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {OutpaintWorkspace} from '../web/studio_outpaint.js';
import {outpaintHDRTake} from '../web/studio_outpaint_hdr.js';

const {document,window}=parseHTML('<html><body><div id="genj-studio"></div></body></html>');
globalThis.document=document;globalThis.window=window;
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
for(const name of ['load','pause','play'])window.HTMLElement.prototype[name]=()=>{};
const storage=new Map();globalThis.localStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
const artifact={filename:'render_00001_.mp4',subfolder:'genj/outpaint',type:'output'};
const raster={width:1280,height:704,frames:73,fps:24,has_audio:true};
const base={id:'outpaint1',kind:'render',state:'complete',hdr:false,artifact,output_raster:raster};
assert.equal(outpaintHDRTake({...base,kind:'review'},'hlg_video'),null);
assert.equal(outpaintHDRTake({...base,hdr:true},'hlg_video'),null);
assert.equal(outpaintHDRTake({...base,output_raster:null},'hlg_video'),null);
assert.equal(outpaintHDRTake({...base,artifact:{...artifact,subfolder:'../unsafe'}},'hlg_video'),null);
assert.equal(outpaintHDRTake({...base,output_raster:{...raster,has_audio:undefined}},'hlg_video'),null);

const calls=[];let ready=false,hdrState='rendering',renderState=base;
const preview={filename:'view.mp4',subfolder:'genj/hdr',type:'output'};
const hlg={filename:'master.mp4',subfolder:'genj/hdr',type:'output'};
const exr={filename:'frames.zip',subfolder:'genj/hdr',type:'output'};
const api={apiURL:p=>p,clientId:'outpaint-test',addEventListener(){},removeEventListener(){},async fetchApi(path,options){
  const body=options?.body?JSON.parse(options.body):undefined;calls.push({path,body});
  const data=path.includes('/readiness?')?{ready,longPreview:true,files:[{filename:'hdr-adapter.safetensors',ready}],missingNodes:[]}:
    path==='/zura/studio/hdr/jobs'?{id:'hdr-job',state:'rendering',active_prompt_id:'owned-prompt',total:2,completed:0}:
    path.endsWith('/cancel')?{state:'cancelling'}:
    path.endsWith('/jobs/hdr-job')?{id:'hdr-job',state:hdrState,active_prompt_id:'owned-prompt',total:2,completed:0,
      ...(hdrState==='complete'?{result:{preview,files:[hlg,exr]}}:{})}:{};
  return {ok:true,json:async()=>data};
}};
const owner={root:document.querySelector('#genj-studio'),api,show(){},async fetch(path,body){
  calls.push({path,body});
  if(path.endsWith('/approve'))return {approved:true};
  if(path.endsWith('/render'))return {id:renderState.id,kind:'render',state:'queued'};
  if(path.endsWith('/delivery'))return {artifact:renderState.artifact,output_raster:renderState.output_raster};
  if(path.endsWith('/jobs/'+renderState.id))return {...renderState,url:'/view?render=1'};
  if(path.endsWith('/capabilities'))return {anchored_masked:true,short_dependencies:{expand:{missing_files:[],missing_nodes:[]},black:{missing_files:[],missing_nodes:[]}}};
  throw Error(path);
}};
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
const ui=new OutpaintWorkspace(owner);ui.closed=false;
ui.source={id:'a'.repeat(32),width:768,height:432,duration:4};ui.reframe();ui.trim.initial();
ui.capabilities={short_dependencies:{expand:{missing_files:[],missing_nodes:[]},black:{missing_files:[],missing_nodes:[]}}};
ui.$('delivery').value='hlg_and_exr';ui.$('delivery').onchange();
assert.equal(ui.$('delivery-note').hidden,false);
assert.equal(ui.$('hdr-option').hidden,true,'SDR input has one output selector, not a second HDR checkbox');
ui.review={id:'review1',hdr:false};await ui.generate();
assert.ok(!calls.some(c=>c.path.endsWith('/approve')),'Missing HDR setup stops before outpaint generation');
assert.match(ui.$('status').textContent,/hdr-adapter/);
assert.ok(ui.modelDownloads.context.files.some(f=>f.filename==='hdr-adapter.safetensors'),'Missing HDR model is included in setup');
ready=true;calls.length=0;await ui.generate();await tick();await tick();
assert.equal(calls.filter(c=>c.path.endsWith('/delivery')).length,1);
const conversion=calls.find(c=>c.path==='/zura/studio/hdr/jobs');
assert.deepEqual(conversion.body.output_ref,artifact);
assert.equal(conversion.body.frame_count,73,'The inspected final count, not the selection, drives conversion');
assert.equal(ui.hdrDelivery.busy,true);assert.equal(ui.$('progress-wrap').hidden,false);
assert.equal(ui.trim.container.hasAttribute('inert'),true,'The trim timeline cannot change while HDR delivery runs');
const previousDuration=ui.$('duration').value;ui.trim.commit({start:0,duration:1});assert.equal(ui.$('duration').value,previousDuration);
ui.dragStart({pointerId:1,clientX:0,clientY:0,preventDefault(){assert.fail('A busy canvas must not capture a drag');}});assert.equal(ui.drag,undefined);
assert.equal(ui.invalidate(),false,'An active conversion cannot be silently discarded');assert.throws(()=>ui.setSourceAsset({id:'new',file:'new.mp4'}),/HDR delivery/);
ui.progress({detail:{prompt_id:'unrelated',node:'hdr_sample',value:4,max:8}});assert.doesNotMatch(ui.$('status').textContent,/step 4/);
ui.progress({detail:{prompt_id:'owned-prompt',node:'hdr_sample',value:4,max:8}});assert.match(ui.$('status').textContent,/step 4 of 8/);
ui.close();ui.open();await tick();assert.equal(calls.filter(c=>c.path==='/zura/studio/hdr/jobs').length,1,'Reopening reconnects without resubmitting');
hdrState='complete';await ui.hdrDelivery.client.poll();
assert.equal(ui.$('download').hidden,false);assert.equal(ui.$('download-exr').hidden,false);assert.equal(ui.$('download-sdr').hidden,false);
assert.match(ui.result.src,/view.mp4/);assert.match(ui.$('status').textContent,/preview is SDR/);
ui.$('width').value='1280';ui.$('width').oninput();
assert.equal(ui.hdrRecord,null,'Changing canvas geometry releases the previous result');
assert.equal(storage.has('zura-outpaint-hdr-record'),false);assert.equal(ui.$('download-sdr').hidden,true);
ui.close();ui.open();await tick();assert.equal(ui.result.hidden,true,'Reopening cannot restore a result from prior geometry');
const completedTake={file:preview,sdrFile:artifact,hdrFiles:[hlg,exr]};ui.hdrRecord={state:'complete',take:completedTake};ui.saveHDR();ui.showHDR(completedTake);
ui.$('delivery').value='sdr';ui.review={id:'new-review',hdr:false};
const regularFetch=ui.fetch.bind(ui);ui.fetch=async(path,body)=>path.endsWith('/jobs/outpaint1')?new Promise(()=>{}):regularFetch(path,body);
await ui.generate();
assert.equal(ui.hdrRecord,null,'Starting another render clears the previous HDR record');
assert.equal(ui.$('download').hidden,true);assert.equal(ui.$('download-exr').hidden,true);assert.equal(ui.$('download-sdr').hidden,true);
const lockedDuration=ui.$('duration').value;ui.trim.commit({start:0,duration:1});assert.equal(ui.$('duration').value,lockedDuration,'A captured pointer cannot change the source range during rendering');
ui.close();ui.open();await tick();assert.equal(ui.hdrRecord,null,'A pending SDR render cannot restore an older HDR take');
ui.close();storage.clear();calls.length=0;

// Black-area mode uses the same verified conversion path. A missing receipt
// preserves the SDR output and never queues a conversion.
const ui2=new OutpaintWorkspace(owner);ui2.closed=false;ui2.source={id:'b'.repeat(32),width:768,height:432,duration:4};ui2.$('mode').value='black';ui2.reframe();ui2.trim.initial();ui2.$('delivery').value='hlg_video';
ui2.review={id:'review2',hdr:false};renderState={...base,id:'outpaint2',output_raster:null};await ui2.generate();await tick();await tick();
assert.ok(!calls.some(c=>c.path==='/zura/studio/hdr/jobs'));assert.equal(ui2.$('download').hidden,false);assert.match(ui2.$('status').textContent,/SDR video is available/);
renderState={...base,id:'outpaint3'};ui2.review={id:'review3',hdr:false};calls.length=0;hdrState='rendering';await ui2.generate();await tick();await tick();
assert.deepEqual(calls.find(c=>c.path==='/zura/studio/hdr/jobs').body.output_ref,artifact);
await ui2.cancel();assert.ok(calls.some(c=>c.path.endsWith('/jobs/hdr-job/cancel')));
hdrState='failed';await ui2.hdrDelivery.client.poll();ui2.close();ui2.open();await tick();
assert.equal(ui2.$('download').hidden,false,'A failed conversion restores the SDR video when reopened');
assert.equal(ui2.$('retry-hdr').hidden,false,'A confirmed failure offers an explicit retry');
assert.equal(calls.filter(c=>c.path==='/zura/studio/hdr/jobs').length,1,'A failed conversion never retries itself');
ui2.$('hdr-output').checked=true;ui2.setSourceAsset({id:'native',file:'genj_studio/native.mov',name:'native.mov',width:768,height:432,duration:2},'pq_rec2020',true);
assert.equal(ui2.hdrRecord,null,'Changing the source clears a failed older take and its retry state');assert.equal(ui2.$('retry-hdr').hidden,true);
ui2.$('hdr-output').checked=false;assert.throws(()=>ui2.config(),/HDR input requires/,'An imported HDR source cannot silently use an SDR route');
ui.dispose();ui2.dispose();storage.clear();calls.length=0;
const uncertain={resultKey:'uncertain',file:artifact,sdrFile:artifact,config:{engine:'ltx',hdrOutput:'hlg_video',frames:73,width:1280,height:704,seed:42}};
storage.set('zura-outpaint-hdr-take',JSON.stringify(uncertain));storage.set('zura-outpaint-hdr-record',JSON.stringify({state:'preparing',take:uncertain}));
const ui3=new OutpaintWorkspace(owner);ui3.open();await tick();
assert.equal(ui3.hdrRecord.state,'unknown','An interrupted submission without a recovery ID is not retried');
assert.equal(ui3.$('download').hidden,false);assert.equal(ui3.$('retry-hdr').hidden,true);
assert.ok(!calls.some(c=>c.path==='/zura/studio/hdr/jobs'));ui3.dispose();
console.log('PASS outpaint HDR delivery: both methods, setup, validated raster, owned progress, recovery, cancellation and retained SDR.');

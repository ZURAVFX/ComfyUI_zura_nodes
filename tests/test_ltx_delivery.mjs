import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {LTXHDRDelivery} from '../web/studio_ltx_delivery.js';
import {FrameVideoWorkspace} from '../web/studio_frames.js';

const {document,window}=parseHTML('<html><body><main></main></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
globalThis.document=document;globalThis.window=window;
const store=new Map();globalThis.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k)};
const calls=[];let ready=true,enabled=true,state='rendering';
const preview={filename:'hdr-preview.mp4',subfolder:'genj/hdr',type:'output'},master={...preview,filename:'hdr-master.mp4'},exr={...preview,filename:'hdr.zip'};
const api={apiURL:p=>p,clientId:'delivery-test',addEventListener(){},async fetchApi(path,options){
  const body=options?.body?JSON.parse(options.body):undefined;calls.push({path,body});
  const data=path.includes('/readiness?')?{ready,longPreview:enabled,files:[{filename:'hdr-adapter.safetensors',ready}]}:
    path.endsWith('/cancel')?{id:'hdr-1',state:'cancelling'}:
    path==='/zura/studio/hdr/jobs'?{id:'hdr-1',state:'rendering',active_prompt_id:'hdr-prompt',completed:0,total:2}:
    path.endsWith('/jobs/hdr-1')?{id:'hdr-1',state,active_prompt_id:'hdr-prompt',completed:0,total:2,...(state==='complete'?{result:{preview,files:[master,exr]}}:{})}:{};
  return {ok:true,json:async()=>data};
}};
const config={engine:'ltx',hdrOutput:'hlg_and_exr',frames:73,width:1344,height:768,seed:42,prompt:'A calm camera move.'};
const take={file:{filename:'sdr.mp4',subfolder:'zura/first_last',type:'output'},config};
const stages=[],complete=[];
const delivery=new LTXHDRDelivery(api,{key:'isolated-delivery',onUpdate:j=>stages.push(j.state),onComplete:t=>complete.push(t)});
await delivery.preflight({...config,engine:'h3'});assert.equal(calls.length,0,'H3 never invokes HDR setup');
ready=false;await assert.rejects(delivery.preflight(config),/hdr-adapter/);assert.ok(!calls.some(c=>c.path.endsWith('/jobs')),'Missing HDR models fail before queuing');
ready=true;enabled=false;await assert.rejects(delivery.preflight(config),/disabled/);enabled=true;
await delivery.preflight(config);await delivery.start(take);
assert.equal(delivery.busy,true);assert.equal(calls.filter(c=>c.path==='/zura/studio/hdr/jobs').length,1);
assert.equal(calls.find(c=>c.path==='/zura/studio/hdr/jobs').body.colour_space,'srgb_display');
assert.equal(calls.find(c=>c.path==='/zura/studio/hdr/jobs').body.seed,42);
assert.deepEqual(calls.find(c=>c.path==='/zura/studio/hdr/jobs').body.output_ref,take.file);
assert.ok(store.get('isolated-delivery-job'));assert.equal(store.has('zura-hdr-long-job'),false,'Separate workspaces cannot steal the converter’s recovery key');
delivery.close();const restored=new LTXHDRDelivery(api,{key:'isolated-delivery',onUpdate:j=>stages.push(j.state),onComplete:t=>complete.push(t)});
restored.resume();assert.equal(restored.busy,true);assert.equal(calls.filter(c=>c.path==='/zura/studio/hdr/jobs').length,1,'Reopening only reconnects');
await restored.cancel();assert.ok(calls.some(c=>c.path==='/zura/studio/hdr/jobs/hdr-1/cancel'));assert.equal(restored.busy,true,'Cancel waits for the authoritative job');
restored.cancelRequested=false;state='complete';await restored.client.poll();restored.close();
assert.equal(complete.length,1);assert.equal(complete[0].file,preview);assert.deepEqual(complete[0].hdrFiles,[master,exr]);assert.equal(restored.busy,false);assert.equal(store.has('isolated-delivery-take'),false);

// Exercise the workspace's actual completed-generation -> HDR -> displayed take.
state='rendering';const owner={api,root:document.querySelector('main'),studio:{},app:{},fetch:async path=>path==='/history/video-1'?{'video-1':{status:{completed:true},outputs:{save:{images:[take.file]}}}}:{}};
const ui=new FrameVideoWorkspace(owner);ui.$('engine').value='ltx';ui.$('output').value='hlg_and_exr';ui.assets.first={file:'first.png'};ui.$('prompt').value=config.prompt;ui.availability={ready:true,missing:[]};ui.render();
assert.equal(ui.$('output-control').hidden,false);assert.equal(ui.config().hdrOutput,'hlg_and_exr');
ui.job={id:'video-1',config};await ui.poll();
assert.equal(ui.job,null);assert.equal(ui.hdrOutput.busy,true);assert.equal(ui.$('generate').disabled,true);assert.equal(ui.$('progress').hidden,false);
assert.ok(ui.items.some(item=>item.file.filename==='sdr.mp4'),'The SDR master survives the conversion');
ui.hdrProgress({prompt_id:'unrelated',value:3,max:8});assert.doesNotMatch(ui.$('progress-detail').textContent,/Step 3/);
ui.hdrProgress({prompt_id:'hdr-prompt',node:'hdr_sample',value:3,max:8});assert.match(ui.$('progress-detail').textContent,/Step 3 of 8/);
state='complete';await ui.hdrOutput.client.poll();
assert.equal(ui.selectedResult.filename,'hdr-preview.mp4');assert.equal(ui.$('hdr-downloads').hidden,false);assert.equal(ui.$('hdr-downloads').querySelectorAll('a').length,2);assert.equal(ui.$('convert-hdr').hidden,true);
assert.match(ui.$('message').textContent,/on-screen preview is SDR/);assert.equal(ui.$('generate').disabled,false);
ui.$('engine').value='h3';ui.render();assert.equal(ui.$('output-control').hidden,true);assert.equal(ui.config().hdrOutput,'sdr');ui.close();delivery.close();

// Cancellation during acceptance is remembered; a network rejection requires
// an explicit retry rather than an unbounded automatic cancel loop.
let accept,cancelCalls=0;
const pendingAPI={clientId:'pending-test',async fetchApi(path){
  if(path==='/zura/studio/hdr/jobs')return new Promise(resolve=>{accept=()=>resolve({ok:true,json:async()=>({id:'pending-job',state:'queued'})});});
  if(path.endsWith('/cancel')){cancelCalls++;return {ok:cancelCalls>1,status:503,json:async()=>cancelCalls>1?{state:'cancelling'}:{error:'Temporary cancellation failure'}};}
  return {ok:true,json:async()=>({id:'pending-job',state:'rendering'})};
}};
const pendingStates=[];const pending=new LTXHDRDelivery(pendingAPI,{key:'pending-delivery',onUpdate:j=>pendingStates.push(j.state),onComplete:()=>assert.fail('Cancelled acceptance cannot publish a result')});
const accepting=pending.start(take);await pending.cancel();assert.equal(cancelCalls,0);accept();await accepting;
await new Promise(resolve=>setImmediate(resolve));
assert.equal(cancelCalls,1);assert.ok(pendingStates.includes('cancel-error'));assert.equal(pending.busy,true);
await pending.cancel();assert.equal(cancelCalls,2);pending.update({state:'cancelled'});pending.client.finish();pending.close();
console.log('PASS inline LTX HDR delivery: setup, isolated recovery, authoritative cancel, preserved SDR, progress and displayed HDR downloads.');

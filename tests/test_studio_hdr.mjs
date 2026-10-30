import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {HDRSourceTool} from '../web/studio_hdr.js';
const {document,window}=parseHTML('<html><body><div id="host"></div></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const o of this.querySelectorAll('option')){if(o.value===String(value))o.setAttribute('selected','');else o.removeAttribute('selected');}}});
globalThis.document=document;
const calls=[];
const outputs={
  zura_hdr_save_preview:{images:[{filename:'preview.mp4',subfolder:'genj/hdr',type:'output'}]},
  zura_hdr_save_video:{images:[{filename:'hdr.mp4',subfolder:'genj/hdr',type:'output'}]},
  zura_hdr_archive:{files:[{filename:'sequence.zip',subfolder:'genj/hdr',type:'output'}]}
};
const api={apiURL:p=>p,clientId:'test',addEventListener(){},removeEventListener(){},async fetchApi(path,options){
  calls.push([path,options?.body&&JSON.parse(options.body)]);
  const data=path.startsWith('/zura/studio/hdr/readiness?')?{route:path.includes('mode=native')?'hdr_native':'hdr_sdr',files:[{folder:'vae',filename:'needed.safetensors',ready:false}],missingNodes:['LTXVInpaintPreprocess']}:path==='/zura/studio/model-downloads'?{models:['ltx25_sdr_hdr','ltx25_refine'].map(id=>({id,name:id,files:[],remaining_bytes:0}))}:path==='/zura/studio/hdr/graph'||path==='/zura/studio/hdr/native-graph'?{graph:{verified:true}}:path==='/prompt'?{prompt_id:'job-1'}:path==='/history/job-1'?{'job-1':{status:{status_str:'success'},outputs}}:{};
  return {ok:true,async json(){return data;}};
}};
const tool=new HDRSourceTool(document.querySelector('#host'),api,()=>({id:'source-id',projectId:'project-id'}));
const outputTool=new HDRSourceTool(document.querySelector('#host'),api,()=>({}));
const chosenOutput={type:'output',subfolder:'zura/first_last',filename:'take.mp4'},outputCalls=[];
outputTool.request=async(path,body)=>{outputCalls.push([path,body]);return path==='/prompt'?{prompt_id:'output-test'}:{graph:{}};};outputTool.poll=()=>{};
outputTool.setOutput(chosenOutput);assert.equal(outputTool.$('source-kind').value,'output');await outputTool.start();
assert.equal(outputCalls[0][1].source_kind,'output');assert.deepEqual(outputCalls[0][1].output_ref,chosenOutput);outputTool.finish();outputTool.close();
const ownApi={...api,async fetchApi(path,options){assert.equal(path,'/zura/studio/upload?kind=video');assert.equal(options.method,'POST');return {ok:true,json:async()=>({id:'uploaded-hdr-video',name:'own.mp4',width:512,height:288})};}};
const ownTool=new HDRSourceTool(document.querySelector('#host'),ownApi,()=>({})),ownCalls=[];
ownTool.$('source-kind').value='own';ownTool.updateMode();await ownTool.uploadVideo(new Blob(['video'],{type:'video/mp4'}));
assert.equal(ownTool.$('video-name').textContent,'own.mp4');ownTool.request=async(path,body)=>{ownCalls.push([path,body]);return path==='/prompt'?{prompt_id:'own-test'}:{graph:{}};};ownTool.poll=()=>{};
await ownTool.start();assert.equal(ownCalls[0][1].source_kind,'upload');assert.equal(ownCalls[0][1].source_id,'uploaded-hdr-video');ownTool.finish();ownTool.close();
const gated=new HDRSourceTool(document.querySelector('#host'),api,()=>({id:'source-id'}));
gated.models.packages=[{id:'existing'}];
gated.request=async()=>({route:'hdr_sdr',files:[],missingNodes:[],longPreview:true});
await gated.refreshModelSetup();assert.equal(gated.$('long-control').hidden,false);assert.match(gated.$('long-control').textContent,/preview/);
gated.request=async()=>({route:'hdr_sdr',files:[],missingNodes:[],longPreview:false});
await gated.refreshModelSetup();assert.equal(gated.$('long-control').hidden,true);assert.equal(gated.$('long').checked,false);gated.close();
assert.equal(tool.$('models').querySelector('summary').textContent,'HDR model packages');
assert.match(tool.$('models').textContent,/Source and frame limits/);
await tool.refreshModelSetup();assert.equal(tool.models.select.value,'__workflow__');assert.match(tool.models.files.textContent,/SDR to HDR/);assert.match(tool.models.files.textContent,/needed.safetensors/);
assert.equal(calls.filter(([path,body])=>path==='/zura/studio/model-downloads'&&body).length,0,'listing HDR packages does not download them');calls.length=0;
tool.job='progress-job';
tool.onExecuting({detail:{prompt_id:'progress-job',node:'model'}});assert.equal(tool.$('status').textContent,'Loading LTX 2.5');assert.equal(tool.$('progress').hasAttribute('value'),false);
tool.onProgress({detail:{prompt_id:'other-job',node:'sample1',value:3,max:8}});assert.equal(tool.$('status').textContent,'Loading LTX 2.5');
tool.onProgress({detail:{prompt_id:'progress-job',node:'sample1',value:3,max:8}});assert.match(tool.$('status').textContent,/pass 1 of 2 · step 3 of 8/);assert.equal(Number(tool.$('progress').value),37.5);
tool.onExecuting({detail:{prompt_id:'progress-job',node:'decode'}});assert.equal(tool.$('status').textContent,'Decoding HDR video');assert.equal(tool.$('progress').hasAttribute('value'),false);tool.job=null;
tool.$('count').value='10';tool.$('start').value='7';tool.$('output').value='hlg_and_exr';
tool.loras.items=[{name:'style.safetensors',strength:.8,confirm_unknown:true}];
await Promise.all([tool.start(),tool.start()]);await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(calls.filter(c=>c[0]==='/prompt').length,1,'Repeated click queues only once');
assert.equal(calls[0][1].start_frame,7);assert.equal(calls[0][1].frame_count,10);
assert.deepEqual(calls[0][1].custom_loras,[{name:'style.safetensors',strength:.8,confirm_unknown:true}],'SDR and HDR preflight receives the selected adapters');
assert.equal(tool.$('result').hidden,false);assert.match(tool.$('hlg').href,/hdr.mp4/);assert.match(tool.$('exr').href,/sequence.zip/);
assert.equal(tool.$('preview').src.includes('preview.mp4'),true);
tool.$('mode').value='native';tool.$('mode').onchange();
await tool.refreshModelSetup();assert.equal(tool.models.context.route,'hdr_native','switching HDR workflow checks its own dependencies');
assert.match(tool.$('limits').textContent,/HLG\/PQ video or EXR sequence/);
assert.ok(tool.$('colour').querySelector('option[value="pq_rec2020"]'));
await tool.start();await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(calls.filter(c=>c[0]==='/zura/studio/hdr/native-graph').length,1,'HDR mode uses the separate native graph');
assert.equal(calls.filter(c=>c[0]==='/zura/studio/hdr/graph').length,1,'SDR conversion remains available');
tool.sequenceAsset={id:'exr-id',count:12,width:384,height:224};tool.$('source-kind').value='sequence';tool.$('source-kind').onchange();tool.$('sequence-fps').value='25';tool.$('colour').value='acescg';
await tool.start();await new Promise(resolve=>setTimeout(resolve,5));
const exr=calls.filter(c=>c[0]==='/zura/studio/hdr/native-graph').at(-1)[1];assert.equal(exr.source_id,'exr-id');assert.equal(exr.sequence_fps,25);assert.equal(exr.colour_space,'acescg');
assert.deepEqual(exr.custom_loras,[{name:'style.safetensors',strength:.8,confirm_unknown:true}]);
// Slow readiness responses must not overwrite the latest selected conversion.
const originalRequest=tool.request.bind(tool),pending=[];
tool.request=path=>new Promise(resolve=>pending.push({path,resolve}));
tool.$('mode').value='sdr';const first=tool.refreshModelSetup();
tool.$('mode').value='native';const second=tool.refreshModelSetup();
pending[1].resolve({route:'hdr_native',files:[],missingNodes:[]});await second;
pending[0].resolve({route:'hdr_sdr',files:[],missingNodes:[]});await first;
assert.equal(tool.models.context.route,'hdr_native','late responses cannot switch setup back to the previous mode');
tool.request=async()=>{throw Error('offline');};await tool.refreshModelSetup();
assert.equal(tool.models.context,null);assert.match(tool.models.progress.textContent,/Could not check HDR dependencies/);
tool.request=originalRequest;
// The displayed limit comes from the backend for the current source geometry;
// it is a software bound, not a promise that the user's GPU can run it.
let currentSource={id:'source-id',width:1920,height:1080};const limitRequests=[];
const limitApi={...api,async fetchApi(path){limitRequests.push(path);return {ok:true,async json(){return path.startsWith('/zura/studio/hdr/readiness?')?{route:'hdr_sdr',files:[],missingNodes:[],frameLimit:{width:currentSource.width,height:currentSource.height,maxFrames:17}}:{models:[]};}};}};
const limitTool=new HDRSourceTool(document.querySelector('#host'),limitApi,()=>currentSource);
limitTool.root.open=true;limitTool.sourceChanged();await new Promise(resolve=>setTimeout(resolve,5));
assert.match(limitTool.$('limits').textContent,/17 frames.*1920 × 1080.*software limit/);
assert.ok(limitRequests.some(path=>path.includes('width=1920')&&path.includes('height=1080')));
currentSource={id:'other',width:1280,height:720};limitTool.sourceChanged();await new Promise(resolve=>setTimeout(resolve,5));
assert.match(limitTool.$('limits').textContent,/1280 × 720/);
limitTool.$('source-kind').value='result';limitTool.updateMode();assert.doesNotMatch(limitTool.$('limits').textContent,/1280 × 720/,'a result with unknown dimensions must not retain the source limit');limitTool.close();
// A transient connection failure must not forget a live job or enable another
// render. Cancellation stays visible until the queue confirms it has stopped.
tool.job='live-job';tool.busy=true;tool.$('start-job').disabled=true;tool.$('cancel').hidden=false;
let running=true,failOnce=true;const requests=[];
tool.request=async(path,body)=>{requests.push([path,body]);if(path==='/history/live-job'){if(failOnce){failOnce=false;throw Error('network');}return {};}
  if(path==='/queue'&&!body)return {queue_running:running?[[0,'live-job']]:[],queue_pending:[]};
  if(path==='/queue'||path==='/interrupt')return {};throw Error(path);};
await tool.poll();assert.equal(tool.job,'live-job');assert.equal(tool.busy,true);assert.equal(tool.$('start-job').disabled,true);assert.match(tool.$('status').textContent,/Reconnecting/);clearTimeout(tool.timer);
await tool.cancel();assert.equal(tool.job,'live-job');assert.equal(tool.busy,true);assert.equal(tool.$('cancel').disabled,true);assert.match(tool.$('status').textContent,/Cancelling/);
tool.onProgress({detail:{prompt_id:'live-job',node:'sample1',value:4,max:8}});assert.match(tool.$('status').textContent,/Cancelling/);
await tool.poll();assert.equal(tool.job,'live-job');clearTimeout(tool.timer);
running=false;await tool.poll();assert.equal(tool.job,null);assert.equal(tool.busy,false);assert.match(tool.$('status').textContent,/cancelled/);
assert.deepEqual(requests.find(([path])=>path==='/interrupt')[1],{prompt_id:'live-job'});
tool.job='live-job';tool.busy=true;tool.$('cancel').hidden=false;
tool.request=async()=>{throw Error('offline');};await tool.cancel();assert.equal(tool.job,'live-job');assert.equal(tool.busy,true);assert.equal(tool.$('cancel').disabled,false);assert.match(tool.$('status').textContent,/Could not request cancellation/);tool.finish();
tool.close();
// Longer conversion is gated, but when enabled it presents the resulting
// preview and files and labels sampler progress as belonging to a section.
let longState='rendering';const longCalls=[];
const longApi={...api,async fetchApi(path,options){
  longCalls.push([path,options]);
  const file=filename=>({filename,subfolder:'genj/hdr',type:'output'});
  const data=path==='/zura/studio/hdr/jobs'?{id:'long-job',state:'ready',completed:0,total:2}:
    {id:'long-job',state:longState,completed:1,total:2,active_prompt_id:'own-prompt',
      result:longState==='complete'?{preview:file('preview.mp4'),files:[file('hdr.mp4'),file('exr.zip')]}:null};
  return {ok:true,status:200,json:async()=>data};
}};
const longTool=new HDRSourceTool(document.querySelector('#host'),longApi,()=>({id:'source-id'}),{longAvailable:true});
assert.equal(longTool.$('long-control').hidden,false);longTool.$('long').checked=true;longTool.$('long').onchange();longTool.$('count').value='130';
assert.equal(longTool.$('sections-control').hidden,true,'SDR conversion keeps its verified section setting');
await longTool.start();await new Promise(resolve=>setTimeout(resolve,5));clearTimeout(longTool.longClient.timer);
assert.equal(longCalls.filter(([path])=>path==='/zura/studio/hdr/jobs').length,1);
longTool.onProgress({detail:{prompt_id:'own-prompt',node:'sample1',value:2,max:8}});
assert.match(longTool.$('status').textContent,/Section 2 of 2.*step 2 of 8/);
longTool.longUpdate({state:'rendering',completed:1,total:2,active_prompt_id:'own-prompt'});
assert.match(longTool.$('status').textContent,/Section 2 of 2.*step 2 of 8/,'polling must not erase live sampler progress');
assert.equal(Number(longTool.$('progress').value),25);
longTool.longUpdate({state:'rendering',completed:1,total:2,active_prompt_id:'new-prompt'});
assert.match(longTool.$('status').textContent,/Section 2 of 2 · processing/);assert.equal(longTool.$('progress').hasAttribute('value'),false);
longState='complete';await longTool.longClient.poll();
assert.equal(longTool.$('result').hidden,false);assert.match(longTool.$('preview').src,/preview.mp4/);
assert.match(longTool.$('hlg').href,/hdr.mp4/);assert.match(longTool.$('exr').href,/exr.zip/);
assert.equal(longTool.busy,false);
longTool.$('mode').value='native';longTool.$('mode').onchange();assert.equal(longTool.$('sections-control').hidden,false);
longTool.$('sections').value='25';await longTool.start();await new Promise(resolve=>setTimeout(resolve,5));
const nativeSubmission=longCalls.filter(([path])=>path==='/zura/studio/hdr/jobs').at(-1);
assert.equal(JSON.parse(nativeSubmission[1].body).section_frames,25,'the shorter native section setting reaches the service');
longTool.close();
// A saved preview job must reconnect only after the server confirms the
// guarded feature is available, without starting a second conversion.
const savedJobs=new Map([['zura-hdr-long-job','existing-long-job']]);
globalThis.localStorage={getItem:key=>savedJobs.get(key)||null,setItem:(key,value)=>savedJobs.set(key,value),removeItem:key=>savedJobs.delete(key)};
const resumedCalls=[];
const resumedApi={...api,async fetchApi(path,options){
  resumedCalls.push([path,options]);
  const data=path.startsWith('/zura/studio/hdr/readiness?')?{route:'hdr_sdr',files:[],missingNodes:[],longPreview:true}:
    path==='/zura/studio/model-downloads'?{models:[]}:
    path==='/zura/studio/hdr/jobs/existing-long-job'?{id:'existing-long-job',state:'complete',completed:1,total:1,result:{preview:{filename:'restored.mp4',subfolder:'genj/hdr',type:'output'},files:[{filename:'hdr.mp4',subfolder:'genj/hdr',type:'output'}]}}:{};
  return {ok:true,status:200,json:async()=>data};
}};
const resumedTool=new HDRSourceTool(document.querySelector('#host'),resumedApi,()=>({id:'source-id'}));
await new Promise(resolve=>setTimeout(resolve,10));
assert.ok(resumedCalls.some(([path])=>path==='/zura/studio/hdr/jobs/existing-long-job'));
assert.ok(!resumedCalls.some(([path,options])=>path==='/zura/studio/hdr/jobs'&&options?.method==='POST'));
assert.match(resumedTool.$('preview').src,/restored.mp4/);assert.equal(savedJobs.has('zura-hdr-long-job'),false);resumedTool.close();
console.log('LTX SDR-to-HDR source range, single submission, result preview and downloads pass.');

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
tool.$('count').value='37';tool.$('count').oninput();assert.match(tool.$('advanced-summary').textContent,/37 frames/);
const rangeTool=new HDRSourceTool(document.querySelector('#host'),api,()=>({}),{longAvailable:true});
const rangePending=[];rangeTool.request=(path,body)=>new Promise(resolve=>rangePending.push({path,body,resolve}));rangeTool.refreshModelSetup=async()=>{};
rangeTool.setOutput({type:'output',subfolder:'zura/first_last',filename:'older.mp4'});rangeTool.activate();
rangeTool.setOutput({type:'output',subfolder:'zura/first_last',filename:'newer.mp4'});
assert.equal(rangePending.length,2);rangePending[1].resolve({frames:180,width:640,height:384,fps:24});await Promise.resolve();
rangePending[0].resolve({frames:30,width:640,height:384,fps:24});await Promise.resolve();
assert.equal(rangeTool.sourceInfo.frames,180,'Late metadata from an earlier source must not replace the current source');
assert.match(rangeTool.$('range-notice').textContent,/25 frames selected · 180 in source/);
rangeTool.$('mode').value='native';rangeTool.updateMode();rangeTool.$('colour').value='pq_rec2020';
rangeTool.frameLimit={maxFrames:81};rangeTool.useFullRange();
assert.equal(rangeTool.$('long').checked,true);assert.equal(rangeTool.$('count').value,'180');assert.equal(rangeTool.$('start').value,'0');assert.match(rangeTool.$('range-notice').textContent,/Full clip · 180 frames/);
assert.equal(rangeTool.$('colour').value,'pq_rec2020','Selecting the full clip must preserve the chosen HDR input colour');
rangeTool.$('count').value='25';rangeTool.$('long').checked=false;rangeTool.longAvailable=false;rangeTool.frameLimit={maxFrames:81};rangeTool.useFullRange();
assert.equal(rangeTool.$('count').value,'25','A full clip must not be silently truncated when long mode is unavailable');assert.match(rangeTool.$('status').textContent,/exceeds the 81-frame limit/);
rangeTool.$('start').value='50';rangeTool.$('count').value='25';rangeTool.setOutput({type:'output',subfolder:'zura/first_last',filename:'short.mp4'});
assert.equal(rangeTool.frameLimit,null,'A different source must not inherit the previous source limit');
rangePending[2].resolve({frames:10,width:640,height:384,fps:24});await Promise.resolve();
assert.equal(rangeTool.$('start').value,'0');assert.equal(rangeTool.$('count').value,'10','A shorter new source recovers an invalid old range');
rangeTool.$('count').value='5';rangeTool.useFullRange();assert.equal(rangeTool.$('count').value,'5');assert.match(rangeTool.$('status').textContent,/Checking this source/);
rangeTool.setOutput({type:'output',subfolder:'zura/first_last',filename:'editing.mp4'});
rangeTool.$('count').value='20';rangeTool.$('count').oninput();rangePending[3].resolve({frames:8,width:640,height:384,fps:24});await Promise.resolve();
assert.equal(rangeTool.$('count').value,'20','Metadata must not overwrite a range the user is editing');assert.match(rangeTool.$('range-notice').textContent,/Range exceeds the 8-frame source/);
rangeTool.close();
const projectInfo=new HDRSourceTool(document.querySelector('#host'),api,()=>({id:'source-id',projectId:'project-123'}));
let infoBody;projectInfo.request=async(path,body)=>{if(path.endsWith('/source-info')){infoBody=body;return {frames:60,width:640,height:384};}return {};};projectInfo.refreshModelSetup=async()=>{};
projectInfo.$('source-kind').value='result';projectInfo.activate();await Promise.resolve();
assert.equal(infoBody.source_kind,'result');assert.equal(infoBody.project_id,'project-123');assert.equal(projectInfo.sourceInfo.frames,60);projectInfo.close();
const failedInfo=new HDRSourceTool(document.querySelector('#host'),api,()=>({id:'broken'}));
failedInfo.refreshModelSetup=async()=>{};failedInfo.request=async()=>{throw new Error('unreadable');};failedInfo.activate();await Promise.resolve();await Promise.resolve();
assert.match(failedInfo.$('status').textContent,/Could not read.*frame range/);assert.equal(failedInfo.sourceInfoKey,null,'Failed metadata can be retried');
failedInfo.request=async()=>({frames:20,width:512,height:288});failedInfo.sourceChanged();await Promise.resolve();await Promise.resolve();
assert.equal(failedInfo.sourceInfo.frames,20);assert.equal(failedInfo.$('status').textContent,'','Successful retry clears the stale error');failedInfo.close();
const raceTool=new HDRSourceTool(document.querySelector('#host'),api,()=>({}));const races=[];
raceTool.request=()=>new Promise((resolve,reject)=>races.push({resolve,reject}));raceTool.refreshModelSetup=async()=>{};
raceTool.setOutput({type:'output',subfolder:'x',filename:'old.mp4'});raceTool.activate();raceTool.setOutput({type:'output',subfolder:'x',filename:'new.mp4'});
races[1].resolve({frames:15,width:512,height:288});await Promise.resolve();races[0].reject(new Error('old failure'));await Promise.resolve();await Promise.resolve();
assert.equal(raceTool.sourceInfo.frames,15);assert.doesNotMatch(raceTool.$('status').textContent,/Could not read/,'An old failure must not replace the current source status');raceTool.close();
const outputTool=new HDRSourceTool(document.querySelector('#host'),api,()=>({}));
const chosenOutput={type:'output',subfolder:'zura/first_last',filename:'take.mp4'},outputCalls=[];
outputTool.request=async(path,body)=>{outputCalls.push([path,body]);return path==='/prompt'?{prompt_id:'output-test'}:{graph:{}};};outputTool.poll=()=>{};
outputTool.setOutput(chosenOutput);outputTool.activate();assert.equal(outputTool.$('source-kind').value,'output');assert.equal(outputTool.$('source-preview').hidden,false);assert.match(outputTool.$('source-preview').src,/take.mp4/);await outputTool.start();
const outputGraph=outputCalls.find(([path])=>path==='/zura/studio/hdr/graph')[1];assert.equal(outputGraph.source_kind,'output');assert.deepEqual(outputGraph.output_ref,chosenOutput);outputTool.finish();outputTool.close();
const ownApi={...api,async fetchApi(path,options){if(path!=='/zura/studio/upload?kind=video')return api.fetchApi(path,options);assert.equal(options.method,'POST');return {ok:true,json:async()=>({id:'uploaded-hdr-video',name:'own.mp4',file:'zura/own.mp4',width:512,height:288})};}};
const ownTool=new HDRSourceTool(document.querySelector('#host'),ownApi,()=>({})),ownCalls=[];
ownTool.$('source-kind').value='own';ownTool.updateMode();ownTool.activate();await ownTool.uploadVideo(new Blob(['video'],{type:'video/mp4'}));assert.equal(ownTool.$('source-preview').hidden,false);assert.match(ownTool.$('source-preview').src,/own.mp4/);
let transferred;ownTool.onUseVideo=async(...values)=>{transferred=values;};ownTool.$('mode').value='native';ownTool.updateMode();assert.equal(ownTool.$('use-video').hidden,false);await ownTool.$('use-video').onclick();assert.equal(transferred[0].id,'uploaded-hdr-video');assert.equal(transferred[1],'auto');ownTool.$('mode').value='sdr';ownTool.updateMode();assert.equal(ownTool.$('use-video').hidden,true,'SDR conversion cannot be silently substituted with HDR paintout');
let escaped=false;ownTool.$('back').onclick=()=>{escaped=true;};const escape=new window.Event('keydown',{bubbles:true,cancelable:true});escape.key='Escape';document.dispatchEvent(escape);assert.equal(escaped,true,'Escape returns to the previous workspace');assert.ok(ownTool.$('back').closest('.zh-composer-heading'),'Exit sits in the composer header');
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
tool.sampleClock.time-=2000;tool.onProgress({detail:{prompt_id:'progress-job',node:'sample1',value:5,max:8}});assert.match(tool.$('status').textContent,/About \d+s left in this pass/);
tool.onExecuting({detail:{prompt_id:'progress-job',node:'decode'}});assert.equal(tool.$('status').textContent,'Decoding HDR video');assert.equal(tool.$('progress').hasAttribute('value'),false);tool.job=null;
let convertedHandoff;tool.onUseResult=async(...args)=>{convertedHandoff=args;};
tool.$('count').value='10';tool.$('start').value='7';tool.$('output').value='hlg_and_exr';
tool.loras.items=[{name:'style.safetensors',strength:.8,confirm_unknown:true}];
await Promise.all([tool.start(),tool.start()]);await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(calls.filter(c=>c[0]==='/prompt').length,1,'Repeated click queues only once');
assert.equal(calls[0][1].start_frame,7);assert.equal(calls[0][1].frame_count,10);
assert.deepEqual(calls[0][1].custom_loras,[{name:'style.safetensors',strength:.8,confirm_unknown:true}],'SDR and HDR preflight receives the selected adapters');
assert.equal(tool.$('result').hidden,false);assert.match(tool.$('hlg').href,/hdr.mp4/);assert.match(tool.$('exr').href,/sequence.zip/);
assert.equal(tool.$('use-result').hidden,false);await tool.$('use-result').onclick();assert.equal(convertedHandoff[0].filename,'hdr.mp4');assert.equal(convertedHandoff[1],'hlg_and_exr');
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
limitTool.activate();await new Promise(resolve=>setTimeout(resolve,5));
assert.match(limitTool.$('limits').textContent,/17 frames.*1920 × 1080.*software limit/);
assert.ok(limitRequests.some(path=>path.includes('width=1920')&&path.includes('height=1080')));
currentSource={id:'other',width:1280,height:720};limitTool.sourceChanged();await new Promise(resolve=>setTimeout(resolve,5));
assert.match(limitTool.$('limits').textContent,/1280 × 720/);
limitTool.$('source-kind').value='result';limitTool.updateMode();assert.doesNotMatch(limitTool.$('limits').textContent,/1280 × 720/,'a result with unknown dimensions must not retain the source limit');limitTool.close();
const longQueries=[];const readinessLongTool=new HDRSourceTool(document.querySelector('#host'),api,()=>({id:'source-id',width:512,height:512}),{longAvailable:true});
readinessLongTool.request=async path=>{if(path.includes('/readiness?'))longQueries.push(path);return path.includes('/readiness?')?{route:'hdr_sdr',files:[],missingNodes:[],longPreview:true,frameLimit:{width:512,height:512,maxFrames:121}}:{frames:121,width:512,height:512};};readinessLongTool.models.load=async()=>{};
readinessLongTool.activate();await new Promise(resolve=>setTimeout(resolve,0));readinessLongTool.$('long').checked=true;readinessLongTool.updateMode();await new Promise(resolve=>setTimeout(resolve,0));assert.ok(longQueries.some(path=>path.includes('long=1')),'Long HDR setup checks continuation dependencies');readinessLongTool.$('output').value='hlg_video';readinessLongTool.$('output').onchange();await new Promise(resolve=>setTimeout(resolve,0));assert.ok(longQueries.at(-1).includes('output=hlg_video'),'Output changes refresh setup even with the panel closed');readinessLongTool.close();
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

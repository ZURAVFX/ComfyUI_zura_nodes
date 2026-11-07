import assert from 'node:assert/strict';
import fs from 'node:fs';
import {installRippleJobs,rippleOutput} from '../web/studio_ripple_jobs.js';
import {H3_RIPPLE_FILES} from '../web/studio_ripple_recipes.js';

const info=JSON.parse(fs.readFileSync(new URL('./fixtures/ripple_nodes.json',import.meta.url),'utf8'));
for(const name of ['ZuraRippleH3Guide','WN_RippleApply','BasicGuider'])info[name]={input:{required:{}}};
const list=(node,key)=>info[node].input.required[key][0];
for(const name of [H3_RIPPLE_FILES.flex,H3_RIPPLE_FILES.ripple])list('LoraLoaderModelOnly','lora_name').push(`H3\\${name}`);
list('UNETLoader','unet_name').push(H3_RIPPLE_FILES.model);
list('CLIPLoader','clip_name').push(H3_RIPPLE_FILES.text);list('CLIPLoader','type').push('minimax');
list('VAELoader','vae_name').push(H3_RIPPLE_FILES.vae);
const config={engine:'h3',source:'clip.mp4',startFrame:3,frameCount:25,sequenceFps:30,width:1024,height:576,seed:42,anchors:[{frame:5,file:'edit.png'}]};
const master={filename:'paintout_SDR_10bit.mp4',subfolder:'ZURA STUDIO/ripple',type:'output'};
const preview={filename:'motion_preview_SDR.mp4',subfolder:'ZURA STUDIO/ripple',type:'output'};
const done={status:{completed:true,status_str:'success'},outputs:{save:{images:[master,preview],text:['Saved 25 frames: output']}}};
assert.deepEqual(rippleOutput(done,config),{file:preview,master,config,saved:'Saved 25 frames: output'});
assert.equal(rippleOutput({outputs:{save:{images:[{filename:'still.png'}]}}},config),null);

function fixture(handler){
  const api=new EventTarget();api.clientId='client';
  const nodes=new Map();
  const ui={api,state:{engine:'h3'},job:null,pendingSubmission:null,submitting:false,app:{},modelInfo:null,
    $(name){if(!nodes.has(name))nodes.set(name,{textContent:'',removeAttribute(){}});return nodes.get(name);},
    fetch:handler,save(){this.saved=structuredClone({job:this.job,pending:this.pendingSubmission});return true;},
    render(){},message(message){this.messageText=message;},setAvailability(a){this.availability=a;},
    setProgress(p){this.progress=p;},clearProgress(){this.progress=null;},setResult(result){this.result=result;this.job=null;this.save();},
    config(){return config;},owner:{studio:{close(){}}}};
  installRippleJobs(ui);return ui;
}
const emit=(api,name,detail)=>{const event=new Event(name);event.detail=detail;api.dispatchEvent(event);};

// A dropped response must recover the owned prompt without submitting twice.
let promptCount=0,requestId='',complete=false;
const ui=fixture(async(path,body)=>{
  if(path==='/object_info')return info;
  if(path==='/prompt'){promptCount++;requestId=body.extra_data.zura_studio_request;throw Error('connection lost');}
  if(path==='/queue')return {queue_running:requestId?[['x','owned',null,{zura_studio_request:requestId}]]:[],queue_pending:[]};
  if(path==='/history?max_items=100')return {};
  if(path==='/history/owned')return complete?{owned:done}:{};
  throw Error(`Unexpected ${path}`);
});
await ui.onGenerate(config);
await new Promise(resolve=>setTimeout(resolve,0));
if(!ui.job)await ui.poll();
assert.equal(promptCount,1);assert.equal(ui.job?.id,'owned');assert.equal(ui.pendingSubmission,null);
emit(ui.api,'progress',{prompt_id:'someone-else',node:'sample',value:4,max:6});
assert.notEqual(ui.progress?.value,100*4/6);
emit(ui.api,'progress',{prompt_id:'owned',node:'sample',value:3,max:6});
assert.equal(ui.progress.value,50);assert.match(ui.progress.title,/Step 3 of 6/);
complete=true;await ui.poll();
assert.deepEqual(ui.result.file,preview);assert.deepEqual(ui.result.master,master);assert.equal(ui.job,null);assert.equal(promptCount,1);
ui.rippleJobs.dispose();

// Definitive validation errors release the run; a failed save never submits.
let calls=0;
const rejected=fixture(async(path)=>{if(path==='/object_info')return info;if(path==='/prompt'){calls++;throw Object.assign(Error('invalid graph'),{status:400});}if(path==='/queue')return {queue_running:[],queue_pending:[]};if(path==='/history?max_items=100')return {};throw Error(path);});
await assert.rejects(rejected.onGenerate(config),/invalid graph/);assert.equal(rejected.pendingSubmission,null);assert.equal(rejected.job,null);assert.equal(calls,1);rejected.rippleJobs.dispose();
const unsaved=fixture(async path=>{if(path==='/object_info')return info;throw Error('must not submit');});
unsaved.save=()=>false;await assert.rejects(unsaved.onGenerate(config),/storage/i);assert.equal(unsaved.pendingSubmission,null);unsaved.rippleJobs.dispose();

// A model check opens setup rather than queuing a broken graph.
const missing=fixture(async path=>path==='/object_info'?{}:assert.fail(`Unexpected ${path}`));
missing.openModelSetup=(engine,availability)=>{missing.opened={engine,availability};};
await assert.rejects(missing.onGenerate(config),/Install the models/);assert.equal(missing.opened.engine,'h3');assert.equal(missing.opened.availability.ready,false);missing.rippleJobs.dispose();

// Cancellation targets only this prompt and reports an interrupted history.
const cancelledCalls=[];
const cancelled=fixture(async(path,body)=>{
  cancelledCalls.push([path,body]);
  if(path==='/queue'&&body)return {};
  if(path==='/interrupt')return {};
  if(path==='/history/owned')return {owned:{status:{completed:true,status_str:'error',messages:[['execution_interrupted',{}]]}}};
  throw Error(`Unexpected ${path}`);
});
cancelled.job={id:'owned',started:Date.now(),config};
await cancelled.onCancel();
assert.deepEqual(cancelledCalls.slice(0,2),[['/queue',{delete:['owned']}],['/interrupt',{prompt_id:'owned'}]]);
assert.equal(cancelled.job,null);assert.match(cancelled.messageText,/cancelled/);cancelled.rippleJobs.dispose();

const pendingCalls=[];
const pending=fixture(async(path,body)=>{
  pendingCalls.push([path,body]);
  if(path==='/queue'&&body)return {};
  if(path==='/queue')return {queue_running:[['x','recovered',null,{zura_studio_request:'nonce'}]],queue_pending:[]};
  if(path==='/interrupt')return {};
  if(path==='/history/recovered')return {recovered:{status:{completed:true,status_str:'error',messages:[['execution_interrupted',{}]]}}};
  throw Error(`Unexpected ${path}`);
});
pending.pendingSubmission={requestId:'nonce',started:Date.now(),config,stages:{}};
await pending.onCancel();await new Promise(resolve=>setTimeout(resolve,0));
assert.ok(pendingCalls.some(([path,body])=>path==='/interrupt'&&body.prompt_id==='recovered'));
assert.equal(pending.job,null);pending.rippleJobs.dispose();
console.log('Ripple owned jobs: submission recovery, progress, output and setup passed');

import assert from 'node:assert/strict';
import {FrameVideoWorkspace} from '../web/studio_frames.js';
import {ReferenceVideoWorkspace} from '../web/studio_references.js';
import {CreativeWorkspace} from '../web/studio_create.js';
import {findOwnedSubmission} from '../web/studio_owned_jobs.js';

const foreign=[0,'foreign',{}, {zura_studio_request:'another-request'},[]];
const own=id=>[1,id,{}, {zura_studio_request:'request-123'},[]];
assert.equal(await findOwnedSubmission(async path=>path==='/queue'?{queue_running:[foreign],queue_pending:[own('own')]}:{},'request-123'),'own');
assert.equal(await findOwnedSubmission(async path=>path==='/queue'?{queue_running:[foreign],queue_pending:[]}:{own:{prompt:own('own')}},'request-123'),'own');
assert.equal(await findOwnedSubmission(async path=>path==='/queue'?{queue_running:[own('one')],queue_pending:[own('two')]}:{},'request-123'),null,'Ambiguous token matches are never adopted');
assert.equal(await findOwnedSubmission(async path=>path==='/queue'?{queue_running:[foreign],queue_pending:[]}:{},'request-123'),null,'Foreign jobs are ignored');
let queueReads=0;assert.equal(await findOwnedSubmission(async path=>path==='/queue'?{queue_running:++queueReads===1?[]:[own('late')],queue_pending:[]}:{},'request-123'),'late','A prompt accepted during the history read is found by the second queue check');
assert.equal(await findOwnedSubmission(async path=>{if(path==='/queue')return {queue_running:[own('in-queue')],queue_pending:[]};throw Error('history offline');},'request-123'),'in-queue','An owned queued prompt does not depend on history availability');

function fixture(Workspace, {lost=true, failureStatus}={}){
  const ui=Object.create(Workspace.prototype), fields=new Map(), calls=[];
  let stored=null, online=false, accepted=null, history={};
  Object.assign(ui,{availability:{ready:true},models:[{id:'flux3',ready:true}],api:{clientId:'test',fetchApi:async()=>({ok:false})},items:[],submitting:false,uploading:false,
    hdrOutput:{busy:false,preflight:async()=>{},start:async()=>{throw Error('Unexpected HDR continuation');}},
    loras:{patch:async graph=>graph},
    config:()=>({model:'flux3',engine:'h3',prompt:'test',frames:9,first:{file:'first.png'},custom_loras:[],random:false}),
    buildGraph:async()=>({sample:{class_type:'Example',inputs:{},_meta:{title:'Generating video'}}}),
    imageGraph:async()=>({sample:{class_type:'Example',inputs:{},_meta:{title:'Generating image'}}}),
    build:()=>({sample:{class_type:'Example',inputs:{},_meta:{title:'Generating video'}}}),
    $:id=>{if(!fields.has(id))fields.set(id,{textContent:'',hidden:false,disabled:false,removeAttribute(){},commitDimension:()=>true});return fields.get(id);},
    save(){stored=JSON.parse(JSON.stringify({job:this.job||null,pendingSubmission:this.pendingSubmission||null}));},
    render(){this.$('generate').disabled=!!(this.job||this.pendingSubmission||this.submitting);this.$('cancel').disabled=!this.job||!!(this.job.cancelPending&&!this.job.cancelRetryAvailable);},
    message(message){this.lastMessage=message;},startPolling(){},stopPolling(){},renderHistory(){},renderGallery(){},
    fetch:async(path,body)=>{calls.push({path,body});
      if(path==='/prompt'){
        if(failureStatus){const e=Error('Rejected by Comfy');e.status=failureStatus;throw e;}
        accepted=body.extra_data.zura_studio_request;
        if(lost)throw Error('response lost after server accepted');
        return {prompt_id:'accepted'};
      }
      if(!online)throw Error('offline');
      if(path==='/queue')return {queue_running:[[0,'accepted',{}, {zura_studio_request:accepted},[]],foreign],queue_pending:[]};
      if(path==='/history?max_items=100')return {};
      if(path.startsWith('/history/'))return history;
      return {};
    }
  });
  return {ui,calls,get stored(){return stored;},get token(){return accepted;},connect(){online=true;},history(value){history=value;}};
}

for(const Workspace of [CreativeWorkspace,FrameVideoWorkspace,ReferenceVideoWorkspace]){
  const f=fixture(Workspace),ui=f.ui;
  await ui.generate();
  assert.equal(ui.$('progress-title').textContent,Workspace===CreativeWorkspace?'Submitting image':'Submitting video','Each workspace names its own generation type');
  assert.ok(ui.pendingSubmission?.requestId,'An uncertain accepted request stays owned');
  assert.equal(ui.pendingSubmission.requestId,f.token);
  assert.equal(ui.$('generate').disabled,true);
  assert.equal(f.stored.pendingSubmission.requestId,f.token,'The token survives a page reload');
  await ui.generate();assert.equal(f.calls.filter(c=>c.path==='/prompt').length,1,'No duplicate prompt is submitted');
  const restored=fixture(Workspace),r=restored.ui;
  r.pendingSubmission=JSON.parse(JSON.stringify(f.stored.pendingSubmission));
  restored.connect();
  // Supply the exact accepted token after an offline/reopen boundary.
  r.fetch=async path=>path==='/queue'?{queue_running:[[0,'accepted',{}, {zura_studio_request:f.token},[]],foreign],queue_pending:[]}:{};
  await r.poll();assert.equal(r.job.id,'accepted');assert.equal(r.pendingSubmission,null);
  assert.equal(restored.stored.job.id,'accepted');assert.equal(r.$('generate').disabled,true);
  const rejected=fixture(Workspace,{failureStatus:400});await rejected.ui.generate();
  assert.equal(rejected.ui.pendingSubmission,null,'A definite validation rejection releases the pending request');
  assert.match(rejected.ui.lastMessage,/Rejected by Comfy/);
  const full=fixture(Workspace);full.ui.save=()=>false;await full.ui.generate();
  assert.equal(full.calls.filter(c=>c.path==='/prompt').length,0,'A request is not sent when its recovery token cannot be persisted');
  assert.match(full.ui.lastMessage,/Browser storage/);
  const live=fixture(Workspace),open=live.ui;
  let firstToken,resolveFirst,resolveSecond,sendCount=0;
  const firstResponse=new Promise(r=>resolveFirst=r),secondResponse=new Promise(r=>resolveSecond=r);
  open.fetch=async(path,body)=>{
    if(path==='/prompt'){sendCount++;if(sendCount===1){firstToken=body.extra_data.zura_studio_request;return firstResponse;}return secondResponse;}
    if(path==='/queue')return {queue_running:[[0,'first',{}, {zura_studio_request:firstToken},[]]],queue_pending:[]};
    if(path==='/history?max_items=100')return {};
    if(path==='/history/first')return {first:{status:{completed:true,status_str:'success',messages:[]},outputs:{save:{images:[{filename:'first.mp4'}]}}}};
    return {};
  };
  const delayed=open.generate();while(!firstToken)await new Promise(r=>setTimeout(r,0));
  await open.poll();assert.equal(open.job.id,'first');assert.equal(open.submitting,false,'Recovery unblocks a stalled HTTP response after ownership is known');
  await open.poll();assert.equal(open.job,null);assert.equal(open.items.length,1);
  const next=open.generate();while(sendCount<2)await new Promise(r=>setTimeout(r,0));
  assert.equal(open.submitting,true);resolveFirst({prompt_id:'first'});await delayed;
  assert.equal(open.submitting,true,'A late response cannot unblock a newer submission');
  assert.ok(open.pendingSubmission);resolveSecond({prompt_id:'second'});await next;
  assert.equal(open.job.id,'second');assert.equal(open.submitting,false);
}

for(const Workspace of [CreativeWorkspace,FrameVideoWorkspace,ReferenceVideoWorkspace]){
  const f=fixture(Workspace),ui=f.ui;
  ui.job={id:'owned',started:Date.now(),config:{engine:'h3',outputMode:'SDR video'}};
  let resolveDelete,resolveInterrupt;
  const deleteWait=new Promise(r=>resolveDelete=r),interruptWait=new Promise(r=>resolveInterrupt=r);
  ui.fetch=async(path,body)=>{f.calls.push({path,body});if(path==='/queue'&&body){await deleteWait;return {};}if(path==='/interrupt'){await interruptWait;return {};}if(path.startsWith('/history/'))return {};if(path==='/queue')return {queue_running:[[0,'owned']],queue_pending:[]};return {};};
  const first=ui.cancel(),second=ui.cancel();
  assert.equal(ui.job.cancelPending,true);assert.equal(ui.$('cancel').disabled,true);
  assert.equal(f.stored.job.cancelPending,true,'Cancellation intent is saved before network calls');
  assert.equal(f.calls.filter(c=>c.path==='/queue'&&c.body).length,1,'A second click cannot duplicate deletion');
  resolveDelete();await new Promise(r=>setTimeout(r,0));
  assert.equal(f.calls.filter(c=>c.path==='/interrupt').length,1);assert.deepEqual(f.calls.find(c=>c.path==='/interrupt').body,{prompt_id:'owned'});
  resolveInterrupt();await Promise.all([first,second]);
  assert.equal(ui.job.cancelPending,true,'A running job stays tracked until Comfy reports a terminal state');
  assert.match(ui.$('progress-title').textContent,/Cancelling/);
  // A saved successful completion wins over a late cancellation request.
  ui.items=[];ui.renderGallery=()=>{};ui.fetch=async path=>path.startsWith('/history/')?{owned:{status:{completed:true,status_str:'success',messages:[]},outputs:{save:{images:[{filename:'finished.mp4'}]}}}}:{};
  await ui.poll();assert.equal(ui.job,null);assert.equal(ui.items.length,1,'A completed result is retained');
  assert.match(ui.lastMessage,/finished before cancellation/i);
  ui.job={id:'failed',started:Date.now(),config:{engine:'h3',outputMode:'SDR video'}};ui.items=[];
  ui.fetch=async path=>path.startsWith('/history/')?{failed:{status:{completed:false,status_str:'error',messages:[['execution_error',{exception_message:'Sampler failed'}]]},outputs:{save:{images:[{filename:'partial.mp4'}]}}}}:{};
  await ui.poll();assert.equal(ui.items.length,0,'An error with partial output is not reported as a completed take');assert.match(ui.lastMessage,/Sampler failed/);
}

console.log('Owned submissions recover after lost responses/reopen; cancellation is persisted, scoped, idempotent and preserves completed results.');

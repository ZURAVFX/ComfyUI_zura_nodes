import assert from 'node:assert/strict';
import {PaintoutEditor} from '../web/paintout_studio/paintout_editor.js';

const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const historyEntry=output=>({status:{completed:true,status_str:'success'},outputs:{save:output}});

function fixture(){
  const state={source:'source.mp4',editorJob:null,maskProject:null,maskRevision:null,maskCoverage:[],maskGrow:0,seed:7,anchors:[{id:'frame-0',frame:0,file:'',status:'draft',layers:[]}]};
  const queue={queue_running:[],queue_pending:[]},history={},calls=[],statuses=[],added=[];
  const editor=Object.create(PaintoutEditor.prototype);
  Object.assign(editor,{
    w:{state,save(){calls.push('save');},render(){calls.push('render');},fetch:async(path,body)=>{
      calls.push({path,body});
      if(path==='/history/'+encodeURIComponent(editor.toolJob?.id))return structuredClone(history);
      if(path==='/queue'&&!body)return structuredClone(queue);
      if(path==='/queue'&&body?.delete)return fixture.deleteQueue?fixture.deleteQueue():{};
      if(path==='/interrupt')return {};
      throw Error('Unexpected fixture request: '+path);
    }},
    toolJob:null,timer:null,polling:false,sequence:0,previewSequence:0,missingPolls:0,manualDirty:false,autoPreviewPending:false,
    $:()=>({textContent:''}),status:message=>statuses.push(message),updateControls(){},startPolling(){calls.push('startPolling');},
    addPaintLayer(...args){added.push(args);},frameChanged:async()=>{},authoritativePreview:async()=>{},loadDocument:async()=>({})
  });
  return {editor,state,queue,history,calls,statuses,added};
}

{
  const f=fixture(),job={id:'mask-cancel',kind:'mask',source:'source.mp4',maskSingle:false};
  f.editor.toolJob=job;f.state.editorJob=job;const deletion=deferred();fixture.deleteQueue=()=>deletion.promise;
  const cancelling=f.editor.cancel();
  assert.equal(job.cancelRequested,true,'Cancellation intent must be set before the server await');
  assert.equal(f.state.editorJob.cancelRequested,true,'Cancellation intent must be persisted immediately');
  deletion.resolve({});await cancelling;assert.equal(job.cancelError,null);assert.equal(job.cancelSent,true);
  f.history[job.id]=historyEntry({zura_mask:[{project:'late-project',revision:9,segment_id:'late-mask'}]});
  f.queue.queue_running=[[0,job.id]];
  await f.editor.poll();
  assert.equal(f.editor.toolJob,job,'A cancelled job must remain fenced while it is still queued');
  assert.equal(f.state.maskProject,null);assert.equal(f.state.maskRevision,null,'A late mask result must not mutate project masks');
  f.queue.queue_running=[];
  await f.editor.poll();assert.equal(f.editor.toolJob,job);
  await f.editor.poll();
  assert.equal(f.editor.toolJob,null,'Cancellation completes only after repeated queue absence');
  assert.equal(f.state.editorJob,null);assert.equal(f.state.maskRevision,null);
  assert.match(f.statuses.at(-1),/Run cancelled.*remain in ComfyUI history/);
}

{
  const f=fixture(),job={id:'frame-cancel',kind:'frame',anchor:'frame-0',source:'source.mp4'};
  f.editor.toolJob=job;f.state.editorJob=job;fixture.deleteQueue=async()=>{throw Error('queue unavailable');};
  await f.editor.cancel();
  assert.equal(job.cancelRequested,true);assert.equal(job.cancelError,'queue unavailable','A failed cancellation must remain retryable and fenced');
  assert.match(f.statuses.at(-1),/Retry Cancel.*late results will not be accepted/);
  f.history[job.id]=historyEntry({zura_frame:[{file:'late-clean.exr',frame:0,layer_mask:'mask'}]});
  f.queue.queue_running=[[0,job.id]];
  await f.editor.poll();
  assert.equal(f.added.length,0,'A late clean frame must never add a paint layer after cancel');
  assert.equal(f.state.anchors[0].file,'');assert.equal(f.editor.toolJob,job);
  f.queue.queue_running=[];await f.editor.poll();await f.editor.poll();
  assert.equal(f.editor.toolJob,null);assert.equal(f.added.length,0);
}

{
  const f=fixture(),old={id:'old-job',kind:'mask',source:'source.mp4'},replacement={id:'new-job',kind:'frame',source:'source.mp4'};
  const history=deferred();f.editor.toolJob=old;f.state.editorJob=old;
  f.editor.w.fetch=async(path)=>{
    if(path==='/history/old-job')return history.promise;
    throw Error('Unexpected fixture request: '+path);
  };
  const polling=f.editor.poll();
  f.editor.toolJob=replacement;f.state.editorJob=replacement;
  history.resolve({old:{status:{completed:true,status_str:'success'},outputs:{save:{zura_mask:[{project:'wrong',revision:8}]}}}});
  await polling;
  assert.equal(f.state.maskProject,null,'A replaced job must not apply its late history');
  assert.equal(f.editor.toolJob,replacement);assert.equal(f.state.editorJob,replacement);
}

{
  const f=fixture(),job={id:'source-race',kind:'frame',anchor:'frame-0',source:'old.mp4'};
  f.editor.toolJob=job;f.state.editorJob=job;job.cancelRequested=true;f.state.source='new.mp4';
  f.history[job.id]=historyEntry({zura_frame:[{file:'wrong-source.exr',frame:0,layer_mask:'mask'}]});
  f.queue.queue_running=[[0,job.id]];
  await f.editor.poll();
  assert.equal(f.added.length,0,'A changed source must not receive a stale frame result');
  assert.equal(f.state.anchors[0].file,'');
}

{
  const f=fixture(),job={id:'resume-cancel',kind:'mask',source:'source.mp4',cancelRequested:true,cancelSent:false};
  f.editor.toolJob=job;f.state.editorJob=job;fixture.deleteQueue=async()=>({});
  f.queue.queue_running=[[0,job.id]];
  await f.editor.poll();
  assert.equal(job.cancelSent,true,'A persisted cancellation must resume after an interrupted page request');
  assert.ok(f.calls.some(call=>call.path==='/queue'&&call.body?.delete?.[0]===job.id));
  assert.equal(f.added.length,0);
}

fixture.deleteQueue=null;
console.log('Remove cancellation: durable intent, late mask/frame rejection, changed-job fencing and queue-drain completion passed');

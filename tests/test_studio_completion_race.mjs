import assert from 'node:assert/strict';
import {CreativeWorkspace} from '../web/studio_create.js';
import {FrameVideoWorkspace} from '../web/studio_frames.js';
import {PaintoutWorkspace,findPaintoutSubmission} from '../web/paintout_studio/studio_paintout.js';

for (const Workspace of [CreativeWorkspace, FrameVideoWorkspace, PaintoutWorkspace]) {
  let historyReads = 0;
  const output = {filename:'completed.mp4', subfolder:'test', type:'output'};
  const entry = {status:{completed:true,status_str:'success',messages:[]}, outputs:{save:{images:[output]}}};
  const ui = Object.create(Workspace.prototype);
  Object.assign(ui, {
    job:{id:'own-job',config:{outputMode:'video'},started:Date.now()}, polling:false, items:[],
    fetch:async path => {
      if (path === '/queue') return {queue_running:[],queue_pending:[]};
      if (path === '/history/own-job') return ++historyReads === 1 ? {} : {'own-job':entry};
      throw Error(path);
    },
    stopPolling(){}, save(){}, render(){}, renderGallery(){}, renderHistory(){}, message(text){this.lastMessage=text;}, preview(){},
  });
  await ui.poll();
  assert.equal(ui.job.id,'own-job','job remains tracked when it completes between history and queue reads');
  await ui.poll();
  assert.equal(ui.job,null);
  assert.equal(ui.items[0].file.filename,'completed.mp4','completed result is retained on the next poll');
  ui.job={id:'own-job',config:{outputMode:'video'},started:Date.now()};let offline=true;
  ui.fetch=async()=>{if(offline){offline=false;throw Error('offline');}return {'own-job':entry};};
  await ui.poll();assert.ok(ui.job);assert.match(ui.lastMessage,/Reconnecting/);
  await ui.poll();assert.equal(ui.job,null);assert.doesNotMatch(ui.lastMessage,/Reconnecting/);
}
const paintout=Object.create(PaintoutWorkspace.prototype),fields=new Map();
Object.assign(paintout,{busy:()=>false,page:{querySelectorAll:()=>[]},availability:{ready:true},validationError:'',api:{clientId:'test'},
  config:()=>({mode:'full',source:'Z:/take.mp4',mask:'',anchors:[],startFrame:0,frameCount:9,sourceColour:'auto',processingSpace:'SDR (sRGB)',width:128,height:64,outputMode:'SDR video',custom_loras:[]}),
  loras:{patch:async graph=>graph},fetch:async()=>{throw Error('connection lost');},render(){},message(text){this.lastMessage=text;},
  $:id=>{if(!fields.has(id))fields.set(id,{removeAttribute(){},textContent:''});return fields.get(id);}});
await paintout.generate();assert.match(paintout.lastMessage,/Could not confirm whether the run started.*Check the ComfyUI queue/);
const foreign=[0,'foreign',{}, {zura_paintout_request:'different'},[]],own=[1,'own',{}, {zura_paintout_request:'our-token'},[]];
assert.equal(await findPaintoutSubmission(async path=>path==='/queue'?{queue_running:[foreign],queue_pending:[own]}:{},'our-token'),'own');
assert.equal(await findPaintoutSubmission(async path=>path==='/queue'?{queue_running:[foreign],queue_pending:[]}:{own:{prompt:own}},'our-token'),'own');
let queueReads=0;assert.equal(await findPaintoutSubmission(async path=>path==='/queue'?{queue_running:++queueReads===1?[]:[own],queue_pending:[]}:{},'our-token'),'own');
assert.equal(await findPaintoutSubmission(async path=>path==='/queue'?{queue_running:[foreign],queue_pending:[]}: {},'our-token'),null,'Unrelated jobs are never adopted');
let sent=0,trackedToken;paintout.save=()=>{};paintout.startPolling=()=>{};paintout.fetch=async(path,body)=>{
  if(path==='/prompt'){sent++;trackedToken=body.extra_data.zura_paintout_request;throw Error('response lost');}
  if(path==='/queue')return {queue_running:[[0,'recovered',{}, {zura_paintout_request:trackedToken},[]]],queue_pending:[]};
  throw Error(path);
};
await paintout.generate();assert.equal(sent,1);assert.equal(paintout.job.id,'recovered','A queued paintout is recovered without resubmitting');
console.log('Image, first/last and paintout workspaces preserve jobs completing between queue and history checks.');

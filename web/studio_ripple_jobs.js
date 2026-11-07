import {buildRippleStudioGraph, rippleStudioAvailability, rippleStudioValidation} from './studio_ripple_recipes.js';
import {submitOwnedGraph, recoverOwnedSubmission, cancelOwnedJob} from './studio_owned_jobs.js';
import {durationLabel, installOwnedExecuting} from './studio_progress.js';

const elapsed=job=>`${durationLabel((Date.now()-(job?.started||Date.now()))/1000)} elapsed`;

/** Select both the source-sized master and the browser playback proxy. */
export function rippleOutput(entry, config) {
  const output=entry?.outputs?.save||{};
  const files=(Array.isArray(output.images)?output.images:[]).filter(file=>file?.filename&&/\.(mp4|mov|webm|mkv)$/i.test(file.filename));
  const master=files.find(file=>!/motion_preview/i.test(file.filename))||files[0];
  const file=files.find(file=>/motion_preview/i.test(file.filename))||master;
  if(!file)return null;
  return {file,master,config,saved:(output.text||[]).join('\n')};
}

/** Attach ownership-aware submission and progress to the dedicated workspace. */
export function installRippleJobs(ui){
  if(ui.rippleJobs)return ui.rippleJobs;
  let disposed=false,modelRequest=null;
  const listeners=[];
  const listen=(name,callback)=>{ui.api.addEventListener?.(name,callback);listeners.push([name,callback]);};
  const clear=()=>{ui.clearProgress();ui.render();};

  async function checkModels(engine=ui.state.engine){
    if(!modelRequest){
      modelRequest=ui.fetch('/object_info').finally(()=>{modelRequest=null;});
    }
    try{
      const info=await modelRequest;if(disposed)return null;
      ui.modelInfo=info;
      const availability=rippleStudioAvailability(info,engine);
      if(ui.state.engine===engine){ui.availability=availability;ui.setAvailability?.(availability);ui.render();}
      return availability;
    }catch(error){
      if(!disposed&&ui.state.engine===engine){ui.availability=null;ui.setAvailability?.(null);ui.message('Could not check installed models. Check the ComfyUI connection and try again.');ui.render();}
      return null;
    }
  }
  ui.onCheckModels=checkModels;

  ui.startPolling=()=>{if(disposed||ui.timer)return;ui.timer=setInterval(()=>void ui.poll(),1500);void ui.poll();};
  ui.stopPolling=()=>{clearInterval(ui.timer);ui.timer=null;};
  ui.poll=async()=>{
    if(disposed||ui.polling)return;
    if(ui.pendingSubmission&&!ui.job){
      const pending=ui.pendingSubmission;
      await recoverOwnedSubmission(ui);
      if(pending.cancelRequested&&ui.job)await cancelOwnedJob(ui);
      return;
    }
    const job=ui.job;if(!job)return;
    ui.polling=true;
    try{
      const history=await ui.fetch('/history/'+encodeURIComponent(job.id));
      if(disposed||ui.job!==job)return;
      const entry=history?.[job.id];
      if(ui.connectionLost){ui.connectionLost=false;ui.message('');}
      if(entry?.status?.completed||entry?.status?.status_str==='error'){
        const messages=entry.status.messages||[];
        const failure=messages.find(message=>message[0]==='execution_error')?.[1];
        const interrupted=messages.some(message=>message[0]==='execution_interrupted');
        const success=entry.status.status_str==='success'&&!failure&&!interrupted;
        const result=success?rippleOutput(entry,job.config):null;
        ui.stopPolling();ui.job=null;
        if(result){ui.setResult(result);}
        else{
          ui.save();clear();
          if(interrupted)ui.message('The run was cancelled. Your earlier results remain saved.');
          else if(failure)ui.message(`Ripple stopped · ${job.stages?.[failure.node_id]||failure.node_type||'Processing'}: ${failure.exception_message||'Check ComfyUI for details.'}`);
          else ui.message('The run finished without a playable video. Check the ComfyUI output folder.');
        }
        return;
      }
      const queue=await ui.fetch('/queue');if(disposed||ui.job!==job)return;
      const running=(queue.queue_running||[]).some(item=>item[1]===job.id);
      const position=(queue.queue_pending||[]).findIndex(item=>item[1]===job.id);
      if(!running&&position<0){
        // Queue and history updates are not atomic. Keep tracking through a short
        // handoff and check history again before deciding that a job disappeared.
        job.missingSince??=Date.now();
        if(Date.now()-job.missingSince<6000)return;
        const again=await ui.fetch('/history/'+encodeURIComponent(job.id));
        if(disposed||ui.job!==job||again?.[job.id])return;
        ui.job=null;ui.stopPolling();ui.save();clear();
        ui.message(job.cancelPending?'The run left the queue after cancellation. Earlier results remain saved.':'This run is no longer in the ComfyUI queue. Check its output folder before starting again.');
        return;
      }
      delete job.missingSince;
      if(job.cancelPending){ui.setProgress({title:'Cancelling…',detail:'Waiting for ComfyUI to stop this run.'});return;}
      const activeProgress=running&&job.progress?.node===job.currentNode?job.progress:null;
      const stage=job.stages?.[job.currentNode]||'Starting Ripple';
      const title=running?(activeProgress?`${stage} · ${job.currentNode==='sample'?'Step':'Progress'} ${activeProgress.step} of ${activeProgress.max}`:stage):'Queued';
      const detail=running?elapsed(job):`Queue position ${position+1} · Waiting for ComfyUI`;
      const value=activeProgress?.value??null;
      ui.setProgress({title,detail,value});
    }catch{
      if(!disposed&&ui.job===job){ui.connectionLost=true;ui.message('Connection interrupted. Reconnecting to your saved run…');}
    }finally{ui.polling=false;}
  };

  ui.onGenerate=async config=>{
    if(ui.job||ui.pendingSubmission||ui.submitting)return;
    const invalid=rippleStudioValidation(config);if(invalid)throw Error(invalid);
    ui.submitting=true;ui.message('');ui.setProgress({title:'Checking models',detail:'Preparing your Ripple run'});ui.render();
    try{
      const availability=await checkModels(config.engine);
      if(disposed)return;
      if(!availability)throw Error('Could not check the models needed for Ripple.');
      if(!availability.ready){ui.openModelSetup?.(config.engine,availability);throw Error('Install the models and extensions needed for this Ripple mode.');}
      const graph=buildRippleStudioGraph(config,ui.modelInfo);
      const submission=submitOwnedGraph(ui,graph,config,'auto',{zura_ripple:true});
      const pending=ui.pendingSubmission;
      await submission;
      if(pending?.cancelRequested&&ui.job)await cancelOwnedJob(ui);
    }catch(error){if(!ui.job&&!ui.pendingSubmission)ui.clearProgress();throw error;}
    finally{ui.submitting=false;ui.render();}
  };
  ui.onCancel=async()=>{
    if(ui.job)return cancelOwnedJob(ui);
    if(!ui.pendingSubmission)return;
    // A failed POST response may still have queued a prompt. Resolve its nonce
    // before cancelling so no other user's work can be interrupted.
    ui.pendingSubmission.cancelRequested=true;ui.save();
    ui.setProgress({title:'Checking run before cancellation',detail:'Finding this run in the ComfyUI queue'});
    ui.message('Checking whether this run started before cancelling it.');
    ui.startPolling();await ui.poll();
  };
  ui.onResume=()=>{
    if(!ui.job&&!ui.pendingSubmission)return;
    if(ui.job?.cancelPending)ui.job.cancelRetryAvailable=true;
    ui.setProgress({title:ui.job?.cancelPending?'Cancelling…':'Checking your run',detail:'Reconnecting to ComfyUI'});
    ui.startPolling();ui.render();
  };

  listen('progress',event=>{
    const detail=event.detail,job=ui.job;
    if(!job||job.cancelPending||detail?.prompt_id!==job.id||!Number.isFinite(detail.value)||!(detail.max>0))return;
    const node=detail.node||job.currentNode||'sample';job.currentNode=node;
    const value=Math.max(0,Math.min(100,100*detail.value/detail.max));job.progress={node,value,step:detail.value,max:detail.max};
    ui.setProgress({title:`${job.stages?.[node]||'Processing Ripple'} · ${node==='sample'?'Step':'Progress'} ${detail.value} of ${detail.max}`,detail:elapsed(job),value});
  });
  const removeExecuting=installOwnedExecuting(ui.api,event=>{
    const detail=event.detail,job=ui.job;
    if(!job||job.cancelPending||detail?.prompt_id!==job.id||!detail.node)return;
    job.currentNode=detail.node;delete job.progress;
    ui.setProgress({title:job.stages?.[detail.node]||'Processing Ripple',detail:elapsed(job)});
  });
  for(const type of ['execution_success','execution_error','execution_interrupted'])listen(type,event=>{if(event.detail?.prompt_id===ui.job?.id)void ui.poll();});

  ui.graph=async()=>{
    try{
      const config=ui.job?.config||ui.config(),graph=buildRippleStudioGraph(config,ui.modelInfo||{});
      const original=(ui.app.rootGraph||ui.app.graph)?.serialize?.();
      if(!original||typeof ui.app.loadApiJson!=='function')throw Error('Update ComfyUI to open this Ripple graph.');
      try{await ui.app.loadApiJson(graph,`Zura Ripple · ${Date.now()}.json`);}catch(error){await ui.app.loadGraphData(original);throw error;}
      ui.owner.studio.close();
    }catch(error){ui.message(error.message);}
  };
  const controller={dispose(){if(disposed)return;disposed=true;ui.stopPolling();removeExecuting();for(const [name,callback] of listeners)ui.api.removeEventListener?.(name,callback);}};
  ui.rippleJobs=controller;
  return controller;
}

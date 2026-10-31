// Direct Comfy prompts carry an opaque per-submission token in extra_data.
// Comfy stores that data at index 3 in queue entries and history.prompt.
export async function findOwnedSubmission(fetch, requestId) {
  const match=item=>Array.isArray(item)&&typeof item[1]==='string'&&item[3]?.zura_studio_request===requestId?item[1]:null;
  const inQueue=async()=>{
    const queue=await fetch('/queue');
    return [...(queue.queue_running||[]),...(queue.queue_pending||[])].map(match).filter(Boolean);
  };
  const found=await inQueue();
  const queued=[...new Set(found)];
  if(queued.length>1)return null;
  if(queued.length===1)return queued[0];
  const history=await fetch('/history?max_items=100');
  for(const [id,entry] of Object.entries(history||{}))if(match(entry?.prompt)===id)found.push(id);
  // A request can move from submission to the queue while history is read.
  found.push(...await inQueue());
  const unique=[...new Set(found)];
  return unique.length===1?unique[0]:null;
}

export function adoptOwnedSubmission(ui, pending, id) {
  if(!id||ui.pendingSubmission!==pending)return false;
  ui.job={id,started:pending.started,config:pending.config,previewMethod:pending.previewMethod,stages:pending.stages};
  ui.pendingSubmission=null;ui.sampleStarted=null;ui.submitting=false;ui.submitAttempt=null;ui.save();
  ui.$('progress-title').textContent='Queued';ui.message('');ui.render();
  return true;
}

export async function recoverOwnedSubmission(ui) {
  if(!ui.pendingSubmission||ui.job||ui.polling)return;
  const pending=ui.pendingSubmission;ui.polling=true;
  try{
    const id=await findOwnedSubmission(path=>ui.fetch(path),pending.requestId);
    if(ui.pendingSubmission!==pending)return;
    if(id)adoptOwnedSubmission(ui,pending,id);
    else ui.message('Checking whether the run started. Check the ComfyUI queue; this run will not be submitted again automatically.');
  }catch{
    if(ui.pendingSubmission===pending)ui.message('Connection interrupted while checking your run. Reconnecting without submitting again…');
  }finally{ui.polling=false;}
}

export async function submitOwnedGraph(ui, graph, config, previewMethod, extra) {
  const pending={requestId:crypto.randomUUID(),started:Date.now(),config,previewMethod,
    stages:Object.fromEntries(Object.entries(graph).map(([id,node])=>[id,node._meta?.title]).filter(([,title])=>title))};
  ui.pendingSubmission=pending;
  if(ui.save()===false){ui.pendingSubmission=null;throw new Error('Browser storage is unavailable. Free storage before starting a tracked run.');}
  ui.$('progress-title').textContent=extra.zura_image?'Submitting image':'Submitting video';
  ui.$('progress-detail').textContent='Checking the ComfyUI queue…';
  ui.startPolling();
  try{
    const response=await ui.fetch('/prompt',{prompt:graph,client_id:ui.api.clientId,
      extra_data:{...extra,preview_method:previewMethod,zura_studio_request:pending.requestId}});
    if(response.prompt_id)adoptOwnedSubmission(ui,pending,response.prompt_id);
    else if(ui.pendingSubmission===pending)ui.message('Checking whether the run started. This run will not be submitted again automatically.');
  }catch(error){
    if(ui.pendingSubmission!==pending)return;
    // A validation rejection is definitive; transport failures and 5xx are not.
    if(error.status>=400&&error.status<500){ui.pendingSubmission=null;ui.stopPolling();ui.save();throw error;}
    ui.message('Connection interrupted while starting the run. Checking its status without submitting again…');
  }
}

export async function cancelOwnedJob(ui) {
  const job=ui.job;
  if(!job||(job.cancelPending&&!job.cancelRetryAvailable))return;
  job.cancelPending=true;job.cancelRetryAvailable=false;ui.save();ui.render();
  ui.$('bar').removeAttribute('value');
  ui.$('progress-title').textContent='Cancelling…';
  ui.$('progress-detail').textContent='Waiting for ComfyUI to stop this run.';
  try{
    await ui.fetch('/queue',{delete:[job.id]});
    if(ui.job!==job)return;
    await ui.fetch('/interrupt',{prompt_id:job.id});
  }catch{
    if(ui.job===job){job.cancelRetryAvailable=true;ui.save();ui.render();ui.message('Could not confirm cancellation. Retry cancellation or wait for the run to finish.');}
  }
  if(ui.job===job)await ui.poll();
}

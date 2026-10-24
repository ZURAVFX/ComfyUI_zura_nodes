/** Native Comfy sample stream. Metadata is checked before any image is shown. */
export function installNativeSamplePreview(api,{getJob,onPreview,onClear=()=>{}}){
  let currentPrompt=null,lastProgress=null,url=null,disposed=false;
  const metadataBlobs=new WeakSet(),listeners=[];
  const listen=(type,fn)=>{api.addEventListener?.(type,fn);listeners.push([type,fn]);};
  const clear=()=>{if(url){URL.revokeObjectURL(url);url=null;}onClear();};
  const show=(blob,id,node)=>{
    const job=getJob();if(disposed||!job?.id||job.id!==id||!blob||typeof blob.arrayBuffer!=='function')return;
    if(!/^image\/(?:jpeg|png|webp)$/.test(blob.type))return;
    if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(blob);
    onPreview({src:url,promptId:id,nodeId:node,caption:job.previewMethod==='taesd'?'Live TAE sample · first frame · approximate':'Live sample · approximate colours'});
  };
  listen('execution_start',e=>{currentPrompt=e.detail?.prompt_id||null;lastProgress=null;clear();});
  listen('progress',e=>{lastProgress=e.detail?.prompt_id||null;if(lastProgress&&lastProgress===getJob()?.id)currentPrompt=lastProgress;});
  listen('b_preview_with_metadata',e=>{const d=e.detail||{};if(d.blob&&typeof d.blob==='object')metadataBlobs.add(d.blob);show(d.blob,d.jobId||d.prompt_id,d.nodeId||d.node_id);});
  listen('b_preview',e=>{const blob=e.detail;if(blob&&metadataBlobs.has(blob))return;const job=getJob();if(job?.id===currentPrompt&&lastProgress===currentPrompt)show(blob,currentPrompt,null);});
  for(const type of ['execution_success','execution_error','execution_interrupted'])listen(type,e=>{if(e.detail?.prompt_id===getJob()?.id){currentPrompt=null;lastProgress=null;clear();}});
  return {clear,dispose(){if(disposed)return;disposed=true;for(const [type,fn] of listeners)api.removeEventListener?.(type,fn);clear();}};
}

export async function nativePreviewMethod(api,engine='h3'){
  const expected=engine==='h3'?'taeh3.safetensors':engine==='wan'?'lighttaew2_1.safetensors':null;
  if(!expected)return 'auto';
  try{const response=await api.fetchApi('/models/vae_approx');if(!response.ok)return 'auto';const files=await response.json();return Array.isArray(files)&&files.some(f=>String(f).replaceAll('\\','/').split('/').at(-1).toLowerCase()===expected)?'taesd':'auto';}catch{return 'auto';}
}

/** Canvas view shared by endpoint and multi-reference workspaces. */
export function attachWorkspaceSamplePreview(owner){
  if(owner.nativeSamplePreview)return;
  let figure=owner.page.querySelector('.zura-live-sample');
  if(!figure){figure=document.createElement('figure');figure.className='zura-live-sample';figure.hidden=true;figure.innerHTML='<figcaption>Live sample · approximate</figcaption>';owner.page.querySelector('.zf-viewer').append(figure);}
  owner.nativeSamplePreview=installNativeSamplePreview(owner.api,{
    getJob:()=>owner.job,
    onPreview:sample=>{if(!owner.job)return;let image=figure.querySelector('img');if(!image){image=document.createElement('img');image.alt='Approximate live generation sample';image.src=sample.src;figure.prepend(image);}else image.src=sample.src;figure.querySelector('figcaption').textContent=sample.caption;figure.hidden=false;},
    onClear:()=>{figure.hidden=true;figure.querySelector('img')?.remove();},
  });
}

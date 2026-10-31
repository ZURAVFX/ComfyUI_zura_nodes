/** Artist-facing milestones. Node progress remains local to its actual stage. */
export function describeGeneration(job={}, {kind}={}) {
  const node=String(job.currentNode||job.node||''), type=kind||job.kind||'render';
  const frame=['frame','clean-frame','clean'].includes(type)||node.startsWith('frame_');
  const mask=['mask','preview','track'].includes(type)||node==='mask_pass';
  const single=type==='preview'||job.single===true||job.maskSingle===true||job.preview===true;
  const hdr=job.phase==='hdr'||node.startsWith('hdr_');
  const steps=mask?['Prepare',single?'Select':'Track','Save']:['Prepare','Generate','Save'];
  let current=-1;
  if(node){
    current=0;
    if(frame){if(node==='frame_sample')current=1;else if(['frame_decode','frame_save'].includes(node))current=2;}
    else if(mask){if(/track|mask_pass|sample/.test(node))current=1;if(/save|commit/.test(node))current=2;}
    else {if(/(^sample$|hdr_sample|sampling)/.test(node))current=1;if(/(^decode$|crop_guides|save|hdr_decode|hdr_finish)/.test(node))current=2;}
  }
  const next=frame?'The finished paint will appear on this clean frame as a new layer. Check it, then paint another area or continue to Render.'
    :mask&&single?'The red selection will appear on this frame. Check it, then choose Track mask to follow the subject through the shot.':mask?'The mask will appear in red on the viewer and as a section on the timeline. Scrub through it, then add another mask if needed.'
    :job.phase==='repair'?'The repaired clip will be saved first. Then choose Convert repaired clip to HDR; you can retry HDR without repeating the repair.'
    :hdr?'The HDR clip will appear in Result. Review it before exporting; your saved SDR repair stays available on disk.'
    :'The finished clip will appear in Result. Play it through, then download the video or image sequence.';
  if(current<0)return {steps,current,title:'Waiting to start',help:'Your run is queued. These steps begin when ComfyUI starts processing it.',next};
  const title=current===0?(frame?'Preparing your paint':mask?'Preparing the subject mask':hdr?'Preparing the saved repair for HDR':'Preparing the repair')
    :current===1?(frame?'Painting the selected area':mask?(single?'Selecting the subject on this frame':'Tracking the mask through the selected range'):hdr?'Generating HDR':'Generating the repaired clip')
    :(frame?'Saving this paint layer':mask?(single?'Finishing the mask preview':'Saving the tracked mask'):hdr?'Saving HDR files':'Saving the repaired clip');
  const help=current===0?'Reading the source and loading the required models. The finished result is not ready yet.'
    :current===1?(mask?'Following the selected subject. The red mask will update when tracking finishes.':'The model is working. Any preview shown now is unfinished; the progress bar describes the current processing step.')
    :'Reconstructing the full-resolution output and writing it to disk. Wait for saving to finish before reviewing it.';
  return {steps,current,title,help,next};
}

export function updateGenerationSteps(container,job,options={}) {
  if(!container)return;
  container.hidden=!job;
  if(!job){container.replaceChildren();return null;}
  const description=describeGeneration(job,options),list=document.createElement('ol');
  list.className='zps-generation-steps';list.setAttribute('aria-label','Generation steps');
  for(const [index,label] of description.steps.entries()){
    const item=document.createElement('li');item.textContent=label;
    if(index===description.current)item.setAttribute('aria-current','step');
    if(description.current>=0&&index<description.current){item.className='is-complete';item.setAttribute('aria-label',label+' complete');}
    list.append(item);
  }
  const help=document.createElement('p');help.className='zps-generation-help';help.textContent=description.help;
  const next=document.createElement('p');next.className='zps-generation-next';next.textContent=description.next;
  container.replaceChildren(list,help,next);
  return description;
}

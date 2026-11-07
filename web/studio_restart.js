import {cancelOwnedJob} from './studio_owned_jobs.js';

const STYLE_URL=new URL('./studio_restart.css',import.meta.url);
const RESTART_LABEL='Start over';

const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

function currentMode(creative){
  return creative?.mode||'video';
}

function workspaceFor(creative){
  switch(currentMode(creative)){
    case 'image': return creative;
    case 'frames': return creative.frames;
    case 'references': return creative.referencesVideo;
    case 'paintout': return creative.paintout;
    case 'watermark': return creative.watermark;
    case 'outpaint': return creative.outpaint;
    case 'ripple': return creative.ripple;
    case 'hdr': return creative.studio?.hdrTool;
    case 'panorama': return creative.panorama;
    default: return creative?.studio;
  }
}

function invokeBusy(workspace){
  if(!workspace)return false;
  if(typeof workspace.busy==='function')return !!workspace.busy();
  return !!workspace.busy;
}

export function studioWorkspaceBusy(creative){
  const mode=currentMode(creative),workspace=workspaceFor(creative);
  if(mode==='video'){
    const studio=creative?.studio;
    return !!studio?.busy||studio?.project?.phase==='working'||!!studio?.resetting;
  }
  if(mode==='image')return !!(workspace?.job||workspace?.pendingSubmission||workspace?.submitting||workspace?.uploading);
  if(mode==='frames'||mode==='references')return !!(
    workspace?.job||workspace?.pendingSubmission||workspace?.submitting||workspace?.uploading||
    workspace?.hdrOutput?.busy||invokeBusy(workspace)
  );
  if(mode==='paintout'||mode==='watermark'||mode==='ripple')return !!(workspace?.job||workspace?.pendingSubmission||workspace?.submitting||workspace?.uploading||workspace?.picking||workspace?.exporting||invokeBusy(workspace));
  if(mode==='outpaint')return !!(
    workspace?.job||workspace?.submitting||workspace?.hdrSubmitting||
    workspace?.layers?.busy||workspace?.hdrDelivery?.busy||invokeBusy(workspace)
  );
  if(mode==='hdr')return !!(
    workspace?.job||workspace?.busy||workspace?.starting||workspace?.cancelling||
    workspace?.longClient?.busy||workspace?.longClient?.cancelPending||
    (typeof workspace?.busy==='function'&&workspace.busy())
  );
  if(mode==='panorama')return !!(workspace?.job||workspace?.pendingSubmission||workspace?.submitting||workspace?.uploading||workspace?.editor||invokeBusy(workspace));
  return false;
}

function resetFormDefaults(page,{skip=[]}={}){
  if(!page)return;
  for(const input of page.querySelectorAll('input')){
    if(input.type==='file'){input.value='';continue;}
    if(skip.includes(input.id))continue;
    if(input.type==='checkbox'||input.type==='radio')input.checked=input.defaultChecked;
    else input.value=input.defaultValue;
    input.removeAttribute('aria-invalid');
    delete input.dataset.inputError;
  }
  for(const textarea of page.querySelectorAll('textarea')){
    if(!skip.includes(textarea.id))textarea.value=textarea.defaultValue;
  }
  for(const select of page.querySelectorAll('select')){
    if(skip.includes(select.id))continue;
    const option=Array.from(select.options).find(item=>item.defaultSelected);
    select.selectedIndex=option?option.index:(select.options.length?0:-1);
  }
}

function clearMedia(element){
  if(!element)return;
  element.pause?.();
  element.removeAttribute?.('src');
  element.load?.();
  element.hidden=true;
}

async function resetVideoWorkspace(studio){
  if(!studio)return false;
  const workflow_mode=studio.config?.workflow_mode||'motion';
  const requestedEngine=studio.config?.engine;
  const engines=new Set(['local','h3','wan','wan2','wan21','seedance']);
  const engine=workflow_mode==='camera'
      ?'h3'
      :workflow_mode==='relight'
        ?'h3'
        :engines.has(requestedEngine)?requestedEngine:'h3';
  const relight_engine=workflow_mode==='relight'?'wan21':studio.config?.relight_engine;
  const result=await studio.reset?.();
  if(result===false)return false;
  studio.config={...studio.config,workflow_mode,engine,...(relight_engine?{relight_engine}:{})};
  studio.navigationStep=null;
  studio.syncForm?.();
  studio.render?.();
  return true;
}

function resetFrameWorkspace(workspace,creative){
  if(!workspace)return false;
  workspace.stopPolling?.();
  workspace.nativeSamplePreview?.clear?.();
  workspace.assets={};
  workspace.job=null;
  workspace.pendingSubmission=null;
  workspace.submitting=false;
  workspace.uploading=false;
  workspace.submitAttempt=null;
  workspace.selectedResult=null;
  resetFormDefaults(workspace.page,{skip:['zc-video-task']});
  clearMedia(workspace.$?.('result'));
  const imageSlot=workspace.$?.('image-slot');
  if(imageSlot){imageSlot.innerHTML='';imageSlot.hidden=true;}
  if(workspace.$?.('empty'))workspace.$('empty').hidden=false;
  workspace.selectAvailability?.();
  workspace.renderHistory?.();
  workspace.save?.();
  workspace.render?.();
  workspace.preview?.();
  clearMedia(workspace.$?.('result'));
  workspace.message?.('');
  creative?.show?.('frames');
  return true;
}

function resetReferenceWorkspace(workspace,creative){
  if(!workspace)return false;
  workspace.stopPolling?.();
  workspace.nativeSamplePreview?.clear?.();
  workspace.assets={images:[],videos:[],audios:[]};
  workspace.firstFrame='';
  workspace.audioDriver='';
  workspace.job=null;
  workspace.pendingSubmission=null;
  workspace.submitting=false;
  workspace.uploading=false;
  workspace.submitAttempt=null;
  resetFormDefaults(workspace.page,{skip:['zc-video-task']});
  clearMedia(workspace.$?.('result'));
  const imageSlot=workspace.$?.('image-slot');
  if(imageSlot){imageSlot.innerHTML='';imageSlot.hidden=true;}
  if(workspace.$?.('empty'))workspace.$('empty').hidden=false;
  workspace.selectAvailability?.();
  workspace.renderHistory?.();
  workspace.save?.();
  workspace.render?.();
  workspace.preview?.();
  clearMedia(workspace.$?.('result'));
  workspace.message?.('');
  creative?.show?.('references');
  return true;
}

function resetImageWorkspace(creative){
  if(!creative)return false;
  const operation=creative.imageOperation==='edit'?'edit':'create';
  const selectedModel=creative.$?.('model')?.value||creative.draft?.model||'';
  creative.stopPolling?.();
  creative.job=null;
  creative.pendingSubmission=null;
  creative.submitting=false;
  creative.uploading=false;
  creative.references=[];
  creative.editMainMissing=false;
  creative.autoCanvasSuppressed=true;
  creative.imageLoras=[];
  creative.imageOperation=operation;
  creative.draft={operation,...(selectedModel?{model:selectedModel}:{})};
  creative.selectedImage=-1;
  creative.imageSizeRatio=null;
  const page=creative.root?.querySelector?.('.zc-image-page');
  resetFormDefaults(page,{skip:['zc-model']});
  if(selectedModel&&creative.$?.('model'))creative.$('model').value=selectedModel;
  if(creative.$?.('prompt'))creative.$('prompt').value='';
  creative.save?.();
  creative.renderGallery?.();
  const gallery=creative.$?.('gallery');
  if(gallery)gallery.innerHTML='';
  const empty=creative.$?.('image-empty');
  if(empty)empty.hidden=false;
  creative.render?.();
  creative.message?.('');
  creative.show?.('image');
  return true;
}

function resetOutpaintWorkspace(creative){
  const workspace=creative?.outpaint;
  if(!workspace)return false;
  const Constructor=workspace.constructor;
  workspace.close?.();
  workspace.dispose?.();
  if(typeof Constructor!=='function')return false;
  for(const key of [
    'zura-outpaint-hdr-record',
    'zura-outpaint-hdr-take',
    'zura-outpaint-hdr-job',
    'zura-outpaint-hdr-request',
  ]){
    try{localStorage.removeItem(key);}catch{}
  }
  creative.outpaint=new Constructor(creative);
  creative.outpaint.save?.();
  creative.show?.('outpaint');
  return true;
}

export async function resetStudioWorkspace(creative){
  const mode=currentMode(creative);
  if(mode==='video'){
    return resetVideoWorkspace(creative?.studio);
  }
  if(mode==='image')return resetImageWorkspace(creative);
  if(mode==='frames')return resetFrameWorkspace(creative?.frames,creative);
  if(mode==='references')return resetReferenceWorkspace(creative?.referencesVideo,creative);
  if(mode==='paintout'){
    const result=await creative?.paintout?.reset?.();
    creative?.show?.('paintout');
    return result!==false;
  }
  if(mode==='watermark'){
    const result=await creative?.watermark?.reset?.();
    creative?.show?.('watermark');
    return result===true;
  }
  if(mode==='outpaint')return resetOutpaintWorkspace(creative);
  if(mode==='ripple'){
    if(typeof creative?.ripple?.reset!=='function')return false;
    const result=await creative.ripple.reset();
    if(result!==false)creative.show?.('ripple');
    return result!==false;
  }
  if(mode==='hdr'){
    const tool=creative?.studio?.hdrTool;
    if(typeof tool?.reset!=='function')return false;
    const result=await tool.reset({keepSource:false});
    creative?.show?.('hdr');
    return result!==false;
  }
  if(mode==='panorama'){
    const result=await creative?.panorama?.reset?.();
    creative?.show?.('panorama');
    return result!==false;
  }
  if(mode==='home'){
    creative?.show?.('video');
    return true;
  }
  return false;
}

async function cancelStudioWorkspace(creative){
  const mode=currentMode(creative),workspace=workspaceFor(creative);
  if(mode==='video')return false;
  if(mode==='watermark'&&workspace?.editor?.busy())await workspace.editor.cancel?.();
  if(mode==='hdr')await workspace?.cancel?.();
  else if(mode==='panorama'&&typeof workspace?.cancel!=='function')await cancelOwnedJob(workspace);
  else await workspace?.cancel?.();
  return true;
}

async function waitForIdle(creative,mode,{timeout=15000,interval=150}={}){
  const started=Date.now();
  while(currentMode(creative)===mode&&studioWorkspaceBusy(creative)){
    if(Date.now()-started>=timeout)return false;
    await sleep(interval);
  }
  return currentMode(creative)===mode;
}

function installStyles(document){
  const existing=document.head?.querySelector('link[data-zura-studio-restart]');
  if(existing)return existing;
  const link=document.createElement('link');
  link.rel='stylesheet';
  link.href=STYLE_URL.href;
  link.dataset.zuraStudioRestart='';
  document.head?.append(link);
  return link;
}

function modeLabel(mode){
  return ({
    video:'this video workspace',
    image:'this image workspace',
    frames:'First & last frame',
    references:'Reference to video',
    paintout:'Paintout',
    watermark:'Watermark removal',
    outpaint:'Frame extension',
    ripple:'Ripple editing',
    hdr:'HDR',
    panorama:'Camera angle',
  })[mode]||'this workspace';
}

function navigateVideoStage(studio,index){
  if(!studio||typeof studio.render!=='function')return;
  index=Number(index);
  if(!Number.isInteger(index)||index<0||index>3)return false;
  if(index===0){
    studio.promptStage=null;
    studio.preview=studio.source?'original':'mask';
    studio.navigationStep=0;
    studio.creative?.selectPanel?.('source');
  }else if(index===1){
    if(!studio.source)return false;
    studio.promptStage=studio.frameAccepted?.()?'review':'image';
    studio.preview='look';
    studio.navigationStep=1;
    studio.creative?.selectPanel?.('look');
  }else if(index===2){
    if(!studio.source)return false;
    studio.promptStage=studio.frameAccepted?.()?null:'review';
    studio.preview='look';
    studio.navigationStep=2;
    studio.creative?.selectPanel?.('settings');
  }else{
    if(!studio.project?.results?.length)return false;
    studio.promptStage=null;
    studio.preview='look';
    studio.navigationStep=3;
    studio.creative?.selectPanel?.('settings');
  }
  studio.render();
  return true;
}

function currentVideoStage(studio){
  if(Number.isInteger(studio?.navigationStep))return studio.navigationStep;
  if(!studio?.source)return 0;
  if(studio.project?.results?.length&&['done','draft'].includes(studio.project.phase))return 3;
  if(!studio.frameAccepted?.())return 1;
  return 2;
}

export function installStudioRestartNavigation(studio,options={}){
  const creative=studio?.creative;
  if(!creative?.root)throw new Error('Studio restart navigation needs an initialised creative workspace.');
  if(studio.restartNavigation?.dispose)studio.restartNavigation.dispose();
  const document=creative.root.ownerDocument;
  const style=installStyles(document);
  const workspaceHeading=()=>{
    const mode=currentMode(creative),workspace=workspaceFor(creative);
    if(mode==='image')return creative.root.querySelector('.zc-image-heading');
    if(mode==='video')return creative.root.querySelector('.gs-preview-heading');
    const page=workspace?.page||workspace?.root;
    return page?.querySelector('.zf-heading,.zpc-heading,.zru-heading,header');
  };

  const wrap=document.createElement('div');
  wrap.className='zrn-restart-wrap';
  wrap.innerHTML=`<button type="button" class="zrn-restart" data-zura-restart aria-label="${RESTART_LABEL}" title="${RESTART_LABEL}">${RESTART_LABEL}</button><div class="zrn-restart-confirm" role="status" hidden><p>This workspace has an active run. Nothing has been cleared.</p><div><button type="button" data-keep-run>Keep run</button><button type="button" data-cancel-reset>Cancel run and start over</button></div></div>`;
  const button=wrap.querySelector('[data-zura-restart]');
  const confirmation=wrap.querySelector('.zrn-restart-confirm');
  const cancelReset=wrap.querySelector('[data-cancel-reset]');
  const keepRun=wrap.querySelector('[data-keep-run]');
  const primary=studio.$?.('primary');

  let operationMode=null;
  let working=false;
  const closeConfirmation=()=>{
    confirmation.hidden=true;
    button.setAttribute('aria-expanded','false');
  };
  const showConfirmation=(error='')=>{
    const mode=currentMode(creative);
    confirmation.querySelector('p').textContent=error||`${modeLabel(mode)} has an active run. Nothing has been cleared.`;
    cancelReset.textContent=error?'Try cancellation again':'Cancel run and start over';
    confirmation.hidden=false;
    button.setAttribute('aria-expanded','true');
    cancelReset.focus({preventScroll:true});
  };

  const sync=()=>{
    const mode=currentMode(creative);
    const heading=workspaceHeading();
    if(heading&&wrap.parentElement!==heading){heading.append(wrap);closeConfirmation();}
    wrap.hidden=!heading;
    if(operationMode&&operationMode!==mode)closeConfirmation();
    button.disabled=working;
    button.textContent=working?'Starting over…':RESTART_LABEL;
    button.title=studioWorkspaceBusy(creative)?`${modeLabel(mode)} has an active run. Start over will ask before cancelling it.`:`Clear ${modeLabel(mode)} inputs and return to its first step. Saved files and other workspaces stay intact.`;
  };

  const resetWhenIdle=async mode=>{
    if(currentMode(creative)!==mode)throw new Error('The workspace changed. Nothing was cleared.');
    if(studioWorkspaceBusy(creative)){showConfirmation();return false;}
    working=true;button.disabled=true;button.textContent='Starting over…';
    try{
      const cleared=await resetStudioWorkspace(creative);
      if(!cleared)throw new Error('This workspace is not ready to reset yet.');
      closeConfirmation();
      sync();
      return true;
    }finally{
      working=false;sync();
    }
  };

  button.onclick=async()=>{
    if(working)return;
    const mode=currentMode(creative);
    if(studioWorkspaceBusy(creative)){showConfirmation();return;}
    try{await resetWhenIdle(mode);}catch(error){showConfirmation(error.message);}
  };

  cancelReset.onclick=async()=>{
    if(working)return;
    const mode=currentMode(creative);
    operationMode=mode;working=true;button.disabled=true;cancelReset.disabled=true;
    try{
      if(mode==='video'){
        // ArtistStudio.reset() owns this project's cancellation and only clears
        // after ComfyUI confirms that the project is no longer working.
        const cleared=await resetStudioWorkspace(creative);
        if(!cleared)throw new Error('The current run is still active. Nothing was cleared.');
      }else{
        await cancelStudioWorkspace(creative);
        const idle=await waitForIdle(creative,mode,options);
        if(!idle)throw new Error('The current run is still active. Nothing was cleared.');
        const cleared=await resetStudioWorkspace(creative);
        if(!cleared)throw new Error('This workspace is not ready to reset yet.');
      }
      closeConfirmation();
    }catch(error){
      showConfirmation(error.message||'The current run could not be stopped. Nothing was cleared.');
    }finally{
      operationMode=null;working=false;cancelReset.disabled=false;sync();
    }
  };
  keepRun.onclick=()=>{closeConfirmation();button.focus({preventScroll:true});};
  const clearNavigationStep=()=>{studio.navigationStep=null;};
  primary?.addEventListener?.('click',clearNavigationStep,true);

  const originalShow=creative.show;
  const wrappedShow=function(...args){
    if(args[0]!=='video')studio.navigationStep=null;
    const result=originalShow.apply(this,args);
    sync();
    return result;
  };
  creative.show=wrappedShow;

  const outside=event=>{
    if(confirmation.hidden||wrap.contains(event.target))return;
    closeConfirmation();
  };
  const escape=event=>{
    if(event.key!=='Escape'||confirmation.hidden)return;
    closeConfirmation();button.focus({preventScroll:true});event.preventDefault();
  };
  document.addEventListener('click',outside,true);
  document.addEventListener('keydown',escape);
  sync();

  const controller={
    button,
    confirmation,
    sync,
    navigateStep(index){
      if(currentMode(creative)!=='video')return false;
      if(studioWorkspaceBusy(creative))return false;
      const target=Number(index),current=currentVideoStage(studio);
      if(!Number.isInteger(target)||target<0||target>=current)return false;
      return navigateVideoStage(studio,target);
    },
    async reset(){const mode=currentMode(creative);return resetWhenIdle(mode);},
    dispose(){
      document.removeEventListener('click',outside,true);
      document.removeEventListener('keydown',escape);
      primary?.removeEventListener?.('click',clearNavigationStep,true);
      if(creative.show===wrappedShow)creative.show=originalShow;
      wrap.remove();
      style?.remove?.();
      if(studio.restartNavigation===controller)studio.restartNavigation=null;
    },
  };
  studio.restartNavigation=controller;
  return controller;
}

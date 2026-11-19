import {workspaceStorage} from './studio_storage.js';
import {cancelOwnedJob} from './studio_owned_jobs.js';
import {activeStudioMode} from './studio_mode_adapters.js';

const STYLE_URL=new URL('./studio_restart.css',import.meta.url);
const RESTART_LABEL='Start over';

const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

function currentMode(creative){
  return creative?.mode||'video';
}

function workspaceFor(creative){
  switch(currentMode(creative)){
    case 'image': return creative;
    case 'paint_vfx': return creative.paint_vfx;
    case 'frames': return creative.frames;
    case 'director': return creative.director;
    case 'references': return creative.referencesVideo;
    case 'paintout': return creative.paintout;
    case 'watermark': return creative.watermark;
    case 'outpaint': return creative.outpaint;
    case 'ripple': return creative.ripple;
    case 'alpha': return creative.alpha;
    case 'upscale': return creative.upscale;
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
  if(mode==='image')return !!(workspace?.job||workspace?.pendingSubmission||workspace?.submitting||workspace?.uploading||workspace?.imageLayers?.busy||creative.outpaintGuide?.importing||creative.rippleImage?.importing);
  if(mode==='paint_vfx')return invokeBusy(workspace);
  if(mode==='frames'||mode==='references'||mode==='director')return !!(
    workspace?.job||workspace?.pendingSubmission||workspace?.submitting||workspace?.uploading||
    workspace?.hdrOutput?.busy||invokeBusy(workspace)
  );
  if(mode==='paintout'||mode==='watermark'||mode==='ripple'||mode==='alpha'||mode==='upscale')return !!(workspace?.job||workspace?.pendingSubmission||workspace?.submitting||workspace?.uploading||workspace?.picking||workspace?.exporting||invokeBusy(workspace));
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
  workspace.sourceSize=true;
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
    try{workspaceStorage(creative).removeItem(key);}catch{}
  }
  creative.outpaint=new Constructor(creative);
  creative.outpaint.save?.();
  creative.show?.('outpaint');
  return true;
}

export async function resetStudioWorkspace(creative){
  const mode=currentMode(creative);
  if(mode==='video'){
    if(creative?.studio?.config?.workflow_mode==='relight'){const lighting=creative.rippleWorkspaces?.get('relight');if(lighting?.busy())return false;lighting?.reset();}
    return resetVideoWorkspace(creative?.studio);
  }
  if(mode==='image'){
    const handoff=creative.outpaintGuide?.request?creative.outpaintGuide:creative.rippleImage?.request?creative.rippleImage:null;
    if(!handoff)return resetImageWorkspace(creative);
    await handoff.leave();
    return currentMode(creative)!=='image'&&resetStudioWorkspace(creative);
  }
  if(mode==='paint_vfx')return creative.paint_vfx?.reset?.()??false;
  if(mode==='frames')return resetFrameWorkspace(creative?.frames,creative);
  if(mode==='director'){
    const result=await creative?.director?.reset?.();
    if(result!==false)creative?.show?.('director');
    return result!==false;
  }
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
  if(mode==='upscale')return creative?.upscale?.reset?.()===true;
  if(mode==='alpha'){
    if(typeof creative?.alpha?.reset!=='function')return false;
    const result=await creative.alpha.reset();
    if(result!==false)creative.show?.('alpha');
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
  if(mode==='paint_vfx')await cancelOwnedJob(workspace);
  else if(mode==='hdr')await workspace?.cancel?.();
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
    swap:'Character replacement',
    viewport:'Viewport to final',
    relight:'Relight',
    frames:'First & last frame',
    director:'Director',
    references:'Reference to video',
    paintout:'Add, remove & replace',
    paint_vfx:'Paint VFX',
    watermark:'Watermark removal',
    outpaint:'Frame extension',
    ripple:'Ripple editing',
    alpha:'Extract alpha',
    upscale:'Upscale video',
    hdr:'HDR',
    panorama:'Camera angle',
    camera:'Camera angle',
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
  const actions=creative.root.querySelector('.gs-top-actions')||creative.root;
  const wrap=document.createElement('div');
  wrap.className='zrn-restart-wrap';
  wrap.innerHTML=`<button type="button" class="zrn-restart" data-zura-restart aria-haspopup="dialog" aria-expanded="false">${RESTART_LABEL}</button><div class="zrn-restart-confirm" role="dialog" aria-label="Start over" aria-describedby="zrn-restart-message" hidden><p id="zrn-restart-message"></p><div><button type="button" data-keep-run>Keep working</button><button type="button" data-cancel-reset>Start over</button></div></div>`;
  const button=wrap.querySelector('[data-zura-restart]');
  const confirmation=wrap.querySelector('.zrn-restart-confirm');
  const cancelReset=wrap.querySelector('[data-cancel-reset]');
  const keepRun=wrap.querySelector('[data-keep-run]');
  const primary=studio.$?.('primary');
  const graph=actions.querySelector('#gs-exit');
  if(graph)graph.before(wrap);else actions.append(wrap);

  let pending=null,working=false;
  const modeId=()=>creative.outpaintGuide?.request?'outpaint':creative.studio?.config?activeStudioMode(creative):currentMode(creative);
  const snapshot=()=>({mode:currentMode(creative),id:modeId(),workspace:workspaceFor(creative),busy:studioWorkspaceBusy(creative)});
  const isCurrent=state=>state.mode===currentMode(creative)&&state.id===modeId()&&state.workspace===workspaceFor(creative);
  const closeConfirmation=()=>{
    pending=null;confirmation.hidden=true;button.setAttribute('aria-expanded','false');
  };
  const showConfirmation=(error='')=>{
    pending=snapshot();
    const label=modeLabel(pending.id);
    const suffix=' Unsaved edits and loaded media will be cleared. Saved files are kept.';
    confirmation.querySelector('p').textContent=error||(pending.busy?`Stop the current run and reset ${label}?`:`Reset ${label} to its first step?`)+suffix;
    cancelReset.textContent=pending.busy?'Cancel run and start over':'Start over';
    confirmation.hidden=false;
    button.setAttribute('aria-expanded','true');
    keepRun.focus({preventScroll:true});
  };

  const sync=()=>{
    if(pending&&!isCurrent(pending))closeConfirmation();
    button.disabled=working;
    button.textContent=working?'Starting over…':RESTART_LABEL;
  };

  button.onclick=()=>{
    if(working)return;
    if(confirmation.hidden)showConfirmation();else closeConfirmation();
  };

  const resetConfirmed=async(state)=>{
    const bridge=studio.aeBridge;
    if(bridge&&!bridge.closed&&(bridge.pending||bridge.sending||bridge.importPolling))throw Error('Wait for the After Effects transfer to finish, then try again.');
    const rollback=bridge?.pauseAutomaticSourceForReset?.(state.id);
    let cleared=false;
    try{
      if(studioWorkspaceBusy(creative)&&state.mode!=='video'){
        await cancelStudioWorkspace(creative);
        if(!await waitForIdle(creative,state.mode,options)||!isCurrent(state))throw Error('The current operation is still active. Try again when it finishes.');
      }
      if(!isCurrent(state))throw Error('The workspace changed. Try again in the current mode.');
      cleared=await resetStudioWorkspace(creative);
      if(!cleared)throw Error('This workspace is not ready to reset yet.');
      closeConfirmation();
    }finally{if(!cleared)rollback?.();}
  };

  cancelReset.onclick=async()=>{
    if(working||!pending||!isCurrent(pending))return;
    if(!pending.busy&&studioWorkspaceBusy(creative)){showConfirmation();return;}
    const state=pending;working=true;cancelReset.disabled=keepRun.disabled=true;sync();
    try{await resetConfirmed(state);}
    catch(error){if(isCurrent(state))showConfirmation(error.message||'This workspace could not be reset.');}
    finally{
      working=false;cancelReset.disabled=keepRun.disabled=false;sync();
      if(confirmation.hidden)button.focus({preventScroll:true});else keepRun.focus({preventScroll:true});
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
    reset(){if(!working)showConfirmation();},
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

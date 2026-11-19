import {applyComposerPatterns,disposeComposerPatterns} from './studio_composer_patterns.js';
/** Shared stage indicator. Reads existing workflow state; never starts jobs. */
import {nativeHDRRoute} from './studio_hdr_capabilities.js';
const running=w=>!!(w?.job||w?.pendingSubmission||w?.submitting||w?.busy===true||w?.project?.phase==='working');
const flow=(id,title,labels,active,raw)=>({id,title,labels,active,raw});
const reference=w=>w?.ltxReference?.()||w?.selected?.();
const hasResult=w=>!!(w?.selectedResult||w?.selectedTake||w?.result);

export function characterSwapStage(s){
  if(!s?.source)return 0;
  const p=s.project;if(!p?.review||p.phase==='new'||p.phase==='review')return 1;
  if(!p.opening_input||s.composerStage()!=='video')return 2;
  return ['done','draft'].includes(p.phase)&&p.results?.length?4:3;
}

export function workflowProgress(owner){
  const borrowed=owner.rippleImage?.request,plate=owner.plate;
  let mode=owner.mode,w,view;
  if(mode==='home'||!mode)return null;
  // The existing main-video indicator already owns these workflows.
  if(mode==='video'){w=owner.studio;if(w?.config?.workflow_mode!=='swap'||w.headSwap?.())return null;view=flow('character-swap','Character replacement',['Source','Mask subject','Reference frame','Video','Result'],characterSwapStage(w),w.selectedTake||w.project?.results?.at(-1));}
  if(mode==='image'&&borrowed){
    if(borrowed.workspace?.platePrimary)mode='paintout';
    else if(borrowed.workspace?.intent==='relight')mode='ripple';
    else if(borrowed.workspace)mode='ripple';
  }
  if(mode==='image'&&owner.outpaintGuide?.request)mode='outpaint';
  if(mode==='paintout'){
    w=owner.paintout;const action=plate?.action||'remove',remove=action==='remove',labels=remove?['Source','Trim clip','Mask','Clean frames','Video','Result']:['Source','Trim clip','Paint frame','Video','Result'];
    const result=!!w?.result,busy=running(w)||running(plate?.runner),anchors=w?.state?.anchors||[];
    const accepted=anchors.some(a=>a.file&&a.enabled!==false),stage=w?.editor?.stage;
    let active=!w?.state?.source?0:busy?labels.length-2:result?labels.length-1:1;
    if(!busy&&w?.state?.source){
      if(!w.state.clipTrimConfirmed||stage==='trim')active=1;
      else if(owner.mode==='image')active=2;
      else if(result&&(stage==='render'||!stage))active=labels.length-1;
      else if(remove)active=stage==='render'?4:stage==='clean'?3:2;
      else active=accepted?3:2;
    }
    view=flow('plate-'+action,remove?'Remove':action==='paint'?'Add':'Replace',labels,active,w?.result);
  }else if(mode==='watermark'){
    w=owner.watermark;view=flow(mode,'Watermark removal',['Source','Settings','Remove','Result'],!w?.state?.source?0:running(w)?2:w?.result?3:1,w?.result);
  }else if(mode==='ripple'){
    w=borrowed?.workspace||owner.ripple;const relight=w?.intent==='relight',labels=['Source',relight?'Lighting frame':'Edited frame','Video','Result'];
    const ready=!!reference(w)?.file;
    view=flow(relight?'relight':'ripple',relight?'Relight':'Video edit',labels,!w?.source?0:running(w)?2:w?.result?3:owner.mode==='image'?1:ready?2:1,w?.result);
  }else if(mode==='panorama'){
    w=owner.panorama;const state=w?.state||{};
    view=flow('camera','Change camera angle',['Source','Camera','Video','Result'],!state.source?0:running(w)?(state.cameraReviewed?2:1):state.result?3:state.cameraReviewed?2:1,state.result);
  }else if(mode==='outpaint'){
    w=owner.outpaint;view=flow(mode,'Frame extension',['Source','Canvas','Generate','Result'],!w?.source?0:running(w)?2:w?.completedResult||w?.outputRef?3:1,w?.completedResult);
  }else if(mode==='extend_length'){
    w=owner.extendLength;view=flow(mode,'Extend length',['Source','Trim & direct','Extend','Result'],!w?.source?0:running(w)?2:w?.result?3:1,w?.result);
  }else if(mode==='upscale'){
    w=owner.upscale;view=flow(mode,'Upscale video',['Source','Upscale','Result'],running(w)?1:w?.result?2:0,w?.result);
  }else if(mode==='alpha'){
    w=owner.alpha;view=flow(mode,'Extract alpha',['Source','Settings','Extract','Result'],!w?.source?0:running(w)?2:w?.result?3:1,w?.result);
  }else if(mode==='hdr'){
    w=owner.studio?.hdrTool;view=flow(mode,'Convert to HDR',['Source','Settings','Convert HDR','Result'],!w?.sourceInfo?0:running(w)||w?.starting?2:w?.completedResult?3:1,w?.completedResult);
  }else if(mode==='paint_vfx'){
    w=owner.paint_vfx;const keys=w?.state?.keys||[],painted=[0,(w?.state?.frames||1)-1].every(frame=>keys.some(key=>key.frame===frame&&key.painted&&key.image));
    view=flow(mode,'Paint VFX',['Paint frames','Video','Result'],running(w)?1:w?.result?2:painted?1:0,w?.result);
  }else if(mode==='frames'){
    w=owner.frames;const assets=w?.assets||{},ready=!!assets.first;
    view=flow(mode,'First and last frame',['Frames','Settings','Video','Result'],running(w)?2:hasResult(w)?3:ready?1:0,w?.selectedTake||w?.selectedResult||w?.result);
  }else if(mode==='references'){
    w=owner.referencesVideo;const assets=w?.assets||{},ready=!!(assets.images?.length||assets.videos?.length||assets.audios?.length);
    view=flow(mode,'Reference to video',['References','Settings','Video','Result'],running(w)?2:hasResult(w)?3:ready?1:0,w?.selectedTake||w?.selectedResult||w?.result);
  }else if(mode==='director'){
    w=owner.director;view=flow(mode,'Director',['Plan shots','Generate','Result'],running(w)?1:w?.resultView&&w?.selectedResult?2:0,w?.resultView?w?.selectedResult:null);
  }else if(mode==='image'){
    const item=owner.items?.[owner.selectedImage],hdr=owner.outputSettings?.delivery?.output==='hdr';
    if(owner.imageIntent==='hdri')view=flow('hdri','Environment',['Environment','Generate','Result'],running(owner)?1:item?.file?2:0,item);
    else if(owner.imageOperation==='edit')view=flow('image','Image edit',['Source','Edit','Result'],running(owner)?1:item?.file?2:owner.references?.length&&!owner.editMainMissing?1:0,item);
    else if(hdr)view=flow('image','Create HDR image',['Image','Result'],item?.file&&!running(owner)?1:0,item);
  }
  if(!view)return null;
  const delivery=owner.outputSettings?.delivery;
  const nativeMode=mode==='video'?'swap':mode==='ripple'?(w?.intent==='relight'?'relight':'ripple'):mode==='panorama'?'camera':mode;
  if(view.id!=='hdr'&&view.id!=='upscale'&&view.id!=='extend_length'&&delivery?.output==='hdr'&&!borrowed&&!nativeHDRRoute(owner,nativeMode,w,typeof w?.config==='object'?w.config:{})){
    const recordMode=mode==='video'?'swap':mode==='ripple'?(w?.intent==='relight'?'relight':'ripple'):mode==='panorama'?'camera':mode;
    let delivered=view.raw;try{delivered=delivery.raw?.(recordMode)||delivered;}catch{}
    const output=view.labels.length-1,record=delivered&&delivery.recordFor?.(recordMode,delivered);
    view.labels=[...view.labels.slice(0,output),'Convert HDR',view.labels[output]];
    if(view.active===output)view.active=record?.state==='complete'||delivery.alreadyHDR?.(delivered)?output+1:output;
    if((delivery.preparing||delivery.delivery?.busy)&&(!delivery.activeMode||delivery.activeMode===recordMode)&&view.raw)view.active=output;
  }
  return view;
}

export function workflowNavigation(owner,view){
  if(!view.id.startsWith('plate-'))return null;
  const surface=owner.plate?.surface,w=owner.paintout;
  if(!surface?.navigateStage)return null;
  const busy=typeof w?.busy==='function'?w.busy():running(w);
  const source=!!w?.state?.source,trimmed=!!w?.state?.clipTrimConfirmed;
  const mask=!!(w?.state?.mask||w?.maskInfo),anchors=w?.state?.anchors?.some(a=>a.file&&a.enabled!==false);
  const enabled=label=>!busy&&({Source:true,'Trim clip':source,Mask:trimmed,'Clean frames':mask,'Paint frame':trimmed,Video:!!(anchors||w?.state?.mode==='full')&&trimmed,Result:!!w?.result}[label]||false);
  return {enabled,go:label=>Promise.resolve(surface.navigateStage(label)).catch(error=>w?.message?.(error.message))};
}

/** Both main-video and specialised modes share one progress renderer. */
export function renderWorkflowSteps(nav,view){
  const availability=view.navigation?view.labels.map(label=>view.navigation.enabled(label)):null;const signature=JSON.stringify([view.id,view.title,view.labels,view.active,availability]);if(signature===nav.workflowSignature)return false;nav.workflowSignature=signature;
  nav.setAttribute('aria-label',view.title+' workflow progress');nav.dataset.workflow=view.id;
  const doc=nav.ownerDocument,list=doc.createElement('ol');
  view.labels.forEach((label,index)=>{const item=doc.createElement('li');item.title=label;item.className=index===view.active?'active':index<view.active?'complete':'';if(index===view.active)item.setAttribute('aria-current','step');
    const number=doc.createElement('span');number.className='zc-workflow-number';number.textContent=String(index+1);number.setAttribute('aria-hidden','true');
    const name=doc.createElement('span');name.className='zc-workflow-label';name.textContent=label;if(view.navigation){const button=doc.createElement('button');button.type='button';button.disabled=!view.navigation.enabled(label);button.setAttribute('aria-label',label);button.append(number,name);button.onclick=()=>{if(!button.disabled)void view.navigation.go(label);};item.append(button);}else item.append(number,name);list.append(item);});
  nav.replaceChildren(list);return true;
}

export class StudioWorkflowProgress{
  constructor(owner){
    this.owner=owner;this.root=owner.root;this.closed=false;const doc=this.root.ownerDocument;
    if(!doc.getElementById('zura-workflow-progress-styles')){const css=doc.createElement('link');css.id='zura-workflow-progress-styles';css.rel='stylesheet';css.href=new URL('./studio_workflow_progress.css',import.meta.url).href;doc.head.append(css);}
    this.nav=doc.createElement('nav');this.nav.className='zc-workflow-progress';this.nav.setAttribute('aria-label','Workflow progress');this.nav.hidden=true;
    const anchor=owner.outputSettings?.delivery?.element||this.root.querySelector('.gs-top');if(anchor)anchor.after(this.nav);else this.root.prepend(this.nav);
    const Observer=doc.defaultView?.MutationObserver||globalThis.MutationObserver;
    if(Observer){this.observer=new Observer(records=>{if(records.every(record=>this.nav===record.target||this.nav.contains(record.target)))return;this.schedule();});this.observer.observe(this.root,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','data-workspace','data-stage']});}
    this.sync();
  }
  schedule(){if(this.closed||this.queued)return;this.queued=true;queueMicrotask(()=>{this.queued=false;this.sync();});}
  sync(){
    if(this.closed)return;applyComposerPatterns(this.root);const view=workflowProgress(this.owner);this.nav.hidden=!view;if(!view)return;
    view.navigation=workflowNavigation(this.owner,view);renderWorkflowSteps(this.nav,view);
  }

  close(){disposeComposerPatterns(this.root);this.closed=true;this.observer?.disconnect();this.nav.remove();}
}

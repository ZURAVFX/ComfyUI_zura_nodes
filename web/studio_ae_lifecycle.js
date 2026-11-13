const ROOT='/zura/comfylink/v1/studio/sessions';

// Each AE workspace owns a proxy. The normal Studio keeps the original API,
// event listeners and storage, so ending AE mode cannot stop its work.
export function scopedStudioAPI(api,session){
  if(!session||session.error)return {api,end(){}};
  const origin=new URL(session.comfyOrigin);
  if(origin.protocol!=='http:'||origin.hostname!=='127.0.0.1'||!origin.port||origin.origin!==session.comfyOrigin)throw new Error('The AE link has no verified local ComfyUI origin');
  let closed=false;
  const ended=()=>Object.assign(new Error('This AE shot has ended'),{name:'AbortError',status:410});
  const fetchApi=async(path,options={})=>{
    if(closed)throw ended();
    if(typeof path!=='string'||!path.startsWith('/')||path.startsWith('//')||/[\\\x00-\x20\x7f]/.test(path))throw new Error('AE work must use this local ComfyUI server');
    const resolved=new URL(path,origin),actual=new URL(typeof api.apiURL==='function'?api.apiURL(path):path,origin);
    const allowed=/^\/(?:api\/)?(?:zura\/|genj\/|upload\/|prompt(?:$|\/)|queue(?:$|\/)|interrupt(?:$|\/)|history(?:$|\/)|object_info(?:$|\/)|view$|system_stats$|models(?:$|\/)|embeddings$)/;
    if(resolved.origin!==origin.origin||actual.origin!==origin.origin||!allowed.test(resolved.pathname)||!allowed.test(actual.pathname))throw new Error('AE work must use this local ComfyUI server');
    const headers=new Headers(options.headers||{});
    headers.set('X-ComfyLink-Studio-Id',session.id);
    headers.set('X-ComfyLink-Studio-Session',session.capability);
    const response=await api.fetchApi(path,{...options,headers,redirect:'error'});
    if(closed)throw ended();
    return response;
  };
  const proxy=new Proxy(api,{get(target,key){if(key==='fetchApi')return fetchApi;const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;}});
  return {api:proxy,end(){closed=true;},get closed(){return closed;}};
}

export function fenceAEWorkspace(studio){
  studio.aeScope?.end();studio.resetEpoch=(studio.resetEpoch||0)+1;
  const creative=studio.creative;
  const workspaces=new Set([creative,studio.hdrTool,creative?.frames,creative?.referencesVideo,creative?.director,creative?.paintout,creative?.watermark,creative?.ripple,creative?.alpha,creative?.outpaint,creative?.panorama,creative?.plate?.runner,...(creative?.rippleWorkspaces?.values?.()||[])]);
  for(const workspace of workspaces){
    if(!workspace)continue;
    workspace.aeSessionEnded=true;
    workspace.stopPolling?.();
    // Clear only active handles. Completed takes, layers and history stay in
    // the old session's isolated store and their output files stay on disk.
    workspace.job=null;workspace.pendingSubmission=null;workspace.submitAttempt=null;
    if(workspace.editor){workspace.editor.sequence=(workspace.editor.sequence||0)+1;workspace.editor.previewSequence=(workspace.editor.previewSequence||0)+1;}
  }
  for(const delivery of [creative?.outputSettings?.delivery,creative?.videoComposer?.ltxOutput?.delivery,creative?.frames?.hdrOutput,creative?.referencesVideo?.hdrOutput,creative?.outpaint?.hdrDelivery]){
    if(!delivery)continue;delivery.preparationCancelled=true;delivery.closed=true;delivery.close?.();
  }
}

export class StudioAELifecycle{
  constructor(bridge,{delay=1000,setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id)}={}){this.bridge=bridge;this.delay=delay;this.setTimer=setTimer;this.clearTimer=clearTimer;this.closed=false;this.timer=null;this.pending=false;}
  start(){if(!this.bridge.session.error)this.schedule();}
  schedule(){if(this.closed)return;this.timer=this.setTimer(()=>{this.timer=null;void this.poll();},this.delay);this.timer?.unref?.();}
  async poll(){
    if(this.closed||this.pending||this.bridge.closed)return;
    this.pending=true;const b=this.bridge;
    try{
      const response=await b.api.fetchApi(ROOT+'/'+encodeURIComponent(b.session.id)+'/status',{headers:{'X-ComfyLink-Studio-Session':b.session.capability}});
      if(this.closed||b.closed)return;
      if([401,403,404,410].includes(response.status)){await b.cancelAndLeave();return;}
      if(!response.ok)return;
      const value=await response.json();if(this.closed||b.closed)return;
      if(['cancelled','closed','expired','left'].includes(value.status)){await b.cancelAndLeave();return;}
      if(value.status==='sent')this.dispose();
    }catch{/* A temporary disconnect keeps the source and completed output. */}
    finally{this.pending=false;if(!this.closed&&!b.closed)this.schedule();}
  }
  dispose(){this.closed=true;if(this.timer!==null)this.clearTimer(this.timer);this.timer=null;}
}

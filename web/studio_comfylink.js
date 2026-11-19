import {sourceAEFrameContract,aeFramePolicy,aeFrameLabel,bindAEFrameWorkspace,clearAEFrameWorkspace} from './studio_ae_frame_contract.js';
import {aeStudioStorage} from './studio_storage.js';
import {activeStudioMode,studioModeAdapter,assertStudioSourceMode,studioProcessingInput,isNativeVideoSource} from './studio_mode_adapters.js';
import {AEFloatDisplay} from './studio_ae_display.js';
import {StudioSessionLease} from './studio_session_lease.js';
import {StudioAELifecycle,fenceAEWorkspace} from './studio_ae_lifecycle.js';
const ROOT='/zura/comfylink/v1/studio/sessions';
const ENDED_LINK='AE link ended. Send the shot again from After Effects, then choose your retained result.';
const RAW_RETURN_UNQUALIFIED='Returning this unconverted 8-bit copy to AE is not qualified yet. Your Studio result is retained.';
// A 4K work area can contain many GiB of lossless frames. ComfyUI's normal
// JSON request timeout can expire while the local source continues staging.
const SOURCE_REQUEST_TIMEOUT_MS=600000;
// The broker inspects the selected physical movie and constructs the verified
// schema-2 descriptor. Browser metadata and display settings are not authority.
export function aeReturnBody(result,nativeVideoReturn=false){
  if(!nativeVideoReturn||result?.kind!=='video')return result;
  const master=result.master,preview=result.preview;
  if(master?.type!=='output'||typeof master.filename!=='string'||typeof master.subfolder!=='string')return result;
  if(!/\.(mp4|mov)$/i.test(master.filename))return result;
  if(/(?:^|[_. -])(?:preview|proxy)(?:[_. -]|$)/i.test(master.filename)||
      preview?.filename===master.filename&&(preview?.subfolder||'')===(master.subfolder||''))return null;
  return {kind:'native_video',master:{filename:master.filename,subfolder:master.subfolder||'',type:'output'}};
}
// Consume before the first asynchronous operation, including malformed fragments.
export function consumeStudioFragment(location=globalThis.location,history=globalThis.history){
  if(!location?.hash)return null;
  const params=new URLSearchParams(location.hash.slice(1));if(!params.has('comfylink'))return null;
  const encoded=params.get('comfylink');params.delete('comfylink');
  history.replaceState(history.state,'',location.pathname+location.search+(params.size?'#'+params.toString():''));
  try{
    const value=JSON.parse(atob(encoded.replace(/-/g,'+').replace(/_/g,'/')));
    if(!/^http:\/\/127\.0\.0\.1:\d+\/studio-bridge\/[a-zA-Z0-9_-]+$/.test(value.broker)||!/^\w{64}$/.test(value.token)||!/^[0-9a-f]+$/i.test(value.token))throw Error();
    return {broker:value.broker,token:value.token};
  }catch{return {error:'The After Effects session link is invalid. Open Studio again from After Effects'};}
}
let launch=consumeStudioFragment();
export async function createStudioSession(api,credential){
  const failed=message=>({id:globalThis.crypto.randomUUID(),error:message});
  if(!credential||!/^http:\/\/127\.0\.0\.1:\d+\/studio-bridge\/[0-9a-f]{32}$/.test(credential.broker||'')||!/^[0-9a-f]{64}$/.test(credential.token||''))return failed('The After Effects session link is invalid. Open Studio again from After Effects');
  if(credential.error)return failed(credential.error);
  try{
    const response=await api.fetchApi(ROOT,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(credential)});
    credential=null;const body=await response.json();if(!response.ok)throw Error(body.error||'Could not connect to the After Effects session');
    return body;
  }catch(error){return failed(error.message||'Could not connect to the After Effects session');}
  finally{credential=null;}
}
export async function takeStudioLaunch(api){
  if(!launch)return null;const credential=launch;launch=null;
  if(credential.error)return {id:globalThis.crypto.randomUUID(),error:credential.error};
  return createStudioSession(api,credential);
}
export const studioLaunchStorage=session=>aeStudioStorage(session.id);
export class StudioAEBridge {
  constructor(studio,api,session,onLeave){
    this.studio=studio;this.api=api;this.session=session;this.onLeave=onLeave;this.closed=false;this.revision=0;this.loaded=new Map();
    const doc=studio.container.ownerDocument;this.root=doc.createElement('section');this.root.className='zc-ae-session';this.root.setAttribute('aria-label','After Effects session');
    this.root.innerHTML='<div class="zc-ae-context"><strong data-ae-label></strong><span data-ae-meta></span></div><span class="zc-ae-status" role="status" aria-live="polite"></span><div class="zc-ae-actions"><button type="button" data-ae-view>View source</button><button type="button" data-ae-source>Load AE source</button><button type="button" data-ae-recover hidden>Use saved result</button><button type="button" data-ae-send>Send to AE</button><button type="button" data-ae-leave>Leave AE mode</button></div>';
    studio.container.querySelector('.gs-top').after(this.root);studio.container.classList.add('zc-ae-mode');
    this.label=this.root.querySelector('[data-ae-label]');this.meta=this.root.querySelector('[data-ae-meta]');this.status=this.root.querySelector('[role=status]');this.send=this.root.querySelector('[data-ae-send]');this.sourceButton=this.root.querySelector('[data-ae-source]');
    this.recoveryButton=this.root.querySelector('[data-ae-recover]');this.recoveryCandidates=[];this.recoveryChecked=false;this.recoveryLoading=false;this.recovering=false;
    this.recoveryButton.onclick=()=>void this.useSavedResult();
    this.label.textContent='After Effects session · '+(session.context?.target?.label||session.label||'Disconnected');
    this.root.querySelector('[data-ae-leave]').onclick=()=>this.leave();this.sourceButton.onclick=()=>void this.loadSource(true);this.send.onclick=()=>void this.sendResult();
    this.display=new AEFloatDisplay(this);this.root.querySelector('[data-ae-view]').onclick=()=>void this.display.open();this.root.querySelector('[data-ae-view]').disabled=!!session.error;
    this.sourceButton.disabled=!!session.error;this.send.disabled=!!session.error;
    this.message(session.error||'Choose a Studio mode');this.updateMeta();
    this.lease=new StudioSessionLease(this);this.lease.start();
    this.lifecycle=new StudioAELifecycle(this);this.lifecycle.start();
    if(!session.error)void this.loadSource();
  }
  message(value){if(!this.closed){this.sourceErrorMode=null;this.status.textContent=value;}}
  nativeVideoReturnEnabled(){return this.session?.context?.capabilities?.nativeVideoReturn===true;}
  nativeStillReturnEnabled(){
    const context=this.session?.context,source=this.source,transfer=context?.transferPrecision;
    return context?.capabilities?.nativeStillReturn===true&&context?.range?.mode==='frame'&&
      ['sdr8','prores12'].includes(transfer)&&source?.frameCount===1&&source?.manifest?.frames?.length===1&&
      source?.processingInput?.conversion==='raw_numeric_to_sdr8'&&source?.sourceTransfer?.kind==='native_still'&&
      source.sourceTransfer.profile===(transfer==='sdr8'?'png8':'png16');
  }
  rawNumericSource(){return this.source?.processingInput?.conversion==='raw_numeric_to_sdr8';}
  rawReturnHeld(){return this.rawNumericSource()&&!this.nativeVideoReturnEnabled()&&!this.nativeStillReturnEnabled();}
  updateMeta(){
    const range=this.session.context?.range,precision=this.source?.precision,adapter=studioModeAdapter(activeStudioMode(this.studio.creative));
    const rangeMode=typeof range==='string'?range:range?.mode;
    const rangeLabel=range?.label||({frame:'Current frame',workarea:'Work area',layer:'Layer range'}[rangeMode]||'');
    const native=this.source&&studioProcessingInput(this.source,adapter?.id,this.studio.creative)===this.source&&this.source.processingInput;
    this.meta.textContent=[rangeLabel,aeFrameLabel(this.frameContract),precision?.sourceBitDepth?`${precision.sourceBitDepth}-bit source`:'',this.source?.processingInput?(native?'Native HDR processing':this.rawNumericSource()?'8-bit numeric copy':'8-bit SDR processing'):'',adapter?.compatibility,this.source?this.studio.creative.outputSettings?.exrLabel():null].filter(Boolean).join(' · ');
    this.send.title=this.rawReturnHeld()?RAW_RETURN_UNQUALIFIED:'';
  }
  async request(suffix,body){
    const capability=this.session?.capability;if(this.closed||!this.session?.id||!capability)throw Error(ENDED_LINK);
    const response=await this.api.fetchApi(ROOT+'/'+encodeURIComponent(this.session.id)+suffix,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-ComfyLink-Studio-Session':capability},...(body===undefined?{}:{body:JSON.stringify(body)}),...(['/source','/model-source'].includes(suffix)?{timeoutMs:SOURCE_REQUEST_TIMEOUT_MS}:{})});
    if(!response.ok&&[401,403,410].includes(response.status))throw Object.assign(Error(ENDED_LINK),{status:response.status});
    let data;
    try{data=await response.json();}catch{
      if(response.status===422)throw Error(suffix==='/prepare-graph'?'This edit cannot match the AE source range or dimensions. Load the AE source again and check this mode’s supported range':'This source or result cannot be transferred. Your original media and Studio result are retained');
      throw Error('ComfyUI could not complete this action. Check the connection and try again; your Studio result is retained');
    }
    if(!response.ok)throw Error(data.diagnostic||data.error||'This action could not complete. Your Studio result is retained');return data;
  }
  sourceClockKey(){const c=this.studio.creative,id=activeStudioMode(c),w=studioModeAdapter(id)?.resolveWorkspace(c);return id+':'+(id==='paintout'?(c.plate?.propagation?.()?'guide':'repair'):'source')+':'+(aeFramePolicy(id,typeof w?.config==='function'?w.config():w?.config||{},w||{}).nativeFPS||'source');}
  ownedResultReady(){const c=this.studio.creative,adapter=studioModeAdapter(activeStudioMode(c));return !!(this.source&&adapter&&this.loaded.get(adapter.id)===adapter.resolveWorkspace(c)&&adapter.getSelectedOutput(c));}
  pauseAutomaticSourceForReset(id){
    if(this.closed||!id)return;
    this.resetSources??=new Set();
    if(this.resetSources.has(id))return;
    this.resetSources.add(id);
    return ()=>this.resetSources.delete(id);
  }
  modeChanged(){this.updateMeta();this.updateRecoveryButton();if(this.closed)return;const c=this.studio.creative,id=activeStudioMode(c),adapter=studioModeAdapter(id),workspace=adapter?.resolveWorkspace(c);if(this.pending&&this.ownedResultReady()&&!this.sending&&!this.importPolling)this.send.disabled=this.rawReturnHeld();if(this.resetSources?.has(id)||id==='image'&&(c.rippleImage?.request||c.outpaintGuide?.request))return;if(!this.pending&&(this.sourceMode!==id||this.sourceWorkspace!==workspace||this.loadedClock!==this.sourceClockKey())){this.sourceMode=id;this.sourceWorkspace=workspace;void this.loadSource();if(!this.pending)void this.findSavedResults();}}
  async loadSource(force=false){
    const creative=this.studio.creative,id=activeStudioMode(creative),adapter=studioModeAdapter(id),workspace=adapter?.resolveWorkspace(creative);
    if(this.closed||this.pending||!adapter)return;
    if(this.resetSources?.has(id)){
      if(!force)return;
      this.resetSources.delete(id);
    }
    if(id==='paint_vfx'){if(!this.sending&&!this.importPolling)this.message('Paint VFX creates a new clip. Your AE source remains linked.');return;}
    // Borrowed frame edits own their uploaded still, not the parent AE video.
    if(id==='image'&&(creative.rippleImage?.request||creative.outpaintGuide?.request))return;
    if(!force&&this.source&&this.loadedClock===this.sourceClockKey()&&this.loaded.get(id)===workspace&&adapter.matchesInput(creative,this.source)){
      if(!isNativeVideoSource(this.source)&&(!this.rawNumericSource()||id==='image'&&this.nativeStillReturnEnabled())&&workspace.aeFrameMode!==id){
        if(adapter.isBusy(creative)){this.message('Finish the current operation before loading the AE source');return;}
        bindAEFrameWorkspace(creative,id,workspace,this.frameContract);
      }
      // Returning from an inline image editor briefly selects Image mode.
      // Clear only that departed mode's source error, never a transfer error.
      if(this.sourceErrorMode&&this.sourceErrorMode!==id&&!this.sending&&!this.importPending)this.message('AE source ready');
      return;
    }
    if(force&&id==='image'){this.recoveryChecked=false;this.recoveryCandidates=[];}
    const revision=++this.revision;this.pending=true;this.sourceButton.disabled=true;this.send.disabled=true;this.message('Preparing AE source…');
    const slowSource=setTimeout(()=>{if(!this.closed&&this.pending&&revision===this.revision)this.message('Loading AE source… Large shots can take several minutes');},15000);slowSource.unref?.();
    try{
      this.originalSource??=await this.request('/source',{});
      let source=this.originalSource;
      const clock=this.sourceClockKey(),rate=aeFramePolicy(id,typeof workspace?.config==='function'?workspace.config():workspace?.config||{},workspace||{}).nativeFPS;
      if(rate&&source.frameCount>1){this.message('Preparing '+rate+' fps working copy, keeping every source frame…');source=await this.request('/model-source',{frameRate:rate});}
      if(this.closed||revision!==this.revision)return;this.source=source;this.loadedClock=clock;this.frameContract=sourceAEFrameContract(source,this.session.id);
      const transfer=this.session.context?.transferPrecision;
      if(transfer)this.studio.creative.outputSettings?.delivery?.setAETransfer?.(transfer);
      this.studio.creative.outputSettings?.preferSourcePrecision(transfer==='float32'?32:transfer==='prores12'?12:transfer==='sdr8'?8:source.precision?.sourceBitDepth);this.updateMeta();
      if(id!==activeStudioMode(creative)||workspace!==adapter.resolveWorkspace(creative))return;
      if(id==='image'&&(creative.rippleImage?.request||creative.outpaintGuide?.request))return;
      if(adapter.isBusy(creative))throw Error('Finish the current operation before loading the AE source');
      assertStudioSourceMode(source,id,creative);
      if(!force&&this.loaded.has(id)&&adapter.matchesInput(creative,source)){
        // Relight can switch from the main video workspace to its edited-frame
        // workspace. Rebind the verified same source without discarding edits.
        if(isNativeVideoSource(source)||this.rawNumericSource()&&!(id==='image'&&this.nativeStillReturnEnabled()))clearAEFrameWorkspace(creative,workspace);else bindAEFrameWorkspace(creative,id,workspace,this.frameContract);
      }else await adapter.acceptInput(creative,source,{sessionId:this.session.id,bindRawStill:id==='image'&&this.nativeStillReturnEnabled(),isActive:()=>!this.closed&&revision===this.revision&&id===activeStudioMode(creative)&&workspace===adapter.resolveWorkspace(creative)});
      if(this.closed||revision!==this.revision||id!==activeStudioMode(creative)||workspace!==adapter.resolveWorkspace(creative))return;
      this.loaded.set(id,workspace);this.updateMeta();this.message(this.rawReturnHeld()?'AE source loaded. Return to AE for this numeric transfer is not qualified yet.':source.modelFrameRate?'AE source ready · '+source.modelFrameRate.numerator/source.modelFrameRate.denominator+' fps working copy':'AE source ready');
    }catch(error){
      if(!this.closed&&revision===this.revision&&id===activeStudioMode(creative)&&workspace===adapter.resolveWorkspace(creative)){
        this.message(error.message||'Could not load the AE source. You can retry or leave AE mode');this.sourceErrorMode=id;
      }
    }
    finally{clearTimeout(slowSource);if(!this.closed&&revision===this.revision){this.pending=false;this.sourceButton.disabled=false;this.send.disabled=this.rawReturnHeld();if(id!==activeStudioMode(creative)||workspace!==adapter.resolveWorkspace(creative))void this.loadSource();}}
    this.updateRecoveryButton();void this.findSavedResults();
  }
  updateRecoveryButton(){
    if(!this.recoveryButton)return;
    const c=this.studio.creative,image=activeStudioMode(c)==='image';
    this.recoveryButton.hidden=this.closed||!image||!!c.items?.[c.selectedImage]?.file||!this.recoveryCandidates?.length;
    this.recoveryButton.disabled=!!(this.pending||this.sending||this.recovering||studioModeAdapter('image').isBusy(c));
  }
  checkedSavedResult(value){
    const master=value?.master,frame=this.frameContract;
    if(!value||!frame||!/^([a-f0-9]{64})$/.test(value.id||'')||value.kind!=='image'||value.width!==frame.width||value.height!==frame.height||value.frameRate?.numerator!==frame.frameRate.numerator||value.frameRate?.denominator!==frame.frameRate.denominator||!/^[a-f0-9]{64}$/.test(value.sourceManifestSha256||'')||!/^[a-f0-9]{64}$/.test(value.imageSha256||'')||!master||master.type!=='output'||typeof master.filename!=='string'||!/\.png$/i.test(master.filename)||typeof master.subfolder!=='string')return null;
    if(master.filename.length>255||/[\\/:\0]/.test(master.filename)||/[\\:\0]/.test(master.subfolder)||master.subfolder.startsWith('/')||master.subfolder.split('/').some(part=>part==='.'||part==='..'))return null;
    return {...value,master:{filename:master.filename,subfolder:master.subfolder,type:'output'}};
  }
  async findSavedResults(){
    const c=this.studio.creative;
    if(!this.recoveryButton||this.closed||this.pending||this.recoveryLoading||this.recoveryChecked||this.loaded.get('image')!==c||activeStudioMode(c)!=='image'||this.frameContract?.frameCount!==1||c.items?.[c.selectedImage]?.file||studioModeAdapter('image').isBusy(c))return;
    const revision=this.revision,source=this.source;this.recoveryLoading=true;this.recoveryChecked=true;
    try{
      const data=await this.request('/retained-images',{});
      if(this.closed||revision!==this.revision||source!==this.source)return;
      this.recoveryCandidates=(Array.isArray(data.results)?data.results.slice(0,8):[]).map(item=>this.checkedSavedResult(item)).filter(Boolean);
      this.updateRecoveryButton();
    }catch{/* Recovery is optional. Source loading and normal generation stay available. */}
    finally{this.recoveryLoading=false;if(revision!==this.revision){this.recoveryChecked=false;void this.findSavedResults();}}
  }
  async useSavedResult(){
    const c=this.studio.creative,candidate=this.recoveryCandidates?.[0];
    if(!candidate||this.closed||this.pending||this.sending||this.recovering||activeStudioMode(c)!=='image'||c.items?.[c.selectedImage]?.file||studioModeAdapter('image').isBusy(c))return;
    const revision=this.revision,source=this.source;this.recovering=true;this.updateRecoveryButton();this.message('Checking the saved result…');
    try{
      const data=await this.request('/retained-images',{candidateId:candidate.id});
      if(this.closed||revision!==this.revision||source!==this.source||activeStudioMode(c)!=='image'||c.items?.[c.selectedImage]?.file||studioModeAdapter('image').isBusy(c))return;
      const result=this.checkedSavedResult(data.result);if(!result||result.id!==candidate.id||result.imageSha256!==candidate.imageSha256||result.sourceManifestSha256!==candidate.sourceManifestSha256)throw Error('No matching saved result is available. Your files are retained');
      c.items=Array.isArray(c.items)?c.items:[];
      let index=c.items.findIndex(item=>item.file?.filename===result.master.filename&&(item.file.subfolder||'')===result.master.subfolder&&item.file.type==='output');
      if(index<0){c.items.unshift({file:result.master,model:'Recovered result',prompt:'Saved image from the same AE frame',operation:'edit',shape:'auto',width:result.width,height:result.height,references:(c.references||[]).map(ref=>({...ref})),ae_frame_contract:this.frameContract,aeRecoveredResult:result.id});index=0;}
      if(c.activateImageResult)c.activateImageResult(index);else{c.selectedImage=index;c.save?.();c.renderGallery?.();c.render?.();}
      this.message('Saved result restored. Review it, then choose Send to AE');
    }catch(error){if(!this.closed)this.message(error.message||'The saved result could not be restored. Your files are retained');}
    finally{this.recovering=false;this.updateRecoveryButton();}
  }
  async prepareGraph(mode,graph,contract,intermediate=null){return this.request('/prepare-graph',{mode,graph,ae_frame_contract:contract,...(intermediate?{ae_intermediate_image:intermediate}:{})});}
  setSendActivity(stage=''){
    const busy=stage==='sending'||stage==='importing';
    this.send.toggleAttribute?.('data-busy',busy);
    this.send.setAttribute?.('aria-busy',String(busy));
    this.send.textContent=stage==='sending'?'Sending to AE…':stage==='importing'?'Importing in AE…':this.importPending?'Check transfer':'Send to AE';
  }
  async sendResult(){
    if(this.closed||this.pending&&!this.ownedResultReady()||this.sending||this.importPolling)return;
    if(this.rawReturnHeld())return this.message(RAW_RETURN_UNQUALIFIED);
    if(this.importPending){this.message('Checking the AE transfer…');this.watchImport();return;}
    const adapter=studioModeAdapter(activeStudioMode(this.studio.creative));
    if(!adapter)return this.message('Choose a Studio mode first');
    if(adapter.isBusy(this.studio.creative))return this.message('Finish the current operation before sending to After Effects');
    const transfer=this.session?.context?.transferPrecision,delivery=this.studio.creative.outputSettings?.delivery;
    if(transfer==='float32'&&(delivery?.preparing||delivery?.delivery?.busy))return this.message('HDR reconstruction is still running. Wait for the FLOAT EXR master before sending to AE.');
    const result=adapter.getSelectedOutput(this.studio.creative);
    if(!result){if(transfer==='float32'){void delivery?.convertCurrent?.();return this.message('A 32-bit AE transfer needs HDR reconstruction and a FLOAT EXR master. Check HDR output progress before sending.');}return this.message('Select a finished result in this mode first');}
    if(transfer==='float32'&&(result.kind!=='hdr_sequence'||result.colour?.encoding!=='acescg'||result.colour?.sceneLinear!==true)){
      void delivery?.convertCurrent?.();return this.message('The SDR edit is retained. Wait for its HDR reconstruction and FLOAT EXR master before sending to AE.');
    }
    const nativeStill=this.rawNumericSource()&&this.nativeStillReturnEnabled();
    const body=aeReturnBody(result,this.nativeVideoReturnEnabled()&&!nativeStill);
    if(!body)return this.message('Select a finished master rather than a preview');
    const sdrLayerEXR=/\.exr$/i.test(body.master?.filename||'')&&body.colour?.encoding==='srgb_display'&&body.colour?.sceneLinear===false;
    if(nativeStill&&(adapter.id!=='image'||body.kind!=='image'||!/(?:\.png|\.tiff?)$/i.test(body.master?.filename||'')&&!sdrLayerEXR))
      return this.message('Only a finished Image Edit master can return from this one-frame PNG transfer.');
    if(this.rawNumericSource()&&!nativeStill&&body.kind!=='native_video')return this.message(RAW_RETURN_UNQUALIFIED);
    this.sending=true;this.send.disabled=true;this.setSendActivity('sending');this.message('Sending the selected master to After Effects…');
    try{const reply=await this.request('/result',body);if(this.closed)return;this.message(reply.status==='sent'?'Sent to After Effects':(reply.diagnostic||'After Effects import pending. Your result is retained'));if(reply.status==='sent')this.lease?.dispose();if(reply.status==='import_pending'){this.importPending=true;this.watchImport();}}
    catch(error){this.message(error.message||'Could not send. Your Studio result is retained');}
    finally{this.sending=false;if(!this.closed){this.send.disabled=!!this.importPolling||this.rawReturnHeld();if(!this.importPolling)this.setSendActivity();}}
  }
  stopImportWatch(){clearTimeout(this.importTimer);this.importTimer=null;this.importPolling=false;this.importRevision=(this.importRevision||0)+1;}
  watchImport(){
    this.stopImportWatch();const revision=this.importRevision,started=Date.now();this.importPolling=true;this.send.disabled=true;this.setSendActivity('importing');
    const finish=(message,sent=false)=>{if(this.closed||revision!==this.importRevision)return;this.stopImportWatch();if(sent){this.importPending=false;this.lease?.dispose();}this.message(message);this.send.disabled=this.rawReturnHeld();this.setSendActivity();};
    const poll=async()=>{
      if(this.closed||revision!==this.importRevision)return;
      try{
        const status=await this.request('/status');if(this.closed||revision!==this.importRevision)return;
        if(status.status==='sent')return finish('Sent to After Effects',true);
        if(status.diagnostic)return finish(status.diagnostic);
        if(status.status!=='import_pending')return finish('AE has not confirmed this transfer. Your result is retained; check the transfer again.');
        if(Date.now()-started>=(this.transferPollTimeout??120000))return finish('AE import is still pending. Your result is retained; choose Check transfer to check again.');
        this.importTimer=setTimeout(poll,this.transferPollDelay??750);this.importTimer?.unref?.();
      }catch(error){finish(error.message||'Could not check the AE transfer. Your result is retained.');}
    };
    this.importTimer=setTimeout(poll,this.transferPollDelay??750);this.importTimer?.unref?.();
  }
  dispose(release=true){
    if(this.closed)return;fenceAEWorkspace(this.studio);this.stopImportWatch();this.lease?.dispose();this.lifecycle?.dispose();const {id,capability}=this.session;this.closed=true;++this.revision;this.display.close();delete this.session.capability;this.source=null;this.studio.creative?.outputSettings?.delivery?.endAETransfer?.();this.root.remove();this.studio.container.classList.remove('zc-ae-mode');
    // Local exit does not wait for a broker or network response.
    if(release&&capability)try{void Promise.resolve(this.api.fetchApi(ROOT+'/'+encodeURIComponent(id)+'/leave',{method:'POST',headers:{'Content-Type':'application/json','X-ComfyLink-Studio-Session':capability},body:'{}'})).catch(()=>{});}catch{}
  }
  cancelAndLeave(){
    if(this.cancelPromise)return this.cancelPromise;
    if(this.closed)return Promise.resolve();
    const {id,capability}=this.session;this.dispose(false);this.onLeave?.();
    this.cancelPromise=(async()=>{if(capability)try{await this.api.fetchApi(ROOT+'/'+encodeURIComponent(id)+'/cancel',{method:'POST',headers:{'Content-Type':'application/json','X-ComfyLink-Studio-Session':capability},body:'{}'});}catch{/* Host cancellation is also observed by the server status check. */}})();
    return this.cancelPromise;
  }
  leave(){void this.cancelAndLeave();}
}

import {sourceAEFrameContract,aeFrameLabel} from './studio_ae_frame_contract.js';
import {aeStudioStorage} from './studio_storage.js';
import {activeStudioMode,studioModeAdapter} from './studio_mode_adapters.js';
const ROOT='/zura/comfylink/v1/studio/sessions';
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
export async function takeStudioLaunch(api){
  if(!launch)return null;let credential=launch;launch=null;
  const failed=message=>({id:globalThis.crypto.randomUUID(),error:message});
  if(credential.error)return failed(credential.error);
  try{
    const response=await api.fetchApi(ROOT,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(credential)});
    credential=null;const body=await response.json();if(!response.ok)throw Error(body.error||'Could not connect to the After Effects session');
    return body;
  }catch(error){return failed(error.message||'Could not connect to the After Effects session');}
  finally{credential=null;}
}
export const studioLaunchStorage=session=>aeStudioStorage(session.id);
export class StudioAEBridge {
  constructor(studio,api,session,onLeave){
    this.studio=studio;this.api=api;this.session=session;this.onLeave=onLeave;this.closed=false;this.revision=0;this.loaded=new Set();
    const doc=studio.container.ownerDocument;this.root=doc.createElement('section');this.root.className='zc-ae-session';this.root.setAttribute('aria-label','After Effects session');
    this.root.innerHTML='<div class="zc-ae-context"><strong data-ae-label></strong><span data-ae-meta></span></div><span class="zc-ae-status" role="status" aria-live="polite"></span><div class="zc-ae-actions"><button type="button" data-ae-source>Load AE source</button><button type="button" data-ae-send>Send to AE</button><button type="button" data-ae-leave>Leave AE mode</button></div>';
    studio.container.querySelector('.gs-top').after(this.root);studio.container.classList.add('zc-ae-mode');
    this.label=this.root.querySelector('[data-ae-label]');this.meta=this.root.querySelector('[data-ae-meta]');this.status=this.root.querySelector('[role=status]');this.send=this.root.querySelector('[data-ae-send]');this.sourceButton=this.root.querySelector('[data-ae-source]');
    this.label.textContent='After Effects session · '+(session.context?.target?.label||session.label||'Disconnected');
    this.root.querySelector('[data-ae-leave]').onclick=()=>this.leave();this.sourceButton.onclick=()=>void this.loadSource(true);this.send.onclick=()=>void this.sendResult();
    this.sourceButton.disabled=!!session.error;this.send.disabled=!!session.error;
    this.message(session.error||'Choose a Studio mode');this.updateMeta();
    if(!session.error)void this.loadSource();
  }
  message(value){if(!this.closed)this.status.textContent=value;}
  updateMeta(){
    const range=this.session.context?.range,precision=this.source?.precision,adapter=studioModeAdapter(activeStudioMode(this.studio.creative));
    const rangeMode=typeof range==='string'?range:range?.mode;
    const rangeLabel=range?.label||({frame:'Current frame',workarea:'Work area',layer:'Layer range'}[rangeMode]||'');
    this.meta.textContent=[rangeLabel,aeFrameLabel(this.frameContract),precision?.sourceBitDepth?`${precision.sourceBitDepth}-bit source`:'',adapter?.compatibility,this.source?this.studio.creative.outputSettings?.exrLabel():null].filter(Boolean).join(' · ');
  }
  async request(suffix,body){
    const capability=this.session.capability;if(this.closed||!capability)throw Error('This After Effects session has ended');
    const response=await this.api.fetchApi(ROOT+'/'+encodeURIComponent(this.session.id)+suffix,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-ComfyLink-Studio-Session':capability},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const data=await response.json();if(!response.ok)throw Error(data.diagnostic||data.error||'This action could not complete. Your Studio result is retained');return data;
  }
  modeChanged(){this.updateMeta();if(!this.closed&&!this.pending)void this.loadSource();}
  async loadSource(force=false){
    const id=activeStudioMode(this.studio.creative),adapter=studioModeAdapter(id);if(this.closed||this.pending||!adapter||!force&&this.loaded.has(id))return;
    const revision=++this.revision;this.pending=true;this.sourceButton.disabled=true;this.send.disabled=true;this.message('Preparing AE source…');
    try{
      const source=this.source||await this.request('/source',{});if(this.closed||revision!==this.revision)return;this.source=source;this.frameContract=sourceAEFrameContract(source,this.session.id);this.studio.creative.outputSettings?.preferSourcePrecision(source.precision?.sourceBitDepth);this.updateMeta();
      if(id!==activeStudioMode(this.studio.creative))return;
      if(source.precision?.sourceBitDepth>8&&id!=='hdr')throw Error('Floating-point source retained. Choose Convert to HDR for a supported native input');
      await adapter.acceptInput(this.studio.creative,source,{sessionId:this.session.id});if(this.closed||revision!==this.revision)return;
      this.loaded.add(id);this.updateMeta();this.message('AE source ready');
    }catch(error){this.message(error.message||'Could not load the AE source. You can retry or leave AE mode');}
    finally{if(!this.closed&&revision===this.revision){this.pending=false;this.sourceButton.disabled=false;this.send.disabled=false;if(id!==activeStudioMode(this.studio.creative))void this.loadSource();}}
  }
  async prepareGraph(mode,graph,contract){return this.request('/prepare-graph',{mode,graph,ae_frame_contract:contract});}
  async sendResult(){
    if(this.closed||this.pending||this.sending)return;const adapter=studioModeAdapter(activeStudioMode(this.studio.creative));
    if(!adapter)return this.message('Choose a Studio mode first');
    if(adapter.isBusy(this.studio.creative))return this.message('Finish the current operation before sending to After Effects');
    const result=adapter.getSelectedOutput(this.studio.creative);if(!result)return this.message('Select a finished result in this mode first');
    this.sending=true;this.send.disabled=true;this.message('Sending the selected master to After Effects…');
    try{const reply=await this.request('/result',result);this.message(reply.status==='sent'?'Sent to After Effects':(reply.diagnostic||'After Effects import pending. Your result is retained'));}
    catch(error){this.message(error.message||'Could not send. Your Studio result is retained');}
    finally{this.sending=false;if(!this.closed)this.send.disabled=false;}
  }
  dispose(){
    if(this.closed)return;const {id,capability}=this.session;this.closed=true;++this.revision;delete this.session.capability;this.source=null;this.root.remove();this.studio.container.classList.remove('zc-ae-mode');
    // Local exit does not wait for a broker or network response.
    if(capability)try{void Promise.resolve(this.api.fetchApi(ROOT+'/'+encodeURIComponent(id)+'/leave',{method:'POST',headers:{'Content-Type':'application/json','X-ComfyLink-Studio-Session':capability},body:'{}'})).catch(()=>{});}catch{}
  }
  leave(){if(this.closed)return;this.dispose();this.onLeave?.();}
}

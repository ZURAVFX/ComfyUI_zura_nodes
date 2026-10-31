import {LTXHDRDelivery} from './studio_ltx_delivery.js';
import {installOwnedExecuting} from './studio_progress.js';
import {nativePerformanceOpening,validateNativePerformance,nativePerformanceReadiness,mainNativeLTXTake} from './studio_native_hdr_performance.js';

const STORE='zura-main-ltx-deliveries';
const FORMATS=['sdr','hlg_video','hlg_and_exr','acescg_exr'];
const terminal=state=>['complete','failed','cancelled','unknown'].includes(state);
const view=(api,file)=>api.apiURL('/view?'+new URLSearchParams(file));
export function mainLTXTake(project,result){
  if(!project?.id||result?.stage!=='restyle'||result.native_hdr||!FORMATS.includes(result.hdr_output)||result.hdr_output==='sdr')return null;
  const raster=result.output_raster,file=result.asset;
  if(!file?.filename||file.type!=='output'||!raster||!Number.isInteger(raster.frames)||raster.frames<1||![raster.width,raster.height].every(v=>Number.isInteger(v)&&v>0))return null;
  return {projectId:project.id,resultKey:`${project.id}:${result.action_id||file.subfolder+'/'+file.filename}`,
    file,config:{engine:'ltx',hdrOutput:result.hdr_output,frames:raster.frames,width:raster.width,height:raster.height,seed:result.seed??42}};
}

/** HDR delivery stays beside the main LTX generation. Its SDR master is never replaced. */
export class MainLTXDelivery {
  constructor(studio,api,tools){
    this.studio=studio;this.api=api;this.records={};this.submitting=false;this.closed=false;
    try{this.records=JSON.parse(localStorage.getItem(STORE))||{};}catch{}
    this.control=document.createElement('label');this.control.className='zc-tool zc-model-control';this.control.hidden=true;
    this.control.title='HDR adds an LTX conversion pass after generation. Your SDR master is retained.';
    this.control.innerHTML='<span class="zc-sr-only">LTX output format</span><select aria-label="LTX output format"><option value="sdr">SDR</option><option value="hlg_video">HDR · HLG video</option><option value="hlg_and_exr">HDR · HLG + EXR</option><option value="acescg_exr">HDR · EXR</option></select>';
    tools.append(this.control);this.select=this.control.querySelector('select');
    this.sourceFrame=document.createElement('button');this.sourceFrame.type='button';this.sourceFrame.className='zc-tool';this.sourceFrame.hidden=true;this.sourceFrame.textContent='Use HDR source frame';this.sourceFrame.title='Use the selected source frame as native HDR appearance. Review it before animation.';tools.append(this.sourceFrame);
    this.sourceFrame.onclick=()=>void this.useSourceFrame();
    this.select.onchange=()=>{this.setup=null;studio.config.ltx_output=this.select.value;studio.render();};
    this.progress=document.createElement('section');this.progress.className='gs-working gs-ltx-delivery';this.progress.hidden=true;this.progress.setAttribute('aria-label','LTX HDR delivery');
    this.progress.innerHTML='<div class="gs-progress-heading"><strong>Creating HDR delivery</strong><button type="button" class="gs-stop">Cancel HDR</button></div><progress max="100" aria-label="HDR pass progress"></progress><div class="gs-progress-caption"><span role="status" aria-live="polite"></span></div>';
    studio.$('canvas').append(this.progress);this.bar=this.progress.querySelector('progress');this.detail=this.progress.querySelector('[role=status]');
    this.progress.querySelector('button').onclick=()=>this.delivery.cancel();
    this.downloads=document.createElement('div');this.downloads.className='zc-prompt-tools';this.downloads.hidden=true;this.downloads.setAttribute('aria-label','HDR delivery files');
    studio.container.querySelector('.gs-composer').append(this.downloads);
    this.delivery=new LTXHDRDelivery(api,{key:'zura-main-ltx-hdr',onSetup:info=>{this.setup=info;if(!info.ready&&studio.$('model-downloads'))studio.$('model-downloads').open=true;},onUpdate:job=>this.update(job),onComplete:take=>{
      this.records[take.resultKey]={state:'complete',take};this.save();
    }});
    this.onProgress=event=>this.sample(event.detail);
    api.addEventListener?.('progress',this.onProgress);
    this.disposeExecuting=installOwnedExecuting(api,event=>{
      const p=event.detail;if(!p?.node||p.prompt_id!==this.delivery.activePrompt||!this.delivery.busy)return;
      this.node=p.node;this.clock=null;this.bar.removeAttribute('value');
      this.detail.textContent=this.section()+this.nodeLabel(p.node);
    });
  }
  save(){try{const entries=Object.entries(this.records).slice(-24);this.records=Object.fromEntries(entries);localStorage.setItem(STORE,JSON.stringify(this.records));}catch{}}
  async useSourceFrame(){
    const s=this.studio,id=s.project?.id,epoch=s.resetEpoch;
    if(!s.modelStatus?.native_hdr_performance||s.config.engine!=='local'||s.config.workflow_mode!=='motion'||s.config.edit_area!=='scene'||this.sourcePreparing||this.delivery.busy||s.busy||s.project?.phase==='working')return;
    if(!s.project?.approval){
      if(s.project&&s.project.look_mode!=='source_hdr')s.invalidateLook();
      Object.assign(s.config,{finished_frame_position:'first',finished_frame_number:1});
      s.hdrSourceLook=true;s.lookMode='build';s.syncForm();s.render();
      s.message('HDR source frame selected. Review the source before using its frame.');return;
    }
    this.sourcePreparing=true;s.render();
    try{
      const response=await this.api.fetchApi('/zura/studio/projects/'+encodeURIComponent(id)+'/hdr-source-opening',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      const project=await response.json();if(!response.ok)throw new Error(project.error||'Could not read the HDR source frame.');
      if(s.project?.id!==id||s.resetEpoch!==epoch)return;
      s.project=project;Object.assign(s.config,project.config||{finished_frame_position:'first',finished_frame_number:1});s.readyAsset=project.starting_asset;s.lookMode='ready';s.hdrSourceLook=false;s.promptStage=null;s.syncForm();s.render();
      s.message('Review the HDR source frame before generating. The preview is SDR.');
    }catch(error){s.message(error.message||'Could not read the HDR source frame.',true);}
    finally{this.sourcePreparing=false;s.render();}
  }
  async beforeAction(action){
    if(this.delivery.busy||this.submitting||this.sourcePreparing)throw new Error('Wait for HDR preparation or delivery before starting another shot.');
    const c=this.studio.config;
    const hdrVideo=this.studio.source?.native_hdr_video||this.studio.project?.source?.native_hdr_video;
    if(hdrVideo&&['animate','restyle','background'].includes(action)&&!nativePerformanceOpening(this.studio))
      throw new Error('Choose a finished HDR EXR or use the HDR source frame before generating.');
    if(nativePerformanceOpening(this.studio)&&['animate','restyle','background'].includes(action)){
      validateNativePerformance(c);
      this.setup=await nativePerformanceReadiness(this.api,c.ltx_output);
      if(!this.setup.enabled)throw new Error('Native HDR performance is not enabled on this server.');
      if(!this.setup.ready)throw new Error('Native HDR setup is incomplete: '+[...(this.setup.files||[]).filter(f=>!f.ready).map(f=>f.filename),...(this.setup.missingNodes||[])].join(', '));
      return;
    }
    if(c.engine!=='local'||c.workflow_mode!=='motion'||!['animate','restyle','background'].includes(action)||!c.ltx_output||c.ltx_output==='sdr')return;
    const source=this.studio.source,scale=Number(c.resolution)/Math.max(source?.width||0,source?.height||0);
    if(!Number.isFinite(scale)||scale<=0)throw new Error('Load the source video before choosing HDR output.');
    await this.delivery.preflight({engine:'ltx',hdrOutput:c.ltx_output,
      width:Math.max(2,2*Math.round(source.width*scale/2)),height:Math.max(2,2*Math.round(source.height*scale/2))});
  }
  candidate(){const p=this.studio.project;return mainLTXTake(p,p?.results?.at(-1));}
  async start(take){
    if(this.closed||this.submitting||this.delivery.busy)return;
    this.submitting=true;this.activeTake=take;this.records[take.resultKey]={state:'preparing',take};this.save();this.studio.render();
    try{await this.delivery.preflight(take.config);if(this.closed){this.records[take.resultKey]={state:'waiting',take};this.save();return;}await this.delivery.start(take);}
    catch(error){this.records[take.resultKey]={state:'failed',take,error:error.message};this.save();this.studio.message(error.message,true);}
    finally{this.submitting=false;this.studio.render();}
  }
  section(){return this.job?.total>0?`Section ${Math.min((this.job.completed||0)+1,this.job.total)} of ${this.job.total} · `:'';}
  nodeLabel(node){return ({hdr_source:'Loading SDR master',hdr_model:'Loading LTX HDR model',hdr_vae:'Preparing HDR VAE',hdr_sample:'Converting to HDR',sample1:'HDR pass 1 of 2',sample2:'HDR pass 2 of 2',hdr_decode:'Decoding HDR frames',zura_hdr_archive:'Saving EXRs',zura_hdr_save_video:'Saving HLG video'})[node]||'Preparing HDR delivery';}
  sample(p){
    if(!this.delivery.busy||p?.prompt_id!==this.delivery.activePrompt||!(p.max>0)||!Number.isFinite(p.value))return;
    if(p.node&&p.node!==this.node){this.node=p.node;this.clock=null;}
    this.bar.value=Math.max(0,Math.min(100,100*p.value/p.max));
    const sampling=['hdr_sample','sample1','sample2'].includes(this.node);let eta='';
    if(sampling){if(!this.clock)this.clock={value:p.value,time:Date.now()};else if(p.value>this.clock.value){const seconds=(Date.now()-this.clock.time)/1000/(p.value-this.clock.value)*(p.max-p.value);if(seconds>=0&&seconds<86400)eta=` · about ${Math.ceil(seconds)}s left in this pass`;}}
    this.detail.textContent=`${this.section()}${this.nodeLabel(this.node)} · ${sampling?'step':'progress'} ${p.value} of ${p.max}${eta}`;
  }
  update(job){
    const same=this.job?.state===job.state&&this.job?.active_prompt_id===job.active_prompt_id;
    this.job=job;const take=this.delivery.take;
    if(take&&terminal(job.state)&&job.state!=='complete'){this.records[take.resultKey]={state:job.state,take,error:job.error||'HDR delivery stopped. Your SDR master is retained.'};this.save();}
    if(!same||!this.node){this.node=null;this.clock=null;this.bar.removeAttribute('value');this.detail.textContent=this.section()+(({reconnecting:'Reconnecting to your saved HDR job',cancelling:'Waiting for HDR cancellation','cancel-error':job.error||'Cancellation could not be confirmed. Try Cancel HDR again.',saving:'Saving HDR files',complete:'HDR delivery complete',failed:job.error||'HDR delivery failed',cancelled:'HDR delivery cancelled',unknown:job.error||'HDR job confirmation is unavailable.'})[job.state]||'Preparing HDR delivery');}
    this.studio.render();
  }
  result(project){const native=mainNativeLTXTake(project,project?.results?.at(-1));if(native)return native;const take=mainLTXTake(project,project?.results?.at(-1));return take&&this.records[take.resultKey]?.state==='complete'?this.records[take.resultKey].take:null;}
  sync(stage){
    const s=this.studio,enabled=s.config.engine==='local'&&s.config.workflow_mode==='motion';
    const hdrSource=!!(s.source?.native_hdr_video||s.project?.source?.native_hdr_video);
    this.sourceFrame.hidden=!enabled||s.config.edit_area!=='scene'||!s.modelStatus?.native_hdr_performance||!hdrSource||stage==='video';
    this.sourceFrame.textContent=s.hdrSourceLook?'HDR source frame selected':'Use HDR source frame';
    this.sourceFrame.setAttribute('aria-pressed',String(!!s.hdrSourceLook));
    this.sourceFrame.disabled=s.busy||s.project?.phase==='working'||this.delivery.busy||this.sourcePreparing;
    const native=!!nativePerformanceOpening(s),nativeTake=mainNativeLTXTake(s.project,s.project?.results?.at(-1));
    this.control.title=native?'Native HDR from your HDR appearance reference. The on-screen preview is SDR. Experimental workflow.':'HDR adds an LTX conversion pass after generation. Your SDR master is retained.';
    this.select.querySelector('option[value="sdr"]').disabled=native;
    this.control.hidden=!enabled||stage!=='video';this.select.value=enabled?(s.config.ltx_output||'sdr'):'sdr';this.select.disabled=s.busy||s.project?.phase==='working'||this.delivery.busy||this.submitting;
    if(enabled&&stage==='video'&&FORMATS.includes(s.config.ltx_output)&&s.config.ltx_output!=='sdr'&&this.setup&&s.modelDownloads){
      const base=s.modelDownloads.context||{},files=new Map([...(base.files||[]).filter(file=>!native||file.filename!=='ltx-2.5-video-vae-conv-bf16.safetensors'),...(this.setup.files||[])].map(file=>[`${file.folder}/${file.filename}`,file]));
      s.modelDownloads.setContext({route:'ltx_performance_hdr',files:[...files.values()],missingNodes:[...new Set([...(base.missingNodes||[]),...(this.setup.missingNodes||[])])]});
    }
    const take=this.candidate(),record=nativeTake?{state:'complete',take:nativeTake}:take&&this.records[take.resultKey];
    const pending=(this.delivery.take?.projectId===s.project?.id&&this.delivery.busy)||(this.activeTake?.projectId===s.project?.id&&this.submitting);
    this.progress.hidden=!pending;this.progress.querySelector('button').disabled=this.delivery.client.cancelPending;
    if(pending){s.$('primary').disabled=true;s.$('primary').textContent='Creating HDR delivery';s.$('action-note').textContent='Your SDR master is ready. HDR conversion is an additional LTX pass.';}
    this.downloads.replaceChildren();this.downloads.hidden=!record||!terminal(record.state);
    if(record?.state==='complete'){
      for(const file of record.take.hdrFiles||[]){const link=document.createElement('a');link.className='zc-tool';link.href=view(this.api,file);link.download=file.filename;link.textContent=file.filename.endsWith('.zip')?'Download EXRs':'Download HDR video';this.downloads.append(link);}
      const note=document.createElement('span');note.className='gs-note';note.textContent=nativeTake?'The on-screen preview is SDR. Download the native HDR master or EXRs to view the full range.':'The on-screen preview is SDR. Your original SDR master remains in Takes.';this.downloads.append(note);
    }else if(record&&terminal(record.state)){
      const message=document.createElement('span');message.className='gs-note';message.textContent=record.error||'HDR delivery stopped. Your SDR master is retained.';this.downloads.append(message);
      if(record.state!=='unknown'){const retry=document.createElement('button');retry.type='button';retry.className='zc-tool';retry.textContent='Retry HDR delivery';retry.disabled=this.delivery.busy||this.submitting;retry.onclick=()=>void this.start(record.take);this.downloads.append(retry);}
    }
    if(!this.closed&&s.project?.phase==='done'&&take&&(!record||record.state==='waiting')&&!this.delivery.busy&&!this.submitting)void this.start(take);
  }
  open(){
    this.closed=false;
    // A missing recovery identity is not permission to submit an uncertain job
    // again. Preserve its SDR take and ask the artist to check Comfy's queue.
    if(!this.submitting&&!this.delivery.take)for(const record of Object.values(this.records))if(record.state==='preparing'){
      record.state='unknown';record.error='HDR job confirmation is missing. Check ComfyUI’s queue before starting another conversion. Your SDR master is retained.';
    }
    this.save();this.delivery.resume();
  }
  close(){this.closed=true;this.delivery.close();}
}

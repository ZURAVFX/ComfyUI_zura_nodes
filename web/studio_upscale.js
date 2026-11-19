import {openStudioGraph} from './studio_graph_view.js';
import {workspaceStorage} from './studio_storage.js';
import {ClipTrimmer} from './studio_trim.js';
import {ShotComparison} from './studio_compare.js';
import {StudioModelDownloads} from './studio_model_download.js';
import {playbackFile} from './studio_delivery_formats.js';
import {captureResultExports,installResultExportStyles} from './studio_result_exports.js';
import {submitOwnedGraph,recoverOwnedSubmission,cancelOwnedJob} from './studio_owned_jobs.js';
import {durationLabel,installOwnedExecuting} from './studio_progress.js';
import {buildUpscaleGraph,DEFAULT_UPSCALE_MODEL,UPSCALE_MODELS,upscaleAvailability} from './studio_upscale_recipes.js';

const KEY='zura-upscale-workspace-v1';
const HDR=new Set(['acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3']);

export class UpscaleWorkspace{
  constructor(owner){
    this.owner=owner;
    this.independentAsset=true;
    this.api=owner.api;
    this.storage=workspaceStorage(owner);
    let saved={};
    try{saved=JSON.parse(this.storage.getItem(KEY))||{};}catch{}
    this.source=saved.source||null;
    this.range=saved.range||null;
    this.detail=saved.detail??1;
    this.model=Object.hasOwn(UPSCALE_MODELS,saved.model)?saved.model:DEFAULT_UPSCALE_MODEL;
    this.result=saved.result||null;
    this.job=saved.job||null;
    this.pendingSubmission=saved.pendingSubmission||null;
    if(this.job?.cancelPending)this.job.cancelRetryAvailable=true;
    this.disposed=false;
    const doc=owner.root.ownerDocument;
    if(!doc.getElementById('zura-alpha-styles')){
      const style=doc.createElement('link');
      style.id='zura-alpha-styles';
      style.rel='stylesheet';
      style.href=new URL('./studio_alpha.css',import.meta.url).href;
      doc.head.append(style);
    }
    const sheet=doc.createElement('link');
    sheet.rel='stylesheet';
    sheet.href=new URL('./studio_upscale.css',import.meta.url).href;
    doc.head.append(sheet);
    this.style=sheet;
    this.page=doc.createElement('section');
    this.page.className='zalpha-page zup-page';
    this.page.hidden=true;
    this.page.innerHTML=`<header class="zalpha-heading"><h2>Upscale video</h2><div class="zup-view-actions" aria-label="Preview tools"><button type="button" data-view hidden>View source</button><button type="button" data-compare hidden>Compare</button></div></header>
      <div class="zalpha-viewer" data-viewer><video data-video controls playsinline preload="metadata" hidden></video><div data-wipe-host hidden></div><div class="zalpha-empty" data-empty><strong>Double the resolution of a video</strong><button type="button" class="gs-primary" data-add>Add video</button></div></div>
      <section class="zalpha-progress" data-progress hidden role="status"><div><strong data-progress-title>Preparing</strong><button type="button" data-cancel>Cancel run</button></div><progress data-bar aria-label="Upscale progress"></progress><span data-progress-detail></span></section>
      <div class="zalpha-composer zc-prompt-card">
        <div class="zalpha-attachments"><button type="button" class="zc-attachment" data-source hidden>Replace video</button><input type="file" data-file accept=".mp4,.mov,.mkv,.webm,video/*" hidden><span data-source-meta></span></div>
        <details data-trim class="zalpha-trim" hidden><summary><span>Trim clip</span><span data-range></span></summary><div data-trimmer></div><div class="zalpha-trim-fields"><label>In frame <input type="number" min="1" step="1" data-in></label><label>Out frame <input type="number" min="1" step="1" data-out></label><button type="button" data-full>Use full clip</button></div></details>
        <div class="zc-prompt-bottom"><div class="zc-prompt-tools"><label class="zup-model">Model <select data-model aria-label="Upscale model"></select></label><span class="zc-tool" data-resolution>2×</span><label class="zup-detail" data-detail-control>Detail <input data-detail type="range" min="0" max="1" step="0.05" aria-label="Detail enhancement"><output data-detail-value></output></label><details class="zc-tool-popup gs-model-help" data-models hidden></details></div><div class="zalpha-actions"><button type="button" class="gs-primary" data-generate>Upscale video</button></div></div>
        <p class="zalpha-status" data-status role="status"></p>
        <div class="zalpha-exports zc-result-exports" data-exports hidden><a data-download download>Save ProRes master</a><a data-preview-download download hidden>Save MP4 preview</a></div>
      </div>`;
    owner.root.append(this.page);
    this.video=this.$('video');
    installResultExportStyles(doc);
    this.comparison=new ShotComparison(this.$('wipe-host'));
    this.comparison.onClose=()=>this.preview('result');
    this.modelDownloads=new StudioModelDownloads(this.$('models'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.checkModels());
    this.modelDownloads.inlineSetup=true;
    this.modelDownloads.mountQuick(this.page.querySelector('.zalpha-composer'));
    this.trimmer=new ClipTrimmer(this.$('trimmer'),{
      onSeek:time=>{if(this.view!=='source')this.preview('source');this.video.currentTime=time;},
      onCommit:range=>{
        const fps=this.source.fps;
        const first=Math.min(this.source.frames,Math.round(range.start*fps)+1);
        const last=Math.min(this.source.frames,Math.round((range.start+range.duration)*fps));
        this.setFrames(first,Math.max(first,last));
      },
    });
    this.$('add').onclick=this.$('source').onclick=()=>this.$('file').click();
    this.$('file').onchange=event=>{
      const file=event.target.files?.[0];
      event.target.value='';
      if(file)void this.upload(file);
    };
    this.$('in').onchange=this.$('out').onchange=()=>this.setFrames(Number(this.$('in').value),Number(this.$('out').value));
    this.$('full').onclick=()=>{this.range=null;this.save();this.render();};
    const select=this.$('model');
    for(const [id,model] of Object.entries(UPSCALE_MODELS)){
      const option=doc.createElement('option');
      option.value=id;
      option.textContent=model.label;
      select.append(option);
    }
    select.value=this.model;
    select.onchange=()=>{
      if(this.busy()||!Object.hasOwn(UPSCALE_MODELS,select.value))return;
      this.model=select.value;
      this.message('');
      this.updateAvailability();
      this.save();
      this.render();
      void this.checkModels();
    };
    this.$('detail').value=String(this.detail);
    this.$('detail').oninput=()=>{
      this.detail=Number(this.$('detail').value);
      this.$('detail-value').textContent=Math.round(this.detail*100)+'%';
    };
    this.$('detail').onchange=()=>this.save();
    this.$('view').onclick=()=>this.preview(this.view==='source'?'result':'source');
    this.$('compare').onclick=()=>{
      this.video.pause();
      this.video.hidden=true;
      this.comparison.show(this.sourceURL(),this.fileURL(playbackFile(this.result.file)),this.result.config.start,{resultLabel:'Upscaled 2×'});
    };
    this.$('generate').onclick=()=>this.generate();
    this.$('cancel').onclick=()=>this.cancel();
    this.video.ontimeupdate=()=>{if(this.view==='source')this.trimmer.setPlayhead(this.video.currentTime);};
    this.video.onerror=()=>this.message('This preview could not play in the browser.');
    this.disposeExecuting=installOwnedExecuting(this.api,event=>{
      if(!this.job||event.detail?.prompt_id!==this.job.id||this.job.cancelPending)return;
      this.setProgress(this.job.stages?.[event.detail.node]||'Upscaling video',durationLabel((Date.now()-this.job.started)/1000)+' elapsed');
    });
    this.view=this.result?'result':'source';
    this.render();
  }

  $(name){return this.page.querySelector(`[data-${name}]`);}
  fetch(path,body){return this.owner.fetch(path,body);}
  fileURL(file){return this.api.apiURL('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type}));}
  sourceURL(){
    if(!this.source)return '';
    if(this.playbackURL)return this.playbackURL;
    const parts=this.source.file.split('/');
    return this.fileURL({filename:parts.pop(),subfolder:parts.join('/'),type:'input'});
  }
  async refreshSourcePreview(){
    const source=this.source;
    if(!source?.id||this.playbackURL||this.refreshingPreview)return;
    this.refreshingPreview=true;
    try{
      const info=await this.fetch('/zura/studio/assets/'+encodeURIComponent(source.id)+'/ripple',{});
      if(this.disposed||this.source!==source)return;
      if(info.playback_url){
        this.playbackURL=this.api.apiURL(info.playback_url);
        if(this.view==='source')this.preview('source');
      }
    }catch(error){if(!this.disposed&&this.source===source)this.message(error.message);}
    finally{this.refreshingPreview=false;}
  }
  setFrames(first,last){
    if(!this.source||this.busy())return;
    if(!Number.isInteger(first)||!Number.isInteger(last)||first<1||last<first||last>this.source.frames){
      this.message('Choose a frame range within the source clip. Out frame is inclusive.');
      this.render();
      return;
    }
    const fps=this.source.fps;
    this.range=first===1&&last===this.source.frames?null:{start:(first-1)/fps,duration:(last-first+1)/fps};
    this.message('');
    this.save();
    this.preview('source');
    this.video.currentTime=(first-1)/fps;
  }
  busy(){return !!(this.uploadController||this.submitting||this.job||this.pendingSubmission);}
  config(){return {file:this.source?.file,start:this.range?.start||0,duration:this.range?.duration||0,detail:this.detail,model:this.model};}
  save(){
    try{
      const {source,range,detail,model,result,job,pendingSubmission}=this;
      this.storage.setItem(KEY,JSON.stringify({source,range,detail,model,result,job,pendingSubmission}));
      return true;
    }catch{return false;}
  }
  message(text){this.$('status').textContent=text||'';}
  setProgress(title,detail){
    this.$('progress').hidden=false;
    this.$('progress-title').textContent=title;
    this.$('progress-detail').textContent=detail;
    this.$('bar').removeAttribute('value');
  }
  preview(view){
    this.comparison.hide();
    this.view=view==='result'&&this.result?'result':'source';
    const url=this.view==='result'?this.fileURL(playbackFile(this.result.file)):this.sourceURL();
    this.video.hidden=!url;
    this.$('empty').hidden=!!url;
    if(url&&this.video.getAttribute('src')!==url)this.video.src=url;
    if(!url){this.video.pause();this.video.removeAttribute('src');}
    this.render();
  }
  render(){
    const busy=this.busy(),source=this.source;
    const needsSetup=this.availability?.ready===false;
    this.$('add').disabled=this.$('source').disabled=this.$('detail').disabled=this.$('full').disabled=this.$('model').disabled=busy;
    this.$('source').hidden=!source;
    this.$('source-meta').textContent=source?`${source.name} · ${source.width} × ${source.height} · ${Number(source.fps.toFixed(3))} fps`:'';
    this.$('resolution').textContent=source?`2× · ${source.width*2} × ${source.height*2}`:'2×';
    this.$('detail-control').hidden=this.model!==DEFAULT_UPSCALE_MODEL;
    this.$('detail-value').textContent=Math.round(this.detail*100)+'%';
    this.$('range').textContent=this.range?`${this.range.duration.toFixed(2)}s selected`:'Full clip';
    this.$('trim').hidden=!source;
    if(source){
      this.$('in').max=this.$('out').max=String(source.frames);
      this.$('in').value=String(this.range?Math.round(this.range.start*source.fps)+1:1);
      this.$('out').value=String(this.range?Math.round((this.range.start+this.range.duration)*source.fps):source.frames);
    }
    this.$('in').disabled=this.$('out').disabled=busy;
    this.trimmer.update(source&&{...source,url:this.sourceURL()},this.range?{...this.range,length_mode:'custom',workflow_mode:'relight'}:{length_mode:'original',workflow_mode:'relight'},{disabled:busy});
    this.$('generate').disabled=busy||(!source&&!needsSetup);
    this.$('generate').textContent=busy?'Working…':needsSetup?`Set up ${UPSCALE_MODELS[this.model].label}`:'Upscale video';
    this.$('view').hidden=this.$('compare').hidden=!source||!this.result;
    this.$('view').textContent=this.view==='source'?'View result':'View source';
    this.$('exports').hidden=!this.result;
    if(this.result){
      this.$('download').href=this.fileURL(this.result.file);
      this.$('preview-download').hidden=!this.result.file.preview;
      if(this.result.file.preview)this.$('preview-download').href=this.fileURL(this.result.file.preview);
    }
    if(!busy)this.$('progress').hidden=true;
    this.owner.workflowProgress?.schedule();
  }

  async upload(file){
    if(this.busy()||this.disposed)return;
    if(!/\.(mp4|mov|mkv|webm)$/i.test(file.name)){this.message('Choose an MP4, MOV, MKV or WebM video.');return;}
    if(file.size>2*1024**3){this.message('Use a source video smaller than 2 GB.');return;}
    const controller=new AbortController();
    this.uploadController=controller;
    this.message('');
    this.setProgress('Loading source','Uploading video to ComfyUI');
    this.render();
    try{
      const body=new FormData();
      body.append('file',file,file.name);
      const response=await this.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body,signal:controller.signal,timeoutMs:null});
      const asset=await response.json();
      if(!response.ok||!asset.id||!asset.file)throw Error(asset.error||'Could not upload this video.');
      const info=await this.fetch('/zura/studio/assets/'+encodeURIComponent(asset.id)+'/ripple',{});
      if(this.disposed||controller.signal.aborted)return;
      if(HDR.has(info.resolved_colour))throw Error('Choose an SDR source for Upscale.');
      const fps=Number(info.fps),duration=Number(asset.duration);
      if(![fps,duration,info.width,info.height].every(value=>Number.isFinite(value)&&value>0)||!Number.isInteger(info.frames)||info.frames<1)throw Error('Could not read this clip’s dimensions or timing.');
      this.source={id:asset.id,file:asset.file,name:asset.name||file.name,width:info.width,height:info.height,frames:info.frames,fps,duration};
      this.playbackURL=info.playback_url?this.api.apiURL(info.playback_url):null;
      this.range=null;
      this.result=null;
      this.save();
      this.preview('source');
    }catch(error){if(!this.disposed)this.message(controller.signal.aborted?'Upload cancelled.':error.message);}
    finally{this.uploadController=null;if(!this.disposed)this.render();}
  }

  updateAvailability(){
    this.availability=this.modelInfo?upscaleAvailability(this.modelInfo,this.model):null;
    this.modelDownloads.setMissingContext(this.model,this.availability?.missing,`${UPSCALE_MODELS[this.model].label} · 2×`);
  }
  async checkModels(){
    try{
      this.modelInfo=await this.fetch('/object_info');
      if(this.disposed)return null;
      this.updateAvailability();
      this.render();
      return this.availability;
    }catch(error){
      if(!this.disposed)this.message('Could not check upscale setup. '+error.message);
      return null;
    }
  }

  async generate(){
    if(this.busy())return;
    if(this.availability?.ready===false){await this.modelDownloads.checkSetup();return;}
    if(!this.source)return;
    this.submitting=true;
    this.$('trim').open=false;
    this.message('');
    const label=UPSCALE_MODELS[this.model].label;
    this.setProgress('Checking setup',`Preparing ${label}`);
    this.render();
    try{
      const availability=await this.checkModels();
      if(this.disposed)return;
      if(!availability?.ready)throw Error(`Check ${label} setup before upscaling.`);
      const config=this.config();
      const submission=submitOwnedGraph(this,buildUpscaleGraph(config,this.modelInfo),config,'auto',{zura_upscale:true});
      await submission;
    }catch(error){if(!this.disposed)this.message(error.message);}
    finally{this.submitting=false;if(!this.disposed)this.render();}
  }
  startPolling(){
    if(this.timer||this.disposed)return;
    this.timer=setInterval(()=>void this.poll(),1500);
    void this.poll();
  }
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  async poll(){
    if(this.polling||this.disposed)return;
    if(this.pendingSubmission&&!this.job){
      const pending=this.pendingSubmission;
      await recoverOwnedSubmission(this);
      if(pending.cancelRequested&&this.job)await cancelOwnedJob(this);
      return;
    }
    const job=this.job;
    if(!job)return;
    this.polling=true;
    try{
      const history=await this.fetch('/history/'+encodeURIComponent(job.id));
      if(this.disposed||this.job!==job)return;
      const entry=history[job.id];
      if(!entry?.status?.completed&&!['error','success'].includes(entry?.status?.status_str))return;
      const failure=entry.status.messages?.find(([type])=>type==='execution_error')?.[1];
      const interrupted=entry.status.messages?.some(([type])=>type==='execution_interrupted');
      const file=entry.outputs?.save?.images?.find(file=>file.type==='output'&&/\.mov$/i.test(file.filename));
      this.job=null;
      this.stopPolling();
      if(entry.status.status_str==='success'&&file&&!failure&&!interrupted){
        this.result={file,config:job.config,exports:captureResultExports(entry.outputs.save)};
        this.message('');
        this.preview('result');
      }else this.message(interrupted?'Upscale cancelled.':failure?.exception_message||'The run ended without an upscaled video.');
      this.save();
      this.render();
    }catch(error){if(!this.disposed)this.message('Waiting to reconnect to the running upscale. '+error.message);}
    finally{this.polling=false;}
  }
  async cancel(){
    if(this.uploadController){this.uploadController.abort();return;}
    if(this.pendingSubmission&&!this.job){
      this.pendingSubmission.cancelRequested=true;
      this.save();
      this.setProgress('Cancelling','Checking whether the run started');
      return;
    }
    if(this.job)await cancelOwnedJob(this);
  }
  async graph(){
    const availability=await this.checkModels();
    const label=UPSCALE_MODELS[this.model].label;
    if(!availability?.ready)throw Error(`Complete ${label} setup before opening the graph.`);
    await openStudioGraph(this.owner.studio,buildUpscaleGraph(this.config(),this.modelInfo),`Upscale video · ${label}`,'upscale');
  }
  onCancel(){return this.cancel();}
  open(){
    this.modelDownloads.resume();
    this.preview(this.view);
    void this.refreshSourcePreview();
    void this.checkModels();
    if(this.job||this.pendingSubmission){
      this.setProgress('Reconnecting','Checking the ComfyUI queue');
      this.startPolling();
    }
  }
  reset(){
    if(this.busy())return false;
    this.source=this.result=this.range=this.playbackURL=null;
    this.save();
    this.message('');
    this.preview('source');
    return true;
  }
  close(){
    this.disposed=true;
    this.uploadController?.abort();
    this.stopPolling();
    this.modelDownloads.dispose();
    this.disposeExecuting?.();
    this.trimmer.close();
    this.comparison.hide();
    this.video.pause();
    this.style.remove();
  }
}

import {workspaceStorage} from './studio_storage.js';
import {ClipTrimmer} from './studio_trim.js';
import {StudioModelDownloads} from './studio_model_download.js';
import {submitOwnedGraph,recoverOwnedSubmission,cancelOwnedJob} from './studio_owned_jobs.js';
import {installOwnedExecuting,durationLabel} from './studio_progress.js';
import {alphaProcessingSize,alphaVideoAvailability,alphaVideoValidation,alphaVideoOutput,buildAlphaVideoGraph} from './studio_alpha_recipes.js';

const KEY='zura-alpha-workspace-v1';
const initial=()=>({processingScale:.5,startFrame:0,frameCount:49,view:'source',seed:42});
const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
const rate=fps=>String(Number(Number(fps||0).toFixed(3)));
const savedState=storage=>{try{return JSON.parse(storage.getItem(KEY))||{};}catch{return {};}};

/** Automatic video matting, with source footage kept visible throughout a run. */
export class AlphaWorkspace {
  constructor(owner){this.storage=workspaceStorage(owner);
    this.owner=owner;this.api=owner.api;this.root=owner.root;this.app=owner.app;this.closed=true;this.disposed=false;
    const saved=savedState(this.storage);this.state={...initial(),...saved};
    if(![1,.75,.5,.25].includes(Number(this.state.processingScale)))this.state.processingScale=.5;
    this.source=null;this.sourceInfo=null;this.result=saved.result||null;this.job=saved.job||null;this.pendingSubmission=saved.pendingSubmission||null;
    if(this.job?.cancelPending)this.job.cancelRetryAvailable=true;
    this.revision=0;this.modelRevision=0;this.modelInfo=null;this.availability=null;this.submitting=false;this.picking=false;this.polling=false;
    const doc=this.root.ownerDocument;
    if(!doc.getElementById('zura-alpha-styles')){const link=doc.createElement('link');link.id='zura-alpha-styles';link.rel='stylesheet';link.href=new URL('./studio_alpha.css',import.meta.url).href;doc.head.append(link);}
    this.page=doc.createElement('section');this.page.className='zalpha-page';this.page.hidden=true;
    this.page.innerHTML=`<header class="zalpha-heading"><h2>Extract alpha</h2><label class="zc-tool zalpha-view"><span>View</span><select data-view aria-label="Alpha preview"><option value="source">Source</option><option value="matte">Matte</option><option value="preview">Cutout</option></select></label></header>
      <div class="zalpha-viewer" aria-label="Alpha video preview"><video data-video controls playsinline preload="metadata" hidden></video><div data-still role="img" aria-label="Selected source frame" hidden></div><div data-empty class="zalpha-empty"><strong>Remove the background from a video</strong><span>Add a clip. Alpha Gen finds the foreground automatically.</span></div></div>
      <section data-progress class="zalpha-progress" role="status" aria-live="polite" hidden><div><strong data-progress-title>Preparing</strong><button type="button" data-cancel>Cancel run</button></div><progress data-bar max="100" aria-label="Alpha generation progress"></progress><span data-progress-detail></span></section>
      <details data-trim class="zalpha-trim" hidden><summary><span>Trim clip</span><span data-selection-range></span></summary><div class="zalpha-trim-panel" aria-label="Trim source clip"><div data-trimmer></div><div class="zalpha-trim-fields"><label>First frame<input type="number" data-start min="0" step="1" aria-label="First source frame"/></label><label>Frames<input type="number" data-count min="1" max="145" step="1" aria-label="Selected frame count"/></label><button type="button" data-full-clip>Use full clip</button></div></div></details>
      <div class="zalpha-composer zc-prompt-card"><div class="zalpha-attachments"><button type="button" class="zc-attachment" data-source>Add video</button><input type="file" data-source-file accept="video/*,.mov,.mkv,.mxf,.avi" hidden/><span data-source-meta></span><button type="button" data-clear-source aria-label="Remove source video" title="Remove source video" hidden>×</button></div>
        <p class="zalpha-description">Automatic foreground matte. No prompt or painted mask needed.</p>
        <div class="zc-prompt-bottom"><div class="zc-prompt-tools"><span class="zc-tool zalpha-model">LTX 2.5 · Alpha Gen</span><label class="zc-tool zalpha-scale"><span class="zc-sr-only">Processing resolution</span><select data-scale aria-label="Alpha processing resolution"><option value="1">Full resolution</option><option value="0.75">75% resolution</option><option value="0.5">50% resolution</option><option value="0.25">25% resolution</option></select></label><span data-size class="zalpha-size"></span><details data-model-downloads class="zc-tool-popup gs-model-help" hidden></details></div><div class="zalpha-actions"><button type="button" class="gs-primary" data-generate>Generate alpha</button></div></div>
        <p data-status class="zalpha-status" role="status" aria-live="polite"></p>
        <div data-exports class="zalpha-exports" hidden><a data-save-alpha download>Save transparent MOV</a><a data-save-matte download>Save matte</a><a data-save-sequence download hidden>Save matte frames</a><span>Original size and frame rate</span></div>
      </div>`;
    this.root.append(this.page);this.video=this.$('video');this.still=this.$('still');
    this.modelDownloads=new StudioModelDownloads(this.$('model-downloads'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.checkModels());this.modelDownloads.mountQuick(this.page.querySelector('.zalpha-composer'));this.modelDownloads.renderQuick();
    this.trimmer=new ClipTrimmer(this.$('trimmer'),{onCommit:range=>this.setTrim(range),onSeek:seconds=>this.seek(seconds)});
    this.$('source').onclick=()=>this.$('source-file').click();
    this.$('source-file').onchange=event=>{const file=event.target.files?.[0];event.target.value='';if(file)void this.uploadSource(file);};
    this.$('clear-source').onclick=()=>this.reset();
    this.$('scale').value=String(this.state.processingScale);this.$('scale').onchange=()=>{if(this.busy())return;this.state.processingScale=Number(this.$('scale').value);this.message('');this.save();this.render();};
    this.$('view').onchange=()=>this.showView(this.$('view').value);
    this.$('start').onchange=this.$('count').onchange=()=>this.setFrameRange();
    this.$('full-clip').onclick=()=>this.fullClip();this.$('generate').onclick=()=>void this.generate();this.$('cancel').onclick=()=>void this.cancel();
    this.$('trim').onkeydown=event=>{if(event.key==='Escape'){this.$('trim').open=false;this.$('trim').querySelector('summary').focus();event.stopPropagation();}};
    this.video.addEventListener('loadedmetadata',()=>{if(this.state.view==='source')this.seek(this.state.startFrame/this.fps());});
    this.video.addEventListener('timeupdate',()=>{if(this.state.view==='source')this.trimmer.setPlayhead(this.video.currentTime);});
    this.video.addEventListener('error',()=>{if(!this.source||this.state.view!=='source')return;this.video.hidden=true;const url=this.url('/zura/paintout/frame-preview?'+new URLSearchParams({file:this.source.path,frame:this.state.startFrame,space:this.source.resolved_colour||'rec709_oetf',size:1280}));this.still.style.backgroundImage=`url(${JSON.stringify(url)})`;this.still.hidden=false;});
    this.disposeExecuting=installOwnedExecuting(this.api,event=>{if(event.detail?.prompt_id!==this.job?.id||this.job.cancelPending)return;this.job.currentNode=event.detail.node;this.setProgress({title:this.job.stages?.[event.detail.node]||'Processing alpha',detail:this.elapsed()});});
    this.onProgress=event=>{const p=event.detail;if(!this.job||p?.prompt_id!==this.job.id||this.job.cancelPending)return;this.job.currentNode=p.node;this.setProgress({title:`${this.job.stages?.[p.node]||'Generating alpha'}${p.max>0?` · Step ${p.value} of ${p.max}`:''}`,detail:this.elapsed(),value:p.max>0?p.value/p.max*100:null});};
    this.api.addEventListener?.('progress',this.onProgress);this.render();
  }
  $(name){return this.page.querySelector(`[data-${name}]`);}
  fetch(path,body){return this.owner.fetch(path,body);}
  url(path){return this.api.apiURL(path);}
  fileURL(file){return this.url('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'}));}
  fps(){return Number(this.source?.fps)||24;}
  busy(){return !!(this.job||this.pendingSubmission||this.submitting||this.picking);}
  elapsed(){return `${durationLabel((Date.now()-(this.job?.started||Date.now()))/1000)} elapsed`;}
  message(text){this.messageText=text||'';this.$('status').textContent=this.messageText;this.$('status').hidden=!this.messageText;}
  save(){try{const sourceImport=this.source?.processingView?.originalAssetId?{path:this.source.path,processingView:this.source.processingView,studioAssetId:this.source.studioAssetId}:this.source?null:this.state.sourceImport||null;this.state.sourceImport=sourceImport;this.storage.setItem(KEY,JSON.stringify({...this.state,sourcePath:this.source?.path||this.state.sourcePath||'',sourceName:this.source?.name||this.state.sourceName||'',sourceImport,job:this.job,pendingSubmission:this.pendingSubmission,result:this.result}));return true;}catch{return false;}}
  config(){const view=this.source?.processingView;return {source:this.source?.path||'',sourceWidth:Number(this.source?.width)||0,sourceHeight:Number(this.source?.height)||0,sourceFrames:this.source?.frames,startFrame:this.state.startFrame,frameCount:this.state.frameCount,processingScale:Number(this.state.processingScale),sequenceFps:this.fps(),seed:this.state.seed??42,...(view?.originalAssetId&&this.source?.studioAssetId?{originalSource:{asset_id:view.originalAssetId,proxy_id:this.source.studioAssetId}}:{})};}
  releaseLocalPreview(){if(this.localPreview){URL.revokeObjectURL?.(this.localPreview);this.localPreview=null;}}
  async uploadSource(file){
    if(this.busy()||this.disposed)return;const revision=++this.revision;this.picking=true;this.uploadController=new AbortController();
    if(typeof URL.createObjectURL==='function'){try{this.releaseLocalPreview();this.localPreview=URL.createObjectURL(file);this.video.src=this.localPreview;this.video.hidden=false;this.still.hidden=true;this.$('empty').hidden=true;this.video.load();}catch{/* Server playback remains available after upload. */}}
    this.message('');this.setProgress({title:'Loading video',detail:'Preparing the source footage'});this.render();
    try{
      const body=new FormData();body.append('file',file,file.name);const response=await this.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body,signal:this.uploadController.signal,timeoutMs:null});
      const asset=await response.json();if(!response.ok)throw Error(asset.error||'Could not upload this video.');if(!asset.id)throw Error('The uploaded video could not be identified.');
      if(this.disposed||revision!==this.revision)return;
      const info=await this.fetch('/zura/studio/assets/'+encodeURIComponent(asset.id)+'/ripple',{});if(this.disposed||revision!==this.revision)return;
      this.setSource({...info,name:asset.name||file.name||info.name});
    }catch(error){if(!this.disposed&&revision===this.revision){this.releaseLocalPreview();this.showView(this.state.view);this.message(error.name==='AbortError'?'Video upload cancelled.':error.message||'Could not open this video.');}}
    finally{if(!this.disposed&&revision===this.revision){this.picking=false;this.uploadController=null;this.clearProgress();this.render();}}
  }
  setSource(info){
    if(this.job||this.pendingSubmission||this.submitting)throw Error('Wait for the current alpha run to finish or cancel it before replacing the source.');
    if(!info?.path||info.kind!=='video'||!Number.isInteger(info.frames)||info.frames<1||![info.width,info.height,info.fps].every(v=>Number.isFinite(Number(v))&&Number(v)>0))throw Error('Choose a video with valid dimensions and frame rate.');
    ++this.revision;this.source=this.sourceInfo=info;this.state={...initial(),processingScale:this.state.processingScale,sourcePath:info.path,sourceName:info.name||'',frameCount:Math.min(49,info.frames)};
    this.result=null;this.picking=false;this.uploadController=null;this.releaseLocalPreview();this.clearProgress();this.message('');this.showView('source');this.save();this.render();
  }
  setSourceAsset(info){this.setSource(info);}
  async restoreSource(){
    const path=this.state.sourcePath;if(!path||this.source?.path===path||this.restoring)return;
    const revision=this.revision;this.restoring=true;
    try{const imported=this.state.sourceImport,info=imported?.studioAssetId?(await this.fetch('/zura/studio/media-import/describe',{asset_id:imported.studioAssetId})).mediaInfo:await this.fetch('/zura/paintout/info?'+new URLSearchParams({file:path}));if(this.disposed||revision!==this.revision||this.state.sourcePath!==path)return;if(!info?.path||info.kind!=='video'||!Number.isInteger(info.frames)||info.frames<1||![info.width,info.height,info.fps].every(v=>Number.isFinite(Number(v))&&Number(v)>0))throw Error('The saved source is no longer available. Replace the video to continue.');this.source=this.sourceInfo=info;this.showView(this.state.view);this.render();}
    catch(error){if(!this.disposed&&revision===this.revision)this.message(error.message||'Could not restore this video.');}
    finally{this.restoring=false;}
  }
  showView(view='source'){
    if(!['source','matte','preview'].includes(view))view='source';if(view!=='source'&&!this.result?.[view])view='source';
    this.state.view=view;this.$('view').value=view;const path=view==='source'?(this.source?.media_url||this.source?.thumbnail_url):this.fileURL(this.result[view]);
    this.video.pause();this.still.hidden=true;
    if(path){const url=view==='source'?this.url(path):path;if(this.video.getAttribute('src')!==url){this.video.src=url;this.video.load();}this.video.hidden=false;this.$('empty').hidden=true;}else{this.video.removeAttribute('src');this.video.hidden=true;this.$('empty').hidden=false;}
    this.save();this.renderExports();
  }
  seek(seconds){if(this.state.view!=='source')this.showView('source');if(!this.source)return;try{this.video.currentTime=clamp(Number(seconds)||0,0,Math.max(0,(this.source.frames-1)/this.fps()));}catch{}this.trimmer.setPlayhead(seconds);}
  setTrim(range){if(!this.source||this.busy())return;const start=clamp(Math.round(Number(range.start)*this.fps()),0,this.source.frames-1),end=clamp(Math.round((Number(range.start)+Number(range.duration))*this.fps()),start+1,this.source.frames);this.state.startFrame=start;this.state.frameCount=end-start;this.message('');this.seek(start/this.fps());this.save();this.render();}
  setFrameRange(){if(!this.source||this.busy())return;const start=Number(this.$('start').value),count=Number(this.$('count').value);if(!Number.isInteger(start)||start<0||!Number.isInteger(count)||count<1||start+count>this.source.frames){this.message('Choose whole frame numbers within the source clip.');this.render();return;}this.state.startFrame=start;this.state.frameCount=count;this.message('');this.seek(start/this.fps());this.save();this.render();}
  fullClip(){if(!this.source||this.busy())return;if(this.source.frames>145){this.message('Trim the clip to 145 frames or fewer.');return;}this.state.startFrame=0;this.state.frameCount=this.source.frames;this.seek(0);this.save();this.render();}
  async checkModels(){
    const revision=++this.modelRevision;
    try{const info=await this.fetch('/object_info');if(this.disposed||revision!==this.modelRevision)return null;this.modelInfo=info;this.availability=alphaVideoAvailability(info);this.modelDownloads.setMissingContext('ltx_alpha',this.availability.missing);this.$('model-downloads').hidden=this.availability.ready;this.render();return this.availability;}
    catch(error){if(!this.disposed&&revision===this.modelRevision){this.availability=null;this.message('Could not check Alpha Gen models. Check the ComfyUI connection and try again.');this.render();}return null;}
  }
  async generate(){
    if(this.busy())return;const config=this.config(),error=alphaVideoValidation(config);if(error){this.message(error);return;}
    this.submitting=true;this.$('trim').open=false;this.message('');this.setProgress({title:'Checking models',detail:'Preparing Alpha Gen'});this.render();
    try{const availability=await this.checkModels();if(this.disposed)return;if(!availability?.ready){this.$('model-downloads').hidden=false;this.$('model-downloads').open=true;void this.modelDownloads.load();throw Error('Install the models needed for Alpha Gen, then try again.');}
      const graph=buildAlphaVideoGraph(config,this.modelInfo);await submitOwnedGraph(this,graph,config,'auto',{zura_alpha:true});
    }catch(error){if(!this.disposed)this.message(error.message||'Could not start Alpha Gen.');}
    finally{this.submitting=false;if(!this.job&&!this.pendingSubmission)this.clearProgress();this.render();}
  }
  startPolling(){if(this.disposed||this.timer)return;this.timer=setInterval(()=>void this.poll(),1500);void this.poll();}
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  async poll(){
    if(this.disposed||this.polling)return;
    if(this.pendingSubmission&&!this.job){const pending=this.pendingSubmission;await recoverOwnedSubmission(this);if(pending.cancelRequested&&this.job)await cancelOwnedJob(this);return;}
    const job=this.job;if(!job)return;this.polling=true;
    try{
      const history=await this.fetch('/history/'+encodeURIComponent(job.id));if(this.disposed||this.job!==job)return;const entry=history?.[job.id];
      if(entry?.status?.completed||entry?.status?.status_str==='error'){
        const failure=entry.status.messages?.find(m=>m[0]==='execution_error')?.[1],cancelled=entry.status.messages?.some(m=>m[0]==='execution_interrupted'),result=!failure&&!cancelled&&entry.status.status_str==='success'?alphaVideoOutput(entry,job.config):null;
        this.job=null;this.stopPolling();this.clearProgress();
        if(result){this.result=result;this.showView('preview');this.message('Alpha ready. Save the transparent MOV or the matte.');}
        else this.message(failure?.exception_message||(cancelled||job.cancelPending?'Run cancelled. Earlier results remain saved.':'The run finished without all alpha exports. Check the ComfyUI output folder.'));
        this.save();this.render();return;
      }
      const queue=await this.fetch('/queue');if(this.disposed||this.job!==job)return;const running=queue.queue_running?.some(item=>item[1]===job.id),position=queue.queue_pending?.findIndex(item=>item[1]===job.id)??-1;
      if(!running&&position<0){job.missingSince??=Date.now();if(Date.now()-job.missingSince<6000)return;const again=await this.fetch('/history/'+encodeURIComponent(job.id));if(this.disposed||this.job!==job||again?.[job.id])return;this.job=null;this.stopPolling();this.clearProgress();this.message('This run left the queue. Check its output folder before starting again.');this.save();this.render();return;}
      delete job.missingSince;
      if(job.cancelPending)this.setProgress({title:'Cancelling…',detail:'Waiting for ComfyUI to stop this run.'});
      else if(!running)this.setProgress({title:'Queued',detail:`Queue position ${position+1} · Waiting for ComfyUI`});
      else this.$('progress-detail').textContent=this.elapsed();
    }catch{if(!this.disposed&&this.job===job)this.message('Connection interrupted. Reconnecting to your saved alpha run…');}
    finally{this.polling=false;}
  }
  async cancel(){
    if(this.picking){this.uploadController?.abort();++this.revision;this.picking=false;this.uploadController=null;this.releaseLocalPreview();this.showView(this.state.view);this.clearProgress();this.message('Video upload cancelled.');this.render();return;}
    if(this.pendingSubmission&&!this.job){this.pendingSubmission.cancelRequested=true;this.save();await this.poll();return;}
    await cancelOwnedJob(this);
  }
  setProgress({title='Generating alpha',detail='',value=null}={}){this.$('progress').hidden=false;this.$('progress-title').textContent=title;this.$('progress-detail').textContent=detail;if(Number.isFinite(value))this.$('bar').value=clamp(value,0,100);else this.$('bar').removeAttribute('value');}
  clearProgress(){this.$('progress').hidden=true;this.$('bar').removeAttribute('value');}
  renderExports(){
    const result=this.result;this.$('exports').hidden=!result?.alpha;
    for(const [key,role] of [['save-alpha','alpha'],['save-matte','matte'],['save-sequence','sequence']]){const a=this.$(key),file=result?.[role];a.hidden=!file;if(file){a.href=this.fileURL(file);a.download=file.filename;}else a.removeAttribute('href');}
  }
  render(){
    const has=!!this.source,busy=this.busy(),error=has?alphaVideoValidation(this.config()):'';
    this.$('source').textContent=has?'Replace video':'Add video';this.$('source').disabled=busy;this.$('clear-source').hidden=!has;this.$('clear-source').disabled=!!(this.job||this.pendingSubmission||this.submitting);
    this.$('source-meta').textContent=has?`${this.source.name||this.state.sourceName||this.source.path.split(/[\\/]/).pop()} · ${this.source.width} × ${this.source.height} · ${rate(this.fps())} fps`:'';
    this.$('scale').disabled=busy;this.$('scale').value=String(this.state.processingScale);this.$('trim').hidden=!has;
    this.$('start').value=String(this.state.startFrame);this.$('count').value=String(this.state.frameCount);this.$('start').max=String(Math.max(0,(this.source?.frames||1)-1));this.$('count').max=String(Math.min(145,this.source?.frames||145));
    for(const key of ['start','count','full-clip'])this.$(key).disabled=busy||!has;
    this.$('full-clip').hidden=!has||this.source.frames>145;this.$('selection-range').textContent=has?`${this.state.frameCount} frames · ${(this.state.frameCount/this.fps()).toFixed(2)}s · 145 frames max`:'';
    this.$('generate').disabled=busy||!has||!!error;this.$('generate').textContent=busy?'Generating…':'Generate alpha';this.$('cancel').disabled=!this.picking&&!this.pendingSubmission&&!this.job||!!(this.job?.cancelPending&&!this.job.cancelRetryAvailable);this.$('cancel').textContent=this.job?.cancelRetryAvailable?'Retry cancellation':'Cancel run';
    for(const option of this.$('view').querySelectorAll('option'))option.disabled=option.value!=='source'&&!this.result?.[option.value];
    this.$('view').value=this.state.view;this.$('view').disabled=!has&&!this.result;
    if(has){const size=alphaProcessingSize(this.source.width,this.source.height,this.state.processingScale);this.$('size').textContent=`${size.width} × ${size.height} processing · ${this.source.width} × ${this.source.height} output`;this.trimmer.update({url:this.url(this.source.media_url||''),duration:this.source.frames/this.fps(),fps:this.fps()},{workflow_mode:'relight',length_mode:'custom',start:this.state.startFrame/this.fps(),duration:this.state.frameCount/this.fps()},{disabled:busy});}else{this.$('size').textContent='';this.trimmer.update(null,{});}
    if(error&&!this.messageText){this.$('status').textContent=error;this.$('status').hidden=false;}else{this.$('status').textContent=this.messageText||'';this.$('status').hidden=!this.messageText;}
    if(this.pendingSubmission){this.$('progress').hidden=false;this.$('progress-title').textContent='Checking your run';this.$('progress-detail').textContent='Reconnecting without submitting again…';}
    if(this.job?.cancelPending){this.$('progress').hidden=false;this.$('progress-title').textContent='Cancelling…';this.$('progress-detail').textContent='Waiting for ComfyUI to stop this run.';}
    this.renderExports();
  }
  reset(){
    if(this.job||this.pendingSubmission||this.submitting)return false;
    ++this.revision;this.uploadController?.abort();this.uploadController=null;this.picking=false;this.source=this.sourceInfo=null;this.result=null;this.state=initial();this.releaseLocalPreview();this.$('trim').open=false;this.trimmer.close();this.video.pause();this.video.removeAttribute('src');this.video.load();this.video.hidden=true;this.still.hidden=true;this.$('empty').hidden=false;this.clearProgress();this.message('');this.save();this.render();return true;
  }
  async graph(){try{const graph=buildAlphaVideoGraph(this.job?.config||this.config(),this.modelInfo),original=(this.app.rootGraph||this.app.graph)?.serialize?.();if(!original||typeof this.app.loadApiJson!=='function')throw Error('Update ComfyUI to open this editable graph.');try{await this.app.loadApiJson(graph,`Zura LTX Alpha Gen · ${Date.now()}.json`);}catch(error){await this.app.loadGraphData(original);throw error;}this.owner.studio?.close();}catch(error){this.message(error.message);}}
  open(){this.closed=false;this.page.hidden=false;this.modelDownloads.resume();void this.restoreSource();void this.checkModels();if(this.job||this.pendingSubmission){this.setProgress({title:this.job?'Reconnecting to alpha run':'Checking your run',detail:'Restoring the saved ComfyUI run…'});this.startPolling();}this.render();}
  close(){this.closed=true;this.page.hidden=true;this.video.pause();this.trimmer.close();this.modelDownloads.close();this.save();}
  dispose(){this.disposed=true;++this.revision;++this.modelRevision;this.uploadController?.abort();this.stopPolling();this.releaseLocalPreview();this.disposeExecuting?.();this.api.removeEventListener?.('progress',this.onProgress);this.close();this.modelDownloads.dispose();this.page.remove();}
}
export {AlphaWorkspace as LTXAlphaWorkspace};

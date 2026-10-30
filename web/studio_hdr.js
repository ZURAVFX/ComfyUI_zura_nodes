import {LTXLoras} from './studio_ltx_loras.js';
import {StudioModelDownloads} from './studio_model_download.js';
import {HDRLongJobClient} from './studio_hdr_long.js';
// Bounded LTX HDR post-passes use explicitly selected source assets.
export class HDRSourceTool {
  constructor(host,api,getSource,{longAvailable=false}={}){
    this.api=api;this.getSource=getSource;this.job=null;this.busy=false;this.timer=null;this.cancelling=false;
    this.root=document.createElement('details');this.root.className='gs-hdr-tool';
    this.root.innerHTML=`<summary>HDR tools · LTX 2.5</summary><div class="gs-hdr-content">
      <label>Conversion<select data-hdr="mode"><option value="sdr">SDR to HDR</option><option value="native">HDR to HDR · preview</option></select></label>
      <p>Convert a short selection. HLG is 10-bit; EXR is ACEScg. The preview is tone-mapped for an SDR screen.</p>
      <label>Convert<select data-hdr="source-kind"><option value="upload">Source footage</option><option value="output" hidden>Selected LTX result</option><option value="result">Latest LTX shot result</option><option value="own">Choose another video</option><option value="sequence" hidden>EXR sequence</option></select></label>
      <div data-hdr="video-controls" hidden><input data-hdr="video-file" type="file" accept="video/*,.mp4,.mov,.mkv,.webm" hidden/><button data-hdr="add-video" type="button">Choose video</button><span data-hdr="video-name">No video selected</span></div>
      <div data-hdr="sequence-controls" hidden><input data-hdr="sequence-files" type="file" accept=".exr" multiple hidden/><button data-hdr="add-sequence" type="button">Add EXR frames</button><span data-hdr="sequence-name">No frames selected</span><label>Sequence frame rate<input data-hdr="sequence-fps" type="number" min="1" max="120" step="0.001" value="24"/></label></div>
      <div class="gs-hdr-fields"><label>First frame<input data-hdr="start" type="number" min="0" step="1" value="0"/></label><label>Number of frames<input data-hdr="count" type="number" min="1" max="121" step="1" value="25"/></label></div>
      <label>Source colour<select data-hdr="colour"><option value="auto">Read source tags</option><option value="rec709_oetf">Rec.709</option><option value="rec709_gamma24">Rec.709 gamma 2.4</option><option value="srgb_display">sRGB</option></select></label>
      <label>Deliver<select data-hdr="output"><option value="hlg_and_exr">HLG video + EXR sequence</option><option value="hlg_video">HLG video</option><option value="acescg_exr">EXR sequence</option></select></label>
      <label data-hdr="long-control" hidden><input data-hdr="long" type="checkbox"/> Longer clip · preview · process in sections</label>
      <label data-hdr="sections-control" hidden>Section size<select data-hdr="sections"><option value="121">Longer sections · fewer joins</option><option value="25">Shorter sections · potentially faster, more joins</option></select></label>
      <p data-hdr="limits" role="status" aria-live="polite">Up to 121 frames per run. Large frame selections may need to be shorter.</p>
      <details data-hdr="models" class="gs-advanced"></details>
      <div class="gs-hdr-actions"><button data-hdr="start-job" type="button">Convert source</button><button data-hdr="cancel" type="button" hidden>Cancel</button></div>
      <p data-hdr="status" role="status" aria-live="polite"></p><progress data-hdr="progress" max="100" hidden></progress>
      <div data-hdr="result" hidden><video data-hdr="preview" controls playsinline></video><p>SDR preview only</p><a data-hdr="hlg" download hidden>Download HLG video</a> <a data-hdr="exr" download hidden>Download EXR sequence</a></div>
    </div>`;
    host.append(this.root);this.loras=new LTXLoras(this.root.querySelector('.gs-hdr-content'),path=>this.request(path),()=>this.busy);this.$('limits').after(this.loras.root);this.$('start-job').onclick=()=>this.start();this.$('cancel').onclick=()=>this.cancel();
    this.longAvailable=longAvailable;this.$('long-control').hidden=!longAvailable;
    this.longClient=new HDRLongJobClient(api,job=>this.longUpdate(job));
    this.$('long').onchange=()=>this.updateMode();
    this.models=new StudioModelDownloads(this.$('models'),(path,body)=>this.request('/zura/studio'+path,body),()=>this.refreshModelSetup());
    this.$('models').querySelector('summary').textContent='HDR model packages';
    const setupNote=document.createElement('p');setupNote.textContent='Checks for installed files and nodes. Source and frame limits are checked when you start.';this.$('models').querySelector('.gs-advanced-body').prepend(setupNote);
    this.$('models').ontoggle=()=>{if(this.$('models').open)this.refreshModelSetup();};
    this.root.ontoggle=()=>{if(this.root.open)this.sourceChanged();};
    this.$('mode').onchange=()=>this.updateMode();this.$('source-kind').onchange=()=>this.updateMode();
    this.$('output').onchange=()=>{if(this.$('models').open)this.refreshModelSetup();};
    this.$('add-sequence').onclick=()=>this.$('sequence-files').click();this.$('sequence-files').onchange=event=>this.uploadSequence(event.target.files);this.updateMode();
    this.$('add-video').onclick=()=>this.$('video-file').click();this.$('video-file').onchange=event=>{const file=event.target.files?.[0];event.target.value='';if(file)void this.uploadVideo(file);};
    this.onExecuting=event=>{const p=event.detail,active=this.longClient.busy?this.longPrompt:this.job;if(!p||!active||this.cancelling||this.longClient.cancelPending||p.prompt_id!==active||!p.node)return;this.currentNode=p.node;this.$('progress').hidden=false;this.$('progress').removeAttribute('value');this.status([this.longSection,this.nodeLabel(p.node)].filter(Boolean).join(' · '));};
    this.onProgress=event=>{const p=event.detail,active=this.longClient.busy?this.longPrompt:this.job;if(!p||!active||this.cancelling||this.longClient.cancelPending||p.prompt_id!==active||!(p.max>0)||!Number.isFinite(p.value))return;if(p.node)this.currentNode=p.node;const bar=this.$('progress'),sampling=['sample1','sample2','hdr_sample'].includes(this.currentNode);bar.hidden=false;bar.value=Math.max(0,Math.min(100,100*p.value/p.max));this.status([this.longSection,`${this.nodeLabel(this.currentNode)} · ${sampling?'step':'progress'} ${p.value} of ${p.max}`].filter(Boolean).join(' · '));};
    api.addEventListener?.('progress',this.onProgress);
    api.addEventListener?.('executing',this.onExecuting);
    try{this.job=localStorage.getItem('zura-hdr-active-job');}catch{}
    if(this.job){this.busy=true;this.loras.setBusy(true);this.root.open=true;this.$('start-job').disabled=true;this.$('cancel').hidden=false;this.$('progress').hidden=false;this.$('progress').removeAttribute('value');this.status('Reconnecting to your HDR conversion…');this.poll();}
    if(longAvailable&&!this.job){let active,pending;try{active=localStorage.getItem('zura-hdr-long-job');pending=localStorage.getItem('zura-hdr-long-request');}catch{}if(active||pending){this.root.open=true;if(active)this.longClient.reconnect(active);else this.longClient.reconnectRequest(pending);}}
    if(!longAvailable&&!this.job){let saved;try{saved=localStorage.getItem('zura-hdr-long-job')||localStorage.getItem('zura-hdr-long-request');}catch{}if(saved)void this.refreshModelSetup();}
  }
  $(id){return this.root.querySelector(`[data-hdr="${id}"]`);}
  setOutput(ref){
    this.outputRef=ref||null;const option=this.$('source-kind').querySelector('option[value="output"]');option.hidden=!ref;option.disabled=!ref;
    if(ref)this.$('source-kind').value='output';else if(this.$('source-kind').value==='output')this.$('source-kind').value=this.getSource()?.id?'upload':'own';this.updateMode();
  }
  setLongAvailable(available){
    if(this.longAvailable===available)return;
    this.longAvailable=available;this.$('long-control').hidden=!available;
    if(!available)this.$('long').checked=false;
    if(available&&!this.job&&!this.longClient.busy){let active,pending;try{active=localStorage.getItem('zura-hdr-long-job');pending=localStorage.getItem('zura-hdr-long-request');}catch{}if(active||pending){this.root.open=true;if(active)this.longClient.reconnect(active);else this.longClient.reconnectRequest(pending);}}
    this.updateMode();
  }
  status(text){this.$('status').textContent=text;}
  nodeLabel(node){return ({zura_hdr_source:'Reading source frames',zura_hdr_audio_source:'Reading source audio',zura_hdr_prepare:'Preparing HDR frames',hdr_model:'Loading LTX 2.5',model:'Loading LTX 2.5',hdr_lora:'Loading HDR adapter',lora:'Loading HDR adapter',hdr_vae_loader:'Loading video decoder',vae:'Loading video decoder',hdr_audio_vae:'Loading audio model',hdr_conditioning:'Preparing HDR conditioning',hdr_guide_input:'Preparing colour guidance',hdr_guide:'Preparing video guidance',guide1:'Preparing video guidance',guide2:'Preparing detail guidance',hdr_sample:'Generating HDR video',sample1:'Generating HDR video · pass 1 of 2',sample2:'Generating HDR video · pass 2 of 2',upsample:'Upscaling HDR detail',hdr_decode:'Decoding HDR video',decode:'Decoding HDR video',zura_hdr_exr:'Converting to EXR',zura_hdr_archive:'Packaging EXR frames',zura_hdr_hlg:'Converting to HLG',zura_hdr_save_video:'Saving HDR video',zura_hdr_preview_tonemap:'Preparing SDR preview',zura_hdr_save_preview:'Saving preview'})[node]||'Processing HDR video';}
  updateMode(){
    const native=this.$('mode').value==='native';
    const option=this.$('source-kind').querySelector('option[value="sequence"]');option.hidden=!native;option.disabled=!native;
    if(!native&&this.$('source-kind').value==='sequence')this.$('source-kind').value='upload';
    const sequence=native&&this.$('source-kind').value==='sequence';this.$('sequence-controls').hidden=!sequence;
    this.$('video-controls').hidden=this.$('source-kind').value!=='own';
    this.$('colour').innerHTML=sequence?'<option value="auto">Read EXR tags</option><option value="acescg">ACEScg</option><option value="acescct">ACEScct</option><option value="linear_rec709">Linear Rec.709</option>':native?'<option value="auto">Read source tags</option><option value="hlg_rec2020">HLG · Rec.2020</option><option value="pq_rec2020">PQ · Rec.2020</option>':'<option value="auto">Read source tags</option><option value="rec709_oetf">Rec.709</option><option value="rec709_gamma24">Rec.709 gamma 2.4</option><option value="srgb_display">sRGB</option>';
    const longer=this.longAvailable&&this.$('long').checked;
    this.$('sections-control').hidden=!longer||!native;
    this.$('count').max=longer?'10000':'121';
    this.$('limits').textContent=this.defaultLimitText();
    this.$('start-job').textContent=native?'Process HDR video':'Convert source';
    if(this.root.open)this.sourceChanged();
    this.showFrameLimit();
  }
  sourceChanged(){
    if(!this.root.open)return;
    const kind=this.$('source-kind').value,asset=kind==='sequence'?this.sequenceAsset:kind==='upload'?this.getSource():kind==='own'?this.ownAsset:null;
    const key=JSON.stringify([this.$('mode').value,this.$('output').value,kind,asset?.width,asset?.height]);
    if(key!==this.modelSetupKey){this.modelSetupKey=key;this.frameLimit=null;this.$('limits').textContent=this.defaultLimitText();void this.refreshModelSetup();}
  }
  defaultLimitText(){return this.longAvailable&&this.$('long').checked?'Longer clips use overlapping sections. Check the joins and allow extra time and disk space.':this.$('mode').value==='native'?'Preview: HLG/PQ video or EXR sequence. 1–121 frames per run, even dimensions between 32 and 2048 px; large selections need fewer frames. Requires the LTX 2.5 Refine Details LoRA. The model may alter motion or appearance.':'Up to 121 frames per run. Large frame selections may need to be shorter.';}
  showFrameLimit(){if(this.frameLimit&&!(this.longAvailable&&this.$('long').checked)){const {width,height,maxFrames}=this.frameLimit;this.$('limits').textContent=maxFrames?`Up to ${maxFrames} frames per conversion at ${width} × ${height} (software limit). Available memory may require less.${this.$('mode').value==='native'?' The model may alter motion or appearance.':''}`:`This resolution exceeds the per-conversion padding limit. Choose smaller footage.`;}}
  async refreshModelSetup(){
    const revision=this.modelSetupRevision=(this.modelSetupRevision||0)+1;
    const kind=this.$('source-kind').value,asset=kind==='sequence'?this.sequenceAsset:kind==='upload'?this.getSource():kind==='own'?this.ownAsset:null;
    const query=new URLSearchParams({mode:this.$('mode').value,output:this.$('output').value});
    if(Number.isInteger(asset?.width)&&Number.isInteger(asset?.height)){query.set('width',asset.width);query.set('height',asset.height);}
    try{
      const context=await this.request('/zura/studio/hdr/readiness?'+query);
      if(revision!==this.modelSetupRevision)return;
      if(typeof context.longPreview==='boolean')this.setLongAvailable(context.longPreview);
      if(revision!==this.modelSetupRevision)return;
      this.models.setContext(context);
      this.frameLimit=context.frameLimit||null;
      this.showFrameLimit();
      if(!this.models.packages.length)await this.models.load();
      if(revision===this.modelSetupRevision&&(this.models.packages.length||!this.models.progress.textContent))this.models.progress.textContent='';
    }catch(error){if(revision===this.modelSetupRevision){this.models.setContext(null);this.models.progress.textContent='Could not check HDR dependencies. Restart ComfyUI and try again.';}}
  }
  async uploadSequence(files){
    if(this.busy||!files?.length)return;
    this.busy=true;this.loras.setBusy(true);this.$('start-job').disabled=true;this.$('add-sequence').disabled=true;this.status('Uploading EXR frames…');
    try{
      const data=new FormData();for(const file of files)data.append('frames',file,file.name);
      const response=await this.api.fetchApi('/zura/studio/hdr/exr-sequence',{method:'POST',body:data});
      const asset=await response.json();if(!response.ok)throw new Error(asset.error?.message||asset.error||'Could not upload EXR sequence.');
      if(!asset.id)throw new Error('EXR sequence was not accepted.');
      this.sequenceAsset=asset;this.$('sequence-name').textContent=`${asset.count} frames · ${asset.width} × ${asset.height}`;
      this.$('count').value=String(Math.min(asset.count,121));this.sourceChanged();this.status('EXR frames ready.');
    }catch(error){this.status(error.message||'Could not upload EXR sequence.');}
    finally{this.busy=false;this.loras.setBusy(false);this.$('start-job').disabled=false;this.$('add-sequence').disabled=false;this.$('sequence-files').value='';}
  }
  async uploadVideo(file){
    if(this.busy)return;this.busy=true;this.loras.setBusy(true);this.$('start-job').disabled=true;this.$('add-video').disabled=true;this.status('Uploading video…');
    try{const form=new FormData();form.append('file',file);const response=await this.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body:form});const asset=await response.json();if(!response.ok)throw new Error(asset.error?.message||asset.error||'Could not upload video.');this.ownAsset=asset;this.$('video-name').textContent=asset.name||file.name;this.sourceChanged();this.status('Video ready.');}
    catch(error){this.status(error.message||'Could not upload video.');}
    finally{this.busy=false;this.loras.setBusy(false);this.$('start-job').disabled=false;this.$('add-video').disabled=false;}
  }
  async request(path,body){const response=await this.api.fetchApi(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let data;try{data=await response.json();}catch{throw new Error('ComfyUI could not respond.');}if(!response.ok)throw new Error(data.error?.message||data.error||'Could not complete the request.');return data;}
  async start(){
    if(this.busy)return;
    const asset=this.getSource(),sourceKind=this.$('source-kind').value;
    if(asset?.busy){this.status('Wait for the current Studio job to finish.');return;}
    if(sourceKind==='upload'&&!asset?.id){this.status('Add a source video first.');return;}
    if(sourceKind==='result'&&!asset?.projectId){this.status('Generate an LTX video first.');return;}
    if(sourceKind==='sequence'&&!this.sequenceAsset?.id){this.status('Add your EXR frames first.');return;}
    if(sourceKind==='own'&&!this.ownAsset?.id){this.status('Choose a video first.');return;}
    if(sourceKind==='output'&&!this.outputRef){this.status('Choose an LTX result first.');return;}
    const start=Number(this.$('start').value),count=Number(this.$('count').value);
    const longer=this.longAvailable&&this.$('long').checked,limit=longer?10000:121;
    if(!Number.isInteger(start)||start<0||!Number.isInteger(count)||count<1||count>limit){this.status(`Choose a valid first frame and 1–${limit} frames.`);return;}
    this.busy=true;this.loras.setBusy(true);this.$('start-job').disabled=true;this.$('result').hidden=true;this.$('progress').hidden=false;this.$('progress').removeAttribute('value');this.status('Checking source and model…');
    try{
      const actualKind=sourceKind==='own'?'upload':sourceKind,sourceId=sourceKind==='sequence'?this.sequenceAsset.id:sourceKind==='own'?this.ownAsset.id:asset?.id;
      if(longer){await this.longClient.start({mode:this.$('mode').value,source_kind:actualKind,source_id:sourceId,output_ref:this.outputRef,project_id:asset?.projectId,start_frame:start,frame_count:count,sequence_fps:Number(this.$('sequence-fps').value),colour_space:this.$('colour').value,output:this.$('output').value,section_frames:this.$('mode').value==='native'?Number(this.$('sections').value):121,custom_loras:this.loras.value(),client_id:this.api.clientId||'zura-hdr'});return;}
      const route=this.$('mode').value==='native'?'/zura/studio/hdr/native-graph':'/zura/studio/hdr/graph';
      const prepared=await this.request(route,{source_kind:actualKind,source_id:sourceId,output_ref:this.outputRef,project_id:asset?.projectId,start_frame:start,frame_count:count,sequence_fps:Number(this.$('sequence-fps').value),colour_space:this.$('colour').value,output:this.$('output').value,custom_loras:this.loras.value()});
      const queued=await this.request('/prompt',{prompt:prepared.graph,client_id:this.api.clientId||'zura-hdr'});
      if(!queued.prompt_id)throw new Error('ComfyUI did not accept the HDR conversion.');
      this.job=queued.prompt_id;this.currentNode=null;try{localStorage.setItem('zura-hdr-active-job',this.job);}catch{}this.$('cancel').hidden=false;this.status('Queued · waiting for ComfyUI…');this.poll();
    }catch(error){this.status(error.message);this.finish();}
  }
  url(file){return this.api.apiURL('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'}));}
  longUpdate(job){
    const state=job.state,previousPrompt=this.longPrompt,previousState=this.longState;this.busy=!['complete','cancelled','failed','unknown'].includes(state);this.loras.setBusy(this.busy);
    this.$('start-job').disabled=this.busy;this.$('cancel').hidden=!this.busy||!this.longClient.id;this.$('cancel').disabled=state==='cancelling';
    this.longPrompt=job.active_prompt_id||null;
    this.longState=state;
    this.longSection=Number.isInteger(job.total)&&job.total>0?`Section ${Math.min(job.completed+1,job.total)} of ${job.total}`:null;
    if(state==='complete'){
      const files=job.result?.files||[],preview=job.result?.preview,hlg=files.find(f=>f.filename.endsWith('.mp4')),exr=files.find(f=>f.filename.endsWith('.zip'));
      if(!preview||(!hlg&&!exr)){this.status('HDR conversion finished without the requested files.');this.finish();return;}
      this.$('preview').src=this.url(preview);for(const [name,file] of [['hlg',hlg],['exr',exr]]){this.$(name).hidden=!file;if(file)this.$(name).href=this.url(file);}
      this.$('result').hidden=false;this.status('HDR conversion complete.');this.finish();return;
    }
    if(state==='cancelled'||state==='failed'||state==='unknown'){this.status(job.error|| (state==='cancelled'?'HDR conversion cancelled.':'HDR conversion failed.'));this.finish();return;}
    // Polling repeats the same section status every two seconds. Preserve live
    // sampler progress until the active prompt or processing phase changes.
    if(state==='rendering'&&previousState==='rendering'&&this.longPrompt&&this.longPrompt===previousPrompt&&this.currentNode)return;
    if(this.longPrompt!==previousPrompt||state!=='rendering')this.currentNode=null;
    this.$('progress').hidden=false;this.$('progress').removeAttribute('value');
    this.status(state==='cancelling'?'Cancelling HDR conversion…':state==='reconnecting'?'Reconnecting to your HDR conversion…':state==='cancel-error'?(job.error||'Could not cancel. Try again.'):state==='exporting'?'Saving HDR video and EXRs…':this.longSection?`${this.longSection} · processing`:'Preparing HDR conversion…');
  }
  async poll(){
    if(!this.job)return;
    try{
      const history=await this.request('/history/'+encodeURIComponent(this.job)),item=history[this.job];
      if(!item){
        const queue=await this.request('/queue');
        const pending=[...(queue.queue_pending||[]),...(queue.queue_running||[])];
        if(!this.currentNode&&!this.cancelling){const running=(queue.queue_running||[]).some(entry=>entry[1]===this.job);this.status(running?'Loading models and preparing HDR video…':'Queued · waiting for ComfyUI…');}
        if(!pending.some(entry=>entry[1]===this.job)){
          const again=await this.request('/history/'+encodeURIComponent(this.job));
          if(!again[this.job]){this.status(this.cancelling?'HDR conversion cancelled.':'This conversion is no longer in the ComfyUI queue. Start it again.');this.finish();return;}
        }
        this.timer=setTimeout(()=>this.poll(),2000);return;
      }
      if(item.status?.status_str==='error'){this.status(this.cancelling?'HDR conversion cancelled.':'HDR conversion failed. Check ComfyUI’s job details.');this.finish();return;}
      const outputs=item.outputs||{},preview=outputs.zura_hdr_save_preview?.images?.[0];
      const hlg=outputs.zura_hdr_save_video?.images?.[0],exr=outputs.zura_hdr_archive?.files?.[0];
      if(!preview || (!hlg&&!exr)){this.status('HDR conversion finished without the requested files.');this.finish();return;}
      this.$('preview').src=this.url(preview);for(const [name,file] of [['hlg',hlg],['exr',exr]]){this.$(name).hidden=!file;if(file)this.$(name).href=this.url(file);}
      this.$('result').hidden=false;this.status('HDR conversion complete.');this.finish();
    }catch(error){if(!this.job)return;this.currentNode=null;this.$('progress').removeAttribute('value');this.status('Connection interrupted. Reconnecting to your HDR conversion…');this.timer=setTimeout(()=>this.poll(),2000);}
  }
  async cancel(){if(this.longClient.busy){await this.longClient.cancel();return;}if(!this.job||this.cancelling)return;this.cancelling=true;this.$('cancel').disabled=true;this.status('Cancelling HDR conversion…');try{await this.request('/queue',{delete:[this.job]});await this.request('/interrupt',{prompt_id:this.job});}catch(error){this.cancelling=false;this.$('cancel').disabled=false;this.status('Could not request cancellation. Try again.');}}
  finish(){clearTimeout(this.timer);this.timer=null;this.job=null;this.longPrompt=null;this.longSection=null;this.cancelling=false;try{localStorage.removeItem('zura-hdr-active-job');}catch{}this.busy=false;this.loras.setBusy(false);this.$('start-job').disabled=false;this.$('cancel').hidden=true;this.$('cancel').disabled=false;this.$('progress').hidden=true;}
  close(){clearTimeout(this.timer);this.longClient.close();this.modelSetupRevision=(this.modelSetupRevision||0)+1;this.models.dispose();this.api.removeEventListener?.('progress',this.onProgress);this.api.removeEventListener?.('executing',this.onExecuting);this.$('preview').pause?.();this.root.remove();}
}

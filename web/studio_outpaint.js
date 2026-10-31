import {installOwnedExecuting} from './studio_progress.js';
import {OutpaintTrim} from './studio_outpaint_trim.js';
import {LTXLoras} from './studio_ltx_loras.js';
import {StudioModelDownloads} from './studio_model_download.js';
import {LTXHDRDelivery} from './studio_ltx_delivery.js';
import {outpaintHDRTake} from './studio_outpaint_hdr.js';
import {OutpaintLayers} from './studio_outpaint_layers.js';
// Experimental workspace. The owner must deliberately enable the entry point.
// Review is mandatory and server-bound to the exact source and geometry.
export class OutpaintWorkspace {
  constructor(owner){
    this.owner=owner;this.api=owner.api;this.root=owner.root;this.source=null;this.sourceColour='auto';this.job=null;this.review=null;this.submitting=false;
    this.page=document.createElement('section');this.page.className='zo-page';this.page.hidden=true;
    this.page.innerHTML=`<header><h2>Extend a video</h2><button type="button" data-back>Back to video</button></header>
      <div class="zo-stage"><div class="zo-canvas" aria-label="Output canvas"><video muted playsinline loop></video><span class="zo-border" aria-hidden="true"></span></div><video class="zo-result" controls playsinline hidden></video></div>
      <div class="zo-composer"><div class="zo-sources"><button type="button" data-source>Add video</button><button type="button" data-hdr>HDR import</button><input type="file" accept="video/*,.mov,.mkv" hidden/><label>Method <select data-mode><option value="expand">Expand canvas</option><option value="black">Use black areas</option></select></label><label data-hdr-option hidden><input type="checkbox" data-hdr-output/> HDR output · preview</label><span data-source-info></span></div>
      <p data-help>Drag the footage to position it inside the new frame.</p><p data-canvas-info aria-live="polite"></p><p data-method-info>The original footage can also change.</p>
      <div class="zo-settings"><label>Width <input type="number" data-width min="128" max="1920" step="64" value="1152"/></label><label>Height <input type="number" data-height min="128" max="1920" step="64" value="640"/></label><label>Footage size <input type="range" data-scale min="30" max="100" step="1" value="72"/></label><label>Start (seconds) <input type="number" data-start min="0" step="0.041667" value="0"/></label><label>Length (seconds) <input type="number" data-duration min="0.125" max="5" step="0.041667" value="2"/></label></div>
      <textarea data-prompt placeholder="Describe the extended scene" aria-label="Video prompt"></textarea>
      <div class="zo-action"><span class="zo-model">LTX 2.5 · Preview</span><label data-delivery-label>Output <select data-delivery aria-label="Output format"><option value="sdr">SDR</option><option value="hlg_video">HDR · HLG video</option><option value="hlg_and_exr">HDR · HLG + EXR</option><option value="acescg_exr">HDR · EXR</option></select><small data-delivery-note hidden>HDR adds a conversion pass; SDR is kept.</small></label><span data-status role="status" aria-live="polite">Add a source video to begin.</span><details data-model-downloads class="zc-tool-popup gs-model-help"></details><a data-download download="zura-frame-extension.mp4" hidden>Download</a><a data-download-exr download hidden>Download EXR frames</a><a data-download-sdr download="zura-frame-extension-sdr.mp4" hidden>Download SDR</a><button type="button" data-retry-hdr hidden>Retry HDR</button><button type="button" data-cancel hidden>Cancel run</button><button type="button" data-review disabled>Review selection</button><button type="button" data-generate hidden>Approve &amp; generate</button></div><div data-progress-wrap class="zo-progress" hidden><progress data-progress max="100" aria-label="Current outpaint stage progress"></progress><span data-progress-detail></span></div></div>`;
    this.root.append(this.page);this.stage=this.page.querySelector('.zo-stage');this.canvas=this.page.querySelector('.zo-canvas');this.video=this.canvas.querySelector('video');this.result=this.page.querySelector('.zo-result');
    this.loras=new LTXLoras(this.page.querySelector('.zo-composer'),path=>this.fetch(path),()=>!!this.job||this.submitting);this.$('prompt').after(this.loras.root);
    this.modelDownloads=new StudioModelDownloads(this.$('model-downloads'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.checkCapabilities());
    this.closed=true;this.hdrSubmitting=false;this.hdrJob=null;
    try{this.hdrRecord=JSON.parse(localStorage.getItem('zura-outpaint-hdr-record'))||null;}catch{this.hdrRecord=null;}
    this.hdrDelivery=new LTXHDRDelivery(this.api,{key:'zura-outpaint-hdr',onSetup:info=>{this.hdrSetup=info;this.modelContextKey=null;this.updateModelContext();if(!info.ready)this.$('model-downloads').open=true;},onUpdate:job=>this.hdrUpdate(job),onComplete:take=>this.hdrComplete(take)});
    this.layers=new OutpaintLayers(this.page.querySelector('.zo-action'),{fetch:(path,body)=>this.fetch(path,body),apiURL:path=>this.api.apiURL(path),onChange:()=>this.paint()});
    this.$('download-exr').after(this.layers.root);
    this.$('delivery').onchange=()=>{this.hdrSetup=null;this.modelContextKey=null;this.paint();};
    this.$('retry-hdr').onclick=()=>{if(this.hdrRecord?.take)void this.startHDR(this.hdrRecord.take);};
    this.closeModels=e=>{const panel=this.$('model-downloads');if(panel.open&&!panel.contains(e.target))panel.open=false;};
    this.closeModelsOnEscape=e=>{const panel=this.$('model-downloads');if(e.key==='Escape'&&panel.open){panel.open=false;panel.querySelector('summary').focus();}};
    this.page.ownerDocument.addEventListener('pointerdown',this.closeModels,true);this.page.ownerDocument.addEventListener('keydown',this.closeModelsOnEscape,true);
    this.page.querySelector('[data-back]').onclick=()=>owner.show('video');
    this.$('source').onclick=()=>this.page.querySelector('input[type=file]').click();
    this.$('hdr').hidden=typeof owner.openHDR!=='function';this.$('hdr').onclick=()=>owner.openHDR({preferSource:true});
    this.$('hdr-output').onchange=()=>{this.trim.modeChanged();this.trim.commit({start:Number(this.$('start').value),duration:Number(this.$('duration').value)});this.invalidate();this.paint();};
    this.page.querySelector('input[type=file]').onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)this.upload(file);};
    this.$('mode').onchange=()=>{if(this.isHDRSource&&this.mode==='black'&&!this.capabilities?.hdr_black_experiment){this.$('mode').value='expand';this.message('HDR black-area preview is not available on this server.');return;}if(!this.isHDRSource&&this.mode!=='expand')this.$('hdr-output').checked=false;this.trim.modeChanged();this.reframe();this.invalidate();this.paint();};
    this.$('scale').oninput=()=>{this.reframe();this.invalidate();this.paint();};
    for(const id of ['width','height']){this.$(id).oninput=()=>{if(this.$(id).value!==''){this.reframe();this.invalidate();this.paint();}};this.$(id).onchange=()=>{this.snap(id);this.reframe();this.invalidate();this.paint();};}
    this.resizeObserver=typeof ResizeObserver==='function'?new ResizeObserver(()=>this.fitCanvas()):null;this.resizeObserver?.observe(this.stage);
    this.trim=new OutpaintTrim(this);
    // A pointer captured before HDR delivery began must not alter its source range.
    const commitTrim=this.trim.commit.bind(this.trim);
    this.trim.commit=range=>{if(!this.job&&!this.submitting&&!this.hdrBusy())return commitTrim(range);};
    this.$('review').onclick=()=>this.reviewSelection();this.$('generate').onclick=()=>this.generate();this.$('cancel').onclick=()=>this.cancel();
    this.canvas.onpointerdown=e=>this.dragStart(e);this.canvas.onpointermove=e=>this.dragMove(e);this.canvas.onpointerup=e=>this.dragEnd(e);this.canvas.onpointercancel=e=>this.dragEnd(e);
    this.executing=e=>{const p=e.detail;if(!p||this.job?.cancelling||this.hdrDelivery.client.cancelPending||!this.ownsPrompt(p.prompt_id)||!p.node)return;this.progressNode=p.node;this.sampleClock=null;this.sampleRemaining=null;this.$('progress').removeAttribute('value');this.message(this.nodeLabel(p.node));this.progressDetail();};
    this.progress=e=>{const p=e.detail;if(!p||this.job?.cancelling||this.hdrDelivery.client.cancelPending||!this.ownsPrompt(p.prompt_id)||!(p.max>0)||!Number.isFinite(p.value))return;if(p.node&&p.node!==this.progressNode){this.progressNode=p.node;this.sampleClock=null;this.sampleRemaining=null;}const sampling=this.isSampleNode(this.progressNode);let remaining=null;if(sampling){if(!this.sampleClock)this.sampleClock={node:this.progressNode,value:p.value,time:Date.now()};else if(p.value>this.sampleClock.value){const seconds=(Date.now()-this.sampleClock.time)/1000/(p.value-this.sampleClock.value)*(p.max-p.value);if(Number.isFinite(seconds)&&seconds>=0&&seconds<86400)remaining=Math.ceil(seconds);}}this.sampleRemaining=remaining;this.$('progress').value=Math.max(0,Math.min(100,100*p.value/p.max));this.message(`${this.nodeLabel(this.progressNode)} · ${sampling?'step':'progress'} ${p.value} of ${p.max}`);this.progressDetail();};
    this.api.addEventListener?.('progress',this.progress);
    this.disposeExecuting=installOwnedExecuting(this.api,this.executing);
  }
  $(name){return this.page.querySelector(`${name==='duration'||name==='start'?'input':''}[data-${name}]`);}
  hdrBusy(){return this.hdrSubmitting||!!this.hdrDelivery?.busy||!!this.hdrDelivery?.take||!!this.layers?.busy;}
  ownsPrompt(id){return !!id && ((!!this.job && (id===this.job.id || id===this.job.active_prompt_id)) || (this.hdrDelivery?.busy && id===this.hdrDelivery.activePrompt));}
  async fetch(path,body){return this.owner.fetch(path,body);}
  message(text){this.$('status').textContent=text;}
  isSampleNode(node){return ['sample','sample_high','sample1','sample2'].includes(node)||String(node).endsWith('_sample');}
  nodeLabel(node){return ({source:'Loading source footage',source_range:'Preparing selected footage',components:'Reading video and audio',canvas:'Preparing canvas',overlay:'Preparing selection preview',encoder:'Loading text encoder',positive:'Encoding prompt',negative:'Encoding prompt',video_vae:'Loading video model',audio_vae:'Loading audio model',model:'Loading LTX 2.5',adapter:'Loading outpaint adapter',guide:'Preparing video guidance',sample:'Generating extended video',sample1:'Converting to HDR · pass 1 of 2',sample2:'Converting to HDR · pass 2 of 2',hdr_source:'Loading SDR master',hdr_model:'Loading HDR model',hdr_vae:'Preparing HDR VAE',hdr_sample:'Converting to HDR',hdr_decode:'Decoding HDR frames',zura_hdr_archive:'Saving EXR frames',zura_hdr_save_video:'Saving HDR video',sample_high:'Refining extended video · pass 2 of 2',decode:'Decoding video',decode_low:'Decoding first pass',decode_high:'Decoding refined video',blend_low:'Blending first pass',blend_high:'Blending outpaint',upsize:'Upscaling first pass',encode_high:'Preparing refinement',trim_result:'Matching selected length',assemble:'Combining video and audio',save:'Saving video'})[node]|| (this.job?.kind==='review'?'Preparing selection preview':this.hdrDelivery?.busy?'Preparing HDR delivery':'Processing extended video');}
  updateSectionEstimate(state){
    if(!state?.stage||!Number.isInteger(state.window)||!Number.isInteger(state.windows)||state.window<1||state.windows<2||state.window>state.windows){this.sectionTiming=null;this.sectionRemaining=null;return;}
    const now=Date.now(),key=state.stage;
    if(!this.sectionTiming||this.sectionTiming.stage!==key||state.window<this.sectionTiming.last){this.sectionTiming={stage:key,first:state.window,last:state.window,start:now,lastStart:now,average:null};this.sectionRemaining=null;return;}
    const timing=this.sectionTiming;
    if(state.window>timing.last){timing.average=(now-timing.start)/1000/(state.window-timing.first);timing.last=state.window;timing.lastStart=now;}
    if(timing.average!==null){const seconds=Math.max(0,timing.average*(state.windows-state.window+1)-(now-timing.lastStart)/1000);this.sectionRemaining=Number.isFinite(seconds)&&seconds<86400?Math.ceil(seconds):null;}
  }
  progressDetail(){const remaining=this.sampleRemaining,seconds=this.jobStarted?Math.max(0,Math.floor((Date.now()-this.jobStarted)/1000)):0,window=this.job?.windows?`Section ${this.job.window||1} of ${this.job.windows} · `:this.hdrDelivery?.busy&&this.hdrJob?.total>0?`Section ${Math.min((this.hdrJob.completed||0)+1,this.hdrJob.total)} of ${this.hdrJob.total} · `:'';this.$('progress-detail').textContent=window+(Number.isFinite(remaining)?`About ${remaining}s left in this pass · `:'')+(Number.isFinite(this.sectionRemaining)?`About ${this.sectionRemaining}s left in this phase \u00b7 `:'')+(seconds?`${Math.floor(seconds/60)}m ${seconds%60}s elapsed`:'Waiting for ComfyUI');}
  get mode(){return this.$('mode').value;}
  snap(key){const node=this.$(key),value=Number(node.value);node.value=String(Math.max(128,Math.min(1920,Math.round((Number.isFinite(value)?value:128)/64)*64)));}
  dimensions(){
    if(this.mode==='black'&&this.source)return {width:this.source.width,height:this.source.height};
    const dimension=id=>{const value=Number(this.$(id).value);return Math.max(128,Math.min(1920,Math.round((Number.isFinite(value)?value:128)/64)*64));};
    return {width:dimension('width'),height:dimension('height')};
  }
  fitCanvas(){
    if(!this.source)return;const {width,height}=this.dimensions(),sw=this.stage.clientWidth,sh=this.stage.clientHeight;
    if(sw>0&&sh>0){const scale=Math.min(sw/width,sh/height,1050/width);this.canvas.style.width=`${width*scale}px`;this.canvas.style.height=`${height*scale}px`;}
  }
  reframe(){
    if(!this.source)return;
    const {width:w,height:h}=this.dimensions();
    if(this.mode==='black'){this.$('width').value=this.source.width;this.$('height').value=this.source.height;this.box={left:0,top:0,right:0,bottom:0};return;}
    const amount=Number(this.$('scale').value)/100,fit=Math.min(w*amount/this.source.width,h*amount/this.source.height),sw=Math.max(1,Math.round(this.source.width*fit)),sh=Math.max(1,Math.round(this.source.height*fit));
    this.box={left:Math.floor((w-sw)/2),top:Math.floor((h-sh)/2),right:w-sw-Math.floor((w-sw)/2),bottom:h-sh-Math.floor((h-sh)/2)};
  }
  usesLongHDR(){return !!(this.$('hdr-output').checked&&this.trim?.long&&Math.ceil((Number(this.$('duration').value)||0)*24-1e-6)>this.trim.maxFrames());}
  paint(){
    const has=!!this.source,black=this.mode==='black',busy=!!this.job||this.submitting||this.hdrSubmitting||!!this.hdrDelivery?.busy||!!this.layers?.busy,hdr=this.$('hdr-output').checked;this.$('width').disabled=black||busy;this.$('height').disabled=black||busy;
    const blackOption=this.$('mode').querySelector('option[value=black]');if(blackOption)blackOption.disabled=!!this.isHDRSource&&!this.capabilities?.hdr_black_experiment;
    this.$('hdr-option').hidden=!this.isHDRSource||!(black?this.capabilities?.hdr_black_experiment:this.capabilities?.hdr_expand_experiment);this.$('hdr-output').disabled=busy||!!this.isHDRSource;this.loras.root.hidden=hdr;
    this.$('delivery-label').hidden=hdr;this.$('delivery').disabled=busy||hdr;this.$('delivery-note').hidden=hdr||this.$('delivery').value==='sdr';
    this.updateModelContext();
    this.loras.setBusy(busy);
    for(const id of ['source','mode','start','duration'])this.$(id).disabled=busy;this.$('scale').disabled=black||busy;
    this.$('help').textContent=black?'Black pixels are selected for masked generation, including dark clothing or shadows. Review the whole selection.':'Drag the footage to position it inside the new frame.';
    const limit=this.trim?.maxFrames()??120,selected=Math.ceil((Number(this.$('duration').value)||0)*24-1e-6),tooLong=hdr&&(limit<9||(this.trim?.long?selected>10000:selected>limit));
    this.$('duration').max=this.trim?.long?String(Math.min(this.source?.duration||86400,hdr?10000/24:86400)):String(Math.max(0,limit)/24);
    this.$('method-info').textContent=hdr?(limit<9?'The HDR source or canvas exceeds the software memory limit. Use smaller footage or a smaller canvas.':tooLong?`Trim to ${this.trim?.long?10000:limit} frames or fewer for this source and canvas (software limit).`:this.usesLongHDR()?`HDR preview uses ${1+Math.ceil((selected-limit)/(limit-Math.min(9,Math.floor((limit-1)/2))))} overlapping sections, each with an extension and HDR pass. Generated edges are converted from SDR; the original centre retains HDR.`:`HDR video source required · up to ${limit} frames at this size (software limit). Generated edges are converted from SDR; the original centre retains HDR.`):'The original footage can also change.';
    if(hdr&&black&&!tooLong&&limit>=9)this.$('method-info').textContent=this.usesLongHDR()?'HDR black-area preview uses overlapping sections. Generated areas are converted from SDR; original footage outside the blend retains HDR.':'HDR black-area preview converts generated areas from SDR. Original footage outside the blend retains HDR.';
    const blackSetup=hdr&&black?(this.usesLongHDR()?this.capabilities?.hdr_black_long_dependencies:this.capabilities?.hdr_black_dependencies):null;
    const blackSetupMissing=!!(hdr&&black&&(!this.capabilities?.hdr_black_experiment||blackSetup?.ready!==true));
    if(blackSetupMissing)this.$('method-info').textContent=blackSetup?'HDR black-area setup is incomplete. Open Models to install the missing requirements.':'Checking HDR black-area setup…';
    if(!hdr&&this.trim?.long)this.$('method-info').textContent='Long clip: guided, blended sections. The original footage may also change.';
    this.$('review').disabled=!has||busy||tooLong||blackSetupMissing||Number(this.source?.duration)<.125;this.$('generate').hidden=!this.review||busy;this.$('generate').disabled=blackSetupMissing;this.$('cancel').hidden=!this.job&&!this.hdrDelivery?.busy;this.$('cancel').disabled=!!this.job?.cancelling||!!this.hdrDelivery?.client.cancelPending;this.$('progress-wrap').hidden=!busy||!!this.layers?.busy;this.trim?.container?.toggleAttribute('inert',busy);this.trim?.update();
    if(!has||!this.box)return;
    const {width:w,height:h}=this.dimensions(),b=this.box;
    this.canvas.style.aspectRatio=`${w}/${h}`;this.fitCanvas();
    this.$('canvas-info').textContent=`Output ${w} × ${h} px${black?' · source resolution':' · dimensions round to 64 px'}`;
    Object.assign(this.video.style,{left:`${100*b.left/w}%`,top:`${100*b.top/h}%`,width:`${100*(w-b.left-b.right)/w}%`,height:`${100*(h-b.top-b.bottom)/h}%`});
    Object.assign(this.canvas.querySelector('.zo-border').style,{left:this.video.style.left,top:this.video.style.top,width:this.video.style.width,height:this.video.style.height});
  }
  clearHDRRecord(){if(this.hdrBusy())return false;this.hdrRecord=null;this.hdrJob=null;this.renderHDROutput=null;try{localStorage.removeItem('zura-outpaint-hdr-record');}catch{}return true;}
  clearResultLinks(){this.outputRef=null;this.outputIsHDR=null;this.$('download').hidden=true;this.$('download-exr').hidden=true;this.$('download-sdr').hidden=true;this.$('retry-hdr').hidden=true;this.layers?.setResult(null);}
  invalidate(){if(this.job||!this.clearHDRRecord())return false;this.review=null;this.clearResultLinks();this.$('generate').hidden=true;this.result.hidden=true;this.canvas.hidden=false;this.message(this.source?'Review the selected area before generating.':'Add a source video to begin.');return true;}
  dragStart(e){if(this.mode==='black'||!this.source||this.job||this.submitting||this.hdrBusy())return;e.preventDefault();this.drag={id:e.pointerId,x:e.clientX,y:e.clientY,box:{...this.box}};this.canvas.setPointerCapture?.(e.pointerId);}
  dragMove(e){if(this.job||this.submitting||this.hdrBusy()){this.drag=null;return;}if(!this.drag||this.drag.id!==e.pointerId)return;const r=this.canvas.getBoundingClientRect(),{width:w,height:h}=this.dimensions(),b=this.drag.box;
    const dx=Math.round((e.clientX-this.drag.x)*w/r.width),dy=Math.round((e.clientY-this.drag.y)*h/r.height),x=Math.max(-b.left,Math.min(b.right,dx)),y=Math.max(-b.top,Math.min(b.bottom,dy));
    this.box={left:b.left+x,right:b.right-x,top:b.top+y,bottom:b.bottom-y};this.invalidate();this.paint();}
  dragEnd(e){if(this.drag?.id===e.pointerId)this.drag=null;}
  async upload(file){
    if(this.job||this.submitting||this.hdrBusy())return;this.submitting=true;this.$('progress').removeAttribute('value');this.$('progress-detail').textContent='Uploading and reading footage';this.paint();this.message('Loading video…');const form=new FormData();form.append('file',file);
    try{const r=await this.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body:form,timeoutMs:null});const asset=await r.json();if(!r.ok)throw new Error(asset.error||'Could not load this video.');this.setSourceAsset(asset);
    }catch(e){this.message(e.message);}finally{this.submitting=false;this.paint();}
  }
  setSourceAsset(asset,colour='auto',isHDR=false){
    if(this.job||this.hdrBusy())throw new Error('Wait for the current render or HDR delivery before changing the source video.');
    if(!asset?.id||!asset.file)throw new Error('Choose a valid uploaded video.');
    this.source=asset;this.sourceColour=colour;this.isHDRSource=isHDR;if(!isHDR)this.$('hdr-output').checked=false;const parts=asset.file.split('/'),params=new URLSearchParams({filename:parts.pop(),subfolder:parts.join('/'),type:'input'});
    this.video.src=asset.preview_url||this.api.apiURL('/view?'+params);this.video.load();this.$('source-info').textContent=`${asset.name} · ${asset.width} × ${asset.height}`;
    this.$('source').textContent='Replace video';this.trim.initial();this.reframe();this.invalidate();this.paint();
    if(asset.preview_status==='preparing')this.pollPreview(asset.id);
  }
  async importStudioHDR(asset,colour){
    if(this.job||this.submitting||this.hdrBusy())throw new Error('Wait for the current frame-extension job or border export to finish.');
    if(!this.capabilities?.hdr_expand_experiment)throw new Error('HDR frame extension is not available in this version.');
    if(!asset?.id||!asset.file)throw new Error('Choose a valid uploaded HDR video.');
    this.submitting=true;this.paint();
    try{
      const info=await this.fetch('/zura/studio/assets/'+encodeURIComponent(asset.id)+'/paintout',{colour_space:colour});
      const sourceColour=info?.colour_space||colour;
      if(info?.kind!=='video'||!info.path||!['auto','hlg_rec2020','pq_rec2020'].includes(sourceColour))
        throw new Error('This HDR colour format is not supported by frame extension yet.');
      this.$('mode').value='expand';this.$('hdr-output').checked=true;
      this.setSourceAsset(asset,sourceColour,true);
      this.trim.modeChanged();
    }finally{this.submitting=false;this.paint();}
  }
  async pollPreview(id){for(let i=0;i<300&&this.source?.id===id;i++){await new Promise(r=>setTimeout(r,1000));try{const a=await this.fetch('/zura/studio/assets/'+encodeURIComponent(id)+'/preview');if(a.preview_status==='ready'){this.video.src=a.preview_url;this.video.load();this.trim.update();return;}if(a.preview_status==='error'){this.message(a.preview_error||'Could not prepare the video preview.');return;}}catch{this.message('Reconnecting to video preview…');}}}
  config(){const hdr=this.$('hdr-output').checked;if(this.isHDRSource&&!hdr)throw new Error('HDR input requires the HDR frame-extension workflow.');return {source:this.source?.id,mode:this.mode,start:Number(this.$('start').value),duration:Number(this.$('duration').value),...this.dimensions(),...this.box,black_threshold:2/255,...(this.trim.long&&(!hdr||this.usesLongHDR())?{strategy:hdr?'hdr_long':'anchored_masked'}:{}),...(hdr?{hdr:true,colour_space:this.sourceColour||'auto'}:{})};}
  async reviewSelection(){if(this.job||this.submitting||this.hdrBusy()||!this.source)return;this.submitting=true;this.progressNode=null;this.sampleClock=null;this.sampleRemaining=null;this.sectionTiming=null;this.sectionRemaining=null;this.jobStarted=Date.now();this.$('progress').removeAttribute('value');this.progressDetail();this.paint();try{this.message('Preparing selection preview…');this.job=await this.fetch('/zura/studio/outpaint/review',{...this.config(),client_id:this.api.clientId||null});this.poll();}catch(e){this.job=null;this.message(e.message);}finally{this.submitting=false;this.paint();}}
  async generate(){if(this.job||this.submitting||this.hdrBusy()||!this.review)return;this.submitting=true;this.progressNode=null;this.sampleClock=null;this.sampleRemaining=null;this.sectionTiming=null;this.sectionRemaining=null;this.jobStarted=Date.now();this.$('progress').removeAttribute('value');this.progressDetail();this.paint();try{
    if(this.isHDRSource&&!this.review.hdr)throw new Error('Review this HDR source using the HDR frame-extension workflow.');
    const output=this.review.hdr?'sdr':this.$('delivery').value;
    if(output!=='sdr'){this.message('Checking HDR conversion setup…');await this.hdrDelivery.preflight({engine:'ltx',hdrOutput:output,...this.dimensions()});}
    if(!this.clearHDRRecord())throw new Error('Wait for HDR delivery or cancel it before starting another render.');
    this.clearResultLinks();this.renderHDROutput=output;
    await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/approve',{});this.message('Starting LTX outpaint…');this.job=await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/render',{prompt:this.$('prompt').value,seed:42,custom_loras:this.review.hdr?[]:this.loras.value(),client_id:this.api.clientId||null});this.poll();}catch(e){this.job=null;this.message(e.message);}finally{this.submitting=false;this.paint();}}
  async poll(){if(!this.job)return;const identity=this.job.id;try{const state=await this.fetch('/zura/studio/outpaint/jobs/'+identity);if(this.job?.id!==identity)return;
    if(this.job.active_prompt_id!==(state.active_prompt_id||null)){this.progressNode=null;this.sampleClock=null;this.sampleRemaining=null;this.$('progress').removeAttribute('value');}
    if(state.state==='cancelling'||this.job.cancelling){this.sectionTiming=null;this.sectionRemaining=null;}else this.updateSectionEstimate(state);this.job.active_prompt_id=state.active_prompt_id||null;this.job.window=state.window;this.job.windows=state.windows;
    if(state.state==='complete'){this.job=null;this.outputRef=state.kind==='render'?state.artifact:null;this.outputIsHDR=state.kind==='render'?!!state.hdr:null;this.result.src=this.api.apiURL(state.url);this.result.hidden=false;this.canvas.hidden=true;this.layers.setResult(state);
      if(state.kind==='review'){this.review=state;this.$('download').hidden=true;this.$('download-exr').hidden=true;this.message(state.hdr?'Orange marks the added area. Check the frame before generating.':'Orange marks the target area. This method may also redraw the original footage. Check the whole clip, then approve.');}else{this.review=null;const url=ref=>this.api.apiURL('/view?'+new URLSearchParams({filename:ref.filename,subfolder:ref.subfolder,type:ref.type}));this.$('download').href=state.hdr_files?.hlg?url(state.hdr_files.hlg):this.api.apiURL(state.url);this.$('download').hidden=false;this.$('download').textContent=state.hdr_files?.hlg?'Download HLG':'Download SDR';this.$('download-exr').hidden=!state.hdr_files?.exr;if(state.hdr_files?.exr)this.$('download-exr').href=url(state.hdr_files.exr);this.message(state.hdr?'HDR video ready. Preview is tone-mapped for SDR.':'Your extended video is ready.');
        if(!state.hdr&&this.renderHDROutput&&this.renderHDROutput!=='sdr')void this.prepareHDRFromOutpaint(state,this.renderHDROutput);}
      this.paint();return;}
    if(['failed','cancelled','interrupted'].includes(state.state)){this.job=null;this.message(state.error||'The job stopped. Review and try again.');this.paint();return;}
    if(state.state==='cancelling'||this.job.cancelling){this.job.cancelling=true;this.progressNode=null;this.$('progress').removeAttribute('value');this.message('Cancelling frame extension…');this.paint();}else if(state.state==='queued'){this.progressNode=null;this.$('progress').removeAttribute('value');this.message('Waiting for ComfyUI…');}else if(state.state==='assembling'){this.progressNode=null;this.$('progress').removeAttribute('value');this.message('Combining sections and audio…');}else if(!this.progressNode)this.message(state.kind==='review'?'Preparing selection preview…':['hdr','converting_hdr'].includes(state.stage)?'Converting the extended scene to HDR…':['outpaint','extending'].includes(state.stage)?'Generating the extended scene…':'Loading models and preparing video…');this.progressDetail();
  }catch{this.message('Connection interrupted. Reconnecting…');}if(this.job?.id===identity)this.timer=setTimeout(()=>this.poll(),1500);}
  async cancel(){if(!this.job){if(this.layers?.busy)await this.layers.cancel();else if(this.hdrDelivery.busy)await this.hdrDelivery.cancel();return;}if(this.job.cancelling)return;const identity=this.job.id;this.job.cancelling=true;this.sampleClock=null;this.sampleRemaining=null;this.sectionTiming=null;this.sectionRemaining=null;this.message('Cancelling frame extension…');this.progressDetail();this.paint();try{await this.fetch('/zura/studio/outpaint/jobs/'+identity+'/cancel',{});clearTimeout(this.timer);await this.poll();}catch(e){if(this.job?.id===identity){this.job.cancelling=false;this.message('Could not request cancellation. Try again.');this.paint();}}}
  async graph(){
    if(!this.review){this.message('Review the selection before opening its graph.');return;}
    if(this.review.hdr||this.review.selection?.strategy==='anchored_masked'){this.message('This workflow renders in multiple passes and cannot be opened as a single graph.');return;}
    try{await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/approve',{});
      const data=await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/graph',{prompt:this.$('prompt').value,seed:42,custom_loras:this.loras.value()});
      const app=this.owner.app,original=(app.rootGraph||app.graph)?.serialize?.();
      if(!original||typeof app.loadApiJson!=='function')throw new Error('Update ComfyUI to open this graph.');
      try{await app.loadApiJson(data.graph,'Zura frame extension.json');}catch(error){await app.loadGraphData(original);throw error;}
      this.owner.studio.close();
    }catch(error){this.message(error.message);}
  }
  saveHDR(){try{localStorage.setItem('zura-outpaint-hdr-record',JSON.stringify(this.hdrRecord));}catch{}}
  viewFile(file){return this.api.apiURL('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder,type:file.type}));}
  async prepareHDRFromOutpaint(state,output){
    if(this.hdrSubmitting||this.hdrDelivery.busy)return;
    let take=null;
    this.hdrSubmitting=true;this.message('Checking the finished SDR video…');this.paint();
    try{
      const verified=await this.fetch('/zura/studio/outpaint/jobs/'+encodeURIComponent(state.id)+'/delivery');
      const original=state.artifact,actual=verified?.artifact;
      if(!original||!actual||original.filename!==actual.filename||original.subfolder!==actual.subfolder||original.type!==actual.type)
        throw new Error('The finished video did not match this render.');
      take=outpaintHDRTake({...state,...verified},output);
      if(!take)throw new Error('The finished video has no verified HDR conversion details.');
      this.hdrRecord={state:'waiting',take};this.saveHDR();
    }catch(error){this.message((error.message||'Could not verify the SDR result.')+' Your SDR video is available to download.');}
    finally{this.hdrSubmitting=false;this.paint();}
    if(take&&!this.closed)void this.startHDR(take);
  }
  async startHDR(take){
    if(this.closed||this.hdrSubmitting||this.hdrDelivery.busy)return;
    this.hdrSubmitting=true;this.hdrRecord={state:'preparing',take};this.saveHDR();this.message('Preparing HDR conversion…');this.paint();
    try{
      await this.hdrDelivery.preflight(take.config);
      if(this.closed){this.hdrRecord={state:'waiting',take};this.saveHDR();return;}
      await this.hdrDelivery.start(take);
    }catch(error){this.hdrRecord={state:'failed',take,error:error.message};this.saveHDR();this.message((error.message||'HDR conversion failed.')+' Your SDR video is retained.');this.$('retry-hdr').hidden=false;}
    finally{this.hdrSubmitting=false;this.paint();}
  }
  hdrUpdate(job){
    const changed=this.hdrJob?.state!==job.state||this.hdrJob?.active_prompt_id!==job.active_prompt_id;this.hdrJob=job;
    const terminal=['complete','failed','cancelled','unknown'].includes(job.state);
    if(terminal&&job.state!=='complete'){
      const take=this.hdrDelivery.take||this.hdrRecord?.take;
      this.hdrRecord={state:job.state,take,error:job.error||'HDR conversion stopped. Your SDR video is retained.'};this.saveHDR();
      this.$('retry-hdr').hidden=job.state==='unknown';
    }
    if(changed||!this.progressNode){this.progressNode=null;this.sampleClock=null;this.sampleRemaining=null;this.$('progress').removeAttribute('value');
      const section=job.total>0?`Section ${Math.min((job.completed||0)+1,job.total)} of ${job.total} · `:'';
      this.message(section+(({preparing:'Preparing HDR conversion…',reconnecting:'Reconnecting to HDR conversion…',cancelling:'Cancelling HDR conversion…','cancel-error':job.error||'Cancellation could not be confirmed. Try again.',saving:'Saving HDR files…',complete:'HDR ready. The preview is SDR; download HLG or EXRs to view HDR.',failed:job.error||'HDR conversion failed. Your SDR video is retained.',cancelled:'HDR conversion cancelled. Your SDR video is retained.',unknown:job.error||'HDR job status is unknown. Your SDR video is retained.'})[job.state]||'Converting the SDR result to HDR…'));}
    this.paint();
  }
  hdrComplete(take){
    this.hdrRecord={state:'complete',take};this.saveHDR();this.showHDR(take);
  }
  showHDR(take){
    this.layers?.setResult(null);
    const hlg=(take.hdrFiles||[]).find(file=>file.filename?.toLowerCase().endsWith('.mp4'));
    const exr=(take.hdrFiles||[]).find(file=>file.filename?.toLowerCase().endsWith('.zip'));
    this.outputRef=take.sdrFile;this.outputIsHDR=false;this.result.src=this.viewFile(take.file);this.result.hidden=false;this.canvas.hidden=true;
    this.$('download').hidden=!hlg;if(hlg){this.$('download').href=this.viewFile(hlg);this.$('download').textContent='Download HLG';}
    this.$('download-exr').hidden=!exr;if(exr)this.$('download-exr').href=this.viewFile(exr);
    this.$('download-sdr').hidden=!take.sdrFile;if(take.sdrFile)this.$('download-sdr').href=this.viewFile(take.sdrFile);
    this.$('retry-hdr').hidden=true;this.message('HDR ready. The preview is SDR; download HLG or EXRs to view HDR.');
  }
  showRetainedSDR(record){
    this.layers?.setResult(null);
    const file=record?.take?.sdrFile;if(!file)return;
    this.outputRef=file;this.outputIsHDR=false;this.result.src=this.viewFile(file);this.result.hidden=false;this.canvas.hidden=true;
    this.$('download').href=this.viewFile(file);this.$('download').textContent='Download SDR';this.$('download').hidden=false;
    this.$('download-exr').hidden=true;this.$('download-sdr').hidden=true;this.$('retry-hdr').hidden=record.state==='unknown';
    this.message(record.error||'HDR conversion stopped. Your SDR video is retained.');
  }
  updateModelContext(){const hdr=this.$('hdr-output').checked,long=hdr?this.usesLongHDR():this.trim?.long,route=hdr?(long?'ltx_outpaint_hdr_long':'ltx_outpaint_hdr'):long?'ltx_outpaint_long':`ltx_outpaint_${this.mode}`,d=hdr?(this.mode==='black'?(long?this.capabilities?.hdr_black_long_dependencies:this.capabilities?.hdr_black_dependencies):(long?this.capabilities?.hdr_expand_long_dependencies:this.capabilities?.hdr_expand_dependencies)):long?this.capabilities?.dependencies:this.capabilities?.short_dependencies?.[this.mode];let missing=d?[...(d.missing_files||[]),...(d.missing_nodes||[])]:null;if(!hdr&&this.$('delivery').value!=='sdr'&&this.hdrSetup){missing=[...new Set([...(missing||[]),...(this.hdrSetup.files||[]).filter(f=>!f.ready).map(f=>f.filename),...(this.hdrSetup.missingNodes||[])])];}const key=JSON.stringify([route,missing]);if(key!==this.modelContextKey){this.modelContextKey=key;this.modelDownloads.setMissingContext(route,missing);}}
  async checkCapabilities(){try{const c=await this.fetch('/zura/studio/outpaint/capabilities');this.capabilities=c;this.longReady=c?.anchored_masked===true;}catch{this.capabilities=null;this.longReady=false;}if(!this.capabilities?.hdr_expand_experiment)this.$('hdr-output').checked=false;if(this.isHDRSource&&this.mode==='black'&&!this.capabilities?.hdr_black_experiment){this.$('mode').value='expand';this.reframe();this.invalidate();}this.trim.modeChanged();this.paint();}
  open(){this.closed=false;this.page.hidden=false;this.layers.resume();
    let identity=this.hdrDelivery.client.id||this.hdrDelivery.client.requestId;try{identity=identity||localStorage.getItem('zura-outpaint-hdr-job')||localStorage.getItem('zura-outpaint-hdr-request');}catch{}
    if(!this.hdrSubmitting&&!this.hdrDelivery.busy&&!identity&&(this.hdrDelivery.take||this.hdrRecord?.state==='preparing')){
      this.hdrRecord={state:'unknown',take:this.hdrDelivery.take||this.hdrRecord?.take,error:'HDR job confirmation is missing. Check ComfyUI before trying again. Your SDR result is retained.'};this.hdrDelivery.take=null;try{localStorage.removeItem('zura-outpaint-hdr-take');}catch{}this.saveHDR();
    }
    this.hdrDelivery.resume();if(this.hdrRecord?.state==='complete'&&!this.job)this.showHDR(this.hdrRecord.take);else if(['failed','cancelled','unknown'].includes(this.hdrRecord?.state)&&!this.job)this.showRetainedSDR(this.hdrRecord);else if(this.hdrRecord?.state==='waiting'&&!this.job&&!this.hdrDelivery.busy)void this.startHDR(this.hdrRecord.take);this.paint();if(this.job)this.poll();this.checkCapabilities();}
  close(){this.closed=true;clearTimeout(this.timer);this.layers.close();this.hdrDelivery.close();this.trim.close();this.video.pause();this.result.pause();this.page.hidden=true;}
  dispose(){this.close();this.layers.dispose();this.modelDownloads.dispose();this.page.ownerDocument.removeEventListener('pointerdown',this.closeModels,true);this.page.ownerDocument.removeEventListener('keydown',this.closeModelsOnEscape,true);this.resizeObserver?.disconnect();this.api.removeEventListener?.('progress',this.progress);this.disposeExecuting?.();this.page.remove();}
}

import {openStudioGraph} from './studio_graph_view.js';
import {deliveryVideoFile,playbackFile} from './studio_delivery_formats.js';
import {aeFrameRequest} from './studio_ae_frame_contract.js';
import {selectedEXRStorage} from './studio_exr_precision.js';
import {workspaceStorage} from './studio_storage.js';
import {OutpaintFirstFrame} from './studio_outpaint_first_frame.js';
import {installOwnedExecuting} from './studio_progress.js';
import {OutpaintTrim} from './studio_outpaint_trim.js';
import {LTXLoras} from './studio_ltx_loras.js';
import {StudioModelDownloads} from './studio_model_download.js';
import {LTXHDRDelivery} from './studio_ltx_delivery.js';
import {outpaintHDRTake} from './studio_outpaint_hdr.js';
import {removableAttachment,setAttachmentThumbnail} from './studio_composer_patterns.js';
import {composerIcons} from './studio_composer.js';
import {OutpaintLayers} from './studio_outpaint_layers.js';
// Experimental workspace. The owner must deliberately enable the entry point.
// The server validates the current canvas and source on submission.
export class OutpaintWorkspace {
  constructor(owner){this.storage=workspaceStorage(owner);
    this.owner=owner;this.api=owner.api;this.root=owner.root;this.source=null;this.sourceColour='auto';this.job=null;this.submitting=false;
    this.page=document.createElement('section');this.page.className='zo-page';this.page.hidden=true;
    this.page.innerHTML=`<header><h2>Frame extension</h2><button type="button" data-back>Back to video</button></header>
      <div class="zo-stage"><div class="zo-canvas" hidden aria-label="Output canvas"><video muted playsinline></video><span class="zo-border" aria-hidden="true"></span></div><video class="zo-result" controls playsinline hidden></video></div>
      <div class="zo-feedback" data-run-state hidden>
        <div class="zo-feedback-copy"><span data-status role="status" aria-live="polite"></span><span data-progress-detail hidden></span></div>
        <div class="zo-progress" data-progress-wrap hidden><progress data-progress max="100" aria-label="Current frame extension stage progress"></progress><button type="button" data-cancel hidden>Cancel</button></div>
      </div>
      <div class="zo-composer"><div class="zo-sources"><button type="button" data-source>${composerIcons.video}<span>Add video</span></button><button type="button" data-hdr>HDR import</button><input type="file" accept="video/*,.mov,.mkv" hidden/><label>Method <select data-mode><option value="expand">Expand canvas</option><option value="black">Use black areas</option></select></label><label data-hdr-option hidden><input type="checkbox" data-hdr-output/> HDR output · preview</label><span data-source-info></span></div>
      <p data-help>Drag the footage to position it inside the new frame.</p><p data-canvas-info aria-live="polite"></p><p data-method-info>Full-resolution frame extension follows the source footage. The original scene can also change.</p>
      <div class="zo-settings"><label>Width <input type="number" data-width min="128" max="1920" step="64" value="1152"/></label><label>Height <input type="number" data-height min="128" max="1920" step="64" value="640"/></label><label class="zo-scale">Footage size <span class="zo-scale-controls"><input type="range" data-scale min="5" max="1000" step="1" value="72" aria-label="Footage size percentage"/><span class="zo-scale-value"><input type="number" data-scale-percent min="5" max="1000" step="1" value="72" aria-label="Exact footage size percentage"/><span>%</span></span><button type="button" data-scale-fit title="Fit the entire source inside the canvas (100%)">Fit</button></span></label><label>Start (seconds) <input type="number" data-start min="0" step="0.041667" value="0"/></label><label>Length (seconds) <input type="number" data-duration min="0.125" max="5" step="0.041667" value="2"/></label></div>
      <textarea data-prompt placeholder="Describe the extended scene" aria-label="Video prompt"></textarea>
      <div class="zo-action"><span class="zo-model">LTX 2.5</span><select data-delivery hidden aria-label="Output format"><option value="sdr">SDR</option><option value="hlg_video">HDR · ProRes 4444 MOV</option><option value="hlg_and_exr">HDR · ProRes 4444 + EXR</option><option value="acescg_exr">HDR · EXR</option></select><details data-model-downloads class="zc-tool-popup gs-model-help"></details><a data-download download="zura-frame-extension.mp4" hidden>Download</a><a data-download-exr download hidden>Download EXR frames</a><a data-download-sdr download="zura-frame-extension-sdr.mp4" hidden>Download SDR</a><button type="button" data-retry-hdr hidden>Retry HDR</button><button type="button" data-generate class="gs-primary" disabled>Generate video</button></div></div>`;
    this.root.append(this.page);this.stage=this.page.querySelector('.zo-stage');this.canvas=this.page.querySelector('.zo-canvas');this.video=this.canvas.querySelector('video');this.result=this.page.querySelector('.zo-result');
    this.loras=new LTXLoras(this.page.querySelector('.zo-composer'),path=>this.fetch(path),()=>!!this.job||this.submitting);this.$('prompt').after(this.loras.root);
    this.modelDownloads=new StudioModelDownloads(this.$('model-downloads'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.checkCapabilities());
    this.modelDownloads.mountQuick(this.page.querySelector('.zo-composer'));
    this.closed=true;this.hdrSubmitting=false;this.hdrJob=null;
    try{this.hdrRecord=JSON.parse(this.storage.getItem('zura-outpaint-hdr-record'))||null;}catch{this.hdrRecord=null;}
    this.hdrDelivery=new LTXHDRDelivery(this.api,{storage:this.storage,key:'zura-outpaint-hdr',onSetup:info=>{this.hdrSetup=info;this.modelContextKey=null;this.updateModelContext();if(!info.ready)this.$('model-downloads').open=true;},onUpdate:job=>this.hdrUpdate(job),onComplete:take=>this.hdrComplete(take)});
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
    this.$('scale').oninput=()=>this.setScale(this.$('scale').value);
    this.$('scale-percent').oninput=()=>this.setScale(this.$('scale-percent').value,false);
    this.$('scale-percent').onchange=()=>this.setScale(this.$('scale-percent').value);
    this.$('scale-percent').addEventListener('focus',()=>this.$('scale-percent').select());
    this.$('scale-fit').onclick=()=>this.setScale(100);
    for(const id of ['width','height']){this.$(id).oninput=()=>{if(this.$(id).value!==''){this.reframe();this.invalidate();this.paint();}};this.$(id).onchange=()=>{this.snap(id);this.reframe();this.invalidate();this.paint();};}
    this.resizeObserver=typeof ResizeObserver==='function'?new ResizeObserver(()=>this.fitCanvas()):null;this.resizeObserver?.observe(this.stage);
    this.trim=new OutpaintTrim(this);
    this.firstFrame=new OutpaintFirstFrame(this);
    // Use Studio's common attachment / prompt / toolbar order. Geometry stays
    // directly visible alongside the shared generation controls.
    const composer=this.page.querySelector('.zo-composer'),sources=this.page.querySelector('.zo-sources'),action=this.page.querySelector('.zo-action');
    composer.classList.add('zc-prompt-card');action.classList.add('zc-prompt-bottom');
    sources.classList.add('zc-composer-attachments');for(const id of ['source','hdr'])this.$(id).classList.add('zc-attachment');
    this.sourceAttachment=removableAttachment(this.$('source'),'Remove source video',()=>this.removeSource());
    const geometry=this.page.querySelector('.zo-settings');geometry.prepend(this.$('mode').closest('label'));sources.after(geometry);
    const help=document.createElement('div');help.className='zo-canvas-help';geometry.after(help);help.append(this.$('help'),this.$('canvas-info'),this.$('method-info'));
    const tools=document.createElement('div');tools.className='zc-prompt-tools';action.prepend(tools);
    tools.append(this.page.querySelector('.zo-model'),this.$('delivery'),this.loras.root);
    const actions=document.createElement('div');actions.className='zo-run-actions';action.append(actions);
    for(const id of ['download','download-exr','download-sdr','retry-hdr','generate'])actions.append(this.$(id));
    actions.append(this.layers.root);
    sources.append(this.firstFrame.root);this.firstFrame.root.classList.add('zc-tool-popup');this.firstFrame.root.querySelector('summary').classList.add('zc-tool');
    const guidePanel=document.createElement('div');guidePanel.className='zc-tool-panel';for(const node of [...this.firstFrame.root.children])if(node.tagName!=='SUMMARY')guidePanel.append(node);this.firstFrame.root.append(guidePanel);

    // A pointer captured before HDR delivery began must not alter its source range.
    const commitTrim=this.trim.commit.bind(this.trim);
    this.trim.commit=range=>{if(!this.job&&!this.submitting&&!this.hdrBusy())return commitTrim(range);};
    this.$('generate').onclick=()=>this.generate();this.$('cancel').onclick=()=>this.cancel();
    this.canvas.onpointerdown=e=>this.dragStart(e);this.canvas.onpointermove=e=>this.dragMove(e);this.canvas.onpointerup=e=>this.dragEnd(e);this.canvas.onpointercancel=e=>this.dragEnd(e);
    this.executing=e=>{const p=e.detail;if(!p||this.job?.cancelling||this.hdrDelivery.client.cancelPending||!this.ownsPrompt(p.prompt_id)||!p.node)return;this.progressNode=p.node;this.progressStep='';this.sampleClock=null;this.sampleRemaining=null;this.$('progress').removeAttribute('value');this.message(this.nodeLabel(p.node));this.progressDetail();};
    this.progress=e=>{const p=e.detail;if(!p||this.job?.cancelling||this.hdrDelivery.client.cancelPending||!this.ownsPrompt(p.prompt_id)||!(p.max>0)||!Number.isFinite(p.value))return;if(p.node&&p.node!==this.progressNode){this.progressNode=p.node;this.sampleClock=null;this.sampleRemaining=null;}const sampling=this.isSampleNode(this.progressNode);let remaining=null;if(sampling){if(!this.sampleClock)this.sampleClock={node:this.progressNode,value:p.value,time:Date.now()};else if(p.value>this.sampleClock.value){const seconds=(Date.now()-this.sampleClock.time)/1000/(p.value-this.sampleClock.value)*(p.max-p.value);if(Number.isFinite(seconds)&&seconds>=0&&seconds<86400)remaining=Math.ceil(seconds);}}this.sampleRemaining=remaining;this.$('progress').value=Math.max(0,Math.min(100,100*p.value/p.max));this.progressStep=`${sampling?'Step':'Progress'} ${p.value} of ${p.max}`;this.message(this.nodeLabel(this.progressNode));this.progressDetail();};
    this.api.addEventListener?.('progress',this.progress);
    this.disposeExecuting=installOwnedExecuting(this.api,this.executing);
    this.message('Add a source video to begin.');
  }
  $(name){return this.page.querySelector(`${name==='duration'||name==='start'?'input':''}[data-${name}]`);}
  hdrBusy(){return this.hdrSubmitting||!!this.hdrDelivery?.busy||!!this.hdrDelivery?.take||!!this.layers?.busy;}
  ownsPrompt(id){return !!id && ((!!this.job && (id===this.job.id || id===this.job.active_prompt_id)) || (this.hdrDelivery?.busy && id===this.hdrDelivery.activePrompt));}
  async fetch(path,body){return this.owner.fetch(path,body);}
  message(text,error=false){
    this.$('status').textContent=text;
    this.$('status').classList.toggle('is-error',error);
    this.$('run-state').hidden=!text&&this.$('progress-wrap').hidden;
  }
  setRunState(phase){this.runPhase=phase;this.$('run-state').dataset.phase=phase||'';}
  isSampleNode(node){return ['sample','sample_high','sample1','sample2'].includes(node)||String(node).endsWith('_sample');}
  nodeLabel(node){return ({source:'Loading source footage',source_range:'Preparing selected footage',components:'Reading video and audio',canvas:'Preparing canvas',inpaint:'Preparing extension mask',encoder:'Loading text encoder',positive:'Encoding prompt',negative:'Encoding prompt',video_vae:'Loading video model',audio_vae:'Loading audio model',model:'Loading LTX 2.5',adapter:'Loading outpaint adapter',guide:'Preparing video guidance',sample:'Generating extension · pass 1 of 2',sample1:'Converting to HDR · pass 1 of 2',sample2:'Converting to HDR · pass 2 of 2',hdr_source:'Loading SDR master',hdr_model:'Loading HDR model',hdr_vae:'Preparing HDR VAE',hdr_sample:'Converting to HDR',hdr_decode:'Decoding HDR frames',zura_hdr_archive:'Saving EXR frames',zura_hdr_save_video:'Saving HDR video',sample_high:'Refining extended video · pass 2 of 2',decode:'Decoding video',decode_low:'Decoding first pass',decode_high:'Decoding refined video',upsize:'Upscaling first pass',encode_high:'Preparing refinement',trim_result:'Matching selected length',assemble:'Combining video and audio',save:'Saving video'})[node]|| (this.hdrDelivery?.busy?'Preparing HDR delivery':'Processing extended video');}
  updateSectionEstimate(state){
    if(!state?.stage||!Number.isInteger(state.window)||!Number.isInteger(state.windows)||state.window<1||state.windows<2||state.window>state.windows){this.sectionTiming=null;this.sectionRemaining=null;return;}
    const now=Date.now(),key=state.stage;
    if(!this.sectionTiming||this.sectionTiming.stage!==key||state.window<this.sectionTiming.last){this.sectionTiming={stage:key,first:state.window,last:state.window,start:now,lastStart:now,average:null};this.sectionRemaining=null;return;}
    const timing=this.sectionTiming;
    if(state.window>timing.last){timing.average=(now-timing.start)/1000/(state.window-timing.first);timing.last=state.window;timing.lastStart=now;}
    if(timing.average!==null){const seconds=Math.max(0,timing.average*(state.windows-state.window+1)-(now-timing.lastStart)/1000);this.sectionRemaining=Number.isFinite(seconds)&&seconds<86400?Math.ceil(seconds):null;}
  }
  progressDetail(){
    const seconds=this.jobStarted?Math.max(0,Math.floor((Date.now()-this.jobStarted)/1000)):0;
    const segment=this.job?.windows? `Segment ${this.job.window||1} of ${this.job.windows}`:
      this.hdrDelivery?.busy&&this.hdrJob?.total>0?`Segment ${Math.min((this.hdrJob.completed||0)+1,this.hdrJob.total)} of ${this.hdrJob.total}`:'';
    this.$('progress-detail').textContent=[
      segment,this.progressStep,
      Number.isFinite(this.sampleRemaining)?`About ${this.sampleRemaining}s left in this pass`:'',
      Number.isFinite(this.sectionRemaining)?`About ${this.sectionRemaining}s left in this phase`:'',
      seconds?`${Math.floor(seconds/60)}m ${seconds%60}s elapsed`:'',
    ].filter(Boolean).join(' · ');
  }
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
  setScale(value,commit=true){
    if(this.job||this.submitting||this.hdrBusy()||this.mode==='black')return;
    const n=Number(value);if(!commit&&(value===''||!Number.isFinite(n)||n<5||n>1000))return;
    const percent=Math.max(5,Math.min(1000,Math.round(Number.isFinite(n)&&value!==''?n:100)));
    this.$('scale').value=String(percent);if(commit)this.$('scale-percent').value=String(percent);
    this.reframe();this.invalidate();this.paint();
  }
  reframe(){
    if(!this.source)return;
    const {width:w,height:h}=this.dimensions();
    if(this.mode==='black'){this.$('width').value=this.source.width;this.$('height').value=this.source.height;this.box={left:0,top:0,right:0,bottom:0};return;}
    const amount=Number(this.$('scale').value)/100,fit=Math.min(w*amount/this.source.width,h*amount/this.source.height),sw=Math.max(1,Math.round(this.source.width*fit)),sh=Math.max(1,Math.round(this.source.height*fit));
    this.box={left:Math.floor((w-sw)/2),top:Math.floor((h-sh)/2),right:w-sw-Math.floor((w-sw)/2),bottom:h-sh-Math.floor((h-sh)/2)};
  }
  showSourceForTrim(){
    if(!this.source||!this.canvas.hidden)return;
    this.result.pause();this.result.hidden=true;this.firstFrame.preview.hidden=true;this.canvas.hidden=false;
  }
  showResultAfterTrim(){
    if(!this.outputRef)return;
    this.video.pause();this.canvas.hidden=true;this.firstFrame.preview.hidden=true;this.result.hidden=false;
  }
  usesLongHDR(){return !!(this.$('hdr-output').checked&&this.trim?.long&&Math.ceil((Number(this.$('duration').value)||0)*24-1e-6)>this.trim.maxFrames());}
  usesSDRSections(){
    if(this.$('hdr-output').checked)return false;
    const {width,height}=this.dimensions(),area=Math.ceil(width/64)*64*Math.ceil(height/64)*64,frames=Math.ceil(Number(this.$('duration').value)*(this.trim?.fps()||24)-1e-6),padded=Math.max(9,1+8*Math.ceil((frames-1)/8));
    return !!this.trim?.long || area>2100000&&area*padded>40000000;
  }
  paint(){
    const has=!!this.source,black=this.mode==='black',covered=!!this.box&&!black&&Object.values(this.box).every(value=>value<=0),busy=!!this.job||this.submitting||this.hdrSubmitting||!!this.hdrDelivery?.busy||!!this.layers?.busy,hdr=this.$('hdr-output').checked;this.$('width').disabled=black||busy;this.$('height').disabled=black||busy;
    const blackOption=this.$('mode').querySelector('option[value=black]');if(blackOption)blackOption.disabled=!!this.isHDRSource&&!this.capabilities?.hdr_black_experiment;
    this.$('hdr-output').disabled=busy||!!this.isHDRSource;this.loras.root.hidden=hdr;
    this.$('delivery').disabled=busy||hdr;
    this.sourceAttachment.remove.hidden=!has;this.sourceAttachment.remove.disabled=busy||!!this.firstFrame?.request;
    this.updateModelContext();
    this.firstFrame?.update();
    this.loras.setBusy(busy);
    for(const id of ['source','mode','start','duration'])this.$(id).disabled=busy;for(const id of ['scale','scale-percent','scale-fit'])this.$(id).disabled=black||busy;
    this.$('help').textContent=black?'Black areas guide the extension, including dark clothing or shadows. Review the whole selection.':'Drag the footage to position it inside the new frame.';
    const limit=this.trim?.maxFrames()??120,selected=Math.ceil((Number(this.$('duration').value)||0)*24-1e-6),tooLong=hdr&&(limit<9||(this.trim?.long?selected>10000:selected>limit));
    this.$('duration').max=this.trim?.long?String(Math.min(this.source?.duration||86400,hdr?10000/24:86400)):String(Math.max(0,limit)/(this.trim?.fps()||24));
    this.$('method-info').textContent=hdr?(limit<9?'The HDR source or canvas exceeds the software memory limit. Use smaller footage or a smaller canvas.':tooLong?`Trim to ${this.trim?.long?10000:limit} frames or fewer for this source and canvas (software limit).`:this.usesLongHDR()?`HDR preview uses ${1+Math.ceil((selected-limit)/(limit-Math.min(9,Math.floor((limit-1)/2))))} overlapping sections, each with an extension and HDR pass. The full result goes through HDR conversion.`:`HDR video source required · up to ${limit} frames at this size (software limit). The full result goes through HDR conversion.`):'Full-resolution frame extension follows the source footage. The original scene can also change.';
    if(hdr&&black&&!tooLong&&limit>=9)this.$('method-info').textContent=this.usesLongHDR()?'HDR black-area extension uses overlapping sections. The full result goes through HDR conversion.':'LTX fills black areas, then converts the full result to HDR.';
    const blackSetup=hdr&&black?(this.usesLongHDR()?this.capabilities?.hdr_black_long_dependencies:this.capabilities?.hdr_black_dependencies):null;
    const blackSetupMissing=!!(hdr&&black&&(!this.capabilities?.hdr_black_experiment||blackSetup?.ready!==true));
    if(blackSetupMissing)this.$('method-info').textContent=blackSetup?'HDR black-area setup is incomplete. Open Models to install the missing requirements.':'Checking HDR black-area setup…';
    if(!hdr&&this.usesSDRSections())this.$('method-info').textContent='Guided sections keep the selected resolution and join on whole frames. The original footage may also change.';
    if(covered)this.$('help').textContent='The footage covers the canvas. Reduce its size to leave an area to extend.';
    const generate=this.$('generate'),tracking=busy&&!this.layers?.busy;
    generate.disabled=!has||busy||tooLong||blackSetupMissing||covered||Number(this.source?.duration)<.125;
    generate.textContent=this.runPhase==='failed'?'Retry generation':busy?'Working…':'Generate video';
    this.$('cancel').hidden=!this.job&&!this.hdrDelivery?.busy;
    this.$('cancel').disabled=!!this.job?.cancelling||!!this.hdrDelivery?.client.cancelPending;
    this.$('progress-wrap').hidden=this.$('progress-detail').hidden=!tracking;
    this.$('run-state').hidden=!tracking&&!this.$('status').textContent;
    this.trim?.container?.toggleAttribute('inert',busy);this.trim?.update();
    if(!has||!this.box)return;
    const {width:w,height:h}=this.dimensions(),b=this.box;
    this.canvas.style.aspectRatio=`${w}/${h}`;this.fitCanvas();
    this.$('canvas-info').textContent=`Output ${w} × ${h} px${black?' · source resolution':' · dimensions round to 64 px'}`;
    Object.assign(this.video.style,{left:`${100*b.left/w}%`,top:`${100*b.top/h}%`,width:`${100*(w-b.left-b.right)/w}%`,height:`${100*(h-b.top-b.bottom)/h}%`});
    Object.assign(this.canvas.querySelector('.zo-border').style,{left:this.video.style.left,top:this.video.style.top,width:this.video.style.width,height:this.video.style.height});
  }
  clearHDRRecord(){if(this.hdrBusy())return false;this.hdrRecord=null;this.hdrJob=null;this.renderHDROutput=null;try{this.storage.removeItem('zura-outpaint-hdr-record');}catch{}return true;}
  clearResultLinks(){this.completedResult=null;this.outputRef=null;this.outputIsHDR=null;this.$('download').hidden=true;this.$('download-exr').hidden=true;this.$('download-sdr').hidden=true;this.$('retry-hdr').hidden=true;this.layers?.setResult(null);}
  invalidate(){if(this.job||!this.clearHDRRecord())return false;this.setRunState(null);this.firstFrame?.changed();this.clearResultLinks();this.result.hidden=true;this.canvas.hidden=!this.source;this.message(this.source?'':'Add a source video to begin.');return true;}
  dragStart(e){if(this.mode==='black'||!this.source||this.job||this.submitting||this.hdrBusy())return;e.preventDefault();this.drag={id:e.pointerId,x:e.clientX,y:e.clientY,box:{...this.box}};this.canvas.setPointerCapture?.(e.pointerId);}
  dragMove(e){if(this.job||this.submitting||this.hdrBusy()){this.drag=null;return;}if(!this.drag||this.drag.id!==e.pointerId)return;const r=this.canvas.getBoundingClientRect(),{width:w,height:h}=this.dimensions(),b=this.drag.box;
    const dx=Math.round((e.clientX-this.drag.x)*w/r.width),dy=Math.round((e.clientY-this.drag.y)*h/r.height),gapX=b.left+b.right,gapY=b.top+b.bottom;
    const left=Math.max(Math.min(0,gapX),Math.min(Math.max(0,gapX),b.left+dx)),top=Math.max(Math.min(0,gapY),Math.min(Math.max(0,gapY),b.top+dy));
    this.box={left,right:gapX-left,top,bottom:gapY-top};this.invalidate();this.paint();}
  dragEnd(e){if(this.drag?.id===e.pointerId)this.drag=null;}
  async upload(file){
    if(this.job||this.submitting||this.hdrBusy())return;this.submitting=true;this.$('progress').removeAttribute('value');this.$('progress-detail').textContent='Uploading and reading footage';this.paint();this.message('Loading video…');const form=new FormData();form.append('file',file);
    try{const r=await this.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body:form,timeoutMs:null});const asset=await r.json();if(!r.ok)throw new Error(asset.error||'Could not load this video.');this.setSourceAsset(asset);
    }catch(e){this.message(e.message);}finally{this.submitting=false;this.paint();}
  }
  removeSource(){
    if(!this.source||this.job||this.submitting||this.hdrBusy()||this.firstFrame?.request)return;
    this.source=null;this.sourceColour='auto';this.isHDRSource=false;this.box=null;this.drag=null;
    this.$('hdr-output').checked=false;
    this.trim.close();this.trim.initial();
    for(const video of [this.video,this.result]){video.pause();video.removeAttribute('src');video.load();}
    this.$('canvas-info').textContent='';this.$('source-info').textContent='';
    this.updateSourceAttachment();this.invalidate();this.paint();
  }
  updateSourceAttachment(){
    const button=this.$('source'),asset=this.source;
    button.classList.toggle('has-media',!!asset);
    button.querySelector('span').textContent=asset?'Replace video':'Add video';
    button.title=asset?.name||'Add video';
    setAttachmentThumbnail(button,asset?.thumbnail_url&&this.api.apiURL(asset.thumbnail_url));
  }
  setSourceAsset(asset,colour='auto',isHDR=false){
    if(this.job||this.hdrBusy())throw new Error('Wait for the current render or HDR delivery before changing the source video.');
    if(!asset?.id||!asset.file)throw new Error('Choose a valid uploaded video.');
    this.source=asset;this.sourceColour=colour;this.isHDRSource=isHDR;if(!isHDR)this.$('hdr-output').checked=false;const parts=asset.file.split('/'),params=new URLSearchParams({filename:parts.pop(),subfolder:parts.join('/'),type:'input'});
    this.video.src=asset.preview_url?this.api.apiURL(asset.preview_url):this.api.apiURL('/view?'+params);this.video.load();this.$('source-info').textContent=`${asset.name} · ${asset.width} × ${asset.height}`;
    this.updateSourceAttachment();this.trim.initial();this.reframe();this.invalidate();this.paint();
    if(asset.preview_status==='preparing')this.pollPreview(asset.id);
    if(!isHDR)void this.loadSourceRate(asset.id);
  }
  async loadSourceRate(identity){
    try{
      const timing=await this.fetch('/zura/studio/outpaint/source-info',{source:identity});
      if(this.source?.id!==identity||this.isHDRSource||this.job||this.submitting||this.completedResult)return;
      const num=Number(timing.fps_num),den=Number(timing.fps_den),rate=num/den;
      if(!Number.isFinite(rate)||rate<1||rate>120)return;
      this.source={...this.source,fps_num:num,fps_den:den};
      const duration=Number(this.$('duration').value)||0,start=Number(this.$('start').value)||0;
      if(duration*rate>this.trim.maxFrames()&&this.trim.canLong())this.trim.longMode.checked=true;
      this.trim.commit({start,duration});this.paint();
    }catch{/* The backend still reads the source cadence when generation starts. */}
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
  async pollPreview(id){for(let i=0;i<300&&this.source?.id===id;i++){await new Promise(r=>setTimeout(r,1000));if(this.source?.id!==id)return;try{const a=await this.fetch('/zura/studio/assets/'+encodeURIComponent(id)+'/preview');if(this.source?.id!==id)return;if(a.preview_status==='ready'){this.video.src=this.api.apiURL(a.preview_url);this.video.load();if(a.thumbnail_url){this.source.thumbnail_url=a.thumbnail_url;this.updateSourceAttachment();}this.trim.update();return;}if(a.preview_status==='error'){this.message(a.preview_error||'Could not prepare the video preview.');return;}}catch{if(this.source?.id!==id)return;this.message('Reconnecting to video preview…');}}}
  config(){const hdr=this.$('hdr-output').checked;if(this.isHDRSource&&!hdr)throw new Error('HDR input requires the HDR frame-extension workflow.');return {exr_storage:selectedEXRStorage(this.owner.outputSettings,hdr?'hlg_and_exr':this.$('delivery').value),source:this.source?.id,mode:this.mode,start:Number(this.$('start').value),duration:Number(this.$('duration').value),...this.dimensions(),...this.box,black_threshold:2/255,...((hdr?this.trim.long&&this.usesLongHDR():this.usesSDRSections())?{strategy:hdr?'hdr_long':'anchored_masked'}:{}),...(hdr?{hdr:true,colour_space:this.sourceColour||'auto'}:{})};}
  generationRequest(){
    const config=this.config();
    return aeFrameRequest(this,{...config,prompt:this.$('prompt').value,seed:42,
      first_frame:config.hdr?null:this.firstFrame?.asset?.id||null,custom_loras:config.hdr?[]:this.loras.value(),
      client_id:this.api.clientId||null});
  }
  async generate(){
    if(this.job||this.submitting||this.hdrBusy()||this.$('generate').disabled)return;
    this.submitting=true;this.progressNode=null;this.progressStep='';this.sampleClock=null;this.sampleRemaining=null;
    this.sectionTiming=null;this.sectionRemaining=null;this.lastGraphPrompt=null;this.jobStarted=Date.now();
    this.$('progress').removeAttribute('value');this.setRunState('rendering');this.message('Preparing frame extension…');
    this.progressDetail();this.paint();
    try{
      const request=this.generationRequest(),output=request.hdr?'sdr':this.$('delivery').value;
      if(output!=='sdr'){
        this.message('Checking HDR conversion setup…');
        await this.hdrDelivery.preflight({engine:'ltx',hdrOutput:output,...this.dimensions()});
      }
      if(!this.clearHDRRecord())throw Error('Wait for HDR delivery or cancel it before starting another render.');
      this.job=await this.fetch('/zura/studio/outpaint/generate',request);
      this.renderHDROutput=output;this.renderEXRStorage=request.exr_storage;
      this.firstFrame.preview.hidden=true;this.result.hidden=true;this.canvas.hidden=false;this.clearResultLinks();
      this.message('Waiting for ComfyUI…');void this.poll();
    }catch(error){
      this.job=null;this.setRunState('failed');this.message(error.message,true);
    }finally{
      this.submitting=false;this.paint();
    }
  }
  async poll(){if(!this.job)return;const identity=this.job.id;try{const state=await this.fetch('/zura/studio/outpaint/jobs/'+identity);if(this.job?.id!==identity)return;
    if(state.active_prompt_id)this.lastGraphPrompt=state.active_prompt_id;
    if((this.job.active_prompt_id||null)!==(state.active_prompt_id||null))this.clearStageProgress();
    if(state.state==='cancelling'||this.job.cancelling){this.sectionTiming=null;this.sectionRemaining=null;}else this.updateSectionEstimate(state);this.job.active_prompt_id=state.active_prompt_id||null;this.job.window=state.window;this.job.windows=state.windows;
    if(state.state==='complete'){
      this.job=null;
      if(typeof state.url!=='string'||!state.url){
        this.setRunState('failed');this.message('The finished video is unavailable. Retry generation.',true);this.paint();return;
      }
      this.completedResult=state;this.outputRef=state.artifact;this.outputIsHDR=!!state.hdr;
      this.result.src=state.artifact?.preview?this.viewFile(playbackFile(state.artifact)):this.api.apiURL(state.url);
      this.result.hidden=false;this.canvas.hidden=true;this.layers.setResult(state);this.result.load();
      this.setRunState('complete');
      this.$('download').href=state.hdr_files?.hlg?this.viewFile(state.hdr_files.hlg):
        state.artifact?.type==='output'?this.viewFile(state.artifact):this.api.apiURL(state.url);
      this.$('download').hidden=false;this.$('download').textContent=state.hdr_files?.hlg?'Download ProRes 4444':'Download SDR';
      this.$('download-exr').hidden=!state.hdr_files?.exr;
      if(state.hdr_files?.exr)this.$('download-exr').href=this.viewFile(state.hdr_files.exr);
      this.message(state.hdr?'HDR video ready · SDR preview':'Extended video ready');
      if(!state.hdr&&this.renderHDROutput&&this.renderHDROutput!=='sdr')void this.prepareHDRFromOutpaint(state,this.renderHDROutput);
      this.paint();return;
    }
    if(['failed','cancelled','interrupted'].includes(state.state)){
      this.job=null;this.setRunState('failed');
      const label=state.state==='cancelled'?'Generation cancelled':'Generation stopped';
      const segment=state.windows?` · Segment ${state.window||1} of ${state.windows}`:'';
      this.message(`${label}${segment}${state.error?` · ${state.error}`:''}`,state.state!=='cancelled');
      this.paint();return;
    }
    if(state.state==='cancelling'||this.job.cancelling){
      this.job.cancelling=true;this.clearStageProgress();this.message('Cancelling frame extension…');this.paint();
    }else if(state.state==='queued'||state.state==='assembling'){
      this.clearStageProgress();this.message(state.state==='queued'?'Waiting for ComfyUI…':'Combining sections and audio…');
    }else if(!this.progressNode){
      this.message(['hdr','converting_hdr'].includes(state.stage)?'Converting to HDR…':'Preparing footage and models…');
    }
    this.progressDetail();
    }catch{this.message('Connection interrupted. Reconnecting…');}
    if(this.job?.id===identity)this.timer=setTimeout(()=>this.poll(),1500);
  }
  clearStageProgress(){
    this.progressNode=null;this.progressStep='';this.sampleRemaining=null;this.sampleClock=null;
    this.$('progress').removeAttribute('value');
  }
  async cancel(){if(!this.job){if(this.layers?.busy)await this.layers.cancel();else if(this.hdrDelivery.busy)await this.hdrDelivery.cancel();return;}if(this.job.cancelling)return;const identity=this.job.id;this.job.cancelling=true;this.clearStageProgress();this.sectionTiming=null;this.sectionRemaining=null;this.message('Cancelling frame extension…');this.progressDetail();this.paint();try{await this.fetch('/zura/studio/outpaint/jobs/'+identity+'/cancel',{});clearTimeout(this.timer);await this.poll();}catch(e){if(this.job?.id===identity){this.job.cancelling=false;this.message('Could not request cancellation. Try again.');this.paint();}}}
  async graph(){
    if(!this.source)throw Error('Add a source video to prepare the frame extension graph.');
    if(this.job||this.submitting)throw Error('Preparing this section’s ComfyUI graph. Open Graph View again once it reaches the queue.');
    const data=await this.fetch('/zura/studio/outpaint/graph',this.generationRequest());
    await openStudioGraph(this.owner.studio,data.graph,'Frame extension · Current settings','outpaint');
  }
  saveHDR(){try{this.storage.setItem('zura-outpaint-hdr-record',JSON.stringify(this.hdrRecord));}catch{}}
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
      take=outpaintHDRTake({...state,...verified,exr_storage:this.renderEXRStorage||state.exr_storage},output);
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
    if(changed||!this.progressNode){this.clearStageProgress();
      this.message(({preparing:'Preparing HDR conversion…',reconnecting:'Reconnecting to HDR conversion…',cancelling:'Cancelling HDR conversion…','cancel-error':job.error||'Cancellation could not be confirmed. Try again.',saving:'Saving HDR files…',complete:'HDR ready. The preview is SDR; download the ProRes MOV or EXR masters.',failed:job.error||'HDR conversion failed. Your SDR video is retained.',cancelled:'HDR conversion cancelled. Your SDR video is retained.',unknown:job.error||'HDR job status is unknown. Your SDR video is retained.'})[job.state]||'Converting the SDR result to HDR…');}
    this.progressDetail();
    this.paint();
  }
  hdrComplete(take){
    this.hdrRecord={state:'complete',take};this.saveHDR();this.showHDR(take);
  }
  showHDR(take){
    this.layers?.setResult(null);
    const hlg=deliveryVideoFile(take.hdrFiles);
    const exr=(take.hdrFiles||[]).find(file=>file.filename?.toLowerCase().endsWith('.zip'));
    this.outputRef=take.sdrFile;this.outputIsHDR=false;this.result.src=this.viewFile(take.file);this.result.hidden=false;this.canvas.hidden=true;
    this.$('download').hidden=!hlg;if(hlg){this.$('download').href=this.viewFile(hlg);this.$('download').textContent='Download ProRes 4444';}
    this.$('download-exr').hidden=!exr;if(exr)this.$('download-exr').href=this.viewFile(exr);
    this.$('download-sdr').hidden=!take.sdrFile;if(take.sdrFile)this.$('download-sdr').href=this.viewFile(take.sdrFile);
    this.$('retry-hdr').hidden=true;this.message('HDR ready. The preview is SDR; download the ProRes MOV or EXR masters.');
  }
  showRetainedSDR(record){
    this.layers?.setResult(null);
    const file=record?.take?.sdrFile;if(!file)return;
    this.outputRef=file;this.outputIsHDR=false;this.result.src=this.viewFile(playbackFile(file));this.result.hidden=false;this.canvas.hidden=true;
    this.$('download').href=this.viewFile(file);this.$('download').textContent='Download SDR';this.$('download').hidden=false;
    this.$('download-exr').hidden=true;this.$('download-sdr').hidden=true;this.$('retry-hdr').hidden=record.state==='unknown';
    this.message(record.error||'HDR conversion stopped. Your SDR video is retained.');
  }
  updateModelContext(){const hdr=this.$('hdr-output').checked,long=hdr?this.usesLongHDR():this.usesSDRSections(),route=hdr?(long?'ltx_outpaint_hdr_long':'ltx_outpaint_hdr'):long?'ltx_outpaint_long':`ltx_outpaint_${this.mode}`,d=hdr?(this.mode==='black'?(long?this.capabilities?.hdr_black_long_dependencies:this.capabilities?.hdr_black_dependencies):(long?this.capabilities?.hdr_expand_long_dependencies:this.capabilities?.hdr_expand_dependencies)):long?this.capabilities?.dependencies:this.capabilities?.short_dependencies?.[this.mode];let missing=d?[...(d.missing_files||[]),...(d.missing_nodes||[])]:null;if(!hdr&&this.$('delivery').value!=='sdr'&&this.hdrSetup){missing=[...new Set([...(missing||[]),...(this.hdrSetup.files||[]).filter(f=>!f.ready).map(f=>f.filename),...(this.hdrSetup.missingNodes||[])])];}const key=JSON.stringify([route,missing]);if(key!==this.modelContextKey){this.modelContextKey=key;this.modelDownloads.setMissingContext(route,missing);}}
  async checkCapabilities(){try{const c=await this.fetch('/zura/studio/outpaint/capabilities');this.capabilities=c;this.longReady=c?.anchored_masked===true;}catch{this.capabilities=null;this.longReady=false;}if(!this.capabilities?.hdr_expand_experiment)this.$('hdr-output').checked=false;if(this.isHDRSource&&this.mode==='black'&&!this.capabilities?.hdr_black_experiment){this.$('mode').value='expand';this.reframe();this.invalidate();}this.trim.modeChanged();this.paint();}
  open(){this.closed=false;this.page.hidden=false;this.layers.resume();
    let identity=this.hdrDelivery.client.id||this.hdrDelivery.client.requestId;try{identity=identity||this.storage.getItem('zura-outpaint-hdr-job')||this.storage.getItem('zura-outpaint-hdr-request');}catch{}
    if(!this.hdrSubmitting&&!this.hdrDelivery.busy&&!identity&&(this.hdrDelivery.take||this.hdrRecord?.state==='preparing')){
      this.hdrRecord={state:'unknown',take:this.hdrDelivery.take||this.hdrRecord?.take,error:'HDR job confirmation is missing. Check ComfyUI before trying again. Your SDR result is retained.'};this.hdrDelivery.take=null;try{this.storage.removeItem('zura-outpaint-hdr-take');}catch{}this.saveHDR();
    }
    this.hdrDelivery.resume();if(this.hdrRecord?.state==='complete'&&!this.job)this.showHDR(this.hdrRecord.take);else if(['failed','cancelled','unknown'].includes(this.hdrRecord?.state)&&!this.job)this.showRetainedSDR(this.hdrRecord);else if(this.hdrRecord?.state==='waiting'&&!this.job&&!this.hdrDelivery.busy)void this.startHDR(this.hdrRecord.take);this.paint();if(this.job)this.poll();this.checkCapabilities();}
  close(){this.closed=true;clearTimeout(this.timer);this.layers.close();this.hdrDelivery.close();this.trim.close();this.video.pause();this.result.pause();this.page.hidden=true;}
  dispose(){this.firstFrame?.dispose();this.close();this.layers.dispose();this.modelDownloads.dispose();this.page.ownerDocument.removeEventListener('pointerdown',this.closeModels,true);this.page.ownerDocument.removeEventListener('keydown',this.closeModelsOnEscape,true);this.resizeObserver?.disconnect();this.api.removeEventListener?.('progress',this.progress);this.disposeExecuting?.();this.page.remove();}
}

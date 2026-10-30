import {OutpaintTrim} from './studio_outpaint_trim.js';
import {LTXLoras} from './studio_ltx_loras.js';
import {StudioModelDownloads} from './studio_model_download.js';
// Experimental workspace. The owner must deliberately enable the entry point.
// Review is mandatory and server-bound to the exact source and geometry.
export class OutpaintWorkspace {
  constructor(owner){
    this.owner=owner;this.api=owner.api;this.root=owner.root;this.source=null;this.job=null;this.review=null;this.submitting=false;
    this.page=document.createElement('section');this.page.className='zo-page';this.page.hidden=true;
    this.page.innerHTML=`<header><h2>Extend a video</h2><button type="button" data-back>Back to video</button></header>
      <div class="zo-stage"><div class="zo-canvas" aria-label="Output canvas"><video muted playsinline loop></video><span class="zo-border" aria-hidden="true"></span></div><video class="zo-result" controls playsinline hidden></video></div>
      <div class="zo-composer"><div class="zo-sources"><button type="button" data-source>Add video</button><input type="file" accept="video/*,.mov,.mkv" hidden/><label>Method <select data-mode><option value="expand">Expand canvas</option><option value="black">Use black areas</option></select></label><span data-source-info></span></div>
      <p data-help>Drag the footage to position it inside the new frame.</p><p data-canvas-info aria-live="polite"></p><p data-method-info>The original footage can also change.</p>
      <div class="zo-settings"><label>Width <input type="number" data-width min="128" max="1920" step="64" value="1152"/></label><label>Height <input type="number" data-height min="128" max="1920" step="64" value="640"/></label><label>Footage size <input type="range" data-scale min="30" max="100" step="1" value="72"/></label><label>Start (seconds) <input type="number" data-start min="0" step="0.041667" value="0"/></label><label>Length (seconds) <input type="number" data-duration min="0.125" max="5" step="0.041667" value="2"/></label></div>
      <textarea data-prompt placeholder="Describe the extended scene" aria-label="Video prompt"></textarea>
      <div class="zo-action"><span class="zo-model">LTX 2.5 · Preview</span><span data-status role="status" aria-live="polite">Add a source video to begin.</span><details data-model-downloads class="zc-tool-popup gs-model-help"></details><a data-download download="zura-frame-extension.mp4" hidden>Download</a><button type="button" data-cancel hidden>Cancel run</button><button type="button" data-review disabled>Review selection</button><button type="button" data-generate hidden>Approve &amp; generate</button></div><div data-progress-wrap class="zo-progress" hidden><progress data-progress max="100" aria-label="Current outpaint stage progress"></progress><span data-progress-detail></span></div></div>`;
    this.root.append(this.page);this.stage=this.page.querySelector('.zo-stage');this.canvas=this.page.querySelector('.zo-canvas');this.video=this.canvas.querySelector('video');this.result=this.page.querySelector('.zo-result');
    this.loras=new LTXLoras(this.page.querySelector('.zo-composer'),path=>this.fetch(path),()=>!!this.job||this.submitting);this.$('prompt').after(this.loras.root);
    this.modelDownloads=new StudioModelDownloads(this.$('model-downloads'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.checkCapabilities());
    this.closeModels=e=>{const panel=this.$('model-downloads');if(panel.open&&!panel.contains(e.target))panel.open=false;};
    this.closeModelsOnEscape=e=>{const panel=this.$('model-downloads');if(e.key==='Escape'&&panel.open){panel.open=false;panel.querySelector('summary').focus();}};
    this.page.ownerDocument.addEventListener('pointerdown',this.closeModels,true);this.page.ownerDocument.addEventListener('keydown',this.closeModelsOnEscape,true);
    this.page.querySelector('[data-back]').onclick=()=>owner.show('video');
    this.$('source').onclick=()=>this.page.querySelector('input[type=file]').click();
    this.page.querySelector('input[type=file]').onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)this.upload(file);};
    this.$('mode').onchange=()=>{this.trim.modeChanged();this.reframe();this.invalidate();this.paint();};
    this.$('scale').oninput=()=>{this.reframe();this.invalidate();this.paint();};
    for(const id of ['width','height']){this.$(id).oninput=()=>{if(this.$(id).value!==''){this.reframe();this.invalidate();this.paint();}};this.$(id).onchange=()=>{this.snap(id);this.reframe();this.invalidate();this.paint();};}
    this.resizeObserver=typeof ResizeObserver==='function'?new ResizeObserver(()=>this.fitCanvas()):null;this.resizeObserver?.observe(this.stage);
    this.trim=new OutpaintTrim(this);
    this.$('review').onclick=()=>this.reviewSelection();this.$('generate').onclick=()=>this.generate();this.$('cancel').onclick=()=>this.cancel();
    this.canvas.onpointerdown=e=>this.dragStart(e);this.canvas.onpointermove=e=>this.dragMove(e);this.canvas.onpointerup=e=>this.dragEnd(e);this.canvas.onpointercancel=e=>this.dragEnd(e);
    this.executing=e=>{const p=e.detail;if(!p||this.job?.cancelling||!this.ownsPrompt(p.prompt_id)||!p.node)return;this.progressNode=p.node;this.$('progress').removeAttribute('value');this.message(this.nodeLabel(p.node));this.progressDetail();};
    this.progress=e=>{const p=e.detail;if(!p||this.job?.cancelling||!this.ownsPrompt(p.prompt_id)||!(p.max>0)||!Number.isFinite(p.value))return;if(p.node)this.progressNode=p.node;this.$('progress').value=Math.max(0,Math.min(100,100*p.value/p.max));this.message(`${this.nodeLabel(this.progressNode)} · ${this.progressNode==='sample'||String(this.progressNode).endsWith('_sample')?'step':'progress'} ${p.value} of ${p.max}`);this.progressDetail();};
    this.api.addEventListener?.('progress',this.progress);
    this.api.addEventListener?.('executing',this.executing);
  }
  $(name){return this.page.querySelector(`${name==='duration'||name==='start'?'input':''}[data-${name}]`);}
  ownsPrompt(id){return !!id && !!this.job && (id===this.job.id || id===this.job.active_prompt_id);}
  async fetch(path,body){return this.owner.fetch(path,body);}
  message(text){this.$('status').textContent=text;}
  nodeLabel(node){return ({source:'Loading source footage',source_range:'Preparing selected footage',components:'Reading video and audio',canvas:'Preparing canvas',overlay:'Preparing selection preview',encoder:'Loading text encoder',positive:'Encoding prompt',negative:'Encoding prompt',video_vae:'Loading video model',audio_vae:'Loading audio model',model:'Loading LTX 2.5',adapter:'Loading outpaint adapter',guide:'Preparing video guidance',sample:'Generating extended video',decode:'Decoding video',blend_high:'Blending outpaint',trim_result:'Matching selected length',assemble:'Combining video and audio',save:'Saving video'})[node]|| (this.job?.kind==='review'?'Preparing selection preview':'Processing extended video');}
  progressDetail(){const seconds=this.jobStarted?Math.max(0,Math.floor((Date.now()-this.jobStarted)/1000)):0,window=this.job?.windows?`Section ${this.job.window||1} of ${this.job.windows} · `:'';this.$('progress-detail').textContent=window+(seconds?`${Math.floor(seconds/60)}m ${seconds%60}s elapsed`:'Waiting for ComfyUI');}
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
  paint(){
    const has=!!this.source,black=this.mode==='black',busy=!!this.job||this.submitting;this.$('width').disabled=black||busy;this.$('height').disabled=black||busy;
    this.updateModelContext();
    this.loras.setBusy(busy);
    for(const id of ['source','mode','start','duration'])this.$(id).disabled=busy;this.$('scale').disabled=black||busy;
    this.$('help').textContent=black?'Black pixels are selected for masked generation, including dark clothing or shadows. Review the whole selection.':'Drag the footage to position it inside the new frame.';
    this.$('duration').max=this.trim?.long?String(this.source?.duration||86400):'5';
    this.$('method-info').textContent=this.trim?.long?'Long clip: guided, blended sections. The original footage may also change.':'The original footage can also change.';
    this.$('review').disabled=!has||busy||Number(this.source?.duration)<.125;this.$('generate').hidden=!this.review||busy;this.$('cancel').hidden=!this.job;this.$('cancel').disabled=!!this.job?.cancelling;this.$('progress-wrap').hidden=!busy;this.trim?.update();
    if(!has||!this.box)return;
    const {width:w,height:h}=this.dimensions(),b=this.box;
    this.canvas.style.aspectRatio=`${w}/${h}`;this.fitCanvas();
    this.$('canvas-info').textContent=`Output ${w} × ${h} px${black?' · source resolution':' · dimensions round to 64 px'}`;
    Object.assign(this.video.style,{left:`${100*b.left/w}%`,top:`${100*b.top/h}%`,width:`${100*(w-b.left-b.right)/w}%`,height:`${100*(h-b.top-b.bottom)/h}%`});
    Object.assign(this.canvas.querySelector('.zo-border').style,{left:this.video.style.left,top:this.video.style.top,width:this.video.style.width,height:this.video.style.height});
  }
  invalidate(){this.review=null;this.$('generate').hidden=true;this.$('download').hidden=true;this.result.hidden=true;this.canvas.hidden=false;this.message(this.source?'Review the selected area before generating.':'Add a source video to begin.');}
  dragStart(e){if(this.mode==='black'||!this.source||this.job||this.submitting)return;e.preventDefault();this.drag={id:e.pointerId,x:e.clientX,y:e.clientY,box:{...this.box}};this.canvas.setPointerCapture?.(e.pointerId);}
  dragMove(e){if(!this.drag||this.drag.id!==e.pointerId)return;const r=this.canvas.getBoundingClientRect(),{width:w,height:h}=this.dimensions(),b=this.drag.box;
    const dx=Math.round((e.clientX-this.drag.x)*w/r.width),dy=Math.round((e.clientY-this.drag.y)*h/r.height),x=Math.max(-b.left,Math.min(b.right,dx)),y=Math.max(-b.top,Math.min(b.bottom,dy));
    this.box={left:b.left+x,right:b.right-x,top:b.top+y,bottom:b.bottom-y};this.invalidate();this.paint();}
  dragEnd(e){if(this.drag?.id===e.pointerId)this.drag=null;}
  async upload(file){
    if(this.job||this.submitting)return;this.submitting=true;this.$('progress').removeAttribute('value');this.$('progress-detail').textContent='Uploading and reading footage';this.paint();this.message('Loading video…');const form=new FormData();form.append('file',file);
    try{const r=await this.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body:form,timeoutMs:null});const asset=await r.json();if(!r.ok)throw new Error(asset.error||'Could not load this video.');this.source=asset;
      const params=new URLSearchParams({filename:asset.file.split('/').pop(),subfolder:asset.file.split('/').slice(0,-1).join('/'),type:'input'});
      this.video.src=asset.preview_url||this.api.apiURL('/view?'+params);this.video.load();this.$('source-info').textContent=`${asset.name} · ${asset.width} × ${asset.height}`;
      this.$('source').textContent='Replace video';this.trim.initial();this.reframe();this.invalidate();this.paint();
      if(asset.preview_status==='preparing')this.pollPreview(asset.id);
    }catch(e){this.message(e.message);}finally{this.submitting=false;this.paint();}
  }
  async pollPreview(id){for(let i=0;i<300&&this.source?.id===id;i++){await new Promise(r=>setTimeout(r,1000));try{const a=await this.fetch('/zura/studio/assets/'+encodeURIComponent(id)+'/preview');if(a.preview_status==='ready'){this.video.src=a.preview_url;this.video.load();this.trim.update();return;}if(a.preview_status==='error'){this.message(a.preview_error||'Could not prepare the video preview.');return;}}catch{this.message('Reconnecting to video preview…');}}}
  config(){return {source:this.source?.id,mode:this.mode,start:Number(this.$('start').value),duration:Number(this.$('duration').value),...this.dimensions(),...this.box,black_threshold:2/255,...(this.trim.long?{strategy:'anchored_masked'}:{})};}
  async reviewSelection(){if(this.job||this.submitting||!this.source)return;this.submitting=true;this.progressNode=null;this.jobStarted=Date.now();this.$('progress').removeAttribute('value');this.progressDetail();this.paint();try{this.message('Preparing selection preview…');this.job=await this.fetch('/zura/studio/outpaint/review',{...this.config(),client_id:this.api.clientId||null});this.poll();}catch(e){this.job=null;this.message(e.message);}finally{this.submitting=false;this.paint();}}
  async generate(){if(this.job||this.submitting||!this.review)return;this.submitting=true;this.progressNode=null;this.jobStarted=Date.now();this.$('progress').removeAttribute('value');this.progressDetail();this.paint();try{await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/approve',{});this.message('Starting LTX outpaint…');this.job=await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/render',{prompt:this.$('prompt').value,seed:42,custom_loras:this.loras.value(),client_id:this.api.clientId||null});this.poll();}catch(e){this.job=null;this.message(e.message);}finally{this.submitting=false;this.paint();}}
  async poll(){if(!this.job)return;const identity=this.job.id;try{const state=await this.fetch('/zura/studio/outpaint/jobs/'+identity);if(this.job?.id!==identity)return;
    if(this.job.active_prompt_id!==(state.active_prompt_id||null)){this.progressNode=null;this.$('progress').removeAttribute('value');}
    this.job.active_prompt_id=state.active_prompt_id||null;this.job.window=state.window;this.job.windows=state.windows;
    if(state.state==='complete'){this.job=null;this.result.src=this.api.apiURL(state.url);this.result.hidden=false;this.canvas.hidden=true;
      if(state.kind==='review'){this.review=state;this.$('download').hidden=true;this.message('Orange marks the target area. This method may also redraw the original footage. Check the whole clip, then approve.');}else{this.review=null;this.$('download').href=this.api.apiURL(state.url);this.$('download').hidden=false;this.message('Your extended video is ready.');}
      this.paint();return;}
    if(['failed','cancelled','interrupted'].includes(state.state)){this.job=null;this.message(state.error||'The job stopped. Review and try again.');this.paint();return;}
    if(state.state==='cancelling'||this.job.cancelling){this.job.cancelling=true;this.progressNode=null;this.$('progress').removeAttribute('value');this.message('Cancelling frame extension…');this.paint();}else if(state.state==='queued'){this.progressNode=null;this.$('progress').removeAttribute('value');this.message('Waiting for ComfyUI…');}else if(state.state==='assembling'){this.progressNode=null;this.$('progress').removeAttribute('value');this.message('Combining sections and audio…');}else if(!this.progressNode)this.message(state.kind==='review'?'Preparing selection preview…':'Loading models and preparing video…');this.progressDetail();
  }catch{this.message('Connection interrupted. Reconnecting…');}if(this.job?.id===identity)this.timer=setTimeout(()=>this.poll(),1500);}
  async cancel(){if(!this.job||this.job.cancelling)return;const identity=this.job.id;this.job.cancelling=true;this.message('Cancelling frame extension…');this.paint();try{await this.fetch('/zura/studio/outpaint/jobs/'+identity+'/cancel',{});clearTimeout(this.timer);await this.poll();}catch(e){if(this.job?.id===identity){this.job.cancelling=false;this.message('Could not request cancellation. Try again.');this.paint();}}}
  async graph(){
    if(!this.review){this.message('Review the selection before opening its graph.');return;}
    if(this.review.selection?.strategy==='anchored_masked'){this.message('Long clips render in sections and cannot be opened as a single graph.');return;}
    try{await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/approve',{});
      const data=await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/graph',{prompt:this.$('prompt').value,seed:42,custom_loras:this.loras.value()});
      const app=this.owner.app,original=(app.rootGraph||app.graph)?.serialize?.();
      if(!original||typeof app.loadApiJson!=='function')throw new Error('Update ComfyUI to open this graph.');
      try{await app.loadApiJson(data.graph,'Zura frame extension.json');}catch(error){await app.loadGraphData(original);throw error;}
      this.owner.studio.close();
    }catch(error){this.message(error.message);}
  }
  updateModelContext(){const route=this.trim?.long?'ltx_outpaint_long':`ltx_outpaint_${this.mode}`,d=this.trim?.long?this.capabilities?.dependencies:this.capabilities?.short_dependencies?.[this.mode];const missing=d?[...(d.missing_files||[]),...(d.missing_nodes||[])]:null;const key=JSON.stringify([route,missing]);if(key!==this.modelContextKey){this.modelContextKey=key;this.modelDownloads.setMissingContext(route,missing);}}
  async checkCapabilities(){try{const c=await this.fetch('/zura/studio/outpaint/capabilities');this.capabilities=c;this.longReady=c?.anchored_masked===true;}catch{this.capabilities=null;this.longReady=false;}this.trim.modeChanged();this.paint();}
  open(){this.page.hidden=false;this.paint();if(this.job)this.poll();this.checkCapabilities();}
  close(){clearTimeout(this.timer);this.trim.close();this.video.pause();this.result.pause();this.page.hidden=true;}
  dispose(){this.close();this.modelDownloads.dispose();this.page.ownerDocument.removeEventListener('pointerdown',this.closeModels,true);this.page.ownerDocument.removeEventListener('keydown',this.closeModelsOnEscape,true);this.resizeObserver?.disconnect();this.api.removeEventListener?.('progress',this.progress);this.api.removeEventListener?.('executing',this.executing);this.page.remove();}
}

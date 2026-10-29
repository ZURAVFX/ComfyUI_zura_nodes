// Experimental workspace. The owner must deliberately enable the entry point.
// Review is mandatory and server-bound to the exact source and geometry.
export class OutpaintWorkspace {
  constructor(owner){
    this.owner=owner;this.api=owner.api;this.root=owner.root;this.source=null;this.job=null;this.review=null;this.submitting=false;
    this.page=document.createElement('section');this.page.className='zo-page';this.page.hidden=true;
    this.page.innerHTML=`<header><h2>Extend a video</h2><button type="button" data-back>Back to video</button></header>
      <div class="zo-stage"><div class="zo-canvas" aria-label="Output canvas"><video muted playsinline loop></video><span class="zo-border" aria-hidden="true"></span></div><video class="zo-result" controls playsinline hidden></video></div>
      <div class="zo-composer"><div class="zo-sources"><button type="button" data-source>Add video</button><input type="file" accept="video/*,.mov,.mkv" hidden/><label>Method <select data-mode><option value="expand">Expand canvas</option><option value="black">Use black areas</option></select></label><span data-source-info></span></div>
      <p data-help>Drag the footage to position it inside the new frame.</p><p>Preview: up to 5 seconds at 24 fps. The original footage can also change.</p>
      <div class="zo-settings"><label>Width <input type="number" data-width min="128" max="1920" step="64" value="1152"/></label><label>Height <input type="number" data-height min="128" max="1920" step="64" value="640"/></label><label>Footage size <input type="range" data-scale min="30" max="100" step="1" value="72"/></label><label>Start (seconds) <input type="number" data-start min="0" step="0.041667" value="0"/></label><label>Length (seconds) <input type="number" data-duration min="0.041667" max="5" step="0.041667" value="2"/></label></div>
      <textarea data-prompt placeholder="Describe the extended scene" aria-label="Video prompt"></textarea>
      <div class="zo-action"><span class="zo-model">LTX 2.5 · Preview</span><span data-status role="status" aria-live="polite">Add a source video to begin.</span><a data-download download="zura-frame-extension.mp4" hidden>Download</a><button type="button" data-cancel hidden>Cancel run</button><button type="button" data-review disabled>Review selection</button><button type="button" data-generate hidden>Approve &amp; generate</button></div></div>`;
    this.root.append(this.page);this.canvas=this.page.querySelector('.zo-canvas');this.video=this.canvas.querySelector('video');this.result=this.page.querySelector('.zo-result');
    this.page.querySelector('[data-back]').onclick=()=>owner.show('video');
    this.$('source').onclick=()=>this.page.querySelector('input[type=file]').click();
    this.page.querySelector('input[type=file]').onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)this.upload(file);};
    this.$('mode').onchange=()=>{this.reframe();this.invalidate();this.paint();};
    this.$('scale').oninput=()=>{this.reframe();this.invalidate();this.paint();};
    for(const id of ['width','height'])this.$(id).onchange=()=>{this.snap(id);this.reframe();this.invalidate();this.paint();};
    for(const id of ['start','duration'])this.$(id).onchange=()=>this.invalidate();
    this.$('review').onclick=()=>this.reviewSelection();this.$('generate').onclick=()=>this.generate();this.$('cancel').onclick=()=>this.cancel();
    this.canvas.onpointerdown=e=>this.dragStart(e);this.canvas.onpointermove=e=>this.dragMove(e);this.canvas.onpointerup=e=>this.dragEnd(e);this.canvas.onpointercancel=e=>this.dragEnd(e);
    this.progress=e=>{const p=e.detail;if(this.job?.id===p.prompt_id&&p.max)this.message(`Generating extended video · step ${p.value} of ${p.max}`);};
    this.api.addEventListener?.('progress',this.progress);
  }
  $(name){return this.page.querySelector(`[data-${name}]`);}
  async fetch(path,body){return this.owner.fetch(path,body);}
  message(text){this.$('status').textContent=text;}
  get mode(){return this.$('mode').value;}
  snap(key){const node=this.$(key),value=Number(node.value);node.value=String(Math.max(128,Math.min(1920,Math.round((Number.isFinite(value)?value:128)/64)*64)));}
  reframe(){
    if(!this.source)return;
    const w=Number(this.$('width').value),h=Number(this.$('height').value);
    if(this.mode==='black'){this.$('width').value=this.source.width;this.$('height').value=this.source.height;this.box={left:0,top:0,right:0,bottom:0};return;}
    const amount=Number(this.$('scale').value)/100,fit=Math.min(w*amount/this.source.width,h*amount/this.source.height),sw=Math.max(1,Math.round(this.source.width*fit)),sh=Math.max(1,Math.round(this.source.height*fit));
    this.box={left:Math.floor((w-sw)/2),top:Math.floor((h-sh)/2),right:w-sw-Math.floor((w-sw)/2),bottom:h-sh-Math.floor((h-sh)/2)};
  }
  paint(){
    const has=!!this.source,black=this.mode==='black',busy=!!this.job||this.submitting;this.$('width').disabled=black||busy;this.$('height').disabled=black||busy;
    for(const id of ['source','mode','start','duration'])this.$(id).disabled=busy;this.$('scale').disabled=black||busy;
    this.$('help').textContent=black?'Black pixels are selected for generation, including dark clothing or shadows. Review the whole selection.':'Drag the footage to position it inside the new frame.';
    this.$('review').disabled=!has||busy;this.$('generate').hidden=!this.review||busy;this.$('cancel').hidden=!this.job;
    if(!has||!this.box)return;
    const w=Number(this.$('width').value),h=Number(this.$('height').value),b=this.box;
    this.canvas.style.aspectRatio=`${w}/${h}`;
    Object.assign(this.video.style,{left:`${100*b.left/w}%`,top:`${100*b.top/h}%`,width:`${100*(w-b.left-b.right)/w}%`,height:`${100*(h-b.top-b.bottom)/h}%`});
    Object.assign(this.canvas.querySelector('.zo-border').style,{left:this.video.style.left,top:this.video.style.top,width:this.video.style.width,height:this.video.style.height});
  }
  invalidate(){this.review=null;this.$('generate').hidden=true;this.$('download').hidden=true;this.result.hidden=true;this.canvas.hidden=false;this.message(this.source?'Review the selected area before generating.':'Add a source video to begin.');}
  dragStart(e){if(this.mode==='black'||!this.source||this.job||this.submitting)return;e.preventDefault();this.drag={id:e.pointerId,x:e.clientX,y:e.clientY,box:{...this.box}};this.canvas.setPointerCapture?.(e.pointerId);}
  dragMove(e){if(!this.drag||this.drag.id!==e.pointerId)return;const r=this.canvas.getBoundingClientRect(),w=Number(this.$('width').value),h=Number(this.$('height').value),b=this.drag.box;
    const dx=Math.round((e.clientX-this.drag.x)*w/r.width),dy=Math.round((e.clientY-this.drag.y)*h/r.height),x=Math.max(-b.left,Math.min(b.right,dx)),y=Math.max(-b.top,Math.min(b.bottom,dy));
    this.box={left:b.left+x,right:b.right-x,top:b.top+y,bottom:b.bottom-y};this.invalidate();this.paint();}
  dragEnd(e){if(this.drag?.id===e.pointerId)this.drag=null;}
  async upload(file){
    if(this.job||this.submitting)return;this.submitting=true;this.paint();this.message('Loading video…');const form=new FormData();form.append('file',file);
    try{const r=await this.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body:form,timeoutMs:null});const asset=await r.json();if(!r.ok)throw new Error(asset.error||'Could not load this video.');this.source=asset;
      const params=new URLSearchParams({filename:asset.file.split('/').pop(),subfolder:asset.file.split('/').slice(0,-1).join('/'),type:'input'});
      this.video.src=asset.preview_url||this.api.apiURL('/view?'+params);this.video.load();this.$('source-info').textContent=`${asset.name} · ${asset.width} × ${asset.height}`;
      this.$('source').textContent='Replace video';this.$('duration').value=Math.min(2,asset.duration).toFixed(2);this.reframe();this.invalidate();this.paint();
      if(asset.preview_status==='preparing')this.pollPreview(asset.id);
    }catch(e){this.message(e.message);}finally{this.submitting=false;this.paint();}
  }
  async pollPreview(id){for(let i=0;i<300&&this.source?.id===id;i++){await new Promise(r=>setTimeout(r,1000));try{const a=await this.fetch('/zura/studio/assets/'+encodeURIComponent(id)+'/preview');if(a.preview_status==='ready'){this.video.src=a.preview_url;this.video.load();return;}if(a.preview_status==='error'){this.message(a.preview_error||'Could not prepare the video preview.');return;}}catch{this.message('Reconnecting to video preview…');}}}
  config(){return {source:this.source?.id,mode:this.mode,start:Number(this.$('start').value),duration:Number(this.$('duration').value),width:Number(this.$('width').value),height:Number(this.$('height').value),...this.box,black_threshold:2/255};}
  async reviewSelection(){if(this.job||this.submitting||!this.source)return;this.submitting=true;this.paint();try{this.message('Preparing selection preview…');this.job=await this.fetch('/zura/studio/outpaint/review',this.config());this.poll();}catch(e){this.job=null;this.message(e.message);}finally{this.submitting=false;this.paint();}}
  async generate(){if(this.job||this.submitting||!this.review)return;this.submitting=true;this.paint();try{await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/approve',{});this.message('Starting LTX outpaint…');this.job=await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/render',{prompt:this.$('prompt').value,seed:42});this.poll();}catch(e){this.job=null;this.message(e.message);}finally{this.submitting=false;this.paint();}}
  async poll(){if(!this.job)return;const identity=this.job.id;try{const state=await this.fetch('/zura/studio/outpaint/jobs/'+identity);if(this.job?.id!==identity)return;
    if(state.state==='complete'){this.job=null;this.result.src=this.api.apiURL(state.url);this.result.hidden=false;this.canvas.hidden=true;
      if(state.kind==='review'){this.review=state;this.$('download').hidden=true;this.message('Orange marks the target area. This method may also redraw the original footage. Check the whole clip, then approve.');}else{this.review=null;this.$('download').href=this.api.apiURL(state.url);this.$('download').hidden=false;this.message('Your extended video is ready.');}
      this.paint();return;}
    if(['failed','cancelled','interrupted'].includes(state.state)){this.job=null;this.message(state.error||'The job stopped. Review and try again.');this.paint();return;}
    this.message(state.state==='queued'?'Waiting for ComfyUI…':state.kind==='review'?'Preparing selection preview…':'Generating extended video…');
  }catch{this.message('Connection interrupted. Reconnecting…');}if(this.job?.id===identity)this.timer=setTimeout(()=>this.poll(),1500);}
  async cancel(){if(!this.job)return;try{await this.fetch('/zura/studio/outpaint/jobs/'+this.job.id+'/cancel',{});this.job=null;this.message('Stopped this run.');this.paint();}catch(e){this.message(e.message);}}
  async graph(){
    if(!this.review){this.message('Review the selection before opening its graph.');return;}
    try{await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/approve',{});
      const data=await this.fetch('/zura/studio/outpaint/jobs/'+this.review.id+'/graph',{prompt:this.$('prompt').value,seed:42});
      const app=this.owner.app,original=(app.rootGraph||app.graph)?.serialize?.();
      if(!original||typeof app.loadApiJson!=='function')throw new Error('Update ComfyUI to open this graph.');
      try{await app.loadApiJson(data.graph,'Zura frame extension.json');}catch(error){await app.loadGraphData(original);throw error;}
      this.owner.studio.close();
    }catch(error){this.message(error.message);}
  }
  open(){this.page.hidden=false;this.paint();if(this.job)this.poll();}
  close(){clearTimeout(this.timer);this.video.pause();this.result.pause();this.page.hidden=true;}
  dispose(){this.close();this.api.removeEventListener?.('progress',this.progress);this.page.remove();}
}

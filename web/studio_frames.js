import {megapixelSlider,editableDimension} from './studio_resolution.js';
import {FRAME_LENGTHS,FRAME_SIZE_PRESETS,FRAME_MEGAPIXELS} from './frame_video_recipes.js';
import {composerIcons as icons} from './studio_composer.js';
import {tidyArtistGraph} from './artist_graph.js';
import {ENDPOINT_RECIPES,endpointRecipe,endpointLengths,endpointPresetSize} from './video_recipe_catalog.js';
import {attachWorkspaceSamplePreview,nativePreviewMethod} from './studio_live_preview.js';
import {PreviewZoom} from './studio_preview_zoom.js';
import {LTXLoras} from './studio_ltx_loras.js';
import {StudioModelDownloads} from './studio_model_download.js';
const KEY='zura-first-last-v1';
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const view=(api,file,type='output')=>api.apiURL('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type}));
export class FrameVideoWorkspace{
  constructor(owner){
    this.owner=owner;this.api=owner.api;this.app=owner.app;this.studio=owner.studio;
    let saved={};try{saved=JSON.parse(localStorage.getItem(KEY))||{};}catch{}
    this.assets=saved.assets||{};this.job=saved.job||null;this.items=Array.isArray(saved.items)?saved.items.slice(0,12):[];
    this.page=document.createElement('section');this.page.className='zf-page';
    this.page.innerHTML=`
      <div class="zf-heading">
        <h2>First & last frame</h2>
        <details id="zf-history"><summary>History</summary><div id="zf-takes"></div></details><button type="button" id="zf-clear">Clear history</button>
      </div>
      <div class="zf-viewer">
        <div id="zf-empty"><h3>Bring your image to life.</h3><p>Add a first frame and describe the movement. Add a last frame if you want to guide the ending.</p></div>
        <div id="zf-image-slot" hidden></div><video id="zf-result" controls playsinline hidden></video>
        <div id="zf-progress" hidden><strong id="zf-progress-title">Queued</strong><button id="zf-cancel" type="button">Cancel run</button><progress id="zf-bar" max="100" aria-label="Video generation progress"></progress><span id="zf-progress-detail"></span></div>
        <p id="zf-message" role="status" hidden></p>
      </div>
      <form class="zf-composer zc-prompt-card">
        <strong>Generate video</strong>
        <div class="zc-composer-attachments">
          ${['first','last'].map(id=>`<div class="zf-frame-slot"><button type="button" class="zc-attachment" data-frame="${id}" aria-label="Choose ${id} frame">${icons.image}<span>${id==='first'?'First frame':'Last frame · optional'}</span></button><button type="button" class="zf-remove-frame" id="zf-remove-${id}" aria-label="Remove ${id} frame" title="Remove ${id} frame" hidden><svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8"/></svg></button><input id="zf-${id}" type="file" accept="image/png,image/jpeg,image/webp" hidden/></div>`).join('')}
          <button type="button" id="zf-swap" class="zc-tool" aria-label="Swap first and last frames" title="Swap first and last frames" hidden><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h16m-4-4 4 4-4 4M20 16H4m4-4-4 4 4 4"/></svg></button>
          <div class="zf-frame-slot" id="zf-audio-slot" hidden><button type="button" id="zf-audio-file-button" class="zc-attachment">${icons.audio}<span>Add audio reference</span></button><button type="button" class="zf-remove-frame" id="zf-remove-audio" aria-label="Remove audio reference" title="Remove audio reference" hidden><svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8"/></svg></button><input id="zf-audio-file" type="file" accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg" hidden/></div>
        </div>
        <label for="zf-prompt" class="zc-sr-only">Describe your video</label><textarea id="zf-prompt" placeholder="Describe the movement, camera and action…" maxlength="12000" required></textarea>
        <div class="zc-prompt-bottom"><div class="zc-prompt-tools"><div class="zc-tool-group" role="group" aria-label="Model and workflow">
          <label class="zc-tool zc-model-control zf-model">${icons.model}<span class="zc-sr-only">Video model</span><select id="zf-engine" aria-label="Video model">${ENDPOINT_RECIPES.map(m=>`<option value="${m.id}">${m.label}</option>`).join('')}</select>${icons.chevron}</label>
          </div><div class="zc-tool-group" role="group" aria-label="Video size and length"><details class="zc-tool-popup"><summary aria-label="Output resolution">${icons.size}<span id="zf-size-label">1344 × 768</span>${icons.chevron}</summary>
            <div class="zc-tool-panel"><strong>Output resolution</strong>
              <label class="zf-presets" for="zf-size-preset">Shape<select id="zf-size-preset">${FRAME_SIZE_PRESETS.map(p=>`<option value="${p.id}">${p.label}</option>`).join('')}<option value="custom">Custom dimensions</option></select></label>
              <label class="zf-presets" id="zf-megapixels-setting" for="zf-megapixels">Megapixels<select id="zf-megapixels">${FRAME_MEGAPIXELS.map(mp=>`<option value="${mp}" ${mp===1?'selected':''}>${mp} MP</option>`).join('')}</select></label>
              <div class="zf-dimensions" id="zf-custom-size"><label>Width (px)<input id="zf-width" type="number" min="256" max="1536" step="32" value="1344"/></label><label>Height (px)<input id="zf-height" type="number" min="256" max="1536" step="32" value="768"/></label></div>
              <p id="zf-size-hint">Dimensions follow H3’s 32-pixel grid. Megapixel sizes are approximate.</p><p>Both frames scale proportionally to fill the output, then crop centrally. No stretching.</p><p id="zf-canvas-note"></p>
            </div>
          </details>
          <label class="zc-tool zc-model-control">${icons.clock}<span class="zc-sr-only">Clip length</span><select id="zf-length" aria-label="Clip length">${FRAME_LENGTHS.map(n=>`<option value="${n}" ${n===73?'selected':''}>${(n/24).toFixed(2)}s</option>`).join('')}</select>${icons.chevron}</label>
          </div><label class="zc-tool zf-audio-switch"><input type="checkbox" id="zf-audio-enabled" role="switch"/>Audio reference</label>
          <details class="zc-tool-popup"><summary aria-label="Advanced generation settings">${icons.settings}</summary><div class="zc-tool-panel"><label>Sampling steps<input type="number" id="zf-steps" min="4" max="40" value="8"/></label><p id="zf-recipe-hint"></p><label>Seed<input id="zf-seed" type="number" min="0" max="9007199254740991" value="42"/></label><label class="zf-check"><input type="checkbox" id="zf-random" checked/>New variation</label><div id="zf-setup"></div><button id="zf-refresh" type="button">Refresh installed models</button></div></details><details id="zf-model-downloads" class="zc-tool-popup gs-model-help"></details>
        </div><div class="zc-prompt-submit"><button id="zf-generate" class="gs-primary" type="submit" aria-describedby="zf-note" disabled>Generate video</button></div></div>
        <p id="zf-note" aria-live="polite">Add a first frame to begin. The last frame is optional.</p>
      </form>`;
    owner.root.append(this.page);
    this.modelDownloads=new StudioModelDownloads(this.$('model-downloads'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.loadModels());
    this.loras=new LTXLoras(this.page.querySelector('.zc-prompt-tools'),(path,body)=>this.fetch(path,body),()=>this.busy(),()=>({h3:'h3',ltx:'ltx25'})[this.$('engine').value]||null,true);
    // Wan 2.2 has separate high and low models; never share one phase's
    // adapter with the other without an explicit selection.
    this.wanHighLoras=new LTXLoras(this.page.querySelector('.zc-prompt-tools'),(path,body)=>this.fetch(path,body),()=>this.busy(),()=>this.$('engine').value==='wan'?'wan22_high':null,true,'High-noise LoRAs');
    this.wanLowLoras=new LTXLoras(this.page.querySelector('.zc-prompt-tools'),(path,body)=>this.fetch(path,body),()=>this.busy(),()=>this.$('engine').value==='wan'?'wan22_low':null,true,'Low-noise LoRAs');
    for(const control of [this.loras,this.wanHighLoras,this.wanLowLoras])control.onchange=()=>this.save();
    this.previewZoom=new PreviewZoom(this.page.querySelector('.zf-viewer'),()=>!this.$('result').hidden?this.$('result'):!this.$('image-slot').hidden?this.$('image-slot').querySelector('img'):null);
    const draft=saved.draft||{};this.$('engine').value=endpointRecipe(draft.engine).id;this.setLengths(draft.length);this.$('steps').value=this.recipe().defaultSteps;
    this.loras.setValue(draft.custom_loras);
    this.wanHighLoras.setValue(draft.wan_high_loras);this.wanLowLoras.setValue(draft.wan_low_loras);
    for(const id of ['prompt','width','height','length','steps','seed'])if(draft[id]!==undefined)this.$(id).value=draft[id];
    this.normaliseDimensions();
    const width=Number(this.$('width').value),height=Number(this.$('height').value);
    this.$('size-preset').value=FRAME_SIZE_PRESETS.some(p=>p.id===draft.sizePreset)?draft.sizePreset:draft.sizePreset==='custom'?'custom':FRAME_SIZE_PRESETS.find(p=>p.width===width&&p.height===height||FRAME_MEGAPIXELS.some(mp=>{const s=endpointPresetSize(this.recipe().id,p.id,mp);return s.width===width&&s.height===height;}))?.id||'custom';
    this.$('megapixels').value=Number(draft.megapixels)>=.25&&Number(draft.megapixels)<=1?draft.megapixels:FRAME_MEGAPIXELS.reduce((best,mp)=>Math.abs(mp-width*height/1e6)<Math.abs(best-width*height/1e6)?mp:best,1);
    this.$('audio-enabled').checked=this.recipe().supportsAudioReference&&draft.audioEnabled===true;this.$('random').checked=draft.random!==false;
    this.$('refresh').onclick=()=>this.loadModels();
    this.$('engine').onchange=()=>{const cap=this.recipe();for(const control of [this.loras,this.wanHighLoras,this.wanLowLoras])control.items.forEach(item=>{item.confirm_unknown=false;});this.$('steps').value=cap.defaultSteps;this.setLengths(cap.defaultFrames);if(!cap.supportsAudioReference)this.$('audio-enabled').checked=false;this.normaliseDimensions();this.selectAvailability();this.save();this.render();};
    this.$('clear').onclick=()=>{this.items=[];this.renderHistory();this.$('result').pause();this.$('result').hidden=true;this.$('result').removeAttribute('src');this.preview();this.save();};
    this.page.querySelector('form').onsubmit=e=>{e.preventDefault();this.generate();};
    for(const id of ['prompt','width','height','length','steps','seed','audio-enabled','random'])for(const event of ['input','change'])this.$(id).addEventListener(event,()=>{if(id==='width'||id==='height')this.normaliseDimensions();this.save();this.render();});
    const applySize=()=>{
      const preset=FRAME_SIZE_PRESETS.find(p=>p.id===this.$('size-preset').value);
      if(preset){const size=endpointPresetSize(this.$('engine').value,preset.id,this.$('megapixels').value);this.$('width').value=size.width;this.$('height').value=size.height;this.dimensionNotice='';}
      this.save();this.render();
    };
    this.$('size-preset').onchange=applySize;this.$('megapixels').onchange=applySize;
    megapixelSlider(this.$('megapixels'));
    for(const key of ['width','height'])editableDimension(this.$(key),()=>{this.$('size-preset').value='custom';this.normaliseDimensions();this.save();this.render();},()=>({step:this.recipe().dimensionStep,min:this.recipe().minDimension||256,max:this.recipe().maxDimension||1536}));
    for(const id of ['first','last']){
      const button=this.page.querySelector(`[data-frame="${id}"]`);button.onclick=()=>this.$(id).click();
      this.$(id).onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)this.upload(id,file);};
      button.ondragover=e=>{e.preventDefault();e.stopPropagation();};button.ondrop=e=>{e.preventDefault();e.stopPropagation();if(e.dataTransfer?.files?.[0])this.upload(id,e.dataTransfer.files[0]);};
      button.onfocus=()=>this.pasteTarget=id;
      this.$('remove-'+id).onclick=()=>this.removeFrame(id);
    }
    this.$('swap').onclick=()=>{if(this.busy())return;[this.assets.first,this.assets.last]=[this.assets.last,this.assets.first];this.save();this.render();this.$('result').pause();this.$('result').hidden=true;this.preview();};
    this.$('remove-audio').onclick=()=>{if(this.busy())return;delete this.assets.audio;this.$('audio-enabled').checked=false;this.$('audio-file').value='';this.save();this.render();this.$('audio-enabled').focus({preventScroll:true});};
    this.$('audio-file-button').onclick=()=>this.$('audio-file').click();this.$('audio-file').onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)this.upload('audio',file);};
    this.$('cancel').onclick=()=>this.cancel();
    this.page.addEventListener('keydown',e=>{if(e.key==='Escape')for(const d of this.page.querySelectorAll('details'))if(d.open){d.open=false;d.querySelector('summary').focus({preventScroll:true});e.stopPropagation();}});
    this.page.addEventListener('toggle',e=>{if(e.target.tagName==='DETAILS'&&e.target.open)for(const d of this.page.querySelectorAll('details'))if(d!==e.target&&!d.contains(e.target))d.open=false;},true);
    this.api.addEventListener?.('progress',e=>{const d=e.detail;if(!this.job||d?.prompt_id!==this.job.id||!Number.isFinite(d.value)||!(d.max>0))return;const node=d.node||this.job.currentNode||'sample',sampling=node==='sample'||node.endsWith('_sample'),label=this.job.stages?.[node]||(sampling?'Generating video':'Processing video');this.$('bar').value=Math.max(0,Math.min(100,100*d.value/d.max));this.$('progress-title').textContent=`${label} · ${sampling?'Step':'Progress'} ${d.value} of ${d.max}`;this.$('progress-detail').textContent=sampling?this.elapsed(d.value,d.max):this.elapsed();});
    this.api.addEventListener?.('executing',e=>{const d=e.detail;if(!this.job||d?.prompt_id!==this.job.id||!d.node)return;this.job.currentNode=d.node;this.sampleStarted=null;this.$('bar').removeAttribute('value');this.$('progress-title').textContent=this.job.stages?.[d.node]||({text:'Loading text encoder',endpoints:'Reading first and last frames',audio_ref:'Loading audio reference',audio_guide:'Encoding audio reference',model:`Loading ${endpointRecipe(this.job.config.engine).label}`,turbo:'Preparing Turbo adapter',sample:'Generating video',decode:'Decoding video',decode_audio:'Decoding audio',save:'Saving video'})[d.node]||'Preparing video';});
    this.render();this.renderHistory();this.preview();
  }
  $(id){return this.page.querySelector('#zf-'+id);}
  recipe(){return endpointRecipe(this.$('engine').value);}
  build(c=this.config()){return endpointRecipe(c.engine).build(c);}
  setLengths(preferred){const cap=this.recipe(),values=endpointLengths(cap.id);this.$('length').innerHTML=values.map(n=>`<option value="${n}">${(n/cap.fps).toFixed(2)}s</option>`).join('');this.$('length').value=values.includes(Number(preferred))?preferred:cap.defaultFrames;}
  selectAvailability(){if(this.modelInfo)this.availability=this.recipe().availability(this.modelInfo,this.config());this.modelDownloads?.setMissingContext(`${this.recipe().id}_first_last`,this.availability?.missing);}
  normaliseDimensions(){
    let changed=false;this.dimensionNotice='';const cap=this.recipe();
    for(const id of ['width','height']){const input=this.$(id),value=Number(input.value);input.step=cap.dimensionStep;input.min=cap.minDimension||256;input.max=cap.maxDimension||1536;if(Number.isFinite(value)&&value>=Number(input.min)&&value<=Number(input.max)&&value%cap.dimensionStep!==0){input.value=Math.round(value/cap.dimensionStep)*cap.dimensionStep;changed=true;}}
    if(changed)this.dimensionNotice=`Adjusted to ${this.$('width').value} × ${this.$('height').value} on ${cap.label}’s ${cap.dimensionStep}-pixel grid.`;
  }
  config(){return {engine:this.$('engine').value,first:this.assets.first,last:this.assets.last,audio:this.assets.audio,audioEnabled:this.$('audio-enabled').checked,prompt:this.$('prompt').value,width:Number(this.$('width').value),height:Number(this.$('height').value),sizePreset:this.$('size-preset').value,megapixels:Number(this.$('megapixels').value),frames:Number(this.$('length').value),steps:Number(''+this.$('steps').value),seed:Number(this.$('seed').value),random:this.$('random').checked,custom_loras:this.loras.value(),wan_high_loras:this.wanHighLoras.value(),wan_low_loras:this.wanLowLoras.value()};}
  async patchLoras(graph,config){if(config.engine==='wan'){graph=await this.wanHighLoras.patch(graph,config.wan_high_loras||[]);return this.wanLowLoras.patch(graph,config.wan_low_loras||[]);}return this.loras.patch(graph,config.custom_loras||[]);}
  save(){const c=this.config();try{localStorage.setItem(KEY,JSON.stringify({assets:this.assets,draft:{...c,length:c.frames},job:this.job,items:this.items}));}catch{this.message('Browser storage is full. Outputs still save in ComfyUI/output/zura/first_last.');}}
  busy(){return !!(this.job||this.submitting||this.uploading);}
  message(text){this.$('message').hidden=!text;this.$('message').textContent=text;}
  async fetch(path,body){return this.owner.fetch(path,body);}
  async loadModels(){
    if(this.loading)return;this.loading=true;this.modelError='';this.render();
    try{const types=[...new Set(ENDPOINT_RECIPES.flatMap(r=>r.nodeTypes))],parts=await Promise.allSettled(types.map(t=>this.fetch('/object_info/'+t)));const available=parts.filter(p=>p.status==='fulfilled').map(p=>p.value);if(!available.length)throw new Error('ComfyUI did not return model information.');this.modelInfo=Object.assign({},...available);this.selectAvailability();}
    catch(e){this.modelError='Could not check installed models. Open generation settings and refresh installed models.';this.message(e.message);}finally{this.loading=false;this.render();}
  }
  open(){attachWorkspaceSamplePreview(this);if(!this.availability)this.loadModels();if(this.job)this.startPolling();}
  removeFrame(slot){
    if(this.busy())return;
    delete this.assets[slot];this.pasteTarget=slot;this.save();this.render();
    this.$('result').pause();this.$('result').hidden=true;this.preview();
    this.page.querySelector(`[data-frame="${slot}"]`).focus({preventScroll:true});
  }
  async upload(slot,file){
    if(this.busy())return;
    if(slot!=='audio'&&!/^image\/(png|jpeg|webp)$/.test(file.type)&&! /\.(png|jpe?g|webp)$/i.test(file.name)){this.message('Choose a PNG, JPG or WebP image.');return;}
    if(file.size>512*1024**2){this.message('Use a file smaller than 512 MB.');return;}
    this.uploading=true;this.message('Uploading '+file.name+'…');this.render();
    try{const data=new FormData();data.append('image',file);data.append('subfolder','zura_frames');data.append('overwrite','false');const response=await this.api.fetchApi('/upload/image',{method:'POST',body:data,timeoutMs:300000});if(!response.ok)throw new Error('Upload failed. Please choose the file again.');const uploaded=await response.json();this.assets[slot]={file:[uploaded.subfolder,uploaded.name].filter(Boolean).join('/'),filename:uploaded.name,subfolder:uploaded.subfolder||'',name:file.name};this.save();this.message('');if(slot!=='audio'){this.$('result').pause();this.$('result').hidden=true;this.preview(slot);}}
    catch(e){this.message(e.message);}finally{this.uploading=false;this.render();}
  }
  async paste(event){const item=Array.from(event.clipboardData?.items||[]).find(i=>i.kind==='file'&&i.type.startsWith('image/'));if(!item)return;event.preventDefault();event.stopPropagation();const file=item.getAsFile();if(file)await this.upload(this.pasteTarget||(!this.assets.first?'first':'last'),file);}
  preview(slot='first'){
    if(!this.$('result').hidden)return;const asset=this.assets[slot]||this.assets.first||this.assets.last;
    this.$('image-slot').hidden=!asset;this.$('empty').hidden=!!asset;if(asset){let image=this.$('image-slot').querySelector('img');if(!image){image=document.createElement('img');image.alt='Selected endpoint';this.$('image-slot').append(image);}image.src=view(this.api,asset,'input');}
    this.previewZoom?.update(asset?.file||'');
  }
  render(){
    const busy=this.busy(),c=this.config(),cap=this.recipe();let error='';try{this.build(c);}catch(e){error=e.message;}
    for(const id of ['engine','prompt','width','height','size-preset','megapixels','length','steps','seed','audio-enabled','random','swap','clear'])this.$(id).disabled=busy;
    this.loras.root.hidden=c.engine==='wan';this.wanHighLoras.root.hidden=c.engine!=='wan';this.wanLowLoras.root.hidden=c.engine!=='wan';for(const control of [this.loras,this.wanHighLoras,this.wanLowLoras])control.setBusy(busy);
    this.$('steps').min=cap.minSteps;this.$('steps').max=cap.maxSteps;this.$('steps').disabled=busy||cap.minSteps===cap.maxSteps;this.$('recipe-hint').textContent=cap.hint;
    this.$('audio-enabled').closest('label').hidden=!cap.supportsAudioReference;
    for(const slot of ['first','last']){const button=this.page.querySelector(`[data-frame="${slot}"]`),asset=this.assets[slot],remove=this.$('remove-'+slot);button.disabled=busy;remove.disabled=busy;remove.hidden=!asset;let image=button.querySelector('img');if(asset){if(!image){image=document.createElement('img');image.alt='';button.prepend(image);}image.src=view(this.api,asset,'input');button.title=`${slot==='first'?'First':'Last'} frame · ${asset.name||asset.filename}`;}else {image?.remove();button.title=`Choose ${slot} frame`;}button.classList.toggle('has-media',!!asset);}
    this.$('audio-slot').hidden=!cap.supportsAudioReference||(!c.audioEnabled&&!this.assets.audio);this.$('audio-file-button').disabled=busy;this.$('remove-audio').hidden=!this.assets.audio;this.$('remove-audio').disabled=busy;this.$('audio-file-button').querySelector('span').textContent=this.assets.audio?.name||'Add audio reference';
    this.$('swap').hidden=!this.assets.first||!this.assets.last;
    this.page.querySelector('[data-frame="last"] span').textContent=this.assets.last?'Last frame':'Last frame · optional';
    this.$('custom-size').hidden=c.sizePreset!=='custom';
    this.$('megapixels-setting').hidden=c.sizePreset==='custom';
    this.$('size-hint').textContent=c.sizePreset==='custom'?`Enter exact dimensions. Values snap to the nearest ${cap.dimensionStep} pixels (${cap.minDimension||256}–${cap.maxDimension||1536} per side).`:`Megapixel sizes are approximate, aligned to ${cap.label}’s ${cap.dimensionStep}-pixel grid.`;
    this.$('generate').disabled=busy||!this.availability?.ready||!!error;this.$('generate').textContent=busy?'Generating…':'Generate video';this.$('progress').hidden=!this.job&&!this.submitting;this.$('cancel').disabled=!this.job;
    this.$('size-label').textContent=`${c.width} × ${c.height}`;
    this.$('canvas-note').textContent=`${c.width} × ${c.height} · ${(c.width*c.height/1e6).toFixed(2)} MP`;
    this.$('setup').textContent=this.availability?.ready?'All required models and nodes are installed.':this.availability?'Missing: '+this.availability.missing.join(', '):'Open this workflow to check installed models.';
    const setup=this.loading?`Checking installed ${cap.label} models…`:this.modelError||(!this.availability?`Open this workflow to check installed ${cap.label} models.`:!this.availability.ready?`${cap.label} setup is incomplete. Open generation settings to see missing models.`:'');
    this.$('note').textContent=error||setup||this.dimensionNotice||`${c.frames} frames at ${cap.fps} fps · ${c.last?.file?'First + last frame':'First frame only'} · ${c.audioEnabled?'Follows your audio reference':cap.generatesAudio?`${cap.label} generates audio`:'Silent video'}`;
    const longClip=c.frames/cap.fps>5;
    if(!error&&!setup&&!this.dimensionNotice&&longClip)this.$('note').textContent=`${(c.frames/cap.fps).toFixed(2)}s · ${c.frames} frames at ${cap.fps} fps. Longer clips use more memory; try 0.25 MP first on a 16 GB GPU.`;
    this.$('note').hidden=!error&&!setup&&!this.dimensionNotice&&!longClip;
  }
  renderHistory(){this.$('takes').innerHTML=this.items.map((item,i)=>`<button type="button" data-take="${i}">${escape(item.config.prompt.slice(0,60))} · ${(item.config.frames/24).toFixed(2)}s</button>`).join('');this.$('takes').onclick=e=>{const button=e.target.closest('[data-take]');if(button)this.showResult(this.items[Number(button.dataset.take)].file);};if(this.items[0])this.showResult(this.items[0].file);}
  showResult(file){this.nativeSamplePreview?.clear();this.$('empty').hidden=true;this.$('image-slot').hidden=true;this.$('result').hidden=false;this.$('result').src=view(this.api,file);this.previewZoom?.update(this.$('result').src);this.$('history').open=false;}
  elapsed(step,max){const elapsed=Math.floor((Date.now()-this.job.started)/1000);const sampleElapsed=this.sampleStarted?(Date.now()-this.sampleStarted)/1000:0;if(!this.sampleStarted&&step)this.sampleStarted=Date.now();return step>1&&sampleElapsed>0?`About ${Math.ceil(sampleElapsed/(step-1)*(max-step))}s left in sampling · ${elapsed}s elapsed`:`${elapsed}s elapsed`;}
  async generate(){if(['width','height'].some(k=>this.$(k).commitDimension?.()===false)){this.message('Enter a whole number for width and height.');return;}
    if(this.busy())return;this.submitting=true;this.message('');this.render();
    try{if(!this.availability?.ready)throw new Error(`Install the required ${this.recipe().label} models and refresh.`);const config=this.config();if(config.random)config.seed=crypto.getRandomValues(new Uint32Array(1))[0];const graph=await this.patchLoras(this.build(config),config),previewMethod=await nativePreviewMethod(this.api,config.engine);const response=await this.fetch('/prompt',{prompt:graph,client_id:this.api.clientId,extra_data:{zura_first_last:true,preview_method:previewMethod}});if(!response.prompt_id)throw new Error('ComfyUI did not confirm this run. Check the queue before retrying.');this.job={id:response.prompt_id,started:Date.now(),config,previewMethod,stages:Object.fromEntries(Object.entries(graph).map(([id,node])=>[id,node._meta?.title]).filter(([,title])=>title))};this.sampleStarted=null;this.save();this.startPolling();}
    catch(e){this.message(e.message);}finally{this.submitting=false;this.render();}
  }
  startPolling(){if(this.timer)return;this.timer=setInterval(()=>this.poll(),1500);this.poll();}
  async poll(){
    if(!this.job||this.polling)return;const job=this.job;this.polling=true;
    try{const history=await this.fetch('/history/'+encodeURIComponent(job.id)),entry=history[job.id];if(this.job!==job)return;if(this.connectionLost){this.message('');this.connectionLost=false;}
      if(entry?.status?.completed||entry?.status?.status_str==='error'){
        const files=entry.outputs?.save?.images||[];for(const file of files)this.items.unshift({file,config:job.config});this.items=this.items.slice(0,12);this.job=null;this.nativeSamplePreview?.clear();this.stopPolling();this.save();this.renderHistory();this.render();if(!files.length)this.message(entry.status.messages?.find(m=>m[0]==='execution_error')?.[1]?.exception_message||'Generation stopped. Your previous takes are safe.');
      }else{const queue=await this.fetch('/queue');if(this.job!==job)return;const running=queue.queue_running.some(r=>r[1]===job.id),pending=queue.queue_pending.some(r=>r[1]===job.id);if(!running&&!pending){const again=await this.fetch('/history/'+encodeURIComponent(job.id));if(this.job!==job)return;if(again[job.id])return;this.job=null;this.nativeSamplePreview?.clear();this.stopPolling();this.save();this.message('This run is no longer in ComfyUI’s queue. It has not been resubmitted.');this.render();}else this.$('progress-detail').textContent=running?this.elapsed():'Waiting for other ComfyUI jobs';}
    }catch{this.connectionLost=true;this.message('Connection interrupted. Reconnecting to your saved run…');}finally{this.polling=false;}
  }
  async cancel(){if(!this.job)return;try{const id=this.job.id;await this.fetch('/queue',{delete:[id]});await this.fetch('/interrupt',{prompt_id:id});this.message('Cancellation requested.');await this.poll();}catch(e){this.message(e.message);}}
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  close(){this.save();this.stopPolling();this.previewZoom?.dispose();this.nativeSamplePreview?.dispose();this.nativeSamplePreview=null;this.modelDownloads?.dispose();}
  async graph(){try{const config=this.job?.config||this.config(),graph=await this.patchLoras(this.build(config),config),original=(this.app.rootGraph||this.app.graph)?.serialize?.();if(!original||typeof this.app.loadApiJson!=='function')throw new Error('Update ComfyUI to open this editable graph.');try{await this.app.loadApiJson(graph,`Zura ${endpointRecipe(config.engine).label} First and Last Frame · ${Date.now()}.json`);await import('./vendor/elk.bundled.js');await tidyArtistGraph(this.app,graph,'first_last',window.ELK);}catch(e){await this.app.loadGraphData(original);throw e;}this.studio.close();}catch(e){this.message(e.message);}}
}

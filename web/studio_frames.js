import {installOwnedExecuting} from './studio_progress.js';
import {submitOwnedGraph,recoverOwnedSubmission,cancelOwnedJob} from './studio_owned_jobs.js';
import {megapixelSlider,editableDimension} from './studio_resolution.js';
import {FRAME_LENGTHS,FRAME_SIZE_PRESETS,FRAME_MEGAPIXELS} from './frame_video_recipes.js';
import {composerIcons as icons} from './studio_composer.js';
import {tidyArtistGraph} from './artist_graph.js';
import {ENDPOINT_RECIPES,endpointRecipe,endpointLengths,endpointPresetSize} from './video_recipe_catalog.js';
import {attachWorkspaceSamplePreview,nativePreviewMethod} from './studio_live_preview.js';
import {PreviewZoom} from './studio_preview_zoom.js';
import {LTXLoras} from './studio_ltx_loras.js';
import {LTX_FRAME_VIDEO_FAST_NODES} from './ltx_frame_video_recipes.js';
import {StudioModelDownloads} from './studio_model_download.js';
import {LTXHDRDelivery} from './studio_ltx_delivery.js';
import {LTXHDREndpoints,hasHDREndpoint} from './studio_ltx_hdr_endpoints.js';
const KEY='zura-first-last-v1';
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const view=(api,file,type='output')=>api.apiURL('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type}));
export class FrameVideoWorkspace{
  constructor(owner){
    this.owner=owner;this.api=owner.api;this.app=owner.app;this.studio=owner.studio;
    let saved={};try{saved=JSON.parse(localStorage.getItem(KEY))||{};}catch{}
    this.nativeHDR=new LTXHDREndpoints(this.api,(path,body)=>this.fetch(path,body));
    this.assets=saved.assets||{};this.job=saved.job||null;this.pendingSubmission=saved.pendingSubmission||null;this.items=Array.isArray(saved.items)?saved.items.slice(0,12):[];
    if(this.job?.cancelPending)this.job.cancelRetryAvailable=true;
    this.page=document.createElement('section');this.page.className='zf-page';
    this.page.innerHTML=`
      <div class="zf-heading">
        <h2>First & last frame</h2>
        <button type="button" id="zf-convert-hdr" class="zc-tool" hidden>Convert result to HDR</button>
        <span id="zf-hdr-downloads" hidden></span>
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
          </div><label class="zc-tool zc-model-control" id="zf-output-control" hidden title="HDR adds an LTX conversion pass after generation. The SDR take is retained."><span class="zc-sr-only">Output format</span><select id="zf-output" aria-label="LTX output format"><option value="sdr">SDR</option><option value="hlg_video">HDR · HLG video</option><option value="hlg_and_exr">HDR · HLG + EXR</option><option value="acescg_exr">HDR · EXR</option></select>${icons.chevron}</label><label class="zc-tool zf-audio-switch"><input type="checkbox" id="zf-audio-enabled" role="switch"/>Audio reference</label><label class="zc-tool zf-audio-switch" id="zf-fast-control" hidden title="Processes at a smaller size then upscales. May lose fine detail; timing varies by clip."><input type="checkbox" id="zf-fast" role="switch" aria-describedby="zf-fast-hint"/>Fast · preview</label><span id="zf-fast-hint" class="zc-sr-only">Processes at a smaller size then upscales. May lose fine detail; timing varies by clip.</span>
          <details class="zc-tool-popup"><summary aria-label="Advanced generation settings">${icons.settings}</summary><div class="zc-tool-panel"><label>Sampling steps<input type="number" id="zf-steps" min="4" max="40" value="8"/></label><p id="zf-recipe-hint"></p><label>Seed<input id="zf-seed" type="number" min="0" max="9007199254740991" value="42"/></label><label class="zf-check"><input type="checkbox" id="zf-random" checked/>New variation</label><div id="zf-setup"></div><button id="zf-refresh" type="button">Refresh installed models</button></div></details><details id="zf-model-downloads" class="zc-tool-popup gs-model-help"></details>
        </div><div class="zc-prompt-submit"><button id="zf-generate" class="gs-primary" type="submit" aria-describedby="zf-note" disabled>Generate video</button></div></div>
        <p id="zf-note" aria-live="polite">Add a first frame to begin. The last frame is optional.</p>
      </form>`;
    owner.root.append(this.page);
    this.hdrOutput=new LTXHDRDelivery(this.api,{key:'zura-first-last-hdr',onSetup:info=>{this.hdrSetup=info;this.selectAvailability();if(!info.ready)this.$('model-downloads').open=true;},onUpdate:job=>this.hdrUpdate(job),onComplete:take=>{
      if(!this.items.some(item=>item.file.filename===take.file.filename&&item.file.subfolder===take.file.subfolder))this.items.unshift(take);
      this.items=this.items.slice(0,12);this.save();this.renderHistory();
    }});
    this.modelDownloads=new StudioModelDownloads(this.$('model-downloads'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.refreshSetup());
    this.loras=new LTXLoras(this.page.querySelector('.zc-prompt-tools'),(path,body)=>this.fetch(path,body),()=>this.busy(),()=>({h3:'h3',ltx:'ltx25'})[this.$('engine').value]||null,true);
    // Wan 2.2 has separate high and low models; never share one phase's
    // adapter with the other without an explicit selection.
    this.wanHighLoras=new LTXLoras(this.page.querySelector('.zc-prompt-tools'),(path,body)=>this.fetch(path,body),()=>this.busy(),()=>this.$('engine').value==='wan'?'wan22_high':null,true,'High-noise LoRAs');
    this.wanLowLoras=new LTXLoras(this.page.querySelector('.zc-prompt-tools'),(path,body)=>this.fetch(path,body),()=>this.busy(),()=>this.$('engine').value==='wan'?'wan22_low':null,true,'Low-noise LoRAs');
    for(const control of [this.loras,this.wanHighLoras,this.wanLowLoras])control.onchange=()=>this.save();
    this.previewZoom=new PreviewZoom(this.page.querySelector('.zf-viewer'),()=>!this.$('result').hidden?this.$('result'):!this.$('image-slot').hidden?this.$('image-slot').querySelector('img'):null);
    const draft=saved.draft||{};this.$('engine').value=endpointRecipe(draft.engine).id;this.setLengths(draft.length);this.$('steps').value=this.recipe().defaultSteps;
    this.$('output').value=['sdr','hlg_video','hlg_and_exr','acescg_exr'].includes(draft.hdrOutput)?draft.hdrOutput:'sdr';
    this.loras.setValue(draft.custom_loras);
    this.wanHighLoras.setValue(draft.wan_high_loras);this.wanLowLoras.setValue(draft.wan_low_loras);
    for(const id of ['prompt','width','height','length','steps','seed'])if(draft[id]!==undefined)this.$(id).value=draft[id];
    this.normaliseDimensions();
    const width=Number(this.$('width').value),height=Number(this.$('height').value);
    this.$('size-preset').value=FRAME_SIZE_PRESETS.some(p=>p.id===draft.sizePreset)?draft.sizePreset:draft.sizePreset==='custom'?'custom':FRAME_SIZE_PRESETS.find(p=>p.width===width&&p.height===height||FRAME_MEGAPIXELS.some(mp=>{const s=endpointPresetSize(this.recipe().id,p.id,mp);return s.width===width&&s.height===height;}))?.id||'custom';
    this.$('megapixels').value=Number(draft.megapixels)>=.25&&Number(draft.megapixels)<=1?draft.megapixels:FRAME_MEGAPIXELS.reduce((best,mp)=>Math.abs(mp-width*height/1e6)<Math.abs(best-width*height/1e6)?mp:best,1);
    this.$('fast').checked=draft.fastLtx===true||draft.fast===true;this.$('audio-enabled').checked=this.recipe().supportsAudioReference&&draft.audioEnabled===true;this.$('random').checked=draft.random!==false;
    this.$('refresh').onclick=()=>this.refreshSetup();
    this.$('convert-hdr').onclick=()=>this.owner.openHDR();
    this.$('engine').onchange=()=>{const cap=this.recipe();for(const control of [this.loras,this.wanHighLoras,this.wanLowLoras])control.items.forEach(item=>{item.confirm_unknown=false;});this.$('steps').value=cap.defaultSteps;this.setLengths(cap.defaultFrames);if(!cap.supportsAudioReference)this.$('audio-enabled').checked=false;this.normaliseDimensions();this.selectAvailability();this.save();this.render();};
    this.$('clear').onclick=()=>{this.items=[];this.selectedResult=null;this.showHDRDownloads([]);this.$('convert-hdr').hidden=true;this.renderHistory();this.$('result').pause();this.$('result').hidden=true;this.$('result').removeAttribute('src');this.preview();this.save();};
    this.page.querySelector('form').onsubmit=e=>{e.preventDefault();this.generate();};
    for(const id of ['prompt','width','height','length','steps','seed','audio-enabled','random','output','fast'])for(const event of ['input','change'])this.$(id).addEventListener(event,()=>{if(id==='width'||id==='height')this.normaliseDimensions();if(id==='output'||id==='fast')this.selectAvailability();this.save();this.render();});
    const applySize=()=>{
      const preset=FRAME_SIZE_PRESETS.find(p=>p.id===this.$('size-preset').value);
      if(preset){const size=endpointPresetSize(this.$('engine').value,preset.id,this.$('megapixels').value);this.$('width').value=size.width;this.$('height').value=size.height;this.dimensionNotice='';}
      this.normaliseDimensions();this.save();this.render();
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
    this.$('swap').onclick=()=>{if(this.busy())return;[this.assets.first,this.assets.last]=[this.assets.last,this.assets.first];this.selectAvailability();this.save();this.render();this.$('result').pause();this.$('result').hidden=true;this.preview();};
    this.$('remove-audio').onclick=()=>{if(this.busy())return;delete this.assets.audio;this.$('audio-enabled').checked=false;this.$('audio-file').value='';this.save();this.render();this.$('audio-enabled').focus({preventScroll:true});};
    this.$('audio-file-button').onclick=()=>this.$('audio-file').click();this.$('audio-file').onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)this.upload('audio',file);};
    this.$('cancel').onclick=()=>this.cancel();
    this.page.addEventListener('keydown',e=>{if(e.key==='Escape')for(const d of this.page.querySelectorAll('details'))if(d.open){d.open=false;d.querySelector('summary').focus({preventScroll:true});e.stopPropagation();}});
    this.page.addEventListener('toggle',e=>{if(e.target.tagName==='DETAILS'&&e.target.open)for(const d of this.page.querySelectorAll('details'))if(d!==e.target&&!d.contains(e.target))d.open=false;},true);
    this.api.addEventListener?.('progress',e=>{const d=e.detail;if(this.hdrOutput?.busy){this.hdrProgress(d);return;}if(!this.job||this.job.cancelPending||d?.prompt_id!==this.job.id||!Number.isFinite(d.value)||!(d.max>0))return;const node=d.node||this.job.currentNode||'sample',sampling=node==='sample'||node.endsWith('_sample')||/^sample\d+$/.test(node),label=this.job.stages?.[node]||(sampling?'Generating video':'Processing video');this.$('bar').value=Math.max(0,Math.min(100,100*d.value/d.max));this.$('progress-title').textContent=`${label} · ${sampling?'Step':'Progress'} ${d.value} of ${d.max}`;this.$('progress-detail').textContent=sampling?this.elapsed(d.value,d.max):this.elapsed();});
    installOwnedExecuting(this.api,e=>{const d=e.detail;if(this.hdrOutput?.busy){this.hdrProgress(d);return;}if(!this.job||this.job.cancelPending||d?.prompt_id!==this.job.id||!d.node)return;this.job.currentNode=d.node;this.sampleStarted=null;this.$('bar').removeAttribute('value');this.$('progress-title').textContent=this.job.stages?.[d.node]||({text:'Loading text encoder',endpoints:'Reading first and last frames',audio_ref:'Loading audio reference',audio_guide:'Encoding audio reference',model:`Loading ${endpointRecipe(this.job.config.engine).label}`,turbo:'Preparing Turbo adapter',sample:'Generating video',upscale_model:'Loading spatial upscaler',upscale:'Upscaling video',crop_output:'Fitting video',decode:'Decoding video',decode_audio:'Decoding audio',save:'Saving video'})[d.node]||'Preparing video';});
    this.render();this.renderHistory();this.preview();
  }
  $(id){return this.page.querySelector('#zf-'+id);}
  recipe(){const cap=endpointRecipe(this.$('engine').value);return cap.id==='ltx'&&hasHDREndpoint(this.assets)?{...cap,dimensionStep:64,minDimension:512,maxDimension:2048,maxPixels:2048**2,hint:'Native HDR · INT8 · two sampling passes · full float32 VAE'}:cap;}
  build(c=this.config()){if(hasHDREndpoint(c)){this.nativeHDR.validate(c);return {};}return endpointRecipe(c.engine).build(c);}
  async buildGraph(c){return hasHDREndpoint(c)?this.nativeHDR.graph(c):this.patchLoras(this.build(c),c);}
  setLengths(preferred){const cap=this.recipe(),values=endpointLengths(cap.id);this.$('length').innerHTML=values.map(n=>`<option value="${n}">${(n/cap.fps).toFixed(2)}s</option>`).join('');this.$('length').value=values.includes(Number(preferred))?preferred:cap.defaultFrames;}
  selectAvailability(){if(hasHDREndpoint(this.assets)){const info=this.nativeHDR.info;this.availability={ready:!!(info?.enabled&&info.ready),missing:[...(info?.files||[]).filter(f=>!f.ready).map(f=>f.filename),...(info?.missingNodes||[])]};this.modelDownloads?.setContext(info);return;}const config=this.config();if(this.modelInfo)this.availability=this.recipe().availability(this.modelInfo,config);let missing=this.availability?.missing;if(config.engine==='ltx'&&config.hdrOutput!=='sdr'&&this.hdrSetup){missing=[...new Set([...(missing||[]),...(this.hdrSetup.files||[]).filter(file=>!file.ready).map(file=>file.filename),...(this.hdrSetup.missingNodes||[])])];}this.modelDownloads?.setMissingContext(`${this.recipe().id}_first_last`,missing);}
  normaliseDimensions(){
    let changed=false;this.dimensionNotice='';const cap=this.recipe();
    for(const id of ['width','height']){const input=this.$(id),value=Number(input.value);input.step=cap.dimensionStep;input.min=cap.minDimension||256;input.max=cap.maxDimension||1536;if(Number.isFinite(value)&&value>=Number(input.min)&&value<=Number(input.max)&&value%cap.dimensionStep!==0){input.value=Math.round(value/cap.dimensionStep)*cap.dimensionStep;changed=true;}}
    if(changed)this.dimensionNotice=`Adjusted to ${this.$('width').value} × ${this.$('height').value} on ${cap.label}’s ${cap.dimensionStep}-pixel grid.`;
  }
  config(){return {fast:this.$('engine').value==='ltx'&&!hasHDREndpoint(this.assets)&&this.$('fast').checked,engine:this.$('engine').value,first:this.assets.first,last:this.assets.last,audio:this.assets.audio,audioEnabled:this.$('audio-enabled').checked,prompt:this.$('prompt').value,width:Number(this.$('width').value),height:Number(this.$('height').value),sizePreset:this.$('size-preset').value,megapixels:Number(this.$('megapixels').value),frames:Number(this.$('length').value),steps:Number(''+this.$('steps').value),seed:Number(this.$('seed').value),random:this.$('random').checked,hdrOutput:this.$('engine').value==='ltx'?this.$('output').value:'sdr',custom_loras:this.loras.value(),wan_high_loras:this.wanHighLoras.value(),wan_low_loras:this.wanLowLoras.value()};}
  async patchLoras(graph,config){if(config.engine==='wan'){graph=await this.wanHighLoras.patch(graph,config.wan_high_loras||[]);return this.wanLowLoras.patch(graph,config.wan_low_loras||[]);}return this.loras.patch(graph,config.custom_loras||[]);}
  save(){const c=this.config();try{localStorage.setItem(KEY,JSON.stringify({assets:this.assets,draft:{...c,fastLtx:this.$('fast').checked,length:c.frames},job:this.job,pendingSubmission:this.pendingSubmission,items:this.items}));return true;}catch{this.message('Browser storage is full. Outputs still save in ComfyUI/output/zura/first_last.');return false;}}
  busy(){return !!(this.job||this.pendingSubmission||this.submitting||this.uploading||this.hdrOutput?.busy);}
  message(text){this.$('message').hidden=!text;this.$('message').textContent=text;}
  async fetch(path,body){return this.owner.fetch(path,body);}
  async refreshSetup(){await this.loadModels();const config=this.config();if(this.hdrSetup&&config.engine==='ltx'&&config.hdrOutput!=='sdr'&&!hasHDREndpoint(config)){try{await this.hdrOutput.preflight(config);}catch{ /* Setup panel reports missing files or connectivity. */ }}}
  async loadModels(){
    if(this.loading)return;this.loading=true;this.modelError='';this.render();
    try{await this.nativeHDR.refresh();const types=[...new Set([...ENDPOINT_RECIPES.flatMap(r=>r.nodeTypes),...LTX_FRAME_VIDEO_FAST_NODES])],parts=await Promise.allSettled(types.map(t=>this.fetch('/object_info/'+t)));const available=parts.filter(p=>p.status==='fulfilled').map(p=>p.value);if(!available.length)throw new Error('ComfyUI did not return model information.');this.modelInfo=Object.assign({},...available);this.selectAvailability();}
    catch(e){this.modelError='Could not check installed models. Open generation settings and refresh installed models.';this.message(e.message);}finally{this.loading=false;this.render();}
  }
  open(){this.modelDownloads?.resume();this.hdrOutput.resume();attachWorkspaceSamplePreview(this);if(!this.availability)this.loadModels();if(this.job||this.pendingSubmission)this.startPolling();}
  removeFrame(slot){
    if(this.busy())return;
    delete this.assets[slot];this.pasteTarget=slot;this.selectAvailability();this.save();this.render();
    this.$('result').pause();this.$('result').hidden=true;this.preview();
    this.page.querySelector(`[data-frame="${slot}"]`).focus({preventScroll:true});
  }
  async upload(slot,file){
    if(this.busy())return;
    const exr=slot!=='audio'&&/\.exr$/i.test(file.name);
    if(exr&&this.$('engine').value!=='ltx'){this.message('Select LTX 2.5 to use EXR endpoint images.');return;}
    if(slot!=='audio'&&!exr&&!/^image\/(png|jpeg|webp)$/.test(file.type)&&! /\.(png|jpe?g|webp)$/i.test(file.name)){this.message('Choose a PNG, JPG or WebP image, or an EXR for LTX HDR.');return;}
    if(file.size>512*1024**2){this.message('Use a file smaller than 512 MB.');return;}
    this.uploading=true;this.message('Uploading '+file.name+'…');this.render();
    try{if(exr){this.assets[slot]=await this.nativeHDR.upload(file);this.$('output').value='hlg_and_exr';this.normaliseDimensions();this.selectAvailability();this.save();this.message('EXR loaded. The preview is SDR; native HDR uses the original EXR.');this.$('result').pause();this.$('result').hidden=true;this.preview(slot);return;}const data=new FormData();data.append('image',file);data.append('subfolder','zura_frames');data.append('overwrite','false');const response=await this.api.fetchApi('/upload/image',{method:'POST',body:data,timeoutMs:300000});if(!response.ok)throw new Error('Upload failed. Please choose the file again.');const uploaded=await response.json();this.assets[slot]={file:[uploaded.subfolder,uploaded.name].filter(Boolean).join('/'),filename:uploaded.name,subfolder:uploaded.subfolder||'',name:file.name};this.selectAvailability();this.save();this.message('');if(slot!=='audio'){this.$('result').pause();this.$('result').hidden=true;this.preview(slot);}}
    catch(e){this.message(e.message);}finally{this.uploading=false;this.render();}
  }
  async paste(event){const item=Array.from(event.clipboardData?.items||[]).find(i=>i.kind==='file'&&i.type.startsWith('image/'));if(!item)return;event.preventDefault();event.stopPropagation();const file=item.getAsFile();if(file)await this.upload(this.pasteTarget||(!this.assets.first?'first':'last'),file);}
  preview(slot='first'){
    if(!this.$('result').hidden)return;this.$('convert-hdr').hidden=true;const asset=this.assets[slot]||this.assets.first||this.assets.last;
    this.$('image-slot').hidden=!asset;this.$('empty').hidden=!!asset;if(asset){let image=this.$('image-slot').querySelector('img');if(!image){image=document.createElement('img');image.alt='Selected endpoint';this.$('image-slot').append(image);}image.src=view(this.api,asset,'input');}
    this.previewZoom?.update(asset?.file||'');
  }
  render(){
    const busy=this.busy(),c=this.config(),cap=this.recipe();let error='';try{this.build(c);}catch(e){error=e.message;}
    for(const id of ['engine','prompt','width','height','size-preset','megapixels','length','steps','seed','audio-enabled','random','swap','clear','output','fast'])this.$(id).disabled=busy;
    this.loras.root.hidden=c.engine==='wan';this.wanHighLoras.root.hidden=c.engine!=='wan';this.wanLowLoras.root.hidden=c.engine!=='wan';for(const control of [this.loras,this.wanHighLoras,this.wanLowLoras])control.setBusy(busy);
    this.$('steps').min=cap.minSteps;this.$('steps').max=cap.maxSteps;this.$('steps').disabled=busy||cap.minSteps===cap.maxSteps;this.$('output').querySelector('option[value="sdr"]').disabled=hasHDREndpoint(c);this.$('output-control').title=hasHDREndpoint(c)?'Native HDR generation from your original EXR endpoints.':'HDR adds an LTX conversion pass after generation. The SDR take is retained.';this.$('recipe-hint').textContent=cap.hint;
    this.$('audio-enabled').closest('label').hidden=!cap.supportsAudioReference;this.$('output-control').hidden=c.engine!=='ltx';this.$('fast-control').hidden=c.engine!=='ltx'||hasHDREndpoint(c);
    for(const slot of ['first','last']){this.$(slot).accept=c.engine==='ltx'&&this.nativeHDR.info?.enabled?'image/png,image/jpeg,image/webp,.exr':'image/png,image/jpeg,image/webp';const button=this.page.querySelector(`[data-frame="${slot}"]`),asset=this.assets[slot],remove=this.$('remove-'+slot);button.disabled=busy;remove.disabled=busy;remove.hidden=!asset;let image=button.querySelector('img');if(asset){if(!image){image=document.createElement('img');image.alt='';button.prepend(image);}image.src=view(this.api,asset,'input');button.title=`${slot==='first'?'First':'Last'} frame · ${asset.name||asset.filename}`;}else {image?.remove();button.title=`Choose ${slot} frame`;}button.classList.toggle('has-media',!!asset);}
    this.$('audio-slot').hidden=!cap.supportsAudioReference||(!c.audioEnabled&&!this.assets.audio);this.$('audio-file-button').disabled=busy;this.$('remove-audio').hidden=!this.assets.audio;this.$('remove-audio').disabled=busy;this.$('audio-file-button').querySelector('span').textContent=this.assets.audio?.name||'Add audio reference';
    this.$('swap').hidden=!this.assets.first||!this.assets.last;
    this.page.querySelector('[data-frame="last"] span').textContent=this.assets.last?'Last frame':'Last frame · optional';
    this.$('custom-size').hidden=c.sizePreset!=='custom';
    this.$('megapixels-setting').hidden=c.sizePreset==='custom';
    this.$('size-hint').textContent=c.sizePreset==='custom'?`Enter exact dimensions. Values snap to the nearest ${cap.dimensionStep} pixels (${cap.minDimension||256}–${cap.maxDimension||1536} per side).`:`Megapixel sizes are approximate, aligned to ${cap.label}’s ${cap.dimensionStep}-pixel grid.`;
    this.$('generate').disabled=busy||!this.availability?.ready||!!error;this.$('generate').textContent=busy?'Generating…':'Generate video';this.$('progress').hidden=!this.job&&!this.pendingSubmission&&!this.submitting&&!this.hdrOutput.busy;this.$('cancel').disabled=(!this.job&&!this.hdrOutput.busy)||!!(this.job?.cancelPending&&!this.job.cancelRetryAvailable);this.$('cancel').textContent=this.job?.cancelRetryAvailable?'Retry cancellation':'Cancel run';if(this.job?.cancelPending){this.$('bar').removeAttribute('value');this.$('progress-title').textContent='Cancelling…';this.$('progress-detail').textContent='Waiting for ComfyUI to stop this run.';}else if(this.pendingSubmission){this.$('bar').removeAttribute('value');this.$('progress-title').textContent='Checking your run';this.$('progress-detail').textContent='Reconnecting without submitting again…';}
    this.$('size-label').textContent=`${c.width} × ${c.height}`;
    this.$('canvas-note').textContent=`${c.width} × ${c.height} · ${(c.width*c.height/1e6).toFixed(2)} MP`;
    this.$('setup').textContent=this.availability?.ready?'All required models and nodes are installed.':this.availability?'Missing: '+this.availability.missing.join(', '):'Open this workflow to check installed models.';
    const setup=this.loading?`Checking installed ${cap.label} models…`:this.modelError||(!this.availability?`Open this workflow to check installed ${cap.label} models.`:!this.availability.ready?`${cap.label} setup is incomplete. Open generation settings to see missing models.`:'');
    this.$('note').textContent=error||setup||this.dimensionNotice||`${c.frames} frames at ${cap.fps} fps · ${c.last?.file?'First + last frame':'First frame only'} · ${c.audioEnabled?'Follows your audio reference':cap.generatesAudio?`${cap.label} generates audio`:'Silent video'}`;
    const longClip=c.frames/cap.fps>5;
    if(!error&&!setup&&!this.dimensionNotice&&longClip)this.$('note').textContent=`${(c.frames/cap.fps).toFixed(2)}s · ${c.frames} frames at ${cap.fps} fps. Longer clips use more memory; try 0.25 MP first on a 16 GB GPU.`;
    if(!error&&!setup&&c.hdrOutput!=='sdr'){this.$('note').textContent+=hasHDREndpoint(c)?' \u00b7 Native HDR: two passes with an SDR viewing preview.':' · HDR adds a conversion pass; SDR is retained. Longer HDR delivery is a preview.';}this.$('note').hidden=!error&&!setup&&!this.dimensionNotice&&!longClip&&c.hdrOutput==='sdr';
  }
  renderHistory(){this.$('takes').innerHTML=this.items.map((item,i)=>`<button type="button" data-take="${i}">${escape(item.config.prompt.slice(0,60))} · ${(item.config.frames/24).toFixed(2)}s</button>`).join('');this.$('takes').onclick=e=>{const button=e.target.closest('[data-take]');if(button)this.showResult(this.items[Number(button.dataset.take)].file);};if(this.items[0])this.showResult(this.items[0].file);}
  showResult(file){this.selectedResult=file;const take=this.items.find(item=>item.file===file||item.file?.filename===file?.filename&&item.file?.subfolder===file?.subfolder&&item.file?.type===file?.type);const convert=this.$('convert-hdr');if(convert)convert.hidden=!!take?.hdrFiles||take?.config?.engine!=='ltx'||typeof this.owner.openHDR!=='function';this.showHDRDownloads?.(take?.hdrFiles||[]);this.nativeSamplePreview?.clear();this.$('empty').hidden=true;this.$('image-slot').hidden=true;this.$('result').hidden=false;this.$('result').src=view(this.api,file);this.previewZoom?.update(this.$('result').src);this.$('history').open=false;}
  elapsed(step,max){const elapsed=Math.floor((Date.now()-this.job.started)/1000);const sampleElapsed=this.sampleStarted?(Date.now()-this.sampleStarted)/1000:0;if(!this.sampleStarted&&step)this.sampleStarted=Date.now();return step>1&&sampleElapsed>0?`About ${Math.ceil(sampleElapsed/(step-1)*(max-step))}s left in sampling · ${elapsed}s elapsed`:`${elapsed}s elapsed`;}
  async generate(){if(['width','height'].some(k=>this.$(k).commitDimension?.()===false)){this.message('Enter a whole number for width and height.');return;}
    if(this.busy())return;this.submitting=true;const attempt={};this.submitAttempt=attempt;this.message('');this.render();
    try{if(!this.availability?.ready)throw new Error(`Install the required ${this.recipe().label} models and refresh.`);const config=this.config();if(!hasHDREndpoint(config))await this.hdrOutput.preflight(config);if(config.random)config.seed=crypto.getRandomValues(new Uint32Array(1))[0];const graph=await this.buildGraph(config),previewMethod=await nativePreviewMethod(this.api,config.engine);await submitOwnedGraph(this,graph,config,previewMethod,{zura_first_last:true});}
    catch(e){this.message(e.message);}finally{if(this.submitAttempt===attempt){this.submitting=false;this.submitAttempt=null;this.render();}}
  }
  showHDRDownloads(files){
    const host=this.$('hdr-downloads');host.replaceChildren();host.hidden=!files.length;
    for(const file of files){const link=document.createElement('a');link.className='zc-tool';link.href=view(this.api,file);link.download=file.filename;link.textContent=file.filename.endsWith('.zip')?'Download EXRs':'Download HDR video';host.append(link);}
  }
  hdrUpdate(job){
    const same=job.active_prompt_id&&job.active_prompt_id===this.hdrPrompt&&job.state===this.hdrState;
    this.hdrPrompt=job.active_prompt_id||null;this.hdrState=job.state;
    this.render();
    if(['complete','failed','cancelled','unknown'].includes(job.state)){
      this.message(job.state==='complete'?'HDR delivery complete. The on-screen preview is SDR; download the HDR master or EXRs.':job.error||'HDR conversion cancelled. Your SDR take is retained.');return;
    }
    if(same&&this.hdrNode)return;
    this.hdrNode=null;this.$('bar').removeAttribute('value');
    const section=Number.isInteger(job.total)&&job.total>0?` · section ${Math.min(job.completed+1,job.total)} of ${job.total}`:'';
    this.$('progress-title').textContent=job.state==='reconnecting'?'Reconnecting to HDR delivery':job.state==='cancelling'?'Cancelling HDR delivery':job.state==='cancel-error'?'Cancellation failed · try again':job.state==='exporting'?'Saving HDR video and EXRs':'Converting to HDR'+section;
    this.$('progress-detail').textContent=job.error||'Additional LTX pass · the original SDR take is retained.';
  }
  hdrProgress(data){
    if(data?.prompt_id!==this.hdrOutput.activePrompt)return;
    if(data.node)this.hdrNode=data.node;
    const sampling=['sample1','sample2','hdr_sample'].includes(this.hdrNode);
    const label=this.hdrNode?.includes('decode')?'Decoding HDR video':this.hdrNode?.includes('save')?'Saving HDR delivery':'Converting to HDR';
    this.$('progress-title').textContent=label;
    if(Number.isFinite(data.value)&&data.max>0){this.$('bar').value=100*data.value/data.max;this.$('progress-detail').textContent=`${sampling?'Step':'Progress'} ${data.value} of ${data.max} · HDR conversion pass`;}
    else this.$('bar').removeAttribute('value');
  }
  startPolling(){if(this.timer)return;this.timer=setInterval(()=>this.poll(),1500);this.poll();}
  async poll(){
    if(this.pendingSubmission&&!this.job)return recoverOwnedSubmission(this);
    if(!this.job||this.polling)return;const job=this.job;this.polling=true;
    try{const history=await this.fetch('/history/'+encodeURIComponent(job.id)),entry=history[job.id];if(this.job!==job)return;if(this.connectionLost){this.message('');this.connectionLost=false;}
      if(entry?.status?.completed||entry?.status?.status_str==='error'){
        const native=hasHDREndpoint(job.config),failed=entry.status.status_str==='error',files=failed?[]:(native?entry.outputs?.save_preview:entry.outputs?.save)?.images||[],hdrFiles=native?[...(entry.outputs?.zura_hdr_save_video?.images||[]),...(entry.outputs?.zura_hdr_archive?.files||[])]:[];for(const file of files)this.items.unshift({file,config:job.config,...(native?{hdrFiles,nativeHDR:true}:{})});this.items=this.items.slice(0,12);this.job=null;this.nativeSamplePreview?.clear();this.stopPolling();this.save();this.renderHistory();this.render();if(!files.length)this.message(entry.status.messages?.find(m=>m[0]==='execution_error')?.[1]?.exception_message||(job.cancelPending?'Run cancelled. Your previous takes are safe.':'Generation stopped. Your previous takes are safe.'));else if(native)this.message('Native HDR generation complete. The on-screen preview is SDR; download the HDR master or EXRs.');else if(job.cancelPending)this.message('Video finished before cancellation. Your take is saved.');else if(job.config.engine==='ltx'&&job.config.hdrOutput&&job.config.hdrOutput!=='sdr')await this.hdrOutput.start({file:files[0],config:job.config});
      }else{const queue=await this.fetch('/queue');if(this.job!==job)return;const running=queue.queue_running.some(r=>r[1]===job.id),pending=queue.queue_pending.some(r=>r[1]===job.id);if(!running&&!pending){const again=await this.fetch('/history/'+encodeURIComponent(job.id));if(this.job!==job)return;if(again[job.id])return;this.job=null;this.nativeSamplePreview?.clear();this.stopPolling();this.save();this.message(job.cancelPending?'Run cancelled. Your previous takes are safe.':'This run is no longer in ComfyUI’s queue. It has not been resubmitted.');this.render();}else if(job.cancelPending){this.$('progress-title').textContent='Cancelling…';this.$('progress-detail').textContent='Waiting for ComfyUI to stop this run.';}else this.$('progress-detail').textContent=running?this.elapsed():'Waiting for other ComfyUI jobs';}
    }catch{this.connectionLost=true;this.message('Connection interrupted. Reconnecting to your saved run…');}finally{this.polling=false;}
  }
  async cancel(){if(this.hdrOutput?.busy){await this.hdrOutput.cancel();return;}await cancelOwnedJob(this);}
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  close(){this.save();this.stopPolling();this.hdrOutput?.close();this.previewZoom?.stopDraw();this.nativeSamplePreview?.dispose();this.nativeSamplePreview=null;this.modelDownloads?.close();}
  async graph(){try{const config=this.job?.config||this.config(),graph=await this.buildGraph(config),original=(this.app.rootGraph||this.app.graph)?.serialize?.();if(!original||typeof this.app.loadApiJson!=='function')throw new Error('Update ComfyUI to open this editable graph.');try{await this.app.loadApiJson(graph,`Zura ${endpointRecipe(config.engine).label} First and Last Frame · ${Date.now()}.json`);await import('./vendor/elk.bundled.js');await tidyArtistGraph(this.app,graph,'first_last',window.ELK);}catch(e){await this.app.loadGraphData(original);throw e;}this.studio.close();}catch(e){this.message(e.message);}}
}

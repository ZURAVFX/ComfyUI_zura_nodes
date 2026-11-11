import {frameSourceResolution} from './frame_source_resolution.js';
import {resolutionSize} from './studio_resolution.js';
import {tidyArtistGraph} from './artist_graph.js';
import {openPanoramaEditor} from './studio_panorama_editor.js';
import {ClipTrimmer} from './studio_trim.js';
import {installOwnedExecuting} from './studio_progress.js';
import {submitOwnedGraph,recoverOwnedSubmission,cancelOwnedJob} from './studio_owned_jobs.js';
import {StudioModelDownloads} from './studio_model_download.js';
const KEY='zura-panorama-camera-v1';
const CAMERA_SIZE={dimensionStep:32,minDimension:256,maxDimension:4096,maxPixels:8_388_608};
// SaveVideo returns native Windows separators; the validated API uses URL paths.
const mediaRef=file=>file?{...file,subfolder:(file.subfolder||'').replaceAll('\\','/')}:file;
const view=file=>'/view?'+new URLSearchParams({filename:file.filename,subfolder:mediaRef(file).subfolder,type:file.type||'output'});
const sourceView=asset=>{
  if(asset.preview_url||asset.url)return asset.preview_url||asset.url;
  const path=String(asset.file||'').replaceAll('\\','/'),slash=path.lastIndexOf('/');
  return path?view({filename:path.slice(slash+1),subfolder:slash<0?'':path.slice(0,slash),type:'input'}):'';
};

/** A camera workspace in the existing shell, using native Panorama UI and H3. */
export class PanoramaCameraWorkspace{
  constructor(owner){
    this.owner=owner;this.app=owner.app;this.api=owner.api;this.studio=owner.studio;
    let saved={};try{saved=JSON.parse(localStorage.getItem(KEY))||{};}catch{}
    this.state=saved.state||{};this.state.geometryMode='temporal_scene';if(this.state.cameraRecipe!=='temporal-scene-ltx25-v1'){for(const key of ['geometry','camera','cameraReviewed','warp','selection','guidePreview','opening','look','result'])delete this.state[key];}this.state.cameraRecipe='temporal-scene-ltx25-v1';this.job=saved.job||null;this.pendingSubmission=saved.pendingSubmission||null;
    this.page=document.createElement('section');this.page.className='zpc-page';
    this.page.innerHTML=`<header class="zpc-heading"><div><strong>Change camera angle</strong><span data-steps>1 Source · 2 Camera · 3 Preview · 4 Render</span></div><button type="button" data-new>New shot</button></header>
      <div class="zpc-viewer"><div data-empty><h2>Find a new angle.</h2><p>Import a clip, then position the camera.</p></div><video data-result controls playsinline preload="metadata" hidden></video><span class="zpc-media-label" data-media-label hidden></span>
      <div class="zpc-progress" data-progress hidden><div><strong data-progress-title>Preparing</strong><button type="button" data-cancel>Cancel run</button></div><progress data-bar max="100" aria-label="Camera shot processing progress"></progress><span data-progress-detail role="status"></span></div></div>
      <form class="zpc-composer zc-prompt-card"><div class="zpc-title"><strong data-title>Prepare your camera shot</strong><button type="button" data-edit hidden>Edit camera</button></div>
      <div class="zpc-attachments"><button type="button" data-source>Add source video</button><button type="button" data-look>Look image · optional</button><button type="button" data-create-look hidden>Create look image</button><button type="button" data-remove-look aria-label="Remove look image" hidden>×</button><button type="button" data-original hidden>View original</button><button type="button" data-warp hidden>View camera guide</button><a data-download hidden download>Download take</a></div>
      <input data-source-file type="file" accept="video/*,.mov,.mkv" hidden><input data-look-file type="file" accept="image/png,image/jpeg,image/webp" hidden>
      <label class="zc-sr-only" for="zpc-prompt">Camera shot direction</label><textarea id="zpc-prompt" data-prompt placeholder="Describe the shot or lighting. The 3D editor controls the camera angle…" maxlength="12000"></textarea>
      <div class="zc-prompt-bottom"><div class="zc-prompt-tools"><span class="zpc-model zc-tool" title="Shared scene + LTX 2.5 · 8 steps">LTX 2.5 · Camera</span>
      <label class="zpc-geometry-mode" hidden><select data-geometry-mode><option value="temporal_scene">Shared scene</option></select></label>
      <details class="zc-tool-popup zpc-resolution"><summary data-size-label>Resolution</summary><div class="zc-tool-panel"><label>Aspect ratio<select data-size><option value="source">Source aspect ratio</option><option value="landscape">Landscape · 16:9</option><option value="portrait">Portrait · 9:16</option><option value="square">Square · 1:1</option><option value="custom">Custom dimensions</option></select></label><label data-mp-control>Megapixels <output data-mp-value></output><input data-megapixels type="range" min="0.25" max="8.35" step="0.01" aria-label="Camera output megapixels"/></label><button type="button" data-source-size>Use source dimensions</button><div data-dimensions hidden><label>Width<input type="text" inputmode="numeric" data-width></label><label>Height<input type="text" inputmode="numeric" data-height></label></div><label class="zpc-two-stage"><input data-two-stage type="checkbox"/>Two-stage upscale</label><p data-size-note></p><small>Up to 8.39 MP. Higher resolutions need more memory. Source proportions are retained.</small></div></details>
      <details class="zc-tool-popup zpc-trim"><summary data-length>Trim footage</summary><div class="zc-tool-panel"><div data-timeline></div><p>Up to 5 seconds in this preview. Original timing and audio are retained.</p></div></details>
      </div><button class="zpc-primary" type="submit" data-generate>Prepare geometry</button></div><p data-message role="status" hidden></p></form>`;
    owner.root.append(this.page);
    this.page.querySelector('.zpc-viewer').after(this.$('progress'));
    const setup=document.createElement('details');setup.className='zc-tool-popup';
    this.page.querySelector('.zc-prompt-tools').append(setup);
    this.modelDownloads=new StudioModelDownloads(setup,(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.refreshSetup());
    this.modelDownloads.mountQuick(this.page.querySelector('.zpc-composer'));
    const refresh=document.createElement('button');refresh.type='button';refresh.textContent='Check setup';
    refresh.onclick=()=>this.refreshSetup();this.page.querySelector('.zc-prompt-tools').append(refresh);
    this.$('prompt').value=this.state.prompt||'';this.$('geometry-mode').value=this.state.geometryMode;this.$('two-stage').checked=!!this.state.config?.two_stage;
    this.$('size').value=['source','landscape','portrait','square','custom'].includes(this.state.size)?this.state.size:this.state.size?'custom':'source';this.$('megapixels').value=this.state.megapixels||1;this.state.sourceSize??=!this.state.size;const legacySize=String(this.state.size||'').split(',').map(Number);if(legacySize.length===2&&legacySize.every(n=>n>0)){this.state.width=legacySize[0];this.state.height=legacySize[1];}this.$('width').value=this.state.width||1920;this.$('height').value=this.state.height||1080;
    this.trimmer=new ClipTrimmer(this.$('timeline'),{onCommit:range=>{this.state.config={...this.config(),...range};this.invalidate();},onSeek:time=>{this.showMedia('source');this.$('result').currentTime=time;}});
    this.$('source').onclick=()=>this.$('source-file').click();this.$('look').onclick=()=>this.$('look-file').click();
    this.$('source-file').onchange=e=>this.upload('source',e.target.files[0]);this.$('look-file').onchange=e=>this.upload('look',e.target.files[0]);
    this.$('remove-look').onclick=()=>{delete this.state.look;delete this.state.result;this.save();this.render();};
    this.$('create-look').onclick=()=>this.createLook();this.$('edit').onclick=()=>this.editCamera();this.$('original').onclick=()=>this.showMedia('source');this.$('warp').onclick=()=>this.showMedia('warp');
    this.$('cancel').onclick=()=>cancelOwnedJob(this);
    this.$('new').onclick=()=>{if(this.busy())return;this.reset();};
    this.$('size').onchange=()=>{this.state.sourceSize=false;this.invalidate();};
    this.$('megapixels').oninput=()=>{if(this.busy())return;this.state.megapixels=Number(this.$('megapixels').value);this.state.sourceSize=false;this.invalidate();};
    this.$('source-size').onclick=()=>{if(this.busy()||!this.state.source)return;this.$('size').value='source';this.state.sourceSize=true;this.invalidate();};
    this.$('two-stage').onchange=()=>{this.state.config={...this.config(),two_stage:this.$('two-stage').checked};this.invalidate();};
    this.$('geometry-mode').onchange=()=>this.setGeometryMode(this.$('geometry-mode').value);
    for(const id of ['width','height']){this.$(id).onfocus=e=>e.target.select();this.$(id).onchange=()=>this.invalidate();}
    this.$('prompt').oninput=()=>{this.state.prompt=this.$('prompt').value;delete this.state.result;this.save();};
    this.page.querySelector('form').onsubmit=e=>{e.preventDefault();this.generate();};
    this.page.addEventListener('dragover',e=>{if(e.dataTransfer?.types?.includes('Files'))e.preventDefault();});
    this.page.addEventListener('drop',e=>{const file=e.dataTransfer?.files?.[0];if(file){e.preventDefault();this.upload(file.type.startsWith('image/')?'look':'source',file);}});
    this.disposeExecuting=installOwnedExecuting(this.api,e=>{const d=e.detail;if(d?.prompt_id!==this.job?.id)return;this.activeNode=d.node;this.sampleStart=null;this.$('bar').removeAttribute('value');this.$('progress-title').textContent=this.job.stages?.[d.node]||'Preparing camera shot';});
    this.progress=e=>{const d=e.detail;if(d?.prompt_id!==this.job?.id||!d.max)return;const now=Date.now();this.sampleStart??=now;this.$('bar').value=100*d.value/d.max;const eta=d.value>=2?Math.round((now-this.sampleStart)/1000/Math.max(1,d.value-1)*(d.max-d.value)):null;this.$('progress-detail').textContent=`${d.value} of ${d.max}${eta!==null?' · about '+eta+'s left in this step':''} · ${this.elapsed()}`;};
    this.api.addEventListener?.('progress',this.progress);
    this.render();if(this.state.result)this.showMedia('result');else if(this.state.warp)this.showMedia('warp');else if(this.state.source)this.showMedia('source');
  }
  $(id){return this.page.querySelector('[data-'+id+']');}
  fetch(path,body){return this.owner.fetch(path,body);}
  busy(){return !!(this.job||this.pendingSubmission||this.submitting||this.uploading||this.editor);}
  message(text){this.$('message').textContent=text||'';this.$('message').hidden=!text;}
  dimensions(){
    const preset=this.$('size').value,source=this.state.source;
    if(preset.includes(',')){const [width,height]=preset.split(',').map(Number);return{width,height};}
    if(preset==='custom'){const snap=value=>Math.max(256,Math.min(4096,Math.round(Number(value||256)/8)*8));return{width:snap(this.$('width').value),height:snap(this.$('height').value)};}
    if(preset==='source'&&source?.width&&source?.height){const size=frameSourceResolution(source,CAMERA_SIZE,this.state.sourceSize?null:Number(this.state.megapixels)||1);return{...size,width:Math.max(256,Math.ceil(size.outputWidth/8)*8),height:Math.max(256,Math.ceil(size.outputHeight/8)*8)};}
    return resolutionSize(({landscape:16/9,portrait:9/16,square:1})[preset]||16/9,Number(this.state.megapixels)||1,CAMERA_SIZE);
  }
  config(){const size=this.dimensions();return {start:0,duration:Math.min(2,this.state.source?.duration||2),...this.state.config,width:size.width,height:size.height,two_stage:!!this.$('two-stage')?.checked,geometry_mode:'temporal_scene'};}
  save(){try{localStorage.setItem(KEY,JSON.stringify({state:this.state,job:this.job,pendingSubmission:this.pendingSubmission}));return true;}catch{this.message('Browser storage is full. Clear old Studio history before starting a run.');return false;}}
  setGeometryMode(){this.state.geometryMode='temporal_scene';}
  invalidate(){if(this.busy())return;this.state.size=this.$('size').value;this.state.megapixels=Number(this.$('megapixels').value)||this.state.megapixels||1;this.state.width=this.$('width').value;this.state.height=this.$('height').value;delete this.state.geometry;delete this.state.camera;delete this.state.cameraReviewed;delete this.state.warp;delete this.state.result;delete this.state.selection;delete this.state.look;delete this.state.opening;delete this.state.sourceOpening;delete this.state.guidePreview;this.save();this.render();if(this.state.source)this.showMedia('source');}
  async open(){this.modelDownloads.resume();this.render();if(this.job||this.pendingSubmission)this.startPolling();await this.refreshSetup();}
  async refreshSetup(){
    try{
      this.status=await this.fetch('/zura/studio/panorama/status');
      if(Array.isArray(this.status.files)&&Array.isArray(this.status.missingNodes))this.modelDownloads.setContext(this.status);
      else this.modelDownloads.setMissingContext('panorama',this.status.missing||[]);
      this.message(this.status.errors?.length?'Panorama needs attention: '+this.status.errors.join(' '):this.status.ready?'':'Set up Change camera angle below, then check setup again.');
    }catch(error){this.status=null;this.message('Could not check camera setup. Restart ComfyUI and choose Check setup. '+error.message);}
    this.render();
  }
  async upload(slot,file){if(!file||this.busy())return;this.uploading=true;this.render();this.message('Loading '+file.name+'…');try{const form=new FormData();form.append('file',file);const r=await this.api.fetchApi('/zura/studio/upload?kind='+(slot==='source'?'video':'image'),{method:'POST',body:form,timeoutMs:null});const asset=await r.json();if(!r.ok)throw new Error(asset.error||'Upload failed.');this.state[slot]=asset;if(slot==='source'){this.state.config={start:0,duration:Math.min(2,asset.duration)};if(this.$('size').value==='source')this.state.sourceSize=true;delete this.state.geometry;delete this.state.camera;delete this.state.cameraReviewed;delete this.state.warp;delete this.state.result;delete this.state.selection;delete this.state.look;delete this.state.opening;delete this.state.sourceOpening;delete this.state.guidePreview;}else delete this.state.result;this.message('');this.save();if(slot==='source')this.showMedia('source');}catch(error){this.message(error.message);}finally{this.uploading=false;this.$(slot+'-file').value='';this.render();}}
  render(){
    const busy=this.busy(),s=this.state,stage=!s.geometry?'geometry':!s.warp?'warp':'render';
    this.$('source').textContent=s.source?.name||'Add source video';this.$('look').textContent=s.look?.name||'Look image · optional';this.$('remove-look').hidden=!s.look;
    this.$('title').textContent=stage==='geometry'?'Prepare your camera shot':stage==='warp'?'Adjust and preview the camera':'Render your new angle';
    this.$('steps').textContent=stage==='geometry'?'1 Source → 2 Camera → 3 Preview → 4 Render':stage==='warp'?'Source ready → Camera → Preview → Render':'Source ready → Camera ready → Guide ready → Render';
    this.$('generate').textContent=busy?'Working…':stage==='geometry'?'Prepare geometry':stage==='warp'?(s.cameraReviewed?'Preview camera':'Choose camera angle'):'Render new angle';
    this.$('generate').disabled=busy||!s.source||!this.status?.ready;
    this.$('create-look').hidden=!s.opening;this.$('create-look').disabled=busy;this.$('edit').hidden=!s.geometry;this.$('edit').disabled=busy;
    this.$('original').hidden=!s.source;this.$('warp').hidden=!s.warp;
    this.$('dimensions').hidden=this.$('size').value!=='custom';this.$('mp-control').hidden=this.$('size').value==='custom';const size=this.dimensions();this.$('size-label').textContent=`${size.width} × ${size.height}`;if(s.sourceSize&&this.$('size').value==='source'){s.megapixels=size.width*size.height/1e6;this.$('megapixels').value=s.megapixels;}this.$('mp-value').textContent=`${(size.width*size.height/1e6).toFixed(2)} MP`;this.$('size-note').textContent=`${size.width} × ${size.height} px${this.$('size').value==='source'?' · source aspect ratio':''}`;this.$('source-size').hidden=!s.source?.width;this.$('source-size').disabled=busy;
    this.$('download').hidden=!s.result;if(s.result)this.$('download').href=view(s.result);
    for(const id of ['source','look','remove-look','new','size','width','height','prompt','geometry-mode','megapixels','two-stage'])this.$(id).disabled=busy;
    this.trimmer.update(s.source,this.config(),{disabled:busy,maximum:5});
    this.$('length').textContent=s.source?`Trim · ${this.config().duration.toFixed(2)}s`:'Trim footage';
    this.$('progress').hidden=!this.job&&!this.pendingSubmission&&!this.submitting;
    if(this.pendingSubmission)this.$('progress-title').textContent='Checking your run';
  }
  async requestGraph(stage,state=this.state.camera){return this.fetch('/zura/studio/panorama/graph',{source_id:this.state.source?.id,config:this.config(),state,stage,warp:mediaRef(this.state.warp),look_id:this.state.look?.id,prompt:this.$('prompt').value,seed:1052});}
  async generate(){if(this.busy())return;const stage=!this.state.geometry?'geometry':!this.state.warp?'warp':'render';if(stage==='warp'&&!this.state.cameraReviewed){await this.editCamera();return;}this.submitting=true;this.render();this.message('');try{const prepared=await this.requestGraph(stage);this.state.selection=prepared.selection;this.state.camera=prepared.state;await submitOwnedGraph(this,prepared.graph,{stage,selection:prepared.selection,state:prepared.state},'auto',{zura_panorama:true});}catch(error){this.message(error.message);}finally{this.submitting=false;this.render();}}
  async editCamera(){if(this.busy()||!this.state.geometry)return;try{this.editor=await openPanoramaEditor({app:this.app,state:this.state.camera,geometryKey:this.state.selection.key,output:this.state.geometry,source:{url:sourceView(this.state.source),start:this.config().start,duration:this.config().duration,fps:this.state.selection?.fps||this.state.source?.fps||24,stillScene:false},onCancel:()=>{this.editor=null;this.render();},onError:error=>{this.editor=null;this.message(error.message);this.render();},onApply:async state=>{this.editor=null;this.state.camera=state;this.state.cameraReviewed=true;delete this.state.warp;delete this.state.result;delete this.state.opening;delete this.state.look;this.save();this.render();await this.generate();}});this.render();}catch(error){this.editor=null;this.message(error.message);this.render();}}
  showMedia(kind){const ref=this.state[kind];if(!ref)return;const video=this.$('result');video.pause();video.poster=kind==='source'?(ref.thumbnail_url||''):'';video.src=kind==='source'?sourceView(ref):view(ref);video.hidden=false;this.$('empty').hidden=true;this.$('media-label').hidden=false;this.$('media-label').textContent=kind==='source'?`Source · ${ref.name||'Imported clip'}`:kind==='result'?'Finished take':'Camera guide';this.viewing=kind;}
  elapsed(){return Math.floor((Date.now()-(this.job?.started||Date.now()))/1000)+'s elapsed';}
  startPolling(){if(!this.timer)this.timer=setInterval(()=>this.poll(),1500);this.poll();}
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  async poll(){if(this.pendingSubmission&&!this.job)return recoverOwnedSubmission(this);if(!this.job||this.polling)return;this.polling=true;const job=this.job;try{const history=await this.fetch('/history/'+encodeURIComponent(job.id)),entry=history[job.id];if(this.job!==job)return;
    if(entry?.status?.completed||entry?.status?.status_str==='error'){
      const failed=entry.status.status_str==='error',file=!failed&&entry.outputs?.save?.images?.find(f=>/\.(mp4|mov)$/i.test(f.filename));
      this.job=null;this.stopPolling();if(file){if(job.config.stage==='render'){this.state.result=file;this.showMedia('result');this.message('Finished. Compare with the source or camera guide, or download your take.');}else{this.state.selection=job.config.selection;this.state.camera=entry.outputs.scene?.zura_camera_state?.[0]||job.config.state;this.state.opening=entry.outputs.opening?.images?.[0];if(job.config.stage==='geometry'){this.state.sourceOpening=entry.outputs.source_opening_save?.images?.[0];this.state.geometry=entry.outputs.panorama;this.state.guidePreview=file;this.showMedia('guidePreview');this.message('Scene ready. Choose the camera angle, then add keyframes for movement.');}else{this.state.warp=file;this.showMedia('warp');this.message('Camera preview ready. Check the movement, then render with LTX 2.5.');}}}else this.message(entry.status.messages?.find(m=>m[0]==='execution_error')?.[1]?.exception_message||'Run stopped. Your source and previous result are retained.');this.save();this.render();
    }else{const queue=await this.fetch('/queue');if(this.job!==job)return;const active=[...(queue.queue_running||[]),...(queue.queue_pending||[])].some(r=>r[1]===job.id);if(!active){const again=await this.fetch('/history/'+encodeURIComponent(job.id));if(again[job.id])return;this.job=null;this.stopPolling();this.save();this.render();this.message(job.cancelPending?'Run cancelled.':'This run is no longer in the queue. It has not been resubmitted.');}else if(!this.activeNode)this.$('progress-detail').textContent=this.elapsed()+' · waiting for ComfyUI';}
    }catch{this.message('Connection interrupted. Reconnecting to your existing run…');}finally{this.polling=false;}}
  async createLook(){
    if(this.busy()||!this.state.opening)return;
    const owner=this.owner;if(owner.job||owner.pendingSubmission||owner.submitting||owner.uploading){this.message('Finish the current image run before editing this camera look.');return;}
    try{
      const refs=[];for(const [index,file]of [this.state.opening,this.state.sourceOpening].filter(Boolean).entries()){const r=await this.api.fetchApi(view(file));if(!r.ok)throw new Error('Camera image could not be read. Rebuild its preview.');refs.push(new File([await r.blob()],index?'Original identity.png':'New camera angle.png',{type:'image/png'}));}
      owner.imageOperation='edit';owner.show('image');if(!owner.models.length)await owner.loadModels();await owner.setImageOperation('edit',{useCanvas:false});
      const gpt=owner.models.find(m=>m.id==='chatgptedit'&&m.ready);if(gpt)owner.$('model').value=gpt.id;
      owner.references=[];owner.$('prompt').value='Fill the magenta holes in Image 1 naturally. Keep its exact camera angle and framing. Use Image 2 for the same person, clothing and room. Preserve identity and realistic detail. '+this.$('prompt').value;
      owner.$('width').value=this.config().width;owner.$('height').value=Math.ceil(this.config().height/16)*16;owner.$('shape').value=this.config().width>=this.config().height?'landscape':'portrait';await owner.uploadReferences(refs);if(owner.references.length!==refs.length)throw new Error('Choose an installed image editor, then add the camera references.');owner.save();owner.render();
      let use=owner.root.querySelector('#zpc-use-image');if(!use){use=document.createElement('button');use.id='zpc-use-image';use.type='button';use.className='zc-tool';owner.$('gallery').parentElement.prepend(use);}use.textContent='Use image for camera shot';
      use.onclick=async()=>{const selected=owner.items[owner.selectedImage||0]?.file;if(!selected){owner.message('Generate or select a finished image first.');return;}if(owner.job||owner.pendingSubmission||owner.submitting)return;try{const r=await this.api.fetchApi(view(selected));if(!r.ok)throw new Error('Image could not be read.');const file=new File([await r.blob()],'Camera look.png',{type:'image/png'});owner.show('panorama');await this.upload('look',file);use.remove();}catch(error){owner.message(error.message);}};
      owner.message('Optional camera look. Choose a local model or browser sign-in, generate, then use the image for your camera shot. The full video warp remains the motion guide.');
    }catch(error){this.message(error.message);}
  }
  reset(){if(this.busy())return false;this.state={geometryMode:'temporal_scene',cameraRecipe:'temporal-scene-ltx25-v1',sourceSize:true,megapixels:1};this.$('prompt').value='';this.$('size').value='source';this.$('megapixels').value=1;this.$('geometry-mode').value='temporal_scene';this.$('two-stage').checked=false;this.save();this.render();this.$('result').pause();this.$('result').removeAttribute('src');this.$('result').poster='';this.$('result').hidden=true;this.$('media-label').hidden=true;this.$('empty').hidden=false;this.message('');return true;}
  async graph(){try{const stage=this.state.warp?'render':this.state.geometry?'warp':'geometry',prepared=await this.requestGraph(stage),before=(this.app.rootGraph||this.app.graph)?.serialize?.();if(!before)throw new Error('Update ComfyUI to export an editable camera graph.');try{await this.app.loadApiJson(prepared.graph,'Zura Panorama Camera.json');await import('./vendor/elk.bundled.js');await tidyArtistGraph(this.app,prepared.graph,'camera',window.ELK);}catch(error){await this.app.loadGraphData(before);throw error;}this.studio.close();}catch(error){this.message(error.message);}}
  close(){this.modelDownloads?.close();this.editor?.cancel();this.editor=null;this.save();this.stopPolling();this.disposeExecuting?.();this.api.removeEventListener?.('progress',this.progress);}
}

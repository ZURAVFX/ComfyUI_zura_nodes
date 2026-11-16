import {BrushSizeControl} from './studio_brush_size.js';
import {playbackFile} from './studio_delivery_formats.js';
import {paintToolIcon,PAINT_SWATCHES as SWATCHES} from './studio_paint_toolbar.js';
import {workspaceStorage} from './studio_storage.js';
import {PaintoutMaskViewer} from './paintout_studio/paintout_viewer.js';
import {buildPaintVfxGraph,paintVfxAvailability,paintVfxValidation,PAINT_VFX_CAPABILITIES as caps} from './studio_paint_vfx_recipes.js';
import {StudioModelDownloads} from './studio_model_download.js';
import {submitOwnedGraph,recoverOwnedSubmission,cancelOwnedJob} from './studio_owned_jobs.js';
const KEY='zura-paint-vfx-v1';
const assetUrl=(api,file,type='input')=>api.apiURL('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||type}));
const blob=canvas=>new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(Error('Could not save the painted frame.')),'image/png'));
const clone=value=>JSON.parse(JSON.stringify(value));
export function paintVfxSlots(frames){const slots=[0];for(let frame=1;frame<=frames-8;frame+=8)slots.push(frame);if(slots.at(-1)!==frames-1)slots.push(frames-1);return slots;}
export class PaintVFXWorkspace{
  constructor(owner,{Viewer=PaintoutMaskViewer}={}){
    this.owner=owner;this.studio=owner.studio;this.app=owner.app;this.api=owner.api;this.independentAsset=true;this.storage=workspaceStorage(owner);this.Viewer=Viewer;this.epoch=0;this.admissionEpoch=0;this.active=false;this.revision=0;this.dirty=false;this.closed=false;
    let saved={};try{saved=JSON.parse(this.storage.getItem(KEY))||{};}catch{}
    this.state={width:512,height:512,frames:121,fps:24,prompt:'',seed:42,colour:'#ff6347',brush:48,background:'#000000',keys:[{frame:0},{frame:120}],...saved.state};
    if(!Array.isArray(this.state.keys)||!this.state.keys.length)this.state.keys=[{frame:0},{frame:this.state.frames-1}];
    this.selected=this.state.keys[0].frame;this.items=Array.isArray(saved.items)?saved.items.slice(0,12):[];this.result=this.items[0]||null;this.job=saved.job||null;this.pendingSubmission=saved.pendingSubmission||null;
    const doc=owner.root.ownerDocument;this.page=doc.createElement('section');this.page.className='zvfx-page';this.page.hidden=true;
    this.page.innerHTML=`<header class="zvfx-heading"><div><h2>Paint VFX</h2><p>Paint flat colours on the first and last frames. Generate smoke, fire, explosions or liquid.</p></div><div class="zvfx-header-actions"><details class="zvfx-background"><summary>${paintToolIcon('background')}<span>Background</span></summary><div class="zvfx-background-panel"><label>Colour <input type="color" data-vfx="background" aria-label="Background colour"></label><button type="button" data-vfx="add-background">Add background image</button><button type="button" data-vfx="remove-background">Remove background</button><input type="file" accept="image/png,image/jpeg,image/webp" data-vfx="background-file" hidden></div></details><button type="button" data-vfx="edit">Back to painting</button></div></header>
      <div class="zvfx-workbench"><nav class="zvfx-tools" aria-label="Painting tools">
        <div class="zvfx-tool-group" role="group" aria-label="Brush tools"><button type="button" data-tool="draw" aria-label="Paint" title="Paint colour on the frame" aria-pressed="true">${paintToolIcon('draw')}<span>Paint</span></button><button type="button" data-tool="protect" aria-label="Eraser" title="Erase painted strokes" aria-pressed="false">${paintToolIcon('protect')}<span>Eraser</span></button><button type="button" data-tool="pan" aria-label="Pan" title="Drag to pan the frame" aria-pressed="false">${paintToolIcon('pan')}<span>Pan</span></button></div>
        <div class="zvfx-brush-controls" role="group" aria-label="Brush size"><label for="zvfx-brush-size">Size</label><input id="zvfx-brush-size" type="range" min="1" max="500" data-vfx="brush" aria-label="Brush size"><label class="zvfx-brush-number"><input type="number" min="1" max="500" step="1" data-vfx="brush-number" aria-label="Brush size in pixels"><span>px</span></label><output data-vfx="brush-label" class="zvfx-sr-only"></output></div>
        <div class="zvfx-colour-controls"><span>Colour</span><div class="zvfx-swatches" role="group" aria-label="Paint colours">${SWATCHES.map(([colour,name])=>`<button type="button" data-vfx-swatch="${colour}" style="--paint-colour:${colour}" title="${name}" aria-label="${name}" aria-pressed="false"></button>`).join('')}</div><label class="zvfx-colour-picker" title="Choose any paint colour"><input type="color" data-vfx="colour" aria-label="Custom paint colour"><span>Custom</span></label></div>
        <div class="zvfx-history-tools" role="group" aria-label="Paint history and view"><button type="button" data-vfx="undo" aria-label="Undo" title="Undo the last stroke">${paintToolIcon('undo')}<span>Undo</span></button><button type="button" data-vfx="redo" aria-label="Redo" title="Redo the last undone stroke" hidden>${paintToolIcon('redo')}<span>Redo</span></button><button type="button" data-vfx="clear" aria-label="Clear paint" title="Clear paint on this frame">${paintToolIcon('clear')}<span>Clear</span></button><button type="button" data-vfx="fit" aria-label="Fit canvas" title="Fit the frame in the viewer">${paintToolIcon('fit')}<span>Fit</span></button></div>
      </nav><div class="zvfx-stage"><div class="zvfx-canvas" data-vfx="canvas"></div><video data-vfx="result" controls playsinline hidden></video><a data-vfx="download" class="zvfx-download" download hidden>Download video</a></div></div>
      <div class="zvfx-timeline"><div class="zvfx-keyframes" data-vfx="keys" role="group" aria-label="Painted keyframes"></div><div class="zvfx-frame-actions" role="group" aria-label="Add painted frame"><select data-vfx="key-frame" aria-label="Frame to add"></select><button type="button" data-vfx="add-key" title="Add a painted keyframe">${paintToolIcon('addFrame')}<span>Add frame</span></button></div><span data-vfx="key-status" role="status"></span></div>
      <div class="zvfx-progress" data-vfx="progress" hidden><strong data-vfx="progress-title"></strong><progress data-vfx="bar" aria-label="Paint VFX progress"></progress><span data-vfx="progress-detail"></span><button type="button" data-vfx="cancel">Cancel run</button></div>
      <form class="zvfx-composer"><label>Describe the effect<textarea data-vfx="prompt" rows="2" maxlength="12000" placeholder="An orange explosion expands into thick grey smoke…"></textarea></label><div class="zvfx-settings"><label class="zvfx-model">Model<select data-vfx="engine" aria-label="Paint VFX model"><option value="ltx_paint_vfx">LTX 2.5</option></select></label><details class="zvfx-settings-advanced"><summary>Settings</summary><div><label>Width<input data-vfx="width" type="number" min="256" max="1920" step="64"></label><label>Height<input data-vfx="height" type="number" min="256" max="1920" step="64"></label><label>Frames<input data-vfx="frames" type="number" min="9" max="321" step="8"></label><label>FPS<select data-vfx="fps"><option>24</option><option>25</option><option>50</option></select></label><label>Seed<input data-vfx="seed" type="number" min="0" step="1"></label></div></details><details class="zc-tool-popup" data-vfx="models"></details><button type="button" data-vfx="refresh">Check models</button><button type="submit" class="gs-primary" data-vfx="generate">Generate VFX</button></div><p data-vfx="readiness" role="status"></p><p data-vfx="message" role="status" aria-live="polite"></p><p class="zvfx-note">Painted controls are SDR sRGB. A background is a visual guide. Generated video may change it. Alpha extraction is a separate operation.</p></form><div class="zvfx-history" data-vfx="history" aria-label="Generated effects"></div>`;
    owner.root.append(this.page);const link=doc.createElement('link');link.rel='stylesheet';link.href=new URL('./studio_paint_vfx.css',import.meta.url).href;doc.head.append(link);
    this.modelDownloads=new StudioModelDownloads(this.$('models'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.refreshSetup());
    this.modelDownloads.mountQuick(this.page.querySelector('.zvfx-composer'));
    this.modelPicker=this.modelDownloads.attachPicker(this.$('engine'),{resolveOption:()=>({key:'ltx_paint_vfx',readyOverride:this.availability?.ready})});
    for(const id of ['width','height','frames','fps','seed','prompt','colour','background']){this.$(id).value=this.state[id];this.$(id).addEventListener(id==='prompt'?'input':'change',()=>void this.change(id));}
    this.$('brush').addEventListener('input',()=>this.setBrush(this.$('brush').value));this.brushControl=new BrushSizeControl(this.$('brush'),{number:this.$('brush-number')});
    this.$('colour').addEventListener('input',()=>void this.change('colour'));
    this.page.querySelectorAll('[data-vfx-swatch]').forEach(button=>button.onclick=()=>{if(this.busy())return;this.$('colour').value=button.dataset.vfxSwatch;void this.change('colour');});
    this.page.querySelectorAll('[data-tool]').forEach(button=>button.onclick=()=>{this.tool=button.dataset.tool;this.viewer?.setTool(this.tool);this.render();});
    this.$('edit').onclick=()=>{this.review=false;this.render();this.viewer?.resize();};
    this.$('undo').onclick=()=>{this.viewer?.undo();this.render();};this.$('redo').onclick=()=>{this.viewer?.redo?.();this.render();};this.$('clear').onclick=()=>this.viewer?.clear();this.$('fit').onclick=()=>this.viewer?.fit();
    this.$('add-background').onclick=()=>this.$('background-file').click();this.$('background-file').onchange=event=>void this.importBackground(event.target.files?.[0]);
    this.$('remove-background').onclick=()=>this.run(async()=>{await this.flushKey();this.state.backgroundImage=null;this.invalidateControls();await this.loadKey();});
    this.$('add-key').onclick=()=>this.run(async()=>{if(this.busy())return;await this.flushKey();const frame=Number(this.$('key-frame').value);if(this.state.keys.some(key=>key.frame===frame)||this.state.keys.length>=33)return;this.state.keys.push({frame});await this.selectKey(frame);});

    this.page.querySelector('form').onsubmit=event=>{event.preventDefault();void this.generate();};this.$('refresh').onclick=()=>this.run(async()=>{await this.refreshSetup();if(!this.viewer)await this.loadKey();});this.$('cancel').onclick=()=>cancelOwnedJob(this);
    this.tool='draw';this.render();
  }
  $(id){return this.page.querySelector('[data-vfx="'+id+'"]');}
  run(work){return Promise.resolve().then(work).catch(error=>this.message(error.message));}
  async fetch(path,body){
    // Painted VFX is a new asset. Keep the AE link, but do not scope this
    // independent prompt to the captured shot's dimensions or frame range.
    const api=this.studio.host?.api;if(!api)return this.owner.fetch(path,body);
    const response=await api.fetchApi(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();if(!response.ok)throw Object.assign(Error(data.error?.message||data.error||'Paint VFX request failed.'),{status:response.status});return data;
  }
  busy(){return !!(this.job||this.pendingSubmission||this.submitting||this.saving||this.uploading||this.loading||this.preparing);}
  key(){return this.state.keys.find(key=>key.frame===this.selected);}
  setBrush(value){
    if(this.busy())return;const size=Math.max(1,Math.min(1000,Math.round(Number(value)||1)));
    if(size!==this.state.brush){this.state.brush=size;this.revision++;this.viewer?.setBrushSize(size);clearTimeout(this.brushSaveTimer);this.brushSaveTimer=setTimeout(()=>this.save(),150);}
    this.$('brush').value=String(size);this.$('brush-number').value=String(size);this.$('brush-label').textContent=size+' px';this.brushControl?.sync();
  }
  config(){return {engine:'ltx',width:this.state.width,height:this.state.height,frames:this.state.frames,frameCount:this.state.frames,fps:this.state.fps,prompt:this.state.prompt,seed:this.state.seed,steps:8,keys:this.state.keys.filter(key=>key.painted&&key.image).map(key=>({frame:key.frame,image:key.image.file}))};}
  save(){try{this.storage.setItem(KEY,JSON.stringify({state:this.state,items:this.items,job:this.job,pendingSubmission:this.pendingSubmission}));return true;}catch{this.message('Browser storage is full. Free storage before generating.');return false;}}
  message(value=''){this.$('message').textContent=value;}
  invalidateControls(){for(const key of this.state.keys){key.image=null;key.painted=!!key.sketch;}this.revision++;this.save();}
  async change(id){
    if(this.busy())return;try{if(['width','height','frames','background'].includes(id))await this.flushKey();
      const value=['width','height','frames','fps','seed','brush'].includes(id)?Number(this.$(id).value):this.$(id).value;
      if(['width','height'].includes(id)&&(!Number.isInteger(value)||value<256||value>1920||value%64))throw Error('Use whole dimensions on the 64-pixel grid.');
      if(id==='frames'){
        if(!Number.isInteger(value)||value<9||value>321||(value-1)%8)throw Error('Use 8n + 1 frames, from 9 to 321.');
        if(this.state.keys.some(key=>key.frame!==this.state.frames-1&&key.frame>=value))throw Error('Remove later intermediate keys before shortening this shot.');
        const last=this.state.keys.find(key=>key.frame===this.state.frames-1);if(last){if(this.selected===last.frame)this.selected=value-1;last.frame=value-1;}
      }
      this.state[id]=value;this.revision++;this.save();
      if(['width','height','background'].includes(id)){this.invalidateControls();await this.loadKey();}
      if(id==='colour')this.viewer?.setDrawColor(value);if(id==='brush')this.viewer?.setBrushSize(value);this.message('');
    }catch(error){this.$(id).value=this.state[id];this.message(error.message);}this.render();
  }
  async upload(canvasOrBlob,name){const data=canvasOrBlob instanceof Blob?canvasOrBlob:await blob(canvasOrBlob);const form=new FormData();form.append('image',data,name);form.append('subfolder','zura_paint_vfx');form.append('type','input');const response=await this.api.fetchApi('/upload/image',{method:'POST',body:form});if(!response.ok)throw Error('Could not save the painted control frame.');const result=await response.json();if(!result.name)throw Error('ComfyUI returned no image file.');return {filename:result.name,subfolder:result.subfolder||'',file:[result.subfolder,result.name].filter(Boolean).join('/')};}
  admission(){
    const bridge=this.owner.studio.aeBridge;
    return {epoch:this.admissionEpoch,revision:this.revision,bridge,source:bridge?.source,aeSession:this.owner.studio.aeSession};
  }
  assertAdmission(token){
    const bridge=this.owner.studio.aeBridge;
    if(!token||token.epoch!==this.admissionEpoch||token.revision!==this.revision||this.closed||!this.active||this.owner.mode!=='paint_vfx'||bridge!==token.bridge||bridge?.source!==token.source||this.owner.studio.aeSession!==token.aeSession)
      throw Object.assign(Error('The Paint VFX workspace or AE source session changed. Return to Paint VFX and try again.'),{status:409});
  }
  deactivate(){this.active=false;this.admissionEpoch++;}
  async importBackground(file){
    if(!file||this.busy())return;const token=this.admission(),revision=this.revision,epoch=this.epoch,key=this.key();
    try{
      this.assertAdmission(token);await this.flushKey();this.assertAdmission(token);this.uploading=true;this.render();
      if(file.size>64*1024*1024)throw Error('Choose a background image under 64 MiB.');if(!['image/png','image/jpeg','image/webp'].includes(file.type))throw Error('Choose an SDR PNG, JPEG or WebP background. HDR originals stay separate.');
      const asset=await this.upload(file,'background_'+crypto.randomUUID()+'.'+({'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[file.type]));
      this.assertAdmission(token);if(revision!==this.revision||epoch!==this.epoch||key!==this.key())throw Error('The painted source changed while the background was uploading. Try again.');
      this.state.backgroundImage=asset;this.invalidateControls();await this.loadKey();
    }catch(error){this.message(error.message);}finally{this.uploading=false;this.$('background-file').value='';this.render();}
  }
  async backgroundUrl(){if(this.state.backgroundImage)return assetUrl(this.api,this.state.backgroundImage);const canvas=this.page.ownerDocument.createElement('canvas');canvas.width=this.state.width;canvas.height=this.state.height;const ctx=canvas.getContext('2d');ctx.fillStyle=this.state.background;ctx.fillRect(0,0,canvas.width,canvas.height);return canvas.toDataURL('image/png');}
  async loadKey(){
    const epoch=++this.epoch,key=this.key();if(!key)return;this.loading=true;this.loadError='';this.viewer?.dispose();this.viewer=null;this.render();
    try{const url=await this.backgroundUrl();if(epoch!==this.epoch||this.closed)return;const viewer=new this.Viewer(this.$('canvas'),{onChange:()=>{if(epoch!==this.epoch)return;this.dirty=true;this.revision++;this.scheduleKey();},onCommit:()=>{this.scheduleKey();this.render();}});this.viewer=viewer;
      await viewer.setFrame(url,this.state.width,this.state.height,key.frame);if(key.sketch)await viewer.setSketch(assetUrl(this.api,key.sketch));if(epoch!==this.epoch||this.closed){viewer.dispose();return;}
      viewer.setOpacity(0);viewer.setTool(this.tool||'draw');viewer.setDrawColor(this.state.colour);viewer.setBrushSize(this.state.brush);this.dirty=false;
    }catch(error){if(epoch===this.epoch){this.loadError=error.message;this.viewer?.dispose();this.viewer=null;this.message(error.message);}}finally{if(epoch===this.epoch){this.loading=false;this.render();}}
  }
  scheduleKey(){clearTimeout(this.saveTimer);this.saveTimer=setTimeout(()=>void this.flushKey().catch(error=>this.message(error.message)),500);}
  async flushKey(){
    clearTimeout(this.saveTimer);if(this.saving)return this.saving;if(!this.viewer||!this.dirty&&(!this.key()?.sketch||this.key()?.image))return;
    const key=this.key(),viewer=this.viewer,epoch=this.epoch,revision=this.revision;if(!key)return;
    const work=(async()=>{
      const painted=viewer.sketchPresent;if(!painted){Object.assign(key,{painted:false,image:null,sketch:null});this.dirty=false;this.save();return;}
      const canvas=this.page.ownerDocument.createElement('canvas');canvas.width=viewer.width;canvas.height=viewer.height;const ctx=canvas.getContext('2d');ctx.fillStyle=this.state.background;ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(viewer.image,0,0,canvas.width,canvas.height);ctx.drawImage(viewer.sketchCanvas,0,0);
      const [image,sketch]=await Promise.all([this.upload(canvas,'key_'+key.frame+'_'+crypto.randomUUID()+'.png'),this.upload(viewer.sketchCanvas,'paint_'+key.frame+'_'+crypto.randomUUID()+'.png')]);
      if(epoch!==this.epoch||revision!==this.revision||key!==this.key())throw Error('The painted frame changed while saving. Try again.');Object.assign(key,{image,sketch,painted:true});this.dirty=false;this.save();
    })();this.saving=work;this.render();try{await work;}finally{if(this.saving===work)this.saving=null;this.render();}
  }
  async selectKey(frame){if(this.busy())return;await this.flushKey();this.selected=frame;this.review=false;this.save();await this.loadKey();}
  async refreshSetup(){try{this.info=await this.fetch('/object_info');this.availability=paintVfxAvailability(this.info);this.modelDownloads.setMissingContext('paint_vfx',this.availability.missing,'Paint VFX');}catch(error){this.message('Could not check Paint VFX models. '+error.message);}this.render();}
  async open(){if(!this.active)this.admissionEpoch++;this.active=true;this.closed=false;this.modelDownloads.resume();this.owner.outputSettings?.delivery?.bind(this,'paint_vfx');if(!this.viewer)await this.loadKey();await this.refreshSetup();if(this.job||this.pendingSubmission)this.startPolling();}
  render(){
    if(!this.page)return;const busy=this.busy();this.$('canvas').hidden=!!this.review;this.$('result').hidden=!this.review;this.$('edit').hidden=!this.review;this.$('download').hidden=!this.review;this.page.querySelector('.zvfx-tools').hidden=!!this.review;this.page.querySelector('.zvfx-workbench').classList.toggle('is-review',!!this.review);
    this.$('canvas').style.pointerEvents=busy?'none':'';for(const control of this.page.querySelectorAll('button,input,textarea,select'))if(control!==this.$('cancel')&&!control.closest('[data-vfx=models]'))control.disabled=busy;
    this.page.querySelectorAll('[data-tool]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.tool===(this.tool||'draw'))));this.$('brush-label').textContent=this.state.brush+' px';this.$('brush').value=String(this.state.brush);this.$('brush-number').value=String(this.state.brush);this.brushControl?.sync();this.$('colour').value=this.state.colour;
    this.page.querySelectorAll('[data-vfx-swatch]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.vfxSwatch===this.state.colour)));
    this.$('undo').disabled=busy||!this.viewer?.history?.length;this.$('redo').hidden=!(typeof this.viewer?.redo==='function'&&this.viewer.paintAPlateMode);this.$('redo').disabled=busy||!this.viewer?.paintAPlateFuture?.length;
    this.$('keys').replaceChildren(...[...this.state.keys].sort((a,b)=>a.frame-b.frame).map(key=>{
      const doc=this.page.ownerDocument,card=doc.createElement('div');card.className='zvfx-key-card';
      const button=doc.createElement('button');button.type='button';button.className='zvfx-key-select';
      if(key.image){const image=doc.createElement('img');image.src=assetUrl(this.api,key.image);image.alt='';button.append(image);}
      const name=doc.createElement('span');name.textContent=key.frame===0?'First frame':key.frame===this.state.frames-1?'Last frame':'Frame '+key.frame;button.append(name);
      button.setAttribute('aria-pressed',String(key.frame===this.selected));button.disabled=busy;button.onclick=()=>void this.selectKey(key.frame).catch(error=>this.message(error.message));card.append(button);
      if(![0,this.state.frames-1].includes(key.frame)){const remove=doc.createElement('button');remove.type='button';remove.className='zvfx-key-remove';remove.textContent='×';remove.setAttribute('aria-label','Remove frame '+key.frame);remove.disabled=busy;remove.onclick=()=>this.run(async()=>{if(this.busy())return;await this.flushKey();this.state.keys=this.state.keys.filter(item=>item.frame!==key.frame);if(this.selected===key.frame)await this.selectKey(0);else{this.save();this.render();}});card.append(remove);}
      return card;
    }));
    this.$('key-frame').replaceChildren(...paintVfxSlots(this.state.frames).filter(frame=>!this.state.keys.some(key=>key.frame===frame)).map(frame=>{const option=this.page.ownerDocument.createElement('option');option.value=frame;option.textContent='Frame '+frame;return option;}));
    this.$('add-key').disabled=busy||!this.$('key-frame').children.length||this.state.keys.length>=33;this.$('remove-background').hidden=!this.state.backgroundImage;
    const painted=frame=>this.state.keys.some(key=>key.frame===frame&&key.painted&&key.image);
    const paintHint=!painted(0)?'Paint the starting shape on First frame.':!painted(this.state.frames-1)?'Select Last frame and paint the ending shape.':'Both frames are ready. Describe the effect, then generate.';
    this.$('key-status').textContent='Frame '+this.selected+' of '+(this.state.frames-1)+' · '+paintHint;this.$('progress').hidden=!this.job&&!this.pendingSubmission&&!this.submitting;
    const config=this.config(),missing=this.availability?.ready?'':this.info?'Set up the missing models below to generate.':'Checking installed models…',error=paintVfxValidation(config);
    this.$('readiness').textContent=busy?(this.saving?'Saving the painted frame…':'Working…'):this.loadError||(['Paint the first and last keyframes before generating.','Describe the effect to generate.'].includes(error)?paintHint:error)||missing;this.$('generate').disabled=busy||!!this.loadError||!!error||!this.availability?.ready;
    this.$('history').replaceChildren(...this.items.map((item,index)=>{const button=this.page.ownerDocument.createElement('button');button.type='button';button.textContent='Take '+(this.items.length-index)+' · '+item.config.width+' × '+item.config.height;button.onclick=()=>this.showResult(item);return button;}));
  }
  showResult(item){this.result=item;this.review=true;this.$('result').src=assetUrl(this.api,playbackFile(item.file),'output');this.$('download').href=assetUrl(this.api,item.file,'output');this.render();}
  async generate(){
    if(this.busy())return;const token=this.admission();try{
      this.assertAdmission(token);
      this.preparing=true;this.render();await this.flushKey();this.assertAdmission(token);const selected=this.selected;
      for(const key of this.state.keys)if(key.sketch&&!key.image){this.selected=key.frame;await this.loadKey();this.assertAdmission(token);if(this.loadError)throw Error(this.loadError);await this.flushKey();this.assertAdmission(token);}
      if(this.selected!==selected){this.selected=selected;await this.loadKey();this.assertAdmission(token);}
      this.preparing=false;this.submitting=true;this.render();const config=this.config(),error=this.loadError||paintVfxValidation(config);if(error)throw Error(error);if(!this.availability?.ready)throw Error('Set up the missing Paint VFX models first.');
      this.assertAdmission(token);await submitOwnedGraph(this,buildPaintVfxGraph(config,this.info),clone(config),'auto',{zura_paint_vfx:true},{assertCurrent:()=>this.assertAdmission(token)});
    }catch(error){this.message(error.message);}finally{this.preparing=false;this.submitting=false;this.render();}
  }
  startPolling(){if(!this.timer)this.timer=setInterval(()=>void this.poll(),1500);void this.poll();}
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  async poll(){
    if(this.pendingSubmission&&!this.job)return recoverOwnedSubmission(this);if(!this.job||this.polling)return;const job=this.job;this.polling=true;
    try{const history=await this.fetch('/history/'+encodeURIComponent(job.id));if(this.job!==job)return;const entry=history[job.id];if(entry?.status?.completed||entry?.status?.status_str==='error'){
      const files=entry.status.status_str==='error'?[]:entry.outputs?.save?.images||[];for(const file of files)this.items.unshift({file,config:job.config});this.items=this.items.slice(0,12);this.job=null;this.stopPolling();if(files.length)this.showResult(this.items[0]);else this.message(entry.status.messages?.find(message=>message[0]==='execution_error')?.[1]?.exception_message||'Run stopped. Your painted frames and previous takes are retained.');this.save();this.render();
    }else{const queue=await this.fetch('/queue');if(this.job!==job)return;if(![...queue.queue_running||[],...queue.queue_pending||[]].some(row=>row[1]===job.id)){const again=await this.fetch('/history/'+encodeURIComponent(job.id));if(this.job!==job||again[job.id])return;this.job=null;this.stopPolling();this.save();this.message('The run left the queue. Your painted frames are retained.');this.render();}else this.$('progress-detail').textContent=job.cancelPending?'Waiting for cancellation…':'Generating the painted effect…';}}
    catch(error){this.message('Connection interrupted. Reconnecting to the saved run…');}finally{this.polling=false;}
  }
  async graph(){try{await this.flushKey();await this.app.loadApiJson(buildPaintVfxGraph(this.config(),this.info),'Zura Paint VFX.json');this.studio.close();}catch(error){this.message(error.message);}}
  close(){this.deactivate();this.closed=true;clearTimeout(this.saveTimer);clearTimeout(this.brushSaveTimer);void this.flushKey().catch(error=>this.message(error.message)).finally(()=>{if(this.closed){this.viewer?.dispose();this.viewer=null;this.epoch++;}});this.save();this.stopPolling();this.modelDownloads.close();}
}

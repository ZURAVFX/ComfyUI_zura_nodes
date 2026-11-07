/** Optional, source-bound image edit selection.
 * UI craft follows Unslop by Damir Sokolovsky (@heydamir), CC BY 4.0.
 * https://github.com/heydamir/unslop
 */
import {PaintoutMaskViewer} from './paintout_studio/paintout_viewer.js';

const clamp=(value,min,max)=>Math.max(min,Math.min(max,Number(value)||0));
export const imageAreaSourceKey=ref=>String(ref?.file||[ref?.subfolder,ref?.filename].filter(Boolean).join('/')||'').replace(/\\/g,'/');
const clone=value=>value?JSON.parse(JSON.stringify(value)):null;
const empty=key=>({enabled:false,source_key:key||'',mask:null,context:64,feather:16});
const accepted=value=>value&&typeof value==='object'?{
  enabled:!!value.enabled,source_key:String(value.source_key||''),mask:value.mask?.file?clone(value.mask):null,
  context:Math.round(clamp(value.context??64,0,512)),feather:Math.round(clamp(value.feather??16,0,128)),
}:empty('');
const imageUrl=(owner,ref)=>owner.api.apiURL('/view?'+new URLSearchParams({filename:ref.filename,subfolder:ref.subfolder||'',type:'input'}));
const maskUrl=(owner,mask)=>owner.api.apiURL('/view?'+new URLSearchParams({filename:mask.filename,subfolder:mask.subfolder||'',type:'input'}));
const asBlob=canvas=>new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('Could not save the painted selection.')),'image/png'));

/**
 * Paintout's source-space brush at a bounded proxy resolution. Comfy uploads
 * store the mask; workspace drafts contain an asset reference, never PNG data.
 */
export class ImageEditArea {
  constructor(owner){
    this.owner=owner;this.state=accepted(owner.draft?.edit_area);this.editing=false;this.dirty=false;this.preparing=false;this.closed=false;
    this.revision=0;this.viewerEpoch=0;this.upload=null;this.load=null;this.brushSize=96;
    const doc=owner.root.ownerDocument;
    this.button=doc.createElement('button');this.button.type='button';this.button.className='zia-open zc-attachment';this.button.textContent='Paint edit area';
    this.button.setAttribute('aria-pressed','false');this.button.title='Optionally paint the part of the main image to edit';
    owner.root.querySelector('.zc-image-tools').prepend(this.button);this.button.addEventListener('click',()=>this.openEditor());
    this.host=doc.createElement('section');this.host.className='zia-editor';this.host.hidden=true;this.host.setAttribute('aria-label','Image edit area');
    this.host.innerHTML=`<div class="zia-stage"><div class="zia-viewer-host"></div><div class="zia-loading" role="status">Loading image…</div></div>
      <div class="zia-toolbar"><div class="zia-tools" role="group" aria-label="Selection tools">
        <button type="button" data-area-tool="brush" aria-pressed="true">Brush</button><button type="button" data-area-tool="protect" aria-pressed="false">Erase</button><button type="button" data-area-tool="pan" aria-pressed="false">Pan</button>
        <label class="zia-brush">Size <input type="range" min="1" max="1000" value="96" aria-label="Brush size in source pixels"><output>96 px</output></label>
        <button type="button" data-area-action="undo">Undo</button><button type="button" data-area-action="clear">Clear</button><button type="button" data-area-action="fit">Fit</button></div>
        <details class="zia-options"><summary>Blend</summary><div class="zia-options-panel"><label>Surrounding context <input type="number" min="0" max="512" step="1" data-area-context></label><label>Edge softness <input type="number" min="0" max="128" step="1" data-area-feather></label><p>Context helps the model match the scene. Only the painted area is changed.</p></div></details>
        <button type="button" data-area-action="whole">Whole image</button><button type="button" class="zia-done" data-area-action="done">Done</button></div>
      <p class="zia-status" role="status" aria-live="polite"></p>`;
    owner.editInputs.source.after(this.host);
    this.stage=this.host.querySelector('.zia-viewer-host');this.loading=this.host.querySelector('.zia-loading');this.status=this.host.querySelector('.zia-status');
    this.brush=this.host.querySelector('.zia-brush input');this.brushOutput=this.host.querySelector('.zia-brush output');
    this.context=this.host.querySelector('[data-area-context]');this.feather=this.host.querySelector('[data-area-feather]');
    for(const field of [this.context,this.feather])field.addEventListener('focus',()=>field.select());
    this.host.querySelectorAll('[data-area-tool]').forEach(button=>button.addEventListener('click',()=>this.setTool(button.dataset.areaTool)));
    this.brush.addEventListener('input',()=>{this.brushSize=Number(this.brush.value);this.brushOutput.textContent=`${this.brushSize} px`;this.applyBrushSize();});
    this.context.addEventListener('change',()=>this.setParameter('context',this.context.value,512));
    this.feather.addEventListener('change',()=>this.setParameter('feather',this.feather.value,128));
    this.host.querySelector('[data-area-action=undo]').addEventListener('click',()=>{this.viewer?.undo();this.scheduleSave();this.refreshTools();});
    this.host.querySelector('[data-area-action=clear]').addEventListener('click',()=>{this.viewer?.clear();this.scheduleSave();this.refreshTools();});
    this.host.querySelector('[data-area-action=fit]').addEventListener('click',()=>this.viewer?.fit());
    this.host.querySelector('[data-area-action=whole]').addEventListener('click',()=>this.useWholeImage());
    this.host.querySelector('[data-area-action=done]').addEventListener('click',()=>this.finishEditor());
  }
  source(){const o=this.owner;return !o.editMainMissing&&o.references?.[0]?.filename?o.references[0]:null;}
  busy(){const o=this.owner;return !!(o.job||o.pendingSubmission||o.submitting||o.uploading||this.preparing);}
  currentKey(){return imageAreaSourceKey(this.source());}
  isCurrent(key=this.state.source_key){return !!key&&this.currentKey()===key;}
  config(){
    // Do not let a mask from an old main image or another operation reach a graph.
    if(this.owner.imageOperation!=='edit'||!this.state.enabled||!this.isCurrent())return null;
    return clone(this.state);
  }
  restore(value){
    clearTimeout(this.saveTimer);this.revision++;this.disposeViewer();this.state=accepted(value);this.editing=false;this.dirty=false;this.error='';
  }
  reset(){
    clearTimeout(this.saveTimer);this.revision++;this.disposeViewer();this.state=empty(this.currentKey());this.editing=false;this.dirty=false;this.error='';
    this.host.hidden=true;this.refreshTools();
  }
  open(){this.closed=false;this.sync();}
  close(){
    this.closed=true;this.editing=false;this.host.hidden=true;clearTimeout(this.saveTimer);
    // Keep the in-memory canvas alive until an unsaved selection is uploaded.
    if(this.dirty&&this.viewer){void this.persist().then(()=>{if(this.closed)this.disposeViewer();}).catch(error=>{if(error.code!=='STALE_SELECTION'){this.error=error.message;this.owner.message(error.message);}});}
    else this.disposeViewer();
  }
  disposeViewer(){this.viewerEpoch++;this.viewer?.dispose();this.viewer=null;this.load=null;this.loading.hidden=false;}
  sync(){
    const o=this.owner,source=this.source(),key=imageAreaSourceKey(source),edit=o.imageOperation==='edit',visible=o.mode==='image'&&edit&&!this.closed;
    // Input rendering may rebuild this group. Keep one entry point beside the
    // main image and its references rather than losing it with the old nodes.
    const controls=o.$('reference-list')?.querySelector('.zc-edit-main')||o.root.querySelector('.zc-image-tools');
    if(controls&&this.button.parentElement!==controls)controls.append(this.button);
    if(key!==this.state.source_key){
      clearTimeout(this.saveTimer);this.revision++;this.disposeViewer();this.state=empty(key);this.editing=false;this.dirty=false;this.error='';
    }
    this.button.hidden=!visible;this.button.disabled=!visible||!source||this.busy();this.button.setAttribute('aria-pressed',String(visible&&!!source&&this.state.enabled));
    this.button.textContent=this.state.enabled?'Paint edit area · on':'Paint edit area';
    this.button.title=source?'Optionally paint the part of the main image to edit':'Add a main image first';
    const show=visible&&!!source&&this.editing;this.host.hidden=!show;
    if(show){
      // A single large canvas replaces the source/result view while painting.
      o.editInputs.source.hidden=true;o.$('gallery').hidden=true;o.$('image-empty').hidden=true;if(o.imageComparison?.host)o.imageComparison.host.hidden=true;
      if(o.imageComparison?.button)o.imageComparison.button.disabled=true;if(o.editInputs.toggle)o.editInputs.toggle.hidden=true;
      if(!this.viewer&&!this.load)void this.loadViewer(source,key);
    }
    this.refreshTools();
  }
  refreshTools(){
    if(!this.host)return;
    const busy=this.busy(),ready=!!this.viewer&&!this.load;
    this.stage.style.pointerEvents=busy?'none':'';
    for(const element of this.host.querySelectorAll('button,input'))element.disabled=busy||(!ready&&!element.matches('[data-area-action=whole],[data-area-action=done]'));
    this.host.querySelector('[data-area-action=undo]').disabled=busy||!ready||!this.viewer.history.length;
    const focused=this.owner.root.ownerDocument.activeElement;
    if(focused!==this.context)this.context.value=String(this.state.context);
    if(focused!==this.feather)this.feather.value=String(this.state.feather);
    const capability=this.owner.imageAreaCapabilities;
    this.status.textContent=this.error||(!capability?.available&&capability?'Smart crop nodes are needed before this selection can be applied. Open Models to check setup.':this.upload?.key===this.state.source_key?'Saving selection…':'Paint the area to change. The rest of the image stays untouched.');
  }
  openEditor(){
    if(this.busy()||!this.source())return;this.state.enabled=true;this.editing=true;this.error='';
    if(this.owner.imageComparison)this.owner.imageComparison.active=false;
    this.owner.editInputs.showSource=true;this.owner.save();this.owner.render();
  }
  finishEditor(){
    if(this.busy())return;
    if(!this.state.mask&&!this.dirty&&!this.viewer?.maskPresent)this.state.enabled=false;
    this.editing=false;this.owner.save();this.owner.render();
  }
  useWholeImage(){
    if(this.busy())return;this.state.enabled=false;this.editing=false;this.owner.save();this.owner.render();
  }
  setParameter(field,value,max){this.state[field]=Math.round(clamp(value,0,max));this.owner.save();this.refreshTools();}
  async loadViewer(source,key){
    const epoch=++this.viewerEpoch,revision=this.revision,url=imageUrl(this.owner,source);this.loading.textContent='Loading image…';this.loading.hidden=false;
    const work=(async()=>{
      let width=Number(source.width)||0,height=Number(source.height)||0;
      if(!width||!height){
        const image=new Image();await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(new Error('Could not load the main image.'));image.src=url;});
        width=image.naturalWidth;height=image.naturalHeight;
      }
      if(!width||!height)throw new Error('The main image has no readable dimensions.');
      if(epoch!==this.viewerEpoch||revision!==this.revision||!this.isCurrent(key))return;
      const scale=Math.min(1,2048/Math.max(width,height)),proxyWidth=Math.max(1,Math.round(width*scale)),proxyHeight=Math.max(1,Math.round(height*scale));
      const viewer=new PaintoutMaskViewer(this.stage,{onChange:()=>this.changed(),onCommit:()=>this.scheduleSave()});
      this.viewer=viewer;this.sourceScale=scale;
      // Four snapshots at 2048² keep undo storage within roughly 64 MiB.
      const snapshot=viewer.snapshot.bind(viewer);viewer.snapshot=(...args)=>{snapshot(...args);while(viewer.history.length>4)viewer.history.shift();};
      await viewer.setFrame(url,proxyWidth,proxyHeight,0);
      if(epoch!==this.viewerEpoch||revision!==this.revision||!this.isCurrent(key)){viewer.dispose();if(this.viewer===viewer)this.viewer=null;return;}
      if(this.state.mask?.filename)await viewer.setMask(maskUrl(this.owner,this.state.mask));
      if(epoch!==this.viewerEpoch||revision!==this.revision||!this.isCurrent(key)){viewer.dispose();if(this.viewer===viewer)this.viewer=null;return;}
      this.setTool('brush');this.applyBrushSize();this.loading.hidden=true;this.error='';
    })();
    this.load=work;
    try{await work;}catch(error){if(epoch===this.viewerEpoch){this.error=error.message||'Could not open the image selection.';this.loading.textContent=this.error;this.viewer?.dispose();this.viewer=null;}}
    finally{if(this.load===work)this.load=null;this.refreshTools();}
  }
  setTool(tool){
    if(!this.viewer)return;this.viewer.setTool(tool);
    this.viewer.root.setAttribute('aria-label',tool==='brush'?'Paint the image area to edit':tool==='protect'?'Erase from the edit area':'Drag to pan the image');
    this.host.querySelectorAll('[data-area-tool]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.areaTool===tool)));
  }
  applyBrushSize(){this.viewer?.setBrushSize(Math.max(1,this.brushSize*(this.sourceScale||1)));}
  changed(){
    if(!this.isCurrent())return;const firstChange=!this.dirty;this.revision++;this.dirty=true;this.state.mask=null;this.error='';
    // Record a pending selection once, instead of writing storage on every pointer move.
    if(firstChange)this.owner.save();this.scheduleSave();this.refreshTools();
  }
  scheduleSave(){
    clearTimeout(this.saveTimer);if(!this.dirty)return;
    this.saveTimer=setTimeout(()=>{void this.persist().catch(error=>{if(error.code!=='STALE_SELECTION'){this.error=error.message;this.owner.message(error.message);this.refreshTools();}});},600);
  }
  async persist(){
    clearTimeout(this.saveTimer);
    if(!this.dirty)return this.state.mask;
    if(this.load)await this.load;
    const viewer=this.viewer,key=this.state.source_key,revision=this.revision;
    if(!viewer||!this.isCurrent(key))throw new Error('The main image changed. Paint the edit area again.');
    if(!viewer.measureMask()){
      this.state.mask=null;this.dirty=false;this.owner.save();this.refreshTools();return null;
    }
    if(this.upload?.revision===revision&&this.upload.key===key)return this.upload.promise;
    const stale=()=>{const error=new Error('The edit area changed while it was saving.');error.code='STALE_SELECTION';return error;};
    const promise=(async()=>{
      const blob=await asBlob(viewer.maskCanvas);if(revision!==this.revision||!this.isCurrent(key))throw stale();
      const form=new FormData();form.append('image',blob,`${crypto.randomUUID()}.png`);form.append('subfolder','zura_images/edit_areas');form.append('type','input');
      const response=await this.owner.api.fetchApi('/upload/image',{method:'POST',body:form});if(!response.ok)throw new Error('Could not save the edit area. Try again.');
      const asset=await response.json();if(!asset.name)throw new Error('ComfyUI did not return the saved edit area.');
      if(revision!==this.revision||!this.isCurrent(key))throw stale();
      const subfolder=asset.subfolder||'';this.state.mask={filename:asset.name,subfolder,file:(subfolder?subfolder+'/':'')+asset.name};this.dirty=false;this.error='';this.owner.save();return clone(this.state.mask);
    })();
    const upload={key,revision,promise};this.upload=upload;this.refreshTools();
    try{return await promise;}finally{if(this.upload===upload)this.upload=null;this.refreshTools();}
  }
  async flush(){
    if(this.dirty)await this.persist();
    return this.config();
  }
  async prepare(){
    if(this.owner.imageOperation!=='edit'||!this.state.enabled)return null;
    if(!this.isCurrent())throw new Error('The main image changed. Choose an edit area again.');
    this.preparing=true;this.refreshTools();
    try{
      await this.flush();
      if(!this.state.mask?.file)throw new Error('Paint an edit area or choose Whole image.');
      if(!this.isCurrent())throw new Error('The main image changed. Choose an edit area again.');
      return clone(this.state);
    }finally{this.preparing=false;this.refreshTools();}
  }
}

import {workspaceStorage} from './studio_storage.js';
// Ripple borrows the ordinary Image workspace, including local models and
// browser sign-in providers. Only a result belonging to this keyframe returns.
const HANDOFF_KEY='zura-ripple-image-handoff-v1';
function readHandoff(storage){
  try{
    const value=JSON.parse(storage.getItem(HANDOFF_KEY));
    if(value?.version===1&&typeof value.id==='string'&&value.id&&typeof value.source==='string'&&value.source&&['h3','ltx'].includes(value.engine)&&typeof value.anchorId==='string'&&Number.isInteger(value.frame)&&value.frame>=0&&Number.isInteger(value.width)&&value.width>0&&Number.isInteger(value.height)&&value.height>0&&['create','edit'].includes(value.previous?.config?.operation))return value;
  }catch{}
  return null;
}
export class RippleImageHandoff {
  constructor(owner){this.storage=workspaceStorage(owner);this.owner=owner;this.revision=0;this.request=null;this.stored=readHandoff(this.storage);this.restoring=null;this.importing=false;}
  imageBusy(){const o=this.owner;return !!(o.job||o.pendingSubmission||o.submitting||o.uploading);}
  key(workspace,anchor){return JSON.stringify([workspace.source?.path,workspace.revision,workspace.state.engine,anchor.id,anchor.frame]);}
  current(request){const w=request?.workspace;return !!w&&this.key(w,request.anchor)===request.key&&w.anchors().includes(request.anchor);}
  persist(request){
    const w=request.workspace,value={version:1,intent:w.intent||'edit',id:request.id,source:w.source.path,engine:w.state.engine,anchorId:String(request.anchor.id),frame:request.anchor.frame,width:request.width,height:request.height,previous:request.previous};
    try{this.storage.setItem(HANDOFF_KEY,JSON.stringify(value));this.stored=value;return true;}catch{return false;}
  }
  clear(){this.request=null;this.stored=null;++this.revision;try{this.storage.removeItem(HANDOFF_KEY);}catch{}if(this.banner)this.banner.hidden=true;}
  invalidate(workspace){if(this.request?.workspace===workspace||this.stored?.source===(workspace.source?.path||workspace.state.sourcePath))this.clear();}
  async resume(){
    if(this.request){if(!this.current(this.request))this.clear();this.syncImageUI();return;}
    if(!this.stored||this.restoring)return this.restoring;
    const saved=this.stored,revision=this.revision,active=this.owner.ripple,intent=saved.intent||'edit';
    const w=this.owner.rippleWorkspaces?.get(intent)||this.owner.ensureRippleWorkspace?.(intent)||this.owner.ripple;
    if(active&&this.owner.mode==='ripple')this.owner.ripple=active;
    if(!w)return;
    this.restoring=(async()=>{
      await w.restoreSource?.();
      if(revision!==this.revision||this.stored!==saved)return;
      // A connection problem is reversible. Keep the return path while the
      // source cannot be resolved, rather than orphaning the recovered image.
      if(!w.source){this.syncImageUI();return;}
      const anchor=w.anchors().find(a=>String(a.id)===saved.anchorId&&a.frame===saved.frame);
      if(w.source.path!==saved.source||w.state.engine!==saved.engine||w.source.width!==saved.width||w.source.height!==saved.height||!anchor){this.clear();this.owner.message('The Ripple source or keyframe changed. Choose its frame again before editing.');return;}
      this.request={...saved,workspace:w,anchor,key:this.key(w,anchor)};this.syncImageUI();
    })().catch(()=>{this.syncImageUI();}).finally(()=>{this.restoring=null;});
    return this.restoring;
  }
  check(request,mode='image'){
    if(this.request!==request||!this.current(request)||this.owner.mode!==mode||this.owner.root.isConnected===false)throw Error('The source, keyframe or workspace changed. Return to Ripple and choose the frame again.');
  }
  async edit(workspace,anchor){
    const o=this.owner;if(this.imageBusy()||this.importing||workspace.busy()){workspace.message('Finish or cancel the current operation first.');return;}
    if(o.outpaintGuide?.request){workspace.message('Return the current frame-extension image edit before editing a Ripple keyframe.');return;}
    if(this.request&&!this.current(this.request))this.clear();
    if(this.stored&&!this.request)await this.resume();
    if(this.request||this.stored){workspace.message('Return the current Ripple image edit first.');return;}
    const key=this.key(workspace,anchor),revision=++this.revision;
    workspace.exporting=true;workspace.render();workspace.message('Preparing the original frame…');
    const check=()=>{if(revision!==this.revision||key!==this.key(workspace,anchor)||!workspace.anchors().includes(anchor)||o.mode!=='ripple')throw Error('The source, keyframe or workspace changed. Select the frame again.');};
    try{
      const exported=await workspace.prepareAnchor(anchor);check();
      const response=await o.api.fetchApi(exported.url);check();if(!response.ok)throw Error('Could not load the original frame.');
      const blob=await response.blob();check();
      const form=new FormData();form.append('image',blob,`ripple_frame_${anchor.frame}.png`);form.append('subfolder','zura_images/ripple');form.append('type','input');
      const upload=await o.api.fetchApi('/upload/image',{method:'POST',body:form});check();const image=await upload.json();check();if(!upload.ok||!image.name)throw Error(image.error||'Could not prepare the frame for editing.');
      await o.imageArea?.flush();check();
      const previous={config:o.config(),selectedFile:o.items[o.selectedImage]?.file||null};
      this.request={id:crypto.randomUUID(),workspace,anchor,key,width:workspace.source.width,height:workspace.source.height,previous};
      if(!this.persist(this.request)){this.clear();throw Error('Browser storage is unavailable. Free storage before editing a tracked keyframe.');}
      const request=this.request;o.show('image');if(!o.models.length)await o.loadModels();this.check(request);
      await o.setImageOperation('edit',{useCanvas:false});this.check(request);
      o.editMainMissing=false;o.autoCanvasSuppressed=true;
      o.imageArea?.reset();
      o.references=[{file:(image.subfolder?image.subfolder+'/':'')+image.name,filename:image.name,subfolder:image.subfolder||'',name:`Source frame ${anchor.frame}`,width:request.width,height:request.height}];
      o.$('shape').value='auto';o.$('width').value=request.width;o.$('height').value=request.height;
      o.$('prompt').value=workspace.$('prompt').value;o.selectedImage=-1;
      o.save();o.render();o.renderGallery();this.syncImageUI();workspace.message('');
    }catch(error){
      if(this.request&&this.request.workspace===workspace){if(o.mode==='image')await this.leave();else this.clear();}
      workspace.message(error.message||'Could not prepare this keyframe.');
    }finally{workspace.exporting=false;workspace.render();}
  }
  syncImageUI(){
    const o=this.owner,request=this.request||this.stored;if(!request){if(this.banner)this.banner.hidden=true;return;}
    if(!this.banner){
      this.banner=o.root.ownerDocument.createElement('div');this.banner.className='zo-guide-handoff zru-image-handoff';
      this.banner.innerHTML='<div><strong data-ripple-image-title></strong><span>Paint an area to target a local edit, then return to Ripple.</span></div><button type="button" data-ripple-return>Back to Ripple</button><button type="button" data-ripple-use>Use edited frame</button>';
      o.root.querySelector('.zc-image-heading').after(this.banner);
      this.banner.querySelector('[data-ripple-return]').onclick=()=>this.leave();this.banner.querySelector('[data-ripple-use]').onclick=()=>this.useResult();
    }
    const label=(request.workspace?.intent||request.intent)==='relight'?'Relight':'Ripple';this.banner.querySelector('[data-ripple-return]').textContent='Back to '+label;this.banner.querySelector('span').textContent=label==='Relight'?'Adjust the lighting, then return to Relight. Painting an area is optional.':'Paint an area to target a local edit, then return to Ripple.';this.banner.hidden=o.mode!=='image';this.banner.querySelector('[data-ripple-image-title]').textContent=`Edit frame ${request.anchor?.frame??request.frame}`;
    const item=o.items[o.selectedImage],busy=this.importing||this.imageBusy();
    this.banner.querySelector('[data-ripple-return]').disabled=busy;
    this.banner.querySelector('[data-ripple-use]').disabled=busy||!this.request||!this.current(this.request)||item?.ripple_guide!==request.id;
  }
  async useResult(){
    await this.resume();
    const o=this.owner,request=this.request,item=o.items[o.selectedImage];
    if(!request||this.importing||this.imageBusy()||item?.ripple_guide!==request.id)return;
    this.importing=true;this.syncImageUI();
    try{
      this.check(request);const file=item.file;
      const response=await o.api.fetchApi('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'}));this.check(request);
      if(!response.ok)throw Error('Could not read this edited image.');const blob=await response.blob();this.check(request);
      const bitmap=await createImageBitmap(blob),canvas=o.root.ownerDocument.createElement('canvas');canvas.width=request.width;canvas.height=request.height;
      try{this.check(request);canvas.getContext('2d').drawImage(bitmap,0,0,request.width,request.height);}finally{bitmap.close();}
      const exact=await new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(Error('Could not prepare the edited frame.')),'image/png'));this.check(request);
      await request.workspace.importAnchorFile(request.anchor,new File([exact],`ripple_frame_${request.anchor.frame}.png`,{type:'image/png'}),()=>this.check(request));this.check(request);
      const prompt=o.$('prompt').value;request.workspace.state.prompt=prompt;request.workspace.$('prompt').value=prompt;request.workspace.save();
      await this.leave(true);request.workspace.message(`Edited frame ${request.anchor.frame} is ready.`);
    }catch(error){o.message(error.message||'Could not return the edited frame.');}
    finally{this.importing=false;this.syncImageUI();}
  }
  async leave(accepted=false){
    const request=this.request||this.stored;
    if(!request||(this.importing&&!accepted)||this.imageBusy())return;
    const o=this.owner,c=request.previous.config;
    await o.setImageOperation(c.operation,{useCanvas:false});if(this.request!==request&&this.stored!==request)return;
    o.references=(c.references||[]).map(r=>({...r}));o.imageLoras=c.loras||[];o.editMainMissing=!!c.editMainMissing;o.autoCanvasSuppressed=!!c.autoCanvasSuppressed;
    o.imageArea?.restore(c.edit_area||null);
    for(const id of ['model','shape','width','height','seed','prompt'])o.$(id).value=c[id]??'';o.$('random').checked=c.random;
    const previous=request.previous.selectedFile;
    o.selectedImage=previous?o.items.findIndex(item=>item.file?.filename===previous.filename&&(item.file?.subfolder||'')===(previous.subfolder||'')&&(item.file?.type||'output')===(previous.type||'output')):-1;
    this.clear();o.imageIntent=c.image_intent||'standard';
    o.save();o.render();o.renderGallery();o.ensureRippleWorkspace?.(request.workspace?.intent||request.intent||'edit');o.show('ripple');
  }
  // Closing Studio is reversible: keep the current hand-off so a completed
  // image can still return when Studio reopens, but invalidate preparation.
  dispose(){++this.revision;this.banner?.remove();this.banner=null;}
}

import {captureAEGuideParent,sameAEGuideParent} from './studio_image_handoff_contract.js';
// The ordinary Image workspace owns model choice, browser sign-in and progress.
// This hand-off supplies Image 1 and returns only this request's chosen result.
export class OutpaintFirstFrame {
  constructor(workspace){
    this.workspace=workspace;this.owner=workspace.owner;this.asset=null;this.transferRevision=0;
    const doc=workspace.page.ownerDocument;
    this.root=doc.createElement('details');this.root.className='zo-first-frame';
    this.root.innerHTML=`<summary>First-frame guide <span>Optional</span></summary><div class="zo-guide-tools"><button type="button" data-guide-generate>Generate filled frame</button><button type="button" data-guide-upload>Upload finished frame</button><input data-guide-file type="file" accept="image/png,image/jpeg,image/webp" hidden/><div class="zo-guide-chip" hidden><button type="button" data-guide-view><span data-guide-image></span><span></span></button><button type="button" data-guide-remove aria-label="Remove first-frame guide"><svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15"/></svg></button></div></div><p>Fill the empty areas in a still first, or supply a finished image matching this canvas. Video generation keeps the original motion guide.</p>`;
    workspace.$('prompt').before(this.root);
    this.preview=doc.createElement('img');this.preview.className='zo-guide-preview';this.preview.alt='First-frame guide at the selected output proportions';this.preview.hidden=true;workspace.stage.append(this.preview);
    this.root.querySelector('[data-guide-generate]').onclick=()=>this.generate();
    this.root.querySelector('[data-guide-upload]').onclick=()=>this.root.querySelector('input').click();
    this.root.querySelector('input').onchange=event=>{const file=event.target.files?.[0];event.target.value='';if(file)void this.upload(file);};
    this.root.querySelector('[data-guide-remove]').onclick=()=>{this.clear();workspace.message('First-frame guide removed.');};
    this.root.querySelector('[data-guide-view]').onclick=()=>{this.preview.hidden=!this.preview.hidden;if(!this.preview.hidden){this.preview.src=this.url(this.asset);workspace.result.hidden=true;workspace.canvas.hidden=true;}else this.restorePreview();};
  }
  key(){const c=this.workspace.config();return JSON.stringify([c.source,c.start,c.mode,c.width,c.height,c.left,c.top,c.right,c.bottom]);}
  busy(){const w=this.workspace;return !!w.job||w.submitting||w.hdrBusy();}
  url(asset){const parts=asset.file.split('/');return this.owner.api.apiURL('/view?'+new URLSearchParams({filename:parts.pop(),subfolder:parts.join('/'),type:'input'}));}
  restorePreview(){const w=this.workspace;this.preview.hidden=true;w.result.hidden=!w.review&&!w.outputRef;w.canvas.hidden=!w.result.hidden;}
  clear(){this.transferRevision++;this.asset=null;this.boundKey=null;this.restorePreview();this.update();}
  changed(){if(this.asset&&(this.workspace.$('hdr-output').checked||this.boundKey!==this.key()))this.clear();else this.transferRevision++;}
  update(){
    const w=this.workspace,busy=this.busy();this.root.hidden=!w.source||!!w.$('hdr-output').checked;
    for(const button of this.root.querySelectorAll('button'))button.disabled=busy;
    const chip=this.root.querySelector('.zo-guide-chip');chip.hidden=!this.asset;
    if(this.asset){let image=chip.querySelector('img');if(!image){image=document.createElement('img');image.alt='Expanded first-frame guide';chip.querySelector('[data-guide-image]').replaceWith(image);}image.src=this.url(this.asset);chip.querySelector('span').textContent=`First frame · ${w.dimensions().width} × ${w.dimensions().height}`;}
  }
  async upload(file){
    if(this.busy())return;const w=this.workspace,key=this.key(),size=w.dimensions(),revision=++this.transferRevision;
    const check=()=>{if(revision!==this.transferRevision||key!==this.key())throw Error('The source or canvas changed. Upload the guide again.');};
    w.submitting=true;w.paint();w.message('Loading first-frame guide…');
    try{
      const bitmap=await createImageBitmap(file);
      try{check();if(bitmap.width!==size.width||bitmap.height!==size.height)throw Error(`Use the complete expanded frame at ${size.width} × ${size.height} px. This image is ${bitmap.width} × ${bitmap.height} px.`);}finally{bitmap.close();}
      const asset=await this.store(file);check();this.asset=asset;this.boundKey=key;this.root.open=true;w.message('First-frame guide ready. Review the selection, then generate.');
    }catch(error){w.message(error.message,true);}finally{w.submitting=false;w.paint();}
  }
  async store(blob){
    const form=new FormData();form.append('file',blob,'first-frame-guide.png');
    const response=await this.owner.api.fetchApi('/zura/studio/upload?kind=image',{method:'POST',body:form,timeoutMs:null});
    const asset=await response.json();if(!response.ok||!asset.id)throw Error(asset.error||'Could not upload the first-frame guide.');return asset;
  }
  async generate(){
    const w=this.workspace,o=this.owner;if(this.busy())return;
    if(o.job||o.pendingSubmission||o.submitting||o.uploading){w.message('Finish or cancel the current image generation first.',true);return;}
    if(Math.min(...Object.values(w.dimensions()))<256){w.message('Use a canvas of at least 256 px per side to generate an image guide, or upload a finished frame.',true);return;}
    w.submitting=true;w.paint();w.message('Preparing the selected first frame…');
    try{
      const key=this.key(),config=w.config(),aeParent=captureAEGuideParent(o,w),asset=await w.fetch('/zura/studio/outpaint/first-frame',config);
      if(!sameAEGuideParent(aeParent,o,w))throw Error('The AE source changed. Prepare the guide again.');
      const frameTime=aeParent?Number(config.start)*aeParent.frameRate.numerator/aeParent.frameRate.denominator:0,sourceFrame=Math.round(frameTime);
      if(aeParent&&(!Number.isFinite(frameTime)||Math.abs(frameTime-sourceFrame)>1e-6||sourceFrame<0||sourceFrame>=aeParent.frameCount))throw Error('Choose a source-aligned frame inside the AE interval.');
      if(key!==this.key())throw Error('The canvas changed. Prepare the guide again.');
      await o.imageArea?.flush();if(key!==this.key())throw Error('The canvas changed. Prepare the guide again.');
      this.previous={config:o.config(),selectedFile:o.items[o.selectedImage]?.file||null};this.request={key,id:crypto.randomUUID(),aeParent,sourceFrame,width:asset.width,height:asset.height};
      o.outpaintGuide=this;o.show('image');if(!o.models.length)await o.loadModels();
      await o.setImageOperation('edit',{useCanvas:false});
      if(!sameAEGuideParent(aeParent,o,w)||key!==this.key())throw Error('The AE source or canvas changed. Prepare the guide again.');
      o.imageArea?.reset();o.editMainMissing=false;const parts=asset.file.split('/');o.references=[{...asset,filename:parts.pop(),subfolder:parts.join('/')}];
      o.$('shape').value='auto';o.$('width').value=asset.width;o.$('height').value=asset.height;
      o.$('prompt').value=`Fill only the black empty areas of Image 1 with a natural continuation of the surrounding scene. Keep every existing visible part of the original footage unchanged, including the subject, camera, perspective, lighting and placement. Do not add borders or reframe the image. Keep exactly ${asset.width} × ${asset.height} pixels and the same proportions. ${w.$('prompt').value}`;
      o.save();o.render();o.renderGallery();this.syncImageUI();
    }catch(error){w.message(error.message,true);}finally{w.submitting=false;w.paint();}
  }
  syncImageUI(){
    if(!this.request)return;const o=this.owner;
    if(!this.banner){this.banner=o.root.ownerDocument.createElement('div');this.banner.className='zo-guide-handoff';this.banner.innerHTML='<div><strong>Fill the first frame</strong><span>Choose an image model, generate, then return the selected result to frame extension.</span></div><button type="button" data-guide-return>Back to frame extension</button><button type="button" data-guide-use>Use this first frame</button>';o.root.querySelector('.zc-image-heading').after(this.banner);this.banner.querySelector('[data-guide-return]').onclick=()=>this.leave();this.banner.querySelector('[data-guide-use]').onclick=()=>this.useResult();}
    this.banner.hidden=false;const item=o.items[o.selectedImage||0],busy=this.importing||!!o.job||!!o.pendingSubmission||o.submitting||o.uploading;
    this.banner.querySelector('[data-guide-return]').disabled=busy;
    this.banner.querySelector('[data-guide-use]').disabled=busy||!item||item.outpaint_guide!==this.request.id;
  }
  async useResult(){
    const o=this.owner,w=this.workspace,item=o.items[o.selectedImage||0];if(!this.request||this.importing||item?.outpaint_guide!==this.request.id||o.job||o.pendingSubmission)return;
    const request=this.request,revision=++this.transferRevision;
    const check=()=>{if(!sameAEGuideParent(request.aeParent,o,w)||this.request!==request||revision!==this.transferRevision||this.key()!==request.key||o.mode!=='image')throw Error('The source, canvas or workspace changed. Return and prepare a new guide.');};
    this.importing=true;this.syncImageUI();
    try{
      check();
      const file=item.file,response=await o.api.fetchApi('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'}));check();if(!response.ok)throw Error('Could not read this generated image.');
      const source=await response.blob();check();const bitmap=await createImageBitmap(source),{width,height}=request,canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
      let fitted=false;
      try{check();const scale=Math.max(width/bitmap.width,height/bitmap.height);fitted=bitmap.width!==width||bitmap.height!==height;canvas.getContext('2d').drawImage(bitmap,(width-bitmap.width*scale)/2,(height-bitmap.height*scale)/2,bitmap.width*scale,bitmap.height*scale);}finally{bitmap.close();}
      const blob=await new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(Error('Could not prepare the guide image.')),'image/png'));check();
      const asset=await this.store(blob);check();await this.leave(true,check);if(revision!==this.transferRevision||this.key()!==request.key)throw Error('The source or canvas changed. Return and prepare a new guide.');this.asset=asset;this.boundKey=request.key;this.root.open=true;w.paint();w.message(fitted?'Guide ready. The generated image was scaled proportionally and cropped to your exact canvas; review its framing.':'First-frame guide ready. Review the selection, then generate.');
      this.preview.src=this.url(this.asset);this.preview.hidden=false;w.result.hidden=true;w.canvas.hidden=true;
    }catch(error){o.message(error.message);}finally{this.importing=false;this.syncImageUI();}
  }
  dispose(){this.transferRevision++;if(this.request)void this.leave();this.banner?.remove();this.banner=null;}
  async leave(accepted=false,check=()=>{}){
    const o=this.owner;if((this.importing&&!accepted)||o.job||o.pendingSubmission||o.submitting||o.uploading)return;
    if(this.previous){const c=this.previous.config;await o.setImageOperation(c.operation,{useCanvas:false});check();o.references=c.references;o.editMainMissing=!!c.editMainMissing;o.imageLoras=c.loras||[];for(const id of ['model','shape','width','height','seed','prompt'])o.$(id).value=c[id];o.$('random').checked=c.random;const selected=this.previous.selectedFile;o.selectedImage=selected?o.items.findIndex(item=>item.file?.filename===selected.filename&&(item.file?.subfolder||'')===(selected.subfolder||'')&&(item.file?.type||'output')===(selected.type||'output')):-1;o.draft=c;}
    if(this.previous)o.imageArea?.restore(this.previous.config.edit_area||null);
    this.request=null;this.previous=null;o.outpaintGuide=null;if(this.banner)this.banner.hidden=true;o.save();o.render();o.renderGallery();o.show('outpaint');
  }
}

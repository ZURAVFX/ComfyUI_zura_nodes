import {workspaceStorage} from './studio_storage.js';
import {EXRExportPreference,hasEXROutput} from './studio_exr_precision.js';
import {StudioDeliveryControls} from './studio_delivery_controls.js';
import {installStudioModelViews} from './studio_model_view.js';
import {StudioMediaImport} from './studio_media_import.js';
const IMAGE_FORMATS=new Map([['png8',['PNG · 8-bit','uint8',8]],['png16',['PNG · 16-bit storage','uint16',16]],['tiff16',['TIFF · 16-bit storage','uint16',16]],['exr_float',['EXR · SDR float (advanced)','float32',32]]]);
const imageFolder=file=>typeof (file?.subfolder||'')==='string'?(file.subfolder||'').replaceAll('\\','/'):null;
const imageFile=file=>{const folder=imageFolder(file);return file?.type==='output'&&typeof file.filename==='string'&&file.filename.length>0&&!/[\\/\0]/.test(file.filename)&&folder!==null&&!/[:\0]/.test(folder)&&!folder.startsWith('/')&&!folder.split('/').some(part=>part==='.'||part==='..');};
const fileRef=file=>({filename:file.filename,subfolder:imageFolder(file),type:file.type});
const fileKey=file=>imageFile(file)?JSON.stringify(fileRef(file)):'';
const imageKey=item=>fileKey(item?.master||item?.file);
/** One saved delivery folder for the whole Studio, independent of each model. */
export class StudioOutputSettings {
  constructor(root, api, owner) {
    this.api=api;this.owner=owner;this.storage=workspaceStorage(owner);this.precision=new EXRExportPreference(this.storage);
    try{this.imageFormat=this.storage.getItem('zura-studio-sdr-image-format-v1')||'png8';}catch{this.imageFormat='png8';}if(!IMAGE_FORMATS.has(this.imageFormat))this.imageFormat='png8';
    const panel=document.createElement('details');
    panel.className='zc-tool-popup zc-global-models zc-output-settings';
    panel.innerHTML='<summary>Settings</summary><form class="zc-tool-panel"><h3>Save your work</h3><label>Output folder<input name="folder" type="text" spellcheck="false" autocomplete="off" placeholder="Loading saved folder…"/></label><p>Finished images, videos and EXR archives are copied here. ComfyUI keeps the originals for your history.</p><div class="zc-output-actions"><button type="button" data-default>Use default</button><button type="submit" class="gs-primary">Save folder</button></div><p role="status" aria-live="polite"></p></form>';
    this.panel=panel;this.form=panel.querySelector('form');this.input=panel.querySelector('input');this.status=panel.querySelector('[role="status"]');
    this.imageFormatLabel=document.createElement('label');this.imageFormatLabel.textContent='SDR image format';this.imageFormatSelect=document.createElement('select');this.imageFormatSelect.setAttribute('aria-label','SDR image format');
    for(const [value,[label]]of IMAGE_FORMATS){const option=document.createElement('option');option.value=value;option.textContent=label;this.imageFormatSelect.append(option);}this.imageFormatSelect.value=this.imageFormat;this.imageFormatLabel.append(this.imageFormatSelect);
    this.imageFormatSelect.onchange=()=>{if(!IMAGE_FORMATS.has(this.imageFormatSelect.value))return;this.imageFormat=this.imageFormatSelect.value;try{this.storage.setItem('zura-studio-sdr-image-format-v1',this.imageFormat);}catch{}this.syncImageExports();};
    this.imageFormatNote=document.createElement('p');this.imageFormatNote.textContent='16-bit files retain available precision; an 8-bit model does not gain extra detail. SDR float EXR remains SDR. HDR images use verified 32-bit FLOAT EXR; HDR video settings are separate.';this.form.querySelector('.zc-output-actions').before(this.imageFormatLabel,this.imageFormatNote);
    const advanced=document.createElement('details');advanced.className='zc-output-advanced';
    advanced.innerHTML='<summary>Advanced export settings</summary><label>EXR precision<select aria-label="EXR precision"><option value="half">HALF · 16-bit float</option><option value="float32">FLOAT · 32-bit float</option></select></label><p>Controls saved EXR files. Model processing precision is separate.</p>';
    this.form.querySelector('.zc-output-actions').before(advanced);this.exrSelect=advanced.querySelector('select');this.exrSelect.value=this.exrStorage('acescg_exr');
    this.exrSelect.onchange=()=>{if(this.delivery?.aeTransfer==='float32'){this.exrSelect.value='float32';return;}this.precision.set(this.exrSelect.value);this.exrSelect.value=this.exrStorage('acescg_exr');this.owner?.studio?.aeBridge?.updateMeta();};
    if(owner?.studio?.hdrTool)owner.studio.hdrTool.outputSettings=this;
    root.querySelector('.gs-top-actions').prepend(panel);
    panel.addEventListener('toggle',()=>{if(panel.open)void this.load();});
    this.form.onsubmit=event=>{event.preventDefault();void this.save(this.input.value);};
    panel.querySelector('[data-default]').onclick=()=>void this.save('');
    this.delivery=new StudioDeliveryControls(root,api,owner,this);
    installStudioModelViews(this.delivery,api);
    this.mediaImport=new StudioMediaImport(this.delivery,api);
    const format=document.createElement('label');format.innerHTML='HDR files<select aria-label="HDR delivery files"><option value="hlg_and_exr">ProRes 4444 MOV + EXR</option><option value="acescg_exr">EXR</option><option value="hlg_video">ProRes 4444 MOV</option></select>';
    advanced.append(format);this.hdrFormatSelect=format.querySelector('select');this.hdrFormatSelect.value=this.delivery.hdrFormat;this.hdrFormatSelect.onchange=()=>this.delivery.setHDRFormat(this.hdrFormatSelect.value);
    this.delivery.mountAdvanced(this.exrSelect.closest('label'),format,advanced.querySelector('p'));advanced.remove();
    void this.load();
  }
  exrStorage(output){return this.delivery?.aeTransfer==='float32'&&hasEXROutput(output)?'float32':this.precision.value(output);}
  preferSourcePrecision(bitDepth){this.precision.preferSource(bitDepth);this.exrSelect.value=this.exrStorage('acescg_exr');}
  exrLabel(){return 'EXR export '+(this.exrStorage('acescg_exr')==='float32'?'FLOAT':'HALF');}
  async request(path, data){
    const response=await this.api.fetchApi('/zura/studio/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    if(!response.ok){let message;try{message=(await response.json()).error;}catch{}throw Error(message||'Restart ComfyUI after this render to enable the new save controls.');}
    return response.json();
  }
  async load(){
    try{const settings=await this.request('output-settings');this.folder=settings.folder;if(this.input!==document.activeElement)this.input.value=settings.folder;this.status.textContent=settings.error||'Images / Videos / Sequences';}
    catch(error){this.status.textContent=error.message;}
  }
  async save(folder){
    const buttons=this.form.querySelectorAll('button');buttons.forEach(button=>button.disabled=true);this.status.textContent='Checking folder…';
    try{const settings=await this.request('output-settings',{folder});this.folder=settings.folder;this.input.value=settings.folder;this.status.textContent='Saved. New finished work will appear here.';}
    catch(error){this.status.textContent=error.message;}
    finally{buttons.forEach(button=>button.disabled=false);}
  }
  async saveImage(file, button){
    button.disabled=true;button.textContent='Saving…';
    try{const result=await this.request('save-output',{assets:[file]});button.textContent='Saved';button.title=result.saved[0];this.status.textContent='Saved to '+result.saved[0];return result.saved[0];}
    catch(error){button.textContent='Save image';throw error;}
    finally{button.disabled=false;}
  }
  imageCommitted(item){this.delivery.imageCommitted(item);}
  imageExportState(item){
    if(!item||item.image_layer_error)return {ready:false,reason:'Choose a verified finished image.'};
    if(this.imageExporting||this.owner.imageLayers?.busy)return {ready:false,reason:'Wait for the image to finish updating.'};
    if(this.delivery.output==='hdr'&&this.delivery.nativeHDRI('image')?.item===item)return {ready:true};
    const raw=this.delivery.raw('image');if(!raw||this.owner.items?.[this.owner.selectedImage]!==item)return {ready:false,reason:'Select the finished image again.'};
    if(this.delivery.output==='hdr'&&!this.delivery.outputFor('image',raw)){
      const record=this.delivery.recordFor('image',raw),reason=record?.error||'HDR output is not ready. Wait for conversion, retry HDR, or choose SDR explicitly.';
      return {ready:false,reason};
    }
    return {ready:true};
  }
  syncImageExports(){
    if(this.imageFormatSelect){this.imageFormatSelect.value=this.imageFormat;this.imageFormatSelect.disabled=this.delivery?.output==='hdr'||!!this.imageExporting;}
    for(const button of this.owner.$?.('gallery')?.querySelectorAll('[data-save-image],[data-download-image]')||[]){
      const item=this.owner.items?.[Number(button.dataset.saveImage??button.dataset.downloadImage)],state=this.imageExportState(item);
      button.disabled=!state.ready;button.title=state.reason||(this.delivery.output==='hdr'?'Save the verified HDR EXR':'Save '+IMAGE_FORMATS.get(this.imageFormat)?.[0]);
      if(!this.imageExporting)button.textContent=button.hasAttribute('data-save-image')?'Save image':this.delivery.output==='hdr'?'Download HDR EXR':'Download';
    }
  }
  async verifyHDRStill(take,jobId){
    const asset=take.verifiedHDRImage||(take.hdrFiles||[]).find(file=>imageFile(file)&&/\.(zip|exr)$/i.test(file.filename));
    if(!asset)throw Error('HDR conversion did not return an EXR master. Your SDR image is retained.');
    const source=take.original?.master;if(!imageFile(source)||!jobId)throw Error('The HDR job lost its original image identity. Your SDR image is retained.');
    const result=await this.request('image-export',{asset:fileRef(asset),format:'hdr_exr',jobId,source:fileRef(source)});
    if(result.schemaVersion!==1||!imageFile(result.file)||result.format!=='hdr_exr'||result.dynamicRange!=='HDR'||result.colour?.encoding!=='acescg'||result.colour?.sceneLinear!==true||!/^[a-f0-9]{64}$/.test(result.sha256||'')||result.sampleType!=='float32'||result.bitDepth!==32||result.verifiedHDR!==true||result.hdrJobId!==jobId)throw Error('The saved HDR EXR could not be verified. Your SDR image is retained.');
    return {...fileRef(result.file),sha256:result.sha256,colour:result.colour,bitDepth:result.bitDepth,sampleType:result.sampleType};
  }
  async resolveImageItem(item){
    const state=this.imageExportState(item);if(!state.ready)throw Error(state.reason);
    const key=imageKey(item),output=this.delivery.output,format=this.imageFormat,source=this.delivery.sourceKey(this.owner),aeSource=this.owner.studio?.aeBridge?.source;
    const current=()=>!this.delivery.closed&&this.owner.items?.[this.owner.selectedImage]===item&&imageKey(item)===key&&this.delivery.output===output&&this.imageFormat===format&&this.delivery.sourceKey(this.owner)===source&&this.owner.studio?.aeBridge?.source===aeSource&&!this.owner.imageLayers?.busy;
    const native=this.delivery.output==='hdr'&&this.delivery.nativeHDRI('image');
    if(native?.item===item){const descriptor=await native.builder.outputDescriptor(item);if(!current()||!imageFile(descriptor.master))throw Error('The environment or output choice changed during export. Try again.');return fileRef(descriptor.master);}
    const raw=this.delivery.raw('image'),selected=this.delivery.outputFor('image',raw);if(!selected)throw Error('The selected output is not ready. Your original image is retained.');
    if(output==='hdr'){
      const record=this.delivery.recordFor('image',raw),verified=record?.state==='complete'&&record.take?.verifiedHDRImage;
      if(verified&&imageFile(verified)){const checked=await this.verifyHDRStill(record.take,record.take.hdrJobId);if(!current())throw Error('The image or output choice changed. Select it and try again.');return fileRef(checked);}
      // Existing native HDR/HDRI descriptors retain their own verified master.
      if(this.delivery.alreadyHDR(raw)&&imageFile(selected.master)&&/\.(exr|zip)$/i.test(selected.master.filename)){if(!current())throw Error('The image or output choice changed. Select it and try again.');return fileRef(selected.master);}
      throw Error('The HDR image is not verified yet. Wait for HDR output or choose SDR explicitly.');
    }
    const result=await this.request('image-export',{asset:fileRef(selected.master),format});
    const expected=IMAGE_FORMATS.get(format);
    if(!current())throw Error('The image or output choice changed during export. Select it and try again.');
    if(!expected||result.schemaVersion!==1||!imageFile(result.file)||result.format!==format||result.dynamicRange!=='SDR'||result.colour?.encoding!=='srgb_display'||result.colour?.sceneLinear!==false||result.hasAlpha!==false||result.sampleType!==expected[1]||result.bitDepth!==expected[2]||!/^[a-f0-9]{64}$/.test(result.sha256||''))throw Error('The saved SDR image format could not be verified. The original master is retained.');
    return fileRef(result.file);
  }
  async saveImageItem(item,button){
    if(this.imageExporting)throw Error('Wait for the current image export.');
    const filePromise=this.resolveImageItem(item);this.imageExporting=true;this.syncImageExports();button.textContent='Saving…';
    try{const file=await filePromise,result=await this.request('save-output',{assets:[file]});if(!result.saved?.[0])throw Error('The image could not be saved.');this.status.textContent='Saved to '+result.saved[0];return result.saved[0];}
    finally{this.imageExporting=false;this.syncImageExports();}
  }
  async downloadImageItem(item,button){
    if(this.imageExporting)throw Error('Wait for the current image export.');
    const filePromise=this.resolveImageItem(item);this.imageExporting=true;this.syncImageExports();button.textContent='Preparing…';
    try{const file=await filePromise,link=this.owner.root.ownerDocument.createElement('a');link.href=this.api.apiURL('/view?'+new URLSearchParams(file));link.download=file.filename;this.owner.root.append(link);link.click();link.remove();return file;}
    finally{this.imageExporting=false;this.syncImageExports();}
  }
}

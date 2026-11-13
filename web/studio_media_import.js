import {activeStudioMode,studioModeAdapter} from './studio_mode_adapters.js';

const HDR=new Set(['acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3']);
const VIDEO_MODES=new Set(['swap','viewport','camera','outpaint','alpha']);
export const studioImportAEActive=owner=>!!(owner.studio?.aeSession||owner.studio?.aeBridge&&!owner.studio.aeBridge.closed);
export function importPrecisionLabel(precision={}){
  if(precision.storage==='video')return `${precision.codec||'Video'} · decoded ${precision.decodedBitDepth||'?'}-bit`;
  return `${precision.storageBitDepth||'?'}-bit ${precision.sampleType==='float'?'float':'image'}`;
}
export function importRequest(asset,mode,{colour,frame,rate,start,count}={}){
  const frames=asset.frameCount||asset.count||1;
  if(VIDEO_MODES.has(mode)&&asset.asset_kind==='image')throw Error('This mode needs a video. Open Image, First & last frame or Reference to video for this still.');
  if(mode==='image'&&frames>1&&(!Number.isInteger(frame)||frame<0||frame>=frames))throw Error('Choose the source frame to edit in Image mode.');
  const request={asset_id:asset.id,colour_space:colour&&colour!=='auto'?colour:asset.resolved_colour||'auto'};
  if(mode==='image')request.frame=frame??0;
  else{request.startFrame=start??0;request.frameCount=count??frames;}
  if(asset.asset_kind==='hdr_sequence'){
    if(!Number.isFinite(rate)||rate<1||rate>240)throw Error('Choose the EXR sequence frame rate.');
    // Common NTSC rates retain their exact clock rather than a rounded decimal.
    const ntsc=[[23.976,24000],[29.97,30000],[59.94,60000],[119.88,120000]].find(([value])=>Math.abs(rate-value)<.001);
    request.frameRate=ntsc?{numerator:ntsc[1],denominator:1001}:{numerator:Math.round(rate*1000000),denominator:1000000};
  }
  return request;
}

/** One original import, shared by all workspaces; model views never replace it. */
export class StudioMediaImport {
  constructor(delivery,api){
    this.delivery=delivery;this.api=api;this.owner=delivery.owner;this.root=delivery.root;
    const doc=this.root.ownerDocument;
    this.button=doc.createElement('button');this.button.type='button';this.button.textContent='Add media';this.button.dataset.studioImport='';
    delivery.element.append(this.button);this.button.onclick=()=>this.choose();
    this.picker=doc.createElement('input');this.picker.type='file';this.picker.multiple=true;this.picker.accept='.mp4,.mov,.mxf,.avi,.mkv,.webm,.png,.jpg,.jpeg,.webp,.tif,.tiff,.exr';this.picker.hidden=true;this.root.append(this.picker);
    this.picker.onchange=()=>{const files=[...this.picker.files];this.picker.value='';if(files.length)void this.upload(files);};
    this.dialog=doc.createElement('dialog');this.dialog.className='zc-media-import';
    this.dialog.innerHTML='<form><h3>Add media</h3><p data-name></p><p data-description></p><label data-colour-row>Source colour<select name="colour"><option value="auto">Read source tags</option><option value="srgb_display">sRGB</option><option value="rec709_oetf">Rec.709</option><option value="rec709_gamma24">Rec.709 gamma 2.4</option><option value="acescg">ACEScg</option><option value="acescct">ACEScct</option><option value="linear_rec709">Linear Rec.709</option><option value="hlg_rec2020">Rec.2020 HLG</option><option value="pq_rec2020">Rec.2020 PQ</option></select></label><label data-rate-row>Sequence frame rate<input name="rate" type="number" min="1" max="240" step="any" value="24"></label><label data-frame-row>Frame to edit<input name="frame" type="number" min="0" step="1" value="0"></label><div data-range-row><label>First frame<input name="start" type="number" min="0" step="1" value="0"></label><label>Frame count<input name="count" type="number" min="1" step="1"></label></div><p data-status role="status" aria-live="polite"></p><footer><button type="button" data-cancel>Cancel</button><button type="submit">Use media</button></footer></form>';
    this.root.append(this.dialog);this.form=this.dialog.querySelector('form');this.status=this.dialog.querySelector('[data-status]');
    const p3=doc.createElement('option');p3.value='pq_display_p3';p3.textContent='Display P3 PQ';this.form.elements.colour.append(p3);
    this.preview=doc.createElement('img');this.preview.className='zc-media-import-preview';this.preview.alt='Selected source frame';this.preview.hidden=true;this.dialog.querySelector('[data-description]').after(this.preview);
    this.preview.onerror=()=>{this.preview.hidden=true;};
    this.form.elements.frame.oninput=()=>this.previewFrame();this.form.elements.colour.onchange=()=>this.previewFrame();
    this.form.onsubmit=event=>{event.preventDefault();void this.apply();};this.dialog.querySelector('[data-cancel]').onclick=()=>this.cancel();
    this.dialog.addEventListener('cancel',()=>this.cancel());
    const link=doc.createElement('link');link.rel='stylesheet';link.href=new URL('./studio_media_import.css',import.meta.url).href;doc.head.append(link);
    const sync=delivery.sync;delivery.sync=(...args)=>{const result=sync.apply(delivery,args);const bound=studioImportAEActive(this.owner);if(bound)this.abandon();this.button.hidden=bound;this.button.disabled=this.busy||bound||delivery.isBusyFor(activeStudioMode(this.owner));return result;};
    const close=delivery.close;delivery.close=(...args)=>{this.closed=true;this.abandon();this.picker.remove();this.dialog.remove();link.remove();return close.apply(delivery,args);};
    delivery.sync();
  }
  choose(){if(studioImportAEActive(this.owner))return this.delivery.message('Leave After Effects mode before replacing its source.');this.picker.click();}
  current(controller){return !this.closed&&controller===this.controller&&!controller.signal.aborted&&!studioImportAEActive(this.owner);}
  assertCurrent(controller){if(!this.current(controller)){const error=Error('This normal import was cancelled or replaced by After Effects.');error.name='AbortError';throw error;}}
  abandon(){clearTimeout(this.previewTimer);this.controller?.abort();this.controller=null;this.asset=null;this.setBusy(false);this.dialog.close();}
  async request(path,options={}){
    const response=await this.api.fetchApi(path,options);let value;try{value=await response.json();}catch{throw Error('The import service is unavailable. Restart ComfyUI after updating the nodes.');}
    if(!response.ok)throw Error(value.error?.message||value.error||'Could not import this media.');return value;
  }
  cancel(){clearTimeout(this.previewTimer);this.controller?.abort();if(!this.busy)this.dialog.close();else this.status.textContent='Cancelling input preparation. The original is retained.';}
  setBusy(value){this.busy=value;this.button.disabled=value;this.form.querySelector('[type="submit"]').disabled=value;}
  async upload(files){
    if(this.busy||this.closed||studioImportAEActive(this.owner))return;this.mode=activeStudioMode(this.owner);this.asset=null;const controller=this.controller=new AbortController();
    this.dialog.querySelector('[data-name]').textContent=files.length===1?files[0].name:`${files.length} EXR frames`;
    for(const row of this.dialog.querySelectorAll('label,[data-range-row]'))row.hidden=true;
    this.preview.hidden=true;this.preview.removeAttribute('src');this.dialog.querySelector('[data-description]').textContent='';
    this.status.textContent='Retaining the original media…';this.dialog.showModal();this.setBusy(true);
    try{
      const sequence=files.every(file=>/\.exr$/i.test(file.name));if(files.length>1&&!sequence)throw Error('Choose one movie or image, or select the frames of one EXR sequence.');
      const data=new FormData();for(const file of files)data.append(sequence?'frames':'file',file,file.name);
      let result=await this.request(sequence?'/zura/studio/hdr/exr-sequence':'/zura/studio/media-import/upload',{method:'POST',body:data,signal:this.controller.signal,timeoutMs:null});
      this.assertCurrent(controller);
      if(sequence)result=await this.request('/zura/studio/media-import/describe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:result.id}),signal:this.controller.signal});
      this.assertCurrent(controller);
      this.asset=result.asset;this.mediaInfo=result.mediaInfo;this.populate();
    }catch(error){if(controller===this.controller)this.status.textContent=error.name==='AbortError'?'Import cancelled.':error.message;}
    finally{if(controller===this.controller){this.setBusy(false);if(!this.current(controller))this.dialog.close();}}
  }
  populate(){
    const asset=this.asset,n=asset.frameCount||asset.count||1;
    this.dialog.querySelector('[data-description]').textContent=`${asset.width} × ${asset.height} · ${n} frame${n===1?'':'s'} · ${importPrecisionLabel(asset.precision)}`;
    for(const row of this.dialog.querySelectorAll('label,[data-range-row]'))row.hidden=false;
    this.dialog.querySelector('[data-rate-row]').hidden=asset.asset_kind!=='hdr_sequence';
    this.dialog.querySelector('[data-frame-row]').hidden=this.mode!=='image'||n===1;
    this.dialog.querySelector('[data-range-row]').hidden=this.mode==='image'||n===1;
    this.form.elements.colour.value=[...this.form.elements.colour.options].some(option=>option.value===asset.resolved_colour)?asset.resolved_colour:'auto';this.form.elements.frame.max=String(n-1);this.form.elements.frame.value='0';
    this.form.elements.start.max=String(n-1);this.form.elements.start.value='0';this.form.elements.count.max=String(n);this.form.elements.count.value=String(n);
    this.status.textContent=asset.resolved_colour?'Original retained. This mode uses a separate SDR input when needed.':'Check the source colour space. The original stays unchanged.';
    this.previewFrame();
  }
  previewFrame(){
    clearTimeout(this.previewTimer);
    if(this.mode!=='image'||!this.mediaInfo?.thumbnail_url){this.preview.hidden=true;return;}
    this.previewTimer=setTimeout(()=>{
      const colour=this.form.elements.colour.value==='auto'?this.asset.resolved_colour:this.form.elements.colour.value;
      if(!colour){this.preview.hidden=true;return;}
      const url=new URL(this.mediaInfo.thumbnail_url,this.root.ownerDocument.location.href);
      url.searchParams.set('frame',String(Number(this.form.elements.frame.value)||0));url.searchParams.set('space',colour);url.searchParams.set('size','480');
      this.preview.src=this.api.apiURL(url.pathname+url.search);this.preview.hidden=false;
    },120);
  }
  async apply(){
    if(!this.asset||this.busy||this.closed||studioImportAEActive(this.owner))return;const controller=this.controller=new AbortController();this.setBusy(true);this.status.textContent='Preparing the model input…';
    try{
      this.assertCurrent(controller);
      const adapter=studioModeAdapter(this.mode);if(!adapter)throw Error('Open a Studio image or video mode first.');
      if(adapter.isBusy(this.owner))throw Error('Finish the current operation before importing media.');
      const values=this.form.elements,request=importRequest(this.asset,this.mode,{colour:values.colour.value,frame:Number(values.frame.value),rate:Number(values.rate.value),start:Number(values.start.value),count:Number(values.count.value)});
      if(this.mode==='hdr'&&this.asset.asset_kind==='hdr_sequence'){
        const colour=request.colour_space;
        if(['acescg','acescct','linear_rec709'].includes(colour)){
          await this.owner.openHDR();this.assertCurrent(controller);const tool=this.owner.studio.hdrTool;tool.setSequenceAsset(this.asset,{fps:request.frameRate.numerator/request.frameRate.denominator,colour:{encoding:colour}});tool.$('start').value=String(request.startFrame);tool.$('count').value=String(request.frameCount);tool.updateRangeSummary();this.dialog.close();return;
        }
        if(!['srgb_display','rec709_oetf','rec709_gamma24'].includes(colour))throw Error('Choose the actual EXR colour space. Native HDR preparation supports scene-linear ACEScg, Linear Rec.709 or ACEScct.');
        const source=await this.request('/zura/studio/media-import/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request),signal:this.controller.signal,timeoutMs:null});
        this.assertCurrent(controller);await this.owner.openHDR();this.assertCurrent(controller);const tool=this.owner.studio.hdrTool;tool.$('mode').value='sdr';tool.setOwnAsset(source.processingInput.studioAsset);tool.$('colour').value='srgb_display';tool.$('start').value='0';tool.$('count').value=String(source.frameCount);tool.updateRangeSummary();tool.sourceChanged();this.dialog.close();return;
      }
      if(this.mode==='hdr'&&this.asset.asset_kind==='video'){
        await this.owner.openHDR();this.assertCurrent(controller);const tool=this.owner.studio.hdrTool;tool.$('mode').value=HDR.has(request.colour_space)?'native':'sdr';tool.setOwnAsset(this.asset);tool.$('colour').value=[...tool.$('colour').options].some(option=>option.value===request.colour_space)?request.colour_space:'auto';tool.$('start').value=String(request.startFrame);tool.$('count').value=String(request.frameCount);tool.updateRangeSummary();tool.sourceChanged();this.dialog.close();return;
      }
      if(this.mode==='hdr')throw Error('For a still image, open Image and choose Output: HDR. It uses the same one-frame LTX HDR conversion.');
      const source=await this.request('/zura/studio/media-import/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request),signal:this.controller.signal,timeoutMs:null});
      this.assertCurrent(controller);await adapter.acceptInput(this.owner,source,{isActive:()=>this.current(controller)});this.assertCurrent(controller);
      this.delivery.sync();this.dialog.close();this.delivery.message(`Media ready · ${importPrecisionLabel(source.precision)} original retained`);
    }catch(error){if(controller===this.controller)this.status.textContent=error.name==='AbortError'?'Input preparation cancelled. The original is retained.':error.message;}
    finally{if(controller===this.controller){this.setBusy(false);if(!this.current(controller))this.dialog.close();}}
  }
}

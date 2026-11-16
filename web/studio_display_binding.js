// One display-only binding per ordinary media element. AEFloatDisplay owns its
// own pixels and never passes through this secondary overlay renderer.
const AE_ROOT='/zura/comfylink/v1/studio/sessions';
import {inverseSRGBPreviewPixels,isUnmanagedICCDisplay,verifiedICCPreviewSource} from './studio_display_state.js';
const MAX_PREVIEW_PIXELS=16*1024*1024,MAX_VIDEO_PREVIEW_PIXELS=1920*1080;
const verifiedUnmanaged=settings=>verifiedICCPreviewSource(settings.owner?.studio?.aeBridge?.source)&&settings.owner.studio.aeBridge.closed!==true;
export function inverseSRGBCanvas(media,doc,{video=false}={}){
  const originalWidth=Number(video?media.videoWidth:media.naturalWidth||media.width),originalHeight=Number(video?media.videoHeight:media.naturalHeight||media.height);
  if(!Number.isSafeInteger(originalWidth)||!Number.isSafeInteger(originalHeight)||originalWidth<1||originalHeight<1||originalWidth*originalHeight>MAX_PREVIEW_PIXELS)throw Error('The unmanaged AE preview has no supported raster.');
  const scale=video?Math.min(1,Math.sqrt(MAX_VIDEO_PREVIEW_PIXELS/(originalWidth*originalHeight))):1;
  const canvas=doc.createElement('canvas');canvas.width=Math.max(1,Math.floor(originalWidth*scale));canvas.height=Math.max(1,Math.floor(originalHeight*scale));
  const ctx=canvas.getContext('2d',{willReadFrequently:true});if(!ctx)throw Error('The browser cannot prepare this display-only preview.');
  ctx.drawImage(media,0,0,canvas.width,canvas.height);
  const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);inverseSRGBPreviewPixels(pixels.data);ctx.putImageData(pixels,0,0);
  return canvas;
}
const pngBlob=canvas=>new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(Error('Could not create the unmanaged AE preview.')),'image/png'));
export async function inverseSRGBPreviewBlob(blob,doc){
  if(typeof globalThis.createImageBitmap!=='function')throw Error('The browser cannot decode the unmanaged AE preview.');
  const bitmap=await globalThis.createImageBitmap(blob);
  try{return await pngBlob(inverseSRGBCanvas(bitmap,doc));}finally{bitmap.close?.();}
}

export class StudioDisplayBinding{
  constructor(settings,media){
    this.settings=settings;this.media=media;this.revision=0;this.closed=false;this.signature=null;this.paintGrants=new Map();
    this.masterSrc=media.tagName==='VIDEO'?(media.getAttribute?.('src')||media.currentSrc||''):null;
    this.proxyURL=null;this.videoSwap=false;this.unmanagedVideo=null;this.videoFrameTimer=null;this.videoFrameHandle=null;
    this.onFollow=()=>{this.signature=null;this.refresh();this.settings.sync();};
    this.onInvalidate=()=>{this.signature=null;this.cancel();this.refresh();this.settings.sync();};
    if(media.tagName==='VIDEO'){
      this.onVideoEvent=()=>{if(!this.videoSwap){if(this.unmanagedVideo)this.drawUnmanagedVideo();else this.refresh();}};
      for(const event of ['play','pause','seeked','loadeddata','emptied'])media.addEventListener?.(event,this.onVideoEvent);
    }else{
      for(const event of ['load','pause','seeked','loadeddata'])media.addEventListener?.(event,this.onFollow);
      for(const event of ['play','seeking','emptied'])media.addEventListener?.(event,this.onInvalidate);
    }
  }
  selected(){return this.settings.currentFor(this.media);}
  report(text,error=false){
    if(this.media.tagName==='VIDEO'&&this.settings.status)this.settings.status.textContent=text;
    const menu=this.settings.menu;if(menu?.active?.media!==this.media)return;
    if(menu.status)menu.status.textContent=text;
    menu.error=error?{key:this.selected()?.key,text}:null;
    this.settings.sync();
  }
  refresh(){
    if(this.closed)return;const state=this.settings.displayStore.get(),selected=this.selected();
    if(this.media.tagName==='VIDEO'){this.refreshVideo(state,selected);return;}
    const signature=JSON.stringify([state.revision,selected?.key,this.media.currentSrc||this.media.getAttribute?.('src')]);
    if(signature===this.signature){this.updatePosition();return;}this.signature=signature;this.cancel();
    if(isUnmanagedICCDisplay(state.selection)){
      if(!selected||!verifiedUnmanaged(this.settings)){this.report('The unmanaged AE view needs a verified linear-sRGB AE source.',true);return;}
      this.timer=setTimeout(()=>void this.renderUnmanagedImage(state,selected),0);this.timer?.unref?.();return;
    }
    if(!state.selection||state.selection.view==='Raw'){
      if(selected?.aeModelView&&verifiedUnmanaged(this.settings))this.timer=setTimeout(()=>void this.renderUnmanagedImage(state,selected),0);
      return;
    }
    if(!selected)return;
    this.timer=setTimeout(()=>void this.render(state,selected),100);this.timer?.unref?.();
  }
  refreshVideo(state,selected){
    const actual=this.media.getAttribute?.('src')||this.media.currentSrc||'';
    if(actual&&actual!==this.masterSrc&&actual!==this.proxyURL&&!this.videoSwap){
      this.cancel();this.proxyURL=null;this.masterSrc=actual;this.signature=null;
    }
    const preset=state.selection?.view==='Raw'?null:state.selection;
    const signature=JSON.stringify([state.revision,selected?.key,this.masterSrc]);
    if(signature===this.signature)return;
    this.signature=signature;this.cancel();
    if(!preset||!selected){this.restoreVideo();if(this.settings.status)this.settings.status.textContent='';return;}
    if(isUnmanagedICCDisplay(preset)){
      if(!verifiedUnmanaged(this.settings)){this.restoreVideo();this.report('The unmanaged AE view needs a verified linear-sRGB AE source.',true);return;}
      void this.prepareUnmanagedVideo(state,selected);return;
    }
    // The server resolves only a registered asset or an already granted source.
    // AE's unregistered float viewer has its own frame display renderer.
    const selector=selected.selector||selected.ae?.source?.displaySelector;
    if(!selector){this.restoreVideo();this.report('Reload the source to enable its playback colour preview.',true);return;}
    this.restoreVideo();
    const revision=++this.revision,controller=new AbortController();this.controller=controller;
    this.report('Preparing colour playback preview…');
    void this.prepareVideo(state,selected,selector,revision,controller);
  }
  async prepareVideo(state,selected,selector,revision,controller){
    try{
      const preset=state.selection,response=await this.settings.api.fetchApi('/zura/studio/display/video',{
        method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
        body:JSON.stringify({source:selector,colour_space:selected.colour||'auto',config:preset.config,display:preset.display,view:preset.view})});
      await this.settings.response(response);
      const result=await response.json();
      if(this.closed||this.revision!==revision||controller.signal.aborted||this.selected()?.key!==selected.key||
         this.settings.displayStore.get().revision!==state.revision||result.preview_only!==true)return;
      const url=this.settings.api.apiURL?.(result.url)||result.url;
      this.proxyURL=url;
      const switched=await this.swapVideo(url,()=>!this.closed&&this.proxyURL===url&&
        this.revision===revision&&!controller.signal.aborted&&
        this.settings.displayStore.get().revision===state.revision&&this.selected()?.key===selected.key);
      if(!switched){if(this.proxyURL===url)this.restoreVideo();return;}
      if(this.closed||this.revision!==revision||controller.signal.aborted||
         this.settings.displayStore.get().revision!==state.revision){if(this.proxyURL===url)this.restoreVideo();return;}
      this.report('Display only. Source and exports are unchanged.');
    }catch(error){
      if(error.name!=='AbortError'&&!this.closed&&this.revision===revision){
        if(this.proxyURL)this.restoreVideo();this.report(error.message||'Colour playback preview unavailable.',true);
      }
    }
  }
  async renderUnmanagedImage(state,selected){
    const revision=++this.revision,controller=new AbortController();this.controller=controller;
    try{
      if(this.media.decode)await this.media.decode();
      if(!this.current(revision,state,selected,controller))return;
      const canvas=inverseSRGBCanvas(this.media,this.settings.root.ownerDocument),blob=await pngBlob(canvas);
      if(!this.current(revision,state,selected,controller))return;
      const url=URL.createObjectURL(blob),overlay=this.settings.root.ownerDocument.createElement('img');overlay.className='zc-colour-inline';overlay.alt='AE unmanaged working RGB display preview';overlay.src=url;
      this.release();this.inline={url,overlay};this.settings.root.append(overlay);this.updatePosition();
      this.report('AE Viewer unmanaged display only. Model input and exports are unchanged.');
    }catch(error){if(error.name!=='AbortError'&&this.current(revision,state,selected,controller))this.report(error.message||'Unmanaged AE preview unavailable.',true);}
  }
  async prepareUnmanagedVideo(state,selected){
    const revision=++this.revision,controller=new AbortController();this.controller=controller;
    try{
      this.restoreVideo();await this.swapTail;
      if(!this.current(revision,state,selected,controller))return;
      const overlay=this.settings.root.ownerDocument.createElement('canvas');overlay.className='zc-colour-inline';overlay.setAttribute('aria-label','AE unmanaged working RGB display preview');
      this.inline={overlay};this.unmanagedVideo={state,selected,revision,controller};this.settings.root.append(overlay);this.updatePosition();this.drawUnmanagedVideo();
      this.report('AE Viewer unmanaged display only. Video source and exports are unchanged.');
    }catch(error){if(error.name!=='AbortError'&&this.current(revision,state,selected,controller))this.report(error.message||'Unmanaged AE playback preview unavailable.',true);}
  }
  drawUnmanagedVideo(){
    clearTimeout(this.videoFrameTimer);this.videoFrameTimer=null;
    if(this.videoFrameHandle!==null){this.media.cancelVideoFrameCallback?.(this.videoFrameHandle);this.videoFrameHandle=null;}
    const active=this.unmanagedVideo;if(!active||!this.current(active.revision,active.state,active.selected,active.controller))return;
    if(!this.media.videoWidth||!this.media.videoHeight)return;
    try{
      const canvas=inverseSRGBCanvas(this.media,this.settings.root.ownerDocument,{video:true}),overlay=this.inline?.overlay;
      if(!overlay)return;overlay.width=canvas.width;overlay.height=canvas.height;
      overlay.getContext('2d')?.drawImage(canvas,0,0);this.updatePosition();
      if(this.media.paused===false){
        if(typeof this.media.requestVideoFrameCallback==='function')this.videoFrameHandle=this.media.requestVideoFrameCallback(()=>{this.videoFrameHandle=null;this.drawUnmanagedVideo();});
        else{this.videoFrameTimer=setTimeout(()=>this.drawUnmanagedVideo(),1000/30);this.videoFrameTimer?.unref?.();}
      }
    }catch(error){this.cancel();this.report(error.message||'Unmanaged AE playback preview unavailable.',true);}
  }
  async swapVideo(url,allowed=()=>true){
    this.swapTail=(this.swapTail||Promise.resolve()).catch(()=>{}).then(()=>allowed()?this.doSwapVideo(url):false);
    return this.swapTail;
  }
  async doSwapVideo(url){
    const media=this.media,time=Number(media.currentTime)||0,playing=media.paused===false;
    const volume=media.volume,muted=media.muted,rate=media.playbackRate,loop=media.loop;
    this.videoSwap=true;
    try{
      media.src=url;media.load?.();
      if(media.readyState<1)await new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>failed(),15000);
        const done=()=>{clearTimeout(timeout);media.removeEventListener('loadedmetadata',ready);media.removeEventListener('error',failed);};
        const ready=()=>{done();resolve();},failed=()=>{done();reject(Error('The colour playback copy could not be loaded.'));};
        media.addEventListener('loadedmetadata',ready,{once:true});media.addEventListener('error',failed,{once:true});
      });
      const duration=Number(media.duration);
      media.currentTime=Number.isFinite(duration)&&duration>0?Math.min(time,Math.max(0,duration-.001)):time;
      media.volume=volume;media.muted=muted;media.playbackRate=rate;media.loop=loop;
      if(playing)await media.play?.().catch?.(()=>{});
      return true;
    }finally{this.videoSwap=false;}
  }
  restoreVideo(){
    if(!this.proxyURL)return;
    const raw=this.media.getAttribute?.('src')||this.media.src||this.media.currentSrc;
    if(raw&&raw!==this.proxyURL&&raw!==this.masterSrc){this.proxyURL=null;return;}
    const original=this.masterSrc;this.proxyURL=null;
    if(original)void this.swapVideo(original).catch(()=>{});
  }
  current(revision,state,selected,controller){
    return !this.closed&&!this.settings.closed&&this.settings.root.contains(this.media)&&this.media.isConnected!==false&&!this.media.hidden&&!this.media.closest?.('[hidden]')
      &&this.revision===revision&&this.controller===controller&&!controller.signal.aborted
      &&this.settings.displayStore.get().revision===state.revision&&this.selected()?.key===selected.key
      &&selected.ae?.closed!==true;
  }
  async sourceInfo(selected,signal){
    if(selected.paint)return {frame_count:1};
    if(selected.ae){
      const count=Number(selected.count);if(!Number.isSafeInteger(count)||count<1||count>10000)throw Error('The AE source has no valid frame count.');
      return {frame_count:count,frame_rate:selected.ae.source?.manifest?.frameRate||selected.ae.source?.rate};
    }
    const response=await this.settings.api.fetchApi('/zura/studio/display/info',{method:'POST',headers:{'Content-Type':'application/json'},signal,body:JSON.stringify({source:selected.selector})});
    await this.settings.response(response);return response.json();
  }
  frame(info){
    const count=Number(info.frame_count);if(!Number.isSafeInteger(count)||count<1||count>10000)throw Error('The original source has no valid frame count.');
    if(count===1||this.media.tagName!=='VIDEO')return 0;
    const time=Number(this.media.currentTime),rate=info.frame_rate,fps=Number(rate?.numerator)/Number(rate?.denominator);
    if(Number.isFinite(time)&&fps>0)return Math.max(0,Math.min(count-1,Math.floor((time+1e-7)*fps)));
    const duration=Number(this.media.duration);if(Number.isFinite(time)&&duration>0)return Math.max(0,Math.min(count-1,Math.floor(time/duration*count)));
    throw Error('The original video timing is unavailable.');
  }
  async render(state,selected){
    const revision=++this.revision,controller=new AbortController();this.controller=controller;
    try{
      const info=await this.sourceInfo(selected,controller.signal);if(!this.current(revision,state,selected,controller))return;
      const index=selected.paint?.frame??this.frame(info),preset=state.selection;let response;
      if(selected.ae){
        const session=selected.ae.session;if(!session?.capability)throw Error('The AE session has ended.');
        const query=new URLSearchParams({index:String(index),config:preset.config,display:preset.display,view:preset.view});
        response=await selected.ae.api.fetchApi(AE_ROOT+'/'+encodeURIComponent(session.id)+'/display-frame?'+query,{headers:{'X-ComfyLink-Studio-Session':session.capability},signal:controller.signal});
      }else{
        const token=selected.paint?await grantPaintSource(selected.paint.workspace,selected.paint.file,controller.signal,this.paintGrants):null;
        if(!this.current(revision,state,selected,controller))return;
        response=await this.settings.api.fetchApi('/zura/studio/display/frame',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
          body:JSON.stringify({source:token?{source_token:token}:selected.selector,frame:index,colour_space:selected.colour||'auto',config:preset.config,display:preset.display,view:preset.view})});
      }
      await this.settings.response(response);if(!this.current(revision,state,selected,controller))return;
      const blob=await response.blob();if(!this.current(revision,state,selected,controller))return;
      this.release();const url=URL.createObjectURL(blob),overlay=this.settings.root.ownerDocument.createElement('img');
      overlay.className='zc-colour-inline';overlay.alt='Preview through the global colour transform';overlay.src=url;
      this.inline={url,overlay};this.settings.root.append(overlay);this.updatePosition();
      this.report('Display only. Source and exports are unchanged.');
    }catch(error){if(error.name!=='AbortError'&&this.current(revision,state,selected,controller)){this.release();this.report(error.message||'Display preview unavailable.',true);this.settings.status.textContent=error.message||'Display preview unavailable.';}}
  }
  updatePosition(){
    if(!this.inline)return;if(this.media.isConnected===false){this.release();return;}
    const doc=this.settings.root.ownerDocument,fullscreen=doc.fullscreenElement;
    const parent=fullscreen?.contains?.(this.media)&&fullscreen.tagName!=='VIDEO'?fullscreen:this.settings.root;
    if(this.inline.overlay.parentNode!==parent)parent.append(this.inline.overlay);
    const rect=this.media.getBoundingClientRect?.();if(!rect)return;
    Object.assign(this.inline.overlay.style,{left:`${Math.max(0,rect.left)}px`,top:`${Math.max(0,rect.top)}px`,width:`${Math.max(0,rect.width)}px`,height:`${Math.max(0,rect.height)}px`});
  }
  release(){if(this.inline){if(this.inline.url)URL.revokeObjectURL(this.inline.url);this.inline.overlay.remove();this.inline=null;}}
  cancel(){clearTimeout(this.timer);this.timer=null;clearTimeout(this.videoFrameTimer);this.videoFrameTimer=null;if(this.videoFrameHandle!==null)this.media.cancelVideoFrameCallback?.(this.videoFrameHandle);this.videoFrameHandle=null;this.unmanagedVideo=null;++this.revision;this.controller?.abort();this.controller=null;this.release();}
  close(){if(this.closed)return;this.closed=true;this.cancel();this.restoreVideo();if(this.onVideoEvent){for(const event of ['play','pause','seeked','loadeddata','emptied'])this.media.removeEventListener?.(event,this.onVideoEvent);}else{for(const event of ['load','pause','seeked','loadeddata'])this.media.removeEventListener?.(event,this.onFollow);for(const event of ['play','seeking','emptied'])this.media.removeEventListener?.(event,this.onInvalidate);}}
}

// The paint editor renders its source and brush in one canvas. Change only the
// bitmap it draws beneath the mask; never replace the canvas or its source.
export function paintPreviewSource(url,origin){
  try{
    const parsed=new URL(url,origin);
    if(parsed.origin!==origin||parsed.pathname!=='/zura/paintout/frame-preview')return null;
    const file=parsed.searchParams.get('file'),frame=Number(parsed.searchParams.get('frame')),space=parsed.searchParams.get('space')||'auto';
    if(!file||!Number.isSafeInteger(frame)||frame<0||frame>=10000)return null;
    return {file,frame,space};
  }catch{return null;}
}

export function knownPaintPreviewFile(workspace,file){
  if(!file||typeof file!=='string')return false;
  if(file===workspace.state?.source)return true;
  const candidates=[workspace.editor?.candidate,...(workspace.state?.anchors||[]),...(workspace.state?.anchors||[]).map(anchor=>anchor?.candidate)];
  return candidates.some(item=>item&&[item.file,item.preview_file,item.png_file].includes(file));
}

async function grantPaintSource(workspace,file,signal,cache){
  const source=workspace.state?.source===file?workspace.sourceInfo:workspace.state?.mask===file?workspace.maskInfo:null;
  if(source?.display_source)return source.display_source;
  const saved=cache.get(file);if(saved&&saved.expires>Date.now())return saved.token;
  const info=await workspace.info(file);
  if(signal.aborted)return null;
  if(!info?.display_source)throw Error(info?.display_preview_error||'Reload this media to enable its colour preview.');
  cache.set(file,{token:info.display_source,expires:Date.now()+30*60*1000});
  return info.display_source;
}

export class StudioPaintDisplayBinding{
  constructor(settings,workspace,viewer){
    this.settings=settings;this.workspace=workspace;this.viewer=viewer;this.closed=false;this.revision=0;this.grants=new Map();this.signature=null;
    this.onSource=()=>this.refresh();viewer.onDisplaySourceChange=this.onSource;this.refresh();
  }
  current(revision,state,url,controller){
    return !this.closed&&!this.settings.closed&&this.revision===revision&&this.controller===controller&&!controller.signal.aborted
      &&this.settings.displayStore.get().revision===state.revision&&this.viewer.displaySourceURL===url
      &&this.settings.root.contains(this.viewer.root)&&!this.viewer.root.closest?.('[hidden]')&&!this.workspace.page?.hidden;
  }
  refresh(){
    if(this.closed)return;
    const state=this.settings.displayStore.get(),url=this.viewer.displaySourceURL;
    const signature=JSON.stringify([state.revision,url]);if(signature===this.signature)return;this.signature=signature;this.cancel();
    if(!state.selection||state.selection.view==='Raw'||!url)return;
    const origin=this.settings.root.ownerDocument.defaultView?.location?.origin;
    const source=origin&&paintPreviewSource(url,origin);
    if(!source||!knownPaintPreviewFile(this.workspace,source.file)){this.viewer.root.title='This paint preview cannot use the selected colour transform.';return;}
    this.timer=setTimeout(()=>void this.render(state,url,source),75);this.timer?.unref?.();
  }
  async grant(file,signal){
    return grantPaintSource(this.workspace,file,signal,this.grants);
  }
  async render(state,url,source){
    const revision=++this.revision,controller=new AbortController();this.controller=controller;
    try{
      const token=await this.grant(source.file,controller.signal);if(!this.current(revision,state,url,controller))return;
      const preset=state.selection,response=await this.settings.api.fetchApi('/zura/studio/display/frame',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
        body:JSON.stringify({source:{source_token:token},frame:source.frame,colour_space:source.space,config:preset.config,display:preset.display,view:preset.view})});
      await this.settings.response(response);if(!this.current(revision,state,url,controller))return;
      const blob=await response.blob();if(!this.current(revision,state,url,controller))return;
      const objectURL=URL.createObjectURL(blob);
      try{await this.viewer.setColourDisplayImage(objectURL,url);}finally{URL.revokeObjectURL(objectURL);}
      if(this.current(revision,state,url,controller))this.viewer.root.title='Display only. Source, masks and exports are unchanged.';
    }catch(error){if(error.name!=='AbortError'&&this.current(revision,state,url,controller)){this.viewer.root.title=error.message||'Colour preview unavailable.';this.settings.status.textContent=error.message||'Colour preview unavailable.';}}
  }
  cancel(){clearTimeout(this.timer);this.timer=null;++this.revision;this.controller?.abort();this.controller=null;this.viewer.clearColourDisplay();}
  close(){if(this.closed)return;this.closed=true;this.cancel();if(this.viewer.onDisplaySourceChange===this.onSource)this.viewer.onDisplaySourceChange=null;}
}

/** Image Edit paints on a separate PaintoutMaskViewer, not the normal gallery. */
export class StudioImageAreaDisplayBinding{
  constructor(settings,area,viewer){
    this.settings=settings;this.area=area;this.viewer=viewer;this.closed=false;this.revision=0;this.signature=null;
    this.previousOnSource=viewer.onDisplaySourceChange;
    this.onSource=()=>{this.previousOnSource?.();this.refresh();};viewer.onDisplaySourceChange=this.onSource;this.refresh();
  }
  current(revision,state,url,controller){
    return !this.closed&&!this.settings.closed&&this.revision===revision&&this.controller===controller&&!controller.signal.aborted&&
      this.settings.displayStore.get().revision===state.revision&&this.viewer.displaySourceURL===url&&
      this.settings.owner.imageArea?.viewer===this.viewer&&!this.area.host.hidden;
  }
  refresh(){
    if(this.closed)return;
    const state=this.settings.displayStore.get(),url=this.viewer.displaySourceURL,
      baseline=!state.selection&&verifiedUnmanaged(this.settings)&&this.settings.aeModelInputFile?.(this.area.source?.()),
      signature=JSON.stringify([state.revision,url,baseline]);
    if(signature===this.signature)return;this.signature=signature;this.cancel();
    if((!state.selection&&!baseline)||state.selection?.view==='Raw'||!url)return;
    if(isUnmanagedICCDisplay(state.selection)&&!verifiedUnmanaged(this.settings))return;
    this.timer=setTimeout(()=>void this.render(state,url,baseline),0);this.timer?.unref?.();
  }
  async render(state,url,baseline=false){
    const revision=++this.revision,controller=new AbortController();this.controller=controller;
    try{
      let blob;
      if(baseline||isUnmanagedICCDisplay(state.selection)){
        if(this.viewer.image?.decode)await this.viewer.image.decode();
        if(!this.current(revision,state,url,controller))return;
        blob=await pngBlob(inverseSRGBCanvas(this.viewer.image,this.settings.root.ownerDocument));
      }else{
        const source=this.area.source?.(),preset=state.selection;
        if(!source?.filename)throw Error('Reload the image source to enable its colour preview.');
        const response=await this.settings.api.fetchApi('/zura/studio/display/frame',{
          method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
          body:JSON.stringify({source:{file:{filename:source.filename,subfolder:source.subfolder||'',type:source.type||'input'}},frame:0,
            colour_space:source.colour_space||'auto',config:preset.config,display:preset.display,view:preset.view})});
        await this.settings.response(response);if(!this.current(revision,state,url,controller))return;
        blob=await response.blob();
      }
      if(!this.current(revision,state,url,controller))return;
      const objectURL=URL.createObjectURL(blob);
      try{await this.viewer.setColourDisplayImage(objectURL,url);}finally{URL.revokeObjectURL(objectURL);}
      if(this.current(revision,state,url,controller))this.viewer.root.title='Display only. Source, model input, mask and export are unchanged.';
    }catch(error){if(error.name!=='AbortError'&&this.current(revision,state,url,controller)){this.viewer.root.title=error.message||'Paint preview unavailable.';this.settings.status.textContent=error.message||'Paint preview unavailable.';}}
  }
  cancel(){clearTimeout(this.timer);this.timer=null;++this.revision;this.controller?.abort();this.controller=null;this.viewer.clearColourDisplay();}
  close(){if(this.closed)return;this.closed=true;this.cancel();if(this.viewer.onDisplaySourceChange===this.onSource)this.viewer.onDisplaySourceChange=this.previousOnSource||null;}
}

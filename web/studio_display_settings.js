import {workspaceStorage} from './studio_storage.js';
import {activeStudioMode} from './studio_mode_adapters.js';
import {AEFloatDisplay} from './studio_ae_display.js';

const KEY='zura-studio-display-view-v1';
const AE_ROOT='/zura/comfylink/v1/studio/sessions';
const SPACES=new Set(['srgb_display','rec709_oetf','rec709_gamma24','linear_rec709','acescg','acescct','hlg_rec2020','pq_rec2020','pq_display_p3']);
const safeFile=(file,type)=>file&&typeof file.filename==='string'?{filename:file.filename,subfolder:file.subfolder||'',type:file.type||type}:null;
export const displayPresetKey=preset=>JSON.stringify([preset.config,preset.display,preset.view]);
export function studioDisplayPresets(config){
  const presets=config.presets||config.displays.flatMap(display=>display.views.map(view=>({config:config.config,display:display.name,view,
    label:view==='Un-tone-mapped'?display.name.replace(/ - Display$/,''):`${display.name.replace(/ - Display$/,'')} · ${view}`})));
  return presets.filter(preset=>['config','display','view'].every(key=>typeof preset[key]==='string'&&preset[key].length>0&&preset[key].length<512));
}

function replaceOptions(select,items,selected){
  const doc=select.ownerDocument;select.replaceChildren();
  for(const item of items){const option=doc.createElement('option');option.value=item.value??item.name;option.textContent=item.label??item.name;select.append(option);}
  if(selected!==undefined&&items.some(item=>(item.value??item.name)===selected))select.value=selected;
}

/** Describe an original, never the already tone-mapped thumbnail URL. */
export function studioDisplaySource(source,type='input'){
  if(!source)return null;
  const bound=source.processingView?.originalSource?.displaySelector;
  if(typeof bound?.imported_frame==='string')return {imported_frame:bound.imported_frame};
  if(source.display_source)return {source_token:source.display_source};
  if(typeof source.studioAssetId==='string'&&/^[a-f0-9]{32}$/.test(source.studioAssetId))return {asset_id:source.studioAssetId,...(Number.isFinite(source.frame_time)?{frame_time:source.frame_time}:{})};
  const original=source.native_hdr?.asset_id||source.native_hdr?.source_id;
  if(original)return {asset_id:original,...(source.native_hdr?.source_id&&Number.isFinite(source.native_hdr.start_seconds)?{frame_time:source.native_hdr.start_seconds}:{})};
  if(source.studioAsset?.id)return {asset_id:source.studioAsset.id};
  if(source.id&&source.kind==='asset')return {asset_id:source.id};
  if(source.media_url)return {media_url:source.media_url};
  const file=safeFile(typeof source.file==='object'?source.file:source,type);
  if(file)return {file};
  if(typeof source.file==='string'&&!/^([A-Za-z]:|[\\/]|[a-z]+:\/\/)/i.test(source.file)){
    const parts=source.file.replaceAll('\\','/').split('/'),filename=parts.pop();
    return {file:{filename,subfolder:parts.join('/'),type:source.type||type}};
  }
  return null;
}

export class StudioDisplaySettings {
  constructor(root,api,owner,delivery){
    this.root=root;this.api=api;this.owner=owner;this.delivery=delivery;this.storage=workspaceStorage(owner);this.revision=0;this.closed=false;
    try{this.saved=JSON.parse(this.storage.getItem(KEY))||{};}catch{this.saved={};}
    const doc=root.ownerDocument,style=doc.createElement('link');style.rel='stylesheet';style.href=new URL('./studio_display_settings.css',import.meta.url).href;doc.head.append(style);
    this.button=doc.createElement('button');this.button.type='button';this.button.className='zc-display-trigger';this.button.setAttribute('aria-label','Display transform');this.button.title='OCIO display preview. Source and exported masters stay unchanged.';this.button.onclick=()=>void this.openMenu();delivery.displayHost.append(this.button);
    this.menu=new StudioDisplayMenu(root,this);
    const sync=delivery.sync;delivery.sync=(...args)=>{const value=sync.apply(delivery,args);this.sync();return value;};
    const close=owner.close;if(typeof close==='function')owner.close=(...args)=>{this.close();return close.apply(owner,args);};
    this.sync();
  }
  save(){try{this.storage.setItem(KEY,JSON.stringify(this.saved));}catch{}this.sync();}
  choices(){
    const mode=activeStudioMode(this.owner),w=this.delivery.workspace(mode),source=this.delivery.source(w),ae=this.owner.studio?.aeBridge;
    const input=this.delivery.input(w),selector=studioDisplaySource(source);
    const explicit=Object.prototype.hasOwnProperty.call(this.delivery.inputOverrides||{},this.delivery.sourceKey(w));
    const sourceColour=explicit&&SPACES.has(input.space)?input.space:'auto';
    const count=source?.frameCount||source?.manifest?.frames?.length||source?.frames||source?.count;
    const original=ae?.source?{ae,which:'source',key:'ae:'+ae.session.id,count:ae.source.frameCount,label:'After Effects source'}
      :selector?{selector,which:'source',key:JSON.stringify(selector)+':'+sourceColour,count:Number.isSafeInteger(count)?count:undefined,colour:sourceColour,label:'Original source'}:null;
    const base=this.delivery.raw(mode),raw=this.delivery.outputFor(mode,base)||base;
    const master=raw?.master,ref=safeFile(master,'output');
    const result=ref?{selector:{file:ref},which:'result',key:JSON.stringify(ref),count:Number.isSafeInteger(raw.frameCount)?raw.frameCount:undefined,colour:SPACES.has(raw.colour?.encoding)?raw.colour.encoding:'auto',label:'Selected result'}:null;
    return {original,result};
  }
  current(){const {original,result}=this.choices();return this.saved.which==='source'?original||result:this.saved.which==='result'?result||original:result||original;}
  currentFor(target){
    const {original,result}=this.choices();
    if(target?.closest?.('.zc-image-source'))return original||result;
    if(target?.closest?.('.zc-gallery'))return result||original;
    return this.current();
  }
  mediaTarget(target){
    if(!target?.closest||!this.root.contains(target))return null;
    const host=target.closest('.gs-canvas,.zc-image-source,.zc-image-comparison,.zc-gallery figure');
    if(!host||target.closest('.zc-reference,.gs-source-upload,.zhe-viewport,.pano-studio-root'))return null;
    const media=target.closest('img,video')||host.querySelector('img:not([hidden]),video:not([hidden])');
    if(!media||(host.matches('.zc-gallery figure')&&!target.closest('img')))return null;
    const selected=this.currentFor(host);
    return selected?{host,media,selected}:null;
  }
  async loadConfig(name,signal){
    const response=await this.api.fetchApi('/zura/studio/display/config'+(name?'?'+new URLSearchParams({config:name}):''),{signal});
    if(!response.ok){let message;try{message=(await response.json()).error;}catch{};throw Error(message||'OpenColorIO display settings are unavailable');}
    return response.json();
  }
  async openMenu(){
    if(this.closed)return;
    const candidates=this.root.querySelectorAll('.gs-canvas img,.gs-canvas video,.zc-image-source img,.zc-image-comparison img,.zc-gallery figure img');
    const target=[...candidates].filter(media=>!media.hidden&&!media.closest('[hidden]')).map(media=>this.mediaTarget(media)).find(Boolean);
    const rect=this.button.getBoundingClientRect();
    await this.menu.open(target||{host:this.root,media:null,selected:this.current()},{clientX:rect.left,clientY:rect.bottom+8});
  }
  sync(){
    if(this.closed)return;
    const display=this.saved.display||'sRGB - Display',label=this.saved.label||display.replace(/ - Display$/,'');
    const pausedOnly=this.menu?.transformEnabled&&this.menu.media?.tagName==='VIDEO'&&this.menu.media.paused===false;
    const error=this.menu?.error,failed=error&&error.key===this.currentFor(this.menu.active?.host)?.key;
    this.button.textContent=(failed?'View unavailable: ':pausedOnly?'View (paused only): ':'View: ')+label;
    this.button.title=failed?error.text:pausedOnly?'Pause video to see this display transform. Playback uses the source display.':'Display only. Source and exported masters stay unchanged.';
    const selected=this.current(),key=selected?.key||'';
    if(this.view?.root&&this.currentKey!==key)this.closeViewer();
    if(this.menu?.inline&&this.menu.inline.key!==this.currentFor(this.menu.active?.host)?.key)this.menu.closeInline();
    this.button.disabled=false;
  }
  capture(view){
    if(!view.root)return;
    Object.assign(this.saved,{config:view.selectConfig.value,display:view.selectDisplay.value,view:view.selectView.value});delete this.saved.label;this.save();
  }
  async response(response){
    if(response.ok)return response;
    let message;try{message=(await response.json()).error;}catch{}
    throw Error(message||'The original media is unavailable for this display preview. Reload the source.');
  }
  async open(){
    if(this.closed)return;this.closeViewer();const revision=++this.revision,selected=this.current();this.currentKey=selected?.key||'';
    const local={closed:false,studio:{container:this.root},source:{frameCount:selected?.count||1}};
    let view;
    if(selected?.ae){view=selected.ae.display;}
    else{
      view=new AEFloatDisplay(local,{title:'Colour preview',imageAlt:'Original media through the selected OCIO display transform',frameCount:selected?.count||1,
        previewNote:response=>{const space=response.headers?.get?.('X-Zura-Display-Source');return space?`Original ${space} · display preview only`:'Display preview only';},
        configRequest:(config,signal)=>this.api.fetchApi('/zura/studio/display/config'+(config?'?'+new URLSearchParams({config}):''),{signal}).then(response=>this.response(response)),
        frameRequest:async(query,signal)=>{
          if(!selected?.selector)throw Error('Load original media or select a finished result to preview its colour.');
          const response=await this.api.fetchApi('/zura/studio/display/frame',{method:'POST',headers:{'Content-Type':'application/json'},signal,body:JSON.stringify({source:selected.selector,frame:Number(query.get('index')),colour_space:selected.colour,config:query.get('config'),display:query.get('display'),view:query.get('view')})});
          await this.response(response);
          const count=Number(response.headers?.get?.('X-Zura-Display-Frames'));
          if(view.root&&Number.isSafeInteger(count)&&count>=1&&count<=10000){view.frameCount=count;view.slider.max=String(count-1);view.slider.disabled=count<=1;view.position.textContent=`${Number(view.slider.value)+1} / ${count}`;}
          return response;
        }});
      this.localBridge=local;
    }
    this.view=view;await view.open();
    if(this.closed||revision!==this.revision||!view.root)return;
    view.root.classList.add('zc-studio-display');
    const choices=this.choices(),doc=this.root.ownerDocument,label=doc.createElement('label'),select=doc.createElement('select');label.className='zc-display-source-choice';label.append(doc.createTextNode('Show '),select);select.setAttribute('aria-label','Colour preview media');
    for(const [value,text,available] of [['source','Original source',choices.original],['result','Selected result',choices.result]]){const option=doc.createElement('option');option.value=value;option.textContent=text;option.disabled=!available;select.append(option);}
    select.value=selected?.which||'source';select.onchange=()=>{this.saved.which=select.value;this.save();void this.open();};view.root.querySelector('.zc-display-controls').before(label);
    if(selected?.ae)view.root.querySelector('h2').textContent='After Effects source · colour preview';
    if(this.saved.config&&view.config?.configs?.some(item=>item.name===this.saved.config)&&view.config.config!==this.saved.config)await view.loadConfig(this.saved.config);
    if(this.closed||revision!==this.revision||!view.root)return;
    const chosen=view.config?.displays?.find(item=>item.name===this.saved.display);let changed=false;
    if(chosen){changed=view.selectDisplay.value!==chosen.name;view.selectDisplay.value=chosen.name;view.setViews(chosen.name,this.saved.view);changed=changed||view.selectView.value!==view.config.view;}
    if(changed)await view.render();
    view.selectConfig.onchange=async()=>{await view.loadConfig(view.selectConfig.value);this.capture(view);};
    const displayChange=view.selectDisplay.onchange,viewChange=view.selectView.onchange;
    view.selectDisplay.onchange=event=>{displayChange(event);this.capture(view);};view.selectView.onchange=event=>{viewChange(event);this.capture(view);};
    this.capture(view);
  }
  closeViewer(){++this.revision;if(this.localBridge)this.localBridge.closed=true;this.localBridge=null;this.view?.close();this.view=null;}
  close(){if(this.closed)return;this.closed=true;this.menu?.dispose();this.closeViewer();this.button.remove();}
}

class StudioDisplayMenu {
  constructor(root,settings){
    this.root=root;this.settings=settings;this.document=root.ownerDocument;this.view=this.document.defaultView;
    this.revision=0;this.previewRevision=0;this.inline=null;this.active=null;this.config=null;this.closed=false;
    this.previewController=null;this.media=null;this.mediaCleanup=null;this.transformEnabled=false;
    this.onContext=event=>this.context(event);
    this.onOutside=event=>{if(!this.element||this.element.hidden)return;const path=event.composedPath?.()||[event.target];if(!path.includes(this.element))this.close();};
    this.onKey=event=>{if(event.key!=='Escape'||!this.element||this.element.hidden)return;this.close();event.preventDefault();event.stopPropagation();};
    this.onMove=()=>{if(this.active)this.position();this.updateInline();};
    root.addEventListener('contextmenu',this.onContext);
    this.document.addEventListener('pointerdown',this.onOutside,true);
    this.document.addEventListener('keydown',this.onKey,true);
    this.view?.addEventListener?.('resize',this.onMove);
    this.document.addEventListener('scroll',this.onMove,true);
  }
  mount(){
    if(this.element)return;
    const menu=this.document.createElement('section');
    menu.className='zc-colour-menu';menu.hidden=true;menu.tabIndex=-1;
    menu.setAttribute('role','dialog');menu.setAttribute('aria-label','Viewer colour');
    menu.innerHTML=`<div class="zc-colour-menu-head"><strong>Display transform</strong><button type="button" data-colour-close aria-label="Close colour menu">Close</button></div>
      <label>View<select data-colour-preset aria-label="Display transform preset"></select></label>
      <p class="zc-colour-menu-status" role="status" aria-live="polite"></p>
      <div class="zc-colour-menu-actions"><button type="button" data-colour-reset>Reset to sRGB</button></div>`;
    this.root.append(menu);this.element=menu;
    this.presetSelect=menu.querySelector('[data-colour-preset]');
    this.status=menu.querySelector('.zc-colour-menu-status');
    menu.querySelector('[data-colour-close]').onclick=()=>this.close();
    menu.querySelector('[data-colour-reset]').onclick=()=>this.selectPreset(this.defaultPreset);
    this.presetSelect.onchange=()=>this.selectPreset(this.presets.find(preset=>displayPresetKey(preset)===this.presetSelect.value));
  }
  async context(event){
    const target=this.settings.mediaTarget(event.target);if(!target)return;
    event.preventDefault();
    await this.open(target,event);
  }
  async open(target,event){
    if(this.closed)return;
    this.mount();this.closeInline();this.revision++;this.bindMedia(target.media);this.active={...target,event,focus:this.document.activeElement};
    this.element.hidden=false;
    this.position();
    this.element.focus({preventScroll:true});
    await this.loadConfig(this.settings.saved.config||'');
    if(this.element&&!this.element.hidden&&this.active?.host===target.host)this.presetSelect.focus({preventScroll:true});
  }
  async loadConfig(name){
    const revision=++this.revision;
    this.config=null;
    this.status.textContent='Loading display settings…';
    replaceOptions(this.presetSelect,[{value:'',label:'Loading…'}],'');this.presetSelect.disabled=true;
    try{
      const selected=this.active?.selected;let config;
      if(selected?.ae){
        const session=selected.ae.session;
        if(!session?.id||!session.capability||selected.ae.closed)throw Error('The After Effects session has ended.');
        const response=await selected.ae.api.fetchApi(AE_ROOT+'/'+encodeURIComponent(session.id)+'/display-config'+(name?'?'+new URLSearchParams({config:name}):''),{headers:{'X-ComfyLink-Studio-Session':session.capability}});
        await this.settings.response(response);config=await response.json();
      }else config=await this.settings.loadConfig(name);
      if(this.closed||!this.element||revision!==this.revision||this.element.hidden)return;
      this.config=config;this.presets=studioDisplayPresets(config);
      this.defaultPreset=this.presets.find(preset=>preset.display==='sRGB - Display'&&preset.view==='Un-tone-mapped')||this.presets[0];
      const saved=this.presets.find(preset=>displayPresetKey(preset)===displayPresetKey(this.settings.saved))
        ||this.presets.find(preset=>preset.display===this.settings.saved.display&&preset.view===this.settings.saved.view)||this.defaultPreset;
      replaceOptions(this.presetSelect,this.presets.map(preset=>({value:displayPresetKey(preset),label:preset.label})),saved&&displayPresetKey(saved));this.presetSelect.disabled=!this.presets.length;
      if(!saved)throw Error('No qualified display transforms are available.');
      this.selectPreset(saved);
    }catch(error){if(revision===this.revision&&this.element)this.status.textContent=error.message||'Display settings are unavailable.';}
  }
  selectPreset(preset){
    if(this.closed||!preset)return;
    this.closeInline();this.error=null;this.preset=preset;this.presetSelect.value=displayPresetKey(preset);this.transformEnabled=true;
    Object.assign(this.settings.saved,preset);this.settings.save();this.schedule();
  }
  schedule(){
    clearTimeout(this.timer);this.cancelPreview();
    this.timer=setTimeout(()=>void this.apply(),100);
  }
  bindMedia(media){
    if(this.media===media)return;
    this.unbindMedia();this.media=media;
    if(media?.tagName!=='VIDEO'||typeof media.addEventListener!=='function')return;
    const invalidate=()=>{
      this.closeInline();
      this.status.textContent='Playback shows the source display. Pause to view this transform.';
      this.error=null;this.settings.sync();
    };
    const follow=()=>{if(this.transformEnabled&&media.paused!==false&&this.active?.media===media)this.schedule();};
    media.addEventListener('play',invalidate);media.addEventListener('seeking',invalidate);media.addEventListener('emptied',invalidate);
    media.addEventListener('seeked',follow);media.addEventListener('pause',follow);
    this.mediaCleanup=()=>{media.removeEventListener?.('play',invalidate);media.removeEventListener?.('seeking',invalidate);media.removeEventListener?.('emptied',invalidate);media.removeEventListener?.('seeked',follow);media.removeEventListener?.('pause',follow);};
  }
  unbindMedia(){this.mediaCleanup?.();this.mediaCleanup=null;this.media=null;}
  cancelPreview(){
    clearTimeout(this.timer);this.timer=null;
    ++this.previewRevision;this.previewController?.abort();this.previewController=null;
    this.element?.removeAttribute('aria-busy');
  }
  currentPreview(revision,target,key,controller){
    return !this.closed&&this.previewRevision===revision&&this.previewController===controller
      &&this.active?.media===target&&this.settings.currentFor(this.active?.host)?.key===key
      &&this.active?.selected?.ae?.closed!==true&&target?.isConnected!==false&&!controller.signal.aborted&&!(target?.tagName==='VIDEO'&&target.paused===false);
  }
  async sourceInfo(selected,signal){
    if(selected?.ae){
      const count=Number(selected.count);
      if(!Number.isSafeInteger(count)||count<1||count>10000)throw Error('The verified After Effects source has no valid frame count.');
      const rate=selected.ae.source?.manifest?.frameRate||selected.ae.source?.rate||null;
      return {kind:count===1?'image':'sequence',frame_count:count,frame_rate:rate};
    }
    if(!selected?.selector)throw Error('Load original media or select a finished result to preview its colour.');
    const response=await this.settings.api.fetchApi('/zura/studio/display/info',{
      method:'POST',headers:{'Content-Type':'application/json'},signal,body:JSON.stringify({source:selected.selector}),
    });
    await this.settings.response(response);
    const value=await response.json(),count=Number(value.frame_count);
    if(!Number.isSafeInteger(count)||count<1||count>10000)throw Error('The original source has no valid frame count.');
    return {...value,frame_count:count};
  }
  targetFrame(media,info){
    const count=Number(info?.frame_count);
    if(!Number.isSafeInteger(count)||count<1||count>10000)throw Error('The original source has no valid frame count.');
    if(count===1||media?.tagName!=='VIDEO')return 0;
    const current=Number(media.currentTime),rate=info.frame_rate;
    const fps=rate&&Number(rate.numerator)>0&&Number(rate.denominator)>0
      ?Number(rate.numerator)/Number(rate.denominator):null;
    if(Number.isFinite(current)&&fps)return Math.max(0,Math.min(count-1,Math.floor((current+1e-7)*fps)));
    const duration=Number(media.duration);
    if(Number.isFinite(current)&&Number.isFinite(duration)&&duration>0){
      return Math.max(0,Math.min(count-1,Math.floor(current/duration*count)));
    }
    throw Error('The original video timing is unavailable. Pause and reload the source before previewing.');
  }
  async apply(){
    if(this.closed||!this.active||!this.preset)return;
    const target=this.active.media,selected=this.settings.currentFor(this.active.host)||this.active.selected;
    if(!target){this.status.textContent=selected?'This viewport does not support an inline display transform.':'Load media to view this transform. Exports are unchanged.';if(selected){this.error={key:selected.key,text:this.status.textContent};this.settings.sync();}return;}
    if(!selected?.ae&&!selected?.selector){this.status.textContent='Load original media or select a finished result to preview its colour.';return;}
    if(selected?.ae&&(!selected.ae.api||selected.ae.closed)){this.status.textContent='The After Effects session has ended.';return;}
    if(target?.tagName==='VIDEO'&&target.paused===false){this.status.textContent='Pause the video before preparing a display-frame preview.';return;}
    const key=selected.key,revision=++this.previewRevision;this.previewController?.abort();
    const controller=new AbortController();this.previewController=controller;
    const preset={...this.preset};this.element.setAttribute('aria-busy','true');this.status.textContent='Updating view…';
    try{
      const info=await this.sourceInfo(selected,controller.signal);
      if(!this.currentPreview(revision,target,key,controller))return;
      const index=this.targetFrame(target,info),query=new URLSearchParams({index:String(index),
        config:preset.config,display:preset.display,view:preset.view});
      let response;
      if(selected.ae){
        const session=selected.ae.session;
        if(!session?.id||!session.capability)throw Error('The After Effects session has ended.');
        response=await selected.ae.api.fetchApi(AE_ROOT+'/'+encodeURIComponent(session.id)+'/display-frame?'+query,{
          headers:{'X-ComfyLink-Studio-Session':session.capability},signal:controller.signal,
        });
      }else{
        response=await this.settings.api.fetchApi('/zura/studio/display/frame',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({
          source:selected.selector,frame:index,colour_space:selected.colour||'auto',
          config:query.get('config'),display:query.get('display'),view:query.get('view'),
        })});
      }
      await this.settings.response(response);
      if(!this.currentPreview(revision,target,key,controller))return;
      const blob=await response.blob();
      if(!this.currentPreview(revision,target,key,controller))return;
      this.releaseInline();
      const url=URL.createObjectURL(blob),overlay=this.document.createElement('img');
      overlay.className='zc-colour-inline';overlay.alt='Original Studio media through the selected OCIO display transform';
      overlay.src=url;this.root.append(overlay);
      this.inline={url,overlay,target,key};
      this.updateInline();
      this.error=null;this.settings.sync();
      this.status.textContent=target.tagName==='VIDEO'
        ?'Paused-frame view. Playback shows the source display.'
        :'Display only. Source and exports are unchanged.';
    }catch(error){
      if(error.name!=='AbortError'&&this.currentPreview(revision,target,key,controller)){
        this.releaseInline();this.status.textContent=error.message||'Preview unavailable.';this.error={key,text:this.status.textContent};this.settings.sync();
      }
    }finally{if(this.previewRevision===revision)this.element?.removeAttribute('aria-busy');}
  }
  updateInline(){
    if(!this.inline?.target?.isConnected){this.closeInline();return;}
    const rect=this.inline.target.getBoundingClientRect?.();
    if(!rect)return;
    Object.assign(this.inline.overlay.style,{left:`${Math.max(0,rect.left)}px`,top:`${Math.max(0,rect.top)}px`,
      width:`${Math.max(0,rect.width)}px`,height:`${Math.max(0,rect.height)}px`});
  }
  position(){
    if(!this.element||this.element.hidden)return;
    const width=this.element.getBoundingClientRect?.().width||304,height=this.element.getBoundingClientRect?.().height||190;
    const point=this.active?.event||{clientX:8,clientY:8},margin=8;
    Object.assign(this.element.style,{left:`${Math.max(margin,Math.min(point.clientX,this.view?.innerWidth-width-margin||margin))}px`,
      top:`${Math.max(margin,Math.min(point.clientY,this.view?.innerHeight-height-margin||margin))}px`});
  }
  releaseInline(){
    if(!this.inline)return;
    URL.revokeObjectURL(this.inline.url);this.inline.overlay.remove();this.inline=null;
  }
  closeInline(){this.cancelPreview();this.releaseInline();}
  close(){
    if(!this.element||this.element.hidden)return;
    this.element.hidden=true;++this.revision;
    if(this.active?.focus?.isConnected&&!this.element.contains(this.active.focus))this.active.focus.focus?.({preventScroll:true});
    // The chosen view remains attached to its source after dismissing settings.
    // Source identity, request revision and media events still fence every frame.
  }
  dispose(){
    if(this.element&&!this.element.hidden){this.element.hidden=true;++this.revision;}
    this.cancelPreview();this.unbindMedia();
    this.active=null;this.config=null;
    this.closeInline();this.root.removeEventListener('contextmenu',this.onContext);
    this.document.removeEventListener('pointerdown',this.onOutside,true);this.document.removeEventListener('keydown',this.onKey,true);
    this.document.removeEventListener('scroll',this.onMove,true);this.view?.removeEventListener?.('resize',this.onMove);this.element?.remove();this.element=null;this.closed=true;
  }
}

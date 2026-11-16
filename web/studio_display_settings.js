import {workspaceStorage} from './studio_storage.js';
import {activeStudioMode} from './studio_mode_adapters.js';
import {AEFloatDisplay,colourTransforms} from './studio_ae_display.js';
import {studioDisplayTransform,displayPreviewOwner,UNMANAGED_ICC_DISPLAY,isUnmanagedICCDisplay,verifiedICCPreviewSource} from './studio_display_state.js';
import {StudioDisplayBinding,StudioPaintDisplayBinding,StudioImageAreaDisplayBinding,paintPreviewSource,knownPaintPreviewFile} from './studio_display_binding.js';

const KEY='zura-studio-preview-media-v2';
const AE_ROOT='/zura/comfylink/v1/studio/sessions';
const SPACES=new Set(['srgb_display','rec709_oetf','rec709_gamma24','linear_rec709','acescg','acescct','hlg_rec2020','pq_rec2020','pq_display_p3']);
const safeFile=(file,type)=>file&&typeof file.filename==='string'?{filename:file.filename,subfolder:file.subfolder||'',type:file.type||type}:null;
export const displayPresetKey=preset=>JSON.stringify([preset.config,preset.display,preset.view]);
export function studioDisplayPresets(config){
  return colourTransforms(config);
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
  constructor(root,api,owner,delivery,{store=studioDisplayTransform}={}){
    this.root=root;this.api=api;this.owner=owner;this.delivery=delivery;this.storage=workspaceStorage(owner);this.revision=0;this.closed=false;
    this.displayStore=store;this.bindings=new Map();this.paintBindings=new Map();this.videoSources=new WeakMap();this.saved={};this.iccPresetIncluded=null;this.imageAreaBinding=null;
    try{const saved=JSON.parse(this.storage.getItem(KEY));if(['source','result'].includes(saved?.which))this.saved.which=saved.which;}catch{}
    const doc=root.ownerDocument,style=doc.createElement('link');style.rel='stylesheet';style.href=new URL('./studio_display_settings.css',import.meta.url).href;doc.head.append(style);
    this.control=doc.createElement('label');this.control.className='zc-global-colour-transform';this.control.append(doc.createTextNode('Colour transform '));
    this.select=doc.createElement('select');this.select.setAttribute('aria-label','Colour transform');this.select.title='Display only. Source and exported masters stay unchanged.';
    this.control.append(this.select);
    this.status=doc.createElement('output');this.status.className='zc-global-colour-status';this.status.setAttribute('role','status');this.status.setAttribute('aria-live','polite');this.control.append(this.status);
    if(delivery.element)delivery.element.append(this.control);else delivery.displayHost.append(this.control);
    replaceOptions(this.select,[{value:'none',label:'None'}],'none');this.select.disabled=true;
    this.select.onchange=()=>{
      if(this.select.value==='none')this.displayStore.choose(null);
      else this.displayStore.choose(this.presets?.find(preset=>displayPresetKey(preset)===this.select.value));
      this.sync();
    };
    this.menu=new StudioDisplayMenu(root,this);
    this.unsubscribe=this.displayStore.subscribe(()=>{this.status.textContent='';this.menu.syncSelection();this.sync();this.refreshBindings();});
    const Observer=doc.defaultView?.MutationObserver||globalThis.MutationObserver;
    if(Observer){this.observer=new Observer(()=>this.queueBindings());this.observer.observe(root,{childList:true,subtree:true,attributes:true,attributeFilter:['src','hidden']});}
    const sync=delivery.sync;delivery.sync=(...args)=>{const value=sync.apply(delivery,args);this.sync();return value;};
    const close=owner.close;if(typeof close==='function')owner.close=(...args)=>{this.close();return close.apply(owner,args);};
    this.sync();void this.loadConfig('').then(config=>{if(!this.closed){
      this.catalogue=config;this.refreshICCOptions();this.sync();this.refreshBindings();
    }}).catch(()=>{if(!this.closed)this.select.title='Display transforms are unavailable. Reopen Studio to retry.';});
  }
  save(){try{this.storage.setItem(KEY,JSON.stringify({which:this.saved.which}));}catch{}this.sync();}
  unmanagedAvailable(){return verifiedICCPreviewSource(this.owner.studio?.aeBridge?.source)&&this.owner.studio.aeBridge.closed!==true;}
  aeModelInputFile(file){
    const ae=this.owner.studio?.aeBridge,first=ae?.source?.processingInput?.stills?.first;
    if(!ae||ae.closed||!verifiedICCPreviewSource(ae.source)||!first)return false;
    const actual=safeFile(file,'input'),expected=safeFile(first,'input');
    return !!actual&&!!expected&&actual.filename===expected.filename&&
      actual.subfolder===expected.subfolder&&actual.type===expected.type;
  }
  aeModelViewResult(item){
    const ae=this.owner.studio?.aeBridge,first=ae?.source?.processingInput?.stills?.first;
    const shown=safeFile(item?.preview||item?.file,'output');
    if(!ae||ae.closed||!verifiedICCPreviewSource(ae.source)||!item?.image_layers||!first||
       item.colour?.encoding!=='srgb_display'||item.colour.sceneLinear!==false||
       !/\.png$/i.test(shown?.filename||''))return false;
    if(item.ae_frame_contract?.sessionId===ae.session?.id)return true;
    const original=safeFile(item.image_layers.originalSourceMetadata,'input'),expected=safeFile(first,'input');
    return item.image_layers.originalSourceMetadata?.aeSourceInput?.schemaVersion===1&&
      original?.filename===expected?.filename&&original?.subfolder===expected?.subfolder&&original?.type===expected?.type;
  }
  presetsFor(config){const presets=studioDisplayPresets(config);if(this.unmanagedAvailable()&&!presets.some(isUnmanagedICCDisplay))presets.push(UNMANAGED_ICC_DISPLAY);return presets;}
  refreshICCOptions(){
    if(!this.catalogue)return;
    const available=this.unmanagedAvailable();if(this.iccPresetIncluded===available)return;
    this.iccPresetIncluded=available;this.presets=this.presetsFor(this.catalogue);this.displayStore.registerCatalogue(this.presets);
    replaceOptions(this.select,[{value:'none',label:'None'},...this.presets.map(preset=>({value:displayPresetKey(preset),label:preset.label}))]);this.select.disabled=false;
    if(!available&&isUnmanagedICCDisplay(this.displayStore.get().selection))this.displayStore.choose(null);
  }
  choices(){
    const mode=activeStudioMode(this.owner),w=this.delivery.workspace(mode),source=this.delivery.source(w),ae=this.owner.studio?.aeBridge;
    const input=this.delivery.input(w),originalMetadata=mode==='image'?this.owner.imageLayers?.originalSourceMetadata?.():null,selector=studioDisplaySource(originalMetadata||source);
    const explicit=Object.prototype.hasOwnProperty.call(this.delivery.inputOverrides||{},this.delivery.sourceKey(w));
    const sourceColour=explicit&&SPACES.has(input.space)?input.space:'auto';
    const count=source?.frameCount||source?.manifest?.frames?.length||source?.frames||source?.count;
    const original=ae?.source?{ae,selector:studioDisplaySource(ae.source),which:'source',key:'ae:'+ae.session.id,count:ae.source.frameCount,label:'After Effects source',aeModelView:verifiedICCPreviewSource(ae.source)}
      :selector?{selector,which:'source',key:JSON.stringify(selector)+':'+sourceColour,count:Number.isSafeInteger(count)?count:undefined,colour:sourceColour,label:'Original source'}:null;
    const base=this.delivery.raw(mode),raw=this.delivery.outputFor(mode,base)||base;
    const master=raw?.master,ref=safeFile(master,'output');
    const result=ref?{selector:{file:ref},which:'result',key:JSON.stringify(ref),count:Number.isSafeInteger(raw.frameCount)?raw.frameCount:undefined,colour:SPACES.has(raw.colour?.encoding)?raw.colour.encoding:'auto',label:'Selected result',aeModelView:this.aeModelViewResult(raw)}:null;
    return {original,result};
  }
  current(){const {original,result}=this.choices();return this.saved.which==='source'?original||result:this.saved.which==='result'?result||original:result||original;}
  currentFor(target){
    const {original,result}=this.choices();
    const media=target?.matches?.('img,video')?target:target?.querySelector?.('img,video');
    if(media?.closest?.('.zf-viewer')&&media?.matches?.('#zps-video,#zps-image-slot img')){
      const workspace=[this.owner.paintout,this.owner.watermark,this.owner.ripple].find(item=>item?.page?.contains?.(media));
      if(workspace){
        if(workspace.view==='mask')return null;
        if(media.tagName==='IMG'){
          const origin=this.root.ownerDocument.defaultView?.location?.origin;
          const preview=origin&&paintPreviewSource(media.currentSrc||media.getAttribute('src'),origin);
          if(preview&&knownPaintPreviewFile(workspace,preview.file))return {paint:{workspace,...preview},which:workspace.view==='anchor'?'result':'source',key:'paint:'+JSON.stringify(preview),colour:SPACES.has(preview.space)?preview.space:'auto',label:'Paintout preview'};
        }
        if(media.tagName==='VIDEO'&&workspace.view==='source'&&workspace.sourceInfo?.display_source)
          return {selector:{source_token:workspace.sourceInfo.display_source},which:'source',key:'paint-source:'+workspace.state.source,colour:SPACES.has(workspace.state.sourceColour)?workspace.state.sourceColour:'auto',label:'Paintout source'};
        if(media.tagName==='VIDEO'&&workspace.view==='result'){
          const file=safeFile(workspace.resultPreviewFile?.(),'output');
          if(file)return {selector:{file},which:'result',key:'paint-result:'+JSON.stringify(file),colour:'auto',label:'Paintout result'};
        }
        return null;
      }
    }
    const side=media?.matches?.('[data-source],[data-source-image]')?'source':media?.matches?.('[data-result],[data-result-image]')?'result':null;
    if(side||target?.closest?.('.zc-gallery')){
      const rawSrc=media?.getAttribute?.('src')||media?.src||media?.currentSrc||'';
      const remembered=media?.tagName==='VIDEO'?this.videoSources.get(media):null;
      if(remembered&&(rawSrc===remembered.src||rawSrc===this.bindings.get(media)?.proxyURL))return remembered.choice;
      const selector=this.fileSelector(media,media?.tagName==='VIDEO'?rawSrc:undefined);
      if(selector){
        const file=selector.file,item=this.owner.items?.find(item=>{const ref=safeFile(item.file,'output');return ref&&ref.filename===file.filename&&ref.subfolder===file.subfolder&&ref.type===file.type;});
        const actual=studioDisplaySource(item)||selector;
        const choice={selector:actual,which:side||'result',key:JSON.stringify(actual)+':auto',colour:'auto',count:item?.frameCount,label:side==='source'?'Original source':'Result',aeModelView:this.aeModelViewResult(item)||side==='source'&&this.aeModelInputFile(file)};
        if(media?.tagName==='VIDEO')this.videoSources.set(media,{src:rawSrc,choice});
        return choice;
      }
      if(media?.tagName==='VIDEO')this.videoSources.delete(media);
      if(side)return side==='source'?original:result;
    }
    if(target?.closest?.('.zc-image-source'))return original||result;
    if(target?.closest?.('.zc-gallery'))return media?.tagName==='VIDEO'?null:result||original;
    return this.current();
  }
  fileSelector(media,provided){
    const value=provided||media?.currentSrc||media?.getAttribute?.('src');if(!value)return null;
    try{const origin=this.root.ownerDocument.defaultView?.location?.origin||'http://studio.invalid';const url=new URL(value,origin);if(url.origin!==origin||!/^\/(?:api\/)?view$/.test(url.pathname))return null;
      const filename=url.searchParams.get('filename'),subfolder=url.searchParams.get('subfolder')||'',type=url.searchParams.get('type')||'input';
      if(!filename||/[\\/\0]/.test(filename)||/[\\:\0]/.test(subfolder)||subfolder.startsWith('/')||subfolder.split('/').some(part=>part==='.'||part==='..')||!['input','output','temp'].includes(type))return null;
      return {file:{filename,subfolder,type}};
    }catch{return null;}
  }
  mediaTarget(target){
    if(!target?.closest||!this.root.contains(target))return null;
    const paint=target.closest('.zp-editor-viewer');
    if(paint){const binding=[...this.paintBindings.values()].find(item=>item.viewer.root===paint);if(binding)return {host:paint,media:null,selected:this.current()};}
    const owned=displayPreviewOwner(target);
    if(owned?.root&&owned.image&&target.closest?.('img,video,.zc-display-image'))return {host:owned.root,media:owned.image,owned,selected:{ae:owned.bridge,key:'owned:'+owned.bridge.session?.id,label:'AE source'}};
    const host=target.closest('.gs-canvas,.zc-image-source,.zc-image-comparison,.gs-comparison,.gs-compare-stage,.zc-gallery figure,.zf-viewer');
    if(!host||target.closest('.zc-reference,.gs-source-upload,.zhe-viewport,.pano-studio-root'))return null;
    const media=target.closest('img,video')||(host.matches('.zf-viewer')?null:host.querySelector('img:not([hidden]),video:not([hidden])'));
    if(!media||media.classList.contains('zc-colour-inline')||(host.matches('.zc-gallery figure')&&!target.closest('img,video')))return null;
    const selected=this.currentFor(media);
    return selected?{host,media,selected}:null;
  }
  async loadConfig(name,signal){
    const response=await this.api.fetchApi('/zura/studio/display/config'+(name?'?'+new URLSearchParams({config:name}):''),{signal});
    if(!response.ok){let message;try{message=(await response.json()).error;}catch{};throw Error(message||'OpenColorIO display settings are unavailable');}
    return response.json();
  }
  async openMenu(){
    if(this.closed)return;
    const candidates=this.root.querySelectorAll('.gs-canvas img,.gs-canvas video,.zc-image-source img,.zc-image-comparison img,.zc-gallery figure img,.zc-gallery figure video');
    const target=[...candidates].filter(media=>!media.hidden&&!media.closest('[hidden]')).map(media=>this.mediaTarget(media)).find(Boolean);
    const rect=this.select.getBoundingClientRect();
    await this.menu.open(target||{host:this.root,media:null,selected:this.current()},{clientX:rect.left,clientY:rect.bottom+8});
  }
  sync(){
    if(this.closed)return;
    this.refreshICCOptions();
    const state=this.displayStore.get(),label=state.label;
    const error=this.menu?.error,failed=error&&error.key===this.currentFor(this.menu.active?.media||this.menu.active?.host)?.key;
    const keyValue=state.selection?displayPresetKey(state.selection):'none';
    if([...this.select.options].some(option=>option.value===keyValue))this.select.value=keyValue;
    this.select.title=failed?error.text:`Preview: ${label}. Source and exported masters stay unchanged.`;
    const selected=this.current(),key=selected?.key||'';
    if(this.view?.root&&this.currentKey!==key)this.closeViewer();
    this.queueBindings();
  }
  capture(view){
    // Preview widgets publish to the global store themselves. Never copy their
    // transform into workspace/generation/output preferences.
    if(view.root)this.sync();
  }
  queueBindings(){if(this.bindingsQueued||this.closed)return;this.bindingsQueued=true;queueMicrotask(()=>{this.bindingsQueued=false;this.refreshBindings();});}
  refreshBindings(){
    if(this.closed)return;this.refreshICCOptions();
    const seen=new Set(),selector='.gs-canvas img,.gs-canvas video,.zc-image-source img,.zc-image-comparison img,.zc-image-comparison video,.gs-comparison img,.gs-comparison video,.gs-compare-stage img,.gs-compare-stage video,.zc-gallery figure img,.zc-gallery figure video,.zf-viewer #zps-image-slot img,.zf-viewer #zps-video';
    for(const media of this.root.querySelectorAll(selector)){
      if(media.hidden||media.closest('[hidden]')||media.isConnected===false||media.classList.contains('zc-colour-inline')||displayPreviewOwner(media))continue;
      const target=this.mediaTarget(media);if(!target?.selected)continue;seen.add(media);
      let binding=this.bindings.get(media);if(!binding){binding=new StudioDisplayBinding(this,media);this.bindings.set(media,binding);}binding.refresh();
    }
    for(const [media,binding]of this.bindings)if(!seen.has(media)){binding.close();this.bindings.delete(media);}
    const active=new Set();
    for(const workspace of new Set([this.owner.paintout,this.owner.watermark,this.owner.ripple])){
      const viewer=workspace?.editor?.viewer;
      if(!viewer?.root||!this.root.contains(viewer.root)||viewer.root.closest?.('[hidden]')||workspace.page?.hidden)continue;
      active.add(viewer);
      let binding=this.paintBindings.get(viewer);
      if(!binding){binding=new StudioPaintDisplayBinding(this,workspace,viewer);this.paintBindings.set(viewer,binding);}
      else binding.refresh();
    }
    for(const [viewer,binding]of this.paintBindings)if(!active.has(viewer)){binding.close();this.paintBindings.delete(viewer);}
    const area=this.owner.imageArea,viewer=area?.viewer;
    if(viewer?.root&&this.root.contains(viewer.root)&&!viewer.root.closest?.('[hidden]')&&!area.host?.hidden){
      if(this.imageAreaBinding?.viewer!==viewer){this.imageAreaBinding?.close();this.imageAreaBinding=new StudioImageAreaDisplayBinding(this,area,viewer);}
      else this.imageAreaBinding.refresh();
    }else if(this.imageAreaBinding){this.imageAreaBinding.close();this.imageAreaBinding=null;}
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
      view=new AEFloatDisplay(local,{store:this.displayStore,title:'Colour preview',imageAlt:'Original media through the selected display transform',frameCount:selected?.count||1,unmanagedICC:this.unmanagedAvailable(),defaultAEModelView:selected?.aeModelView===true,
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
  }
  closeViewer(){++this.revision;if(this.localBridge)this.localBridge.closed=true;this.localBridge=null;this.view?.close();this.view=null;}
  close(){if(this.closed)return;this.closed=true;this.unsubscribe?.();this.unsubscribe=null;this.observer?.disconnect();for(const binding of this.bindings.values())binding.close();this.bindings.clear();for(const binding of this.paintBindings.values())binding.close();this.paintBindings.clear();this.imageAreaBinding?.close();this.imageAreaBinding=null;this.menu?.dispose();this.closeViewer();this.control.remove();}
}

class StudioDisplayMenu {
  constructor(root,settings){
    this.root=root;this.settings=settings;this.document=root.ownerDocument;this.view=this.document.defaultView;this.revision=0;this.closed=false;this.active=null;
    this.onContext=event=>void this.context(event);
    this.onOutside=event=>{if(this.element&&!this.element.hidden&&!(event.composedPath?.()||[event.target]).includes(this.element))this.close();};
    this.onKey=event=>{if(event.key==='Escape'&&this.element&&!this.element.hidden){this.close();event.preventDefault();event.stopPropagation();}};
    this.onMove=()=>{if(this.active)this.position();for(const binding of this.settings.bindings.values())binding.updatePosition();};
    this.onFullscreen=()=>{this.onMove();this.settings.queueBindings();};
    root.addEventListener('contextmenu',this.onContext);this.document.addEventListener('pointerdown',this.onOutside,true);this.document.addEventListener('keydown',this.onKey,true);
    this.document.addEventListener('scroll',this.onMove,true);this.document.addEventListener('fullscreenchange',this.onFullscreen);this.view?.addEventListener?.('resize',this.onMove);
  }
  mount(){
    if(this.element)return;const menu=this.document.createElement('section');menu.className='zc-colour-menu';menu.hidden=true;menu.tabIndex=-1;menu.setAttribute('role','dialog');menu.setAttribute('aria-label','Colour transform');
    menu.innerHTML='<div class="zc-colour-menu-head"><strong>Colour transform</strong><button type="button" data-colour-close aria-label="Close colour menu">Close</button></div><label>Colour transform<select data-colour-preset aria-label="Colour transform"></select></label><p class="zc-colour-menu-status" role="status" aria-live="polite"></p><div class="zc-colour-menu-actions"><button type="button" data-colour-reset>None</button></div>';
    this.root.append(menu);this.element=menu;this.presetSelect=menu.querySelector('[data-colour-preset]');this.status=menu.querySelector('.zc-colour-menu-status');
    menu.querySelector('[data-colour-close]').onclick=()=>this.close();menu.querySelector('[data-colour-reset]').onclick=()=>this.settings.displayStore.choose(null);
    this.presetSelect.onchange=()=>this.selectPreset(this.presets?.find(preset=>displayPresetKey(preset)===this.presetSelect.value));
  }
  async context(event){const target=this.settings.mediaTarget(event.target);if(!target)return;event.preventDefault();await this.open(target,event);}
  async open(target,event){
    if(this.closed)return;this.mount();this.active={...target,event,focus:this.document.activeElement};this.media=target.media;this.element.hidden=false;this.position();this.element.focus({preventScroll:true});
    const choice=this.settings.displayStore.get().selection;
    await this.loadConfig(isUnmanagedICCDisplay(choice)?'':choice?.config||'');
    if(this.element&&!this.element.hidden&&this.active?.host===target.host)this.presetSelect.focus({preventScroll:true});
  }
  async loadConfig(name){
    const revision=++this.revision;this.status.textContent='Loading display settings…';this.presetSelect.disabled=true;
    try{
      const owner=this.active?.owned,selected=this.active?.selected;let config;
      if(owner?.config&&(!name||name===owner.config.config))config=owner.config;
      else if(owner){const response=await owner.requestConfig(name);await this.settings.response(response);config=await response.json();}
      else if(selected?.ae){
        const session=selected.ae.session;if(!session?.capability||selected.ae.closed)throw Error('The After Effects session has ended.');
        const response=await selected.ae.api.fetchApi(AE_ROOT+'/'+encodeURIComponent(session.id)+'/display-config'+(name?'?'+new URLSearchParams({config:name}):''),{headers:{'X-ComfyLink-Studio-Session':session.capability}});
        await this.settings.response(response);config=await response.json();
      }else config=await this.settings.loadConfig(name);
      if(this.closed||!this.element||this.element.hidden||revision!==this.revision)return;
      this.config=config;this.presets=this.settings.presetsFor(config);this.settings.displayStore.registerCatalogue(this.presets);this.defaultPreset=this.presets.find(preset=>preset.view==='Raw');
      replaceOptions(this.presetSelect,this.presets.map(preset=>({value:displayPresetKey(preset),label:preset.label})));this.presetSelect.disabled=!this.presets.length;
      this.syncSelection();this.status.textContent='Display only. Source and exports are unchanged.';
      // Opening a menu reads the current choice. Only an explicit change event
      // can publish a different transform or request new preview pixels.
    }catch(error){if(revision===this.revision&&this.element)this.status.textContent=error.message||'Display settings are unavailable.';}
  }
  syncSelection(){
    const state=this.settings.displayStore.get();this.transformEnabled=!!state.selection&&state.selection.view!=='Raw';this.preset=state.selection||this.presets?.find(preset=>preset.view==='Raw');
    if(this.presetSelect&&this.preset)this.presetSelect.value=displayPresetKey(this.preset);
  }
  selectPreset(preset){if(this.closed||!preset)return;this.error=null;this.settings.displayStore.choose(preset);}
  schedule(){this.settings.refreshBindings();}
  async apply(){this.settings.refreshBindings();}
  targetFrame(media,info){
    const owned=displayPreviewOwner(media);if(owned)return Math.max(0,Math.min(Number(info.frame_count)-1,Number(owned.slider?.value)||0));
    const binding=this.settings.bindings.get(media);return binding?binding.frame(info):0;
  }
  get inline(){return this.settings.bindings.get(this.active?.media)?.inline||null;}
  updateInline(){for(const binding of this.settings.bindings.values())binding.updatePosition();}
  position(){
    if(!this.element||this.element.hidden)return;const width=this.element.getBoundingClientRect?.().width||304,height=this.element.getBoundingClientRect?.().height||190,point=this.active?.event||{clientX:8,clientY:8},margin=8;
    Object.assign(this.element.style,{left:`${Math.max(margin,Math.min(point.clientX,this.view?.innerWidth-width-margin||margin))}px`,top:`${Math.max(margin,Math.min(point.clientY,this.view?.innerHeight-height-margin||margin))}px`});
  }
  close(){
    if(!this.element||this.element.hidden)return;this.element.hidden=true;++this.revision;
    if(this.active?.focus?.isConnected&&!this.element.contains(this.active.focus))this.active.focus.focus?.({preventScroll:true});
  }
  dispose(){
    if(this.closed)return;this.closed=true;++this.revision;this.root.removeEventListener('contextmenu',this.onContext);this.document.removeEventListener('pointerdown',this.onOutside,true);this.document.removeEventListener('keydown',this.onKey,true);
    this.document.removeEventListener('scroll',this.onMove,true);this.document.removeEventListener('fullscreenchange',this.onFullscreen);this.view?.removeEventListener?.('resize',this.onMove);this.element?.remove();this.element=null;this.active=null;
  }
}

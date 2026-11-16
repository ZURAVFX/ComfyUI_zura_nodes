// Display-only OCIO preview for the scoped AE source. The source and masters
// stay in their declared colour space and never receive these view settings.
const ROOT='/zura/comfylink/v1/studio/sessions';
import {studioDisplayTransform,registerDisplayPreview,UNMANAGED_ICC_DISPLAY,isUnmanagedICCDisplay,verifiedICCPreviewSource} from './studio_display_state.js';
const presetKey=preset=>JSON.stringify([preset.config,preset.display,preset.view]);
const validPreset=preset=>preset&&['config','display','view'].every(key=>typeof preset[key]==='string'&&preset[key].length>0&&preset[key].length<512);

export function colourTransforms(config){
  const local=config.displays.flatMap(display=>display.views.map(view=>({config:config.config,display:display.name,view})));
  const catalogue=(config.adobePresets?.length?config.adobePresets:config.presets?.length?config.presets:local).filter(validPreset),result=[];
  const add=(label,preset)=>{if(preset&&!result.some(item=>presetKey(item)===presetKey(preset)))result.push({...preset,label});};
  add('None',local.find(preset=>preset.display===config.display&&preset.view==='Raw')||catalogue.find(preset=>preset.view==='Raw'));
  for(const preset of catalogue)add(preset.label||preset.view,preset);
  return result;
}

export class AEFloatDisplay {
  constructor(bridge,options={}){this.bridge=bridge;this.viewerOptions=options;this.displayStore=studioDisplayTransform;this.revision=0;this.configRevision=0;this.objectURL=null;this.timer=null;this.playbackTimer=null;this.playing=false;}
  unmanagedAvailable(){return this.viewerOptions.unmanagedICC===true||verifiedICCPreviewSource(this.bridge.source);}
  presets(){const options=colourTransforms(this.config);if(this.unmanagedAvailable())options.push(UNMANAGED_ICC_DISPLAY);return options;}
  rawChoice(){return colourTransforms(this.config).find(preset=>preset.view==='Raw');}
  openInline(host){return this.open(host);}
  async open(host=null){
    if(this.bridge.closed)return;if(this.root){if(host&&this.root.parentNode!==host)host.append(this.root);return;}
    const doc=this.bridge.studio.container.ownerDocument;
    this.root=doc.createElement(host?'section':'dialog');this.root.className='zc-display'+(host?' zc-display-inline':'');
    this.root.setAttribute('aria-label','AE source display');
    this.root.innerHTML=`<div class="zc-display-head"><h2>AE source preview</h2><button type="button" data-view-close aria-label="Close preview">Close</button></div>
      <div class="zc-display-image"></div>
      <div class="zc-display-bottom"><button type="button" data-view-play aria-label="Play preview">Play</button><label>Frame <input type="range" min="0" value="0" step="1" data-view-frame></label><span data-view-position></span><span role="status" aria-live="polite"></span></div>
      <p>Source preview</p>`;
    (host||this.bridge.studio.container).append(this.root);
    this.releaseOwner=registerDisplayPreview(this.root,this);
    this.unsubscribe=this.displayStore.subscribe(()=>{if(this.root&&!this.loadingConfig)void this.applySharedChoice();});
    this.root.querySelector('h2').textContent=this.viewerOptions.title||'AE source preview';
    this.root.setAttribute('aria-label',this.viewerOptions.title||'AE source display');
    this.root.querySelector('[data-view-close]').onclick=()=>this.close();
    this.root.querySelector('[data-view-close]').hidden=!!host;
    this.root.addEventListener('cancel',event=>{event.preventDefault();this.close();});
    this.transformSelect=doc.createElement('select');
    // Keep tuple objects for existing Studio integrations without exposing
    // configuration/display/view as three separate artist-facing controls.
    this.selectConfig=doc.createElement('select');this.selectDisplay=doc.createElement('select');this.selectView=doc.createElement('select');
    this.slider=this.root.querySelector('[data-view-frame]');this.playButton=this.root.querySelector('[data-view-play]');this.position=this.root.querySelector('[data-view-position]');this.status=this.root.querySelector('[role=status]');this.image=null;this.imageHost=this.root.querySelector('.zc-display-image');
    const count=this.viewerOptions.frameCount||this.bridge.source?.frameCount||this.bridge.session?.context?.source?.frameCount||1;
    this.frameCount=count;
    this.slider.disabled=count<=1;
    this.playButton.disabled=count<=1;
    this.slider.max=String(Math.max(0,count-1));this.position.textContent=`1 / ${count}`;
    this.slider.value=String(Math.max(0,Math.min(count-1,this.lastFrameIndex||0)));this.position.textContent=`${Number(this.slider.value)+1} / ${count}`;
    this.selectConfig.onchange=()=>this.loadConfig(this.selectConfig.value);
    this.selectDisplay.onchange=()=>{this.setViews(this.selectDisplay.value,this.selectView.value);this.chooseCurrentTuple();};
    this.selectView.onchange=()=>this.chooseCurrentTuple();
    this.transformSelect.onchange=()=>void this.chooseTransform(this.transformSelect.value);
    this.playButton.onclick=()=>{if(this.playing)this.pause();else void this.play();};
    this.visibilityListener=()=>{if(doc.hidden)this.pause();};doc.addEventListener('visibilitychange',this.visibilityListener);
    this.slider.oninput=()=>{this.pause();this.position.textContent=`${Number(this.slider.value)+1} / ${this.frameCount}`;++this.revision;if(!this.loadingConfig)this.controller?.abort();if(this.image)this.image.hidden=true;clearTimeout(this.timer);this.timer=setTimeout(()=>void this.render(),150);};
    if(!host){if(typeof this.root.showModal==='function')this.root.showModal();else this.root.open=true;}
    await this.loadConfig('');
  }
  frameInterval(){
    const rate=this.viewerOptions.frameRate||this.bridge.frameContract?.frameRate||this.bridge.source?.manifest?.frameRate||this.bridge.session?.context?.source?.frameRate;
    const numerator=Number(rate?.numerator),denominator=Number(rate?.denominator);
    return numerator>0&&denominator>0&&Number.isFinite(numerator)&&Number.isFinite(denominator)?1000*denominator/numerator:1000/24;
  }
  pause(){
    this.playing=false;clearTimeout(this.playbackTimer);this.playbackTimer=null;
    if(this.playButton){this.playButton.textContent='Play';this.playButton.setAttribute('aria-label','Play preview');}
  }
  async play(){
    if(this.playing||!this.root||this.frameCount<=1||this.bridge.closed)return;
    this.playing=true;this.playButton.textContent='Pause';this.playButton.setAttribute('aria-label','Pause preview');
    if(Number(this.slider.value)>=this.frameCount-1){this.slider.value='0';this.position.textContent=`1 / ${this.frameCount}`;await this.render();}
    if(this.playing)this.schedulePlayback();
  }
  schedulePlayback(){
    clearTimeout(this.playbackTimer);
    this.playbackTimer=setTimeout(async()=>{
      if(!this.playing||!this.root||this.bridge.closed||this.root.ownerDocument.hidden||this.root.hidden||this.root.closest('[hidden]')){this.pause();return;}
      const next=Number(this.slider.value)+1;
      if(next>=this.frameCount){this.pause();return;}
      this.slider.value=String(next);this.position.textContent=`${next+1} / ${this.frameCount}`;
      await this.render();
      if(!this.playing)return;
      if(next>=this.frameCount-1||!this.image||this.image.hidden)this.pause();else this.schedulePlayback();
    },this.frameInterval());
  }
  options(select,items,selected){
    select.replaceChildren();for(const item of items){const option=select.ownerDocument.createElement('option');option.value=item.name;option.textContent=item.label||item.name;option.selected=item.name===selected;option.defaultSelected=option.selected;select.append(option);}
    if(items.some(item=>item.name===selected))select.value=selected;
  }
  setViews(display,selected){
    const item=this.config.displays.find(entry=>entry.name===display),views=item?.views||[];
    // Rebuilding a native select without a selection silently chooses its first
    // entry, which is often an ACES tone map. Keep an explicit view when valid,
    // otherwise use the server's declared default rather than option ordering.
    const preferred=selected||this.config.view;
    this.options(this.selectView,views.map(name=>({name})),views.includes(preferred)?preferred:views.includes(this.config.view)?this.config.view:item?.defaultView);
  }
  syncTransforms(){
    if(!this.config||!this.transformSelect)return;
    const current={config:this.selectConfig.value,display:this.selectDisplay.value,view:this.selectView.value};
    this.transforms=this.presets();
    if(validPreset(current)&&!this.transforms.some(item=>presetKey(item)===presetKey(current)))this.transforms.push({...current,label:current.view==='Raw'?'None':current.view});
    const selected=this.displayStore.get().selection;
    this.options(this.transformSelect,this.transforms.map(preset=>({name:presetKey(preset),label:preset.label})),presetKey(isUnmanagedICCDisplay(selected)?selected:current));
  }
  async chooseTransform(key){
    const preset=this.transforms?.find(item=>presetKey(item)===key);if(!preset)return;
    this.displayStore.choose(preset);
  }
  chooseCurrentTuple(){this.displayStore.choose({config:this.selectConfig.value,display:this.selectDisplay.value,view:this.selectView.value});}
  async requestConfig(name,signal){
    if(this.viewerOptions.configRequest)return this.viewerOptions.configRequest(name,signal);
    const session=this.bridge.session;if(!session?.capability)throw Error('The AE session has ended');
    return this.bridge.api.fetchApi(ROOT+'/'+encodeURIComponent(session.id)+'/display-config'+(name?'?'+new URLSearchParams({config:name}):''),{headers:{'X-ComfyLink-Studio-Session':session.capability},signal});
  }
  async applySharedChoice(){
    if(!this.root||!this.config||this.bridge.closed||this.loadingConfig)return;
    const choice=this.displayStore.get().selection||this.rawChoice();
    if(!choice)return;
    if(isUnmanagedICCDisplay(choice)){
      if(!this.unmanagedAvailable()){this.status.textContent='The unmanaged AE view needs a verified linear-sRGB AE source.';return;}
      const raw=this.rawChoice();if(!raw){this.status.textContent='Raw display is unavailable for this AE source.';return;}
      if(raw.config!==this.config.config){await this.loadConfig(raw.config);return;}
      this.selectDisplay.value=raw.display;this.setViews(raw.display,raw.view);await this.render();return;
    }
    if(choice.config!==this.config.config){await this.loadConfig(choice.config);return;}
    this.selectDisplay.value=choice.display;this.setViews(choice.display,choice.view);await this.render();
  }
  async loadConfig(name){
    const revision=++this.configRevision;this.loadingConfig=true;++this.revision;this.status.textContent='Loading display settings…';if(this.image)this.image.hidden=true;this.controller?.abort();this.controller=new AbortController();
    try{
      const response=await this.requestConfig(name,this.controller.signal);
      if(!response.ok)throw Error('OpenColorIO display settings are unavailable');
      const data=await response.json();if(!this.root||revision!==this.configRevision)return;
      this.config=data;this.displayStore.registerCatalogue(this.presets());
      const choice=this.displayStore.get().selection||this.rawChoice();
      if(choice&&choice.config!==data.config&&data.configs.some(item=>item.name===choice.config)){this.loadingConfig=false;await this.loadConfig(choice.config);return;}
      const selected=isUnmanagedICCDisplay(choice)?this.rawChoice():choice||{config:data.config,display:data.display,view:data.view};
      this.options(this.selectConfig,data.configs,data.config);this.options(this.selectDisplay,data.displays,selected.display);this.setViews(selected.display,selected.view);this.loadingConfig=false;await this.render();
    }catch(error){if(this.root&&revision===this.configRevision){this.loadingConfig=false;this.status.textContent=error.message||'Display settings are unavailable';}}
  }
  async render(){
    if(!this.root||!this.config||this.bridge.closed||this.loadingConfig)return;this.syncTransforms();const revision=++this.revision,storeRevision=this.displayStore.get().revision,index=this.slider.value;this.status.textContent='Preparing preview…';if(this.image)this.image.hidden=true;
    this.controller?.abort();this.controller=new AbortController();
    const query=new URLSearchParams({index,config:this.selectConfig.value,display:this.selectDisplay.value,view:'Raw'});
    try{
      let response;
      if(this.viewerOptions.frameRequest)response=await this.viewerOptions.frameRequest(query,this.controller.signal);
      else{const session=this.bridge.session,capability=session.capability;if(!capability)throw Error('The AE session has ended');response=await this.bridge.api.fetchApi(ROOT+'/'+encodeURIComponent(session.id)+'/display-frame?'+query,{headers:{'X-ComfyLink-Studio-Session':capability},signal:this.controller.signal});}
      if(!response.ok)throw Error('This source colour space is not available for display preview');
      let blob=await response.blob();if(!this.root||revision!==this.revision||storeRevision!==this.displayStore.get().revision||this.slider.value!==index)return;
      const url=URL.createObjectURL(blob),previous=this.objectURL;this.objectURL=url;
      if(!this.image){this.image=this.root.ownerDocument.createElement('img');this.image.alt=this.viewerOptions.imageAlt||'AE source preview';this.image.setAttribute('data-view-image','');this.image.src=url;this.imageHost.append(this.image);}else this.image.src=url;
      this.image.hidden=false;this.viewerOptions.onFrame?.({url,index:Number(index),frameCount:this.frameCount});if(previous)URL.revokeObjectURL(previous);
      this.status.textContent=isUnmanagedICCDisplay(this.displayStore.get().selection)?'AE Viewer unmanaged display only. Source and exports are unchanged.':this.viewerOptions.previewNote?.(response)||response.headers?.get?.('X-ComfyLink-Preview-Note')||'';
    }catch(error){if(this.root&&revision===this.revision&&error.name!=='AbortError')this.status.textContent=error.message||'Preview unavailable';}
  }
  close(){if(!this.root)return;this.pause();this.root.ownerDocument.removeEventListener('visibilitychange',this.visibilityListener);this.visibilityListener=null;this.lastFrameIndex=Number(this.slider?.value)||0;++this.revision;++this.configRevision;this.loadingConfig=false;clearTimeout(this.timer);this.controller?.abort();this.unsubscribe?.();this.unsubscribe=null;this.releaseOwner?.();this.releaseOwner=null;if(this.objectURL)URL.revokeObjectURL(this.objectURL);this.objectURL=null;this.root.close?.();this.root.remove();this.root=null;this.viewerOptions.onClose?.();}
}

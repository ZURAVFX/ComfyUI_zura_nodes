// Display-only OCIO preview for the scoped AE source. The source and masters
// stay in their declared colour space and never receive these view settings.
const ROOT='/zura/comfylink/v1/studio/sessions';

export class AEFloatDisplay {
  constructor(bridge){this.bridge=bridge;this.revision=0;this.objectURL=null;this.timer=null;}
  async open(){
    if(this.root||this.bridge.closed)return;
    const doc=this.bridge.studio.container.ownerDocument;
    this.root=doc.createElement('dialog');this.root.className='zc-display';
    this.root.setAttribute('aria-label','AE source display');
    this.root.innerHTML=`<div class="zc-display-head"><h2>AE source preview</h2><button type="button" data-view-close aria-label="Close preview">Close</button></div>
      <div class="zc-display-controls"><label>Configuration<select data-view-config></select></label><label>Display<select data-view-display></select></label><label>View<select data-view-view></select></label></div>
      <div class="zc-display-image"><img alt="AE source with the selected display transform" data-view-image hidden></div>
      <div class="zc-display-bottom"><label>Frame <input type="range" min="0" value="0" step="1" data-view-frame></label><span data-view-position></span><span role="status" aria-live="polite"></span></div>
      <p>Display settings do not change the source or exported result.</p>`;
    this.bridge.studio.container.append(this.root);
    this.root.querySelector('[data-view-close]').onclick=()=>this.close();
    this.root.addEventListener('cancel',event=>{event.preventDefault();this.close();});
    this.selectConfig=this.root.querySelector('[data-view-config]');this.selectDisplay=this.root.querySelector('[data-view-display]');this.selectView=this.root.querySelector('[data-view-view]');
    this.slider=this.root.querySelector('[data-view-frame]');this.position=this.root.querySelector('[data-view-position]');this.status=this.root.querySelector('[role=status]');this.image=this.root.querySelector('[data-view-image]');
    const count=this.bridge.source?.frameCount||this.bridge.session.context?.source?.frameCount||1;
    this.slider.max=String(Math.max(0,count-1));this.position.textContent=`1 / ${count}`;
    this.selectConfig.onchange=()=>void this.loadConfig(this.selectConfig.value);
    this.selectDisplay.onchange=()=>{this.setViews(this.selectDisplay.value);void this.render();};
    this.selectView.onchange=()=>void this.render();
    this.slider.oninput=()=>{this.position.textContent=`${Number(this.slider.value)+1} / ${count}`;clearTimeout(this.timer);this.timer=setTimeout(()=>void this.render(),150);};
    if(typeof this.root.showModal==='function')this.root.showModal();else this.root.open=true;
    await this.loadConfig('');
  }
  options(select,items,selected){
    select.replaceChildren();for(const item of items){const option=select.ownerDocument.createElement('option');option.value=item.name;option.textContent=item.label||item.name;select.append(option);}
    if(items.some(item=>item.name===selected))select.value=selected;
  }
  setViews(display,selected){const item=this.config.displays.find(entry=>entry.name===display);this.options(this.selectView,(item?.views||[]).map(name=>({name})),selected);}
  async loadConfig(name){
    const revision=++this.revision;this.status.textContent='Loading display settings…';this.image.hidden=true;this.controller?.abort();this.controller=new AbortController();
    try{
      const session=this.bridge.session;if(!session.capability)throw Error('The AE session has ended');
      const response=await this.bridge.api.fetchApi(ROOT+'/'+encodeURIComponent(session.id)+'/display-config'+(name?'?'+new URLSearchParams({config:name}):''),{headers:{'X-ComfyLink-Studio-Session':session.capability},signal:this.controller.signal});
      if(!response.ok)throw Error('OpenColorIO display settings are unavailable');
      const data=await response.json();if(!this.root||revision!==this.revision)return;
      this.config=data;this.options(this.selectConfig,data.configs,data.config);this.options(this.selectDisplay,data.displays,data.display);this.setViews(data.display,data.view);await this.render();
    }catch(error){if(this.root&&revision===this.revision)this.status.textContent=error.message||'Display settings are unavailable';}
  }
  async render(){
    if(!this.root||!this.config||this.bridge.closed)return;const revision=++this.revision;this.status.textContent='Preparing preview…';this.image.hidden=true;
    this.controller?.abort();this.controller=new AbortController();
    const query=new URLSearchParams({index:this.slider.value,config:this.selectConfig.value,display:this.selectDisplay.value,view:this.selectView.value});
    try{
      const session=this.bridge.session,capability=session.capability;if(!capability)throw Error('The AE session has ended');
      const response=await this.bridge.api.fetchApi(ROOT+'/'+encodeURIComponent(session.id)+'/display-frame?'+query,{headers:{'X-ComfyLink-Studio-Session':capability},signal:this.controller.signal});
      if(!response.ok)throw Error('This source colour space is not available for display preview');
      const blob=await response.blob();if(!this.root||revision!==this.revision)return;
      const url=URL.createObjectURL(blob),previous=this.objectURL;this.objectURL=url;this.image.src=url;this.image.hidden=false;if(previous)URL.revokeObjectURL(previous);
      this.status.textContent=response.headers?.get?.('X-ComfyLink-Preview-Note')||'';
    }catch(error){if(this.root&&revision===this.revision&&error.name!=='AbortError')this.status.textContent=error.message||'Preview unavailable';}
  }
  close(){if(!this.root)return;++this.revision;clearTimeout(this.timer);this.controller?.abort();if(this.objectURL)URL.revokeObjectURL(this.objectURL);this.objectURL=null;this.root.close?.();this.root.remove();this.root=null;}
}

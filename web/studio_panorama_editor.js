import {cameraOnlyControls} from './studio_panorama_controls.js';

/** Panorama's modal is mounted under body, outside Studio's theme inheritance. */
export function installPanoramaAppearance(root,themeRoot=root.ownerDocument?.querySelector('#genj-studio')){
  const doc=root.ownerDocument||document,editor=root.querySelector('.pano-studio');
  if(!editor)return()=>{};
  const sync=()=>{
    const light=themeRoot?.dataset?.theme==='light',computed=doc.defaultView?.getComputedStyle?.(themeRoot||root);
    const value=(name,fallback)=>computed?.getPropertyValue(name)?.trim()||fallback;
    root.classList.add('zc-camera-themed');root.dataset.zuraCameraTheme=light?'light':'dark';
    editor.classList.toggle('dark-theme',!light);editor.style.colorScheme=light?'light':'dark';
    const colours={
      '--studio-frame':value('--gs-bg',light?'#f5f5f1':'#111111'),
      '--studio-panel':value('--gs-panel',light?'#ffffff':'#1b1b1b'),
      '--studio-fill':value('--gs-input',light?'#f0f0eb':'#222222'),
      '--studio-fill-hover':value('--zc-hover',light?'#e8e8e3':'#303030'),
      '--studio-fill-active':value('--gs-selected',light?'#e3e3dc':'#292a21'),
      '--studio-line':value('--gs-line',light?'#dcdcd5':'#383838'),
      '--studio-line-strong':value('--gs-line',light?'#c8c8c0':'#484848'),
      '--studio-fg-2':value('--gs-muted',light?'#686861':'#ababab'),
      '--studio-fg':value('--zc-text',light?'#202019':'#f2f2f2'),
      '--studio-strong':value('--gs-accent','#caff00'),
      '--studio-on-strong':value('--gs-ink','#111111'),
    };
    for(const [name,colour]of Object.entries(colours))editor.style.setProperty(name,colour);
  };
  sync();const Observer=doc.defaultView?.MutationObserver||globalThis.MutationObserver;
  const observer=themeRoot&&Observer?new Observer(sync):null;
  observer?.observe(themeRoot,{attributes:true,attributeFilter:['data-theme','class','style']});
  return()=>{observer?.disconnect();root.classList.remove('zc-camera-themed');delete root.dataset.zuraCameraTheme;};
}

export function installSourcePreview(root,source){
  if(!source?.url)return()=>{};
  const main=root.querySelector('.pano-studio-main');if(!main)return()=>{};
  const panel=document.createElement('aside');panel.className='zc-camera-source';panel.setAttribute('aria-label','Original video reference');
  panel.innerHTML='<strong>Original video</strong><video muted playsinline preload="metadata" aria-label="Original footage"></video><label><input type="checkbox" checked/>Follow camera timeline</label><p></p>';
  panel.querySelector('p').textContent=source.stillScene?'The 3D view uses a still scene. This video remains the performance reference for the final render.':'Compare the source performance with the camera view.';
  const video=panel.querySelector('video'),follow=panel.querySelector('input'),start=Math.max(0,Number(source.start)||0),duration=Math.max(1/24,Number(source.duration)||2),fps=Number(source.fps)||24;
  follow.checked=true;video.muted=true;video.src=source.url;main.append(panel);main.classList.add('zc-camera-with-source');
  const sync=()=>{if(!follow.checked)return;const frame=Number(root.querySelector('.pano-studio-tl-frame')?.textContent?.split('/')[0]?.trim())||0;const playing=!!root.querySelector('[data-tl="play"][aria-label="Pause"]');const time=start+Math.max(0,Math.min(duration-1/fps,frame/fps));if(Math.abs(video.currentTime-time)>(playing ? .15 : .015))try{video.currentTime=time;}catch{}if(playing){const promise=video.play?.();promise?.catch?.(()=>{});}else video.pause?.();};
  video.onloadedmetadata=sync;follow.onchange=()=>{video.controls=!follow.checked;if(follow.checked)sync();};
  video.ontimeupdate=()=>{if(!follow.checked&&video.currentTime>=start+duration){video.pause?.();video.currentTime=start;}};
  const observer=new MutationObserver(sync);observer.observe(root,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['aria-label']});sync();
  return()=>{observer.disconnect();video.pause?.();video.removeAttribute('src');video.load?.();panel.remove();main.classList.remove('zc-camera-with-source');};
}

/** Reuse the native image picker; resizing never recreates the scene. */
export function installEnvironmentWorkspace(root,host,{resize=()=>globalThis.window?.dispatchEvent(new Event('resize'))}={}){
  const doc=host.ownerDocument,bar=doc.createElement('div');bar.className='zc-environment-actions';
  bar.innerHTML='<button type="button" data-environment-add>Add image / sticker</button><span>Add images one at a time, then place them in the scene.</span><button type="button" data-environment-expand aria-expanded="false">Expand workspace</button>';
  host.append(bar);const add=bar.querySelector('[data-environment-add]'),expand=bar.querySelector('[data-environment-expand]');let previousFocus=null;
  add.onclick=()=>{const picker=root.querySelector('[data-add-picker]');if(picker&&!picker.disabled){picker.value='';picker.click();}};
  add.disabled=!root.querySelector('[data-add-picker]');
  const setExpanded=value=>{
    if(value===host.classList.contains('is-expanded'))return;
    if(value)previousFocus=doc.activeElement;
    host.classList.toggle('is-expanded',value);expand.setAttribute('aria-expanded',String(value));expand.textContent=value?'Exit expanded view (Esc)':'Expand workspace';
    if(value)expand.focus({preventScroll:true});else(previousFocus?.isConnected?previousFocus:expand)?.focus?.({preventScroll:true});resize();
  };
  expand.onclick=()=>setExpanded(!host.classList.contains('is-expanded'));
  return {onKeyDown(event){
    if(event.key!=='Escape'||!host.classList.contains('is-expanded'))return;
    if([...root.querySelectorAll('[role="alertdialog"],.pano-studio-place-layer,[role="menu"],details[open]')].some(element=>!element.closest('[hidden],[aria-hidden="true"]')&&(!element.getClientRects||element.getClientRects().length)))return;
    event.preventDefault();event.stopImmediatePropagation();setExpanded(false);
  },dispose(){setExpanded(false);bar.remove();}};
}

/** Open the installed Panorama editor on an isolated native graph.
 * The artist's Graph view is never replaced. Only Apply returns native state.
 */
export async function openPanoramaEditor({app,state,geometryKey,output,source,sky=null,environment=false,host=null,onApply,onCancel,onError}){
  const create=app.createNode?.bind(app)||globalThis.LiteGraph?.createNode?.bind(globalThis.LiteGraph);
  if(!create)throw new Error('Update ComfyUI to open the Panorama camera editor.');
  const graph=new app.graph.constructor();
  const node=create('PanoramaStudio'),geometry=create(geometryKey?'ZuraCameraLoadScene':'LoadImage');
  if(!node||!geometry)throw new Error('Install Panorama 2.0.2 or newer and restart ComfyUI.');
  // IDs must be unique across app.nodeOutputs, not just inside this graph.
  node.id='zura-panorama-'+crypto.randomUUID();geometry.id='zura-geometry-'+crypto.randomUUID();
  graph.add(geometry);graph.add(node);node.title=environment?'Zura · Compose 360°':'Zura · Change camera angle';
  if(geometryKey)geometry.widgets.find(w=>w.name==='cache_key').value=geometryKey;else{const file=sky?.file;if(!file)throw new Error('Prepare a panorama source first.');geometry.widgets.find(w=>w.name==='image').value=[file.subfolder,file.filename].filter(Boolean).join('/')+(file.type==='output'?' [output]':'');}
  geometry.connect(0,node,node.inputs.findIndex(i=>i.name===(geometryKey?'world':sky.port||'background')));
  const widget=node.widgets.find(w=>w.name==='state_json');
  if(!widget)throw new Error('This Panorama version has no camera state control.');
  widget.value=state;
  for(const [name,value] of Object.entries({background_color:'#ff00ff',background_range:'360',multiple:8})){const w=node.widgets.find(w=>w.name===name);if(w)w.value=value;}
  const button=node.widgets.find(w=>w.name==='Open Studio Editor');
  if(!button?.callback)throw new Error('Update Panorama to use its interactive camera editor.');
  if(app.ui?.settings?.getSettingValue?.('PanoramaSuite.Editor.NewUI')===false){
    graph.clear();throw new Error('Enable “Panorama Studio: new editor” in ComfyUI settings, then reopen the camera.');
  }
  const outputs=app.nodeOutputs;
  if(!outputs){graph.clear();throw new Error('ComfyUI media outputs are unavailable. Reload this page.');}
  const set=value=>outputs instanceof Map?outputs.set(node.id,value):outputs[node.id]=value;
  set(output);
  const controls=document.createElement('div');controls.className='zc-panorama-actions';
  controls.setAttribute('role','group');controls.setAttribute('aria-label',environment?'Panorama changes':'Camera changes');
  controls.innerHTML='<span>Review the camera move, then apply.</span><button type="button" data-cancel>Cancel</button><button type="button" class="zc-panorama-apply" data-apply>Apply camera</button>';
  if(environment){controls.querySelector('span').textContent='Compose a still panorama. AI fills the missing areas afterwards.';controls.querySelector('[data-apply]').textContent='Use panorama';}
  let handle,editorRoot,disposeCamera,disposeSource,disposeAppearance,environmentControls,done=false,applying=false;
  // Capture before the vendor listener: expanded Escape restores this layout.
  const environmentKey=event=>environmentControls?.onKeyDown(event);
  if(environment&&host)window.addEventListener('keydown',environmentKey,true);
  const snapshot=()=>handle?.session?.stateText?.(node,widget.value)||widget.value;
  const previousCallback=widget.callback;
  const cleanup=()=>{
    if(done)return;done=true;observer.disconnect();disposeSource?.();disposeCamera?.();disposeAppearance?.();environmentControls?.dispose();window.removeEventListener('keydown',environmentKey,true);controls.remove();widget.callback=previousCallback;
    if(outputs instanceof Map)outputs.delete(node.id);else delete outputs[node.id];
    graph.clear();document.body.classList.remove('zura-camera-editor-open');
  };
  const cancel=()=>{if(done)return;applying=true;handle?.close();widget.value=state;cleanup();onCancel?.();};
  controls.querySelector('[data-cancel]').onclick=cancel;
  controls.querySelector('[data-apply]').onclick=async()=>{
    if(done||applying)return;applying=true;
    controls.querySelectorAll('button').forEach(b=>b.disabled=true);
    try{handle.close();const applied=widget.value;cleanup();await onApply(applied);}
    catch(error){cleanup();onError?.(error);}
  };
  // Native close/Escape is Cancel. Native state writes never change the shot.
  const observer=new MutationObserver(()=>{
    if(handle&&!applying&&!(editorRoot?.isConnected??document.querySelector('.pano-studio-backdrop')))cancel();
  });
  try{
    if(!host)document.body.classList.add('zura-camera-editor-open');
    handle=await button.callback();
    if(!handle?.close)throw new Error('Panorama did not open its camera editor. Enable its new editor and retry.');
    const root=editorRoot=document.querySelector('.pano-studio-backdrop');disposeAppearance=installPanoramaAppearance(root);if(host){host.replaceChildren(root);root.classList.add('zc-panorama-inline');const dialog=root.querySelector('[role=dialog]');if(dialog){dialog.setAttribute('role','region');dialog.setAttribute('aria-modal','false');}}if(environment){root.classList.add('zc-hdri-editor');if(host)environmentControls=installEnvironmentWorkspace(root,host);root.querySelector('.pano-studio-tabs [data-value="sky"]')?.click();}else{disposeCamera=cameraOnlyControls(handle,root);disposeSource=installSourcePreview(root,source);}
    if(!host){document.body.append(controls);controls.querySelector('[data-apply]').focus({preventScroll:true});}
    observer.observe(document.body,{childList:true,subtree:true});
    return {cancel,snapshot,root,dispose:()=>{applying=true;handle?.close();cleanup();}};
  }catch(error){handle?.close?.();cleanup();throw error;}
}

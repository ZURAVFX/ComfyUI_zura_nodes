/** Open the installed Panorama editor on an isolated native graph.
 * The artist's Graph view is never replaced. Only Apply returns native state.
 */
export async function openPanoramaEditor({app,state,geometryKey,output,onApply,onCancel,onError}){
  const create=app.createNode?.bind(app)||globalThis.LiteGraph?.createNode?.bind(globalThis.LiteGraph);
  if(!create)throw new Error('Update ComfyUI to open the Panorama camera editor.');
  const graph=new app.graph.constructor();
  const node=create('PanoramaStudio'),geometry=create('ZuraPanoramaLoadGeometry');
  if(!node||!geometry)throw new Error('Install Panorama 2.0.2 or newer and restart ComfyUI.');
  // IDs must be unique across app.nodeOutputs, not just inside this graph.
  node.id='zura-panorama-'+crypto.randomUUID();geometry.id='zura-geometry-'+crypto.randomUUID();
  graph.add(geometry);graph.add(node);node.title='Zura · Change camera angle';
  geometry.widgets.find(w=>w.name==='cache_key').value=geometryKey;
  geometry.connect(0,node,node.inputs.findIndex(i=>i.name==='world'));
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
  controls.setAttribute('role','group');controls.setAttribute('aria-label','Camera changes');
  controls.innerHTML='<span>Adjust the camera in the 3D preview. Timeline keyframes are supported.</span><button type="button" data-cancel>Cancel</button><button type="button" class="zc-panorama-apply" data-apply>Apply camera</button>';
  let handle,done=false,applying=false;
  const previousCallback=widget.callback;
  const cleanup=()=>{
    if(done)return;done=true;observer.disconnect();controls.remove();widget.callback=previousCallback;
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
    if(handle&&!applying&&!document.querySelector('.pano-studio-backdrop'))cancel();
  });
  try{
    document.body.classList.add('zura-camera-editor-open');
    handle=await button.callback();
    if(!handle?.close)throw new Error('Panorama did not open its camera editor. Enable its new editor and retry.');
    document.body.append(controls);observer.observe(document.body,{childList:true,subtree:true});
    controls.querySelector('[data-apply]').focus({preventScroll:true});
    return {cancel};
  }catch(error){handle?.close?.();cleanup();throw error;}
}

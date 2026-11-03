// A camera-only surface over Panorama's native session and interpolation.
// Painting, scene authoring and the artist's main graph remain outside this shot.
export function installBlenderCameraNavigation(handle,root,{keyCamera,status=()=>{}}={}){
  const win=root.ownerDocument.defaultView,stage=()=>handle.stage?.();
  const editable=target=>!!target?.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"])');
  const canvasFor=target=>target?.closest?.('[data-stage-canvas]');
  let dolly=null;
  const stop=event=>{event.preventDefault();event.stopImmediatePropagation();};
  const down=event=>{
    const canvas=canvasFor(event.target);if(!canvas)return;
    canvas.tabIndex=0;canvas.focus({preventScroll:true});
    if(event.button!==1){
      // Left click selects controls; it must not unexpectedly rotate the shot.
      if(event.button===0&&!event.altKey)event.stopPropagation();
      return;
    }
    if(event.metaKey)return;
    stop(event);
    if(handle.session?.readOnly||handle.session?.state.camera?.locked){status('Unlock the camera before editing it.');return;}
    canvas.setPointerCapture?.(event.pointerId);
    if(event.ctrlKey){dolly={canvas,id:event.pointerId,y:event.clientY};return;}
    // Use Panorama's native orbit/pan so its depth pivot, camera lanes,
    // interpolation, bounds and Undo remain the source of truth.
    stage()?.knobDown?.(event.shiftKey?'pan':'orbit',{
      button:0,pointerId:event.pointerId,clientX:event.clientX,clientY:event.clientY,
      currentTarget:canvas,altKey:false,shiftKey:false,ctrlKey:false,metaKey:false,
      preventDefault:()=>event.preventDefault(),
    });
  };
  const move=event=>{
    if(!dolly||event.pointerId!==dolly.id)return;
    stop(event);const dy=event.clientY-dolly.y;dolly.y=event.clientY;
    if(dy)dolly.canvas.dispatchEvent(new win.WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY:dy*4,deltaMode:0,clientX:event.clientX,clientY:event.clientY}));
  };
  const end=event=>{
    if(!dolly||event.pointerId!==dolly.id)return;
    const {canvas,id}=dolly;dolly=null;
    if(canvas.hasPointerCapture?.(id))canvas.releasePointerCapture(id);
    stage()?.settle?.();
  };
  const blur=()=>{if(dolly){dolly=null;stage()?.settle?.();}};
  const key=event=>{
    if(editable(event.target)||event.ctrlKey||event.metaKey||event.altKey)return;
    if(event.code==='KeyI'&&!event.shiftKey&&!event.repeat){stop(event);keyCamera?.();}
    else if(event.code==='Home'||event.code==='NumpadDecimal'){
      stop(event);stage()?.settle?.();stage()?.frameSelected?.();status('Scene framed at the current timeline position.');
    }else if(event.code==='Numpad0'){
      stop(event);root.querySelector('.pano-studio-tabs [data-value="camera"]')?.click();
    }
  };
  const autoscroll=event=>{if(event.button===1&&canvasFor(event.target))event.preventDefault();};
  root.addEventListener('pointerdown',down,true);root.addEventListener('mousedown',autoscroll,true);root.addEventListener('keydown',key,true);
  win.addEventListener('pointermove',move,true);win.addEventListener('pointerup',end,true);win.addEventListener('pointercancel',end,true);win.addEventListener('blur',blur);
  return ()=>{
    blur();root.removeEventListener('pointerdown',down,true);root.removeEventListener('mousedown',autoscroll,true);root.removeEventListener('keydown',key,true);
    win.removeEventListener('pointermove',move,true);win.removeEventListener('pointerup',end,true);win.removeEventListener('pointercancel',end,true);win.removeEventListener('blur',blur);
  };
}

export function cameraOnlyControls(handle,root){
  if(!root)throw new Error('The camera editor did not open. Close it and try again.');
  const session=handle.session,stage=()=>handle.stage?.();
  const cameraTab=root.querySelector('.pano-studio-tabs [data-value="camera"]');
  const selectCamera=root.querySelector('[data-head="camera"] [data-part="name"]');
  if(!session?.applyInspector||!cameraTab||!selectCamera||!root.querySelector('.pano-studio-main'))throw new Error('Update Panorama to use the guided camera controls.');
  cameraTab.click();selectCamera.click();
  root.classList.add('zc-camera-only');
  const toolbar=document.createElement('div');toolbar.className='zc-camera-toolbar';
  toolbar.innerHTML='<div><strong>Camera view</strong><span>Middle mouse: orbit · Shift + middle mouse: pan · Wheel: dolly</span></div><details class="zc-camera-navigation"><summary>Blender controls</summary><div class="zc-camera-navigation-panel"><dl><dt>Orbit</dt><dd>Middle mouse drag</dd><dt>Pan</dt><dd>Shift + middle mouse</dd><dt>Dolly</dt><dd>Wheel or Ctrl + middle mouse</dd><dt>Frame scene</dt><dd>Home / Numpad .</dd><dt>Camera view</dt><dd>Numpad 0</dd><dt>Key all camera properties</dt><dd>I</dd></dl><p>Move the camera, set a keyframe, then scrub and set the next pose. These controls move the rendered camera.</p></div></details><button type="button" data-reset-camera title="Return this frame to the source camera; other keyframes stay">Reset view</button><button type="button" data-key-camera title="Key position, rotation and lens at this frame (I)">Set camera keyframe</button><span data-camera-status role="status" aria-live="polite"></span>';
  root.querySelector('.pano-studio-main').prepend(toolbar);
  const frame=()=>{
    const number=Number(root.querySelector('.pano-studio-tl-frame')?.textContent?.split('/')[0]?.trim());
    if(!Number.isFinite(number)||number<0)throw new Error('The camera timeline is not ready. Reopen the camera editor.');
    return number;
  };
  const prepare=()=>{
    const playing=root.querySelector('[data-tl="play"][aria-label="Pause"]');
    playing?.click();stage()?.settle?.();
    if(session.readOnly||session.state.camera?.locked)throw new Error('Unlock the camera before editing it.');
    return frame();
  };
  const refresh=()=>{selectCamera.click();stage()?.redraw?.();};
  const act=fn=>{try{const at=prepare();fn(at);refresh();}catch(error){toolbar.querySelector('[data-camera-status]').textContent=error.message;}};
  toolbar.querySelector('[data-key-camera]').onclick=()=>act(at=>{
    for(const [lane,row] of [['position','position'],['rotation','rotation'],['fov','hfov'],['curve','lens']]){
      // A repeated press updates nothing and never removes an existing key.
      if(!session.state.camera[lane]?.keyframes?.some(key=>Math.abs(key.frame-at)<1e-6))
        session.applyInspector({type:'key',target:{kind:'camera'},row},{playhead:at});
    }
    toolbar.querySelector('[data-camera-status]').textContent=`Camera keyed at frame ${at}.`;
  });
  toolbar.querySelector('[data-reset-camera]').onclick=()=>act(at=>{
    // Native field edits preserve interpolation, existing keys and one Undo step.
    const values=[['curve',1],['position_x',0],['position_y',0],['position_z',0],['yaw_deg',0],['pitch_deg',0],['roll_deg',0],['hFOV_deg',85]];
    values.forEach(([field,value],i)=>session.applyInspector({type:'field',target:{kind:'camera'},field,value,phase:i===values.length-1?'commit':'input'},{playhead:at}));
    toolbar.querySelector('[data-camera-status]').textContent=`Source view restored at frame ${at}.`;
  });
  const disposeNavigation=installBlenderCameraNavigation(handle,root,{
    keyCamera:()=>toolbar.querySelector('[data-key-camera]').click(),
    status:message=>{toolbar.querySelector('[data-camera-status]').textContent=message;},
  });
  return ()=>{disposeNavigation();toolbar.remove();root.classList.remove('zc-camera-only');};
}

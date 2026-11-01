// A camera-only surface over Panorama's native session and interpolation.
// Painting, scene authoring and the artist's main graph remain outside this shot.
export function cameraOnlyControls(handle,root){
  if(!root)throw new Error('The camera editor did not open. Close it and try again.');
  const session=handle.session,stage=()=>handle.stage?.();
  const cameraTab=root.querySelector('.pano-studio-tabs [data-value="camera"]');
  const selectCamera=root.querySelector('[data-head="camera"] [data-part="name"]');
  if(!session?.applyInspector||!cameraTab||!selectCamera||!root.querySelector('.pano-studio-main'))throw new Error('Update Panorama to use the guided camera controls.');
  cameraTab.click();selectCamera.click();
  root.classList.add('zc-camera-only');
  const toolbar=document.createElement('div');toolbar.className='zc-camera-toolbar';
  toolbar.innerHTML='<div><strong>Camera view</strong><span>Move the camera, set a keyframe, then scrub to the next position.</span></div><button type="button" data-reset-camera title="Return this frame to the source camera; other keyframes stay">Reset view</button><button type="button" data-key-camera>Set camera keyframe</button><span data-camera-status role="status" aria-live="polite"></span>';
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
  return ()=>{toolbar.remove();root.classList.remove('zc-camera-only');};
}

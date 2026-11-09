const KEY='zura-relight-engine-v1';
const read=()=>{try{return localStorage.getItem(KEY)||'wan21';}catch{return'wan21';}};
const frameFile=file=>file&&('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'}));

/** Match the original plate, undoing a lighting model's smaller working raster. */
export async function lightingFrameAtSourceSize(owner,blob,source){
  const bitmap=await createImageBitmap(blob),canvas=owner.root.ownerDocument.createElement('canvas');
  canvas.width=source.width;canvas.height=source.height;
  try{canvas.getContext('2d').drawImage(bitmap,0,0,source.width,source.height);}finally{bitmap.close();}
  const png=await new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(Error('Could not prepare the lighting frame.')),'image/png'));
  return new File([png],'Lighting frame.png',{type:'image/png'});
}

/** Relight shares the proven edited-frame renderers without sharing its draft. */
export function installRelightEngines(owner){
  owner.relightEngine=['wan21','ltx','h3'].includes(read())?read():'wan21';
  owner.rememberRelightEngine=engine=>{owner.relightEngine=engine;try{localStorage.setItem(KEY,engine);}catch{}};
  owner.selectRelightEngine=engine=>selectRelightEngine(owner,engine);
}

export async function selectRelightEngine(owner,engine){
  if(!['wan21','ltx','h3'].includes(engine)||owner.relightSwitchPending)return;
  const studio=owner.studio,fromWan=owner.mode==='video'&&owner.studio.config.workflow_mode==='relight';if((fromWan||engine==='wan21')&&(studio.busy||studio.project?.phase==='working')){if(fromWan)owner.show('video');return;}
  const w=owner.rippleWorkspaces?.get('relight');if(w?.busy()){owner.ripple=w;owner.show('ripple');w.message('Finish or cancel the current Relight run before changing models.');return;}
  owner.relightSwitchPending=true;owner.videoComposer.sync?.();
  try{
    if(w?.state.relightCleared&&w.state.clearedStudioAssetId&&studio.source?.id===w.state.clearedStudioAssetId&&studio.config.workflow_mode==='relight'){if(await studio.reset()===false)throw Error('Finish the current operation before clearing the Relight source.');Object.assign(studio.config,{workflow_mode:'relight',engine:'h3',relight_engine:'wan21',edit_area:'scene'});}
    if(engine==='wan21'){
      const source=w?.state.studioAsset;
      if(studio.config.workflow_mode!=='relight'){studio.readyAsset=null;studio.lookMode='build';studio.invalidateLook();}
      Object.assign(studio.config,{workflow_mode:'relight',engine:'h3',relight_engine:'wan21',edit_area:'scene',h3_head_swap:false});
      if(source&&source.id!==studio.source?.id){studio.source=source;studio.readyAsset=null;studio.lookMode='build';studio.invalidateLook();}
      if(w?.source&&source){
        Object.assign(studio.config,{start:w.state.startFrame/w.fps(),duration:w.state.frameCount/w.fps(),length_mode:'custom',prompt:w.$('prompt').value,image_prompt:w.$('prompt').value});
        const anchor=w.selected()?.file?w.selected():w.anchors().find(a=>a.file&&a.enabled!==false&&a.frame>=w.state.startFrame&&a.frame<w.state.startFrame+w.state.frameCount);
        if(anchor?.file&&w.state.wanAnchorFile!==anchor.file){
          const exported=await owner.fetch('/zura/paintout/export-frame',{file:anchor.file,frame:0,colour_space:anchor.colour_space||'srgb_display'});
          const response=await owner.api.fetchApi(exported.url);if(!response.ok)throw Error('Could not transfer the lighting frame.');
          const previousReady=studio.readyAsset?.id;await studio.upload('ready',new File([await response.blob()],'Lighting frame.png',{type:'image/png'}));if(!studio.readyAsset?.id||studio.readyAsset.id===previousReady)throw Error('Could not transfer the lighting frame to Wan. Your edited frames are retained.');w.state.wanAnchorFile=anchor.file;w.state.wanOpeningKey=studio.readyAsset?.id;w.save();
        }
      }
      Object.assign(studio.config,{workflow_mode:'relight',engine:'h3',relight_engine:'wan21',edit_area:'scene',h3_head_swap:false});studio.syncForm();owner.rememberRelightEngine('wan21');owner.show('video');studio.render();return;
    }
    const target=owner.ensureRippleWorkspace('relight');
    const source=(fromWan||!target.state.sourcePath&&!target.state.relightCleared)?studio.source:null;
    if(source?.id&&target.state.studioAsset?.id!==source.id){
      const info=await owner.fetch('/zura/studio/assets/'+encodeURIComponent(source.id)+'/ripple',{});if(studio.source?.id!==source.id||fromWan&&studio.config.workflow_mode!=='relight')throw Error('The source changed. Choose the relight model again.');target.setSource({...info,name:source.name||info.name,studioAsset:source});
    }else if(!target.source)await target.restoreSource();
    if(fromWan&&target.source&&source?.id===target.state.studioAsset?.id){
      const fps=target.fps(),start=Math.max(0,Math.min(target.source.frames-1,Math.round((studio.config.start||0)*fps))),duration=studio.config.length_mode==='original'?target.source.frames-start:Math.max(1,Math.round((studio.config.duration||target.source.frames/fps)*fps));
      target.state.startFrame=start;target.state.frameCount=Math.min(duration,target.source.frames-start);target.state.playhead=Math.max(start,Math.min(start+target.state.frameCount-1,target.state.playhead||start));
      const prompt=studio.config.image_prompt||studio.config.prompt||'';target.state.prompt=prompt;target.$('prompt').value=prompt;
    }
    target.state.engine=engine;if(engine==='ltx'){const anchor=target.selected()?.file?target.selected():target.ltxReference();if(anchor)target.state.ltxReferenceId=anchor.id;}target.$('engine').value=engine;owner.rememberRelightEngine(engine);owner.show('ripple');
    const opening=studio.readyAsset,openingURL=opening?.url||studio.project?.opening_url||(opening?.filename?frameFile(opening):null),openingKey=opening?.id||studio.project?.opening_key;
    if(fromWan&&target.source&&openingURL&&openingKey&&target.state.wanOpeningKey!==openingKey){
      target.addAnchor(target.state.startFrame);const anchor=target.selected();
      const response=await owner.api.fetchApi(openingURL);if(!response.ok)throw Error('Could not transfer the reviewed lighting image.');
      const image=await lightingFrameAtSourceSize(owner,await response.blob(),target.source);await target.importAnchorFile(anchor,image);target.state.wanOpeningKey=openingKey;target.state.wanAnchorFile=anchor.file;
    }
    target.save();target.render();owner.videoComposer.syncWorkflow();
  }catch(error){const target=owner.ripple?.intent==='relight'?owner.ripple:null;if(target&&owner.mode==='ripple')target.message(error.message);else studio.message?.(error.message,true);}
  finally{owner.relightSwitchPending=false;if(owner.mode==='video')owner.videoComposer.sync?.();else if(owner.mode==='ripple')owner.ripple?.render();}
}

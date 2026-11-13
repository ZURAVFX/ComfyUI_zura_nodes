import {sourceAEFrameContract,bindAEFrameWorkspace} from './studio_ae_frame_contract.js';
import {referenceVideoDimensions,REFERENCE_VIDEO_CAPABILITIES} from './reference_video_recipes.js';
// Native Studio modes. Data crosses typed workspace methods, never a DOM preview.
const definitions=[['swap','Character replacement','Video'],['ripple','Ripple editing','Video'],['viewport','Viewport to final','Video'],['camera','Change camera angle','Video'],['relight','Relight','Video'],['paintout','Paintout / clean plate','Video'],['watermark','Watermark removal','Video'],['alpha','Extract alpha','Video'],['outpaint','Frame extension','Video'],['hdr','Convert to HDR','Video'],['director','Director','Authored'],['frames','First & last frame','Endpoint'],['references','Reference to video','Reference'],['image','Image','Image']];
const mainModes=new Set(['swap','viewport']);
export async function navigateStudioMode(creative,id){
  if(id==='plate')return creative.plate.select();
  if(id==='paintout'&&creative.plate)return creative.plate.select(creative.plate.action||'remove');
  if(id==='inpaint'||id==='objects')id='ripple';
  if(id==='panorama')id='camera';
  if(id==='camera')return creative.show('panorama');
  if(id==='ripple'){creative.ensureRippleWorkspace?.('edit');return creative.show('ripple');}
  if(id==='hdr')return creative.openHDR();
  if(id==='relight')return creative.selectRelightEngine(creative.relightEngine||'wan21');
  if(mainModes.has(id))return creative.videoComposer.selectWorkflow(id);
  if(['home','video',...definitions.map(d=>d[0])].includes(id))return creative.show(id);
}
export function activeStudioMode(creative){
  if(creative.mode==='image'&&creative.rippleImage?.request?.workspace?.platePrimary)return 'paintout';
  if(creative.mode==='panorama')return 'camera';
  if(creative.mode==='ripple'&&creative.ripple?.intent==='relight')return 'relight';
  return creative.mode==='video'?(creative.studio.config.workflow_mode==='motion'?'swap':creative.studio.config.workflow_mode||'swap'):creative.mode;
}
function workspace(creative,id){
  if(mainModes.has(id)||id==='relight'&&creative.mode==='video')return creative.studio;
  return ({image:creative,camera:creative.panorama,hdr:creative.studio.hdrTool,references:creative.referencesVideo,relight:creative.ripple})[id]||creative[id];
}
function busy(w){return (!!w&&(typeof w.busy==='function'?!!w.busy():!!w.busy))||!!(w?.job||w?.pendingSubmission||w?.submitting||w?.uploading||w?.picking||w?.exporting||w?.project?.phase==='working'||w?.hdrDelivery?.busy||w?.hdrOutput?.busy);}
const validFile=file=>file&&typeof file.filename==='string'&&file.type==='output';
// ComfyUI asset records also carry UI metadata and IDs. Only the contained file
// identity belongs in the strict transfer descriptor; labels are not authority.
const alphaFileRef=file=>({filename:file.filename,subfolder:file.subfolder||'',type:file.type});
function transferFileRefs(result){
  if(!result)return null;const clean={};
  for(const key of ['kind','master','preview','original','colour','alpha','width','height','frameCount','fps','precision'])if(Object.prototype.hasOwnProperty.call(result,key))clean[key]=result[key];
  for(const key of ['master','preview','original']){
    if(clean[key]===undefined)continue;
    if(Array.isArray(clean[key])){if(!clean[key].every(validFile))return null;clean[key]=clean[key].map(alphaFileRef);}
    else{if(!validFile(clean[key]))return null;clean[key]=alphaFileRef(clean[key]);}
  }
  return clean;
}
function output(value,kind='video'){
  if(!value)return null;const master=value.master||value.file||value;
  if(!validFile(master))return null;
  const descriptorKind=/\.(zip|exr)$/i.test(master.filename)?'hdr_sequence':master.filename==='manifest.json'?'float_manifest':kind;
  return {kind:descriptorKind,master:alphaFileRef(master),...(value.file&&master!==value.file&&validFile(value.file)?{preview:alphaFileRef(value.file)}:{}),...(value.colour?{colour:value.colour}:{}),...(value.alpha?{alpha:value.alpha}:{})};
}
function hdrOutput(value){
  const raw=value?.hdrFiles||value?.hdr_files||value?.files||[],files=Array.isArray(raw)?raw:Object.values(raw);
  const master=files.find(f=>/\.(zip|exr)$/i.test(f.filename||''))||files.find(f=>/\.(mov|mp4)$/i.test(f.filename||''));
  return master?output({master,colour:value.colour},/\.(zip|exr)$/i.test(master.filename)?'hdr_sequence':'video'):null;
}
function selectedOutput(c,id,w){
  if(!w)return null;
  if(id==='image')return output(w.items?.[w.selectedImage],'image');
  if(id==='alpha')return w.result?.native_hdr?{kind:'hdr_sequence',master:alphaFileRef(w.result.native_hdr),preview:alphaFileRef(w.result.alpha),colour:{encoding:'acescg',sceneLinear:true},alpha:'straight'}:w.result?.ae_float&&w.result?.alpha?{kind:'alpha_extract',master:alphaFileRef(w.result.ae_float),original:alphaFileRef(w.result.alpha),alpha_ref:alphaFileRef(w.result.ae_float),...(w.result.ae_float.colour?{colour:w.result.ae_float.colour}:{})}:w.result?.alpha?{...output({master:alphaFileRef(w.result.alpha)},'video'),...(w.result.alpha_float?{alpha_ref:alphaFileRef(w.result.alpha_float)}:{})}:null;
  if(id==='camera')return output(w.state?.result);
  if(id==='hdr')return hdrOutput(w.completedResult);
  if(id==='outpaint')return w.hdrRecord?.state==='complete'?hdrOutput(w.hdrRecord.take):hdrOutput(w.completedResult)||output(w.completedResult?.artifact);
  if(id==='director')return w.resultView?output(w.selectedResult):null;
  if(id==='frames'||id==='references'){
    const file=w.selectedResult,take=w.items?.find(item=>item.file===file||item.file?.filename===file?.filename&&item.file?.subfolder===file?.subfolder);
    return hdrOutput(take)||output(file);
  }
  if(w===c.studio){
    const result=w.selectedTake||w.project?.results?.at(-1);
    if(!['done','draft'].includes(w.project?.phase))return null;
    const delivery=c.videoComposer?.ltxOutput?.result?.({...w.project,results:result?[result]:[]});
    return hdrOutput(delivery)||hdrOutput(result)||output(result?.asset);
  }
  if(w.result?.stage==='repair'&&/\.(zip|exr)$/i.test(w.result?.master?.filename||''))return null;
  return output(w.result);
}
function requireValue(value,message){if(!value)throw Error(message);return value;}
export function studioProcessingInput(source,id){return id!=='hdr'&&source.processingInput?.precision?.sourceBitDepth===8?source.processingInput:source;}
const aeSourceOwned=value=>value?.aeSourceInput?.schemaVersion===1;
function fileIdentity(value){
  const path=typeof value?.file==='string'?value.file:[value?.subfolder,value?.filename||value?.name].filter(Boolean).join('/');
  return path?`${value?.type||'input'}:${path.replaceAll('\\','/')}`:null;
}
function sourceDimensions(source){
  const input=studioProcessingInput(source),first=Array.isArray(input.stills)?input.stills[0]:input.stills?.first;
  return {width:source.width||first?.width,height:source.height||first?.height};
}
function sourceFrameDimensions(source,frame){
  const raster=sourceDimensions(source),valid=value=>Number.isSafeInteger(value)&&value>0;
  // Broker stills may contain only a file identity. Carry the verified source
  // raster into every still consumer so image models can select their grid.
  return {...frame,width:valid(frame.width)?frame.width:raster.width,height:valid(frame.height)?frame.height:raster.height};
}
function referenceSourceDimensions(source){
  const size=sourceDimensions(source);
  try{
    if(![size.width,size.height].every(value=>Number.isSafeInteger(value)&&value>0))throw Error();
    const step=REFERENCE_VIDEO_CAPABILITIES.dimensionStep;
    return referenceVideoDimensions({width:Math.ceil(size.width/step)*step,height:Math.ceil(size.height/step)*step});
  }catch{
    throw Error(`Reference to video cannot process this AE raster (${size.width||'?'} × ${size.height||'?'}). Its aligned working size must fit H3's 4096-pixel sides and 8.39 MP canvas. Choose another Studio mode`);
  }
}
function sourceReferences(existing,frames){
  const keys=new Set(),source=[];
  for(const [index,frame] of frames.entries()){
    const key=fileIdentity(frame);if(!key||keys.has(key))continue;keys.add(key);
    // This marker only records UI ownership. It grants no transfer authority.
    const user=existing.find(value=>!aeSourceOwned(value)&&fileIdentity(value)===key);
    source.push({...user,...frame,...(!user?{aeSourceInput:{schemaVersion:1,role:index?'last':'first'}}:{})});
  }
  return [...source,...existing.filter(value=>!aeSourceOwned(value)&&!keys.has(fileIdentity(value)))];
}
function sourceDirectorClips(clips,frame){
  const key=fileIdentity(frame),legacy=clip=>clip.kind==='image'&&clip.startFrame===0&&clip.endFrame===1&&fileIdentity(clip.asset)===key;
  const previous=clips.find(aeSourceOwned)||clips.find(legacy);
  if(!previous&&clips.some(clip=>clip.kind==='image'&&clip.startFrame<1&&clip.endFrame>0))throw Error('Director already has an image at frame 0. Move that image before loading the AE source; your timeline is unchanged');
  const source=previous?{...previous,asset:{...frame}}:{id:globalThis.crypto.randomUUID(),kind:'image',startFrame:0,endFrame:1,asset:{...frame},text:'',strength:1};
  source.aeSourceInput={schemaVersion:1,role:'first'};
  return [source,...clips.filter(clip=>clip!==previous&&!aeSourceOwned(clip)&&!legacy(clip))];
}
function matchesInput(c,id,source){
  const w=workspace(c,id),input=studioProcessingInput(source,id);
  if(w===c.studio)return !!input.studioAsset?.id&&w.source?.id===input.studioAsset.id;
  if(id==='ripple'||id==='relight'){
    if(input.mediaInfo?.path&&w?.source?.path===input.mediaInfo.path)return true;
    return !!input.studioAsset?.id&&w?.state?.studioAsset?.id===input.studioAsset.id;
  }
  return false;
}
function sdrSourceInfo(source,input,info){
  // The broker's processing copy contains display-sRGB samples. Untagged FFV1
  // inspection must not reinterpret those samples using its Rec.709 fallback.
  const detected=info?.resolved_colour;
  const colour=input!==source?'srgb_display':['srgb_display','rec709_gamma24','rec709_oetf'].includes(detected)?detected:'srgb_display';
  const resolved={...info,resolved_colour:colour};
  if(input!==source){
    // This is the verified broker-created sRGB view. Its lossless container may
    // be untagged, so an automatic preview would repeat a detection error that
    // no longer applies to these explicitly interpreted samples.
    delete resolved.colour_error;
    if(typeof resolved.thumbnail_url==='string'){
      const url=new URL(resolved.thumbnail_url,'http://studio.invalid');
      if(url.origin==='http://studio.invalid'&&url.pathname==='/zura/paintout/frame-preview'){
        url.searchParams.set('space',colour);resolved.thumbnail_url=url.pathname+url.search;
      }
    }
  }
  return resolved;
}
function resetSDRSourceColour(workspace,info){
  Object.assign(workspace.state,{sourceColour:info.resolved_colour,sourceColourConfirmed:true,
    colourPipeline:'sdr_sdr',processingSpace:'SDR (sRGB)',outputMode:'SDR video'});
  for(const [id,key] of [['colour','sourceColour'],['processing','processingSpace'],['output','outputMode']]){
    const control=workspace.$?.(id);if(control)control.value=workspace.state[key];
  }
}
export function assertStudioSourceMode(source,id){
  const input=studioProcessingInput(source,id),asset=input.studioAsset;
  if((input.precision?.sourceBitDepth>8||asset?.native_hdr_video||asset?.native_hdr)&&id!=='hdr')throw Error(source.nativeImport?.diagnostic||'This mode needs 8-bit SDR processing. Choose 8-bit in After Effects and send the shot again. The floating-point source is retained');
  if(id==='image'&&(source.manifest?.frames?.length??source.frameCount??1)!==1)throw Error('Image mode produces one frame. Choose Current frame in After Effects or use a video mode for this range');
  if(id==='references')referenceSourceDimensions(source);
}
async function accept(c,id,w,source,isActive){
  assertStudioSourceMode(source,id);
  const input=studioProcessingInput(source,id),asset=input.studioAsset,stills=input.stills||{},frames=(Array.isArray(stills)?stills:[stills.first,stills.last].filter(Boolean)).map(frame=>sourceFrameDimensions(source,frame));
  let info=input.mediaInfo;
  if(!info&&asset?.id&&['ripple','relight','alpha','paintout','watermark'].includes(id)&&w!==c.studio){
    // The paintout asset endpoint deliberately accepts HDR only. All ordinary
    // SDR video editors share the verified native SDR inspection endpoint.
    info=await c.fetch('/zura/studio/assets/'+encodeURIComponent(asset.id)+'/ripple',{});
    if(!isActive())return;
  }
  const imported=!!source.originalAssetId&&asset?.processingView?.kind==='sdr8_inference';
  const duration=imported?asset.duration:Math.min(2,asset?.duration||2);
  if(w===c.studio){requireValue(asset,'This source has no native video input for this mode');if(asset.native_hdr_video)throw Error('Choose Convert to HDR for this floating-point source');w.source=asset;w.project=null;w.lastVideo=null;w.hdrSourceLook=false;w.config.start=0;w.config.duration=duration;w.syncForm();w.render();return;}
  if(id==='hdr'){
    requireValue(asset,'This source is not available as a native HDR input');
    if(input.precision?.sourceBitDepth>8||asset.native_hdr_video||asset.native_hdr)w.setSequenceAsset(asset,{fps:source.fps,colour:input.colour,nativeInputColour:input.nativeInputColour||asset.nativeInputColour});else w.setOwnAsset(asset);
    return;
  }
  if(id==='outpaint'){
    requireValue(asset,'This source has no frame-extension video input');
    if(imported&&w.trim&&(source.frameCount<3||source.frameCount>w.trim.maxFrames()&&!w.trim.canLong()))throw Error('This frame-extension mode cannot use the selected range. Choose at least 3 frames within its clip limit, or enable long clips.');
    w.setSourceAsset(asset);
    if(imported&&w.trim){if(source.frameCount>w.trim.maxFrames())w.trim.longMode.checked=true;w.trim.commit({start:0,duration});}
    return;
  }
  if(id==='ripple'||id==='relight'||id==='alpha'){
    w.setSource(sdrSourceInfo(source,input,requireValue(info,'This source has no native media input for this mode')));
    if(imported){w.state.startFrame=0;w.state.frameCount=source.frameCount;w.save();w.render();}return;
  }
  if(id==='paintout'||id==='watermark'){
    info=sdrSourceInfo(source,input,requireValue(info,'This source has no paintout media input'));resetSDRSourceColour(w,info);w.applySourceInfo(info);
    if(imported){w.state.startFrame=0;w.state.frameCount=source.frameCount;const count=w.$?.('count');if(count)count.value=String(source.frameCount);w.save();w.render();}return;
  }
  if(id==='camera'){w.state={...w.state,source:requireValue(asset,'This source has no camera video input'),config:{start:0,duration}};for(const key of ['result','geometry','camera','warp','selection','opening','sourceOpening','guidePreview'])delete w.state[key];w.save();w.showMedia('source');w.render();return;}
  requireValue(frames[0],'This source has no still-frame input for this mode');
  if(id==='frames'){w.assets.first=frames[0];w.assets.last=frames.at(-1);w.selectAvailability();w.save();w.preview('first');w.render();return;}
  if(id==='references'){
    const {width,height}=referenceSourceDimensions(source);
    w.assets.images=sourceReferences(w.assets.images,frames);
    for(const [id,value] of [['size-preset','custom'],['width',String(width)],['height',String(height)]]){const control=w.$?.(id);if(control)control.value=value;}
    w.selectAvailability?.();w.save();w.preview();w.render();return;
  }
  if(id==='image'){
    await w.setImageOperation('edit',{useCanvas:false});if(!isActive())return;
    w.clearImageResult();w.editMainMissing=false;w.references=sourceReferences(w.references,[frames[0]]);
    const width=source.width||frames[0].width,height=source.height||frames[0].height;
    if(Number.isSafeInteger(width)&&width>0&&Number.isSafeInteger(height)&&height>0){
      for(const [id,value] of [['shape','auto'],['width',String(width)],['height',String(height)]]){const control=w.$?.(id);if(control)control.value=value;}
      w.imageSizeRatio=width/height;
    }
    w.save();w.render();return;
  }
  if(id==='director'){w.draft.clips=sourceDirectorClips(w.draft.clips,frames[0]);w.resultView=false;w.save();w.render();return;}
  throw Error('This native mode does not accept the selected source');
}
export const STUDIO_MODE_ADAPTERS=Object.freeze(definitions.map(([id,label,compatibility])=>Object.freeze({id,label,compatibility,
  resolveWorkspace:c=>workspace(c,id),isBusy:c=>busy(workspace(c,id))||workspace(c,id)===c.studio&&!!c.videoComposer?.ltxOutput?.delivery?.busy||!!c.outputSettings?.delivery?.isBusyFor(id),
  matchesInput:(c,source)=>matchesInput(c,id,source),
  async acceptInput(c,source,{sessionId,isActive=()=>true}={}){assertStudioSourceMode(source,id);if(!isActive())return;await navigateStudioMode(c,id);if(!isActive())return;const w=workspace(c,id);if(busy(w))throw Error('Finish the current operation before loading the AE source');await accept(c,id,w,source,isActive);if(sessionId&&isActive())bindAEFrameWorkspace(c,id,w,sourceAEFrameContract(source,sessionId));},
  getSelectedOutput:c=>{const raw=selectedOutput(c,id,workspace(c,id)),delivery=c.outputSettings?.delivery;if(delivery?.readingOutput)return raw;return transferFileRefs(delivery?delivery.outputFor(id,raw):raw);},
})));
export const studioModeAdapter=id=>STUDIO_MODE_ADAPTERS.find(adapter=>adapter.id===id);

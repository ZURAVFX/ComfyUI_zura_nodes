import {preferNativeHDRSource} from './studio_hdr_capabilities.js';
import {sourceAEFrameContract,bindAEFrameWorkspace,clearAEFrameWorkspace} from './studio_ae_frame_contract.js';
import {referenceVideoDimensions,REFERENCE_VIDEO_CAPABILITIES} from './reference_video_recipes.js';
import {paintoutOutputDescriptor,paintoutPreviewFile} from './paintout_studio/paintout_outputs.js';
import {deliveryVideoColour} from './studio_delivery_formats.js';
// Native Studio modes. Data crosses typed workspace methods, never a DOM preview.
const definitions=[['swap','Character replacement','Video'],['ripple','Ripple editing','Video'],['viewport','Viewport to final','Video'],['camera','Change camera angle','Video'],['relight','Relight','Video'],['paintout','Paintout / clean plate','Video'],['watermark','Watermark removal','Video'],['alpha','Extract alpha','Video'],['outpaint','Frame extension','Video'],['hdr','Convert to HDR','Video'],['paint_vfx','Paint VFX','Painted'],['director','Director','Authored'],['frames','First & last frame','Endpoint'],['references','Reference to video','Reference'],['image','Image','Image']];
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
function busy(w){return (!!w&&(typeof w.busy==='function'?!!w.busy():!!w.busy))||!!(w?.imageLayers?.busy||w?.job||w?.pendingSubmission||w?.submitting||w?.uploading||w?.picking||w?.exporting||w?.project?.phase==='working'||w?.hdrDelivery?.busy||w?.hdrOutput?.busy);}
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
  const preview=value.preview||master.preview||(value.file&&master!==value.file?value.file:null);
  return {kind:descriptorKind,master:alphaFileRef(master),...(validFile(preview)?{preview:alphaFileRef(preview)}:{}),...(value.colour||master.colour?{colour:value.colour||master.colour}:{}),...(value.alpha?{alpha:value.alpha}:{})};
}
function hdrOutput(value){
  const raw=value?.hdrFiles||value?.hdr_files||value?.files||[],files=Array.isArray(raw)?raw:Object.values(raw);
  const master=files.find(f=>/\.(zip|exr)$/i.test(f.filename||''))||files.find(f=>/\.(mov|mp4)$/i.test(f.filename||''));
  return master?output({master,preview:value.preview||value.file,colour:value.colour||(/\.mov$/i.test(master.filename)?deliveryVideoColour(master,value):undefined)},/\.(zip|exr)$/i.test(master.filename)?'hdr_sequence':'video'):null;
}
function selectedOutput(c,id,w){
  if(!w)return null;
  if(id==='image'){
    const item=w.items?.[w.selectedImage];if(item?.image_layer_error)return null;
    const selected=output(item,'image');
    // Image Layers produces an SDR FLOAT composite with a product receipt.
    // Its EXR remains the physical master; the PNG is display-only. The broker
    // verifies the receipt and source lineage before accepting a return.
    if(selected?.kind==='hdr_sequence'&&item?.image_layers?.schemaVersion===1&&
        item?.colour?.encoding==='srgb_display'&&item?.colour?.sceneLinear===false&&
        item?.master?.type==='output'&&/\.exr$/i.test(item.master.filename||''))return {...selected,kind:'image'};
    return selected;
  }
  if(id==='alpha')return w.result?.native_hdr?{kind:'hdr_sequence',master:alphaFileRef(w.result.native_hdr),preview:alphaFileRef(w.result.alpha),colour:{encoding:'acescg',sceneLinear:true},alpha:'straight'}:w.result?.ae_float&&w.result?.alpha?{kind:'alpha_extract',master:alphaFileRef(w.result.ae_float),original:alphaFileRef(w.result.alpha),alpha_ref:alphaFileRef(w.result.ae_float),...(w.result.ae_float.colour?{colour:w.result.ae_float.colour}:{})}:w.result?.alpha?{...output({master:alphaFileRef(w.result.alpha)},'video'),...(w.result.alpha_float?{alpha_ref:alphaFileRef(w.result.alpha_float)}:{})}:null;
  if(id==='paint_vfx'){const value=output(w.result);return value?{...value,width:w.result.config.width,height:w.result.config.height,frameCount:w.result.config.frames,fps:w.result.config.fps,colour:{encoding:'srgb_display',sceneLinear:false}}:null;}
  if(id==='camera')return output(w.state?.result);
  if(id==='hdr')return hdrOutput(w.completedResult);
  if(id==='outpaint')return w.hdrRecord?.state==='complete'?hdrOutput(w.hdrRecord.take):hdrOutput(w.completedResult)||output(w.completedResult?.artifact);
  if(id==='director')return w.resultView?output(w.selectedResult):null;
  if(id==='frames'||id==='references'){
    if(w.$?.('result')?.hidden===true)return null;
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
  if(id==='paintout')return paintoutOutputDescriptor(w.result);
  return output(w.result);
}
function requireValue(value,message){if(!value)throw Error(message);return value;}
const sameRecord=(a,b)=>{
  if(a===b)return true;
  if(!a||!b||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)!==Array.isArray(b))return false;
  const keys=Object.keys(a);return keys.length===Object.keys(b).length&&keys.every(key=>Object.hasOwn(b,key)&&sameRecord(a[key],b[key]));
};
export function isRawNumericProcessingInput(source){
  const input=source?.processingInput;if(input?.conversion!=='raw_numeric_to_sdr8')return false;
  const rendered=source.sourceTransfer,storage={png8:['uint8',8],png16:['uint16_png',16]}[rendered?.profile];
  const renderedPNG=storage&&rendered.schemaVersion===2&&rendered.kind==='native_still'&&source.frameCount===1&&
      source.precision?.sampleType===storage[0]&&source.precision?.transferBitDepth===storage[1]&&source.precision?.storageBitDepth===storage[1]&&
      rendered.transferBitDepth===storage[1]&&rendered.storageBitDepth===storage[1]&&rendered.sourceBitDepth===32&&
      rendered.width===source.manifest?.width&&rendered.height===source.manifest?.height&&sameRecord(rendered.sourceColour,source.colour);
  if(input.schemaVersion!==1||input.precision?.sourceBitDepth!==8||input.precision?.sampleType!=='uint8'||
      input.sourceProcessingPrecision!=='sdr8'||input.samplePolicy!=='clamp_round_unorm8'||input.colourAssignment!=='numeric_sdr8_code_values'||
      !/^[a-f0-9]{64}$/.test(input.sourceManifestSha256||'')||
      source.precision?.sourceBitDepth!==32||source.precision?.sampleType!=='float32'&&!renderedPNG||source.alpha!=='straight'||
      source.manifest?.sampleType!=='float32'||source.manifest?.sourceBitDepth!==32||source.manifest?.alphaAssociation!=='straight'||
      !sameRecord(source.colour,source.manifest.colour)||!sameRecord(input.sourceColour,source.colour)||
      input.colour?.encoding!=='srgb_display'||input.colour?.sceneLinear!==false||input.alphaAssociation!=='straight'){
    throw Error('The raw 8-bit AE copy no longer matches its captured source. Send the shot again from After Effects.');
  }
  return true;
}
export function studioProcessingInput(source,id,creative=null){if(preferNativeHDRSource(creative,id,source))return source;return (id!=='hdr'||isRawNumericProcessingInput(source))&&source.processingInput?.precision?.sourceBitDepth===8?source.processingInput:source;}
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
  const w=workspace(c,id),input=studioProcessingInput(source,id,c);
  if(w===c.studio)return !!input.studioAsset?.id&&w.source?.id===input.studioAsset.id;
  if(['paintout','watermark'].includes(id)&&preferNativeHDRSource(c,id,source)&&input.mediaInfo){
    const info=studioSourceMediaInfo(source,input,input.mediaInfo,true);
    if(w.state?.sourceColour!==info.resolved_colour||Math.abs(Number(w.state?.sequenceFps)-source.fps)>1e-8)return false;
  }
  if(isRawNumericProcessingInput(source)&&['paintout','watermark'].includes(id))return !!input.mediaInfo?.path&&w?.state?.source===input.mediaInfo.path&&w?.sourceInfo?.path===input.mediaInfo.path;
  if(['ripple','relight','alpha','paintout','watermark'].includes(id)){
    if(input.mediaInfo?.path&&w?.source?.path===input.mediaInfo.path)return true;
    if(input.mediaInfo?.path&&(w?.sourceInfo?.path===input.mediaInfo.path||w?.state?.source===input.mediaInfo.path))return true;
    return !!input.studioAsset?.id&&w?.state?.studioAsset?.id===input.studioAsset.id;
  }
  if(id==='camera')return !!input.studioAsset?.id&&w?.state?.source?.id===input.studioAsset.id;
  if(id==='outpaint')return !!input.studioAsset?.id&&w?.source?.id===input.studioAsset.id;
  if(id==='hdr')return !!input.studioAsset?.id&&(w?.ownAsset?.id===input.studioAsset.id||w?.sequenceAsset?.id===input.studioAsset.id);
  const stills=input.stills||{},first=Array.isArray(stills)?stills[0]:stills.first,last=Array.isArray(stills)?stills.at(-1):stills.last||first,key=fileIdentity(first);
  if(id==='frames'&&preferNativeHDRSource(c,id,source))return !!key&&w?.assets?.first?.aeNativeSourceKey===key&&w?.assets?.last?.aeNativeSourceKey===fileIdentity(last);
  if(id==='frames')return !!key&&fileIdentity(w?.assets?.first)===key&&fileIdentity(w?.assets?.last)===fileIdentity(last);
  if(id==='references')return !!key&&fileIdentity(w?.assets?.images?.[0])===key;
  if(id==='image'){
    if(!key)return false;
    if(fileIdentity(w?.references?.[0])===key)return true;
    const selected=w?.items?.[w.selectedImage],stack=selected?.image_layers;
    return stack?.schemaVersion===1&&!selected.image_layer_error&&
      fileIdentity(stack.source)===key&&
      fileIdentity(w?.references?.[0])===fileIdentity(stack.conditioningInput);
  }
  if(id==='director')return !!key&&w?.draft?.clips?.some(clip=>aeSourceOwned(clip)&&fileIdentity(clip.asset)===key);
  return false;
}
export function studioSourceMediaInfo(source,input,info,native=false){
  if(!native)return sdrSourceInfo(source,input,info);
  const mapped={scene_linear_rec709:'linear_rec709'};
  const candidates=[source.resolved_colour,input.resolved_colour,source.nativeInputColour?.encoding,input.studioAsset?.resolved_colour,info.resolved_colour];
  const space=candidates.map(value=>mapped[value]||value).find(value=>['linear_rec709','acescg','acescct','hlg_rec2020','pq_rec2020','pq_display_p3'].includes(value));
  if(!['linear_rec709','acescg','acescct','hlg_rec2020','pq_rec2020','pq_display_p3'].includes(space))throw Error('The native HDR source colour space is unavailable. Reload the AE source.');
  return {...info,resolved_colour:space,colour_space:space,fps:source.fps,frames:source.frameCount};
}

function sdrSourceInfo(source,input,info){
  // A raw numeric processing copy is an ordinary uploaded clip. Its measured
  // metadata and browser proxy belong to the normal uploader, not an inferred
  // sRGB colour conversion. Keep the captured working identity on `source`.
  if(isRawNumericProcessingInput(source))return info;
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
  for(const [id,key] of [['colour','sourceColour'],['fps','sequenceFps'],['processing','processingSpace'],['output','outputMode']]){
    const control=workspace.$?.(id);if(control)control.value=workspace.state[key];
  }
}
export const isNativeVideoSource=source=>source?.sourceTransfer?.kind==='native_video'&&source.sourceTransfer.schemaVersion===2;
export function assertStudioSourceMode(source,id,creative=null){
  if(id==='paint_vfx')throw Error('Paint VFX creates an independent asset and does not accept an AE source shot. Leave the AE session to use this mode.');
  isRawNumericProcessingInput(source);
  const input=studioProcessingInput(source,id,creative),asset=input.studioAsset;
  if((input.precision?.sourceBitDepth>8||asset?.native_hdr_video||asset?.native_hdr)&&id!=='hdr'&&!isNativeVideoSource(source)&&!preferNativeHDRSource(creative,id,source)){
    if(input===source&&source.colour?.management==='icc'&&source.colour?.encoding==='ae_project_icc')throw Error('This colour profile can be previewed, but is not supported for processing yet.');
    throw Error(source.nativeImport?.diagnostic||'This mode needs 8-bit SDR processing. Choose 8-bit in After Effects and send the shot again. The floating-point source is retained');
  }
  if(id==='image'&&(source.manifest?.frames?.length??source.frameCount??1)!==1)throw Error('Image mode produces one frame. Choose Current frame in After Effects or use a video mode for this range');
  if(id==='references')referenceSourceDimensions(source);
}
async function accept(c,id,w,source,isActive){
  assertStudioSourceMode(source,id,c);
  const input=studioProcessingInput(source,id,c),asset=input.studioAsset,stills=input.stills||{},frames=(Array.isArray(stills)?stills:[stills.first,stills.last].filter(Boolean)).map(frame=>sourceFrameDimensions(source,frame));
  let info=input.mediaInfo;
  if(!info&&asset?.id&&['ripple','relight','alpha','paintout','watermark'].includes(id)&&w!==c.studio){
    // The paintout asset endpoint deliberately accepts HDR only. All ordinary
    // SDR video editors share the verified native SDR inspection endpoint.
    info=await c.fetch('/zura/studio/assets/'+encodeURIComponent(asset.id)+(preferNativeHDRSource(c,id,source)?'/paintout':'/ripple'),preferNativeHDRSource(c,id,source)?{colour_space:source.resolved_colour||'auto',sequence_fps:source.fps}:{});
    if(!isActive())return;
  }
  const native=preferNativeHDRSource(c,id,source),rawNumeric=isRawNumericProcessingInput(source),imported=native||rawNumeric||isNativeVideoSource(source)||!!source.originalAssetId&&asset?.processingView?.kind==='sdr8_inference';
  const duration=imported?(asset.duration??source.frameCount/source.fps):Math.min(2,asset?.duration||2);
  if(w===c.studio){requireValue(asset,'This source has no native video input for this mode');if(asset.native_hdr_video&&!native)throw Error('Choose Convert to HDR for this floating-point source');w.source=asset;w.project=null;w.lastVideo=null;w.hdrSourceLook=false;w.config.start=0;w.config.duration=duration;w.syncForm();w.render();return;}
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
    w.setSource(studioSourceMediaInfo(source,input,requireValue(info,'This source has no native media input for this mode'),native));
    if(imported){w.state.startFrame=0;w.state.frameCount=source.frameCount;w.save();w.render();}return;
  }
  if(id==='paintout'||id==='watermark'){
    info=studioSourceMediaInfo(source,input,requireValue(info,'This source has no paintout media input'),native);
    const sameSource=!!info.path&&w.state.source===info.path;
    if(rawNumeric){
      if(typeof w.pickSource!=='function')throw Error('Update Studio to load the AE clip through its normal video loader.');
      if(!await w.pickSource('footage',info,{isActive})){
        if(!isActive())return;
        throw Error(w.$?.('message')?.textContent||w.lastMessage||'The AE clip could not be loaded. Your existing source is retained.');
      }
      if(!isActive())return;
    }else{if(native){info={...info,fps:source.fps,frames:source.frameCount};Object.assign(w.state,{sourceColour:info.resolved_colour||source.resolved_colour,sequenceFps:source.fps,sourceColourConfirmed:true,colourPipeline:'hdr_hdr',processingSpace:'HDR (ACEScct)',outputMode:'EXR + HLG video',studioAsset:asset});for(const [id,key]of [['colour','sourceColour'],['fps','sequenceFps'],['processing','processingSpace'],['output','outputMode']]){const control=w.$?.(id);if(control)control.value=w.state[key];}}else resetSDRSourceColour(w,info);if(sameSource){w.sourceInfo=info;w.save();w.render();}else w.applySourceInfo(info);}
    if(imported&&!sameSource){w.state.startFrame=0;w.state.frameCount=source.frameCount;const count=w.$?.('count');if(count)count.value=String(source.frameCount);w.save();w.render();}return;
  }
  if(id==='camera'){
    requireValue(asset,'This source has no camera video input');
    if(typeof w.acceptSourceAsset==='function')w.acceptSourceAsset(asset);
    else{w.state={...w.state,source:asset,config:{start:0,duration}};for(const key of ['result','geometry','camera','warp','selection','opening','sourceOpening','guidePreview'])delete w.state[key];w.save();w.showMedia('source');w.render();}
    return;
  }
  requireValue(frames[0],'This source has no still-frame input for this mode');
  if(id==='frames'){
    if(native){
      const endpoint=async frame=>{const response=await c.api.fetchApi('/view?'+new URLSearchParams({filename:frame.filename,subfolder:frame.subfolder||'',type:'input'}));if(!response.ok)throw Error('Could not read the native EXR endpoint.');const asset=await w.nativeHDR.upload(new File([await response.blob()],frame.filename,{type:'image/x-exr'}));return {...asset,aeNativeSourceKey:fileIdentity(frame)};};
      const first=await endpoint(frames[0]);if(!isActive())return;const last=fileIdentity(frames.at(-1))===fileIdentity(frames[0])?first:await endpoint(frames.at(-1));if(!isActive())return;w.assets.first=first;w.assets.last=last;
    }else{w.assets.first=frames[0];w.assets.last=frames.at(-1);}
    w.selectAvailability();w.save();w.preview('first');w.render();return;
  }
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
  async acceptInput(c,source,{sessionId,bindRawStill=false,isActive=()=>true}={}){assertStudioSourceMode(source,id,c);if(!isActive())return;await navigateStudioMode(c,id);if(!isActive())return;const w=workspace(c,id);if(busy(w))throw Error('Finish the current operation before loading the AE source');const rawNumeric=isRawNumericProcessingInput(source),ownedStill=rawNumeric&&bindRawStill&&id==='image'&&source.frameCount===1&&source.sourceTransfer?.kind==='native_still'&&['png8','png16'].includes(source.sourceTransfer.profile);if((rawNumeric&&!ownedStill)||isNativeVideoSource(source))clearAEFrameWorkspace(c,w);await accept(c,id,w,source,isActive);if(sessionId&&isActive()&&!isNativeVideoSource(source)&&(!rawNumeric||ownedStill))bindAEFrameWorkspace(c,id,w,sourceAEFrameContract(source,sessionId));},
  getSelectedOutput:c=>{
    const w=workspace(c,id),raw=selectedOutput(c,id,w),delivery=c.outputSettings?.delivery;if(delivery?.readingOutput)return raw;
    // Paintout has explicit delivery roles. A display proxy is never a lower
    // precision substitute when the requested SDR/HDR master is unavailable.
    if(id==='paintout'&&raw&&delivery?.output==='sdr')return transferFileRefs(paintoutOutputDescriptor(w.result,{output:'sdr'}));
    if(id==='paintout'&&raw?.hdrMaster&&delivery?.output==='hdr')return transferFileRefs(paintoutOutputDescriptor(w.result,{output:'hdr',hdrFormat:delivery.hdrFormat}));
    const result=delivery?delivery.outputFor(id,raw):raw;
    if(id==='paintout'&&result&&paintoutPreviewFile(result.master,raw?.preview))return null;
    return transferFileRefs(result);
  },
})));
export const studioModeAdapter=id=>STUDIO_MODE_ADAPTERS.find(adapter=>adapter.id===id);

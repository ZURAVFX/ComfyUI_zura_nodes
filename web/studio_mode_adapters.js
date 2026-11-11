import {sourceAEFrameContract,bindAEFrameWorkspace} from './studio_ae_frame_contract.js';
// Native Studio modes. Data crosses typed workspace methods, never a DOM preview.
const definitions=[['swap','Character replacement','Video'],['ripple','Ripple editing','Video'],['viewport','Viewport to final','Video'],['camera','Change camera angle','Video'],['relight','Relight','Video'],['paintout','Paintout / clean plate','Video'],['watermark','Watermark removal','Video'],['alpha','Extract alpha','Video'],['outpaint','Frame extension','Video'],['hdr','Convert to HDR','Video'],['director','Director','Authored'],['frames','First & last frame','Endpoint'],['references','Reference to video','Reference'],['image','Image','Image']];
const mainModes=new Set(['swap','viewport']);
export async function navigateStudioMode(creative,id){
  if(id==='plate')return creative.plate.select();
  if(id==='paintout'&&creative.plate)return creative.plate.select('remove');
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
function output(value,kind='video'){
  if(!value)return null;const master=value.master||value.file||value;
  if(!validFile(master))return null;
  const descriptorKind=/\.(zip|exr)$/i.test(master.filename)?'hdr_sequence':master.filename==='manifest.json'?'float_manifest':kind;
  return {kind:descriptorKind,master,...(value.file&&master!==value.file?{preview:value.file}:{}),...(value.colour?{colour:value.colour}:{}),...(value.alpha?{alpha:value.alpha}:{})};
}
function hdrOutput(value){
  const raw=value?.hdrFiles||value?.hdr_files||value?.files||[],files=Array.isArray(raw)?raw:Object.values(raw);
  const master=files.find(f=>/\.(zip|exr)$/i.test(f.filename||''))||files.find(f=>/\.(mov|mp4)$/i.test(f.filename||''));
  return master?output({master,colour:value.colour},/\.(zip|exr)$/i.test(master.filename)?'hdr_sequence':'video'):null;
}
function selectedOutput(c,id,w){
  if(!w)return null;
  if(id==='image')return output(w.items?.[w.selectedImage],'image');
  if(id==='alpha')return w.result?.alpha?output({master:w.result.alpha},'video'):null;
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
async function accept(c,id,w,source){
  const asset=source.studioAsset,stills=source.stills||{},frames=Array.isArray(stills)?stills:[stills.first,stills.last].filter(Boolean);
  if((source.precision?.sourceBitDepth>8||asset?.native_hdr_video||asset?.native_hdr)&&id!=='hdr')throw Error('This mode needs a compatible native input. The floating-point source is retained');
  let info=source.mediaInfo;
  if(!info&&asset?.id&&['ripple','relight','alpha','paintout','watermark'].includes(id)&&w!==c.studio){
    const route=['paintout','watermark'].includes(id)?'paintout':'ripple';info=await c.fetch('/zura/studio/assets/'+encodeURIComponent(asset.id)+'/'+route,{});
  }
  if(w===c.studio){requireValue(asset,'This source has no native video input for this mode');if(asset.native_hdr_video)throw Error('Choose Convert to HDR for this floating-point source');w.source=asset;w.project=null;w.lastVideo=null;w.hdrSourceLook=false;w.config.start=0;w.config.duration=Math.min(2,asset.duration||2);w.syncForm();w.render();return;}
  if(id==='hdr'){
    requireValue(asset,'This source is not available as a native HDR input');
    if(source.precision?.sourceBitDepth>8||asset.count)w.setSequenceAsset(asset,{fps:source.fps,colour:source.colour});else w.setOwnAsset(asset);
    return;
  }
  if(id==='outpaint'){w.setSourceAsset(requireValue(asset,'This source has no frame-extension video input'));return;}
  if(id==='ripple'||id==='relight'||id==='alpha'){w.setSource(requireValue(info,'This source has no native media input for this mode'));return;}
  if(id==='paintout'||id==='watermark'){w.applySourceInfo(requireValue(info,'This source has no paintout media input'));return;}
  if(id==='camera'){w.state={...w.state,source:requireValue(asset,'This source has no camera video input'),config:{start:0,duration:Math.min(2,asset.duration||2)}};for(const key of ['result','geometry','camera','warp','selection','opening','sourceOpening','guidePreview'])delete w.state[key];w.save();w.showMedia('source');w.render();return;}
  requireValue(frames[0],'This source has no still-frame input for this mode');
  if(id==='frames'){w.assets.first=frames[0];w.assets.last=frames.at(-1);w.selectAvailability();w.save();w.preview('first');w.render();return;}
  if(id==='references'){w.assets.images.push(...frames);w.save();w.preview();w.render();return;}
  if(id==='image'){await w.setImageOperation('edit',{useCanvas:false});w.clearImageResult();w.editMainMissing=false;w.references=[frames[0],...w.references].slice(0,9);w.save();w.render();return;}
  if(id==='director'){w.draft.clips.push({id:globalThis.crypto.randomUUID(),kind:'image',startFrame:0,endFrame:1,asset:frames[0],text:'',strength:1});w.resultView=false;w.save();w.render();return;}
  throw Error('This native mode does not accept the selected source');
}
export const STUDIO_MODE_ADAPTERS=Object.freeze(definitions.map(([id,label,compatibility])=>Object.freeze({id,label,compatibility,
  resolveWorkspace:c=>workspace(c,id),isBusy:c=>busy(workspace(c,id))||workspace(c,id)===c.studio&&!!c.videoComposer?.ltxOutput?.delivery?.busy,
  async acceptInput(c,source,{sessionId}={}){await navigateStudioMode(c,id);const w=workspace(c,id);if(busy(w))throw Error('Finish the current operation before loading the AE source');await accept(c,id,w,source);if(sessionId)bindAEFrameWorkspace(c,id,w,sourceAEFrameContract(source,sessionId));},
  getSelectedOutput:c=>selectedOutput(c,id,workspace(c,id)),
})));
export const studioModeAdapter=id=>STUDIO_MODE_ADAPTERS.find(adapter=>adapter.id===id);

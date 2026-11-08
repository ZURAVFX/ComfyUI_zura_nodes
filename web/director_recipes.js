import {applyAvailableAttention} from './studio_attention.js';
import {VIDEO_CANVAS_LIMITS} from './studio_resolution.js';
import {frameOutputSize} from './frame_source_resolution.js';
import {
  FRAME_VIDEO_MODELS,
  FRAME_LENGTHS,
  frameVideoDimensions,
} from './frame_video_recipes.js';
import {
  LTX_FRAME_VIDEO_MODELS,
  LTX_FRAME_VIDEO_CAPABILITIES,
  LTX_DISTILLED_SIGMAS,
} from './ltx_frame_video_recipes.js';

export const DIRECTOR_ENGINES=Object.freeze([
  Object.freeze({
    id:'ltx',label:'LTX 2.5 Director',fps:24,dimensionStep:32,
    minFrames:9,maxFrames:361,frameStep:8,frameOffset:1,defaultFrames:49,
    defaultSteps:8,minSteps:8,maxSteps:8,node:'LTXDirector',
    guideNode:'LTXDirectorGuide',model:LTX_FRAME_VIDEO_MODELS.model,
  }),
  Object.freeze({
    id:'h3',label:'MiniMax H3 Director',fps:24,dimensionStep:32,
    minFrames:FRAME_LENGTHS[0],maxFrames:FRAME_LENGTHS.at(-1),
    frameStep:17,frameOffset:5,defaultFrames:73,defaultSteps:8,
    minSteps:8,maxSteps:8,node:'MiniMaxH3DirectorCS',guideNode:null,
    model:FRAME_VIDEO_MODELS.model,
  }),
]);

const ref=(id,index=0)=>[id,index];
const assetId=value=>String(value??'').trim().replace(/[^a-zA-Z0-9_-]+/g,'_');
const engineFor=id=>{
  const engine=DIRECTOR_ENGINES.find(item=>item.id===id);
  if(!engine)throw new Error(`Unknown Director engine: ${id||'missing'}.`);
  return engine;
};
const expectedOwner=engine=>engine.id==='h3'
  ?'custom_nodes.minimaxh3-director'
  :'custom_nodes.WhatDreamsCost-ComfyUI';

function wrongDirectorOwner(info,engine){
  const director=info?.[engine.node];
  if(!director||!director.python_module)return null;
  return director.python_module===expectedOwner(engine)?null:director.python_module;
}

// endFrame is exclusive throughout Studio and native timelines. A clip from
// 24 to 25 occupies frame 24 only and has length 1.
export function directorFrameCount(engineId,requested){
  const engine=engineFor(engineId);
  const value=Number(requested);
  if(!Number.isInteger(value)||value<1)throw new Error('The requested clip length must be a positive whole number of frames.');
  if(value>engine.maxFrames)throw new Error(`${engine.label} supports up to ${engine.maxFrames} frames.`);
  if(value<=engine.minFrames)return engine.minFrames;
  return engine.minFrames+Math.ceil((value-engine.minFrames)/engine.frameStep)*engine.frameStep;
}

function directorCanvas(c,engine){
  if(engine.id==='h3')return frameVideoDimensions(c);
  const width=Number(c.width),height=Number(c.height);
  if(![width,height].every(n=>Number.isInteger(n)&&n>=VIDEO_CANVAS_LIMITS.minDimension&&n<=VIDEO_CANVAS_LIMITS.maxDimension&&n%32===0)){
    throw new Error('Use dimensions in 32-pixel increments, from 256 to 4096 pixels.');
  }
  if(width*height>LTX_FRAME_VIDEO_CAPABILITIES.maxPixels)throw new Error('Choose a canvas up to 8.39 MP.');
  return {width,height};
}

function assetPath(asset,label){
  if(!asset||typeof asset!=='object')throw new Error(`Add an asset for ${label}.`);
  const direct=String(asset.file??'').trim().replaceAll('\\','/');
  const subfolder=String(asset.subfolder??'').trim().replaceAll('\\','/');
  const filename=String(asset.filename??asset.name??'').trim().replaceAll('\\','/');
  const path=direct||(subfolder?`${subfolder.replace(/^\/+|\/+$/g,'')}/${filename.replace(/^\/+/,'')}`:filename.replace(/^\/+/,''));
  if(!path)throw new Error(`Add an asset for ${label}.`);
  if(path.startsWith('/')||/^[a-z]:\//i.test(path)||path.split('/').includes('..')){
    throw new Error(`${label} must be a ComfyUI input-relative file.`);
  }
  return path;
}

function normaliseClips(config,engine,frames,startFrame){
  const endFrame=startFrame+frames;
  if(!Number.isInteger(startFrame)||startFrame<0)throw new Error('Director startFrame must be zero or a positive whole number.');
  if(!Array.isArray(config.clips))throw new Error('Director needs a clips timeline.');
  const range=(clip,index)=>{
    const start=Number(clip.startFrame),end=clip.endFrame==null?start+1:Number(clip.endFrame);
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<startFrame||end<=start||end>endFrame){
      throw new Error(`Clip ${clip.id||index+1} must have an inclusive start and an exclusive end inside the Director render window.`);
    }
    return {...clip,index,startFrame:start,endFrame:end,length:end-start};
  };
  const clips=config.clips.map(range);
  const image=clips.filter(clip=>clip.kind==='image').sort((a,b)=>a.startFrame-b.startFrame||a.endFrame-b.endFrame);
  const prompt=clips.filter(clip=>clip.kind==='prompt');
  const audio=clips.filter(clip=>clip.kind==='audio');
  for(const clip of clips)if(!['image','prompt','audio'].includes(clip.kind))throw new Error(`Clip ${clip.id||clip.index+1} has an unsupported kind.`);
  for(let i=1;i<image.length;i++){
    if(image[i].startFrame<image[i-1].endFrame)throw new Error('Image clips cannot overlap on the Director timeline.');
  }
  for(const clip of image)assetPath(clip.asset,`image clip ${clip.id||clip.index+1}`);
  for(const clip of audio)assetPath(clip.asset,`audio clip ${clip.id||clip.index+1}`);
  return {image,prompt,audio,endFrame};
}

function timelineSegments(config,engine,frames,startFrame){
  const {image,prompt,audio,endFrame}=normaliseClips(config,engine,frames,startFrame);
  const boundaries=new Set([startFrame,endFrame]);
  for(const clip of [...image,...prompt]){
    boundaries.add(clip.startFrame);
    boundaries.add(clip.endFrame);
  }
  const ordered=[...boundaries].sort((a,b)=>a-b),segments=[],prompts=[],lengths=[],strengths=[];
  for(let i=0;i<ordered.length-1;i++){
    const start=ordered[i],end=ordered[i+1];
    if(end<=start)continue;
    const imageClip=image.find(clip=>clip.startFrame<=start&&clip.endFrame>=end);
    const promptClip=prompt.filter(clip=>clip.startFrame<=start&&clip.endFrame>=end).sort((a,b)=>b.startFrame-a.startFrame)[0];
    const text=String(promptClip?.text??imageClip?.text??'').trim();
    const id=assetId(`director-${engine.id}-${start}-${end}`);
    if(imageClip){
      const path=assetPath(imageClip.asset,`image clip ${imageClip.id||imageClip.index+1}`);
      segments.push({
        id,start,length:end-start,prompt:text,type:'image',imageFile:path,
        guideStrength:Number(imageClip.strength??1),isEndFrame:imageClip.isEndFrame===true,
      });
      strengths.push(Number(imageClip.strength??1).toFixed(2));
    }else{
      segments.push({id,start,length:end-start,prompt:text,type:'text',isEndFrame:false});
    }
    prompts.push(text.replaceAll('|',' / '));
    lengths.push(end-start);
  }
  const audioSegments=audio.map((clip,index)=>{
    const path=assetPath(clip.asset,`audio clip ${clip.id||clip.index+1}`);
    return {
      id:assetId(clip.id||`director-audio-${index+1}`),type:'audio',start:clip.startFrame,
      length:clip.length,trimStart:Number(clip.trimStart??0),
      audioDurationFrames:Number(clip.audioDurationFrames??clip.length),
      audioFile:path,fileName:String(clip.asset.filename??clip.asset.name??path).split('/').at(-1),
    };
  });
  const timeline={
    mainTrackEnabled:true,audioTrackEnabled:audioSegments.length>0,motionTrackEnabled:false,
    propHeight:90,globalPropHeight:70,showFilenames:true,overrideAudio:false,inpaint_audio:false,
    global_prompt:String(config.globalPrompt??config.prompt??''),retake_global_prompt:'',
    retakeMode:false,retakeStart:24,retakeLength:48,retakePrompt:'',retakeStrength:1,retakeVideo:null,
    normalStartFrame:startFrame,normalDurationFrames:frames,segments,audioSegments,motionSegments:[],
  };
  return {
    timeline,localPrompts:prompts.join(' | '),segmentLengths:lengths.join(','),
    guideStrength:strengths.join(','),endFrame,
  };
}

function encodeDirector(c,info,engine){
  if(!c||typeof c!=='object')throw new Error('Director configuration is missing.');
  if(!String(c.prompt??'').trim())throw new Error('Describe the sequence you want to direct.');
  const frames=directorFrameCount(engine.id,c.frames),startFrame=Number(c.startFrame??0);
  const canvas=directorCanvas(c,engine),output=frameOutputSize(c);
  const steps=Number(c.steps??engine.defaultSteps),seed=Number(c.seed??42),fps=Number(c.fps??engine.fps);
  if(!Number.isInteger(steps)||steps<engine.minSteps||steps>engine.maxSteps)throw new Error(`Sampling steps must be between ${engine.minSteps} and ${engine.maxSteps}.`);
  if(!Number.isSafeInteger(seed)||seed<0)throw new Error('Seed must be a positive whole number or zero.');
  if(fps!==engine.fps)throw new Error(`${engine.label} renders at ${engine.fps} fps.`);
  return {frames,startFrame,canvas,output,steps,seed,fps,...timelineSegments(c,engine,frames,startFrame)};
}

function addCommonSampling(g,node,modelRef,positiveRef,latentRef,steps,seed){
  node('guider','BasicGuider',{model:modelRef,conditioning:positiveRef},'Director conditioning');
  node('scheduler','BasicScheduler',{model:modelRef,scheduler:'simple',steps,denoise:1},'Director schedule');
  node('sampler','KSamplerSelect',{sampler_name:'res_multistep'});
  node('noise','RandomNoise',{noise_seed:seed});
  node('sample','SamplerCustomAdvanced',{
    noise:ref('noise'),guider:ref('guider'),sampler:ref('sampler'),sigmas:ref('scheduler'),latent_image:latentRef,
  },'Generate Director sequence');
}

function addOutputGraph(g,node,output,decodeRef,decodeSize,fps,engine,audioRef){
  let images=decodeRef;
  if(output&&(output.width!==decodeSize.width||output.height!==decodeSize.height)){
    node('restore_output','ImageScale',{image:images,upscale_method:'lanczos',width:output.width,height:output.height,crop:'disabled'},'Restore requested output size');
    images=ref('restore_output');
  }
  node('video','CreateVideo',{images,audio:audioRef,fps,bit_depth:8,color_space:'sRGB',codec:'none'},'Assemble Director video');
  node('save','SaveVideo',{video:ref('video'),filename_prefix:`zura/director/${engine.id}/result`,format:'mp4','format.codec':'h264','format.codec.encoding':'auto'},`Save ${engine.label}`);
}

function buildH3(c,info,engine){
  const d=encodeDirector(c,info,engine);
  const g={},node=(id,class_type,inputs,title)=>{g[id]={class_type,inputs,_meta:{title:title||class_type}};};
  node('model','UNETLoader',{unet_name:FRAME_VIDEO_MODELS.model,weight_dtype:'default'},'Load MiniMax H3 FL2VA');
  node('turbo','LoraLoaderModelOnly',{model:ref('model'),lora_name:FRAME_VIDEO_MODELS.lora,strength_model:1},'Apply H3 Turbo 8-step');
  node('attention','ModelAttentionBackend',{model:ref('turbo'),attention:'comfy kitchen attention'},'Comfy Kitchen attention');
  node('text','CLIPLoader',{clip_name:FRAME_VIDEO_MODELS.text,type:'minimax',device:'default'},'Load H3 text encoder');
  node('video_vae','VAELoader',{vae_name:FRAME_VIDEO_MODELS.videoVae},'Load H3 video VAE');
  node('audio_vae','VAELoader',{vae_name:FRAME_VIDEO_MODELS.audioVae},'Load H3 audio VAE');
  node('director',engine.node,{
    clip:ref('text'),vae:ref('video_vae'),model:ref('attention'),
    start_second:d.startFrame/d.fps,end_second:d.endFrame/d.fps,duration_seconds:d.frames/d.fps,
    start_frame:d.startFrame,end_frame:d.endFrame,duration_frames:d.frames,
    timeline_data:JSON.stringify(d.timeline),local_prompts:d.localPrompts,
    segment_lengths:d.segmentLengths,guide_strength:d.guideStrength,
    audio_vae:ref('audio_vae'),global_prompt:c.globalPrompt??c.prompt,
    use_custom_audio:false,use_custom_motion:false,
    inpaint_audio:false,frame_rate:d.fps,display_mode:'frames',
    custom_width:d.canvas.width,custom_height:d.canvas.height,resize_method:'stretch to fit',
    divisible_by:32,img_compression:0,override_audio:false,ref_image_size:'match',
    shift_video:12,shift_audio:3,
  },'H3 Director timeline');
  const hasAudio=d.timeline.audioSegments.length>0;
  if(hasAudio){
    node('trim_audio','TrimAudioDuration',{audio:ref('director',3),start_index:0,duration:d.frames/d.fps},'Match timeline soundtrack to video');
    node('audio_guide','MiniMaxH3AddGuide',{positive:ref('director',1),latent:ref('director',2),audio_vae:ref('audio_vae'),audio:ref('trim_audio'),frame_idx:0},'Follow soundtrack using first/last-frame audio guidance');
  }
  addCommonSampling(g,node,ref('director'),hasAudio?ref('audio_guide'):ref('director',1),ref('director',2),d.steps,d.seed);
  node('decode','VAEDecode',{samples:ref('sample'),vae:ref('video_vae')},'Decode Director video');
  if(!hasAudio)node('decode_audio','VAEDecodeAudio',{samples:ref('sample'),vae:ref('audio_vae')},'Decode Director audio');
  addOutputGraph(g,node,d.output,ref('decode'),d.canvas,d.fps,engine,ref(hasAudio?'trim_audio':'decode_audio'));
  return g;
}

function buildLtx(c,info,engine){
  const d=encodeDirector(c,info,engine);
  const g={},node=(id,class_type,inputs,title)=>{g[id]={class_type,inputs,_meta:{title:title||class_type}};};
  node('model','UNETLoader',{unet_name:LTX_FRAME_VIDEO_MODELS.model,weight_dtype:'default'},'Load LTX 2.5 Director model');
  node('attention','ModelAttentionBackend',{model:ref('model'),attention:'comfy kitchen attention'},'Comfy Kitchen attention');
  node('text','CLIPLoader',{clip_name:LTX_FRAME_VIDEO_MODELS.text,type:'ltxv',device:'default'},'Load LTX text encoder');
  node('video_vae','VAELoader',{vae_name:LTX_FRAME_VIDEO_MODELS.videoVae},'Load LTX video VAE');
  node('audio_vae','VAELoader',{vae_name:LTX_FRAME_VIDEO_MODELS.audioVae},'Load LTX audio VAE');
  node('negative','CLIPTextEncode',{clip:ref('text'),text:''},'Encode negative prompt');
  node('director',engine.node,{
    model:ref('attention'),clip:ref('text'),audio_vae:ref('audio_vae'),
    start_second:d.startFrame/d.fps,end_second:d.endFrame/d.fps,duration_seconds:d.frames/d.fps,
    start_frame:d.startFrame,end_frame:d.endFrame,duration_frames:d.frames,
    timeline_data:JSON.stringify(d.timeline),local_prompts:d.localPrompts,
    segment_lengths:d.segmentLengths,epsilon:.001,guide_strength:d.guideStrength,
    global_prompt:c.globalPrompt??c.prompt,
    use_custom_audio:false,use_custom_motion:false,
    inpaint_audio:false,frame_rate:d.fps,display_mode:'frames',
    custom_width:d.canvas.width,custom_height:d.canvas.height,resize_method:'stretch to fit',
    divisible_by:32,img_compression:0,override_audio:false,
  },'LTX Director timeline');
  node('guide',engine.guideNode,{
    positive:ref('director',1),negative:ref('negative'),vae:ref('video_vae'),latent:ref('director',2),
    guide_data:ref('director',4),motion_guide_data:ref('director',5),model:ref('director',0),
    ic_lora_name:'None',ic_lora_strength:1,scale_by:1,upscale_method:'bicubic',
    image_attention_strength:1,crop:'center',auto_snap_ic_grid:true,
    use_tiled_encode:false,tile_size:256,tile_overlap:64,retake_mode:false,
  },'Prepare LTX guide keyframes');
  const hasAudio=d.timeline.audioSegments.length>0;
  if(hasAudio){
    node('trim_audio','TrimAudioDuration',{audio:ref('director',7),start_index:0,duration:d.frames/d.fps},'Match timeline soundtrack to video');
    node('encode_audio','LTXVAudioVAEEncode',{audio:ref('trim_audio'),audio_vae:ref('audio_vae')},'Encode original timeline soundtrack');
    node('freeze_audio_mask','SolidMask',{value:0,width:1024,height:1024});
    node('freeze_audio','SetLatentNoiseMask',{samples:ref('encode_audio'),mask:ref('freeze_audio_mask')},'Preserve soundtrack using first/last-frame audio method');
  }
  node('av_latent','LTXVConcatAVLatent',{
    video_latent:ref('guide',2),audio_latent:hasAudio?ref('freeze_audio'):ref('director',3),
  },'Combine Director video and audio latents');
  node('guider','CFGGuider',{
    model:ref('guide',3),positive:ref('guide',0),negative:ref('guide',1),cfg:1,
  },'Director conditioning');
  node('sigmas','ManualSigmas',{sigmas:LTX_DISTILLED_SIGMAS},'Official distilled 8-step schedule');
  node('sampler','KSamplerSelect',{sampler_name:'euler_ancestral'});
  node('noise','RandomNoise',{noise_seed:d.seed});
  node('sample','SamplerCustomAdvanced',{
    noise:ref('noise'),guider:ref('guider'),sampler:ref('sampler'),
    sigmas:ref('sigmas'),latent_image:ref('av_latent'),
  },'Generate LTX Director sequence');
  node('separate','LTXVSeparateAVLatent',{av_latent:ref('sample')});
  node('crop_guides','LTXVCropGuides',{
    positive:ref('guide',0),negative:ref('guide',1),latent:ref('separate'),
  },'Remove guide frames');
  node('decode','VAEDecodeTiled',{
    samples:ref('crop_guides',2),vae:ref('video_vae'),tile_size:512,overlap:64,
    temporal_size:128,temporal_overlap:32,
  },'Decode Director video');
  if(!hasAudio)node('decode_audio','LTXVAudioVAEDecode',{
    samples:ref('separate',1),audio_vae:ref('audio_vae'),
  },'Decode Director audio');
  addOutputGraph(g,node,d.output,ref('decode'),d.canvas,d.fps,engine,ref(hasAudio?'trim_audio':'decode_audio'));
  return g;
}

function walkReferences(graph,visitor){
  for(const [id,value] of Object.entries(graph)){
    for(const [key,input] of Object.entries(value.inputs||{})){
      if(Array.isArray(input)&&input.length===2&&typeof input[0]==='string'&&Number.isInteger(input[1]))visitor(id,key,input);
    }
  }
}

export function validateDirectorGraph(graph){
  if(!graph||typeof graph!=='object')throw new Error('Director graph is missing.');
  for(const [id,value] of Object.entries(graph)){
    if(!value?.class_type||!value.inputs||typeof value.inputs!=='object')throw new Error(`Director graph node ${id} is malformed.`);
  }
  walkReferences(graph,(id,key,input)=>{
    if(!graph[input[0]])throw new Error(`Director graph node ${id}.${key} refers to missing node ${input[0]}.`);
    if(input[1]<0)throw new Error(`Director graph node ${id}.${key} has an invalid output slot.`);
  });
  return graph;
}

export function buildDirectorGraph(c,info){
  const engine=engineFor(c?.engine);
  const owner=wrongDirectorOwner(info,engine);
  if(owner)throw new Error(`${engine.node} is loaded from ${owner}; expected ${expectedOwner(engine)}.`);
  const graph=engine.id==='h3'?buildH3(c,info,engine):buildLtx(c,info,engine);
  applyAvailableAttention(graph,info);
  return validateDirectorGraph(graph);
}

function nodeOptions(info,node,key){
  const field=info?.[node]?.input?.required?.[key]??info?.[node]?.input?.optional?.[key];
  if(field?.[0]==='COMBO'&&Array.isArray(field[1]?.options))return field[1].options;
  return Array.isArray(field?.[0])?field[0]:[];
}

const COMMON_NODES=['RandomNoise','SamplerCustomAdvanced','CreateVideo','SaveVideo'];
const H3_NODES=['UNETLoader','LoraLoaderModelOnly','CLIPLoader','VAELoader','MiniMaxH3DirectorCS',
  'BasicGuider','BasicScheduler','KSamplerSelect','VAEDecode','VAEDecodeAudio',...COMMON_NODES];
const LTX_NODES=['UNETLoader','CLIPLoader','VAELoader','CLIPTextEncode','LTXDirector','LTXDirectorGuide',
  'LTXVConcatAVLatent','CFGGuider','ManualSigmas','KSamplerSelect','LTXVSeparateAVLatent',
  'LTXVCropGuides','VAEDecodeTiled','LTXVAudioVAEDecode',...COMMON_NODES];

export function directorAvailability(info={},c={}){
  const engine=engineFor(c.engine??'ltx'),required=engine.id==='h3'?H3_NODES:LTX_NODES;
  const audioNodes=c.clips?.some(clip=>clip.kind==='audio')?['TrimAudioDuration',...(engine.id==='h3'?['MiniMaxH3AddGuide']:['LTXVAudioVAEEncode','SolidMask','SetLatentNoiseMask'])]:[];
  const missingNodes=[...required,...audioNodes].filter(node=>!info?.[node]),missingFiles=[];
  const owner=wrongDirectorOwner(info,engine);
  if(engine.id==='h3'){
    for(const [node,key,file] of [
      ['UNETLoader','unet_name',FRAME_VIDEO_MODELS.model],
      ['CLIPLoader','clip_name',FRAME_VIDEO_MODELS.text],
      ['LoraLoaderModelOnly','lora_name',FRAME_VIDEO_MODELS.lora],
    ])if(!nodeOptions(info,node,key).includes(file))missingFiles.push(file);
    for(const file of [FRAME_VIDEO_MODELS.videoVae,FRAME_VIDEO_MODELS.audioVae]){
      if(!nodeOptions(info,'VAELoader','vae_name').includes(file))missingFiles.push(file);
    }
  }else{
    for(const [node,key,file] of [
      ['UNETLoader','unet_name',LTX_FRAME_VIDEO_MODELS.model],
      ['CLIPLoader','clip_name',LTX_FRAME_VIDEO_MODELS.text],
    ])if(!nodeOptions(info,node,key).includes(file))missingFiles.push(file);
    for(const file of [LTX_FRAME_VIDEO_MODELS.videoVae,LTX_FRAME_VIDEO_MODELS.audioVae]){
      if(!nodeOptions(info,'VAELoader','vae_name').includes(file))missingFiles.push(file);
    }
  }
  return {
    ready:!missingNodes.length&&!missingFiles.length&&!owner,
    missing:[...new Set([...missingNodes,...missingFiles,...(owner?[`${engine.node} (loaded from ${owner})`]:[])])],
    missingNodes:[...new Set(missingNodes)],
    missingFiles:[...new Set(missingFiles)],
    wrongOwners:owner?[{node:engine.node,loaded:owner,expected:expectedOwner(engine)}]:[],
  };
}

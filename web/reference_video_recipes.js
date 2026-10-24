// Native MiniMax H3 Ref2Video recipe. References are ingredients for identity,
// appearance, scene, motion cues and audio; they are not frame anchors.
export const REFERENCE_VIDEO_MODELS=Object.freeze({
  ref2va:'minimax_h3_ref2va_pruned_int8_convrot.safetensors',
  viggle:'minimax_h3_ref2va_viggle_pruned_int8_convrot.safetensors',
  turbo:'minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors',
  text:'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',
  videoVae:'minimax_h3_video_vae_int8_convrot.safetensors',
  audioVae:'minimax_h3_audio_vae_fp32.safetensors',
});

export const REFERENCE_VIDEO_CAPABILITIES=Object.freeze({
  id:'h3',
  label:'MiniMax H3',
  fps:24,
  dimensionStep:32,
  frameStep:17,
  frameOffset:5,
  minFrames:5,
  maxFrames:362,
  trainedMinFrames:124,
  trainedMaxFrames:362,
  defaultFrames:124,
  defaultSteps:8,
  minSteps:4,
  maxSteps:80,
  maxPixels:1344*768,
  maxImages:9,
  maxVideos:3,
  maxAudios:3,
  maxVideoAudios:3,
  minVideoSeconds:2,
  maxVideoSeconds:15,
  defaultVideoSeconds:3,
  defaultAudioSeconds:10,
  maxAudioSeconds:10,
  promptTags:['<Picture i>','<Video k>','<Audio j>'],
  nodeTypes:[
    'LoadImage','LoadVideo','Video Slice','GetVideoComponents','H3ReferenceVideo',
    'LoadAudio','TrimAudioDuration','H3ReferenceAudio','UNETLoader','LoraLoaderModelOnly',
    'CLIPLoader','VAELoader','MiniMaxH3ReferenceToVideo','MiniMaxH3SigmaShift',
    'ModelAttentionBackend','BasicGuider','BasicScheduler','KSamplerSelect',
    'RandomNoise','SamplerCustomAdvanced','VAEDecode','VAEDecodeAudio',
    'CreateVideo','SaveVideo','MiniMaxH3AddGuide','EmptyAudio','AudioConcat',
  ],
});

export const REFERENCE_VIDEO_PROFILES=Object.freeze({
  turbo:Object.freeze({
    id:'turbo',
    label:'Fast Ref2VA',
    model:'ref2va',
    speedup:'turbo',
    steps:8,
    scheduler:'simple',
    sampler:'res_multistep',
    sigmaVideo:12,
    sigmaAudio:6,
  }),
  quality:Object.freeze({
    id:'quality',
    label:'Quality Ref2VA',
    model:'ref2va',
    speedup:'quality',
    steps:40,
    scheduler:'beta',
    sampler:'res_multistep',
    sigmaVideo:12,
    sigmaAudio:6,
  }),
});

const ref=(id,output=0)=>[id,output];
const clampFramesUp=n=>n+((((n-5)%17)+17)%17===0?0:17-((n-5)%17));
const used=value=>value!==undefined&&value!==null;
const title=value=>String(value||'').replace(/[_-]+/g,' ').trim();

function safeFile(value,label){
  if(typeof value!=='string'||!value.trim())throw new Error(`Add a ${label} before generating.`);
  if(value.split(/[\\/]+/).includes('..'))throw new Error(`The ${label} path is not valid.`);
  return value;
}

function list(value,label){
  if(!Array.isArray(value))throw new Error(`${label} must be a list.`);
  return value;
}

function referenceCounts(c={}){
  return {
    images:Array.isArray(c.images)?c.images.length:0,
    videos:Array.isArray(c.videos)?c.videos.length:0,
    audios:Array.isArray(c.audios)?c.audios.length:0,
  };
}

export function referencePromptTags(c={}){
  const images=list(c.images||[],'Image references');
  const videos=list(c.videos||[],'Video references');
  const audios=list(c.audios||[],'Audio references');
  const tags=[];
  images.forEach((image,index)=>tags.push({kind:'image',index,tag:`<Picture ${index+1}>`}));
  let audioIndex=0;
  videos.forEach((video,index)=>{
    if(video?.audioFile){
      audioIndex+=1;
      tags.push({kind:'audio',index:audioIndex-1,tag:`<Audio ${audioIndex}>`,pairedVideoIndex:index});
    }
    tags.push({kind:'video',index,tag:`<Video ${index+1}>`});
  });
  audios.forEach((audio,index)=>{
    audioIndex+=1;
    tags.push({kind:'audio',index:audioIndex-1,tag:`<Audio ${audioIndex}>`,standaloneAudioIndex:index});
  });
  return tags;
}

export function referenceVideoPrompt(c={}){
  const prompt=String(c.prompt||'').trim();
  if(!prompt)throw new Error('Describe the video you want to generate.');
  const sequence=referencePromptTags(c);
  const max={
    Picture:(c.images||[]).length,
    Video:(c.videos||[]).length,
    Audio:sequence.filter(item=>item.kind==='audio').length,
  };
  for(const match of prompt.matchAll(/<(Picture|Video|Audio)\s+(\d+)>/gi)){
    const kind=match[1][0].toUpperCase()+match[1].slice(1).toLowerCase(),ordinal=Number(match[2]);
    if(ordinal<1||ordinal>max[kind]){
      throw new Error(`The prompt uses ${match[0]}, but this run has ${max[kind]} ${kind.toLowerCase()} reference${max[kind]===1?'':'s'}.`);
    }
  }
  // The native H3 tokenizer prepends each reference label and vision block.
  // Prompt tags are pointers written by the user, not extra prompt content.
  return prompt.replace(/<(Picture|Video|Audio)\s+(\d+)>/gi,(_,kind,n)=>`<${kind[0].toUpperCase()+kind.slice(1).toLowerCase()} ${Number(n)}>`);
}

/** Stable file keys keep a chosen vocal selected when earlier references move. */
export function referenceAudioSources(c={}){
  return referencePromptTags(c).filter(item=>item.kind==='audio').map(item=>{
    const paired=item.pairedVideoIndex!==undefined;
    const source=paired?c.videos[item.pairedVideoIndex]:c.audios[item.standaloneAudioIndex];
    return {...item,key:(paired?'video:':'audio:')+source.file,file:paired?source.audioFile:source.file,start:paired?Number(source.start||0):0,name:source.name||source.filename||source.file};
  });
}

export function referenceVideoDimensions(c={}){
  const width=Number(c.width),height=Number(c.height),caps=REFERENCE_VIDEO_CAPABILITIES;
  if(![width,height].every(n=>Number.isInteger(n)&&n>=32&&n%caps.dimensionStep===0)){
    throw new Error('H3 width and height must be whole numbers in multiples of 32.');
  }
  if(width*height>caps.maxPixels){
    throw new Error('Choose a smaller size. H3 supports up to 1.03 megapixels in this mode.');
  }
  return {width,height};
}

export function referenceVideoFrames(c={}){
  const caps=REFERENCE_VIDEO_CAPABILITIES;
  const frames=Number(c.frames??caps.defaultFrames);
  if(!Number.isInteger(frames)||frames<caps.minFrames||frames>caps.maxFrames||(frames-caps.frameOffset)%caps.frameStep!==0){
    throw new Error('Choose 5 to 362 H3 frames on the 17k + 5 frame grid.');
  }
  return frames;
}

export function nextReferenceVideoFrameCount(frames){
  const requested=Number(frames);
  if(!Number.isFinite(requested)||requested<REFERENCE_VIDEO_CAPABILITIES.minFrames)return REFERENCE_VIDEO_CAPABILITIES.minFrames;
  return Math.min(REFERENCE_VIDEO_CAPABILITIES.maxFrames,clampFramesUp(Math.ceil(requested)));
}

function normaliseConfig(c={}){
  const caps=REFERENCE_VIDEO_CAPABILITIES;
  const images=list(c.images||[],'Image references');
  const videos=list(c.videos||[],'Video references');
  const audios=list(c.audios||[],'Audio references');
  const audioDriver=c.audioDriver||'';
  if(audioDriver&&!referenceAudioSources(c).some(source=>source.key===audioDriver))throw new Error('Choose an uploaded audio to follow, or select Reference only.');
  if(images.length>caps.maxImages)throw new Error(`H3 supports up to ${caps.maxImages} reference images.`);
  if(videos.length>caps.maxVideos)throw new Error(`H3 supports up to ${caps.maxVideos} reference videos.`);
  if(audios.length>caps.maxAudios)throw new Error(`H3 supports up to ${caps.maxAudios} standalone reference audios.`);
  if(!images.length&&!videos.length&&!audios.length)throw new Error('Add at least one image, video or audio reference.');
  images.forEach((image,index)=>{
    image.file=safeFile(image.file,`reference image ${index+1}`);
    if(used(image.frame)&&image.frame!==0)throw new Error('H3 Ref2Video does not support frame positions for image references.');
    if((used(image.start)&&Number(image.start)!==0)||(used(image.duration)&&Number(image.duration)!==0)){
      throw new Error('H3 Ref2Video treats images as unanchored appearance references.');
    }
  });
  videos.forEach((video,index)=>{
    video.file=safeFile(video.file,`reference video ${index+1}`);
    video.start=Number(video.start??0);
    video.duration=Number(video.duration??caps.defaultVideoSeconds);
    if(!Number.isFinite(video.start)||video.start<0)throw new Error(`Reference video ${index+1} has an invalid start time.`);
    if(!Number.isFinite(video.duration)||video.duration<caps.minVideoSeconds||video.duration>caps.maxVideoSeconds){
      throw new Error(`Reference video ${index+1} must use ${caps.minVideoSeconds}-${caps.maxVideoSeconds} seconds.`);
    }
    if(video.audioFile)video.audioFile=safeFile(video.audioFile,`soundtrack for reference video ${index+1}`);
  });
  audios.forEach((audio,index)=>{
    audio.file=safeFile(audio.file,`reference audio ${index+1}`);
    if(used(audio.start)&&Number(audio.start)!==0)throw new Error('Standalone H3 reference audio supports a duration limit, not a start offset.');
    audio.duration=Number(audio.duration??caps.defaultAudioSeconds);
    if(!Number.isFinite(audio.duration)||audio.duration<0.5||audio.duration>caps.maxAudioSeconds){
      throw new Error(`Reference audio ${index+1} must be 0.5-${caps.maxAudioSeconds} seconds.`);
    }
  });
  const model=c.model||'ref2va',speedup=c.speedup||'turbo';
  if(!['ref2va','viggle'].includes(model))throw new Error('Choose the standard or Viggle H3 Ref2VA checkpoint.');
  if(!['turbo','quality'].includes(speedup))throw new Error('Choose the Turbo or Quality H3 sampling profile.');
  if(model==='viggle'&&speedup!=='quality')throw new Error('Use the Viggle checkpoint with the Quality profile. No compatible Viggle Turbo adapter is verified.');
  const spectrum=c.spectrum===true;
  if(spectrum&&speedup!=='turbo')throw new Error('The Spectrum speedup is only enabled with the verified Turbo profile.');
  const steps=Number(c.steps??(speedup==='turbo'?8:40));
  if(!Number.isInteger(steps)||steps<caps.minSteps||steps>caps.maxSteps)throw new Error(`Sampling steps must be ${caps.minSteps}-${caps.maxSteps}.`);
  if(speedup==='turbo'&&steps!==8)throw new Error('The verified H3 Turbo Ref2VA adapter uses eight sampling steps.');
  const seed=Number(c.seed??42);
  if(!Number.isSafeInteger(seed)||seed<0)throw new Error('Seed must be a positive whole number or zero.');
  if(c.refImageSize!==undefined&&!['match','max'].includes(c.refImageSize))throw new Error('Choose Match or Max reference image sizing.');
  return {
    ...c,images,videos,audios,audioDriver,
    prompt:referenceVideoPrompt({...c,images,videos,audios}),
    model,speedup,spectrum,steps,seed,
    refImageSize:c.refImageSize||'match',
    ...referenceVideoDimensions(c),
    frames:referenceVideoFrames(c),
  };
}

export function buildReferenceVideoGraph(config={}){
  const c=normaliseConfig(config),caps=REFERENCE_VIDEO_CAPABILITIES;
  const graph={};
  const node=(id,class_type,inputs,nodeTitle)=>{
    graph[id]={class_type,inputs,_meta:{title:title(nodeTitle)}};
    return ref(id);
  };
  let model=node('model','UNETLoader',{unet_name:REFERENCE_VIDEO_MODELS[c.model],weight_dtype:'default'},'Load INT8 H3 Ref2VA');
  let positive;
  if(c.speedup==='turbo'){
    model=node('turbo','LoraLoaderModelOnly',{model,lora_name:REFERENCE_VIDEO_MODELS.turbo,strength_model:1},'Load 8-step Ref2VA Turbo');
  }
  model=node('attention','ModelAttentionBackend',{model,attention:'comfy kitchen attention'},'Comfy Kitchen attention');
  model=node('shift','MiniMaxH3SigmaShift',{model,shift_video:12,shift_audio:6},'Match H3 video and audio schedules');
  if(c.spectrum){
    model=node('spectrum','SpectrumApplyMiniMaxH3',{
      model,enabled:true,blend_weight:0.5,degree:4,ridge_lambda:0.1,
      window_size:2,flex_window:0.75,warmup_steps:5,tail_actual_steps:1,
      max_history:8,debug:false,history_storage:'system_ram',
      bootstrap_first_forecast:true,anchor_residual_feedback:false,
      selective_rollback_correction:false,offline_smoothing_replay:true,
      audio_blend_weight:0,offline_archive_storage:'system_ram',
      model_aware_mode:'off',model_aware_risk_threshold:0.65,
    },'Reuse verified H3 sampling work');
  }
  const clip=node('text','CLIPLoader',{clip_name:REFERENCE_VIDEO_MODELS.text,type:'minimax',device:'default'},'Load H3 reference text and vision encoder');
  const videoVae=node('video_vae','VAELoader',{vae_name:REFERENCE_VIDEO_MODELS.videoVae},'Load INT8 H3 video decoder');
  const audioVae=node('audio_vae','VAELoader',{vae_name:REFERENCE_VIDEO_MODELS.audioVae},'Load H3 audio decoder');
  const references={},audioLoads=new Map();
  c.images.forEach((image,index)=>{
    references[`ref_images.ref_image_${index}`]=node(`image_${index+1}`,'LoadImage',{image:image.file},`Reference picture ${index+1}`);
  });
  c.videos.forEach((video,index)=>{
    const loaded=node(`video_${index+1}`,'LoadVideo',{file:video.file},`Reference video ${index+1}`);
    // Keep long uploads file-backed until the selected reference interval is
    // known. Decoding the entire upload before trimming exhausts host memory.
    const window=node(`video_window_${index+1}`,'Video Slice',{video:loaded,start_time:video.start,duration:video.duration,strict_duration:false},`Read only reference interval ${index+1}`);
    const components=node(`components_${index+1}`,'GetVideoComponents',{video:window},`Read reference video ${index+1}`);
    const inputs={
      frames:components,start_seconds:0,seconds:video.duration,
      source_fps:ref(`components_${index+1}`,2),
    };
    let soundtrack;
    if(video.audioFile){
      const loadedAudio=node(`video_audio_${index+1}`,'LoadAudio',{audio:video.audioFile},`Reference soundtrack ${index+1}`);
      audioLoads.set('video:'+video.file,loadedAudio);
      const audioWindow=node(`video_audio_window_${index+1}`,'TrimAudioDuration',{audio:loadedAudio,start_index:video.start,duration:video.duration},`Match soundtrack reference interval ${index+1}`);
      soundtrack=node(`video_audio_guard_${index+1}`,'H3ReferenceAudio',{audio:audioWindow,max_seconds:caps.maxVideoSeconds},`Make reference soundtrack ${index+1} stereo`);
      inputs.audio=soundtrack;
    }
    const trimmed=node(`reference_video_${index+1}`,'H3ReferenceVideo',inputs,`Trim reference video ${index+1}`);
    references[`ref_videos.ref_video_${index}`]=trimmed;
    if(soundtrack)references[`ref_video_audios.ref_video_audio_${index}`]=ref(`reference_video_${index+1}`,1);
  });
  c.audios.forEach((audio,index)=>{
    const loaded=node(`audio_${index+1}`,'LoadAudio',{audio:audio.file},`Reference audio ${index+1}`);
    audioLoads.set('audio:'+audio.file,loaded);
    const guarded=node(`audio_guard_${index+1}`,'H3ReferenceAudio',{audio:loaded,max_seconds:audio.duration},`Trim reference audio ${index+1}`);
    references[`ref_audios.ref_audio_${index}`]=guarded;
  });
  positive=node('references','MiniMaxH3ReferenceToVideo',{
    clip,vae:videoVae,audio_vae:audioVae,prompt:c.prompt,width:c.width,height:c.height,
    length:c.frames,ref_image_size:c.refImageSize,...references,
  },'Combine image, video and audio references');
  let followedAudio;
  if(c.audioDriver){
    const source=referenceAudioSources(c).find(item=>item.key===c.audioDriver),duration=c.frames/caps.fps;
    const selected=node('vocal_window','TrimAudioDuration',{audio:audioLoads.get(source.key),start_index:source.start,duration},'Read the selected vocal on the output timeline');
    const stereo=node('vocal_stereo','H3ReferenceAudio',{audio:selected,max_seconds:Math.max(0.5,duration)},'Prepare the selected vocal');
    const silence=node('vocal_silence','EmptyAudio',{duration,sample_rate:48000,channels:2},'Keep silence after a short vocal');
    const padded=node('vocal_tail','AudioConcat',{audio1:stereo,audio2:silence,direction:'after'},'Append silence without repeating the vocal');
    followedAudio=node('followed_audio','TrimAudioDuration',{audio:padded,start_index:0,duration},'Match the vocal to the video duration');
    positive=node('vocal_guide','MiniMaxH3AddGuide',{positive,latent:ref('references',1),audio_vae:audioVae,audio:followedAudio,frame_idx:0},'Drive the performance with the selected vocal');
  }
  const guider=node('guider','BasicGuider',{model,conditioning:positive},'Guide the reference scene');
  const scheduler=node('scheduler','BasicScheduler',{model,scheduler:c.speedup==='turbo'?'simple':'beta',steps:c.steps,denoise:1},'Schedule H3 sampling');
  const sampler=node('sampler','KSamplerSelect',{sampler_name:'res_multistep'},'Choose H3 sampler');
  const noise=node('noise','RandomNoise',{noise_seed:c.seed},'Choose variation seed');
  const samples=node('sample','SamplerCustomAdvanced',{noise,guider,sampler,sigmas:scheduler,latent_image:ref('references',1)},'Generate video and audio');
  const decoded=node('decode','VAEDecode',{samples,vae:videoVae},'Decode H3 video');
  const decodedAudio=followedAudio||node('decode_audio','VAEDecodeAudio',{samples,vae:audioVae},'Decode H3 audio');
  const video=node('video','CreateVideo',{images:decoded,audio:decodedAudio,fps:caps.fps,bit_depth:8,color_space:'sRGB',codec:'none'},'Assemble video with audio');
  node('save','SaveVideo',{video,filename_prefix:'zura/reference/h3',format:'mp4','format.codec':'h264','format.codec.encoding':'auto'},'Save reference video');
  return graph;
}

function options(info,node,key){
  const field=info?.[node]?.input?.required?.[key]??info?.[node]?.input?.optional?.[key];
  if(field?.[0]==='COMBO')return field[1]?.options||[];
  if(Array.isArray(field?.[0]))return field[0];
  return [];
}

export function referenceVideoAvailability(info={},config={}){
  const counts=referenceCounts(config);
  const model=config.model||'ref2va',speedup=config.speedup||'turbo';
  const requiredNodes=[
    'UNETLoader','CLIPLoader','VAELoader','LoraLoaderModelOnly',
    'ModelAttentionBackend','MiniMaxH3SigmaShift','MiniMaxH3ReferenceToVideo',
    'BasicGuider','BasicScheduler','KSamplerSelect','RandomNoise',
    'SamplerCustomAdvanced','VAEDecode','CreateVideo','SaveVideo',
  ];
  if(config.audioDriver)requiredNodes.push('MiniMaxH3AddGuide','EmptyAudio','AudioConcat','TrimAudioDuration','H3ReferenceAudio','LoadAudio');
  else requiredNodes.push('VAEDecodeAudio');
  if(counts.images)requiredNodes.push('LoadImage');
  if(counts.videos){
    requiredNodes.push('LoadVideo','Video Slice','GetVideoComponents','H3ReferenceVideo');
    if(config.videos.some(video=>video?.audioFile))requiredNodes.push('LoadAudio','TrimAudioDuration','H3ReferenceAudio');
  }
  if(counts.audios)requiredNodes.push('LoadAudio','H3ReferenceAudio');
  if(config.spectrum===true)requiredNodes.push('SpectrumApplyMiniMaxH3');
  const missing=requiredNodes.filter(type=>!info[type]);
  const files=[
    ['UNETLoader','unet_name',REFERENCE_VIDEO_MODELS[model]],
    ['CLIPLoader','clip_name',REFERENCE_VIDEO_MODELS.text],
    ['VAELoader','vae_name',REFERENCE_VIDEO_MODELS.videoVae],
    ['VAELoader','vae_name',REFERENCE_VIDEO_MODELS.audioVae],
    ...(speedup==='turbo'?[['LoraLoaderModelOnly','lora_name',REFERENCE_VIDEO_MODELS.turbo]]:[]),
  ];
  for(const [type,key,file] of files){
    if(file&&!options(info,type,key).includes(file))missing.push(file);
  }
  if(info.CLIPLoader&&!options(info,'CLIPLoader','type').includes('minimax')){
    missing.push('MiniMax H3 text encoder type');
  }
  if(info.ModelAttentionBackend&&!options(info,'ModelAttentionBackend','attention').includes('comfy kitchen attention')){
    missing.push('Comfy Kitchen attention');
  }
  if(model==='viggle'&&speedup==='turbo'){
    missing.push('A verified turbo adapter for the Viggle checkpoint');
  }
  return {
    ready:missing.length===0,
    missing:[...new Set(missing)],
    model,
    speedup,
    nodeTypes:[...new Set(requiredNodes)],
    capabilities:REFERENCE_VIDEO_CAPABILITIES,
  };
}

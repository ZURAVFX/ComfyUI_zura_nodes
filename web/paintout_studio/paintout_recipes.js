// Native paintout recipes from Zura Nodes 1.3.30. These whole-shot graphs use
// source-frame anchors, not character references or first/last-frame prompts.
export const PAINTOUT_MODELS={
  model:'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
  text:'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
  videoVae:'ltx-2.5-video-vae-conv-bf16.safetensors',
  hdrVideoVae:'ltx-2.5-video-vae-bf16.safetensors',
  audioVae:'ltx-2.5-audio-vae-bf16.safetensors',
  targetedLora:'LTX23_Obscura_Remova_v1.safetensors',
  hdrLora:'ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors',
  hdrEmbeddings:'ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors',
  fullLora:'ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors',
};
const modelOptions=(info,node,key)=>{const field=info?.[node]?.input?.required?.[key]||info?.[node]?.input?.optional?.[key];return field?.[0]==='COMBO'?field[1]?.options||[]:Array.isArray(field?.[0])?field[0]:[];};
const modelChoice=(files,name)=>files.find(file=>file===name)||files.find(file=>String(file).replaceAll('\\','/').split('/').pop()===name);
function resolvedModelFiles(info){
  const inputs={model:['UNETLoader','unet_name'],text:['CLIPLoader','clip_name'],videoVae:['VAELoader','vae_name'],hdrVideoVae:['VAELoader','vae_name'],audioVae:['VAELoader','vae_name'],targetedLora:['LoraLoaderModelOnly','lora_name'],fullLora:['LTXICLoRALoaderModelOnly','lora_name'],hdrLora:['LTXICLoRALoaderModelOnly','lora_name'],hdrEmbeddings:['ZuraPaintoutHDRConditioning','file_name']};
  return Object.fromEntries(Object.entries(PAINTOUT_MODELS).map(([key,file])=>[key,modelChoice(modelOptions(info,...inputs[key]),file)||file]));
}
export const PAINTOUT_DEFAULT_PROMPTS={
  targeted:'Remove the objects covered by the removal mask, using the manually painted clean frames as the restored background. Preserve all other subjects, scene details, lighting and original camera movement.',
  full:'An empty clean plate of the same scene, without people, vehicles or moving obstructions. Preserve the static background, architecture, lighting, perspective and original camera movement.',
};
export const PAINTOUT_COLOUR_SPACES=['auto','acescg','acescct','hlg_rec2020','pq_rec2020','linear_rec709','srgb_display','rec709_gamma24','rec709_oetf'];
export const PAINTOUT_OUTPUT_MODES=['SDR video','HLG video','EXR sequence','EXR + SDR video','EXR + HLG video'];
export const PAINTOUT_SIZE_PRESETS=[['landscape','Widescreen · 16:9',16/9],['portrait','Portrait · 9:16',9/16],['square','Square · 1:1',1],['standard','Landscape · 4:3',4/3]];
export function paintoutPresetSize(preset,megapixels=.75){
  const ratio=PAINTOUT_SIZE_PRESETS.find(p=>p[0]===preset)?.[2]||16/9;
  const snap=n=>Math.max(64,Math.min(4096,Math.round(n/64)*64));
  return {width:snap(Math.sqrt(Number(megapixels)*1e6*ratio)),height:snap(Math.sqrt(Number(megapixels)*1e6/ratio))};
}
export const paintoutStages={
  source:'Reading footage and preparing frames',anchors:'Loading painted anchors',
  model:'Loading LTX 2.5',lora:'Loading the paintout adapter',memory:'Preparing guide attention',
  text:'Loading the text encoder',positive:'Encoding the prompt',negative:'Encoding the prompt',
  video_vae:'Loading the video VAE',float_vae:'Preparing float32 precision',audio_vae:'Loading the audio VAE',
  take:'Reading the selected frames',conditioning:'Preparing conditioning',latent:'Preparing video samples',
  grow_mask:'Expanding the removal mask',block_mask:'Preparing removal attention',invert_mask:'Preparing removal attention',
  guide:'Encoding source guidance',apply_anchors:'Encoding painted anchors',audio:'Preparing audio samples',
  combine:'Preparing samples',sample:'Generating the clean plate',separate:'Preparing the result',
  crop_guides:'Removing guide frames',decode:'Decoding the result',save:'Compositing and saving the shot',
};
const absolutePath=value=>typeof value==='string'&&(/^[a-z]:[\\/]/i.test(value)||/^\\\\[^\\]+\\[^\\]+/.test(value)||value.startsWith('/'));
const whole=(value,min,max)=>Number.isInteger(Number(value))&&Number(value)>=min&&Number(value)<=max;
export const paintoutColourPipeline=c=>c.colourPipeline||(c.processingSpace==='HDR (ACEScct)'?'hdr_hdr':'sdr_sdr');
const hdrSource=c=>['acescg','acescct','hlg_rec2020','pq_rec2020','linear_rec709'].includes(c.sourceColour==='auto'?c.detectedSourceColour:c.sourceColour);
const normalise=c=>({mode:'targeted',startFrame:0,frameCount:81,sequenceFps:25,sourceColour:'srgb_display',processingSpace:'SDR (sRGB)',width:1152,height:640,outputMode:'SDR video',savePrefix:'paintout/studio',exrPrecision:'float32',keepAudio:true,seed:42,maskBlockSize:32,...c});

/** Returns an actionable message, or an empty string when ready to queue. */
export function paintoutHDRFrameLimit(c){
  const width=Math.ceil(Number(c.sourceWidth||c.width)/64)*64,height=Math.ceil(Number(c.sourceHeight||c.height)/64)*64;
  if(!Number.isFinite(width*height)||width<=0||height<=0||Math.max(width,height)>4096)return 0;
  // Streaming still encodes a full-resolution temporal window. The backend
  // caps that window at 17 frames (or 9 for larger plates), not the whole shot.
  if(width*height*9>40000000)return 0;
  const cpuFrames=Math.floor((8*1024**3)/(width*height*3*4));
  return Math.min(121,Math.floor((cpuFrames-1)/8)*8+1);
}

export function paintoutValidation(config={}){
  const c=normalise(config);
  if(!['targeted','full'].includes(c.mode))return 'Choose targeted paintout or a full-scene clean plate.';
  if(!absolutePath(c.source))return 'Choose the original footage or an image-sequence folder.';
  if(!whole(c.startFrame,0,100000))return 'Start frame must be a whole source-frame number, starting at 0.';
  if(!whole(c.frameCount,1,993))return 'Choose between 1 and 993 frames for one continuous shot.';
  if(!Number.isFinite(Number(c.sequenceFps))||Number(c.sequenceFps)<1||Number(c.sequenceFps)>120)return 'Sequence frame rate must be between 1 and 120 fps.';
  if(c.sourceWidth>4096||c.sourceHeight>4096)return 'This plate exceeds the current 4096-pixel processing limit. No smaller proxy will be substituted.';
  if(c.resolutionMode==='source'&&![c.sourceWidth,c.sourceHeight].every(n=>whole(n,1,4096)))return 'Load footage up to 4096 pixels per side, or choose a smaller processing resolution.';
  if(![c.width,c.height].every(n=>whole(n,64,4096)&&Number(n)%64===0))return 'Render width and height must use 64-pixel increments, from 64 to 4096 pixels.';
  if(!PAINTOUT_COLOUR_SPACES.includes(c.sourceColour))return 'Choose the actual source colour space.';
  if(c.maskBlockSize!==0&&!whole(c.maskBlockSize,8,512))return 'Mask block size must be Off or a whole number from 8 to 512 pixels.';
  if(!['SDR (sRGB)','HDR (ACEScct)'].includes(c.processingSpace))return 'Choose SDR or HDR processing.';
  const pipeline=paintoutColourPipeline(c);
  if(!['sdr_sdr','sdr_hdr','hdr_hdr'].includes(pipeline))return 'Choose SDR to SDR, SDR to HDR or HDR to HDR.';
  if(hdrSource(c)&&pipeline!=='hdr_hdr')return 'This is HDR footage. Choose HDR to HDR to preserve its highlights.';
  if(pipeline==='hdr_hdr'&&c.sourceColour!=='auto'&&!hdrSource(c))return 'HDR to HDR needs HLG, PQ or a scene-linear/ACES source. Choose SDR to HDR for SDR footage.';
  if(pipeline==='sdr_sdr'&&c.outputMode.includes('HLG'))return 'Choose SDR to HDR for a real HDR conversion; HLG tags alone do not expand SDR.';
  if(pipeline!=='sdr_sdr'&&c.outputMode.includes('SDR'))return 'Choose HLG video, EXR sequence or EXR + HLG video for HDR delivery.';
  if(pipeline==='sdr_hdr'){
    const limit=paintoutHDRFrameLimit(c);
    if(c.frameCount>limit)return `SDR to HDR supports ${limit} frames at this plate size (streaming HDR memory limits). This clip has ${c.frameCount} frames. Keep SDR output for the full clip, or trim a shorter clip for HDR.`;
  }
  if(!PAINTOUT_OUTPUT_MODES.includes(c.outputMode))return 'Choose a supported video or EXR export.';
  if(!['float32','float16'].includes(c.exrPrecision))return 'Choose float32 or float16 EXR precision.';
  if(!String(c.savePrefix??'').trim()||absolutePath(c.savePrefix)||String(c.savePrefix).split(/[\\/]/).includes('..'))return 'Use an output name inside the ComfyUI output folder.';
  if(!Number.isSafeInteger(Number(c.seed))||Number(c.seed)<0)return 'Seed must be a positive whole number or zero.';
  if(c.keepAudio===false)return 'Paintout exports currently retain source audio when present.';
  if(c.mode==='targeted'){
    if(!absolutePath(c.mask)&&!(c.maskProject&&Number.isInteger(c.maskRevision)))return 'Create a removal mask or import a matching mask. White removes; black keeps the original.';
    if(c.maskProject&&Array.isArray(c.maskCoverage)){
      const covered=new Set(c.maskCoverage),missing=Array.from({length:Number(c.frameCount)},(_,i)=>Number(c.startFrame)+i).find(frame=>!covered.has(frame));
      if(missing!==undefined)return `Track or mark absent the remaining mask section before rendering. First unreviewed frame: ${missing}.`;
    }
    const anchors=(Array.isArray(c.anchors)?c.anchors:[]).filter(a=>a.enabled!==false);
    if(!anchors.length)return 'Add at least one painted clean frame and enter its source-frame number.';
    const seen=new Set(),start=Number(c.startFrame),last=start+Number(c.frameCount)-1;
    for(let i=0;i<anchors.length;i++){
      const a=anchors[i],frame=Number(a.frame),resolved=frame===-1?last:frame;
      if(!absolutePath(a.file))return `Choose an image for painted frame ${i+1}.`;
      if(a.frame===''||a.frame===null||a.frame===undefined||!Number.isInteger(frame)||frame< -1)return `Enter a whole source-frame number for painted frame ${i+1}.`;
      if(resolved<start||resolved>last)return `Painted frame ${frame} is outside the selected source range (${start}–${last}).`;
      if(seen.has(resolved))return `There is already a painted image for source frame ${resolved}.`;
      seen.add(resolved);
      const strength=Number(a.strength??.75);
      if(!Number.isFinite(strength)||strength<=0||strength>1)return `Painted frame ${i+1} strength must be greater than 0 and no more than 1.`;
      if(a.colour_space&&!PAINTOUT_COLOUR_SPACES.includes(a.colour_space))return `Choose a valid colour space for painted frame ${i+1}.`;
      if(c.processingSpace==='HDR (ACEScct)'&&['acescg','acescct','hlg_rec2020','pq_rec2020','linear_rec709'].includes(c.sourceColour)&&! /\.(exr|tiff?)$/i.test(a.file))return 'For HDR footage, use full-resolution EXR or high-bit-depth TIFF painted frames.';
    }
  }
  return '';
}

/** Offer an explicit range correction without moving painted source-frame IDs. */
export function paintoutRangeFix(config,sourceFrames,maskFrames){
  const c=normalise(config),start=Number(c.startFrame),count=Number(c.frameCount);
  if(!Number.isInteger(start)||!Number.isInteger(count)||start<0||count<1)return null;
  const anchors=c.mode==='targeted'?(c.anchors||[]).filter(a=>a.enabled!==false&&Number(a.frame)>=0).map(a=>Number(a.frame)):[];
  if(!anchors.every(Number.isInteger))return null;
  const available=Math.min(Number.isInteger(sourceFrames)?sourceFrames:Infinity,c.mode==='targeted'&&maskFrames>1?maskFrames:Infinity);
  const first=Math.min(start,...anchors),end=Math.min(Math.max(start+count,...anchors.map(n=>n+1)),available,first+993);
  if(end<=first||anchors.some(n=>n<first||n>=end)||first===start&&end-first===count)return null;
  return {patch:{startFrame:first,frameCount:end-first},label:`Use frames ${first}–${end-1} (${end-first} frames)`};
}

export function buildPaintoutGraph(config={},info){
  const error=paintoutValidation(config);if(error)throw new Error(error);
  const c=normalise(config),targeted=c.mode==='targeted',g={},models=resolvedModelFiles(info);
  const ref=(id,slot=0)=>[id,slot],node=(id,class_type,inputs)=>{g[id]={class_type,inputs,_meta:{title:paintoutStages[id]||id}};};
  const projectMask=targeted&&c.maskProject&&Number.isInteger(c.maskRevision);
  if(projectMask)node('mask_source','ZuraPaintoutMaskSource',{project:c.maskProject,revision:c.maskRevision});
  if(c.colourPipeline)node('colour_check','ZuraPaintoutColourCheck',{source:c.source,colour_space:c.sourceColour,pipeline:c.colourPipeline,frame_count:Number(c.frameCount),...(paintoutColourPipeline(c)==='sdr_hdr'?{sampling_mode:'tiled_fusion'}:{})});
  node('source',targeted?(projectMask?'ZuraPaintoutEditorCrop':'ZuraPaintoutCrop'):'ZuraPaintoutFullFrame',{
    plate_path:c.colourPipeline?ref('colour_check'):c.source,...(targeted?{mask_path:projectMask?ref('mask_source'):c.mask}:{}),colour_space:c.sourceColour,
    start_frame:Number(c.startFrame),frame_count:Number(c.frameCount),sequence_fps:Number(c.sequenceFps),
    context_pixels:128,max_crop_side:768,repair_grow:targeted?Number(c.maskGrow??0):0,feather_pixels:targeted?Number(c.maskFeather??0):0,
    processing_mode:paintoutColourPipeline(c)==='hdr_hdr'?'HDR (ACEScct)':'SDR (sRGB)',framing_mode:'Plate resolution (stretch to next grid)',
    render_width:Number(c.width),render_height:Number(c.height),
  });
  if(targeted)node('anchors','ZuraPaintoutAnchors',{plate:ref('source',2),anchors:JSON.stringify(c.anchors.filter(a=>a.enabled!==false).map(a=>({file:a.file,frame:Number(a.frame),strength:Number(a.strength??.75),enabled:true,...(a.colour_space?{colour_space:a.colour_space}:{})})))});
  node('model','UNETLoader',{unet_name:models.model,weight_dtype:'default'});
  node('lora',targeted?'LoraLoaderModelOnly':'LTXICLoRALoaderModelOnly',{model:ref('model'),lora_name:targeted?models.targetedLora:models.fullLora,strength_model:targeted?1.25:1});
  node('memory','ZuraPaintoutGuideMemory',{model:ref('lora'),query_chunk:1024});
  node('text','CLIPLoader',{clip_name:models.text,type:'ltxv',device:'default'});
  node('positive','CLIPTextEncode',{clip:ref('text'),text:String(c.prompt||'').trim()||PAINTOUT_DEFAULT_PROMPTS[c.mode]});
  node('negative','CLIPTextEncode',{clip:ref('text'),text:targeted?'blurry, low resolution, ugly, garbled mess, compression artifacts, glitch, stop motion, still image, pixelated, robotic voice, oversaturated':'people, person, pedestrian, human, cyclist, car, taxi, vehicle, bicycle, ghosting, blurry, distorted, jitter'});
  node('video_vae','VAELoader',{vae_name:paintoutColourPipeline(c)==='hdr_hdr'?models.hdrVideoVae:models.videoVae});
  node('float_vae','LTXVVAEForceFloat32',{vae:ref('video_vae')});
  node('audio_vae','VAELoader',{vae_name:models.audioVae});
  node('take','ZuraPaintoutTake',{plate:ref('source',2)});
  node('conditioning','LTXVConditioning',{positive:ref('positive'),negative:ref('negative'),frame_rate:ref('take',5)});
  node('latent','EmptyLTXVLatentVideo',{width:ref('take',2),height:ref('take',3),length:ref('take',4),batch_size:1});
  if(targeted){
    node('grow_mask','GrowMask',{mask:ref('take',1),expand:32,tapered_corners:true});
    if(Number(c.maskBlockSize)>0)node('block_mask','BlockifyMask',{masks:ref('grow_mask'),block_size:Number(c.maskBlockSize),device:'gpu'});
    node('invert_mask','InvertMask',{mask:ref(Number(c.maskBlockSize)>0?'block_mask':'grow_mask')});
  }
  node('guide','LTXAddVideoICLoRAGuideAdvanced',{
    positive:ref('conditioning'),negative:ref('conditioning',1),vae:ref('float_vae'),latent:ref('latent'),image:ref('take'),
    ...(targeted?{attention_mask:ref('invert_mask')}:{}),frame_idx:0,strength:1,latent_downscale_factor:1,crop:'disabled',
    use_tiled_encode:false,tile_size:256,tile_overlap:64,attention_strength:1,use_streaming:false,tile_frames:97,
  });
  const conditioned=targeted?'apply_anchors':'guide';
  if(targeted)node('apply_anchors','ZuraPaintoutApplyAnchors',{positive:ref('guide'),negative:ref('guide',1),vae:ref('float_vae'),latent:ref('guide',2),anchors:ref('anchors')});
  node('audio','LTXVEmptyLatentAudio',{audio_vae:ref('audio_vae'),frames_number:ref('take',4),frame_rate:ref('take',5),batch_size:1});
  node('combine','LTXVConcatAVLatent',{video_latent:ref(conditioned,2),audio_latent:ref('audio')});
  node('sample','KSampler',{model:ref('memory'),positive:ref(conditioned),negative:ref(conditioned,1),latent_image:ref('combine'),seed:Number(c.seed),steps:8,cfg:1,sampler_name:'euler_ancestral',scheduler:'linear_quadratic',denoise:1});
  node('separate','LTXVSeparateAVLatent',{av_latent:ref('sample')});
  node('crop_guides','LTXVCropGuides',{positive:ref(conditioned),negative:ref(conditioned,1),latent:ref('separate')});
  node('decode','VAEDecodeTiled',{samples:ref('crop_guides',2),vae:ref('float_vae'),tile_size:512,overlap:64,temporal_size:128,temporal_overlap:32});
  node('save','ZuraPaintoutUncrop',{decoded_crop:ref('decode'),plate:ref('source',2),output_name:c.savePrefix,precision:c.exrPrecision,match_context:targeted,export_format:c.outputMode,motion_preview:true});
  if(paintoutColourPipeline(c)==='sdr_hdr'){
    g.repair_save=g.save;delete g.save;
    Object.assign(g.repair_save.inputs,{export_format:'EXR sequence',motion_preview:false});
    if(!c.separateHDR)appendHDRConversion(g,c,['repair_save',0],['source',2],info);
  }
  return g;
}

/** Availability is mode-specific: one adapter need not block the other mode. */
export function paintoutAvailability(info={},mode='targeted',config={}){
  const targeted=mode!=='full',missing=[];if(config.colourPipeline&&!info.ZuraPaintoutColourCheck)missing.push('ZuraPaintoutColourCheck (restart ComfyUI after updating)');
  const options=(node,key)=>{const f=info[node]?.input?.required?.[key]||info[node]?.input?.optional?.[key];return f?.[0]==='COMBO'?f[1]?.options||[]:Array.isArray(f?.[0])?f[0]:[];};
  const expected={UNETLoader:['unet_name',PAINTOUT_MODELS.model],CLIPLoader:['clip_name',PAINTOUT_MODELS.text],[targeted?'LoraLoaderModelOnly':'LTXICLoRALoaderModelOnly']:['lora_name',targeted?PAINTOUT_MODELS.targetedLora:PAINTOUT_MODELS.fullLora]};
  for(const [node,[key,file]] of Object.entries(expected))if(!modelChoice(options(node,key),file))missing.push(file);
  for(const file of [paintoutColourPipeline(config)==='hdr_hdr'?PAINTOUT_MODELS.hdrVideoVae:PAINTOUT_MODELS.videoVae,PAINTOUT_MODELS.audioVae])if(!modelChoice(options('VAELoader','vae_name'),file))missing.push(file);
  const types=['UNETLoader','CLIPLoader','CLIPTextEncode','VAELoader','ZuraPaintoutTake','ZuraPaintoutUncrop','ZuraPaintoutGuideMemory','LTXVVAEForceFloat32','LTXVConditioning','EmptyLTXVLatentVideo','LTXAddVideoICLoRAGuideAdvanced','LTXVEmptyLatentAudio','LTXVConcatAVLatent','KSampler','LTXVSeparateAVLatent','LTXVCropGuides','VAEDecodeTiled',...(targeted?['ZuraPaintoutCrop','ZuraPaintoutAnchors','ZuraPaintoutApplyAnchors','GrowMask',...(config.maskBlockSize===0?[]:['BlockifyMask']),'InvertMask','LoraLoaderModelOnly']:['ZuraPaintoutFullFrame','LTXICLoRALoaderModelOnly'])];
  for(const node of types)if(!info[node])missing.push(node);
  if(info.KSampler&&!options('KSampler','scheduler').includes('linear_quadratic'))missing.push('LTX linear_quadratic scheduler');
  const guideInputs=info.LTXAddVideoICLoRAGuideAdvanced?.input;
  if(guideInputs&&!guideInputs.optional?.use_streaming&&!guideInputs.required?.use_streaming)missing.push('Current ComfyUI-LTXVideo guide nodes');
  if(paintoutColourPipeline(config)==='sdr_hdr'){
    if(!modelChoice(options('VAELoader','vae_name'),PAINTOUT_MODELS.hdrVideoVae))missing.push(PAINTOUT_MODELS.hdrVideoVae);
    for(const [type,key,file] of [['LTXICLoRALoaderModelOnly','lora_name',PAINTOUT_MODELS.hdrLora],['ZuraPaintoutHDRConditioning','file_name',PAINTOUT_MODELS.hdrEmbeddings]])if(!modelChoice(options(type,key),file))missing.push(file);
    for(const type of ['ZuraPaintoutHDRPrepare','ZuraPaintoutHDRSave','ZuraPaintoutHDRConditioning','ZuraPaintoutHDRResume','LTXAddVideoICLoRAGuide','ManualSigmas','LTXVTiledFusionSampler','KSamplerSelect'])if(!info[type])missing.push(type);
  }
  return {ready:!missing.length,missing:[...new Set(missing)]};
}

/** Queue only the repair; its EXR checkpoint can feed a fresh HDR queue. */
export function buildPaintoutRepairGraph(config={},info){
  return buildPaintoutGraph({...config,separateHDR:true},info);
}

/** Independent HDR queue. Resume validates the persisted checkpoint and frees
 * cached repair models before loading the conversion model. */
export function buildPaintoutHDRGraph(config={},savedSequence,info){
  const c=normalise(config);
  if(paintoutColourPipeline(c)!=='sdr_hdr')throw new Error('Choose SDR to HDR for the HDR conversion step.');
  const error=paintoutValidation(c);if(error)throw new Error(error);
  if(!absolutePath(savedSequence))throw new Error('Choose the saved SDR repair checkpoint.');
  const g={
    hdr_resume:{class_type:'ZuraPaintoutHDRResume',inputs:{saved_sequence:savedSequence},_meta:{title:'Resuming saved SDR repair and releasing repair models'}},
  };
  appendHDRConversion(g,c,['hdr_resume',0],['hdr_resume',1],info);
  return g;
}

// Official LTX 2.5 HDR adapter, using streaming TiledFusion at source raster.
// The guide must remain spatially untiled; fusion crops appended guide frames.
function appendHDRConversion(g,c,savedSequence,plate,info){
  const models=resolvedModelFiles(info);
  const r=(id,slot=0)=>[id,slot],n=(id,class_type,inputs,title)=>{g[id]={class_type,inputs,_meta:{title}};};
  n('hdr_prepare','ZuraPaintoutHDRPrepare',{saved_sequence:savedSequence,plate,sampling_mode:'tiled_fusion',model_name:models.model,...(g.repair_save?{release_models:true}:{})},'Preparing repaired SDR for HDR');
  n('hdr_model','UNETLoader',{unet_name:r('hdr_prepare',7),weight_dtype:'default'},'Loading HDR model after repair memory release');
  n('hdr_vae_loader','VAELoader',{vae_name:models.hdrVideoVae},'Loading HDR video VAE');
  n('hdr_vae','LTXVVAEForceFloat32',{vae:r('hdr_vae_loader')},'Preparing HDR float32 VAE');
  n('hdr_lora','LTXICLoRALoaderModelOnly',{model:r('hdr_model'),lora_name:models.hdrLora,strength_model:1},'Loading SDR to HDR adapter');
  n('hdr_conditioning','ZuraPaintoutHDRConditioning',{file_name:models.hdrEmbeddings},'Loading HDR scene embeddings');
  n('hdr_condition','LTXVConditioning',{positive:r('hdr_conditioning'),negative:r('hdr_conditioning'),frame_rate:r('hdr_prepare',5)},'Preparing HDR conditioning');
  n('hdr_latent','EmptyLTXVLatentVideo',{width:r('hdr_prepare',2),height:r('hdr_prepare',3),length:r('hdr_prepare',4),batch_size:1},'Preparing HDR samples');
  n('hdr_guide','LTXAddVideoICLoRAGuide',{positive:r('hdr_condition'),negative:r('hdr_condition',1),vae:r('hdr_vae'),latent:r('hdr_latent'),image:r('hdr_prepare'),frame_idx:0,strength:1,latent_downscale_factor:r('hdr_lora',1),crop:'disabled',use_tiled_encode:false,tile_size:256,tile_overlap:64,use_streaming:true,tile_frames:r('hdr_prepare',6)},'Encoding repaired SDR guide in temporal windows');
  n('hdr_sampler','KSamplerSelect',{sampler_name:'euler'},'Preparing HDR sampler');
  n('hdr_sigmas','ManualSigmas',{sigmas:'1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0'},'Preparing official HDR schedule');
  n('hdr_sample','LTXVTiledFusionSampler',{model:r('hdr_lora'),positive:r('hdr_guide'),negative:r('hdr_guide',1),latents:r('hdr_guide',2),sigmas:r('hdr_sigmas'),sampler:r('hdr_sampler'),seed:Number(c.seed),cfg:1,tile_width:1024,tile_height:576,overlap_frac:.5,blend_var:.05,grid_cycle:1,tile_frames:r('hdr_prepare',6),vae:r('hdr_vae'),canvas_device:'cpu'},'Converting the repaired shot to HDR');
  n('hdr_decode','VAEDecodeTiled',{samples:r('hdr_sample'),vae:r('hdr_vae'),tile_size:512,overlap:64,temporal_size:32,temporal_overlap:8},'Decoding HDR');
  n('save','ZuraPaintoutHDRSave',{images:r('hdr_decode'),take:r('hdr_prepare',1),output_name:c.savePrefix,precision:c.exrPrecision,export_format:c.outputMode},'Saving HDR at original resolution and frame rate');
}

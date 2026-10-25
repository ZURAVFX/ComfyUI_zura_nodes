// Native paintout recipes from Zura Nodes 1.3.30. These whole-shot graphs use
// source-frame anchors, not character references or first/last-frame prompts.
export const PAINTOUT_MODELS={
  model:'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
  text:'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
  videoVae:'ltx-2.5-video-vae-conv-bf16.safetensors',
  audioVae:'ltx-2.5-audio-vae-bf16.safetensors',
  targetedLora:'LTX23_Obscura_Remova_v1.safetensors',
  fullLora:'ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors',
};
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
const normalise=c=>({mode:'targeted',startFrame:0,frameCount:81,sequenceFps:25,sourceColour:'srgb_display',processingSpace:'SDR (sRGB)',width:1152,height:640,outputMode:'SDR video',savePrefix:'paintout/studio',exrPrecision:'float32',keepAudio:true,seed:42,...c});

/** Returns an actionable message, or an empty string when ready to queue. */
export function paintoutValidation(config={}){
  const c=normalise(config);
  if(!['targeted','full'].includes(c.mode))return 'Choose targeted paintout or a full-scene clean plate.';
  if(!absolutePath(c.source))return 'Choose the original footage or an image-sequence folder.';
  if(!whole(c.startFrame,0,100000))return 'Start frame must be a whole source-frame number, starting at 0.';
  if(!whole(c.frameCount,1,993))return 'Choose between 1 and 993 frames for one continuous shot.';
  if(!Number.isFinite(Number(c.sequenceFps))||Number(c.sequenceFps)<1||Number(c.sequenceFps)>120)return 'Sequence frame rate must be between 1 and 120 fps.';
  if(c.resolutionMode!==undefined&&!['default','source','custom',...PAINTOUT_SIZE_PRESETS.map(p=>p[0])].includes(c.resolutionMode))return 'Choose a processing resolution.';
  if(c.resolutionMode==='source'&&![c.sourceWidth,c.sourceHeight].every(n=>whole(n,1,4096)))return 'Load footage up to 4096 pixels per side, or choose a smaller processing resolution.';
  if(![c.width,c.height].every(n=>whole(n,64,4096)&&Number(n)%64===0))return 'Render width and height must use 64-pixel increments, from 64 to 4096 pixels.';
  if(!PAINTOUT_COLOUR_SPACES.includes(c.sourceColour))return 'Choose the actual source colour space.';
  if(!['SDR (sRGB)','HDR (ACEScct)'].includes(c.processingSpace))return 'Choose SDR or HDR processing.';
  if(!PAINTOUT_OUTPUT_MODES.includes(c.outputMode))return 'Choose a supported video or EXR export.';
  if(!['float32','float16'].includes(c.exrPrecision))return 'Choose float32 or float16 EXR precision.';
  if(!String(c.savePrefix??'').trim()||absolutePath(c.savePrefix)||String(c.savePrefix).split(/[\\/]/).includes('..'))return 'Use an output name inside the ComfyUI output folder.';
  if(!Number.isSafeInteger(Number(c.seed))||Number(c.seed)<0)return 'Seed must be a positive whole number or zero.';
  if(c.keepAudio===false)return 'Paintout exports currently retain source audio when present.';
  if(c.mode==='targeted'){
    if(!absolutePath(c.mask))return 'Add a matching removal mask. White removes; black keeps the original.';
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

export function buildPaintoutGraph(config={}){
  const error=paintoutValidation(config);if(error)throw new Error(error);
  const c=normalise(config),targeted=c.mode==='targeted',g={};
  const ref=(id,slot=0)=>[id,slot],node=(id,class_type,inputs)=>{g[id]={class_type,inputs,_meta:{title:paintoutStages[id]||id}};};
  node('source',targeted?'ZuraPaintoutCrop':'ZuraPaintoutFullFrame',{
    plate_path:c.source,...(targeted?{mask_path:c.mask}:{}),colour_space:c.sourceColour,
    start_frame:Number(c.startFrame),frame_count:Number(c.frameCount),sequence_fps:Number(c.sequenceFps),
    context_pixels:128,max_crop_side:768,repair_grow:0,feather_pixels:targeted?24:0,
    processing_mode:c.processingSpace,framing_mode:c.resolutionMode==='source'?'Source resolution (pad, no resize)':c.resolutionMode&&c.resolutionMode!=='default'?'Full frame (fit, no crop)':targeted?'Full frame (original method)':'Full frame (fit, no crop)',
    render_width:Number(c.width),render_height:Number(c.height),
  });
  if(targeted)node('anchors','ZuraPaintoutAnchors',{plate:ref('source',2),anchors:JSON.stringify(c.anchors.filter(a=>a.enabled!==false).map(a=>({file:a.file,frame:Number(a.frame),strength:Number(a.strength??.75),enabled:true,...(a.colour_space?{colour_space:a.colour_space}:{})})))});
  node('model','UNETLoader',{unet_name:PAINTOUT_MODELS.model,weight_dtype:'default'});
  node('lora',targeted?'LoraLoaderModelOnly':'LTXICLoRALoaderModelOnly',{model:ref('model'),lora_name:targeted?PAINTOUT_MODELS.targetedLora:PAINTOUT_MODELS.fullLora,strength_model:targeted?1.25:1});
  node('memory','ZuraPaintoutGuideMemory',{model:ref('lora'),query_chunk:1024});
  node('text','CLIPLoader',{clip_name:PAINTOUT_MODELS.text,type:'ltxv',device:'default'});
  node('positive','CLIPTextEncode',{clip:ref('text'),text:String(c.prompt||'').trim()||PAINTOUT_DEFAULT_PROMPTS[c.mode]});
  node('negative','CLIPTextEncode',{clip:ref('text'),text:targeted?'blurry, low resolution, ugly, garbled mess, compression artifacts, glitch, stop motion, still image, pixelated, robotic voice, oversaturated':'people, person, pedestrian, human, cyclist, car, taxi, vehicle, bicycle, ghosting, blurry, distorted, jitter'});
  node('video_vae','VAELoader',{vae_name:PAINTOUT_MODELS.videoVae});
  node('float_vae','LTXVVAEForceFloat32',{vae:ref('video_vae')});
  node('audio_vae','VAELoader',{vae_name:PAINTOUT_MODELS.audioVae});
  node('take','ZuraPaintoutTake',{plate:ref('source',2)});
  node('conditioning','LTXVConditioning',{positive:ref('positive'),negative:ref('negative'),frame_rate:ref('take',5)});
  node('latent','EmptyLTXVLatentVideo',{width:ref('take',2),height:ref('take',3),length:ref('take',4),batch_size:1});
  if(targeted){
    node('grow_mask','GrowMask',{mask:ref('take',1),expand:32,tapered_corners:true});
    node('block_mask','BlockifyMask',{masks:ref('grow_mask'),block_size:32,device:'gpu'});
    node('invert_mask','InvertMask',{mask:ref('block_mask')});
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
  return g;
}

/** Availability is mode-specific: one adapter need not block the other mode. */
export function paintoutAvailability(info={},mode='targeted'){
  const targeted=mode!=='full',missing=[];
  const options=(node,key)=>{const f=info[node]?.input?.required?.[key]||info[node]?.input?.optional?.[key];return f?.[0]==='COMBO'?f[1]?.options||[]:Array.isArray(f?.[0])?f[0]:[];};
  const expected={UNETLoader:['unet_name',PAINTOUT_MODELS.model],CLIPLoader:['clip_name',PAINTOUT_MODELS.text],[targeted?'LoraLoaderModelOnly':'LTXICLoRALoaderModelOnly']:['lora_name',targeted?PAINTOUT_MODELS.targetedLora:PAINTOUT_MODELS.fullLora]};
  for(const [node,[key,file]] of Object.entries(expected))if(!options(node,key).includes(file))missing.push(file);
  for(const file of [PAINTOUT_MODELS.videoVae,PAINTOUT_MODELS.audioVae])if(!options('VAELoader','vae_name').includes(file))missing.push(file);
  const types=['UNETLoader','CLIPLoader','CLIPTextEncode','VAELoader','ZuraPaintoutTake','ZuraPaintoutUncrop','ZuraPaintoutGuideMemory','LTXVVAEForceFloat32','LTXVConditioning','EmptyLTXVLatentVideo','LTXAddVideoICLoRAGuideAdvanced','LTXVEmptyLatentAudio','LTXVConcatAVLatent','KSampler','LTXVSeparateAVLatent','LTXVCropGuides','VAEDecodeTiled',...(targeted?['ZuraPaintoutCrop','ZuraPaintoutAnchors','ZuraPaintoutApplyAnchors','GrowMask','BlockifyMask','InvertMask','LoraLoaderModelOnly']:['ZuraPaintoutFullFrame','LTXICLoRALoaderModelOnly'])];
  for(const node of types)if(!info[node])missing.push(node);
  if(info.KSampler&&!options('KSampler','scheduler').includes('linear_quadratic'))missing.push('LTX linear_quadratic scheduler');
  const guideInputs=info.LTXAddVideoICLoRAGuideAdvanced?.input;
  if(guideInputs&&!guideInputs.optional?.use_streaming&&!guideInputs.required?.use_streaming)missing.push('Current ComfyUI-LTXVideo guide nodes');
  return {ready:!missing.length,missing:[...new Set(missing)]};
}

import {PAINTOUT_MODELS,paintoutValidation,paintoutColourPipeline} from './watermark_recipes.js';

export const SUBTITLE_PROMPT='Remove subtitles, captions, and related text occlusions from the video, restoring a clean and natural underlying image.';
export const SUBTITLE_MODELS={
  joyfox:{file:'ltx2.3-ic-subtitles-remove-general.safetensors',strength:1.2},
  zarxrax:{file:'ltx23_removetext_v1.safetensors',strength:1.5},
  upscaler:'ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors',
};
const options=(info,node,key)=>{const entry=info?.[node]?.input?.required?.[key]||info?.[node]?.input?.optional?.[key];return entry?.[0]==='COMBO'?entry[1]?.options||[]:Array.isArray(entry?.[0])?entry[0]:[];};
const choose=(values,name)=>values.find(value=>value===name)||values.find(value=>String(value).replaceAll('\\','/').split('/').pop()===name)||name;

export function subtitleValidation(config={}){
  const error=paintoutValidation({...config,mode:'targeted',targetedMethod:'automatic',referenceEnabled:false,anchors:[]});
  if(error)return error;
  if(paintoutColourPipeline(config)!=='sdr_sdr')return 'Subtitle removal currently needs SDR input and SDR output. Convert the finished clip separately if you need HDR.';
  if(!Object.hasOwn(SUBTITLE_MODELS,config.subtitleVariant||'zarxrax')||typeof SUBTITLE_MODELS[config.subtitleVariant||'zarxrax']!=='object')return 'Choose an available subtitle-removal adapter.';
  return '';
}

/** Two-stage video IC-LoRA graph: the source crop is never masked for inference. */
export function buildSubtitleGraph(config={},info={}){
  const error=subtitleValidation(config);if(error)throw Error(error);
  const variantName=config.subtitleVariant||'zarxrax',variant=SUBTITLE_MODELS[variantName],g={},n=(id,type,inputs,title)=>{g[id]={class_type:type,inputs,_meta:{title:title||id}};return [id,0];},r=(id,slot=0)=>[id,slot];
  const model=choose(options(info,'UNETLoader','unet_name'),PAINTOUT_MODELS.model),text=choose(options(info,'CLIPLoader','clip_name'),PAINTOUT_MODELS.text),vae=choose(options(info,'VAELoader','vae_name'),PAINTOUT_MODELS.videoVae),audioVae=choose(options(info,'VAELoader','vae_name'),PAINTOUT_MODELS.audioVae),lora=choose(options(info,'LTXICLoRALoaderModelOnly','lora_name'),variant.file),upscaler=choose(options(info,'LatentUpscaleModelLoader','model_name'),SUBTITLE_MODELS.upscaler);
  const project=!!config.maskProject&&Number.isInteger(config.maskRevision);
  if(project)n('mask_source','ZuraPaintoutMaskSource',{project:config.maskProject,revision:config.maskRevision},'Loading crop selection');
  n('source','ZuraPaintout'+(project?'EditorCrop':'Crop'),{plate_path:config.source,mask_path:project?r('mask_source'):config.mask,colour_space:config.sourceColour,start_frame:Number(config.startFrame),frame_count:Number(config.frameCount),sequence_fps:Number(config.sequenceFps),context_pixels:64,max_crop_side:4096,processing_scale:Number(config.processingScale??1),repair_grow:0,feather_pixels:0,processing_mode:'SDR (sRGB)',framing_mode:'Smart crop (experimental)',render_width:Number(config.width),render_height:Number(config.height)},'Preparing the crop from your selection');
  n('prepare','ZuraSubtitlePrepareCrop',{plate:r('source',2)},'Preparing two-stage crop');
  n('take','ZuraPaintoutTake',{plate:r('prepare')},'Reading source frames');
  n('model','UNETLoader',{unet_name:model,weight_dtype:'default'},'Loading LTX 2.5');
  n('lora','LTXICLoRALoaderModelOnly',{model:r('model'),lora_name:lora,strength_model:variant.strength},'Loading subtitle removal adapter');
  n('text','CLIPLoader',{clip_name:text,type:'ltxv',device:'default'},'Loading text encoder');
  const prompt=String(config.prompt||'').trim();
  n('positive','CLIPTextEncode',{clip:r('text'),text:variantName==='zarxrax'&&!/^removetext\b/i.test(prompt)?`removetext ${prompt||SUBTITLE_PROMPT}`:prompt||SUBTITLE_PROMPT},'Encoding instruction');
  n('negative','CLIPTextEncode',{clip:r('text'),text:'pc game, console game, video game, cartoon, childish, ugly'},'Encoding negative instruction');
  n('vae','VAELoader',{vae_name:vae},'Loading video decoder');n('float_vae','LTXVVAEForceFloat32',{vae:r('vae')},'Preparing video precision');
  n('audio_vae','VAELoader',{vae_name:audioVae},'Loading audio encoder');
  n('audio_source','ZuraSubtitleSourceAudio',{plate:r('prepare')},'Reading source audio');
  n('audio_encoded','LTXVAudioVAEEncode',{audio:r('audio_source'),audio_vae:r('audio_vae')},'Preparing source audio guidance');
  n('conditioning','LTXVConditioning',{positive:r('positive'),negative:r('negative'),frame_rate:r('take',5)},'Preparing video conditioning');
  n('latent','EmptyLTXVLatentVideo',{width:r('prepare',2),height:r('prepare',3),length:r('take',4),batch_size:1},'Preparing first pass');
  n('guide','LTXAddVideoICLoRAGuide',{positive:r('conditioning'),negative:r('conditioning',1),vae:r('float_vae'),latent:r('latent'),image:r('prepare',1),frame_idx:0,strength:1,latent_downscale_factor:1,crop:'disabled',use_tiled_encode:true,tile_size:256,tile_overlap:64},'Guiding with the full source crop');
  n('audio_ref','LTXVSetAudioRefTokens',{positive:r('guide'),negative:r('guide',1),audio_latent:r('audio_encoded')},'Guiding with source audio');
  n('audio_empty','LTXVEmptyLatentAudio',{audio_vae:r('audio_vae'),frames_number:r('take',4),frame_rate:r('take',5),batch_size:1},'Preparing audio samples');
  n('combine','LTXVConcatAVLatent',{video_latent:r('guide',2),audio_latent:r('audio_empty')});
  n('guider','CFGGuider',{model:r('lora'),positive:r('audio_ref'),negative:r('audio_ref',1),cfg:1});
  n('noise','RandomNoise',{noise_seed:Number(config.seed)});n('sampler','KSamplerSelect',{sampler_name:'euler'});
  n('sigmas','ManualSigmas',{sigmas:'1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0'});
  n('sample','SamplerCustomAdvanced',{noise:r('noise'),guider:r('guider'),sampler:r('sampler'),sigmas:r('sigmas'),latent_image:r('combine')},'Removing subtitles · first pass');
  n('separate','LTXVSeparateAVLatent',{av_latent:r('sample')});
  n('crop_guides','LTXVCropGuides',{positive:r('guide'),negative:r('guide',1),latent:r('separate')});
  n('upscale_model','LatentUpscaleModelLoader',{model_name:upscaler},'Loading LTX 2.5 upscaler');
  n('upscale','LTXVLatentUpsampler',{samples:r('crop_guides',2),upscale_model:r('upscale_model'),vae:r('float_vae')},'Upscaling the crop');
  n('audio_ref2','LTXVSetAudioRefTokens',{positive:r('crop_guides'),negative:r('crop_guides',1),audio_latent:r('separate',1)});
  n('guide2','LTXAddVideoICLoRAGuide',{positive:r('audio_ref2'),negative:r('audio_ref2',1),vae:r('float_vae'),latent:r('upscale'),image:r('take'),frame_idx:0,strength:1,latent_downscale_factor:1,crop:'disabled',use_tiled_encode:true,tile_size:256,tile_overlap:64},'Guiding the full-resolution crop');
  n('combine2','LTXVConcatAVLatent',{video_latent:r('guide2',2),audio_latent:r('audio_ref2',2)});
  n('guider2','CFGGuider',{model:r('lora'),positive:r('guide2'),negative:r('guide2',1),cfg:1});
  n('noise2','RandomNoise',{noise_seed:29});n('sampler2','KSamplerSelect',{sampler_name:'euler'});
  n('sigmas2','ManualSigmas',{sigmas:'0.909375, 0.725, 0.421875, 0.0'});
  n('sample2','SamplerCustomAdvanced',{noise:r('noise2'),guider:r('guider2'),sampler:r('sampler2'),sigmas:r('sigmas2'),latent_image:r('combine2')},'Refining the crop');
  n('separate2','LTXVSeparateAVLatent',{av_latent:r('sample2')});
  n('crop_guides2','LTXVCropGuides',{positive:r('guide2'),negative:r('guide2',1),latent:r('separate2')});
  n('decode','VAEDecodeTiled',{samples:r('crop_guides2',2),vae:r('float_vae'),tile_size:512,overlap:64,temporal_size:128,temporal_overlap:32},'Decoding repaired crop');
  n('save','ZuraPaintoutUncrop',{decoded_crop:r('decode'),plate:r('prepare'),output_name:config.savePrefix,precision:config.exrPrecision||'float32',match_context:false,export_format:config.outputMode,motion_preview:true},'Blending and saving');
  return g;
}

export function subtitleAvailability(info={},config={}){
  const example={...config,source:'C:/example.mp4',mask:'C:/mask.png',maskProject:null,maskRevision:null,maskCoverage:null,startFrame:0,frameCount:9,sequenceFps:25,sourceColour:'srgb_display',processingSpace:'SDR (sRGB)',colourPipeline:'sdr_sdr',width:1152,height:640,sourceWidth:1152,sourceHeight:640,maskBlockSize:0,outputMode:'SDR video',seed:42,savePrefix:'ZURA STUDIO/test',exrPrecision:'float32'};
  const variant=SUBTITLE_MODELS[example.subtitleVariant||'zarxrax']||SUBTITLE_MODELS.zarxrax;
  const missing=[];
  try{for(const node of Object.values(buildSubtitleGraph(example,info)))if(!info[node.class_type])missing.push(node.class_type);}catch(error){return {ready:false,missing:[error.message]};}
  for(const [node,key,file] of [['UNETLoader','unet_name',PAINTOUT_MODELS.model],['CLIPLoader','clip_name',PAINTOUT_MODELS.text],['VAELoader','vae_name',PAINTOUT_MODELS.videoVae],['VAELoader','vae_name',PAINTOUT_MODELS.audioVae],['LTXICLoRALoaderModelOnly','lora_name',variant.file],['LatentUpscaleModelLoader','model_name',SUBTITLE_MODELS.upscaler]])if(choose(options(info,node,key),file)===file&&!options(info,node,key).includes(file))missing.push(file);
  return {ready:missing.length===0,missing:[...new Set(missing)]};
}

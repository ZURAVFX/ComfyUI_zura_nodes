import {LTX_FRAME_VIDEO_MODELS,LTX_DISTILLED_SIGMAS} from './ltx_frame_video_recipes.js';
import {applyAvailableAttention} from './studio_attention.js';

export const ALPHA_VIDEO_MODELS=Object.freeze({...LTX_FRAME_VIDEO_MODELS,lora:'ltx-2.5-22b-ic-lora-alpha-gen-0.9.safetensors'});
export const ALPHA_VIDEO_LIMITS=Object.freeze({maxFrames:145,dimensionStep:32,maxDimension:1920,maxPixels:1920*1088});
export const ALPHA_VIDEO_NODES=Object.freeze(['ZuraAlphaVideoInput','ZuraAlphaVideoOutput','UNETLoader','CLIPLoader','VAELoader','LTXICLoRALoaderModelOnly','CLIPTextEncode','LTXVConditioning','EmptyLTXVLatentVideo','LTXAddVideoICLoRAGuide','LTXVEmptyLatentAudio','LTXVConcatAVLatent','CFGGuider','RandomNoise','KSamplerSelect','ManualSigmas','SamplerCustomAdvanced','LTXVSeparateAVLatent','LTXVCropGuides','VAEDecodeTiled']);
const basename=s=>String(s).replaceAll('\\','/').split('/').pop().toLowerCase();
const options=(info,node,key)=>{const field=info?.[node]?.input?.required?.[key];return Array.isArray(field?.[0])?field[0]:field?.[0]==='COMBO'?field[1]?.options||[]:[];};
const choice=(info,node,key,file)=>options(info,node,key).find(value=>basename(value)===basename(file))||file;
// Match Python's pixel rounding before the adapter pads to model alignment.
const roundContent=value=>{const lower=Math.floor(value);return value-lower===.5?lower+lower%2:Math.round(value);};

/** Pad each processing axis upwards. The input adapter never stretches footage. */
export function alphaProcessingSize(width,height,scale=1){
  if(![width,height,scale].every(value=>Number.isFinite(Number(value))&&Number(value)>0)||Number(scale)<.25||Number(scale)>1)throw Error('Choose a processing scale from 25% to 100%.');
  return {width:Math.max(32,Math.ceil(roundContent(Number(width)*Number(scale))/32)*32),height:Math.max(32,Math.ceil(roundContent(Number(height)*Number(scale))/32)*32)};
}

export function alphaVideoValidation(c={}){
  if(typeof c.source!=='string'||!c.source.trim())return 'Add a source video.';
  if(!Number.isInteger(c.startFrame)||c.startFrame<0||!Number.isInteger(c.frameCount)||c.frameCount<1||c.frameCount>ALPHA_VIDEO_LIMITS.maxFrames)return 'Trim the clip to between 1 and 145 frames.';
  if(Number.isInteger(c.sourceFrames)&&c.startFrame+c.frameCount>c.sourceFrames)return 'The selection extends past the end of the source video.';
  if(!Number.isFinite(c.sequenceFps)||c.sequenceFps<=0||c.sequenceFps>1000)return 'The source video needs a valid constant frame rate.';
  if(![c.sourceWidth,c.sourceHeight].every(v=>Number.isInteger(v)&&v>0))return 'The source video dimensions are unavailable. Load the clip again.';
  let size;try{size=alphaProcessingSize(c.sourceWidth,c.sourceHeight,c.processingScale??1);}catch(error){return error.message;}
  if(size.width>ALPHA_VIDEO_LIMITS.maxDimension||size.height>ALPHA_VIDEO_LIMITS.maxDimension||Math.min(size.width,size.height)>1088||size.width*size.height>ALPHA_VIDEO_LIMITS.maxPixels)return 'Choose a lower processing scale. Alpha supports up to 1920 × 1088 pixels, including portrait orientation.';
  if(!Number.isSafeInteger(c.seed??42)||(c.seed??42)<0)return 'Choose a whole-number seed.';
  return '';
}

export function alphaVideoAvailability(info={}){
  const missing=ALPHA_VIDEO_NODES.filter(name=>!info[name]);
  for(const [node,key,file] of [['UNETLoader','unet_name',ALPHA_VIDEO_MODELS.model],['CLIPLoader','clip_name',ALPHA_VIDEO_MODELS.text],['VAELoader','vae_name',ALPHA_VIDEO_MODELS.videoVae],['VAELoader','vae_name',ALPHA_VIDEO_MODELS.audioVae],['LTXICLoRALoaderModelOnly','lora_name',ALPHA_VIDEO_MODELS.lora]])if(!options(info,node,key).some(value=>basename(value)===basename(file)))missing.push(file);
  if(info.CLIPLoader&&!options(info,'CLIPLoader','type').includes('ltxv'))missing.push('ltxv text support');
  if(info.KSamplerSelect&&!options(info,'KSamplerSelect','sampler_name').includes('euler_ancestral'))missing.push('Euler ancestral sampler');
  return {ready:missing.length===0,missing:[...new Set(missing)]};
}

/** Official native-resolution, single-stage V2V recipe. Alpha is promptless. */
export function buildAlphaVideoGraph(c,info){
  const error=alphaVideoValidation(c);if(error)throw Error(error);
  const g={},r=(id,slot=0)=>[id,slot],n=(id,class_type,inputs,title)=>{g[id]={class_type,inputs,_meta:{title}};};
  n('source','ZuraAlphaVideoInput',{source_path:c.source,start_frame:c.startFrame,frame_count:c.frameCount,processing_scale:Number(c.processingScale??1)},'Reading and padding the selected footage');
  n('model','UNETLoader',{unet_name:choice(info,'UNETLoader','unet_name',ALPHA_VIDEO_MODELS.model),weight_dtype:'default'},'Loading LTX 2.5');
  n('adapter','LTXICLoRALoaderModelOnly',{model:r('model'),lora_name:choice(info,'LTXICLoRALoaderModelOnly','lora_name',ALPHA_VIDEO_MODELS.lora),strength_model:1},'Loading Alpha Gen');
  n('attention','ModelAttentionBackend',{model:r('adapter'),attention:'comfy kitchen attention'},'Preparing Comfy Kitchen attention');
  n('text','CLIPLoader',{clip_name:choice(info,'CLIPLoader','clip_name',ALPHA_VIDEO_MODELS.text),type:'ltxv',device:'default'},'Loading the text encoder');
  n('video_vae','VAELoader',{vae_name:choice(info,'VAELoader','vae_name',ALPHA_VIDEO_MODELS.videoVae)},'Loading the video VAE');
  n('audio_vae','VAELoader',{vae_name:choice(info,'VAELoader','vae_name',ALPHA_VIDEO_MODELS.audioVae)},'Loading the audio VAE');
  n('positive','CLIPTextEncode',{clip:r('text'),text:''},'Preparing empty alpha conditioning');
  n('negative','CLIPTextEncode',{clip:r('text'),text:''},'Preparing empty negative conditioning');
  n('conditioning','LTXVConditioning',{positive:r('positive'),negative:r('negative'),frame_rate:r('source',5)},'Matching the source frame rate');
  n('empty_video','EmptyLTXVLatentVideo',{width:r('source',2),height:r('source',3),length:r('source',4),batch_size:1},'Preparing the padded video latent');
  n('guide','LTXAddVideoICLoRAGuide',{positive:r('conditioning'),negative:r('conditioning',1),vae:r('video_vae'),latent:r('empty_video'),image:r('source'),frame_idx:0,strength:1,latent_downscale_factor:r('adapter',1),crop:'disabled',use_tiled_encode:true,tile_size:256,tile_overlap:64},'Encoding the original footage as alpha guidance');
  n('empty_audio','LTXVEmptyLatentAudio',{frames_number:r('source',4),frame_rate:r('source',5),batch_size:1,audio_vae:r('audio_vae')},'Preparing empty audio tokens');
  n('av_latent','LTXVConcatAVLatent',{video_latent:r('guide',2),audio_latent:r('empty_audio')},'Preparing the sampling latent');
  n('guider','CFGGuider',{model:r('attention'),positive:r('guide'),negative:r('guide',1),cfg:1},'Preparing alpha guidance');
  n('sampler','KSamplerSelect',{sampler_name:'euler_ancestral'},'Preparing the native sampler');
  n('sigmas','ManualSigmas',{sigmas:LTX_DISTILLED_SIGMAS},'Preparing the official eight-step schedule');
  n('noise','RandomNoise',{noise_seed:c.seed??42},'Preparing noise');
  n('sample','SamplerCustomAdvanced',{noise:r('noise'),guider:r('guider'),sampler:r('sampler'),sigmas:r('sigmas'),latent_image:r('av_latent')},'Generating the alpha matte');
  n('separate','LTXVSeparateAVLatent',{av_latent:r('sample')},'Separating the video latent');
  n('crop_guides','LTXVCropGuides',{positive:r('guide'),negative:r('guide',1),latent:r('separate')},'Removing conditioning frames');
  n('decode','VAEDecodeTiled',{samples:r('crop_guides',2),vae:r('video_vae'),tile_size:512,overlap:64,temporal_size:64,temporal_overlap:8},'Decoding the alpha matte');
  n('save','ZuraAlphaVideoOutput',{images:r('decode'),info:r('source',1),filename_prefix:c.savePrefix||'ZURA STUDIO/alpha'},'Saving source-sized alpha and transparent video');
  return applyAvailableAttention(g,info);
}

export function alphaVideoOutput(entry,config){
  const output=entry?.outputs?.save||{},files=[...(output.images||[]),...(output.files||[])].filter(f=>f?.filename),find=(role,pattern)=>files.find(f=>f.role===role)||files.find(f=>pattern.test(f.filename));
  const matte=find('matte',/matte.*\.mp4$/i),preview=find('preview',/(checker|preview).*\.mp4$/i),alpha=find('alpha',/\.mov$/i),sequence=find('sequence',/\.zip$/i);
  if(!matte||!preview||!alpha)return null;
  return {matte,preview,alpha,...(sequence?{sequence}:{}),config};
}

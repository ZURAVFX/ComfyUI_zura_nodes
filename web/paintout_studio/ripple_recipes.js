// Approved first-frame object experiment. No video mask or timed-anchor promise.
import {PAINTOUT_MODELS} from './paintout_recipes.js';
export const RIPPLE_LORA='LTX25_Ripple_v11.safetensors';
export const RIPPLE_PROMPT='Use the reference video for motion, timing, camera movement, composition, and unchanged scene content, while consistently propagating the visual edit established in the first frame throughout the video.';
const base=s=>String(s).replaceAll('\\','/').split('/').pop();
const choices=(info,node,key)=>{const f=info?.[node]?.input?.required?.[key]||info?.[node]?.input?.optional?.[key];return Array.isArray(f?.[0])?f[0]:f?.[1]?.options||[];};
const file=(info,node,key,name)=>choices(info,node,key).find(s=>base(s)===name)||name;
const NODES=['ZuraPaintoutFullFrame','ZuraPaintoutAnchors','ZuraPaintoutTake','ZuraRippleGuide','ZuraPaintoutUncrop','UNETLoader','LoraLoaderModelOnly','ModelAttentionBackend','CLIPLoader','CLIPTextEncode','VAELoader','LTXVConditioning','EmptyLTXVLatentVideo','LTXAddVideoICLoRAGuide','LTXVEmptyLatentAudio','LTXVConcatAVLatent','CFGGuider','RandomNoise','KSamplerSelect','BasicScheduler','SamplerCustomAdvanced','LTXVSeparateAVLatent','LTXVCropGuides','VAEDecode','ImageFromBatch'];
const FILES=[['UNETLoader','unet_name',PAINTOUT_MODELS.model],['CLIPLoader','clip_name',PAINTOUT_MODELS.text],['VAELoader','vae_name',PAINTOUT_MODELS.videoVae],['VAELoader','vae_name',PAINTOUT_MODELS.audioVae],['LoraLoaderModelOnly','lora_name',RIPPLE_LORA]];

export function rippleValidation(c){
  if(!c.source)return 'Add a source video.';
  if([c.sourceColour,c.detectedSourceColour].some(s=>['hlg_rec2020','pq_rec2020','pq_display_p3','acescg','acescct','linear_rec709'].includes(s)))return 'Ripple object replacement currently supports SDR footage only.';
  if(c.colourPipeline&&c.colourPipeline!=='sdr_sdr'||c.processingSpace&&c.processingSpace!=='SDR (sRGB)')return 'Ripple object replacement currently supports SDR footage only.';
  if(!Number.isInteger(c.startFrame)||c.startFrame<0||!Number.isInteger(c.frameCount)||c.frameCount<1||c.frameCount>985)return 'Choose a valid clip range of 1 to 985 source frames (including the model’s held tail).';
  if(!Number.isFinite(c.sequenceFps)||c.sequenceFps<1||c.sequenceFps>120)return 'Choose a valid source frame rate.';
  const anchors=(c.anchors||[]).filter(a=>a.enabled!==false);
  if(anchors.length!==1||!anchors[0].file||Number(anchors[0].frame)!==c.startFrame)return 'Create or import a replacement image for the first selected frame.';
  if(anchors[0].rippleReviewedFile!==anchors[0].file)return 'Review the first-frame replacement image, then click Use this first frame.';
  if(!Number.isSafeInteger(c.seed)||c.seed<0)return 'Choose a whole-number seed.';
  if(!Number.isFinite(Number(c.rippleStrength??1.35))||Number(c.rippleStrength??1.35)<.1||Number(c.rippleStrength??1.35)>2)return 'Choose a Ripple strength between 0.1 and 2.';
  if(!['SDR video'].includes(c.outputMode||'SDR video'))return 'Choose SDR video for Ripple object replacement.';
  return '';
}

export function rippleAvailability(info={}){
  const missing=NODES.filter(n=>!info[n]).map(n=>n==='ZuraRippleGuide'?'ZuraRippleGuide (restart ComfyUI after updating)':n);
  for(const [node,key,name] of FILES)if(!choices(info,node,key).some(s=>base(s)===name))missing.push(name);
  return {ready:!missing.length,missing};
}

export function buildRippleGraph(c,info){
  const error=rippleValidation(c);if(error)throw Error(error);
  const g={},r=(id,slot=0)=>[id,slot],n=(id,class_type,inputs,title)=>{g[id]={class_type,inputs,_meta:{title}};return r(id);};
  n('source','ZuraPaintoutFullFrame',{plate_path:c.source,colour_space:c.sourceColour||'srgb_display',start_frame:c.startFrame,frame_count:c.frameCount,sequence_fps:c.sequenceFps,context_pixels:128,max_crop_side:768,repair_grow:0,feather_pixels:0,processing_mode:'SDR (sRGB)',framing_mode:'Plate resolution (stretch to next grid)',render_width:c.width||1152,render_height:c.height||640},'Reading the selected clip at its original frame rate');
  n('anchors','ZuraPaintoutAnchors',{plate:r('source',2),anchors:JSON.stringify(c.anchors.filter(a=>a.enabled!==false).map(a=>({file:a.file,frame:c.startFrame,strength:1,enabled:true,colour_space:a.colour_space||c.sourceColour||'srgb_display'})))},'Loading your replacement first frame');
  n('take','ZuraPaintoutTake',{plate:r('source',2)},'Preparing source frames and held tail');
  n('ripple_guide','ZuraRippleGuide',{plate:r('source',2),anchors:r('anchors')},'Preparing the first-frame Ripple guide');
  n('model','UNETLoader',{unet_name:file(info,'UNETLoader','unet_name',PAINTOUT_MODELS.model),weight_dtype:'default'},'Loading LTX 2.5');
  n('lora','LoraLoaderModelOnly',{model:r('model'),lora_name:file(info,'LoraLoaderModelOnly','lora_name',RIPPLE_LORA),strength_model:Number(c.rippleStrength??1.35)},'Loading Ripple');
  n('attention','ModelAttentionBackend',{model:r('lora'),attention:'comfy kitchen attention'},'Preparing attention');
  n('text','CLIPLoader',{clip_name:file(info,'CLIPLoader','clip_name',PAINTOUT_MODELS.text),type:'ltxv',device:'default'},'Loading the text encoder');
  n('positive','CLIPTextEncode',{clip:r('text'),text:RIPPLE_PROMPT+'\n'+String(c.prompt||'').trim()},'Encoding your object direction');
  n('negative','CLIPTextEncode',{clip:r('text'),text:'blurry, low resolution, ugly, garbled mess, compression artifacts, glitch, stop motion, still image, pixelated, robotic voice, oversaturated'},'Preparing conditioning');
  n('video_vae','VAELoader',{vae_name:file(info,'VAELoader','vae_name',PAINTOUT_MODELS.videoVae)},'Loading the video VAE');
  n('audio_vae','VAELoader',{vae_name:file(info,'VAELoader','vae_name',PAINTOUT_MODELS.audioVae)},'Loading the audio VAE');
  n('conditioning','LTXVConditioning',{positive:r('positive'),negative:r('negative'),frame_rate:r('take',5)},'Keeping the source frame rate');
  n('latent','EmptyLTXVLatentVideo',{width:r('take',2),height:r('take',3),length:r('ripple_guide',1),batch_size:1},'Preparing video samples');
  n('guide','LTXAddVideoICLoRAGuide',{positive:r('conditioning'),negative:r('conditioning',1),vae:r('video_vae'),latent:r('latent'),image:r('ripple_guide'),frame_idx:0,strength:1,latent_downscale_factor:1,crop:'disabled',use_tiled_encode:false,tile_size:256,tile_overlap:64},'Encoding source motion and the first-frame edit');
  n('audio','LTXVEmptyLatentAudio',{frames_number:r('ripple_guide',1),frame_rate:r('take',5),batch_size:1,audio_vae:r('audio_vae')},'Preparing model audio samples');
  n('combine','LTXVConcatAVLatent',{video_latent:r('guide',2),audio_latent:r('audio')},'Preparing samples');
  n('guider','CFGGuider',{model:r('attention'),positive:r('guide'),negative:r('guide',1),cfg:1},'Preparing Ripple guidance');
  n('noise','RandomNoise',{noise_seed:c.seed},'Preparing noise');
  n('sampler','KSamplerSelect',{sampler_name:'euler'},'Preparing sampler');
  n('sigmas','BasicScheduler',{model:r('attention'),scheduler:'simple',steps:8,denoise:1},'Preparing eight sampling steps');
  n('sample','SamplerCustomAdvanced',{noise:r('noise'),guider:r('guider'),sampler:r('sampler'),sigmas:r('sigmas'),latent_image:r('combine')},'Replacing the object through your clip');
  n('separate','LTXVSeparateAVLatent',{av_latent:r('sample')},'Preparing the video result');
  n('crop_guides','LTXVCropGuides',{positive:r('guide'),negative:r('guide',1),latent:r('separate')},'Removing model guides');
  n('decode','VAEDecode',{samples:r('crop_guides',2),vae:r('video_vae')},'Decoding the replacement video');
  n('align','ImageFromBatch',{image:r('decode'),batch_index:1,length:r('take',4)},'Aligning every frame with the original audio');
  n('save','ZuraPaintoutUncrop',{decoded_crop:r('align'),plate:r('source',2),output_name:c.savePrefix||'ZURA STUDIO/object replacement',precision:'float32',match_context:false,export_format:'SDR video',motion_preview:true},'Saving the full selected clip and original audio');
  return g;
}

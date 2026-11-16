import {LTX_FRAME_VIDEO_MODELS,LTX_DISTILLED_SIGMAS} from './ltx_frame_video_recipes.js';
import {applyAvailableAttention} from './studio_attention.js';

export const PAINT_VFX_ADAPTER=Object.freeze({
  file:'ainvfx-fluid.safetensors',repository:'AInVFX/ainvfx-fluid',revision:'6acb88df82c38a1f288a8f94fbd8b70eb5f975fb',
  path:'ltx-2.5/ainvfx-fluid.safetensors',size:654446320,
  sha256:'167b4ccfd3ed5e95c7973a0233f8fbd8edb5e9182ecb3998bd972661c861ebaa',
  url:'https://huggingface.co/AInVFX/ainvfx-fluid/resolve/6acb88df82c38a1f288a8f94fbd8b70eb5f975fb/ltx-2.5/ainvfx-fluid.safetensors',
  license:'LTX-2.x Community License',licenseUrl:'https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x',
  trigger:'ainvfxfluid',expectedDownscaleFactor:2,
});
export const PAINT_VFX_CAPABILITIES=Object.freeze({id:'paint-vfx',label:'Paint VFX',dimensionStep:64,minDimension:256,maxDimension:1920,minFrames:9,maxFrames:321,defaultFrames:121,defaultWidth:512,defaultHeight:512,fps:24,rates:[24,25,50],maxControlBytes:512*1024*1024,maxKeys:33,steps:8,
  nodeTypes:['ZuraPaintKeyframeVideo','UNETLoader','LTXICLoRALoaderModelOnly','CLIPLoader','CLIPTextEncode','VAELoader','LTXVConditioning','EmptyLTXVLatentVideo','LTXAddVideoICLoRAGuide','LTXVEmptyLatentAudio','LTXVConcatAVLatent','CFGGuider','KSamplerSelect','ManualSigmas','RandomNoise','SamplerCustomAdvanced','LTXVSeparateAVLatent','LTXVCropGuides','VAEDecodeTiled','LTXVAudioVAEDecode','CreateVideo','ZuraSaveProRes4444']});
const basename=value=>String(value||'').replaceAll('\\','/').split('/').at(-1);
const options=(info,node,key)=>{const field=info?.[node]?.input?.required?.[key];return field?.[0]==='COMBO'?field[1]?.options||[]:Array.isArray(field?.[0])?field[0]:[];};
const choice=(info,node,key,file)=>options(info,node,key).find(value=>basename(value)===basename(file))||file;
export function paintVfxPrompt(words){return 'ainvfxfluid, '+String(words||'').replace(/\bainvfxfluid\b[\s,]*/gi,'').trim();}
export function paintVfxValidation(c){
  const {width,height,frames}=c;
  if(![width,height].every(n=>Number.isInteger(n)&&n>=256&&n<=1920&&n%64===0))return 'Paint VFX needs dimensions in 64-pixel increments, from 256 to 1920.';
  if(!Number.isInteger(frames)||frames<9||frames>321||(frames-1)%8)return 'Paint VFX needs 8n + 1 frames, from 9 to 321.';
  if(width*height*frames*3*4>PAINT_VFX_CAPABILITIES.maxControlBytes)return 'Reduce the size or length. The painted control video is limited to 512 MiB.';
  if(!PAINT_VFX_CAPABILITIES.rates.includes(c.fps))return 'Paint VFX supports 24, 25 or 50 fps.';
  if(!String(c.prompt||'').replace(/\bainvfxfluid\b[\s,]*/gi,'').trim())return 'Describe the effect to generate.';
  if(!Number.isSafeInteger(c.seed??42)||(c.seed??42)<0)return 'Choose a whole-number seed, zero or higher.';
  if(c.steps!=null&&c.steps!==8)return 'Paint VFX uses the fixed distilled eight-step schedule.';
  if(c.fast||c.twoStage||c.audioEnabled||c.alpha)return 'Paint VFX uses its single-stage painted-control recipe. Audio references and alpha are separate workflows.';
  if(!Array.isArray(c.keys)||c.keys.length<2)return 'Paint the first and last keyframes before generating.';
  if(c.keys.length>33)return 'Use at most 33 painted keyframes.';
  const seen=new Set();
  for(const key of c.keys){
    if(!key||typeof key!=='object'||!Number.isInteger(key.frame)||key.frame<0||key.frame>=frames||key.frame!==0&&key.frame!==frames-1&&(key.frame-1)%8!==0||seen.has(key.frame))return 'Use unique keyframes at frame 0, the last frame, or 1 + 8n between them.';
    seen.add(key.frame);
    if(typeof key.image!=='string'||!key.image||key.image.includes('\\')||key.image.startsWith('/')||key.image.split('/').some(part=>!part||part==='.'||part==='..')||/[:\x00-\x1f]/.test(key.image)||!/\.(png|jpe?g|webp)$/i.test(key.image))return 'Save each painted keyframe as an image in the ComfyUI input folder.';
  }
  if(!seen.has(0)||!seen.has(frames-1))return 'Paint the first and last keyframes before generating.';
  return '';
}
export function paintVfxAvailability(info={}){
  const missing=PAINT_VFX_CAPABILITIES.nodeTypes.filter(node=>!info[node]);
  for(const [node,key,file] of [['UNETLoader','unet_name',LTX_FRAME_VIDEO_MODELS.model],['CLIPLoader','clip_name',LTX_FRAME_VIDEO_MODELS.text],['VAELoader','vae_name',LTX_FRAME_VIDEO_MODELS.videoVae],['VAELoader','vae_name',LTX_FRAME_VIDEO_MODELS.audioVae],['LTXICLoRALoaderModelOnly','lora_name',PAINT_VFX_ADAPTER.file]])if(!options(info,node,key).some(value=>basename(value)===basename(file)))missing.push(file);
  if(info.CLIPLoader&&!options(info,'CLIPLoader','type').includes('ltxv'))missing.push('ltxv text support');
  if(info.KSamplerSelect&&!options(info,'KSamplerSelect','sampler_name').includes('euler_ancestral'))missing.push('Euler ancestral sampler');
  return {ready:missing.length===0,missing:[...new Set(missing)]};
}
/** Sparse painted controls, not endpoint image conditioning or Ripple propagation. */
export function buildPaintVfxGraph(c,info){
  const error=paintVfxValidation(c);if(error)throw Error(error);
  const g={},r=(id,slot=0)=>[id,slot],n=(id,class_type,inputs,title)=>{g[id]={class_type,inputs,_meta:{title}};};
  n('control','ZuraPaintKeyframeVideo',{width:c.width,height:c.height,frames:c.frames,keys:JSON.stringify([...c.keys].sort((a,b)=>a.frame-b.frame).map(({frame,image})=>({frame,image})))},'Sparse painted keyframes on black');
  n('model','UNETLoader',{unet_name:choice(info,'UNETLoader','unet_name',LTX_FRAME_VIDEO_MODELS.model),weight_dtype:'default'},'Load LTX 2.5 distilled INT8');
  n('adapter','LTXICLoRALoaderModelOnly',{model:r('model'),lora_name:choice(info,'LTXICLoRALoaderModelOnly','lora_name',PAINT_VFX_ADAPTER.file),strength_model:1},'Load ainvfx-fluid painted-control adapter');
  n('attention','ModelAttentionBackend',{model:r('adapter'),attention:'comfy kitchen attention'},'Comfy Kitchen attention');
  n('text','CLIPLoader',{clip_name:choice(info,'CLIPLoader','clip_name',LTX_FRAME_VIDEO_MODELS.text),type:'ltxv',device:'default'},'Load Gemma4 INT8');
  n('video_vae','VAELoader',{vae_name:choice(info,'VAELoader','vae_name',LTX_FRAME_VIDEO_MODELS.videoVae)},'Load video VAE');
  n('audio_vae','VAELoader',{vae_name:choice(info,'VAELoader','vae_name',LTX_FRAME_VIDEO_MODELS.audioVae)},'Load audio VAE');
  n('positive','CLIPTextEncode',{clip:r('text'),text:paintVfxPrompt(c.prompt)},'Describe the painted effect');
  n('negative','CLIPTextEncode',{clip:r('text'),text:'blurry, low quality, distorted, watermark'},'Reference fluid negative prompt');
  n('conditioning','LTXVConditioning',{positive:r('positive'),negative:r('negative'),frame_rate:c.fps},'Match the chosen frame rate');
  n('empty_video','EmptyLTXVLatentVideo',{width:c.width,height:c.height,length:c.frames,batch_size:1},'Prepare video latent');
  n('guide','LTXAddVideoICLoRAGuide',{positive:r('conditioning'),negative:r('conditioning',1),vae:r('video_vae'),latent:r('empty_video'),image:r('control'),frame_idx:0,strength:1,latent_downscale_factor:r('adapter',1),crop:'disabled',use_tiled_encode:false,tile_size:256,tile_overlap:64,use_streaming:false,tile_frames:97},'Encode sparse painted keyframes with the adapter downscale factor');
  n('empty_audio','LTXVEmptyLatentAudio',{frames_number:c.frames,frame_rate:c.fps,batch_size:1,audio_vae:r('audio_vae')},'Prepare generated audio tokens');
  n('av_latent','LTXVConcatAVLatent',{video_latent:r('guide',2),audio_latent:r('empty_audio')},'Combine video and audio latents');
  n('guider','CFGGuider',{model:r('attention'),positive:r('guide'),negative:r('guide',1),cfg:1},'Painted-control CFG 1');
  n('sigmas','ManualSigmas',{sigmas:LTX_DISTILLED_SIGMAS},'Official distilled eight-step schedule');
  n('sampler','KSamplerSelect',{sampler_name:'euler_ancestral'},'Euler ancestral sampler');
  n('noise','RandomNoise',{noise_seed:c.seed??42},'Prepare noise');
  n('sample','SamplerCustomAdvanced',{noise:r('noise'),guider:r('guider'),sampler:r('sampler'),sigmas:r('sigmas'),latent_image:r('av_latent')},'Generate the painted effect');
  n('separate','LTXVSeparateAVLatent',{av_latent:r('sample')},'Separate video and audio');
  n('crop_guides','LTXVCropGuides',{positive:r('guide'),negative:r('guide',1),latent:r('separate')},'Remove conditioning frames');
  n('decode','VAEDecodeTiled',{samples:r('crop_guides',2),vae:r('video_vae'),tile_size:512,overlap:64,temporal_size:128,temporal_overlap:32},'Decode SDR video');
  n('decode_audio','LTXVAudioVAEDecode',{samples:r('separate',1),audio_vae:r('audio_vae')},'Decode generated audio');
  n('video','CreateVideo',{images:r('decode'),audio:r('decode_audio'),fps:c.fps,bit_depth:8,color_space:'sRGB',codec:'none'},'Generated SDR video, no alpha');
  n('save','ZuraSaveProRes4444',{video:r('video'),filename_prefix:'zura/paint_vfx/result'},'Save the generated SDR result');
  return applyAvailableAttention(g,info);
}

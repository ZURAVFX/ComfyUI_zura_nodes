// The artist-approved H3 FL2VA recipe. Endpoints are native keyframes, not
// ingredients. Keep the supplied sampler, Turbo adapter and Kitchen backend.
export const FRAME_VIDEO_MODELS={
  model:'minimax_h3_fl2va_pruned_int8_convrot.safetensors',
  text:'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',
  videoVae:'minimax_h3_video_vae_int8_convrot.safetensors',
  audioVae:'minimax_h3_audio_vae_fp32.safetensors',
  lora:'minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors',
};
export const FRAME_LENGTHS=[22,39,56,73,90,107,124];
const ref=id=>[id,0];
export function buildFrameVideoGraph(c){
  if(!c.first?.file||!c.last?.file)throw new Error('Add both a first frame and a last frame.');
  if(!String(c.prompt||'').trim())throw new Error('Describe the transition between your frames.');
  const width=Number(c.width),height=Number(c.height),frames=Number(c.frames),steps=Number(c.steps??8),seed=Number(c.seed??42);
  if(![width,height].every(n=>Number.isInteger(n)&&n>=256&&n<=1536&&n%32===0)||width*height>1344*768)throw new Error('Use dimensions in multiples of 32, up to 1.03 megapixels.');
  if(!FRAME_LENGTHS.includes(frames))throw new Error('Choose a supported H3 clip length.');
  if(!Number.isInteger(steps)||steps<4||steps>40)throw new Error('Sampling steps must be between 4 and 40.');
  if(!Number.isSafeInteger(seed)||seed<0)throw new Error('Seed must be a positive whole number or zero.');
  if(c.audioEnabled&&!c.audio?.file)throw new Error('Add an audio reference, or switch Audio reference off.');
  const g={},node=(id,class_type,inputs)=>{g[id]={class_type,inputs};};
  node('first','LoadImage',{image:c.first.file});node('last','LoadImage',{image:c.last.file});
  node('model','UNETLoader',{unet_name:FRAME_VIDEO_MODELS.model,weight_dtype:'default'});
  node('turbo','LoraLoaderModelOnly',{model:ref('model'),lora_name:FRAME_VIDEO_MODELS.lora,strength_model:1});
  node('attention','ModelAttentionBackend',{model:ref('turbo'),attention:'comfy kitchen attention'});
  node('text','CLIPLoader',{clip_name:FRAME_VIDEO_MODELS.text,type:'minimax',device:'default'});
  node('video_vae','VAELoader',{vae_name:FRAME_VIDEO_MODELS.videoVae});node('audio_vae','VAELoader',{vae_name:FRAME_VIDEO_MODELS.audioVae});
  node('endpoints','MiniMaxH3ImageToVideo',{clip:ref('text'),vae:ref('video_vae'),prompt:c.prompt,width,height,length:frames,first_frame:ref('first'),last_frame:ref('last')});
  let positive=ref('endpoints');
  if(c.audioEnabled){
    node('audio_ref','LoadAudio',{audio:c.audio.file});
    node('audio_guide','MiniMaxH3AddGuide',{positive,latent:['endpoints',1],audio_vae:ref('audio_vae'),audio:ref('audio_ref'),frame_idx:0});positive=ref('audio_guide');
  }
  node('guider','BasicGuider',{model:ref('attention'),conditioning:positive});
  node('scheduler','BasicScheduler',{model:ref('attention'),scheduler:'simple',steps,denoise:1});
  node('sampler','KSamplerSelect',{sampler_name:'res_multistep'});node('noise','RandomNoise',{noise_seed:seed});
  node('sample','SamplerCustomAdvanced',{noise:ref('noise'),guider:ref('guider'),sampler:ref('sampler'),sigmas:ref('scheduler'),latent_image:['endpoints',1]});
  node('decode','VAEDecode',{samples:ref('sample'),vae:ref('video_vae')});node('decode_audio','VAEDecodeAudio',{samples:ref('sample'),vae:ref('audio_vae')});
  node('video','CreateVideo',{images:ref('decode'),audio:ref('decode_audio'),fps:24,bit_depth:8,color_space:'sRGB',codec:'none'});
  node('save','SaveVideo',{video:ref('video'),filename_prefix:'zura/first_last/result',format:'mp4','format.codec':'h264','format.codec.encoding':'auto'});
  return g;
}
export function frameVideoAvailability(info){
  const options=(node,key)=>{const field=info[node]?.input?.required?.[key];return field?.[0]==='COMBO'?field[1]?.options||[]:Array.isArray(field?.[0])?field[0]:[];};
  const names={UNETLoader:['unet_name',FRAME_VIDEO_MODELS.model],CLIPLoader:['clip_name',FRAME_VIDEO_MODELS.text],LoraLoaderModelOnly:['lora_name',FRAME_VIDEO_MODELS.lora]};
  const missing=[];
  for(const [node,[key,file]] of Object.entries(names))if(!options(node,key).includes(file))missing.push(file);
  for(const file of [FRAME_VIDEO_MODELS.videoVae,FRAME_VIDEO_MODELS.audioVae])if(!options('VAELoader','vae_name').includes(file))missing.push(file);
  for(const node of ['ModelAttentionBackend','MiniMaxH3ImageToVideo','MiniMaxH3AddGuide','LoadAudio','LoadImage','BasicGuider','BasicScheduler','KSamplerSelect','RandomNoise','SamplerCustomAdvanced','VAEDecode','VAEDecodeAudio','CreateVideo','SaveVideo'])if(!info[node])missing.push(node);
  if(info.ModelAttentionBackend&&!options('ModelAttentionBackend','attention').includes('comfy kitchen attention'))missing.push('Comfy Kitchen attention');
  return {ready:!missing.length,missing};
}

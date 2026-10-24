// Native Wan 2.2 I2V endpoint recipe: matched high/low models and Lightx2v
// adapters, four Euler/simple steps split 2 + 2, CFG 1 and shift 5.
// The supplied example's subject-specific rotation adapter is not a speedup.
export const WAN_FRAME_VIDEO_MODELS=Object.freeze({
  high:'WAN\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors',
  low:'WAN\\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors',
  text:'umt5_xxl_fp8_e4m3fn_scaled.safetensors',
  vae:'wan_2.1_vae.safetensors',
  highLora:'wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors',
  lowLora:'wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors',
});
export const WAN_FRAME_VIDEO_CAPABILITIES=Object.freeze({
  id:'wan',label:'Wan 2.2',fps:24,dimensionStep:16,frameStep:4,
  minFrames:9,maxFrames:361,defaultFrames:81,defaultSteps:4,minSteps:4,maxSteps:4,
  minDimension:256,maxDimension:1536,maxPixels:1344*768,
  supportsAudioReference:false,generatesAudio:false,
  precision:'FP8 scaled',attention:'comfy kitchen attention',
  nodeTypes:['LoadImage','ImageScale','UNETLoader','LoraLoaderModelOnly','ModelSamplingSD3',
    'ModelAttentionBackend','CLIPLoader','CLIPTextEncode','VAELoader',
    'WanFirstLastFrameToVideo','KSamplerAdvanced','VAEDecode','CreateVideo','SaveVideo'],
});
const negative='Overexposed, blurry, low quality, JPEG artefacts, unwanted text, watermark, distorted anatomy, malformed hands, extra limbs, frozen motion.';
const ref=(id,output=0)=>[id,output];
export function wanFrameVideoDimensions(c){
  const width=Number(c.width),height=Number(c.height),cap=WAN_FRAME_VIDEO_CAPABILITIES;
  if(![width,height].every(n=>Number.isInteger(n)&&n>=cap.minDimension&&n<=cap.maxDimension&&n%cap.dimensionStep===0))throw new Error('Wan dimensions must be multiples of 16, from 256 to 1536 pixels.');
  if(width*height>cap.maxPixels)throw new Error('Choose a smaller size. This Wan endpoint preset supports up to 1.03 megapixels per section.');
  return {width,height};
}
export function buildWanFrameVideoGraph(c){
  if(!c.first?.file)throw new Error('Add a first frame to begin. The last frame is optional.');
  if(!String(c.prompt||'').trim())throw new Error('Describe the video you want to generate.');
  if(c.audioEnabled)throw new Error('Wan 2.2 does not use audio references. Switch Audio reference off or choose H3 or LTX.');
  const {width,height}=wanFrameVideoDimensions(c),cap=WAN_FRAME_VIDEO_CAPABILITIES;
  const frames=Number(c.frames??cap.defaultFrames),steps=Number(c.steps??cap.defaultSteps),seed=Number(c.seed??42);
  if(!Number.isInteger(frames)||frames<cap.minFrames||frames>cap.maxFrames||(frames-1)%cap.frameStep!==0)throw new Error('Choose 9–361 frames in steps of 4 (4n + 1), up to about 15 seconds.');
  if(steps!==4)throw new Error('This Wan Lightx2v preset uses four sampling steps.');
  if(!Number.isSafeInteger(seed)||seed<0)throw new Error('Seed must be a positive whole number or zero.');
  const attention=c.attention||cap.attention;
  if(!['comfy kitchen attention','pytorch attention'].includes(attention))throw new Error('Choose Comfy Kitchen or PyTorch attention for this Wan recipe.');
  const g={},node=(id,class_type,inputs,title)=>{g[id]={class_type,inputs,_meta:{title}};};
  for(const slot of ['first','last'])if(c[slot]?.file){
    node(slot,'LoadImage',{image:c[slot].file},slot==='first'?'First frame':'Last frame');
    node('fit_'+slot,'ImageScale',{image:ref(slot),upscale_method:'lanczos',width,height,crop:'center'},'Fit '+slot+' frame without stretching');
  }
  node('text','CLIPLoader',{clip_name:WAN_FRAME_VIDEO_MODELS.text,type:'wan',device:'default'},'Load Wan text encoder');
  node('positive','CLIPTextEncode',{clip:ref('text'),text:c.prompt},'Describe the video');
  node('negative','CLIPTextEncode',{clip:ref('text'),text:String(c.negativePrompt??negative)},'Avoid visual defects');
  node('vae','VAELoader',{vae_name:WAN_FRAME_VIDEO_MODELS.vae},'Load Wan video VAE');
  node('endpoints','WanFirstLastFrameToVideo',{positive:ref('positive'),negative:ref('negative'),vae:ref('vae'),
    width,height,length:frames,batch_size:1,start_image:ref('fit_first'),...(c.last?.file?{end_image:ref('fit_last')}:{})},'Encode first and optional last frame');
  for(const stage of ['high','low']){
    node(stage+'_model','UNETLoader',{unet_name:WAN_FRAME_VIDEO_MODELS[stage],weight_dtype:c.fastFp8===false?'default':'fp8_e4m3fn_fast'},'Load Wan '+stage+'-noise model');
    node(stage+'_turbo','LoraLoaderModelOnly',{model:ref(stage+'_model'),lora_name:WAN_FRAME_VIDEO_MODELS[stage+'Lora'],strength_model:1},'Wan '+stage+'-noise Lightx2v 4-step');
    node(stage+'_shift','ModelSamplingSD3',{model:ref(stage+'_turbo'),shift:5},'Wan '+stage+'-noise shift');
    node(stage+'_attention','ModelAttentionBackend',{model:ref(stage+'_shift'),attention},'Wan '+stage+'-noise attention');
    node(stage+'_sample','KSamplerAdvanced',{model:ref(stage+'_attention'),add_noise:stage==='high'?'enable':'disable',noise_seed:seed,
      steps,cfg:1,sampler_name:'euler',scheduler:'simple',positive:ref('endpoints'),negative:ref('endpoints',1),
      latent_image:stage==='high'?ref('endpoints',2):ref('high_sample'),start_at_step:stage==='high'?0:2,
      end_at_step:stage==='high'?2:4,return_with_leftover_noise:stage==='high'?'enable':'disable'},
    stage==='high'?'Generate motion · high-noise steps 1–2':'Refine detail · low-noise steps 3–4');
  }
  const decodeInputs={samples:ref('low_sample'),vae:ref('vae')};
  // Full decode preserves the supplied workflow. Native VAEDecode can fall
  // back after OOM; explicit tiling is opt-in because it can alter joins.
  if(c.lowMemoryDecode)node('decode','VAEDecodeTiled',{...decodeInputs,tile_size:512,overlap:64,temporal_size:64,temporal_overlap:8},'Decode video in low-memory tiles');
  else node('decode','VAEDecode',decodeInputs,'Decode Wan video');
  node('video','CreateVideo',{images:ref('decode'),fps:cap.fps,bit_depth:8,color_space:'sRGB',codec:'none'},'Assemble silent video');
  node('save','SaveVideo',{video:ref('video'),filename_prefix:'zura/first_last/wan',format:'mp4','format.codec':'h264','format.codec.encoding':'auto'},'Save Wan video');
  return g;
}
export function wanFrameVideoAvailability(info,c={}){
  const options=(node,key)=>{const field=info[node]?.input?.required?.[key];return field?.[0]==='COMBO'?field[1]?.options||[]:Array.isArray(field?.[0])?field[0]:[];};
  const missing=[];
  for(const node of [...WAN_FRAME_VIDEO_CAPABILITIES.nodeTypes,...(c.lowMemoryDecode?['VAEDecodeTiled']:[])])if(!info[node])missing.push(node);
  for(const [node,key,files] of [
    ['UNETLoader','unet_name',[WAN_FRAME_VIDEO_MODELS.high,WAN_FRAME_VIDEO_MODELS.low]],
    ['CLIPLoader','clip_name',[WAN_FRAME_VIDEO_MODELS.text]],['VAELoader','vae_name',[WAN_FRAME_VIDEO_MODELS.vae]],
    ['LoraLoaderModelOnly','lora_name',[WAN_FRAME_VIDEO_MODELS.highLora,WAN_FRAME_VIDEO_MODELS.lowLora]],
  ])for(const file of files)if(!options(node,key).includes(file))missing.push(file);
  if(info.ModelAttentionBackend&&!options('ModelAttentionBackend','attention').includes(c.attention||WAN_FRAME_VIDEO_CAPABILITIES.attention))missing.push('Comfy Kitchen attention');
  if(info.UNETLoader&&c.fastFp8!==false&&!options('UNETLoader','weight_dtype').includes('fp8_e4m3fn_fast'))missing.push('Fast FP8 model loading');
  return {ready:!missing.length,missing:[...new Set(missing)]};
}

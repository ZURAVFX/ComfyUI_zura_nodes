// LTX 2.5 native endpoint conditioning, based on Lightricks' distilled recipe.
// INT8 + convrot checkpoints are intended for ComfyUI. No cross-family LoRA.
export const LTX_FRAME_VIDEO_MODELS=Object.freeze({
  model:'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
  text:'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
  videoVae:'ltx-2.5-video-vae-conv-bf16.safetensors',
  audioVae:'ltx-2.5-audio-vae-bf16.safetensors',
  latentUpscaler:'ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors',
});
export const LTX_DISTILLED_SIGMAS='1.0,0.99375,0.9875,0.98125,0.975,0.909375,0.725,0.421875,0.0';
export const LTX_FRAME_VIDEO_CAPABILITIES=Object.freeze({
  id:'ltx',label:'LTX 2.5',fps:24,dimensionStep:32,frameStep:8,minFrames:9,maxFrames:361,defaultFrames:49,
  defaultSteps:8,minSteps:8,maxSteps:8,supportsAudioReference:true,audioReferenceRole:'performance',generatesAudio:true,
  maxPixels:1344*768,
  nodeTypes:['LoadImage','ImageScale','UNETLoader','ModelAttentionBackend','CLIPLoader','CLIPTextEncode','VAELoader',
    'LTXVConditioning','EmptyLTXVLatentVideo','LTXVPreprocess','LTXVAddGuide','LTXVCropGuides','LTXVEmptyLatentAudio',
    'LoadAudio','TrimAudioDuration','EmptyAudio','AudioConcat','LTXVAudioVAEEncode','SolidMask','SetLatentNoiseMask','LTXVConcatAVLatent',
    'CFGGuider','KSamplerSelect','RandomNoise','ManualSigmas','SamplerCustomAdvanced','LTXVSeparateAVLatent',
    'VAEDecodeTiled','LTXVAudioVAEDecode','CreateVideo','SaveVideo'],
});
const ref=(id,index=0)=>[id,index];
export function buildLtxFrameVideoGraph(c){
  if(!c.first?.file)throw new Error('Add a first frame. The last frame is optional.');
  if(!String(c.prompt||'').trim())throw new Error('Describe the video you want to generate.');
  const width=Number(c.width),height=Number(c.height),frames=Number(c.frames),steps=Number(c.steps??8),seed=Number(c.seed??42);
  if(![width,height].every(n=>Number.isInteger(n)&&n>=256&&n<=1536&&n%32===0))throw new Error('Use dimensions in 32-pixel increments, from 256 to 1536 pixels.');
  if(width*height>LTX_FRAME_VIDEO_CAPABILITIES.maxPixels)throw new Error('Choose a size up to 1.03 megapixels for this LTX recipe.');
  if(!Number.isInteger(frames)||frames<9||frames>LTX_FRAME_VIDEO_CAPABILITIES.maxFrames||(frames-1)%8!==0)throw new Error('LTX needs 8n + 1 frames, from 9 to 361 (about 15 seconds).');
  if(steps!==8)throw new Error('The LTX 2.5 distilled model uses its fixed 8-step schedule.');
  if(c.fps!=null&&Number(c.fps)!==24)throw new Error('This LTX recipe runs at 24 fps.');
  if(!Number.isSafeInteger(seed)||seed<0)throw new Error('Seed must be a positive whole number or zero.');
  if(c.audioEnabled&&!c.audio?.file)throw new Error('Add an audio reference, or switch Audio reference off.');
  const audioStart=Number(c.audioStart??0);
  if(!Number.isFinite(audioStart)||audioStart<0)throw new Error('Audio start must be zero or a positive number of seconds.');
  const fast=c.fast===true;
  // LTX samples on a 32-pixel grid. Pad the requested output to 64 before
  // halving, then crop back after upscaling so 32-grid sizes stay exact.
  const paddedWidth=fast?Math.ceil(width/64)*64:width,paddedHeight=fast?Math.ceil(height/64)*64:height;
  const sampleWidth=fast?paddedWidth/2:width,sampleHeight=fast?paddedHeight/2:height;
  const g={},node=(id,class_type,inputs,title)=>{g[id]={class_type,inputs,_meta:{title:title||class_type}};};
  node('model','UNETLoader',{unet_name:LTX_FRAME_VIDEO_MODELS.model,weight_dtype:'default'},'Load LTX 2.5 distilled INT8');
  node('attention','ModelAttentionBackend',{model:ref('model'),attention:'comfy kitchen attention'},'Comfy Kitchen attention');
  node('text','CLIPLoader',{clip_name:LTX_FRAME_VIDEO_MODELS.text,type:'ltxv',device:'default'},'Load Gemma4 INT8');
  node('video_vae','VAELoader',{vae_name:LTX_FRAME_VIDEO_MODELS.videoVae},'Load fast convolutional video VAE');
  node('audio_vae','VAELoader',{vae_name:LTX_FRAME_VIDEO_MODELS.audioVae});
  node('positive','CLIPTextEncode',{clip:ref('text'),text:c.prompt},'Encode video prompt');
  node('negative','CLIPTextEncode',{clip:ref('text'),text:''});
  node('conditioning','LTXVConditioning',{positive:ref('positive'),negative:ref('negative'),frame_rate:24});
  node('empty_video','EmptyLTXVLatentVideo',{width:sampleWidth,height:sampleHeight,length:frames,batch_size:1});
  let positive=ref('conditioning'),negative=ref('conditioning',1),latent=ref('empty_video');
  for(const [id,image,frame_idx] of [['first',c.first,0],['last',c.last,frames-1]]){
    if(!image?.file)continue;
    node(id,'LoadImage',{image:image.file},`Load ${id} frame`);
    node(`fit_${id}`,'ImageScale',{image:ref(id),upscale_method:'lanczos',width,height,crop:'center'},`Fit ${id} frame without stretching`);
    let guideImage=ref(`fit_${id}`);
    if(fast){
      if(paddedWidth!==width||paddedHeight!==height){
        node(`pad_${id}`,'ImagePadForOutpaint',{image:guideImage,left:0,top:0,right:paddedWidth-width,bottom:paddedHeight-height,feathering:0},`Pad ${id} frame for the model grid`);
        guideImage=ref(`pad_${id}`);
      }
      node(`small_${id}`,'ImageScale',{image:guideImage,upscale_method:'lanczos',width:sampleWidth,height:sampleHeight,crop:'disabled'},`Scale ${id} guide to sampling size`);
      guideImage=ref(`small_${id}`);
    }
    node(`preprocess_${id}`,'LTXVPreprocess',{image:guideImage,img_compression:18});
    node(`guide_${id}`,'LTXVAddGuide',{positive,negative,vae:ref('video_vae'),latent,image:ref(`preprocess_${id}`),frame_idx,strength:1},`Anchor ${id} frame at frame ${frame_idx+1}`);
    positive=ref(`guide_${id}`);negative=ref(`guide_${id}`,1);latent=ref(`guide_${id}`,2);
  }
  let audioLatent;
  if(c.audioEnabled){
    node('audio_ref','LoadAudio',{audio:c.audio.file},'Load reference soundtrack');
    node('audio_window','TrimAudioDuration',{audio:ref('audio_ref'),start_index:audioStart,duration:frames/24},'Select reference soundtrack');
    node('audio_silence','EmptyAudio',{duration:frames/24,sample_rate:48000,channels:2},'Extend short reference with silence');
    node('audio_padded','AudioConcat',{audio1:ref('audio_window'),audio2:ref('audio_silence'),direction:'after'},'Keep the original audio followed by silence');
    node('trim_audio','TrimAudioDuration',{audio:ref('audio_padded'),start_index:0,duration:frames/24},'Match reference soundtrack to output length');
    node('encode_audio','LTXVAudioVAEEncode',{audio:ref('trim_audio'),audio_vae:ref('audio_vae')});
    node('freeze_audio_mask','SolidMask',{value:0,width:1024,height:1024});
    node('freeze_audio','SetLatentNoiseMask',{samples:ref('encode_audio'),mask:ref('freeze_audio_mask')},'Preserve reference audio tokens');
    audioLatent=ref('freeze_audio');
  }else{
    node('empty_audio','LTXVEmptyLatentAudio',{frames_number:frames,frame_rate:24,batch_size:1,audio_vae:ref('audio_vae')});
    audioLatent=ref('empty_audio');
  }
  node('av_latent','LTXVConcatAVLatent',{video_latent:latent,audio_latent:audioLatent});
  node('guider','CFGGuider',{model:ref('attention'),positive,negative,cfg:1});
  node('sigmas','ManualSigmas',{sigmas:LTX_DISTILLED_SIGMAS},'Official distilled 8-step schedule');
  node('sampler','KSamplerSelect',{sampler_name:'euler_ancestral'});
  node('noise','RandomNoise',{noise_seed:seed});
  node('sample','SamplerCustomAdvanced',{noise:ref('noise'),guider:ref('guider'),sampler:ref('sampler'),sigmas:ref('sigmas'),latent_image:ref('av_latent')},'Generate video and audio: 8 steps');
  node('separate','LTXVSeparateAVLatent',{av_latent:ref('sample')});
  node('crop_guides','LTXVCropGuides',{positive,negative,latent:ref('separate')},'Remove conditioning frames');
  let videoLatent=ref('crop_guides',2);
  if(fast){
    node('upscale_model','LatentUpscaleModelLoader',{model_name:LTX_FRAME_VIDEO_MODELS.latentUpscaler},'Load LTX 2.5 spatial upscaler');
    node('upscale','LTXVLatentUpsampler',{samples:videoLatent,upscale_model:ref('upscale_model'),vae:ref('video_vae')},'Upscale sampled video');
    videoLatent=ref('upscale');
  }
  node('decode','VAEDecodeTiled',{samples:videoLatent,vae:ref('video_vae'),tile_size:512,overlap:64,temporal_size:128,temporal_overlap:32},'Decode video');
  let videoImages=ref('decode');
  if(fast&&(paddedWidth!==width||paddedHeight!==height)){
    node('crop_output','ImageCrop',{image:videoImages,width,height,x:0,y:0},'Restore requested output size');
    videoImages=ref('crop_output');
  }
  if(!c.audioEnabled)node('decode_audio','LTXVAudioVAEDecode',{samples:ref('separate',1),audio_vae:ref('audio_vae')},'Decode generated soundtrack');
  node('video','CreateVideo',{images:videoImages,audio:ref(c.audioEnabled?'trim_audio':'decode_audio'),fps:24,bit_depth:8,color_space:'sRGB',codec:'none'});
  node('save','SaveVideo',{video:ref('video'),filename_prefix:'zura/first_last/ltx/result',format:'mp4','format.codec':'h264','format.codec.encoding':'auto'},'Save LTX video');
  return g;
}
export const LTX_FRAME_VIDEO_FAST_NODES=Object.freeze(['LatentUpscaleModelLoader','LTXVLatentUpsampler','ImagePadForOutpaint','ImageCrop']);
export function ltxFrameVideoAvailability(info={},config={}){
  const options=(node,key)=>{const field=info[node]?.input?.required?.[key];return field?.[0]==='COMBO'?field[1]?.options||[]:Array.isArray(field?.[0])?field[0]:[];};
  const missing=[];
  for(const node of LTX_FRAME_VIDEO_CAPABILITIES.nodeTypes)if(!info[node])missing.push(node);
  for(const [node,key,file] of [['UNETLoader','unet_name',LTX_FRAME_VIDEO_MODELS.model],['CLIPLoader','clip_name',LTX_FRAME_VIDEO_MODELS.text],['VAELoader','vae_name',LTX_FRAME_VIDEO_MODELS.videoVae],['VAELoader','vae_name',LTX_FRAME_VIDEO_MODELS.audioVae]])if(!options(node,key).includes(file))missing.push(file);
  if(config.fast===true){
    for(const node of LTX_FRAME_VIDEO_FAST_NODES)if(!info[node])missing.push(node);
    if(info.LatentUpscaleModelLoader&&!options('LatentUpscaleModelLoader','model_name').includes(LTX_FRAME_VIDEO_MODELS.latentUpscaler))missing.push(LTX_FRAME_VIDEO_MODELS.latentUpscaler);
  }
  if(info.ModelAttentionBackend&&!options('ModelAttentionBackend','attention').includes('comfy kitchen attention'))missing.push('Comfy Kitchen attention');
  if(info.KSamplerSelect&&!options('KSamplerSelect','sampler_name').includes('euler_ancestral'))missing.push('Euler ancestral sampler');
  return {ready:missing.length===0,missing:[...new Set(missing)]};
}

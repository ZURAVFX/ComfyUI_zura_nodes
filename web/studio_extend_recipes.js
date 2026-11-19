import {resolutionSize} from './studio_resolution.js';

export const EXTEND_DEFAULT='h3_extend_turbo';
export const EXTEND_MODELS={
  h3_extend_turbo:{label:'MiniMax H3 · Turbo',steps:6},
  h3_extend_quality:{label:'MiniMax H3 · Quality',steps:40},
};
export const EXTEND_SETTINGS={seconds:2,context:2,megapixels:.25,steps:6,seed:44,turboStrength:.6,audio:true};
const models={
  model:['UNETLoader','unet_name','minimax_h3_ref2va_pruned_int8_convrot.safetensors'],
  clip:['CLIPLoader','clip_name','qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'],
  vae:['VAELoader','vae_name','minimax_h3_video_vae_int8_convrot.safetensors'],
  audioVae:['VAELoader','vae_name','minimax_h3_audio_vae_fp32.safetensors'],
  turbo:['LoraLoaderModelOnly','lora_name','minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors'],
};
const nodes=['LoadVideo','Video Slice','ZuraH3ExtendContext','ImageScale','VAEEncode','VAEEncodeAudio',
  'MiniMaxH3ReferenceToVideo','ZuraH3ExtendLatent','RandomNoise','KSamplerSelect','BasicScheduler','BasicGuider',
  'SamplerCustomAdvanced','VAEDecode','VAEDecodeAudio','ZuraH3ExtendDelivery','ZuraSaveProRes4444'];
const optionList=(info,node,key)=>{
  const spec=info[node]?.input?.required?.[key];
  return Array.isArray(spec?.[0])?spec[0]:spec?.[1]?.options||[];
};
function installed(info,mode){
  return Object.fromEntries(Object.entries(models).filter(([id])=>id!=='turbo'||mode===EXTEND_DEFAULT)
    .map(([id,[node,key,file]])=>[id,optionList(info,node,key).find(name=>String(name).split(/[\\/]/).pop()===file)]));
}
export function extendAvailability(info,mode=EXTEND_DEFAULT){
  const choices=installed(info,mode);
  const missing=[...new Set([...nodes,...Object.keys(choices).map(key=>models[key][0])])].filter(node=>!info[node]);
  for(const [id,choice] of Object.entries(choices))if(!choice)missing.push(models[id][2]);
  if(info.KSamplerSelect&&!optionList(info,'KSamplerSelect','sampler_name').includes('er_sde'))missing.push('ER-SDE sampler');
  return {ready:!missing.length,missing};
}

const lattice=n=>Math.max(5,Math.ceil((n-5)/17)*17+5);
export function extendPlan(config){
  const {width,height,seconds,context,megapixels,steps,seed,turboStrength}=config;
  if(![width,height].every(n=>Number.isInteger(n)&&n>0))throw Error('Add a video to extend.');
  if(!Number.isFinite(seconds)||seconds<.25||seconds>10)throw Error('Extend by 0.25 to 10 seconds.');
  if(!Number.isFinite(context)||context<.25||context>4.25)throw Error('Use 0.25 to 4.25 seconds of ending context.');
  if(!Number.isFinite(megapixels)||megapixels<.16||megapixels>1.05)throw Error('Choose a processing size from 0.16 to 1.05 megapixels.');
  if(!Number.isSafeInteger(seed)||seed<0||!Number.isInteger(steps)||steps<4||steps>50||
     !Number.isFinite(turboStrength)||turboStrength<0||turboStrength>1)throw Error('Check the seed, sampling steps and Turbo strength.');
  const size=resolutionSize(width/height,megapixels,{min:128,max:1536,maxPixels:1_050_000});
  const contextFrames=lattice(Math.round(context*24));
  const frames=lattice(contextFrames+Math.ceil(seconds*24));
  return {...size,contextFrames,frames};
}
export function buildExtendGraph(config,info){
  const {file,start=0,duration=0,model,prompt='',seed,steps,turboStrength,seconds,audio}=config;
  if(typeof file!=='string'||!file||file.includes('\\')||file.includes(':')||file.split('/').some(part=>!part||part==='.'||part==='..'))
    throw Error('Add a video to extend.');
  if(![start,duration].every(Number.isFinite)||start<0||duration<0)throw Error('Choose a valid clip range.');
  if(!EXTEND_MODELS[model]||!extendAvailability(info,model).ready)throw Error('Complete MiniMax H3 setup before extending.');
  const {width,height,contextFrames,frames}=extendPlan(config),weights=installed(info,model);
  const graph={};
  const node=(id,class_type,inputs,title)=>{
    graph[id]={class_type,inputs,_meta:{title}};
    return [id,0];
  };
  const source=node('source','LoadVideo',{file},'Reading source video');
  const selected=start||duration?node('trim','Video Slice',{video:source,start_time:start,duration,strict_duration:false},
    'Reading the selected cut'):source;
  const context=node('context','ZuraH3ExtendContext',{video:selected,context_frames:contextFrames},'Preparing the ending context');
  const guide=node('guide','ImageScale',{image:context,width,height,upscale_method:'lanczos',crop:'disabled'},'Sizing the motion reference');
  const vae=node('vae','VAELoader',{vae_name:weights.vae},'Loading the H3 video VAE');
  const audioVae=node('audio_vae','VAELoader',{vae_name:weights.audioVae},'Loading the H3 audio VAE');
  const clip=node('text','CLIPLoader',{clip_name:weights.clip,type:'minimax',device:'default'},'Loading the local text encoder');
  const base=node('model','UNETLoader',{unet_name:weights.model,weight_dtype:'default'},'Loading MiniMax H3');
  const modelLink=weights.turbo?node('turbo','LoraLoaderModelOnly',{model:base,lora_name:weights.turbo,strength_model:turboStrength},
    'Applying the continuation Turbo adapter'):base;
  const description=prompt.trim()||'Continue the same subject, framing, lighting, motion and ambience without a cut.';
  const conditioning=node('reference','MiniMaxH3ReferenceToVideo',{
    clip,vae,audio_vae:audioVae,width,height,length:frames,ref_image_size:'match',
    prompt:'Continue <Video 1> directly from the final frame, keeping its camera motion and direction. '+description,
    'ref_videos.ref_video_0':guide,'ref_video_audios.ref_video_audio_0':['context',1],
  },'Conditioning on the ending picture and audio');
  const encoded=node('encode','VAEEncode',{pixels:guide,vae},'Encoding the ending frames');
  const audioEncoded=node('encode_audio','VAEEncodeAudio',{audio:['context',1],vae:audioVae},'Encoding the ending audio');
  const latent=node('prefix','ZuraH3ExtendLatent',{latent:['reference',1],ending_video:encoded,
    ending_audio:audioEncoded,context_frames:contextFrames},'Protecting the encoded context');
  const noise=node('noise','RandomNoise',{noise_seed:seed},'Setting the seed');
  const sampler=node('sampler','KSamplerSelect',{sampler_name:'er_sde'},'Selecting ER-SDE sampling');
  const sigmas=node('sigmas','BasicScheduler',{model:modelLink,scheduler:'beta',steps,denoise:1},'Preparing the continuation schedule');
  const guider=node('guider','BasicGuider',{model:modelLink,conditioning},'Guiding the continuation');
  const sample=node('sample','SamplerCustomAdvanced',{noise,sampler,sigmas,guider,latent_image:latent},'Generating the continuation');
  const generated=node('decode','VAEDecode',{vae,samples:sample},'Decoding the continuation');
  const delivery={source:['context',2],generated,context_frames:contextFrames,seconds};
  if(audio)delivery.generated_audio=node('decode_audio','VAEDecodeAudio',{samples:sample,vae:audioVae},'Decoding generated audio');
  const video=node('delivery','ZuraH3ExtendDelivery',delivery,'Joining the tail to the original cut');
  node('save','ZuraSaveProRes4444',{video,filename_prefix:'ZURA STUDIO/extend/H3_Extended'},'Saving the extended clip');
  node('save_tail','ZuraSaveProRes4444',{video:['delivery',1],filename_prefix:'ZURA STUDIO/extend/H3_Tail'},'Saving the continuation only');
  return graph;
}

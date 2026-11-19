const MODELS = [
  ['UNETLoader','unet_name','relayvsr_x2_lightx2v_int8_convrot.safetensors'],
  ['VAELoader','vae_name','relayvsr_flash_vae_x2_fp32.safetensors'],
];
const REQUIRED = ['LoadVideo','Video Slice','GetVideoComponents','RelayVSRConditioning',
  'VSRDecode','KSampler','CreateVideo','ZuraSaveProRes4444',...MODELS.map(([type])=>type)];
const basename=value=>String(value).split(/[\\/]/).pop();
function installedModel(info,type,key,name){
  const field=info[type]?.input?.required?.[key];
  const choices=Array.isArray(field?.[0])?field[0]:field?.[1]?.options||[];
  return choices.find(choice=>basename(choice)===name);
}
export function upscaleAvailability(info){
  const missing=REQUIRED.filter(type=>!info[type]);
  for(const [type,key,name] of MODELS)if(!installedModel(info,type,key,name))missing.push(name);
  return {ready:missing.length===0,missing};
}

export function buildUpscaleGraph(config,info){
  const {file,start=0,duration=0,detail=1}=config;
  if(typeof file!=='string'||!file||file.includes('\\')||file.includes(':')||file.split('/').some(part=>!part||part==='.'||part==='..'))throw Error('Add a video to upscale.');
  if(![start,duration,detail].every(Number.isFinite)||start<0||duration<0||detail<0||detail>1)throw Error('Choose a valid clip range and detail amount.');
  const availability=upscaleAvailability(info);
  if(!availability.ready)throw Error('Complete Relay VSR setup before upscaling.');
  const [model,vae]=MODELS.map(args=>installedModel(info,...args));
  const graph={};
  const add=(id,class_type,inputs,title)=>{
    graph[id]={class_type,inputs,_meta:{title}};
    return [id,0];
  };
  const loaded=add('source','LoadVideo',{file},'Reading source video');
  const selected=start||duration?add('trim','Video Slice',{video:loaded,start_time:start,duration,strict_duration:false},'Reading the selected clip'):loaded;
  const images=add('components','GetVideoComponents',{video:selected},'Separating picture and audio');
  const diffusion=add('model','UNETLoader',{unet_name:model,weight_dtype:'default'},'Loading Relay VSR 2×');
  const decoder=add('vae','VAELoader',{vae_name:vae},'Loading the matched 2× decoder');
  const conditioning=add('conditioning','RelayVSRConditioning',{model:diffusion,images},'Preparing source keyframes');
  const samples=add('sample','KSampler',{model:diffusion,positive:conditioning,negative:conditioning,latent_image:['conditioning',1],seed:42,steps:1,cfg:1,sampler_name:'euler',scheduler:'simple',denoise:1},'Restoring detail in keyframes');
  const upscaled=add('decode','VSRDecode',{vae:decoder,samples,images,detail},'Upscaling every frame');
  const video=add('video','CreateVideo',{images:upscaled,audio:['components',1],fps:['components',2]},'Restoring source frame rate and audio');
  add('save','ZuraSaveProRes4444',{video,filename_prefix:'ZURA STUDIO/upscale/RelayVSR_2x'},'Writing ProRes master and playback preview');
  return graph;
}

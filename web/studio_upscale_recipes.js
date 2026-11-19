export const UPSCALE_MODELS = {
  relayvsr_x2: {
    label: 'Relay VSR',
    model: 'relayvsr_x2_lightx2v_int8_convrot.safetensors',
    vae: 'relayvsr_flash_vae_x2_fp32.safetensors',
    nodes: ['RelayVSRConditioning','VSRDecode'],
    output: 'RelayVSR_2x',
  },
  seedvr2_7b_x2: {
    label: 'SeedVR2 7B INT8',
    model: 'seedvr2_7b_int8_convrot.safetensors',
    vae: 'seedvr2_ema_vae_fp16.safetensors',
    vaeAlias: 'ema_vae_fp16.safetensors',
    nodes: ['ResizeImageMaskNode','SeedVR2Preprocess','VAEEncodeTiled','SeedVR2TemporalChunk',
      'SeedVR2Conditioning','SeedVR2TemporalMerge','VAEDecodeTiled','SeedVR2PostProcessing'],
    output: 'SeedVR2_7B_2x',
  },
};
export const DEFAULT_UPSCALE_MODEL = 'relayvsr_x2';
const REQUIRED = ['LoadVideo','Video Slice','GetVideoComponents','UNETLoader','VAELoader',
  'KSampler','CreateVideo','ZuraSaveProRes4444'];
const basename=value=>String(value).split(/[\\/]/).pop();
function installedModel(info,type,key,name){
  const field=info[type]?.input?.required?.[key];
  const choices=Array.isArray(field?.[0])?field[0]:field?.[1]?.options||[];
  return choices.find(choice=>basename(choice)===name);
}
function installedWeights(info,recipe){
  return [
    installedModel(info,'UNETLoader','unet_name',recipe.model),
    installedModel(info,'VAELoader','vae_name',recipe.vae)||
      (recipe.vaeAlias&&installedModel(info,'VAELoader','vae_name',recipe.vaeAlias)),
  ];
}
export function upscaleAvailability(info,model=DEFAULT_UPSCALE_MODEL){
  const recipe=UPSCALE_MODELS[model];
  const missing=[...REQUIRED,...recipe.nodes].filter(type=>!info[type]);
  const [diffusion,vae]=installedWeights(info,recipe);
  if(!diffusion)missing.push(recipe.model);
  if(!vae)missing.push(recipe.vae);
  return {ready:missing.length===0,missing};
}

export function buildUpscaleGraph(config,info){
  const {file,start=0,duration=0,detail=1,model:mode=DEFAULT_UPSCALE_MODEL}=config;
  const recipe=UPSCALE_MODELS[mode];
  if(typeof file!=='string'||!file||file.includes('\\')||file.includes(':')||file.split('/').some(part=>!part||part==='.'||part==='..'))throw Error('Add a video to upscale.');
  if(![start,duration,detail].every(Number.isFinite)||start<0||duration<0||detail<0||detail>1)throw Error('Choose a valid clip range and detail amount.');
  if(!recipe)throw Error('Choose an upscale model.');
  if(!upscaleAvailability(info,mode).ready)throw Error(`Complete ${recipe.label} setup before upscaling.`);
  const [model,vae]=installedWeights(info,recipe);
  const graph={};
  const add=(id,class_type,inputs,title)=>{
    graph[id]={class_type,inputs,_meta:{title}};
    return [id,0];
  };
  const loaded=add('source','LoadVideo',{file},'Reading source video');
  const selected=start||duration?add('trim','Video Slice',{video:loaded,start_time:start,duration,strict_duration:false},'Reading the selected clip'):loaded;
  const images=add('components','GetVideoComponents',{video:selected},'Separating picture and audio');
  const diffusion=add('model','UNETLoader',{unet_name:model,weight_dtype:'default'},`Loading ${recipe.label}`);
  const decoder=add('vae','VAELoader',{vae_name:vae},'Loading the matching VAE');
  const sample=(positive,negative,latent)=>add('sample','KSampler',{
    model:diffusion,positive,negative,latent_image:latent,seed:42,steps:1,cfg:1,
    sampler_name:'euler',scheduler:'simple',denoise:1,
  },'Restoring detail');
  let upscaled;
  if(mode==='seedvr2_7b_x2'){
    // Follow ComfyUI's SeedVR2 video blueprint with automatic temporal chunks.
    const tiles={vae:decoder,tile_size:512,overlap:128,temporal_size:64,temporal_overlap:8};
    const resized=add('resize','ResizeImageMaskNode',{
      input:images,resize_type:'scale by multiplier','resize_type.multiplier':2,scale_method:'lanczos',
    },'Sizing the source to 2×');
    const prepared=add('preprocess','SeedVR2Preprocess',{resized_images:resized},'Preparing SeedVR2 input');
    const encoded=add('encode','VAEEncodeTiled',{pixels:prepared,...tiles},'Encoding source frames');
    const chunks=add('chunks','SeedVR2TemporalChunk',{
      latent:encoded,chunking_mode:'auto',temporal_overlap:0,
    },'Splitting the clip for available GPU memory');
    const conditioning=add('conditioning','SeedVR2Conditioning',{
      model:diffusion,vae_conditioning:chunks,
    },'Conditioning SeedVR2');
    const samples=sample(conditioning,['conditioning',1],chunks);
    const merged=add('merge','SeedVR2TemporalMerge',{
      latents:samples,temporal_overlap:['chunks',1],
    },'Joining the upscaled segments');
    const decoded=add('decode','VAEDecodeTiled',{samples:merged,...tiles},'Decoding the upscaled clip');
    upscaled=add('postprocess','SeedVR2PostProcessing',{
      images:decoded,original_resized_images:resized,color_correction_method:'none',
    },'Restoring the source geometry and frame count');
  }else{
    const conditioning=add('conditioning','RelayVSRConditioning',{model:diffusion,images},'Preparing source keyframes');
    const samples=sample(conditioning,conditioning,['conditioning',1]);
    upscaled=add('decode','VSRDecode',{vae:decoder,samples,images,detail},'Upscaling every frame');
  }
  const video=add('video','CreateVideo',{images:upscaled,audio:['components',1],fps:['components',2]},'Restoring source frame rate and audio');
  add('save','ZuraSaveProRes4444',{video,filename_prefix:'ZURA STUDIO/upscale/'+recipe.output},'Writing ProRes master and playback preview');
  return graph;
}

import {LTX_DISTILLED_SIGMAS,LTX_FRAME_VIDEO_MODELS as LTX} from './ltx_frame_video_recipes.js';

export const RTX_UPSCALE='nvidia_rtx';
export const RTX_NODE='RTXVideoSuperResolution';
const LTX_NODES=['GetImageSize','GenjHoldToModelLength','ImageScale','ImageFromBatch','VAEDecodeTiled'];
export const UPSCALE_MODELS = {
  [RTX_UPSCALE]: {
    label:'NVIDIA RTX Super Resolution', nodes:[RTX_NODE], output:'NVIDIA_RTX',
  },
  relayvsr_x2: {
    label: 'RelayVSR · 2× INT8', scale:2,
    model: 'relayvsr_x2_lightx2v_int8_convrot.safetensors',
    vae: 'relayvsr_flash_vae_x2_fp32.safetensors',
    nodes: ['RelayVSRConditioning','VSRDecode'],
    output: 'RelayVSR_2x',
  },
  relayvsr_x2_bf16: {
    label:'RelayVSR · 2× BF16', scale:2,
    loader:'ZuraRelayVSRLoadBF16',
    model:'relayvsr_lightx2v_bf16_original.safetensors',
    vae:'relayvsr_flash_vae_x2_fp32.safetensors',
    nodes:['RelayVSRConditioning','VSRDecode'],
    output:'RelayVSR_2x_BF16',
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
  ltx25_latent_x2: {
    label: 'LTX 2.5 · Latent 2×', vae: LTX.videoVae,
    weights: [['LatentUpscaleModelLoader','model_name',LTX.latentUpscaler]],
    nodes: [...LTX_NODES,'VAEEncodeTiled','LTXVLatentUpsampler'], output:'LTX25_Latent_2x',
  },
  ltx25_tiled_x2: {
    label: 'LTX 2.5 · Refine (SDR)', textGuidance:true, vae:'ltx-2.5-video-vae-bf16.safetensors',
    weights: [['UNETLoader','unet_name',LTX.model],['CLIPLoader','clip_name',LTX.text],
      ['LTXICLoRALoaderModelOnly','lora_name','ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors']],
    nodes:[...LTX_NODES,'CLIPTextEncode','LTXVConditioning','EmptyLTXVLatentVideo',
      'LTXAddVideoICLoRAGuide','LTXVTiledFusionSampler','KSamplerSelect','ManualSigmas'],
    output:'LTX25_Refine',
  },
};
UPSCALE_MODELS.ltx25_hdr_refine_x2 = {
  label:'LTX 2.5 · Refine (HDR)',
  textGuidance:true,
  hdr:true,
  vae:UPSCALE_MODELS.ltx25_tiled_x2.vae,
  weights:[...UPSCALE_MODELS.ltx25_tiled_x2.weights,['LatentUpscaleModelLoader','model_name',LTX.latentUpscaler]],
  nodes:[...UPSCALE_MODELS.ltx25_tiled_x2.nodes
    .filter(node=>!['GetImageSize','GenjHoldToModelLength'].includes(node)),
    'LTXVLatentUpsampler','LTXVVAEForceFloat32','ImageCrop','ZuraHDRLoadNativeSource',
    'ZuraHDRNativePrepare','ZuraHDRSaveProRes4444','ZuraHDRLoadAudioRange',
    'ZuraHDRPackageACEScct','ZuraHDRSDRPreview','ZuraHDRSaveExactRate'],
};
export const DEFAULT_UPSCALE_MODEL = 'relayvsr_x2';
const REQUIRED = ['LoadVideo','Video Slice','GetVideoComponents','CreateVideo','ZuraSaveProRes4444'];
const basename=value=>String(value).split(/[\\/]/).pop();
function installedModel(info,type,key,name){
  const field=info[type]?.input?.required?.[key];
  const choices=Array.isArray(field?.[0])?field[0]:field?.[1]?.options||[];
  return choices.find(choice=>basename(choice)===name);
}
function weightRequirements(recipe){
  if(!recipe.vae)return [];
  return [['VAELoader','vae_name',recipe.vae,recipe.vaeAlias],
    ...(recipe.weights||[[recipe.loader||'UNETLoader','unet_name',recipe.model]])];
}
function installedWeights(info,recipe){
  return weightRequirements(recipe).map(([node,key,file,alias])=>
    installedModel(info,node,key,file)||(alias&&installedModel(info,node,key,alias)));
}
export function upscaleAvailability(info,model=DEFAULT_UPSCALE_MODEL){
  const recipe=UPSCALE_MODELS[model];
  const nodes=model===RTX_UPSCALE?[]:recipe.weights?recipe.weights.map(([node])=>node):[recipe.loader||'UNETLoader','KSampler'];
  if(recipe.vae)nodes.push('VAELoader');
  const common=recipe.hdr?['VAELoader','CreateVideo']:REQUIRED;
  const missing=[...new Set([...common,...recipe.nodes,...nodes])].filter(type=>!info[type]);
  const weights=installedWeights(info,recipe);
  weightRequirements(recipe).forEach(([, , file],index)=>{if(!weights[index])missing.push(file);});
  return {ready:missing.length===0,missing};
}

export function rtxCapabilities(info){
  const fields=info?.[RTX_NODE]?.input?.required;
  const available=fields?.quality?.[1]?.options||fields?.quality?.[0];
  const offered=Array.isArray(available)?available:['LOW','MEDIUM','HIGH','ULTRA'];
  const quality=['HIGHBITRATE_ULTRA','ULTRA','HIGH','MEDIUM','LOW','BICUBIC'].filter(id=>offered.includes(id));
  return {quality,strength:!!fields?.strength,tenBit:!!fields?.image_encoding};
}

export function rtxSize(width,height,scale){
  const aligned=value=>Math.round(value*scale/8)*8;
  return {width:aligned(width),height:aligned(height)};
}

function ltxUpscale(add,mode,{width,height,prompt='',negativePrompt='',refineScale=1},images,vae,weights){
  if(![width,height].every(value=>Number.isInteger(value)&&value>0&&value<=4096)){
    throw Error('Choose a source up to 4096 pixels per side for LTX upscale.');
  }
  const direct=mode==='ltx25_latent_x2';
  const measured=add('source_size','GetImageSize',{image:images},'Counting selected source frames');
  const held=add('pad_frames','GenjHoldToModelLength',{images,stride:8},'Preparing LTX frame count');
  const scale=direct||refineScale===2?2:1;
  const targetWidth=width*scale,targetHeight=height*scale;
  // The latent upscaler doubles an input on the VAE's 32-pixel grid.
  const grid=direct?64:32;
  const paddedWidth=Math.ceil(targetWidth/grid)*grid,paddedHeight=Math.ceil(targetHeight/grid)*grid;
  const resize=(id,image,w,h,title)=>add(id,'ImageScale',{
    image,upscale_method:'lanczos',width:w,height:h,crop:'disabled',
  },title);
  const tiles={vae,tile_size:512,overlap:64,temporal_size:128,temporal_overlap:32};
  let latent;
  if(direct){
    const fitted=width===paddedWidth/2&&height===paddedHeight/2?held:
      resize('fit_vae',held,paddedWidth/2,paddedHeight/2,'Fitting the source to the LTX raster');
    const encoded=add('encode','VAEEncodeTiled',{pixels:fitted,...tiles},'Encoding source frames');
    const upscaler=add('upscaler','LatentUpscaleModelLoader',{model_name:weights[0]},'Loading LTX spatial upscaler');
    latent=add('upscale','LTXVLatentUpsampler',{samples:encoded,upscale_model:upscaler,vae},'Doubling latent resolution');
  }else{
    const [model,text,lora]=weights;
    const diffusion=add('model','UNETLoader',{unet_name:model,weight_dtype:'default'},'Loading LTX 2.5');
    const refiner=add('refiner','LTXICLoRALoaderModelOnly',{model:diffusion,lora_name:lora,strength_model:1},'Loading the LTX detail adapter');
    const clip=add('text_encoder','CLIPLoader',{clip_name:text,type:'ltxv',device:'default'},'Loading the local prompt encoder');
    const encode=(id,text)=>add(id,'CLIPTextEncode',{clip,text},'Encoding upscale guidance');
    const conditioning=add('conditioning','LTXVConditioning',{
      positive:encode('positive',prompt.trim()||'Preserve the source shot, motion, lighting and colour. Refine fine details.'),
      negative:encode('negative',negativePrompt.trim()),frame_rate:['components',2],
    },'Preparing frame-rate conditioning');
    const guide=resize('guide_frames',held,paddedWidth,paddedHeight,'Sizing the source guide');
    const empty=add('empty','EmptyLTXVLatentVideo',{
      width:paddedWidth,height:paddedHeight,length:[held[0],1],batch_size:1,
    },'Preparing the high-resolution canvas');
    const tileFrames=97;
    const guided=add('guide','LTXAddVideoICLoRAGuide',{
      positive:conditioning,negative:[conditioning[0],1],vae,latent:empty,image:guide,
      frame_idx:0,strength:1,latent_downscale_factor:[refiner[0],1],crop:'disabled',
      use_tiled_encode:false,tile_size:256,tile_overlap:64,use_streaming:true,tile_frames:tileFrames,
    },'Conditioning tiles on the source video');
    const sigmas=add('sigmas','ManualSigmas',{sigmas:LTX_DISTILLED_SIGMAS},'Setting the Lightricks eight-step schedule');
    const sampler=add('sampler','KSamplerSelect',{sampler_name:'euler'},'Selecting Euler sampling');
    latent=add('sample','LTXVTiledFusionSampler',{
      model:refiner,positive:guided,negative:[guided[0],1],latents:[guided[0],2],vae,sigmas,sampler,
      seed:42,cfg:negativePrompt.trim()?1.5:1,tile_width:width>=height?1024:576,tile_height:width>=height?576:1024,
      overlap_frac:.5,blend_var:.05,grid_cycle:1,tile_frames:tileFrames,canvas_device:'auto',
    },'Refining detail with overlapping tiles');
  }
  const decoded=add('decode','VAEDecodeTiled',{samples:latent,...tiles},'Decoding upscaled frames');
  const trimmed=add('delivery_frames','ImageFromBatch',{
    image:decoded,batch_index:0,length:[measured[0],2],
  },'Restoring the selected frame count');
  return paddedWidth===targetWidth&&paddedHeight===targetHeight?trimmed:
    resize('delivery_size',trimmed,targetWidth,targetHeight,'Restoring exact output dimensions');
}

export function upscaleFrameConfig(config,sourceFrames,time){
  const frame=Math.max(0,Math.min(sourceFrames-1,Math.floor((time+1e-6)*config.fps)));
  // Refine needs short temporal context. Spatial and restoration routes can
  // process a single source frame through their standard graph.
  const frames=config.model.startsWith('ltx25_')&&config.model!=='ltx25_latent_x2'?Math.min(9,sourceFrames):1;
  const first=Math.min(Math.max(0,frame-Math.floor(frames/2)),sourceFrames-frames);
  return {...config,start:first/config.fps,duration:frames/config.fps,frames,
    framePreview:{frame,offset:frame-first}};
}

export function addUpscaleFramePreviews(graph,{offset},source,result,hdr=false){
  for(const [id,images,title] of [['original',source,'Source frame'],['result',result,'Processed frame']]){
    const still='frame_'+id;
    graph[still]={class_type:'ImageFromBatch',inputs:{image:images,batch_index:offset,length:1}};
    if(hdr)graph[still+'_sdr']={class_type:'ZuraHDRSDRPreview',inputs:{image:[still,0]}};
    graph[still+'_preview']={class_type:'PreviewImage',inputs:{images:[hdr?still+'_sdr':still,0]},_meta:{title}};
  }
  return graph;
}

export function buildUpscaleGraph(config,info){
  const {file,start=0,duration=0,detail=1,model:mode=DEFAULT_UPSCALE_MODEL}=config;
  const recipe=UPSCALE_MODELS[mode];
  if(typeof file!=='string'||!file||file.includes('\\')||file.includes(':')||file.split('/').some(part=>!part||part==='.'||part==='..'))throw Error('Add a video to upscale.');
  if(![start,duration,detail].every(Number.isFinite)||start<0||duration<0||detail<0||detail>1)throw Error('Choose a valid clip range and detail amount.');
  if(!recipe)throw Error('Choose an upscale model.');
  if(!upscaleAvailability(info,mode).ready)throw Error(`Complete ${recipe.label} setup before upscaling.`);
  if(recipe.hdr)throw Error('Prepare HDR refinement through the native HDR source route.');
  const [vae,...weights]=installedWeights(info,recipe);
  const graph={};
  const add=(id,class_type,inputs,title)=>{
    graph[id]={class_type,inputs,_meta:{title}};
    return [id,0];
  };
  const loaded=add('source','LoadVideo',{file},'Reading source video');
  const selected=start||duration?add('trim','Video Slice',{video:loaded,start_time:start,duration,strict_duration:false},'Reading the selected clip'):loaded;
  const images=add('components','GetVideoComponents',{video:selected},'Separating picture and audio');
  const fullSizePreview=info.ZuraSaveProRes4444.input?.optional?.full_size_preview?{full_size_preview:true}:{};
  const finish=upscaled=>{
    if(config.framePreview)return addUpscaleFramePreviews(graph,config.framePreview,images,upscaled);
    saveVideo(add,upscaled,recipe,fullSizePreview);
    return graph;
  };
  if(mode===RTX_UPSCALE){
    const {rtxScale=2,rtxQuality,rtxStrength=1}=config;
    const size=rtxSize(config.width,config.height,rtxScale);
    if(!Number.isFinite(rtxScale)||rtxScale<1||rtxScale>4||
       !Object.values(size).every(value=>Number.isInteger(value)&&value>=64&&value<=8192)){
      throw Error('Choose an RTX scale that gives dimensions between 64 and 8192 pixels.');
    }
    const caps=rtxCapabilities(info);
    const quality=caps.quality.includes(rtxQuality)?rtxQuality:caps.quality[0];
    if(!quality)throw Error('Update the NVIDIA VFX nodes to use RTX Super Resolution.');
    const inputs={images,resize_type:'target dimensions','resize_type.width':size.width,'resize_type.height':size.height,quality};
    if(caps.strength)inputs.strength=Math.max(0,Math.min(1,rtxStrength));
    if(caps.tenBit)inputs.image_encoding='10-bit RGB (RGB10A2)';
    const upscale=add('upscale',RTX_NODE,inputs,'Upscaling with NVIDIA RTX');
    return finish(upscale);
  }
  const decoder=add('vae','VAELoader',{vae_name:vae},'Loading the matching VAE');
  if(recipe.weights){
    return finish(ltxUpscale(add,mode,config,images,decoder,weights));
  }
  const modelInputs={unet_name:weights[0],...(!recipe.loader&&{weight_dtype:'default'})};
  const diffusion=add('model',recipe.loader||'UNETLoader',modelInputs,`Loading ${recipe.label}`);
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
  return finish(upscaled);
}

function saveVideo(add,upscaled,recipe,preview){
  const video=add('video','CreateVideo',{images:upscaled,audio:['components',1],fps:['components',2]},'Restoring source frame rate and audio');
  add('save','ZuraSaveProRes4444',{video,filename_prefix:'ZURA STUDIO/upscale/'+recipe.output,...preview},'Writing ProRes master and playback preview');
}

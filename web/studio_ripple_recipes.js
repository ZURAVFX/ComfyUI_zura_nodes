// Dedicated Ripple workspace recipes. Keep the artist's source timeline intact;
// model padding and full-resolution delivery happen inside the native nodes.
import {buildRippleGraph, rippleAvailability, rippleValidation} from './paintout_studio/ripple_recipes.js';

export const H3_RIPPLE_FILES = Object.freeze({
  model:'minimax_h3_fl2va_pruned_int8_convrot.safetensors',
  flex:'pika_h3_flex_fl2va_v1_bf16.safetensors',
  ripple:'minimax_H3_Ripple-v1.safetensors',
  text:'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',
  vae:'minimax_h3_video_vae_fp16.safetensors',
});
export const RIPPLE_STUDIO_PACKAGES=Object.freeze({h3:'h3_ripple',ltx:'ltx_ripple'});
export const H3_RIPPLE_PROMPT='Edit propagation: each edited frame shows exactly how that moment of the video should look after the edit. Apply the same changes to every frame of the clip, before, between and after the edited frames, so the edit stays consistent through the whole video. Keep the guide video\'s motion, timing, camera movement, composition and all unedited content unchanged.';

const H3_NODES=['ZuraPaintoutFullFrame','ZuraPaintoutAnchors','ZuraRippleH3Guide','ZuraPaintoutUncrop','UNETLoader','LoraLoaderModelOnly','ModelAttentionBackend','CLIPLoader','VAELoader','WN_RippleApply','RandomNoise','KSamplerSelect','BasicScheduler','BasicGuider','SamplerCustomAdvanced','VAEDecode'];
const H3_FILES=[['UNETLoader','unet_name',H3_RIPPLE_FILES.model],['LoraLoaderModelOnly','lora_name',H3_RIPPLE_FILES.flex],['LoraLoaderModelOnly','lora_name',H3_RIPPLE_FILES.ripple],['CLIPLoader','clip_name',H3_RIPPLE_FILES.text],['VAELoader','vae_name',H3_RIPPLE_FILES.vae]];
const basename=value=>String(value).replaceAll('\\','/').split('/').pop().toLowerCase();
const choices=(info,node,key)=>{const f=info?.[node]?.input?.required?.[key]||info?.[node]?.input?.optional?.[key];return Array.isArray(f?.[0])?f[0]:f?.[0]==='COMBO'?f[1]?.options||[]:[];};
const choice=(info,node,key,name)=>choices(info,node,key).find(s=>basename(s)===basename(name))||name;
const anchorsOf=c=>(Array.isArray(c.anchors)?c.anchors:[]).filter(a=>a?.enabled!==false);

/** Round each dimension up independently. Only the AI working canvas changes. */
export function rippleStudioProcessingSize(sourceWidth,sourceHeight,scale=1,engine='h3'){
  if(!['h3','ltx'].includes(engine)||![sourceWidth,sourceHeight,scale].every(v=>Number.isFinite(Number(v))&&Number(v)>0))throw Error('Choose a valid source size and processing scale.');
  const step=engine==='h3'?32:64;
  return {width:Math.max(64,Math.ceil(Number(sourceWidth)*Number(scale)/step)*step),height:Math.max(64,Math.ceil(Number(sourceHeight)*Number(scale)/step)*step)};
}

export function rippleStudioAvailability(info={},engine='h3'){
  if(engine==='ltx')return rippleAvailability(info);
  if(engine!=='h3')return {ready:false,missing:['Choose a Ripple model.']};
  const missing=H3_NODES.filter(name=>!info[name]);
  for(const [node,key,name] of H3_FILES)if(!choices(info,node,key).some(v=>basename(v)===basename(name)))missing.push(name);
  if(!choices(info,'CLIPLoader','type').includes('minimax'))missing.push('minimax text support');
  return {ready:missing.length===0,missing:[...new Set(missing)]};
}

export function rippleStudioValidation(c={}){
  if(!['h3','ltx'].includes(c.engine))return 'Choose H3 or LTX Ripple.';
  if(typeof c.source!=='string'||!c.source.trim())return 'Add a source video.';
  if([c.sourceColour,c.detectedSourceColour].some(s=>['hlg_rec2020','pq_rec2020','pq_display_p3','acescg','acescct','linear_rec709'].includes(s)))return 'Ripple currently supports SDR footage.';
  if(c.colourPipeline&&c.colourPipeline!=='sdr_sdr'||c.processingSpace&&c.processingSpace!=='SDR (sRGB)')return 'Ripple currently supports SDR footage.';
  const maxFrames=c.engine==='h3'?993:985,step=c.engine==='h3'?32:64;
  if(!Number.isInteger(c.startFrame)||c.startFrame<0||!Number.isInteger(c.frameCount)||c.frameCount<1||c.frameCount>maxFrames)return `Choose a clip range of 1 to ${maxFrames} frames.`;
  if(!Number.isFinite(c.sequenceFps)||c.sequenceFps<1||c.sequenceFps>120)return 'Choose a valid source frame rate.';
  if(![c.width,c.height].every(v=>Number.isInteger(v)&&v>=64&&v<=4096&&v%step===0))return `Choose processing dimensions from 64 to 4096 px on the ${step}-pixel grid.`;
  if(!Number.isSafeInteger(c.seed??42)||(c.seed??42)<0)return 'Choose a whole-number seed.';
  if(!['SDR video'].includes(c.outputMode||'SDR video'))return 'Choose SDR video for Ripple.';
  const anchors=anchorsOf(c);
  if(!anchors.length)return 'Add an edited frame on the timeline.';
  if(c.engine==='ltx'&&(anchors.length!==1||Number(anchors[0].frame)!==c.startFrame))return 'LTX Ripple uses one edited frame at the start of the selected clip.';
  if(c.engine==='h3'&&anchors.length>16)return 'H3 Ripple supports up to 16 edited frames.';
  if(anchors.some(a=>typeof a.file!=='string'||!a.file.trim()))return 'Add an image for every edited frame.';
  if(anchors.some(a=>!Number.isInteger(Number(a.frame))||Number(a.frame)<c.startFrame||Number(a.frame)>=c.startFrame+c.frameCount))return 'Place every edited frame inside the selected clip.';
  if(new Set(anchors.map(a=>Number(a.frame))).size!==anchors.length)return 'Use a different timeline frame for each edit.';
  if(c.rippleStrength!=null&&(!Number.isFinite(Number(c.rippleStrength))||Number(c.rippleStrength)<.1||Number(c.rippleStrength)>2))return 'Choose a Ripple strength between 0.1 and 2.';
  return '';
}

/** Build a graph for the selected model without changing source rate or range. */
export function buildRippleStudioGraph(c,info={}){
  const error=rippleStudioValidation(c);if(error)throw Error(error);
  const anchors=anchorsOf(c).sort((a,b)=>Number(a.frame)-Number(b.frame));
  if(c.engine==='ltx'){
    // This published LoRA is first-frame-only. The existing author-approved
    // path prepends that edit, holds the tail and discards the added lead.
    const ltx={...c,savePrefix:c.savePrefix||'ZURA STUDIO/ripple',seed:c.seed??42,allowLargeWorkingRaster:true,anchors:anchors.map(a=>({...a,rippleReviewedFile:a.file}))};
    const oldError=rippleValidation(ltx);if(oldError)throw Error(oldError);
    const graph=buildRippleGraph(ltx,info);
    graph.source.inputs.framing_mode='Full frame (stretch to working size)';
    graph.source.inputs.render_width=c.width;graph.source.inputs.render_height=c.height;
    graph.anchors.inputs.anchors=JSON.stringify(anchors.map(a=>({file:a.file,frame:Number(a.frame),strength:1,enabled:true,colour_space:a.colour_space||'srgb_display'})));
    return graph;
  }
  const graph={},r=(id,slot=0)=>[id,slot],n=(id,class_type,inputs,title)=>{graph[id]={class_type,inputs,_meta:{title}};return r(id);};
  n('source','ZuraPaintoutFullFrame',{plate_path:c.source,colour_space:c.sourceColour||'auto',start_frame:c.startFrame,frame_count:c.frameCount,sequence_fps:c.sequenceFps,context_pixels:128,max_crop_side:768,repair_grow:0,feather_pixels:0,processing_mode:'SDR (sRGB)',framing_mode:'Full frame (stretch to working size)',render_width:c.width,render_height:c.height},'Reading the selected source frames');
  n('anchors','ZuraPaintoutAnchors',{plate:r('source',2),anchors:JSON.stringify(anchors.map(a=>({file:a.file,frame:Number(a.frame),strength:1,enabled:true,colour_space:a.colour_space||'srgb_display'})))},'Loading edited keyframes');
  n('ripple_guide','ZuraRippleH3Guide',{plate:r('source',2),anchors:r('anchors')},'Preparing source and edited keyframes');
  n('model','UNETLoader',{unet_name:choice(info,'UNETLoader','unet_name',H3_RIPPLE_FILES.model),weight_dtype:'default'},'Loading H3');
  n('flex','LoraLoaderModelOnly',{model:r('model'),lora_name:choice(info,'LoraLoaderModelOnly','lora_name',H3_RIPPLE_FILES.flex),strength_model:1},'Loading H3 Flex');
  n('lora','LoraLoaderModelOnly',{model:r('flex'),lora_name:choice(info,'LoraLoaderModelOnly','lora_name',H3_RIPPLE_FILES.ripple),strength_model:Number(c.rippleStrength??1)},'Loading H3 Ripple');
  n('attention','ModelAttentionBackend',{model:r('lora'),attention:'comfy kitchen attention'},'Preparing attention');
  n('text','CLIPLoader',{clip_name:choice(info,'CLIPLoader','clip_name',H3_RIPPLE_FILES.text),type:'minimax',device:'default'},'Loading H3 text encoder');
  n('video_vae','VAELoader',{vae_name:choice(info,'VAELoader','vae_name',H3_RIPPLE_FILES.vae)},'Loading H3 video VAE');
  n('apply','WN_RippleApply',{clip:r('text'),vae:r('video_vae'),ripple:r('ripple_guide'),edited_images:r('ripple_guide',1),prompt:H3_RIPPLE_PROMPT+(String(c.prompt||'').trim()?'\n'+String(c.prompt).trim():'')},'Applying your edited keyframes');
  n('noise','RandomNoise',{noise_seed:c.seed??42},'Preparing noise');
  n('sampler','KSamplerSelect',{sampler_name:'lcm'},'Preparing sampler');
  n('sigmas','BasicScheduler',{model:r('attention'),scheduler:'simple',steps:6,denoise:1},'Preparing six sampling steps');
  n('guider','BasicGuider',{model:r('attention'),conditioning:r('apply')},'Preparing H3 guidance');
  n('sample','SamplerCustomAdvanced',{noise:r('noise'),guider:r('guider'),sampler:r('sampler'),sigmas:r('sigmas'),latent_image:r('apply',1)},'Propagating edits through the clip');
  n('decode','VAEDecode',{samples:r('sample'),vae:r('video_vae')},'Decoding the video');
  n('save','ZuraPaintoutUncrop',{decoded_crop:r('decode'),plate:r('source',2),output_name:c.savePrefix||'ZURA STUDIO/ripple',precision:'float32',match_context:false,export_format:'SDR video',motion_preview:true},'Restoring source size, frame rate and audio');
  return graph;
}

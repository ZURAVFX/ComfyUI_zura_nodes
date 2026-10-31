// Experimental timed-frame inpainting. Source and mask are prepared by the
// Paintout editor; the sampling stages follow LTX's 2.5 inpaint example.
import {buildPaintoutRepairGraph, paintoutAvailability, paintoutValidation, paintoutColourPipeline, PAINTOUT_MODELS} from './paintout_recipes.js';

export const INPAINT_LORA = 'ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors';
export const INPAINT_PROMPT = 'Add the object shown in the reference frame. Match the existing perspective, lighting and movement. Preserve the rest of the shot.';
const choices=(info,node,key)=>{const f=info?.[node]?.input?.required?.[key]||info?.[node]?.input?.optional?.[key];return f?.[0]==='COMBO'?f[1]?.options||[]:Array.isArray(f?.[0])?f[0]:[];};
const basename=s=>String(s).replaceAll('\\','/').split('/').pop();
const adapter=info=>choices(info,'LTXICLoRALoaderModelOnly','lora_name').find(s=>basename(s)===INPAINT_LORA)||INPAINT_LORA;

export function inpaintValidation(config){
  const error=paintoutValidation({...config,mode:'targeted'});
  return error.replace('removal mask','inpaint mask').replaceAll('painted clean frame','reference frame');
}

export function inpaintAvailability(info,config){
  // Reuse the existing source/anchor/export requirements, but do not require
  // the unrelated Remova adapter or its specialised attention implementation.
  const base=paintoutAvailability(info,'targeted',{...config,mode:'targeted'});
  const vaes=choices(info,'VAELoader','vae_name'),officialVae=vaes.find(s=>basename(s)===PAINTOUT_MODELS.hdrVideoVae);
  const unrelated=new Set(['LTX23_Obscura_Remova_v1.safetensors','LoraLoaderModelOnly','ZuraPaintoutGuideMemory','KSampler','LTX linear_quadratic scheduler','GrowMask','BlockifyMask','InvertMask',...(officialVae?[PAINTOUT_MODELS.videoVae]:[])]);
  const missing=base.missing.filter(x=>!unrelated.has(x));
  for(const name of ['LTXICLoRALoaderModelOnly','MaskToImage','ImageScaleBy','ImageToMask','GetImageSize','LTXVInpaintPreprocess','CFGGuider','RandomNoise','KSamplerSelect','ManualSigmas','SamplerCustomAdvanced','LTXVLaplacianPyramidBlend','VAEEncodeTiled'])if(!info?.[name])missing.push(name);
  if(config?.maskProject&&Number.isInteger(config?.maskRevision))for(const name of ['ZuraPaintoutMaskSource','ZuraPaintoutEditorCrop'])if(!info?.[name])missing.push(name);
  if(!choices(info,'LTXICLoRALoaderModelOnly','lora_name').some(s=>basename(s)===INPAINT_LORA))missing.push(INPAINT_LORA);
  return {ready:!missing.length,missing:[...new Set(missing)]};
}

export function buildInpaintRepairGraph(config,info){
  const error=inpaintValidation(config);if(error)throw Error(error);
  const c={...config,mode:'targeted',prompt:String(config.prompt||'').trim()||INPAINT_PROMPT};
  const graph=buildPaintoutRepairGraph(c,info),ref=(id,slot=0)=>[id,slot];
  const vaes=choices(info,'VAELoader','vae_name');
  if(info&&paintoutColourPipeline(c)!=='hdr_hdr'&&!vaes.some(s=>basename(s)===PAINTOUT_MODELS.videoVae)){
    const official=vaes.find(s=>basename(s)===PAINTOUT_MODELS.hdrVideoVae);if(official)graph.video_vae.inputs.vae_name=official;
  }
  for(const id of ['lora','memory','latent','grow_mask','block_mask','invert_mask','guide','apply_anchors','combine','sample','separate','crop_guides','decode'])delete graph[id];
  const node=(id,type,inputs,title)=>{graph[id]={class_type:type,inputs,_meta:{title}};};
  node('lora','LTXICLoRALoaderModelOnly',{model:ref('model'),lora_name:adapter(info),strength_model:1},'Loading the inpaint adapter');
  node('mask_image','MaskToImage',{mask:ref('take',1)},'Preparing the selected area');
  node('mask_low_image','ImageScaleBy',{image:ref('mask_image'),upscale_method:'area',scale_by:.5},'Scaling the mask');
  node('mask_low','ImageToMask',{image:ref('mask_low_image'),channel:'red'},'Preparing the low-resolution mask');
  node('source_low','ImageScaleBy',{image:ref('take'),upscale_method:'lanczos',scale_by:.5},'Preparing the low-resolution video');
  node('size_low','GetImageSize',{image:ref('source_low')},'Checking the sample dimensions');
  node('prepare_low','LTXVInpaintPreprocess',{images:ref('source_low'),mask:ref('mask_low')},'Preparing masked guidance');
  node('latent','EmptyLTXVLatentVideo',{width:ref('size_low'),height:ref('size_low',1),length:ref('take',4),batch_size:1},'Preparing video samples');
  node('guide','LTXAddVideoICLoRAGuideAdvanced',{positive:ref('conditioning'),negative:ref('conditioning',1),vae:ref('float_vae'),latent:ref('latent'),image:ref('prepare_low'),frame_idx:0,strength:1,latent_downscale_factor:ref('lora',1),crop:'disabled',use_tiled_encode:false,tile_size:256,tile_overlap:64,attention_strength:1,use_streaming:false,tile_frames:97},'Encoding the masked video');
  node('apply_anchors','ZuraPaintoutApplyAnchors',{positive:ref('guide'),negative:ref('guide',1),vae:ref('float_vae'),latent:ref('guide',2),anchors:ref('anchors')},'Encoding reference frames');
  node('combine','LTXVConcatAVLatent',{video_latent:ref('apply_anchors',2),audio_latent:ref('audio')},'Preparing samples');
  node('guider','CFGGuider',{model:ref('lora'),positive:ref('apply_anchors'),negative:ref('apply_anchors',1),cfg:1},'Preparing inpaint guidance');
  node('noise','RandomNoise',{noise_seed:Number(c.seed??42)},'Preparing noise');
  node('sampler','KSamplerSelect',{sampler_name:'euler_ancestral'},'Preparing sampler');
  node('sigmas','ManualSigmas',{sigmas:'1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0'},'Preparing first pass');
  node('sample','SamplerCustomAdvanced',{noise:ref('noise'),guider:ref('guider'),sampler:ref('sampler'),sigmas:ref('sigmas'),latent_image:ref('combine')},'Generating the object');
  node('separate','LTXVSeparateAVLatent',{av_latent:ref('sample')},'Preparing the first pass');
  node('crop_guides','LTXVCropGuides',{positive:ref('apply_anchors'),negative:ref('apply_anchors',1),latent:ref('separate')},'Removing guide samples');
  node('decode_low','VAEDecodeTiled',{samples:ref('crop_guides',2),vae:ref('float_vae'),tile_size:512,overlap:64,temporal_size:128,temporal_overlap:32},'Decoding the first pass');
  node('blend_low','LTXVLaplacianPyramidBlend',{image_a:ref('decode_low'),image_b:ref('source_low'),mask:ref('mask_low'),trim_to_shortest:true,mask_low_res_dilation:5},'Blending the first pass');
  node('upsize','ImageScale',{image:ref('blend_low'),upscale_method:'lanczos',width:ref('take',2),height:ref('take',3),crop:'disabled'},'Upscaling the first pass');
  node('encode_high','VAEEncodeTiled',{pixels:ref('upsize'),vae:ref('float_vae'),tile_size:512,overlap:64,temporal_size:128,temporal_overlap:32},'Preparing detail refinement');
  node('anchors_high','ZuraPaintoutApplyAnchors',{positive:ref('conditioning'),negative:ref('conditioning',1),vae:ref('float_vae'),latent:ref('encode_high'),anchors:ref('anchors')},'Applying reference frames to refinement');
  node('combine_high','LTXVConcatAVLatent',{video_latent:ref('anchors_high',2),audio_latent:ref('separate',1)},'Preparing refined samples');
  node('guider_high','CFGGuider',{model:ref('lora'),positive:ref('anchors_high'),negative:ref('anchors_high',1),cfg:1},'Preparing detail guidance');
  node('sampler_high','KSamplerSelect',{sampler_name:'euler'},'Preparing refinement sampler');
  node('sigmas_high','ManualSigmas',{sigmas:'0.7250, 0.4219, 0.0'},'Preparing two-step refinement');
  node('sample_high','SamplerCustomAdvanced',{noise:ref('noise'),guider:ref('guider_high'),sampler:ref('sampler_high'),sigmas:ref('sigmas_high'),latent_image:ref('combine_high')},'Refining the object');
  node('separate_high','LTXVSeparateAVLatent',{av_latent:ref('sample_high')},'Preparing the final frame');
  node('crop_high','LTXVCropGuides',{positive:ref('anchors_high'),negative:ref('anchors_high',1),latent:ref('separate_high')},'Removing reference samples');
  node('decode_high','VAEDecodeTiled',{samples:ref('crop_high',2),vae:ref('float_vae'),tile_size:512,overlap:64,temporal_size:128,temporal_overlap:32},'Decoding the result');
  node('prepare_high','LTXVInpaintPreprocess',{images:ref('take'),mask:ref('take',1)},'Preparing the final blend');
  node('blend_high','LTXVLaplacianPyramidBlend',{image_a:ref('decode_high'),image_b:ref('prepare_high'),mask:ref('take',1),trim_to_shortest:true,mask_low_res_dilation:6},'Blending the result');
  const output=paintoutColourPipeline(c)==='sdr_hdr'?'repair_save':'save';
  graph[output].inputs.decoded_crop=ref('blend_high');
  return graph;
}

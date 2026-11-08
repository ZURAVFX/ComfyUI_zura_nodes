import {FLUX3_PROMPT_SYSTEMS} from '../flux3_prompt_upsampling.js';

export const DEFAULT_FRAME_EDIT_PROMPT = 'Remove the foreground object';
// Native FLUX 3 Image Klein distilled editing, with an explicit source-pixel composite.
export const FRAME_EDIT_MODELS = {
  model: 'flux3-image-klein-int8-convrot.safetensors',
  text: 'qwen3vl_4b_int8_convrot.safetensors',
  upsampler: 'qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors',
  vae: 'flux2-vae.safetensors',
};

const requiredNodes = ['ZuraPaintoutFrameCrop', 'ZuraPaintoutFrameComposite', 'UNETLoader', 'CLIPLoader', 'VAELoader', 'CLIPTextEncode', 'ReferenceMultiLatent', 'KSampler', 'VAEDecode', 'TextGenerate', 'ModelSamplingFlux', 'ConditioningZeroOut', 'BatchImagesNode', 'ResizeAndPadImage'];
const choices = (info, node, input) => {
  const field = info[node]?.input?.required?.[input] || info[node]?.input?.optional?.[input];
  return field?.[0] === 'COMBO' ? field[1]?.options || [] : Array.isArray(field?.[0]) ? field[0] : [];
};
const matchFile = (files, name) => files.find(file => String(file).replaceAll('\\', '/').split('/').pop() === name);

export function frameRemovalTarget(instruction = '') {
  const text=String(instruction).trim();
  const match=text.match(/^(?:please\s+)?(?:remove|erase|delete)\s+(?:only\s+)?(?:the\s+)?(.+?)(?=\s+(?:and|but|without|while)\s+|[,.;!\n]|$)/i);
  if(!match)return '';
  const target=match[1].replace(/\s+only$/i,'').trim();
  if(!target||target.length>120||/^(?:everything|anything|all|selected|masked|painted|object|subject|area|region)\b/i.test(target))return '';
  const remainder=text.slice(match[0].length).trim();
  if(/^and\s+/i.test(remainder)&&!/^and\s+(?:reconstruct|restore|fill|keep|preserve|leave|match|replace|inpaint)\b/i.test(remainder))return '';
  return target;
}

export function frameEditAvailability(info = {}, config = {}) {
  const files = {
    model: matchFile(choices(info, 'UNETLoader', 'unet_name'), FRAME_EDIT_MODELS.model),
    text: matchFile(choices(info, 'CLIPLoader', 'clip_name'), FRAME_EDIT_MODELS.text),
    upsampler: matchFile(choices(info, 'CLIPLoader', 'clip_name'), FRAME_EDIT_MODELS.upsampler),
    vae: matchFile(choices(info, 'VAELoader', 'vae_name'), FRAME_EDIT_MODELS.vae),
  };
  const missing = requiredNodes.filter(name => !info[name]);
  if(config.named_target&&frameRemovalTarget(config.prompt)){
    const sam=choices(info,'CheckpointLoaderSimple','ckpt_name').find(file=>/sam3\.1_multiplex_fp16\.safetensors$/i.test(file));
    if(!sam)missing.push('SAM3.1 checkpoint for selecting the named object');
    for(const name of ['CheckpointLoaderSimple','SAM3_Detect','ZuraPaintoutTargetConditioning','ZuraPaintoutFrameTarget'])if(!info[name])missing.push(name);
    files.sam=sam;
  }
  if (Array.isArray(info.ZuraPaintoutFrameCrop?.output) && info.ZuraPaintoutFrameCrop.output.length < 7) missing.push('Restart ComfyUI to load the updated frame-removal backend');
  for (const [key, name] of Object.entries(FRAME_EDIT_MODELS)) if (!files[key]) missing.push(name);
  if (info.CLIPLoader && !choices(info, 'CLIPLoader', 'type').includes('flux3')) missing.push('Current ComfyUI FLUX 3 text encoder support');
  return {ready: !missing.length, missing: [...new Set(missing)], files};
}

const selectionInstruction = 'Reconstruct the filled area left by the removal, matching the surrounding scene, perspective, texture and lighting. Preserve other objects and scene details. Follow the artist instruction; do not remove unrelated subjects.';
const backgroundInstruction = 'Reconstruct the flat gray filled area as a natural continuation of the empty background. Continue the existing surface texture, lines, perspective and lighting across it. The filled area must contain only empty ground and background. Do not add a vehicle or object. Keep the rest of the image unchanged.';

// Match the released Flux 3 recipe used by Image and Ripple. Its visual prompt
// stage sees the same source/reference images as diffusion, before masking the
// generated pixels back into the original plate.
function framePrompt(graph, instruction, images, seed, upsampler) {
  const node=(id,class_type,inputs,title)=>{graph[id]={class_type,inputs,_meta:{title}};return [id,0];};
  const batch={'images.image0':images[0]};
  for(let index=1;index<images.length;index++)batch['images.image'+index]=node(
    'frame_prompt_reference_'+index,'ResizeAndPadImage',{
      image:images[index],target_width:['frame_crop',3],target_height:['frame_crop',4],
      padding_color:'white',interpolation:'lanczos',
    },'Keeping the complete appearance reference');
  const image=node('frame_prompt_images','BatchImagesNode',batch,'Ordered frame and appearance references');
  const clip=node('frame_prompt_encoder','CLIPLoader',{clip_name:upsampler,type:'flux3',device:'default'},'Loading Flux 3 image-aware prompt expansion');
  const expanded=node('frame_expand_prompt','TextGenerate',{
    clip,image,prompt:`Reference images follow in order (the first image, the second image, ...).\nUser request: ${instruction}\nOutput the caption.`,
    system_prompt:FLUX3_PROMPT_SYSTEMS.i2i,max_length:3584,sampling_mode:'on',
    'sampling_mode.temperature':1,'sampling_mode.top_k':1,'sampling_mode.top_p':.95,
    'sampling_mode.min_p':0,'sampling_mode.repetition_penalty':1,'sampling_mode.seed':seed,
    'sampling_mode.presence_penalty':0,thinking:false,use_default_template:true,mtp:'off',
  },'Understanding the painted frame edit');
  graph.frame_positive.inputs.text=expanded;
}

export function buildFrameEditGraph(config, info) {
  const available = frameEditAvailability(info, config);
  if (!available.ready) throw new Error('Frame cleaning needs: ' + available.missing.join(', '));
  if (!config.source || !Number.isInteger(Number(config.frame)) || Number(config.frame) < 0) throw new Error('Choose a source frame to clean.');
  if (!config.mask) throw new Error('Draw over the object to remove first.');
  const seed = Number(config.seed ?? 42);
  if (!Number.isSafeInteger(seed) || seed < 0) throw new Error('Choose a whole-number seed.');
  const graph = {}, ref = (id, slot = 0) => [id, slot];
  const node = (id, class_type, inputs, title) => {graph[id] = {class_type, inputs, _meta: {title}};};
  const files = available.files;
  node('frame_crop', 'ZuraPaintoutFrameCrop', {
    source: config.source, frame: Number(config.frame), colour_space: config.colour_space || 'srgb_display',
    mask: config.mask, grow: Number(config.grow ?? 0), feather: Number(config.feather ?? 0),
    context: Number(config.context ?? 256), max_side: Number(config.max_side ?? 1024),
    ...(config.base_file?{base_file:config.base_file,base_colour_space:config.base_colour_space||'srgb_display'}:{}),
    ...(config.project ? {project: config.project, mask_revision: Number(config.mask_revision)} : {}),
  }, 'Preparing the selected frame');
  const namedInstruction=frameRemovalTarget(config.prompt);
  const target=config.named_target?namedInstruction:'';
  if(target){
    node('frame_subject_model','CheckpointLoaderSimple',{ckpt_name:files.sam},'Loading object selection');
    node('frame_subject_text','CLIPTextEncode',{clip:ref('frame_subject_model',1),text:target},'Finding '+target);
    node('frame_subject_conditioning','ZuraPaintoutTargetConditioning',{conditioning:ref('frame_subject_text')},'Checking matching objects');
    node('frame_subject_detect','SAM3_Detect',{model:ref('frame_subject_model'),image:ref('frame_crop'),conditioning:ref('frame_subject_conditioning'),threshold:.5,refine_iterations:2,individual_masks:true},'Selecting '+target);
    node('frame_target','ZuraPaintoutFrameTarget',{patch:ref('frame_crop',2),image:ref('frame_crop'),masks:ref('frame_subject_detect'),target},'Protecting everything except '+target);
  }
  node('frame_model', 'UNETLoader', {unet_name: files.model, weight_dtype: 'default'}, 'Loading FLUX 3 Image Klein');
  node('frame_text', 'CLIPLoader', {clip_name: files.text, type: 'flux3', device: 'default'}, 'Loading the frame text encoder');
  node('frame_vae', 'VAELoader', {vae_name: files.vae}, 'Loading the frame VAE');
  // The artist's subject goes to SAM. FLUX synthesises replacement background;
  // only the detected subject support is composited, protecting other objects.
  node('frame_positive', 'CLIPTextEncode', {clip: ref('frame_text'), text: target?backgroundInstruction:'Artist instruction: '+String(config.prompt || DEFAULT_FRAME_EDIT_PROMPT).trim()+'\n\n'+selectionInstruction}, 'Encoding the clean-frame instruction');
  node('frame_negative', 'ConditioningZeroOut', {conditioning: ref('frame_positive')}, 'Preparing distilled guidance');
  node('frame_sampling', 'ModelSamplingFlux', {model:ref('frame_model'),max_shift:Math.log(16),base_shift:Math.log(16),width:ref('frame_crop',3),height:ref('frame_crop',4)}, 'Flux 3 alpha-16 sampling');
  node('frame_reference', 'ReferenceMultiLatent', {
    positive: ref('frame_positive'), negative: ref('frame_negative'), vae: ref('frame_vae'),
    resolution: 'keep resolution', 'images.image0': ref('frame_crop', namedInstruction&&!target?0:6),
  }, namedInstruction&&!target?'Encoding the original image for the removal instruction':'Encoding the background reconstruction reference');
  node('frame_sample', 'KSampler', {
    model: ref('frame_sampling'), positive: ref('frame_reference'), negative: ref('frame_reference', 1),
    latent_image: ref('frame_reference', 2), seed, steps: 16, cfg: 1,
    sampler_name: 'euler', scheduler: 'simple', denoise: 1,
  }, 'Cleaning the frame with FLUX 3');
  node('frame_decode', 'VAEDecode', {samples: ref('frame_sample'), vae: ref('frame_vae')}, 'Decoding the clean frame');
  node('frame_save', 'ZuraPaintoutFrameComposite', {
    patch: ref(target?'frame_target':'frame_crop', target?1:2), image: ref('frame_decode'), match_context: config.match_context !== false,
  }, 'Blending only the painted region');
  framePrompt(graph,graph.frame_positive.inputs.text,[graph.frame_reference.inputs['images.image0']],seed,files.upsampler);
  return graph;
}

/** Build an object-reference edit from the selected original source frame.
 * The reference is conditioning, not an already-composited full-frame anchor.
 * The generated pixels are confined to the artist's reviewed mask. */
export function buildInpaintFrameGraph(config, info) {
  const references=Array.isArray(config.references)?config.references:[];
  if(references.length>8)throw Error('Use up to eight object reference images.');
  if(references.some(file=>typeof file!=='string'||!file||file.startsWith('/')||file.includes('..')||file.includes('\\')))throw Error('Upload the object references again.');
  if(references.length&&!info.LoadImage)throw Error('LoadImage is required for object references.');
  const graph=buildFrameEditGraph({...config,named_target:false},info);
  const instruction='Edit the first image only within the selected region. '+String(config.prompt||'Add the object shown in the reference image.').trim()+' Preserve the surrounding scene, perspective and lighting. Do not duplicate the object unless requested.';
  graph.frame_positive._meta.title='Encoding the object instruction';
  graph.frame_reference.inputs['images.image0']=['frame_crop',0];
  graph.frame_reference._meta.title='Encoding the source frame and object references';
  references.forEach((file,index)=>{
    const id='object_reference_'+index;
    graph[id]={class_type:'LoadImage',inputs:{image:file},_meta:{title:'Loading object reference '+(index+1)}};
    graph.frame_reference.inputs['images.image'+(index+1)]=[id,0];
  });
  framePrompt(graph,instruction,[graph.frame_reference.inputs['images.image0'],...references.map((_,index)=>['object_reference_'+index,0])],Number(config.seed??42),frameEditAvailability(info,config).files.upsampler);
  graph.frame_sample._meta.title='Creating the reference frame with FLUX 3';
  graph.frame_decode._meta.title='Decoding the reference frame';
  return graph;
}

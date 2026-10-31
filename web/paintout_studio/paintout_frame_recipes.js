export const DEFAULT_FRAME_EDIT_PROMPT = 'Remove the foreground object';
// Native FLUX 3 Image Klein distilled editing, with an explicit source-pixel composite.
export const FRAME_EDIT_MODELS = {
  model: 'flux3-image-klein-int8-convrot.safetensors',
  text: 'qwen3vl_4b_int8_convrot.safetensors',
  vae: 'flux2-vae.safetensors',
};

const requiredNodes = ['ZuraPaintoutFrameCrop', 'ZuraPaintoutFrameComposite', 'UNETLoader', 'CLIPLoader', 'VAELoader', 'CLIPTextEncode', 'ReferenceMultiLatent', 'KSampler', 'VAEDecode'];
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
  node('frame_negative', 'CLIPTextEncode', {clip: ref('frame_text'), text: ''}, 'Preparing frame conditioning');
  node('frame_reference', 'ReferenceMultiLatent', {
    positive: ref('frame_positive'), negative: ref('frame_negative'), vae: ref('frame_vae'),
    resolution: 'keep resolution', 'images.image0': ref('frame_crop', namedInstruction&&!target?0:6),
  }, namedInstruction&&!target?'Encoding the original image for the removal instruction':'Encoding the background reconstruction reference');
  node('frame_sample', 'KSampler', {
    model: ref('frame_model'), positive: ref('frame_reference'), negative: ref('frame_reference', 1),
    latent_image: ref('frame_reference', 2), seed, steps: 16, cfg: 1,
    sampler_name: 'euler', scheduler: 'simple', denoise: 1,
  }, 'Cleaning the frame with FLUX 3');
  node('frame_decode', 'VAEDecode', {samples: ref('frame_sample'), vae: ref('frame_vae')}, 'Decoding the clean frame');
  node('frame_save', 'ZuraPaintoutFrameComposite', {
    patch: ref(target?'frame_target':'frame_crop', target?1:2), image: ref('frame_decode'), match_context: config.match_context !== false,
  }, 'Blending only the painted region');
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
  graph.frame_positive.inputs.text='Edit the first image only within the selected region. '+String(config.prompt||'Add the object shown in the reference image.').trim()+' Preserve the surrounding scene, perspective and lighting. Do not duplicate the object unless requested.';
  graph.frame_positive._meta.title='Encoding the object instruction';
  graph.frame_reference.inputs['images.image0']=['frame_crop',0];
  graph.frame_reference._meta.title='Encoding the source frame and object references';
  references.forEach((file,index)=>{
    const id='object_reference_'+index;
    graph[id]={class_type:'LoadImage',inputs:{image:file},_meta:{title:'Loading object reference '+(index+1)}};
    graph.frame_reference.inputs['images.image'+(index+1)]=[id,0];
  });
  graph.frame_sample._meta.title='Creating the reference frame with FLUX 3';
  graph.frame_decode._meta.title='Decoding the reference frame';
  return graph;
}

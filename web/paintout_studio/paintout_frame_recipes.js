// Native FLUX 3 Image Klein distilled editing, with an explicit source-pixel composite.
export const FRAME_EDIT_MODELS = {
  model: 'flux3-image-klein-int8-convrot.safetensors',
  text: 'qwen3vl_4b_int8_convrot.safetensors',
  upsampler: 'qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors',
  vae: 'flux2-vae.safetensors',
};

const requiredNodes = ['ZuraPaintoutFrameCrop', 'ZuraPaintoutFrameComposite', 'UNETLoader', 'CLIPLoader', 'VAELoader', 'TextGenerate', 'CLIPTextEncode', 'ReferenceMultiLatent', 'KSampler', 'VAEDecode'];
const choices = (info, node, input) => {
  const field = info[node]?.input?.required?.[input] || info[node]?.input?.optional?.[input];
  return field?.[0] === 'COMBO' ? field[1]?.options || [] : Array.isArray(field?.[0]) ? field[0] : [];
};
const matchFile = (files, name) => files.find(file => String(file).replaceAll('\\', '/').split('/').pop() === name);

export function frameEditAvailability(info = {}) {
  const files = {
    model: matchFile(choices(info, 'UNETLoader', 'unet_name'), FRAME_EDIT_MODELS.model),
    text: matchFile(choices(info, 'CLIPLoader', 'clip_name'), FRAME_EDIT_MODELS.text),
    upsampler: matchFile(choices(info, 'CLIPLoader', 'clip_name'), FRAME_EDIT_MODELS.upsampler),
    vae: matchFile(choices(info, 'VAELoader', 'vae_name'), FRAME_EDIT_MODELS.vae),
  };
  const missing = requiredNodes.filter(name => !info[name]);
  for (const [key, file] of Object.entries(files)) if (!file) missing.push(FRAME_EDIT_MODELS[key]);
  if (info.CLIPLoader && !choices(info, 'CLIPLoader', 'type').includes('flux3')) missing.push('Current ComfyUI FLUX 3 text encoder support');
  return {ready: !missing.length, missing: [...new Set(missing)], files};
}

const expansionInstruction = 'You are the prompt upsampler for an image-editing model. The attached source crop has a translucent red selection painted over the object the user wants removed. The red paint is a UI annotation, not scene content. Identify only the selected object by its visible appearance and position, then expand the user request into one clear English editing instruction for the unmarked original image. Describe the background that should naturally fill its place, accounting for perspective, lighting, shadows and reflections. Do not mention red paint or selection annotations in your output. Do not invent people, objects or a new scene. Preserve the camera, composition and all content outside the requested edit. Output only the instruction, approximately 50 to 150 words, without Markdown or commentary.';

export function buildFrameEditGraph(config, info) {
  const available = frameEditAvailability(info);
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
    context: Number(config.context ?? 128), max_side: Number(config.max_side ?? 1024),
    ...(config.project ? {project: config.project, mask_revision: Number(config.mask_revision)} : {}),
  }, 'Preparing the selected frame');
  node('frame_upsampler', 'CLIPLoader', {clip_name: files.upsampler, type: 'flux3', device: 'default'}, 'Loading local prompt expansion');
  node('frame_caption', 'TextGenerate', {
    clip: ref('frame_upsampler'), prompt: String(config.prompt || 'Remove the marked unwanted object and reconstruct the background.').trim(),
    image: ref('frame_crop', 5), max_length: 768, sampling_mode: 'off',
    thinking: false, use_default_template: true, mtp: 'off', system_prompt: expansionInstruction,
  }, 'Describing the cleaned frame');
  node('frame_model', 'UNETLoader', {unet_name: files.model, weight_dtype: 'default'}, 'Loading FLUX 3 Image Klein');
  node('frame_text', 'CLIPLoader', {clip_name: files.text, type: 'flux3', device: 'default'}, 'Loading the frame text encoder');
  node('frame_vae', 'VAELoader', {vae_name: files.vae}, 'Loading the frame VAE');
  node('frame_positive', 'CLIPTextEncode', {clip: ref('frame_text'), text: ref('frame_caption')}, 'Encoding the clean-frame instruction');
  node('frame_negative', 'CLIPTextEncode', {clip: ref('frame_text'), text: ''}, 'Preparing frame conditioning');
  node('frame_reference', 'ReferenceMultiLatent', {
    positive: ref('frame_positive'), negative: ref('frame_negative'), vae: ref('frame_vae'),
    resolution: 'keep resolution', 'images.image0': ref('frame_crop'),
  }, 'Encoding the source crop');
  node('frame_sample', 'KSampler', {
    model: ref('frame_model'), positive: ref('frame_reference'), negative: ref('frame_reference', 1),
    latent_image: ref('frame_reference', 2), seed, steps: 16, cfg: 1,
    sampler_name: 'euler', scheduler: 'simple', denoise: 1,
  }, 'Cleaning the frame with FLUX 3');
  node('frame_decode', 'VAEDecode', {samples: ref('frame_sample'), vae: ref('frame_vae')}, 'Decoding the clean frame');
  node('frame_save', 'ZuraPaintoutFrameComposite', {
    patch: ref('frame_crop', 2), image: ref('frame_decode'), match_context: config.match_context !== false,
  }, 'Blending only the painted region');
  return graph;
}

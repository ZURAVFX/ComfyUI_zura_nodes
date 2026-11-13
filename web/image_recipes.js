// Local recipes and the existing Zura browser-account image nodes.
import {applyImageEditArea} from './studio_image_area_graph.js';
import {FLUX3_PROMPT_SYSTEMS} from './flux3_prompt_upsampling.js';
import {editSourceRaster,modelRasterOptions,sourceModelRaster} from './source_model_resolution.js';
export const IMAGE_MODELS = [
  {id:"flux2",maxReferences:4,name:"FLUX.2 Klein 9B",hint:"Detailed images with optional visual references",model:"flux-2-klein-9b-fp8.safetensors",text:"qwen_3_8b_fp4mixed.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:4,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-klein-9B"},
  {id:"flux2bf16",maxReferences:4,name:"FLUX.2 Klein 9B · BF16 test",hint:"Full-precision diffusion weights for comparison. Shares the installed FP4 text encoder and VAE with the FP8 option; slower and may offload on 16 GB GPUs.",model:"flux-2-klein-9b.safetensors",text:"qwen_3_8b_fp4mixed.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:4,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-klein-9B"},
  {id:"flux3",maxReferences:10,name:"Flux 3 Klein",hint:"Detailed scenes and prompt following",model:"flux3-image-klein-int8-convrot.safetensors",text:"qwen3vl_4b_int8_convrot.safetensors",upsampler:"qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors",vae:"flux2-vae.safetensors",type:"flux3",steps:16,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"},
  {id:"flux3bf16",maxReferences:10,name:"Flux 3 Klein · BF16 test",hint:"Full-precision diffusion weights for comparison. Shares the installed INT8 text encoder and VAE with the INT8 option; slower and may offload on 16 GB GPUs.",model:"flux3-image-klein-bf16.safetensors",text:"qwen3vl_4b_int8_convrot.safetensors",upsampler:"qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors",vae:"flux2-vae.safetensors",type:"flux3",steps:16,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"},
  {id:"zimage",maxReferences:0,name:"Z-Image Turbo",hint:"Fast photography and illustration",model:"z_image_turbo_bf16.safetensors",text:"qwen_3_4b.safetensors",vae:"ae.safetensors",type:"lumina2",steps:9,latent:"EmptySD3LatentImage",url:"https://huggingface.co/Comfy-Org/z_image_turbo"},
  {id:"qwen2511",minReferences:1,maxReferences:3,edit:true,name:"Qwen Image Edit 2511",hint:"Edit an image with up to two extra references. Your 4-step Lightning recipe; INT8 with CPU offloading on 16 GB.",model:"qwen_image_edit_2511_int8_convrot.safetensors",text:"qwen_2.5_vl_7b_fp8_scaled.safetensors",vae:"qwen_image_vae.safetensors",type:"qwen_image",steps:4,lora:"Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",url:"https://huggingface.co/Qwen/Qwen-Image-Edit-2511"},
  {id:"ph3edit",minReferences:1,maxReferences:8,edit:true,name:"P-H3 Image",hint:"Edit Image 1 with up to seven references. Uses prompt expansion and eight steps. 4–8 MP is recommended; larger images need more memory and may be slow.",model:"minimax_h3_fl2va_pruned_int8_convrot.safetensors",text:"p-h3-image_text_encoder_int8_convrot.safetensors",upsampler:"p-h3-image_prompt_upsampler_w4a8.safetensors",vae:"p-h3-image_vae_int8_convrot.safetensors",lora:"p-h3-image_lora_bf16.safetensors",type:"minimax",steps:8,sizeStep:32,maxPixels:16*1024*1024,url:"https://huggingface.co/PrunaAI/P-H3-Image-Comfy"},
  {id:"klein9b",minReferences:1,maxReferences:4,edit:true,name:"FLUX Klein 9B",hint:"Full-frame edits and reference-led changes. Your FP8 9B recipe: native Flux 2 scheduling, 4 steps and ordered image references.",model:"flux-2-klein-9b-fp8.safetensors",text:"qwen_3_8b_fp4mixed.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:4,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-klein-9B"},
  {id:"klein9bbf16",minReferences:1,maxReferences:4,edit:true,name:"FLUX Klein 9B · BF16 test",hint:"Full-precision diffusion weights for comparison. Shares the installed FP4 text encoder and VAE with the FP8 option; slower and may offload on 16 GB GPUs.",model:"flux-2-klein-9b.safetensors",text:"qwen_3_8b_fp4mixed.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:4,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-klein-9B"},
  {id:"flux3edit",minReferences:1,maxReferences:10,edit:true,name:"Flux 3 Klein",hint:"Edit Image 1 using your prompt and optional appearance references. Image-aware prompt expansion and the official 16-step recipe.",model:"flux3-image-klein-int8-convrot.safetensors",text:"qwen3vl_4b_int8_convrot.safetensors",upsampler:"qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors",vae:"flux2-vae.safetensors",type:"flux3",steps:16,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"},
  {id:"flux3editbf16",minReferences:1,maxReferences:10,edit:true,name:"Flux 3 Klein · BF16 test",hint:"Full-precision diffusion weights for comparison. Shares the installed INT8 text encoder and VAE with the INT8 option; slower and may offload on 16 GB GPUs.",model:"flux3-image-klein-bf16.safetensors",text:"qwen3vl_4b_int8_convrot.safetensors",upsampler:"qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors",vae:"flux2-vae.safetensors",type:"flux3",steps:16,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"},
  {id:"qwen21edit",minReferences:1,maxReferences:10,edit:true,name:"Qwen Image 2.1 · Preview",hint:"Full 40-step edit with INT8 weights and its own image encoder. Reference cache uses RAM to leave room on a 16 GB GPU. Quality testing in progress.",model:"qwen_image_2.1_int8_convrot.safetensors",text:"qwen3vl_8b_int8_convrot.safetensors",vae:"qwen_image_2.1_vae_bf16.safetensors",type:"qwen_image",steps:40,sizeStep:32,maxDimension:4096,url:"https://huggingface.co/Qwen/Qwen-Image-2.1"},
  {id:"flux2devedit",minReferences:1,maxReferences:4,edit:true,name:"FLUX.2 dev · Preview",hint:"Full FLUX.2 dev, distinct from Klein. 20 steps, NVFP4 weights and Mistral encoder. Uses RAM offloading on 16 GB GPUs and can be slow. Quality testing in progress.",model:"flux2-dev-nvfp4.safetensors",text:"mistral_3_small_flux2_fp8.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:20,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-dev-NVFP4"},
  ...['chatgpt','gemini'].flatMap(provider=>[false,true].map(edit=>({id:provider+(edit?'edit':''),provider,edit,minReferences:edit?1:0,maxReferences:8,name:provider==='chatgpt'?'ChatGPT Image':'Gemini Image',node:provider==='chatgpt'?'ZuraChatGPTImage':'ZuraGeminiImage',hint:'Sign in through your browser. Uses your website account allowance, with no Zura or paid API credits. References are sent to the selected provider.',url:provider==='chatgpt'?'https://chatgpt.com':'https://gemini.google.com'}))),
];
export const IMAGE_SIZES={auto:[1024,1024],square:[1024,1024],landscape:[1152,768],portrait:[768,1152]};
export function imageDimensions({model,shape="square",width,height,references=[],edit_area}={}){
  const preset=IMAGE_SIZES[shape];
  if(!preset)throw new Error("Choose an available image shape.");
  const recipe=IMAGE_MODELS.find(item=>item.id===model);
  if(recipe?.edit&&!recipe.provider&&references[0]){
    const raster=editSourceRaster(references,recipe,{editArea:!!edit_area?.enabled});
    return [raster.width,raster.height];
  }
  const first=references[0];
  if(shape==='auto'&&first?.width&&first?.height){
    const raster=sourceModelRaster(first,modelRasterOptions(recipe));
    return [raster.width,raster.height];
  }
  const size=shape==='auto'?[1024,1024]:[width??preset[0],height??preset[1]];
  if(size.some(v=>!Number.isInteger(v)))throw new Error("Width and height must be whole numbers.");
  if(recipe?.provider)return size;
  const raster=sourceModelRaster({width:size[0],height:size[1]},modelRasterOptions(recipe));
  return [raster.width,raster.height];
}
function buildImageGraphBase({model="flux3",prompt,shape="square",seed=42,width,height,references=[],loras=[],edit_area}={}){
  const recipe=IMAGE_MODELS.find(m=>m.id===model);
  if(!recipe || !IMAGE_SIZES[shape])throw new Error("Choose an available model and image shape.");
  if(typeof prompt!=="string" || !prompt.trim())throw new Error("Describe the image you want to create.");
  if(!recipe.provider&&(!Number.isSafeInteger(seed)||seed<0))throw new Error("Seed must be a positive whole number or zero.");
  if(!Array.isArray(references)||references.length>recipe.maxReferences)throw new Error(`${recipe.name} supports ${recipe.maxReferences} reference images in this workflow.`);
  if(references.length<(recipe.minReferences||0))throw new Error("Add the image you want to edit first. Extra images are optional references.");
  if(references.some(r=>!r||typeof r.file!=="string"||!r.file||r.file.includes("..")))throw new Error("Upload each reference image before generating.");
  const sourceRaster=recipe.edit&&!recipe.provider?editSourceRaster(references,recipe,{editArea:!!edit_area?.enabled}):null;
  [width,height]=sourceRaster?[sourceRaster.width,sourceRaster.height]:imageDimensions({model,shape,width,height,references});
  const restoreSize=sourceRaster?{width:sourceRaster.sourceWidth,height:sourceRaster.sourceHeight}:{width,height};
  if(recipe.provider){
    if(loras.length)throw new Error('Custom LoRAs apply to local image models only.');
    const inputs={prompt:prompt.trim(),size:shape==='auto'?'Auto':'Custom',custom_width:width,custom_height:height,timeout_seconds:300};
    const graph={};references.forEach((ref,i)=>{graph[`reference_${i+1}`]={class_type:'LoadImage',inputs:{image:ref.file}};inputs[`reference_${i+1}`]=[`reference_${i+1}`,0];});
    graph.browser_image={class_type:recipe.node,_meta:{title:`Generate with ${recipe.name} · browser account`},inputs};
    graph.save={class_type:'SaveImage',inputs:{images:['browser_image',0],filename_prefix:'zura_images/'+recipe.provider}};
    return graph;
  }
  const graph={};
  const node=(id,type,title,inputs)=>{graph[id]={class_type:type,_meta:{title},inputs};return [id,0];};
  const sourcePixels=(id,image,title="Align Image 1 to the model grid")=>node(id,"ImageScale",title,{image,upscale_method:"lanczos",width,height,crop:"disabled"});
  const restoreEdit=(id,image)=>recipe.edit?node(id,"ImageScale","Restore captured Image 1 size",{image,upscale_method:"lanczos",width:restoreSize.width,height:restoreSize.height,crop:"disabled"}):image;
  let unet=node("model","UNETLoader",recipe.name,{unet_name:recipe.model,weight_dtype:"default"});
  if(!Array.isArray(loras)||loras.length>4)throw new Error("Choose up to four image LoRAs.");
  for(const [index,lora] of loras.entries()){
    if(!lora || typeof lora.name!=="string" || !lora.name || !Number.isFinite(Number(lora.strength)) || Math.abs(Number(lora.strength))>2)throw new Error("Choose an installed LoRA and a strength between -2 and 2.");
    unet=node(`custom_image_lora_${index+1}`,"LoraLoaderModelOnly",`Image LoRA ${index+1}`,{model:unet,lora_name:lora.name,strength_model:Number(lora.strength)});
  }
  const clip=node("text","CLIPLoader","Text encoder",{clip_name:recipe.text,type:recipe.type,device:"default"});
  const vae=node("vae","VAELoader","Image decoder",{vae_name:recipe.vae});
  if(model==="ph3edit"){
    // Pruna's FL2VA LoRA workflow: bypass loading is required for its quantised base.
    // https://huggingface.co/PrunaAI/P-H3-Image-Comfy/blob/main/workflows/p-h3-image_lora_edit.json
    unet=node("image_adapter","LoraLoaderBypassModelOnly","P-H3 image adapter",{model:unet,lora_name:recipe.lora,strength_model:1});
    unet=node("sampling","MiniMaxH3SigmaShift","P-H3 sampling",{model:unet,shift_video:1,shift_audio:1});
    const images={},batch={};
    node("source_size_pixels","GetImageSize","Source processing dimensions",{image:["source_size",0]});
    references.forEach((ref,i)=>{
      const original=node(`reference_${i+1}`,"LoadImage",i?`Reference ${i+1}`:"Image to edit",{image:ref.file});
      images[`images.image_${i+1}`]=i?original:sourcePixels("source_size",original);
      if(!i){
        batch['images.image0']=["source_size",0];
      }else batch[`images.image${i}`]=sourcePixels(`prompt_reference_${i+1}`,original,`Prompt reference ${i+1} at source raster`);
    });
    const promptImages=node("prompt_images","BatchImagesNode","Ordered prompt references",batch);
    const promptEncoder=node("prompt_encoder","CLIPLoader","Prompt expansion model",{clip_name:recipe.upsampler,type:"minimax",device:"default"});
    const pictureTokens=references.map((_,i)=>`<Picture ${i+1}>: <|vision_start|><|image_pad|><|vision_end|>`).join("");
    const expanded=node("expand_prompt","TextGenerate","Expand edit instruction",{clip:promptEncoder,image:promptImages,prompt:`<|im_start|>user\n${pictureTokens}Edit <Picture 1>. ${prompt.trim()}<|im_end|>\n<|im_start|>assistant\n<think>\n`,max_length:3072,sampling_mode:"off",thinking:false,use_default_template:true,mtp:"auto"});
    const conditioning=node("prompt","PH3ImageConditioning","Source image and edit instruction",{clip,vae,prompt:expanded,width,height,...images});
    const noise=node("noise","RandomNoise","Seed",{noise_seed:seed});
    const guider=node("guider","BasicGuider","P-H3 guidance",{model:unet,conditioning});
    const sampler=node("sampler","KSamplerSelect","Euler",{sampler_name:"euler"});
    const sigmas=node("schedule","ManualSigmas","P-H3 eight-step schedule",{sigmas:"1.0, 0.984753, 0.967905, 0.951688, 0.925372, 0.881923, 0.810083, 0.528718, 0.0"});
    const samples=node("sample","SamplerCustomAdvanced","Edit image",{noise,guider,sampler,sigmas,latent_image:["prompt",1]});
    const image=node("decode","VAEDecode","Decode edited image",{samples,vae});
    node("save","SaveImage","Save edited image",{images:restoreEdit("output_size",image),filename_prefix:"ZURA STUDIO/images/"+model});return graph;
  }
  if(model==="qwen21edit"){
    unet=node("reference_cache","QwenImage21Cache","Reference cache in RAM",{model:unet,device:"cpu",dtype:"default"});
    const images={};
    node("source_size_pixels","GetImageSize","Source processing dimensions",{image:["source_size",0]});
    references.forEach((ref,i)=>{
      let pixels=node(`reference_${i+1}`,"LoadImage",i?`Reference ${i+1}`:"Main image",{image:ref.file});
      pixels=i?sourcePixels(`reference_size_${i+1}`,pixels,`Reference ${i+1} at source raster`):sourcePixels("source_size",pixels);
      images[`images.image_${i+1}`]=pixels;
    });
    node("prompt","TextEncodeQwenImage21","Source image and edit instruction",{clip,vae,prompt:prompt.trim(),negative_prompt:"",resolution:0,...images});
    // The encoder's latent must match its first reference tokens. An unrelated
    // empty latent can shift the edit. Do not apply the older 2511 Lightning LoRA.
    const samples=node("sample","KSampler","Edit image",{model:unet,positive:["prompt",0],negative:["prompt",1],latent_image:["prompt",2],seed,steps:40,cfg:1,sampler_name:"euler",scheduler:"simple",denoise:1});
    const image=node("decode","VAEDecodeTiled","Decode edited image",{samples,vae,tile_size:512,overlap:64,temporal_size:64,temporal_overlap:8});
    node("save","SaveImage","Save edited image",{images:restoreEdit("output_size",image),filename_prefix:"ZURA STUDIO/images/"+model});return graph;
  }
  if(model==="qwen2511"){
    unet=node("lightning","LoraLoaderModelOnly","4-step edit adapter",{model:unet,lora_name:recipe.lora,strength_model:1});
    unet=node("sampling","ModelSamplingAuraFlow","Qwen sampling shift",{model:unet,shift:3.1});
    unet=node("cfg_norm","CFGNorm","Normalised guidance",{model:unet,strength:1});
    const images={};
    node("source_size_pixels","GetImageSize","Source processing dimensions",{image:["source_size",0]});
    references.forEach((ref,i)=>{
      let pixels=node(`reference_${i+1}`,"LoadImage",i?`Reference ${i+1}`:"Image to edit",{image:ref.file});
      pixels=i
        ? sourcePixels(`reference_working_${i+1}`,pixels,`Reference ${i+1} at source raster`)
        : sourcePixels("source_size",pixels);
      images[`image${i+1}`]=pixels;
    });
    // Keep the text encoder on CLIP image tokens only. Feeding it VAE used to
    // resample Image 1 internally to roughly 1 MP, disagreeing with the latent
    // sampled below. Reference latents are attached explicitly instead.
    const positiveBase=node("prompt","TextEncodeQwenImageEditPlus","Edit instruction",{clip,prompt:prompt.trim(),...images});
    const negativeBase=node("negative","TextEncodeQwenImageEditPlus","Negative conditioning",{clip,prompt:"",...images});
    let latent;
    let positive=positiveBase;
    let negative=negativeBase;
    references.forEach((_,i)=>{
      const encoded=node(i?"reference_latent_"+(i+1):"size","VAEEncode",i?`Encode reference ${i+1}`:"Encode source at working size",{pixels:images[`image${i+1}`],vae});
      if(!i)latent=encoded;
      positive=node(`positive_reference_${i+1}`,"ReferenceLatent",`Attach positive reference ${i+1}`,{conditioning:positive,latent:encoded});
      negative=node(`negative_reference_${i+1}`,"ReferenceLatent",`Attach negative reference ${i+1}`,{conditioning:negative,latent:encoded});
    });
    // ComfyUI's official Qwen 2511 blueprint specifies CFG 1 for the
    // four-step Lightning adapter; CFG 4 belongs to the full-step recipe.
    const samples=node("sample","KSampler","Edit image",{model:unet,positive,negative,latent_image:latent,seed,steps:4,cfg:1,sampler_name:"euler",scheduler:"simple",denoise:1});
    const image=node("decode","VAEDecode","Decode edit",{samples,vae});
    const sized=restoreEdit("output_size",image);
    node("save","SaveImage","Save to Zura images",{images:sized,filename_prefix:"zura_images/"+model});return graph;
  }
  const referenceImages=references.map((ref,i)=>{
    const image=node(`reference_${i+1}`,"LoadImage",i?`Reference ${i+1}`:"Image to edit",{image:ref.file});
    return references.length&&!i?sourcePixels("source_size",image):image;
  });
  let instruction=prompt.trim();
  if(recipe.type==="flux3"){
    // Flux 3 is trained on expanded captions. Its official image-aware upsampler
    // is part of the model recipe, rather than sending a short edit request raw.
    // https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy
    const promptEncoder=node("prompt_encoder","CLIPLoader","Flux 3 prompt expansion",{clip_name:recipe.upsampler,type:"flux3",device:"default"});
    const promptInputs={clip:promptEncoder,prompt:references.length?`Reference images follow in order (the first image, the second image, ...).\nUser request: ${instruction}\nOutput the caption.`:instruction,system_prompt:FLUX3_PROMPT_SYSTEMS[references.length?'i2i':'t2i'],max_length:3584,sampling_mode:"on","sampling_mode.temperature":1,"sampling_mode.top_k":1,"sampling_mode.top_p":0.95,"sampling_mode.min_p":0,"sampling_mode.repetition_penalty":1,"sampling_mode.seed":seed,"sampling_mode.presence_penalty":0,thinking:false,use_default_template:true,mtp:"off"};
    if(referenceImages.length){
      // Batches need one shared raster. Stretch each reference to the captured
      // source size; the final edit is restored to the original dimensions.
      const batch={};
      referenceImages.forEach((image,i)=>{batch[`images.image${i}`]=i?sourcePixels(`prompt_reference_${i+1}`,image,`Prompt reference ${i+1} at source raster`):image;});
      promptInputs.image=node("prompt_images","BatchImagesNode","Ordered prompt references",batch);
    }
    instruction=node("expand_prompt","TextGenerate","Understand image edit",promptInputs);
    // The distilled release workflow uses alpha 16 (log shift), independent of size.
    unet=node("sampling","ModelSamplingFlux","Flux 3 distilled sampling",{model:unet,max_shift:Math.log(16),base_shift:Math.log(16),width,height});
  }
  let positive=node("prompt","CLIPTextEncode","Your prompt",{clip,text:instruction});
  let negative=node("negative","ConditioningZeroOut","Distilled guidance",{conditioning:positive});
  let workingReferences=referenceImages;
  if(references.length){
    node("source_size_pixels","GetImageSize","Source processing dimensions",{image:["source_size",0]});
    workingReferences=referenceImages.map((image,i)=>i
      ? sourcePixels(`reference_working_${i+1}`,image,`Reference ${i+1} at source raster`)
      : image);
    const images=Object.fromEntries(workingReferences.map((image,i)=>[`images.image${i}`,image]));
    positive=node("references","ReferenceMultiLatent","Reference images",{positive,negative,vae,resolution:"keep resolution",...images});
    negative=["references",1];
  }
  if(model==="zimage")unet=node("sampling","ModelSamplingAuraFlow","Z-Image sampling",{model:unet,shift:3});
  const latent=references.length?["references",2]:node("size",recipe.latent,"Image size",{width,height,batch_size:1});
  let samples;
  if(model==="klein9b"||model==="klein9bbf16"||model==="flux2"||model==="flux2bf16"||model==="flux2devedit"){
    // This is the regular Klein checkpoint, not the separately trained 9B-KV
    // model. FluxKVCache overrides reference timing/positions and is not valid
    // here. Match the official distilled recipe: retain the model's native
    // reference conditioning throughout all four sampling steps.
    if(model==="flux2devedit")positive=node("guidance","FluxGuidance","FLUX.2 dev guidance",{conditioning:positive,guidance:4});
    const noise=node("noise","RandomNoise","Seed",{noise_seed:seed});
    const guider=node("guider","BasicGuider","Distilled guidance",{model:unet,conditioning:positive});
    const sampler=node("sampler","KSamplerSelect","Euler",{sampler_name:"euler"});
    const sigmas=node("schedule","Flux2Scheduler",`Native ${recipe.steps}-step schedule`,{steps:recipe.steps,width,height});
    samples=node("sample","SamplerCustomAdvanced","Edit image",{noise,guider,sampler,sigmas,latent_image:latent});
  }else samples=node("sample","KSampler","Generate image",{model:unet,positive,negative,latent_image:latent,seed,steps:recipe.steps,cfg:1,sampler_name:"euler",scheduler:"simple",denoise:1});
  const image=node("decode","VAEDecode","Decode image",{samples,vae});
  node("save","SaveImage","Save to Zura images",{images:restoreEdit("output_size",image),filename_prefix:"zura_images/"+model});
  return graph;
}
export function buildImageGraph(config={}){
  const graph=buildImageGraphBase(config.edit_area?.guide?.file?{...config,prompt:'Replace the coloured painted guide itself with the requested object, at exactly the same position and scale. The guide is a placement instruction, not an object to keep. Remove all visible guide paint; do not put a second object beside it. Match the original scene, perspective and lighting. '+config.prompt}:config);
  if(!config.edit_area?.enabled)return graph;
  const model=config.model||'flux3',shape=config.shape||'square';
  const recipe=IMAGE_MODELS.find(item=>item.id===model);
  const [width,height]=imageDimensions({...config,model,shape});
  return applyImageEditArea(graph,{...config,recipe,shape,width,height,references:config.references||[]});
}
export function imageAvailability(info){
  const files=(type,key)=>{const field=info[type]?.input?.required?.[key];return field?.[0]==="COMBO"?field[1]?.options||[]:Array.isArray(field?.[0])?field[0]:[];};
  return IMAGE_MODELS.map(model=>{
    const graph=buildImageGraph({model:model.id,prompt:"Availability check",references:model.minReferences?[{file:"availability-check.png",width:1024,height:1024}]:[]});
    const missing=Object.values(graph).map(n=>n.class_type).filter(type=>!info[type]);
    if(!model.provider){
      for(const [type,key,file] of [["UNETLoader","unet_name",model.model],["CLIPLoader","clip_name",model.text],["VAELoader","vae_name",model.vae]])if(!files(type,key).includes(file))missing.push(file);
      if(!files("CLIPLoader","type").includes(model.type))missing.push(model.type+" text support");
    }
    if(model.upsampler&&!files("CLIPLoader","clip_name").includes(model.upsampler))missing.push(model.upsampler);
    if(model.lora&&!files(model.id==="ph3edit"?"LoraLoaderBypassModelOnly":"LoraLoaderModelOnly","lora_name").includes(model.lora))missing.push(model.lora);
    return {...model,referenceReady:!!info.LoadImage&&(model.provider?!!info[model.node]:model.id==="qwen2511"?!!info.TextEncodeQwenImageEditPlus:model.id==="qwen21edit"?!!info.TextEncodeQwenImage21:model.id==="ph3edit"?!!info.PH3ImageConditioning:!!info.ReferenceMultiLatent),ready:!missing.length,missing:[...new Set(missing)]};
  });
}

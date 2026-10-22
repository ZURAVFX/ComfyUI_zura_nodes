// Native ComfyUI recipes. No additional inference service or paid provider.
export const IMAGE_MODELS = [
  {id:"flux3",maxReferences:10,name:"Flux 3 Klein",hint:"Detailed scenes and prompt following",model:"flux3-image-klein-int8-convrot.safetensors",text:"qwen3vl_4b_int8_convrot.safetensors",vae:"flux2-vae.safetensors",type:"flux3",steps:16,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"},
  {id:"flux2",maxReferences:4,name:"Flux 2 Klein 4B",hint:"Quick concepts and everyday images",model:"flux-2-klein-4b-fp8.safetensors",text:"qwen_3_4b.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:4,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-klein-4B"},
  {id:"zimage",maxReferences:0,name:"Z-Image Turbo",hint:"Fast photography and illustration",model:"z_image_turbo_bf16.safetensors",text:"qwen_3_4b.safetensors",vae:"ae.safetensors",type:"lumina2",steps:9,latent:"EmptySD3LatentImage",url:"https://huggingface.co/Comfy-Org/z_image_turbo"},
  {id:"qwen2511",minReferences:1,maxReferences:3,edit:true,name:"Qwen Image Edit 2511",hint:"Edit an image with up to two extra references. Your 4-step Lightning recipe; INT8 with CPU offloading on 16 GB.",model:"qwen_image_edit_2511_int8_convrot.safetensors",text:"qwen_2.5_vl_7b_fp8_scaled.safetensors",vae:"qwen_image_vae.safetensors",type:"qwen_image",steps:4,lora:"Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",url:"https://huggingface.co/Qwen/Qwen-Image-Edit-2511"},
  {id:"klein9b",minReferences:1,maxReferences:4,edit:true,name:"FLUX Klein 9B",hint:"Full-frame edits and reference-led changes. Your FP8 9B recipe: native Flux 2 scheduling, 4 steps and reference KV cache.",model:"flux-2-klein-9b-fp8.safetensors",text:"qwen_3_8b_fp4mixed.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:4,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-klein-9B"},
];
export const IMAGE_SIZES={square:[1024,1024],landscape:[1152,768],portrait:[768,1152]};
export function imageDimensions({shape="square",width,height}={}){
  const preset=IMAGE_SIZES[shape];
  if(!preset)throw new Error("Choose an available image shape.");
  const size=[width??preset[0],height??preset[1]];
  if(size.some(v=>!Number.isInteger(v)||v<256||v>2048||v%16))throw new Error("Width and height must be 256–2048 px, in multiples of 16.");
  return size;
}
export function buildImageGraph({model="flux3",prompt,shape="square",seed=42,width,height,references=[]}={}){
  const recipe=IMAGE_MODELS.find(m=>m.id===model);
  if(!recipe || !IMAGE_SIZES[shape])throw new Error("Choose an available model and image shape.");
  if(typeof prompt!=="string" || !prompt.trim())throw new Error("Describe the image you want to create.");
  if(!Number.isSafeInteger(seed)||seed<0)throw new Error("Seed must be a positive whole number or zero.");
  if(!Array.isArray(references)||references.length>recipe.maxReferences)throw new Error(`${recipe.name} supports ${recipe.maxReferences} reference images in this workflow.`);
  if(references.length<(recipe.minReferences||0))throw new Error("Add the image you want to edit first. Extra images are optional references.");
  if(references.some(r=>!r||typeof r.file!=="string"||!r.file||r.file.includes("..")))throw new Error("Upload each reference image before generating.");
  [width,height]=imageDimensions({shape,width,height});
  const graph={};
  const node=(id,type,title,inputs)=>{graph[id]={class_type:type,_meta:{title},inputs};return [id,0];};
  let unet=node("model","UNETLoader",recipe.name,{unet_name:recipe.model,weight_dtype:"default"});
  const clip=node("text","CLIPLoader","Text encoder",{clip_name:recipe.text,type:recipe.type,device:"default"});
  const vae=node("vae","VAELoader","Image decoder",{vae_name:recipe.vae});
  if(model==="qwen2511"){
    unet=node("lightning","LoraLoaderModelOnly","4-step edit adapter",{model:unet,lora_name:recipe.lora,strength_model:1});
    unet=node("sampling","ModelSamplingAuraFlow","Qwen sampling shift",{model:unet,shift:3.1});
    unet=node("cfg_norm","CFGNorm","Normalised guidance",{model:unet,strength:1});
    const images={};references.forEach((ref,i)=>{let pixels=node(`reference_${i+1}`,"LoadImage",i?`Reference ${i+1}`:"Image to edit",{image:ref.file});if(!i)pixels=node("source_size","ImageScale","Output dimensions",{image:pixels,upscale_method:"bicubic",width,height,crop:"disabled"});images[`image${i+1}`]=pixels;});
    const pos=node("prompt","TextEncodeQwenImageEditPlus","Edit instruction",{clip,vae,prompt:prompt.trim(),...images});
    const neg=node("negative","TextEncodeQwenImageEditPlus","Negative conditioning",{clip,vae,prompt:"",...images});
    const positive=node("positive_references","FluxKontextMultiReferenceLatentMethod","Qwen reference method",{conditioning:pos,reference_latents_method:"index_timestep_zero"});
    const negative=node("negative_references","FluxKontextMultiReferenceLatentMethod","Qwen negative reference method",{conditioning:neg,reference_latents_method:"index_timestep_zero"});
    const latent=node("size","VAEEncode","Encode source image",{pixels:images.image1,vae});
    const samples=node("sample","KSampler","Edit image",{model:unet,positive,negative,latent_image:latent,seed,steps:4,cfg:4,sampler_name:"euler",scheduler:"simple",denoise:1});
    const image=node("decode","VAEDecode","Decode edit",{samples,vae});
    node("save","SaveImage","Save to Zura images",{images:image,filename_prefix:"zura_images/"+model});return graph;
  }
  let positive=node("prompt","CLIPTextEncode","Your prompt",{clip,text:prompt.trim()});
  let negative=node("negative","ConditioningZeroOut","Distilled guidance",{conditioning:positive});
  if(references.length){
    const images={};references.forEach((ref,i)=>{images[`images.image${i}`]=node(`reference_${i+1}`,"LoadImage",`Reference ${i+1}`,{image:ref.file});});
    positive=node("references","ReferenceMultiLatent","Reference images",{positive,negative,vae,resolution:"resize","resolution.megapixels":Math.min(1,2/references.length),...images});
    negative=["references",1];
  }
  if(model==="zimage")unet=node("sampling","ModelSamplingAuraFlow","Z-Image sampling",{model:unet,shift:3});
  const latent=node("size",recipe.latent,"Image size",{width,height,batch_size:1});
  let samples;
  if(model==="klein9b"){
    unet=node("kv_cache","FluxKVCache","Cache reference attention",{model:unet});
    const noise=node("noise","RandomNoise","Seed",{noise_seed:seed});
    const guider=node("guider","BasicGuider","Distilled guidance",{model:unet,conditioning:positive});
    const sampler=node("sampler","KSamplerSelect","Euler",{sampler_name:"euler"});
    const sigmas=node("schedule","Flux2Scheduler","Native 4-step schedule",{steps:4,width,height});
    samples=node("sample","SamplerCustomAdvanced","Edit image",{noise,guider,sampler,sigmas,latent_image:latent});
  }else samples=node("sample","KSampler","Generate image",{model:unet,positive,negative,latent_image:latent,seed,steps:recipe.steps,cfg:1,sampler_name:"euler",scheduler:"simple",denoise:1});
  const image=node("decode","VAEDecode","Decode image",{samples,vae});
  node("save","SaveImage","Save to Zura images",{images:image,filename_prefix:"zura_images/"+model});
  return graph;
}
export function imageAvailability(info){
  const files=(type,key)=>{const field=info[type]?.input?.required?.[key];return field?.[0]==="COMBO"?field[1]?.options||[]:Array.isArray(field?.[0])?field[0]:[];};
  return IMAGE_MODELS.map(model=>{
    const graph=buildImageGraph({model:model.id,prompt:"Availability check",references:model.minReferences?[{file:"availability-check.png"}]:[]});
    const missing=Object.values(graph).map(n=>n.class_type).filter(type=>!info[type]);
    for(const [type,key,file] of [["UNETLoader","unet_name",model.model],["CLIPLoader","clip_name",model.text],["VAELoader","vae_name",model.vae]])if(!files(type,key).includes(file))missing.push(file);
    if(!files("CLIPLoader","type").includes(model.type))missing.push(model.type+" text support");
    if(model.lora&&!files("LoraLoaderModelOnly","lora_name").includes(model.lora))missing.push(model.lora);
    return {...model,referenceReady:!!info.LoadImage&&(model.id==="qwen2511"?!!info.TextEncodeQwenImageEditPlus:!!info.ReferenceMultiLatent),ready:!missing.length,missing:[...new Set(missing)]};
  });
}

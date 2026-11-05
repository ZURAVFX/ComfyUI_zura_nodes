// Local recipes and the existing Zura browser-account image nodes.
export const IMAGE_MODELS = [
  {id:"flux2",maxReferences:4,name:"FLUX.2 Klein 9B",hint:"Detailed images with optional visual references",model:"flux-2-klein-9b-fp8.safetensors",text:"qwen_3_8b_fp4mixed.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:4,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-klein-9B"},
  {id:"flux3",maxReferences:10,name:"Flux 3 Klein",hint:"Detailed scenes and prompt following",model:"flux3-image-klein-int8-convrot.safetensors",text:"qwen3vl_4b_int8_convrot.safetensors",vae:"flux2-vae.safetensors",type:"flux3",steps:16,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"},
  {id:"zimage",maxReferences:0,name:"Z-Image Turbo",hint:"Fast photography and illustration",model:"z_image_turbo_bf16.safetensors",text:"qwen_3_4b.safetensors",vae:"ae.safetensors",type:"lumina2",steps:9,latent:"EmptySD3LatentImage",url:"https://huggingface.co/Comfy-Org/z_image_turbo"},
  {id:"qwen2511",minReferences:1,maxReferences:3,edit:true,name:"Qwen Image Edit 2511",hint:"Edit an image with up to two extra references. Your 4-step Lightning recipe; INT8 with CPU offloading on 16 GB.",model:"qwen_image_edit_2511_int8_convrot.safetensors",text:"qwen_2.5_vl_7b_fp8_scaled.safetensors",vae:"qwen_image_vae.safetensors",type:"qwen_image",steps:4,lora:"Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",url:"https://huggingface.co/Qwen/Qwen-Image-Edit-2511"},
  {id:"klein9b",minReferences:1,maxReferences:4,edit:true,name:"FLUX Klein 9B",hint:"Full-frame edits and reference-led changes. Your FP8 9B recipe: native Flux 2 scheduling, 4 steps and ordered image references.",model:"flux-2-klein-9b-fp8.safetensors",text:"qwen_3_8b_fp4mixed.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:4,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-klein-9B"},
  {id:"flux3edit",minReferences:1,maxReferences:10,edit:true,name:"Flux 3 Klein",hint:"Edit Image 1 using your prompt and optional appearance references. Native INT8 recipe, 16 steps.",model:"flux3-image-klein-int8-convrot.safetensors",text:"qwen3vl_4b_int8_convrot.safetensors",vae:"flux2-vae.safetensors",type:"flux3",steps:16,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"},
  {id:"qwen21edit",minReferences:1,maxReferences:10,edit:true,name:"Qwen Image 2.1 · Preview",hint:"Full 40-step edit with INT8 weights and its own image encoder. Reference cache uses RAM to leave room on a 16 GB GPU. Quality testing in progress.",model:"qwen_image_2.1_int8_convrot.safetensors",text:"qwen3vl_8b_int8_convrot.safetensors",vae:"qwen_image_2.1_vae_bf16.safetensors",type:"qwen_image",steps:40,sizeStep:32,url:"https://huggingface.co/Qwen/Qwen-Image-2.1"},
  {id:"flux2devedit",minReferences:1,maxReferences:4,edit:true,name:"FLUX.2 dev · Preview",hint:"Full FLUX.2 dev, distinct from Klein. 20 steps, NVFP4 weights and Mistral encoder. Uses RAM offloading on 16 GB GPUs and can be slow. Quality testing in progress.",model:"flux2-dev-nvfp4.safetensors",text:"mistral_3_small_flux2_fp8.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:20,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-dev-NVFP4"},
  ...['chatgpt','gemini'].flatMap(provider=>[false,true].map(edit=>({id:provider+(edit?'edit':''),provider,edit,minReferences:edit?1:0,maxReferences:8,name:provider==='chatgpt'?'ChatGPT Image':'Gemini Image',node:provider==='chatgpt'?'ZuraChatGPTImage':'ZuraGeminiImage',hint:'Sign in through your browser. Uses your website account allowance, with no Zura or paid API credits. References are sent to the selected provider.',url:provider==='chatgpt'?'https://chatgpt.com':'https://gemini.google.com'}))),
];
export const IMAGE_SIZES={auto:[1024,1024],square:[1024,1024],landscape:[1152,768],portrait:[768,1152]};
export function imageDimensions({model,shape="square",width,height,references=[]}={}){
  const preset=IMAGE_SIZES[shape];
  if(!preset)throw new Error("Choose an available image shape.");
  const first=references[0];
  const size=shape==='auto'?[first?.width||1024,first?.height||1024].map(v=>Math.max(256,Math.round(v/16)*16)):[width??preset[0],height??preset[1]];
  if(size.some(v=>!Number.isInteger(v)||v<256||v>8192||v%16))throw new Error("Width and height must be 256–8192 px, in multiples of 16.");
  const step=IMAGE_MODELS.find(m=>m.id===model)?.sizeStep||16;
  return size.map(v=>Math.round(v/step)*step);
}
export function buildImageGraph({model="flux3",prompt,shape="square",seed=42,width,height,references=[],loras=[]}={}){
  const recipe=IMAGE_MODELS.find(m=>m.id===model);
  if(!recipe || !IMAGE_SIZES[shape])throw new Error("Choose an available model and image shape.");
  if(typeof prompt!=="string" || !prompt.trim())throw new Error("Describe the image you want to create.");
  if(!recipe.provider&&(!Number.isSafeInteger(seed)||seed<0))throw new Error("Seed must be a positive whole number or zero.");
  if(!Array.isArray(references)||references.length>recipe.maxReferences)throw new Error(`${recipe.name} supports ${recipe.maxReferences} reference images in this workflow.`);
  if(references.length<(recipe.minReferences||0))throw new Error("Add the image you want to edit first. Extra images are optional references.");
  if(references.some(r=>!r||typeof r.file!=="string"||!r.file||r.file.includes("..")))throw new Error("Upload each reference image before generating.");
  [width,height]=imageDimensions({model,shape,width,height,references});
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
  let unet=node("model","UNETLoader",recipe.name,{unet_name:recipe.model,weight_dtype:"default"});
  if(!Array.isArray(loras)||loras.length>4)throw new Error("Choose up to four image LoRAs.");
  for(const [index,lora] of loras.entries()){
    if(!lora || typeof lora.name!=="string" || !lora.name || !Number.isFinite(Number(lora.strength)) || Math.abs(Number(lora.strength))>2)throw new Error("Choose an installed LoRA and a strength between -2 and 2.");
    unet=node(`custom_image_lora_${index+1}`,"LoraLoaderModelOnly",`Image LoRA ${index+1}`,{model:unet,lora_name:lora.name,strength_model:Number(lora.strength)});
  }
  const clip=node("text","CLIPLoader","Text encoder",{clip_name:recipe.text,type:recipe.type,device:"default"});
  const vae=node("vae","VAELoader","Image decoder",{vae_name:recipe.vae});
  if(model==="qwen21edit"){
    unet=node("reference_cache","QwenImage21Cache","Reference cache in RAM",{model:unet,device:"cpu",dtype:"default"});
    const images={};references.forEach((ref,i)=>{
      let pixels=node(`reference_${i+1}`,"LoadImage",i?`Reference ${i+1}`:"Main image",{image:ref.file});
      pixels=i?node(`reference_size_${i+1}`,"ImageScaleToTotalPixels","Reference size",{image:pixels,upscale_method:"lanczos",megapixels:Math.min(1,2/Math.max(1,references.length-1)),resolution_steps:32}):node("source_size","ImageScale","Output dimensions",{image:pixels,upscale_method:"lanczos",width,height,crop:"disabled"});
      images[`images.image_${i+1}`]=pixels;
    });
    node("prompt","TextEncodeQwenImage21","Source image and edit instruction",{clip,vae,prompt:prompt.trim(),negative_prompt:"",resolution:0,...images});
    // The encoder's latent must match its first reference tokens. An unrelated
    // empty latent can shift the edit. Do not apply the older 2511 Lightning LoRA.
    const samples=node("sample","KSampler","Edit image",{model:unet,positive:["prompt",0],negative:["prompt",1],latent_image:["prompt",2],seed,steps:40,cfg:1,sampler_name:"euler",scheduler:"simple",denoise:1});
    const image=node("decode","VAEDecodeTiled","Decode edited image",{samples,vae,tile_size:512,overlap:64,temporal_size:64,temporal_overlap:8});
    node("save","SaveImage","Save edited image",{images:image,filename_prefix:"ZURA STUDIO/images/"+model});return graph;
  }
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
  if(model==="klein9b"||model==="flux2"||model==="flux2devedit"){
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
  node("save","SaveImage","Save to Zura images",{images:image,filename_prefix:"zura_images/"+model});
  return graph;
}
export function imageAvailability(info){
  const files=(type,key)=>{const field=info[type]?.input?.required?.[key];return field?.[0]==="COMBO"?field[1]?.options||[]:Array.isArray(field?.[0])?field[0]:[];};
  return IMAGE_MODELS.map(model=>{
    const graph=buildImageGraph({model:model.id,prompt:"Availability check",references:model.minReferences?[{file:"availability-check.png"}]:[]});
    const missing=Object.values(graph).map(n=>n.class_type).filter(type=>!info[type]);
    if(!model.provider){
      for(const [type,key,file] of [["UNETLoader","unet_name",model.model],["CLIPLoader","clip_name",model.text],["VAELoader","vae_name",model.vae]])if(!files(type,key).includes(file))missing.push(file);
      if(!files("CLIPLoader","type").includes(model.type))missing.push(model.type+" text support");
    }
    if(model.lora&&!files("LoraLoaderModelOnly","lora_name").includes(model.lora))missing.push(model.lora);
    return {...model,referenceReady:!!info.LoadImage&&(model.provider?!!info[model.node]:model.id==="qwen2511"?!!info.TextEncodeQwenImageEditPlus:model.id==="qwen21edit"?!!info.TextEncodeQwenImage21:!!info.ReferenceMultiLatent),ready:!missing.length,missing:[...new Set(missing)]};
  });
}

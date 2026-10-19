// Native ComfyUI recipes. No additional inference service or paid provider.
export const IMAGE_MODELS = [
  {id:"flux3",maxReferences:10,name:"Flux 3 Klein",hint:"Detailed scenes and prompt following",model:"flux3-image-klein-int8-convrot.safetensors",text:"qwen3vl_4b_int8_convrot.safetensors",vae:"flux2-vae.safetensors",type:"flux3",steps:16,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"},
  {id:"flux2",maxReferences:4,name:"Flux 2 Klein 4B",hint:"Quick concepts and everyday images",model:"flux-2-klein-4b-fp8.safetensors",text:"qwen_3_4b.safetensors",vae:"flux2-vae.safetensors",type:"flux2",steps:4,latent:"EmptyFlux2LatentImage",url:"https://huggingface.co/black-forest-labs/FLUX.2-klein-4B"},
  {id:"zimage",maxReferences:0,name:"Z-Image Turbo",hint:"Fast photography and illustration",model:"z_image_turbo_bf16.safetensors",text:"qwen_3_4b.safetensors",vae:"ae.safetensors",type:"lumina2",steps:9,latent:"EmptySD3LatentImage",url:"https://huggingface.co/Comfy-Org/z_image_turbo"},
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
  if(references.some(r=>!r||typeof r.file!=="string"||!r.file||r.file.includes("..")))throw new Error("Upload each reference image before generating.");
  [width,height]=imageDimensions({shape,width,height});
  const graph={};
  const node=(id,type,title,inputs)=>{graph[id]={class_type:type,_meta:{title},inputs};return [id,0];};
  let unet=node("model","UNETLoader",recipe.name,{unet_name:recipe.model,weight_dtype:"default"});
  const clip=node("text","CLIPLoader","Text encoder",{clip_name:recipe.text,type:recipe.type,device:"default"});
  const vae=node("vae","VAELoader","Image decoder",{vae_name:recipe.vae});
  let positive=node("prompt","CLIPTextEncode","Your prompt",{clip,text:prompt.trim()});
  let negative=node("negative","ConditioningZeroOut","Distilled guidance",{conditioning:positive});
  if(references.length){
    const images={};references.forEach((ref,i)=>{images[`images.image${i}`]=node(`reference_${i+1}`,"LoadImage",`Reference ${i+1}`,{image:ref.file});});
    positive=node("references","ReferenceMultiLatent","Reference images",{positive,negative,vae,resolution:"resize","resolution.megapixels":Math.min(1,2/references.length),...images});
    negative=["references",1];
  }
  if(model==="zimage")unet=node("sampling","ModelSamplingAuraFlow","Z-Image sampling",{model:unet,shift:3});
  const latent=node("size",recipe.latent,"Image size",{width,height,batch_size:1});
  const samples=node("sample","KSampler","Generate image",{model:unet,positive,negative,latent_image:latent,seed,steps:recipe.steps,cfg:1,sampler_name:"euler",scheduler:"simple",denoise:1});
  const image=node("decode","VAEDecode","Decode image",{samples,vae});
  node("save","SaveImage","Save to Zura images",{images:image,filename_prefix:"zura_images/"+model});
  return graph;
}
export function imageAvailability(info){
  const files=(type,key)=>info[type]?.input?.required?.[key]?.[0] || [];
  return IMAGE_MODELS.map(model=>{
    const graph=buildImageGraph({model:model.id,prompt:"Availability check"});
    const missing=Object.values(graph).map(n=>n.class_type).filter(type=>!info[type]);
    for(const [type,key,file] of [["UNETLoader","unet_name",model.model],["CLIPLoader","clip_name",model.text],["VAELoader","vae_name",model.vae]])if(!files(type,key).includes(file))missing.push(file);
    if(!files("CLIPLoader","type").includes(model.type))missing.push(model.type+" text support");
    return {...model,referenceReady:!!info.ReferenceMultiLatent&&!!info.LoadImage,ready:!missing.length,missing:[...new Set(missing)]};
  });
}

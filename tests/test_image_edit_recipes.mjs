import assert from 'node:assert/strict';
import {IMAGE_MODELS,buildImageGraph,imageAvailability} from '../web/image_recipes.js';
import {FLUX3_PROMPT_SYSTEMS} from '../web/flux3_prompt_upsampling.js';
const refs=[{file:'edit/source.png',width:1280,height:720},{file:'edit/style.png',width:768,height:768},{file:'edit/subject.png',width:512,height:512}];
const create=buildImageGraph({model:'flux2',prompt:'A natural portrait',width:1024,height:1024});
assert.equal(create.model.inputs.unet_name,'flux-2-klein-9b-fp8.safetensors');
assert.equal(create.text.inputs.clip_name,'qwen_3_8b_fp4mixed.safetensors');
assert.equal(create.schedule.class_type,'Flux2Scheduler');
assert.equal(create.schedule.inputs.steps,4);assert.ok(!create.kv_cache);assert.deepEqual(create.guider.inputs.model,['model',0]);
assert.equal(IMAGE_MODELS.find(m=>m.id==='flux3').name,'Flux 3 Klein','Flux 3 remains available');
for(const model of ['qwen2511','klein9b','flux3edit']){
  assert.throws(()=>buildImageGraph({model,prompt:'Edit the image'}),/image you want to edit/);
  assert.throws(()=>buildImageGraph({model,prompt:'Edit',references:[{file:'../escape.png'}]}),/Upload/);
  const graph=buildImageGraph({model,prompt:'  Make the wall blue  ',references:refs,width:1280,height:720,seed:17});
  for(const node of Object.values(graph))for(const value of Object.values(node.inputs))if(Array.isArray(value))assert.ok(graph[value[0]],`Closed graph link: ${value[0]}`);
  assert.equal(graph.model.inputs.unet_name,IMAGE_MODELS.find(m=>m.id===model).model);
  assert.equal(graph.reference_1.inputs.image,'edit/source.png');
  assert.equal(graph.reference_3.inputs.image,'edit/subject.png');
  assert.ok(!Object.values(graph).some(n=>/API|Partner/.test(n.class_type)));
  if(model==='qwen2511'){
    assert.equal(graph.lightning.inputs.strength_model,1);
    assert.equal(graph.sample.inputs.steps,4);assert.equal(graph.sample.inputs.cfg,1,'Qwen Lightning uses its distilled CFG rather than the full-step recipe');
    assert.equal(graph.sampling.inputs.shift,3.1);assert.equal(graph.cfg_norm.inputs.strength,1);
    assert.equal(graph.prompt.inputs.prompt,'Make the wall blue');assert.equal(graph.negative.inputs.prompt,'');
    assert.deepEqual(graph.prompt.inputs.image1,['source_size',0]);assert.ok(!Object.hasOwn(graph.prompt.inputs,'vae'));
    assert.equal(graph.size.class_type,'VAEEncode');assert.deepEqual(graph.size.inputs.pixels,['source_size',0]);
    assert.equal(graph.positive_reference_1.class_type,'ReferenceLatent');assert.deepEqual(graph.positive_reference_1.inputs.latent,['size',0]);
    assert.deepEqual(graph.sample.inputs.positive,['positive_reference_3',0]);assert.deepEqual(graph.sample.inputs.negative,['negative_reference_3',0]);
    assert.equal(graph.source_size.class_type,'ImageScale');
    assert.equal(graph.source_size.inputs.width,1280);assert.equal(graph.source_size.inputs.height,720);
    assert.equal(graph.source_size.inputs.crop,'disabled');assert.equal(graph.source_size.inputs.upscale_method,'lanczos');
    assert.equal(graph.output_size.inputs.width,1280);assert.equal(graph.output_size.inputs.height,720);assert.equal(graph.output_size.inputs.crop,'disabled');
    assert.deepEqual(graph.save.inputs.images,['output_size',0]);
  }else if(model==='klein9b'){
    assert.equal(graph.sample.class_type,'SamplerCustomAdvanced');
    assert.deepEqual(graph.schedule.inputs,{steps:4,width:1280,height:720});
    assert.ok(!Object.values(graph).some(n=>n.class_type==='FluxKVCache'),'Regular Klein must not receive the separately trained KV model patch');assert.deepEqual(graph.guider.inputs.model,['model',0]);assert.equal(graph.noise.inputs.noise_seed,17);
  }else{
    assert.equal(graph.text.inputs.type,'flux3');assert.equal(graph.sample.inputs.steps,16);
    assert.deepEqual(graph.sample.inputs.positive,['references',0]);
    assert.deepEqual(graph.sample.inputs.latent_image,['references',2]);
    assert.deepEqual(graph.references.inputs['images.image0'],['source_size',0]);
  }
}
// Image LoRAs precede each model's existing optimisations and reach the sampler.
for(const model of ['flux2','flux3','flux3edit','klein9b','qwen2511','zimage']){
  const graph=buildImageGraph({model,prompt:'Check',references:IMAGE_MODELS.find(m=>m.id===model).minReferences?[refs[0]]:[],loras:[{name:'face.safetensors',strength:.75}]});
  assert.deepEqual(graph.custom_image_lora_1.inputs.model,['model',0]);
  const consumer=model==='qwen2511'?graph.lightning:model==='flux2'||model==='klein9b'?graph.guider:model==='zimage'||model.startsWith('flux3')?graph.sampling:graph.sample;
  assert.deepEqual(consumer.inputs.model,['custom_image_lora_1',0]);
}
assert.throws(()=>buildImageGraph({model:'flux2',prompt:'Check',loras:[{name:'x',strength:3}]}),/strength/);
// ComfyUI's current COMBO schema and its earlier array schema both resolve.
const info={};
for(const m of IMAGE_MODELS)for(const n of Object.values(buildImageGraph({model:m.id,prompt:'Check',references:m.minReferences?[refs[0]]:[]})))info[n.class_type]={input:{required:{}}};
const combo=options=>['COMBO',{options}];
info.UNETLoader.input.required.unet_name=combo(IMAGE_MODELS.map(m=>m.model));
info.CLIPLoader.input.required={clip_name:combo(IMAGE_MODELS.flatMap(m=>[m.text,m.upsampler].filter(Boolean))),type:combo(IMAGE_MODELS.map(m=>m.type))};
info.VAELoader.input.required.vae_name=combo(IMAGE_MODELS.map(m=>m.vae));
info.LoraLoaderModelOnly.input.required.lora_name=combo(IMAGE_MODELS.map(m=>m.lora).filter(Boolean));
info.LoraLoaderBypassModelOnly.input.required.lora_name=combo(IMAGE_MODELS.map(m=>m.lora).filter(Boolean));
assert.ok(imageAvailability(info).every(m=>m.ready));
info.LoraLoaderModelOnly.input.required.lora_name=combo([]);
assert.equal(imageAvailability(info).find(m=>m.id==='qwen2511').ready,false,'Missing Lightning adapter blocks Qwen rather than changing its recipe');
console.log('Qwen 2511 and Klein 9B artist recipes: ordered edit references, native sampling, dimensions, readiness and local-only graphs pass.');

for(const model of IMAGE_MODELS.filter(m=>m.provider)){
 const references=model.edit?refs:[];
 const graph=buildImageGraph({model:model.id,prompt:' Draw this ',references,width:1152,height:768});
 assert.equal(graph.browser_image.class_type,model.node);assert.equal(graph.browser_image.inputs.prompt,'Draw this');
 assert.equal(graph.browser_image.inputs.custom_width,1152);assert.equal(graph.browser_image.inputs.custom_height,768);
 assert.equal(graph.browser_image.inputs.size,'Custom');assert.deepEqual(graph.save.inputs.images,['browser_image',0]);
 assert.ok(!graph.model&&!graph.text&&!graph.sample&&!graph.vae);
 assert.doesNotThrow(()=>buildImageGraph({model:model.id,prompt:'Draw',references,seed:NaN}),'Browser models do not expose local seeds');
 if(model.edit){assert.deepEqual(graph.browser_image.inputs.reference_1,['reference_1',0]);assert.throws(()=>buildImageGraph({model:model.id,prompt:'Edit'}),/image you want to edit/);}
 assert.throws(()=>buildImageGraph({model:model.id,prompt:'Draw',references,loras:[{name:'x',strength:1}]}),/LoRA/);
 assert.throws(()=>buildImageGraph({model:model.id,prompt:'Draw',references:Array.from({length:9},()=>refs[0])}),/8/);
 const withoutProvider={...info};delete withoutProvider[model.node];assert.equal(imageAvailability(withoutProvider).find(m=>m.id===model.id).ready,false);
}
console.log('Browser create/edit recipes: ordered references, limits, requested size, no local model or API-key inputs pass.');

// Preview editors retain their own conditioning, precision and sampler recipe.
for (const model of ['qwen21edit','flux2devedit']) {
  assert.throws(()=>buildImageGraph({model,prompt:'Edit'}),/image you want to edit/);
  const g=buildImageGraph({model,prompt:'Change only the coat',references:refs,width:1280,height:720,seed:17});
  assert.equal(g.reference_1.inputs.image,'edit/source.png');
  assert.equal(g.reference_3.inputs.image,'edit/subject.png');
  assert.ok(!g.lightning && !g.kv_cache);
  if(model==='qwen21edit') {
    assert.equal(g.prompt.class_type,'TextEncodeQwenImage21');
    assert.deepEqual(g.prompt.inputs['images.image_1'],['source_size',0]);
    assert.deepEqual(g.sample.inputs.latent_image,['prompt',2]);
    assert.equal(g.source_size.class_type,'ImageScale');
    assert.equal(g.source_size.inputs.width,1280);
    assert.equal(g.source_size.inputs.height,736);
    assert.equal(g.sample.inputs.steps,40);
    assert.equal(g.reference_cache.inputs.device,'cpu');
    assert.equal(g.reference_cache.inputs.dtype,'default');
  } else {
    assert.equal(g.model.inputs.unet_name,'flux2-dev-nvfp4.safetensors');
    assert.equal(g.text.inputs.clip_name,'mistral_3_small_flux2_fp8.safetensors');
    assert.equal(g.schedule.inputs.steps,20);
    assert.ok(Object.values(g).some(n=>n.class_type==='FluxGuidance'&&n.inputs.guidance===4));
    assert.deepEqual(g.sample.inputs.latent_image,['references',2]);
  }
  const missingEncoder=structuredClone(info);
  missingEncoder.CLIPLoader.input.required.clip_name=combo(IMAGE_MODELS.filter(m=>m.id!==model).map(m=>m.text));
  assert.equal(imageAvailability(missingEncoder).find(m=>m.id===model).ready,false);
}
console.log('Qwen 2.1 and full FLUX.2 dev native edit recipes pass.');

// Flux 3's released checkpoint expects its image-aware caption stage and alpha-16 shift.
for(const model of ['flux3','flux3bf16','flux3edit','flux3editbf16']){
  const g=buildImageGraph({model,prompt:'Replace the walking person with the reference character',references:refs,seed:17,width:1280,height:720});
  assert.equal(g.prompt_encoder.inputs.clip_name,'qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors');
  assert.equal(g.prompt_encoder.inputs.type,'flux3');
  assert.equal(g.expand_prompt.class_type,'TextGenerate');
  assert.equal(g.expand_prompt.inputs.system_prompt,FLUX3_PROMPT_SYSTEMS.i2i);
  assert.match(g.expand_prompt.inputs.prompt,/User request: Replace the walking person/);
  assert.deepEqual(g.prompt.inputs.text,['expand_prompt',0]);
  assert.deepEqual(g.expand_prompt.inputs.image,['prompt_images',0]);
  assert.deepEqual(g.prompt_images.inputs['images.image0'],['source_size',0]);
  assert.deepEqual(g.prompt_images.inputs['images.image1'],['prompt_reference_2',0]);
  assert.deepEqual(g.prompt_reference_2.inputs.image,['reference_2',0]);
  assert.equal(g.prompt_reference_2.class_type,'ImageScale');
  assert.equal(g.prompt_reference_2.inputs.width,1280);
  assert.equal(g.prompt_reference_2.inputs.height,720);
  assert.equal(g.prompt_reference_2.inputs.crop,'disabled');
  assert.deepEqual(g.references.inputs['images.image1'],['reference_working_2',0],'Diffusion sees the same source raster as prompt and sampling');
  assert.equal(g.expand_prompt.inputs['sampling_mode.seed'],17);
  assert.equal(g.expand_prompt.inputs.max_length,3584);
  assert.equal(g.expand_prompt.inputs.mtp,'off');
  assert.equal(g.sampling.inputs.max_shift,Math.log(16));
  assert.equal(g.sampling.inputs.base_shift,Math.log(16));
  assert.deepEqual(g.sample.inputs.model,['sampling',0]);
  assert.equal(g.sample.inputs.cfg,1);assert.equal(g.sample.inputs.steps,16);
}
const textFlux3=buildImageGraph({model:'flux3',prompt:'A room'});
assert.equal(textFlux3.expand_prompt.inputs.system_prompt,FLUX3_PROMPT_SYSTEMS.t2i);
assert.equal(textFlux3.expand_prompt.inputs.prompt,'A room');
assert.ok(!textFlux3.prompt_images);
const noFlux3Upsampler=structuredClone(info);
noFlux3Upsampler.CLIPLoader.input.required.clip_name=combo(IMAGE_MODELS.flatMap(m=>[m.text,m.id.startsWith('flux3')?null:m.upsampler].filter(Boolean)));
for(const model of imageAvailability(noFlux3Upsampler).filter(m=>m.id.startsWith('flux3'))){
  assert.equal(model.ready,false);assert.ok(model.missing.includes(model.upsampler));
}
const noPromptNode=structuredClone(info);delete noPromptNode.TextGenerate;
assert.equal(imageAvailability(noPromptNode).find(m=>m.id==='flux3edit').ready,false);
console.log('Flux 3 official prompt expansion, ordered full references, sampler shift and readiness checks pass.');

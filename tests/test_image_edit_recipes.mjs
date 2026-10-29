import assert from 'node:assert/strict';
import {IMAGE_MODELS,buildImageGraph,imageAvailability} from '../web/image_recipes.js';
const refs=[{file:'edit/source.png'},{file:'edit/style.png'},{file:'edit/subject.png'}];
const create=buildImageGraph({model:'flux2',prompt:'A natural portrait',width:1024,height:1024});
assert.equal(create.model.inputs.unet_name,'flux-2-klein-9b-fp8.safetensors');
assert.equal(create.text.inputs.clip_name,'qwen_3_8b_fp4mixed.safetensors');
assert.equal(create.schedule.class_type,'Flux2Scheduler');
assert.equal(create.schedule.inputs.steps,4);
assert.equal(IMAGE_MODELS.find(m=>m.id==='flux3').name,'Flux 3 Klein','Flux 3 remains available');
for(const model of ['qwen2511','klein9b']){
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
    assert.equal(graph.sample.inputs.steps,4);assert.equal(graph.sample.inputs.cfg,4);
    assert.equal(graph.sampling.inputs.shift,3.1);assert.equal(graph.cfg_norm.inputs.strength,1);
    assert.equal(graph.prompt.inputs.prompt,'Make the wall blue');assert.equal(graph.negative.inputs.prompt,'');
    assert.deepEqual(graph.prompt.inputs.image1,['source_size',0]);assert.deepEqual(graph.size.inputs.pixels,['source_size',0]);
    assert.equal(graph.source_size.inputs.width,1280);assert.equal(graph.source_size.inputs.height,720);
    assert.equal(graph.positive_references.inputs.reference_latents_method,'index_timestep_zero');
  }else{
    assert.equal(graph.sample.class_type,'SamplerCustomAdvanced');
    assert.deepEqual(graph.schedule.inputs,{steps:4,width:1280,height:720});
    assert.equal(graph.kv_cache.class_type,'FluxKVCache');assert.equal(graph.noise.inputs.noise_seed,17);
  }
}
// Image LoRAs precede each model's existing optimisations and reach the sampler.
for(const model of ['flux2','flux3','klein9b','qwen2511','zimage']){
  const graph=buildImageGraph({model,prompt:'Check',references:IMAGE_MODELS.find(m=>m.id===model).minReferences?[refs[0]]:[],loras:[{name:'face.safetensors',strength:.75}]});
  assert.deepEqual(graph.custom_image_lora_1.inputs.model,['model',0]);
  const consumer=model==='qwen2511'?graph.lightning:model==='flux2'||model==='klein9b'?graph.kv_cache:model==='zimage'?graph.sampling:graph.sample;
  assert.deepEqual(consumer.inputs.model,['custom_image_lora_1',0]);
}
assert.throws(()=>buildImageGraph({model:'flux2',prompt:'Check',loras:[{name:'x',strength:3}]}),/strength/);
// ComfyUI's current COMBO schema and its earlier array schema both resolve.
const info={};
for(const m of IMAGE_MODELS)for(const n of Object.values(buildImageGraph({model:m.id,prompt:'Check',references:m.minReferences?[refs[0]]:[]})))info[n.class_type]={input:{required:{}}};
const combo=options=>['COMBO',{options}];
info.UNETLoader.input.required.unet_name=combo(IMAGE_MODELS.map(m=>m.model));
info.CLIPLoader.input.required={clip_name:combo(IMAGE_MODELS.map(m=>m.text)),type:combo(IMAGE_MODELS.map(m=>m.type))};
info.VAELoader.input.required.vae_name=combo(IMAGE_MODELS.map(m=>m.vae));
info.LoraLoaderModelOnly.input.required.lora_name=combo(IMAGE_MODELS.map(m=>m.lora).filter(Boolean));
assert.ok(imageAvailability(info).every(m=>m.ready));
info.LoraLoaderModelOnly.input.required.lora_name=combo([]);
assert.equal(imageAvailability(info).find(m=>m.id==='qwen2511').ready,false,'Missing Lightning adapter blocks Qwen rather than changing its recipe');
console.log('Qwen 2511 and Klein 9B artist recipes: ordered edit references, native sampling, dimensions, readiness and local-only graphs pass.');

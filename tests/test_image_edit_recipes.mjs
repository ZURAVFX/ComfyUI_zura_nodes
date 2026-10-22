import assert from 'node:assert/strict';
import {IMAGE_MODELS,buildImageGraph,imageAvailability} from '../web/image_recipes.js';
const refs=[{file:'edit/source.png'},{file:'edit/style.png'},{file:'edit/subject.png'}];
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

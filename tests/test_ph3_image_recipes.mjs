import assert from 'node:assert/strict';
import {IMAGE_MODELS,buildImageGraph,imageAvailability,imageDimensions} from '../web/image_recipes.js';

const model=IMAGE_MODELS.find(m=>m.id==='ph3edit');
const refs=Array.from({length:8},(_,i)=>({file:`source/image${i+1}.png`,width:1136,height:1760}));
assert.equal(model.maxReferences,8);
assert.throws(()=>buildImageGraph({model:model.id,prompt:'Edit'}),/image you want to edit/);
assert.throws(()=>buildImageGraph({model:model.id,prompt:'Edit',references:[...refs,refs[0]]}),/8/);
assert.deepEqual(imageDimensions({model:model.id,shape:'auto',references:refs}),[1152,1760]);
const graph=buildImageGraph({model:model.id,prompt:'Replace the hat',references:refs,shape:'auto',seed:17});
assert.equal(graph.model.inputs.unet_name,'minimax_h3_fl2va_pruned_int8_convrot.safetensors');
assert.equal(graph.image_adapter.class_type,'LoraLoaderBypassModelOnly');
assert.equal(graph.image_adapter.inputs.lora_name,model.lora);
assert.deepEqual([graph.sampling.inputs.shift_video,graph.sampling.inputs.shift_audio],[1,1]);
assert.deepEqual(graph.prompt.inputs['images.image_1'],['source_size',0]);
assert.deepEqual(graph.prompt.inputs['images.image_8'],['reference_8',0]);
assert.deepEqual(graph.prompt_images.inputs['images.image0'],['source_size',0]);
assert.deepEqual(graph.prompt_images.inputs['images.image7'],['prompt_reference_8',0]);
assert.equal(graph.expand_prompt.inputs.sampling_mode,'off');
assert.equal((graph.expand_prompt.inputs.prompt.match(/<\|image_pad\|>/g)||[]).length,8);
assert.match(graph.expand_prompt.inputs.prompt,/Edit <Picture 1>\. Replace the hat/);
assert.deepEqual(graph.prompt.inputs.prompt,['expand_prompt',0]);
assert.equal(graph.schedule.inputs.sigmas,'1.0, 0.984753, 0.967905, 0.951688, 0.925372, 0.881923, 0.810083, 0.528718, 0.0');
assert.deepEqual(graph.sample.inputs.latent_image,['prompt',1]);
assert.deepEqual(graph.decode.inputs.samples,['sample',0]);
for(const node of Object.values(graph))for(const value of Object.values(node.inputs))if(Array.isArray(value))assert.ok(graph[value[0]],`Missing graph node ${value[0]}`);
const info={};
for(const node of Object.values(graph))info[node.class_type]={input:{required:{}}};
const combo=options=>['COMBO',{options}];
info.UNETLoader.input.required.unet_name=combo([model.model]);
info.CLIPLoader.input.required.clip_name=combo([model.text,model.upsampler]);
info.CLIPLoader.input.required.type=combo([model.type]);
info.VAELoader.input.required.vae_name=combo([model.vae]);
info.LoraLoaderBypassModelOnly.input.required.lora_name=combo([model.lora]);
assert.equal(imageAvailability(info).find(m=>m.id===model.id).ready,true);
for(const [type,key,file] of [['CLIPLoader','clip_name',model.upsampler],['LoraLoaderBypassModelOnly','lora_name',model.lora]]){
  const missing=structuredClone(info);missing[type].input.required[key]=combo([]);
  assert.ok(imageAvailability(missing).find(m=>m.id===model.id).missing.includes(file));
}
delete info.PH3ImageConditioning;
assert.equal(imageAvailability(info).find(m=>m.id===model.id).ready,false);
console.log('P-H3 image edit: ordered references, official sampler, prompt expansion and model readiness pass.');

// Optional read-only check against the running ComfyUI node schemas and model lists.
if(process.env.PH3_VALIDATE_URL){
  const response=await fetch(`${process.env.PH3_VALIDATE_URL}/object_info`);assert.ok(response.ok);
  const live=await response.json();
  const status=imageAvailability(live).find(m=>m.id===model.id);
  assert.ok(status.ready,`P-H3 setup missing: ${status.missing.join(', ')}`);
  for(const [id,node] of Object.entries(graph)){
    const spec=live[node.class_type];assert.ok(spec,`Node ${node.class_type} is unavailable`);
    const fields={...spec.input.required,...spec.input.optional};
    for(const key of Object.keys(spec.input.required||{})){
      const dynamic=fields[key]?.[0]==='COMFY_AUTOGROW_V3';
      assert.ok(dynamic?Object.keys(node.inputs).some(k=>k.startsWith(`${key}.`)):key in node.inputs,`${id} is missing ${key}`);
    }
    for(const [key,value] of Object.entries(node.inputs)){
      const field=fields[key]||fields[key.split('.')[0]];
      assert.ok(field,`${id} has unsupported input ${key}`);
      if(Array.isArray(value)){
        const from=graph[value[0]],output=live[from.class_type].output[value[1]];
        const type=field[0]==='COMFY_AUTOGROW_V3'?field[1].template.input.required.image[0]:field[0];
        assert.ok(type==='*'||type===output,`${id}.${key} expects ${type}, got ${output}`);
      }
    }
  }
  console.log('P-H3 graph node inputs, connections and installed files match the live ComfyUI schemas.');
}

import assert from 'node:assert/strict';
import fs from 'node:fs';
import {H3_RIPPLE_FILES,buildRippleStudioGraph,rippleStudioAvailability,rippleStudioProcessingSize,rippleStudioValidation} from '../web/studio_ripple_recipes.js';

const info=JSON.parse(fs.readFileSync(new URL('./fixtures/ripple_nodes.json',import.meta.url),'utf8'));
for(const name of ['ZuraRippleGuide','ZuraRippleH3Guide','WN_RippleApply','BasicGuider'])info[name]={input:{required:{}}};
const list=(node,key)=>info[node].input.required[key][0];
for(const name of [H3_RIPPLE_FILES.flex,H3_RIPPLE_FILES.ripple])list('LoraLoaderModelOnly','lora_name').push(`H3\\${name}`);
list('UNETLoader','unet_name').push(H3_RIPPLE_FILES.model);
list('CLIPLoader','clip_name').push(H3_RIPPLE_FILES.text);
list('CLIPLoader','type').push('minimax');
list('VAELoader','vae_name').push(H3_RIPPLE_FILES.vae);

assert.deepEqual(rippleStudioProcessingSize(1921,1081,1,'h3'),{width:1952,height:1088});
assert.deepEqual(rippleStudioProcessingSize(1921,1081,1,'ltx'),{width:1984,height:1088});
assert.deepEqual(rippleStudioProcessingSize(1921,1081,.5,'ltx'),{width:1024,height:576});
assert.deepEqual(rippleStudioProcessingSize(1920,1080,.25,'h3'),{width:480,height:288});
assert.throws(()=>rippleStudioProcessingSize(0,1080,1,'h3'),/source size/);

const c={engine:'h3',source:'fixtures/source.mp4',startFrame:10,frameCount:74,sequenceFps:30000/1001,width:1952,height:1088,seed:23,sourceColour:'auto',anchors:[{frame:63,file:'later.png'},{frame:10,file:'start.png'}]};
assert.equal(rippleStudioValidation(c),'');
assert.equal(rippleStudioAvailability(info,'h3').ready,true);
const missing=structuredClone(info);delete missing.WN_RippleApply;
assert.ok(rippleStudioAvailability(missing,'h3').missing.includes('WN_RippleApply'));
const h3=buildRippleStudioGraph(c,info);
assert.equal(h3.source.inputs.framing_mode,'Full frame (stretch to working size)');
assert.equal(h3.source.inputs.sequence_fps,30000/1001);
assert.equal(h3.source.inputs.frame_count,74);
assert.equal(h3.source.inputs.render_width,1952);
assert.deepEqual(JSON.parse(h3.anchors.inputs.anchors).map(a=>[a.frame,a.file,a.colour_space]),[[10,'start.png','srgb_display'],[63,'later.png','srgb_display']]);
assert.equal(h3.model.inputs.unet_name,H3_RIPPLE_FILES.model);
assert.equal(h3.flex.inputs.lora_name,`H3\\${H3_RIPPLE_FILES.flex}`);
assert.equal(h3.flex.inputs.strength_model,1);
assert.equal(h3.lora.inputs.lora_name,`H3\\${H3_RIPPLE_FILES.ripple}`);
assert.equal(h3.lora.inputs.strength_model,1);
assert.deepEqual(h3.apply.inputs.ripple,['ripple_guide',0]);
assert.deepEqual(h3.apply.inputs.edited_images,['ripple_guide',1]);
assert.equal(h3.sigmas.inputs.steps,6);assert.equal(h3.sigmas.inputs.scheduler,'simple');
assert.equal(h3.sampler.inputs.sampler_name,'lcm');
assert.deepEqual(h3.sample.inputs.latent_image,['apply',1]);
assert.deepEqual(h3.save.inputs.decoded_crop,['decode',0]);
assert.deepEqual(h3.save.inputs.plate,['source',2]);
assert.equal(h3.save.inputs.match_context,false);
for(const node of Object.values(h3))for(const value of Object.values(node.inputs))if(Array.isArray(value))assert.ok(h3[value[0]],`Broken graph link: ${value[0]}`);

const ltx={...c,engine:'ltx',width:1984,anchors:[{frame:10,file:'start.png'}]};
assert.equal(rippleStudioAvailability(info,'ltx').ready,true);
assert.equal(rippleStudioValidation(ltx),'');
const g=buildRippleStudioGraph(ltx,info);
assert.equal(g.source.inputs.framing_mode,'Full frame (stretch to working size)');
assert.equal(g.source.inputs.render_width,1984);
assert.equal(g.source.inputs.sequence_fps,30000/1001);
for(const graph of [h3,g])for(const [id,node] of Object.entries(graph))for(const [key,value] of Object.entries(node.inputs)){
  if(typeof value!=='number')continue;
  const limits=(info[node.class_type]?.input?.required?.[key]||info[node.class_type]?.input?.optional?.[key])?.[1]||{};
  if(Number.isFinite(limits.min))assert.ok(value>=limits.min,`${id}.${key} is below the native minimum`);
  if(Number.isFinite(limits.max))assert.ok(value<=limits.max,`${id}.${key} is above the native maximum`);
}
assert.equal(g.align.inputs.batch_index,1,'LTX still discards the prepended edited guide');
assert.deepEqual(g.save.inputs.plate,['source',2]);
assert.equal(JSON.parse(g.anchors.inputs.anchors)[0].colour_space,'srgb_display');
const selectedReference={...ltx,startFrame:11,frameCount:34,anchors:[{id:'edit-18',frame:18,file:'edited-18.png',colour_space:'srgb_display'}]};
const originalReference=structuredClone(selectedReference);
assert.equal(rippleStudioValidation(selectedReference),'','LTX accepts one visual reference from inside the selected clip');
const referenceGraph=buildRippleStudioGraph(selectedReference,info);
assert.deepEqual(selectedReference,originalReference,'Building the guide must not rewrite the saved anchor or trim');
assert.equal(referenceGraph.source.inputs.start_frame,11);
assert.equal(referenceGraph.source.inputs.frame_count,34);
assert.equal(referenceGraph.source.inputs.sequence_fps,30000/1001);
assert.equal(referenceGraph.source.inputs.render_width,1984);
assert.equal(referenceGraph.source.inputs.render_height,1088);
assert.deepEqual(JSON.parse(referenceGraph.anchors.inputs.anchors).map(a=>[a.frame,a.file]),[[11,'edited-18.png']],'Only the internal prepended reference slot maps to the selected source start');
assert.equal(referenceGraph.anchors._meta.source_reference_frame,18);
assert.match(referenceGraph.anchors._meta.title,/source frame 18/);
assert.equal(referenceGraph.align.inputs.batch_index,1,'Non-start references keep the same leading-guide removal');
assert.deepEqual(referenceGraph.save.inputs.plate,['source',2],'Saving still restores the original selected source range');
const cinema=buildRippleStudioGraph({...ltx,width:4096,height:2176},info);
assert.equal(cinema.source.inputs.render_width,4096,'The dedicated workspace allows cinema 4K on a supported grid');
assert.equal(cinema.source.inputs.render_height,2176);
for(const change of [
  {anchors:[]},{anchors:[{frame:9,file:'before.png'}]},
  {anchors:[{frame:10,file:'one.png'},{frame:10,file:'two.png'}]},
  {anchors:[{frame:20,file:''}]},{width:1953},{frameCount:994},{sequenceFps:0},
])assert.notEqual(rippleStudioValidation({...c,...change}),'');
assert.equal(rippleStudioValidation({...ltx,anchors:[{frame:11,file:'late.png'}]}),'');
assert.match(rippleStudioValidation({...ltx,anchors:[...ltx.anchors,{frame:15,file:'another.png'}]}),/one visual reference/);
assert.match(rippleStudioValidation({...selectedReference,anchors:[{frame:10,file:'outside.png'}]}),/inside the selected clip/);
assert.match(rippleStudioValidation({...c,anchors:Array.from({length:17},(_,i)=>({frame:10+i,file:`${i}.png`}))}),/up to 16/);
console.log('Ripple Studio recipes preserve source timing and extent, support ordered H3 anchors, and map one LTX visual reference without changing its saved identity.');

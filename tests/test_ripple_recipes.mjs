import assert from 'node:assert/strict';
import fs from 'node:fs';
import {buildRippleGraph,rippleValidation,rippleAvailability,RIPPLE_LORA} from '../web/paintout_studio/ripple_recipes.js';
const info=JSON.parse(fs.readFileSync(new URL('./fixtures/ripple_nodes.json',import.meta.url),'utf8'));
info.ZuraRippleGuide={input:{required:{plate:['ZURA_PLATE'],anchors:['ZURA_ANCHORS']}},output:['IMAGE','INT']};
const config={source:'fixtures/source.mp4',startFrame:0,frameCount:97,sequenceFps:24,sourceColour:'srgb_display',colourPipeline:'sdr_sdr',processingSpace:'SDR (sRGB)',outputMode:'SDR video',width:512,height:896,seed:42,anchors:[{frame:0,file:'fixtures/edited_first_frame.png',rippleReviewedFile:'fixtures/edited_first_frame.png',status:'accepted',enabled:true}]};
assert.equal(rippleValidation(config),'');
for(const fps of [24,25,30,30000/1001]){
 const g=buildRippleGraph({...config,sequenceFps:fps},info);
 assert.equal(g.source.inputs.sequence_fps,fps);
 assert.deepEqual(g.conditioning.inputs.frame_rate,['take',5]);assert.deepEqual(g.audio.inputs.frame_rate,['take',5]);
 assert.deepEqual(g.latent.inputs.length,['ripple_guide',1]);assert.equal(g.align.inputs.batch_index,1);assert.deepEqual(g.align.inputs.length,['take',4]);
 assert.equal(g.lora.inputs.lora_name,RIPPLE_LORA);assert.equal(g.lora.inputs.strength_model,1.35);
 assert.equal(g.save.inputs.match_context,false);assert.deepEqual(g.save.inputs.plate,['source',2]);
 assert.equal(g.guide.inputs.frame_idx,0);assert.deepEqual(g.guide.inputs.image,['ripple_guide',0]);
 assert.equal(g.sigmas.inputs.steps,8);
 for(const [id,n] of Object.entries(g)){
  const schema=info[n.class_type];assert.ok(schema,`${id}: missing ${n.class_type}`);
  for(const key of Object.keys(schema.input?.required||{}))assert.ok(key in n.inputs,`${id}: missing ${key}`);
  for(const [key,v] of Object.entries(n.inputs)){
   if(Array.isArray(v)&&typeof v[0]==='string'&&Number.isInteger(v[1])){assert.ok(g[v[0]],`${id}.${key}: broken link`);continue;}
   const type=schema.input?.required?.[key]||schema.input?.optional?.[key];assert.ok(type,`${id}.${key}: unsupported input`);
   if(Array.isArray(type[0]))assert.ok(type[0].includes(v),`${id}.${key}: unsupported choice ${v}`);
  }
 }
}
for(const change of [{anchors:[{frame:10,file:'later.png'}]},{anchors:config.anchors.concat(config.anchors)},{sourceColour:'hlg_rec2020'},{detectedSourceColour:'pq_rec2020'},{frameCount:993},{sequenceFps:0}])assert.notEqual(rippleValidation({...config,...change}),'');
assert.equal(rippleAvailability(info).ready,true);
delete info.ZuraRippleGuide;assert.match(rippleAvailability(info).missing.join(' '),/restart ComfyUI/);
console.log('Ripple graph matches native schemas, first-frame alignment and original-FPS/audio delivery contracts.');

const custom=buildRippleGraph({...config,resolutionMode:'custom',width:1920,height:1088,prompt:'Replace the silver car'},info);
assert.equal(custom.source.inputs.framing_mode,'Full frame (fit, no crop)');
assert.equal(custom.source.inputs.render_width,1920);assert.equal(custom.source.inputs.render_height,1088);
assert.match(rippleValidation({...config,width:1919}),/64-pixel/);
assert.match(rippleValidation({...config,width:4096,height:4096}),/8.39/);

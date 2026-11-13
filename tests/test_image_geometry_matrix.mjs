import assert from 'node:assert/strict';
import {IMAGE_MODELS,buildImageGraph,imageDimensions} from '../web/image_recipes.js';
import {SOURCE_MODEL_LIMITS,editSourceRaster,restoreSourceSize,sourceModelRaster} from '../web/source_model_resolution.js';

const refs=[
  {file:'images/portrait.png',width:512,height:1024},
  {file:'images/landscape.png',width:1024,height:512},
  {file:'images/style.png',width:768,height:768},
];
const sourceCases=[
  {width:512,height:1024},
  {width:1024,height:512},
  {width:1921,height:1081},
  {width:3840,height:2160},
  {width:257,height:511},
  {width:50,height:500},
];
const localEditors=IMAGE_MODELS.filter(model=>model.edit&&!model.provider);
const providerEditors=IMAGE_MODELS.filter(model=>model.edit&&model.provider);

const stretched=sourceModelRaster({width:1921,height:1081},{quantum:16});
assert.deepEqual(stretched,{
  width:1936,
  height:1088,
  sourceWidth:1921,
  sourceHeight:1081,
  exact:false,
  scaleX:1936/1921,
  scaleY:1088/1081,
});
assert.deepEqual(restoreSourceSize(stretched.sourceWidth,stretched.sourceHeight),{width:1921,height:1081,crop:'disabled'});
assert.deepEqual(sourceModelRaster({width:50,height:500},{quantum:16}),{
  width:256,
  height:2560,
  sourceWidth:50,
  sourceHeight:500,
  exact:false,
  scaleX:256/50,
  scaleY:2560/500,
});
assert.deepEqual(sourceModelRaster({width:1000,height:50},{quantum:16}),{
  width:5120,
  height:256,
  sourceWidth:1000,
  sourceHeight:50,
  exact:false,
  scaleX:5120/1000,
  scaleY:256/50,
});
assert.equal(sourceModelRaster({width:257,height:511},{quantum:16}).width,272);
assert.equal(sourceModelRaster({width:257,height:511},{quantum:16}).height,512);
assert.equal(sourceModelRaster({width:4096,height:2048},{quantum:16}).width,4096);
assert.throws(()=>sourceModelRaster({width:4096,height:2160},{quantum:16}),/operational canvas.*without reducing the source/);
assert.throws(()=>sourceModelRaster({width:10,height:1000},{quantum:16}),/cannot align.*without reducing the source/);
assert.throws(()=>editSourceRaster([{}],{name:'Qwen Image Edit 2511'}),/dimensions are missing/);
assert.equal(editSourceRaster([{width:4096,height:4096}],{name:'Edit area'},{editArea:true}).width,4096);

// Every local edit model processes Image 1 on its native model grid without
// shrinking it, then stretches the decoded master back to the captured raster.
for(const model of localEditors){
  for(const source of sourceCases){
    const modelRefs=[{...refs[0],...source},...refs.slice(1)];
    const raster=editSourceRaster(modelRefs,model);
    assert.deepEqual(imageDimensions({model:model.id,shape:'auto',references:modelRefs}),[raster.width,raster.height]);
    const graph=buildImageGraph({model:model.id,prompt:'Edit only the coat',shape:'auto',references:modelRefs,seed:17});
    const step=model.sizeStep??16,min=model.minDimension??SOURCE_MODEL_LIMITS.minDimension,max=model.maxDimension??SOURCE_MODEL_LIMITS.maxDimension,maxPixels=(model.editAreaMaxPixels??model.maxPixels??SOURCE_MODEL_LIMITS.maxPixels);
    assert.ok(raster.width>=min&&raster.height>=min,`${model.id}: minimum side`);
    assert.equal(raster.width%step,0,`${model.id}: aligned width`);
    assert.equal(raster.height%step,0,`${model.id}: aligned height`);
    assert.ok(raster.width<=max&&raster.height<=max&&raster.width*raster.height<=maxPixels,`${model.id}: documented operational cap`);
    assert.ok(raster.width>=source.width&&raster.height>=source.height,`${model.id}: source is never reduced`);
    assert.ok(Math.abs(raster.scaleX-raster.scaleY)<=step/Math.min(source.width,source.height),`${model.id}: aspect stays as close as the model grid permits`);
    assert.equal(graph.source_size.class_type,'ImageScale',`${model.id}: primary source is stretched to the aligned raster`);
    assert.deepEqual(graph.source_size.inputs.image,['reference_1',0]);
    assert.equal(graph.source_size.inputs.width,raster.width,`${model.id}: aligned width`);
    assert.equal(graph.source_size.inputs.height,raster.height,`${model.id}: aligned height`);
    assert.equal(graph.source_size.inputs.crop,'disabled');
    assert.ok(Object.values(graph).some(entry=>
      entry.class_type==='ImageScale'
      && entry.inputs.width===source.width
      && entry.inputs.height===source.height
      && entry.inputs.crop==='disabled'
    ),`${model.id}: decoded edit restores the source`);
    assert.ok(Object.values(graph).every(entry=>entry.class_type!=='ResizeAndPadImage'||entry.inputs.image?.[0]!=='source_size'),`${model.id}: source edit is not letterboxed`);
  }
}

// Model caps stay explicit and reject an over-limit source instead of silently
// downscaling the artist's frame. P-H3 deliberately owns the larger 16 MP path.
assert.throws(
  ()=>editSourceRaster([{width:4100,height:1000}],IMAGE_MODELS.find(model=>model.id==='qwen21edit')),
  /without reducing the source/,
);
assert.equal(editSourceRaster([{width:4096,height:4096}],IMAGE_MODELS.find(model=>model.id==='ph3edit')).width,4096);
assert.equal(editSourceRaster([{width:4096,height:4096}],IMAGE_MODELS.find(model=>model.id==='ph3edit')).height,4096);

// Qwen 2511 owns a full-size sampling latent. Text-only conditioning receives
// the image tokens, then explicit positive and negative ReferenceLatent chains
// attach every chosen reference without Edit Plus silently resampling Image 1.
const qwen=buildImageGraph({model:'qwen2511',prompt:'Edit the coat',references:refs,seed:19});
assert.ok(!Object.hasOwn(qwen.prompt.inputs,'vae'));
assert.ok(!Object.hasOwn(qwen.negative.inputs,'vae'));
assert.equal(qwen.size.class_type,'VAEEncode');
assert.deepEqual(qwen.size.inputs.pixels,['source_size',0]);
assert.equal(qwen.positive_reference_1.class_type,'ReferenceLatent');
assert.deepEqual(qwen.positive_reference_1.inputs.conditioning,['prompt',0]);
assert.deepEqual(qwen.positive_reference_1.inputs.latent,['size',0]);
assert.equal(qwen.negative_reference_1.class_type,'ReferenceLatent');
assert.deepEqual(qwen.negative_reference_1.inputs.conditioning,['negative',0]);
assert.deepEqual(qwen.positive_reference_3.inputs.conditioning,['positive_reference_2',0]);
assert.ok(!Object.values(qwen).some(entry=>entry.class_type==='ZuraQwenEditLatent'));

// Browser editors retain their provider contract. Studio labels those results
// as provider-sized because their internal canvas cannot be guaranteed locally.
for(const model of providerEditors){
  const graph=buildImageGraph({model:model.id,prompt:'Edit only the coat',shape:'auto',references:refs});
  assert.equal(graph.browser_image.inputs.custom_width,512);
  assert.equal(graph.browser_image.inputs.custom_height,1024);
  assert.ok(!graph.source_size);
  assert.ok(!graph.output_size);
}

// A painted crop is dynamic. The model-facing scale must follow the crop's
// actual raster, while the stitcher restores the full original source.
const editArea={
  enabled:true,
  source_key:refs[0].file,
  mask:{file:'images/mask.png'},
  context:64,
  feather:12,
};
for(const model of localEditors){
  const graph=buildImageGraph({model:model.id,operation:'edit',prompt:'Change the marked area',references:refs,seed:23,edit_area:editArea});
  assert.equal(graph.source_size.class_type,'ImageScale');
  assert.deepEqual(graph.source_size.inputs.image,['zura_area_working',0]);
  assert.deepEqual(graph.source_size.inputs.width,['zura_area_size',0]);
  assert.deepEqual(graph.source_size.inputs.height,['zura_area_size',1]);
  assert.equal(graph.source_size.inputs.crop,'disabled');
  assert.deepEqual(graph.zura_area_mask.inputs.image,['reference_1',0]);
  assert.deepEqual(graph.zura_area_composite.inputs.destination,['reference_1',0]);
  assert.deepEqual(graph.save.inputs.images,['zura_area_composite',0]);
  if(graph.output_size){
    assert.deepEqual(graph.output_size.inputs.width,['zura_area_size',0]);
    assert.deepEqual(graph.output_size.inputs.height,['zura_area_size',1]);
  }
}

// The current operational cap rejects an oversized source instead of quietly
// decoding it smaller. A source on the limit remains eligible.
assert.throws(
  ()=>buildImageGraph({model:'qwen2511',prompt:'Edit',references:[{file:'wide.png',width:4096,height:2160}]}),
  /without reducing the source.*Choose a compatible model/,
);
console.log('PASS: source-aligned edit raster, inverse restoration, explicit Qwen latents and painted-crop wiring');

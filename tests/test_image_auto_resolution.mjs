import assert from 'node:assert/strict';
import {IMAGE_MODELS,imageDimensions,buildImageGraph} from '../web/image_recipes.js';
import {modelRasterOptions} from '../web/source_model_resolution.js';
import {resolutionSize} from '../web/studio_resolution.js';

const refs=[{file:'source.png',width:1920,height:1080},{file:'look.png',width:512,height:512}];
assert.deepEqual(imageDimensions({shape:'auto',width:512,height:512,references:refs}),[1920,1088]);
assert.deepEqual(imageDimensions({shape:'auto',references:[{file:'4k.png',width:3840,height:2160}]}),[3840,2160]);
assert.deepEqual(imageDimensions({shape:'auto'}),[1024,1024]);
for(const model of ['flux2','flux3','klein9b','flux3edit','qwen2511']){
  const graph=buildImageGraph({model,prompt:'Relight Image 1',shape:'auto',references:refs});
  if(graph.source_size){
    assert.equal(graph.source_size.class_type,'ImageScale');
    assert.equal(graph.source_size.inputs.width,1920);
    assert.equal(graph.source_size.inputs.height,1088);
    assert.equal(graph.source_size.inputs.crop,'disabled');
  }else{
    assert.equal(graph.size.inputs.width,1920);assert.equal(graph.size.inputs.height,1088);
  }
}
for(const model of ['chatgpt','chatgptedit','gemini','geminiedit']){
  const graph=buildImageGraph({model,prompt:'Relight Image 1',shape:'auto',references:refs});
  assert.equal(graph.browser_image.inputs.size,'Auto','Browser node must not append a size instruction');
  const custom=buildImageGraph({model,prompt:'Relight Image 1',shape:'landscape',width:3840,height:2160,references:refs});
  assert.equal(custom.browser_image.inputs.size,'Custom');
  assert.equal(custom.browser_image.inputs.custom_width,3840);assert.equal(custom.browser_image.inputs.custom_height,2160);
}
const fourK=resolutionSize(16/9,8.2944,{step:16,min:256,max:8192,maxPixels:8_388_608});
assert.deepEqual(fourK,{width:3840,height:2160});
const qwenOptions=modelRasterOptions(IMAGE_MODELS.find(model=>model.id==='qwen21edit'));
assert.deepEqual({step:qwenOptions.step,min:qwenOptions.min,max:qwenOptions.max,maxPixels:qwenOptions.maxPixels},{
  step:32,
  min:256,
  max:4096,
  maxPixels:8_388_608,
});
const qwenManual=resolutionSize(4,8,qwenOptions);
assert.ok(qwenManual.width<=4096&&qwenManual.height<=4096);
assert.equal(qwenManual.width%32,0);assert.equal(qwenManual.height%32,0);
assert.deepEqual(imageDimensions({width:3840,height:2160}),[3840,2160]);
console.log('Auto respects Image 1 and provider-native sizing; manual dimensions and MP slider reach 4K.');

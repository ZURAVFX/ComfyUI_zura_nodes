import assert from 'node:assert/strict';
import {imageDimensions,buildImageGraph} from '../web/image_recipes.js';
import {resolutionSize} from '../web/studio_resolution.js';

const refs=[{file:'source.png',width:1920,height:1080},{file:'look.png',width:512,height:512}];
assert.deepEqual(imageDimensions({shape:'auto',width:512,height:512,references:refs}),[1920,1088]);
assert.deepEqual(imageDimensions({shape:'auto',references:[{file:'4k.png',width:3840,height:2160}]}),[3840,2160]);
assert.deepEqual(imageDimensions({shape:'auto'}),[1024,1024]);
for(const model of ['flux2','flux3','klein9b','flux3edit','qwen2511']){
  const graph=buildImageGraph({model,prompt:'Relight Image 1',shape:'auto',references:refs});
  const size=model==='qwen2511'?graph.source_size.inputs:graph.size.inputs;
  assert.equal(size.width,1920);assert.equal(size.height,1088);
}
for(const model of ['chatgpt','chatgptedit','gemini','geminiedit']){
  const graph=buildImageGraph({model,prompt:'Relight Image 1',shape:'auto',references:refs});
  assert.equal(graph.browser_image.inputs.size,'Auto','Browser node must not append a size instruction');
  const custom=buildImageGraph({model,prompt:'Relight Image 1',shape:'landscape',width:3840,height:2160,references:refs});
  assert.equal(custom.browser_image.inputs.size,'Custom');
  assert.equal(custom.browser_image.inputs.custom_width,3840);assert.equal(custom.browser_image.inputs.custom_height,2160);
}
const fourK=resolutionSize(16/9,8.2944,{step:16,min:256,max:8192,maxPixels:8.5e6});
assert.deepEqual(fourK,{width:3840,height:2160});
assert.deepEqual(imageDimensions({width:3840,height:2160}),[3840,2160]);
console.log('Auto respects Image 1 and provider-native sizing; manual dimensions and MP slider reach 4K.');

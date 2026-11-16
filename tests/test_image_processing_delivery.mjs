import assert from 'node:assert/strict';
import {IMAGE_MODELS,buildImageGraph,imageDimensions,imageResolutionPlan} from '../web/image_recipes.js';

const source={file:'source.png',width:3264,height:1632,colour:{encoding:'acescg',sceneLinear:true}};
for(const model of IMAGE_MODELS.filter(value=>value.edit&&!value.provider)){
  const config={model:model.id,operation:'edit',shape:'auto',prompt:'Change the wall',seed:42,references:[source],processingResolution:'manual',width:1024,height:512};
  const plan=imageResolutionPlan(config),graph=buildImageGraph(config);
  assert.deepEqual(imageDimensions(config),[plan.processing.width,plan.processing.height]);
  assert.ok(plan.processing.width<source.width&&plan.processing.height<source.height,model.id);
  assert.deepEqual(plan.output,{width:source.width,height:source.height},model.id);
  assert.deepEqual([graph.source_size.inputs.width,graph.source_size.inputs.height],[plan.processing.width,plan.processing.height]);
  assert.deepEqual([graph.output_size.inputs.width,graph.output_size.inputs.height],[source.width,source.height]);
  const smaller=buildImageGraph({...config,deliveryResolution:'processing'});
  assert.deepEqual([smaller.delivery_size.inputs.width,smaller.delivery_size.inputs.height],[plan.processing.width,plan.processing.height]);
  assert.deepEqual(smaller.delivery_size.inputs.image,graph.output_size.inputs.image,'Whole-frame smaller delivery avoids upscale/downscale round trip');
  const layered=buildImageGraph({...config,deliveryResolution:'processing',retain_layer_context:true,image_layer_base:{source}});
  assert.deepEqual(layered.save_layer.inputs.images,['output_size',0],'Layer cache remains in original source coordinates');
  assert.deepEqual(layered.save.inputs.images,['delivery_size',0]);
  const auto=imageResolutionPlan({...config,processingResolution:'auto'});
  assert.ok(auto.processing.width>=source.width&&auto.processing.height>=source.height,'Auto never silently reduces the source');
}
const areaConfig={model:'qwen2511',operation:'edit',shape:'auto',prompt:'Remove the logo',seed:42,references:[source],processingResolution:'manual',width:1024,height:512,deliveryResolution:'processing',retain_layer_context:true,image_layer_base:{source},edit_area:{enabled:true,source_key:'source.png',mask:{file:'mask.png'},context:64,feather:16}};
const area=buildImageGraph(areaConfig);
assert.ok(area.zura_area_target.inputs.megapixels>0,'A manual target reaches crop processing');
assert.deepEqual(area.save_layer.inputs.images,['zura_area_stitch',0],'Raw context remains source-sized for editable layers');
assert.deepEqual(area.delivery_size.inputs.image,['zura_area_stitch',0],'Only the final delivery is resized');
assert.deepEqual(area.zura_area_mask.inputs.image,['reference_1',0],'The mask stays on the original source');
const legacyBrowser=buildImageGraph({model:'chatgptedit',shape:'auto',prompt:'Edit Image 1',references:[source]});
assert.equal(legacyBrowser.delivery_size,undefined,'Browser-native Auto remains unchanged without an explicit delivery choice');
const originalBrowser=buildImageGraph({model:'chatgptedit',shape:'auto',prompt:'Edit Image 1',references:[source],deliveryResolution:'original'});
assert.deepEqual([originalBrowser.delivery_size.inputs.width,originalBrowser.delivery_size.inputs.height],[source.width,source.height]);
assert.deepEqual(source.colour,{encoding:'acescg',sceneLinear:true},'Resolution planning does not mutate source colour metadata');
const odd=imageResolutionPlan({model:'qwen2511',operation:'edit',shape:'auto',references:[{file:'odd.png',width:253,height:141}],processingResolution:'manual',width:256,height:256,deliveryResolution:'processing'});
assert.ok(Math.abs((odd.output.width/odd.output.height)/(253/141)-1)<.01,'Processing delivery restores the source aspect after native-grid rounding');
assert.ok(odd.output.width<=odd.processing.width&&odd.output.height<=odd.processing.height);
console.log('Image processing/delivery: all local edit models, exact originals, smaller outputs, crop/layer coordinates and browser-native defaults pass.');

import assert from 'node:assert/strict';
import {IMAGE_MODELS,buildImageGraph} from '../web/image_recipes.js';
import {IMAGE_AREA_NODE_TYPES,imageAreaSourceKey,smartCropCapabilities} from '../web/studio_image_area_graph.js';

const refs=[{file:'images/main.png'},{file:'images/guide.png'}];
const selected={enabled:true,source_key:refs[0].file,mask:{file:'images/selection.png'},context:64,feather:16};
assert.equal(imageAreaSourceKey(refs[0]),refs[0].file);
const oldInfo=Object.fromEntries(IMAGE_AREA_NODE_TYPES.map(name=>[name,{input:{required:{},optional:{}}}]));
const latestInfo=structuredClone(oldInfo);
latestInfo.SmartImageCrop.input.required.context_padding=['INT'];
latestInfo.SmartImageCrop.input.optional.max_megapixels=['FLOAT'];
latestInfo.SmartImageStitcher.input.required.feather_mode=[['Auto','Pixels']];
assert.deepEqual(smartCropCapabilities(oldInfo).schema,{contextPadding:false,maxMegapixels:false,featherMode:false});
assert.deepEqual(smartCropCapabilities(latestInfo).schema,{contextPadding:true,maxMegapixels:true,featherMode:true});
delete latestInfo.SmartImageCrop;
assert.ok(smartCropCapabilities(latestInfo).missing.includes('SmartImageCrop'));

for(const model of IMAGE_MODELS.filter(item=>item.edit)){
  const config={model:model.id,operation:'edit',prompt:'Change the marked area',shape:'landscape',width:1152,height:768,references:refs,seed:23};
  const full=buildImageGraph(config);
  assert.deepEqual(buildImageGraph({...config,edit_area:{enabled:false}}),full,`${model.id}: normal editing stays unchanged`);
  for(const schema of [{contextPadding:true,featherMode:true,maxMegapixels:true},{contextPadding:false,featherMode:false,maxMegapixels:false}]){
    const graph=buildImageGraph({...config,edit_area:selected,smart_crop_schema:schema});
    assert.equal(graph.reference_1.inputs.image,refs[0].file);
    assert.equal(graph.reference_2.inputs.image,refs[1].file);
    assert.equal(graph.zura_area_mask_image.inputs.image,selected.mask.file);
    assert.deepEqual(graph.zura_area_mask.inputs.image,['reference_1',0]);
    assert.deepEqual(graph.zura_area_crop.inputs.mask,['zura_area_mask',0]);
    assert.equal(graph.zura_area_crop.inputs.patch_mask_holes,false);
    assert.equal(graph.zura_area_crop.inputs.mask_grow_pixels,schema.contextPadding?0:64);
    assert.equal('context_padding' in graph.zura_area_crop.inputs,schema.contextPadding);
    assert.equal('feather_mode' in graph.zura_area_stitch.inputs,schema.featherMode);
    assert.equal(graph.zura_area_stitch.inputs.blend_mode,'Mask Feather');
    assert.deepEqual(graph.zura_area_composite.inputs.destination,['reference_1',0]);
    assert.deepEqual(graph.zura_area_composite.inputs.mask,['zura_area_mask',1]);
    assert.deepEqual(graph.save.inputs.images,['zura_area_composite',0]);
    assert.equal(graph.zura_area_working.class_type,'ImageScaleToTotalPixels');
    assert.equal(graph.zura_area_working.inputs.resolution_steps,model.sizeStep||16);
    assert.deepEqual(graph.zura_area_working.inputs.megapixels,['zura_area_target',0]);
    assert.ok(graph.zura_area_target.inputs.megapixels>0);
    for(const [id,entry] of Object.entries(graph))for(const value of Object.values(entry.inputs)){
      if(Array.isArray(value)&&value.length===2&&typeof value[0]==='string')assert.ok(graph[value[0]],`${model.id}: ${id} references missing ${value[0]}`);
      if(['width','custom_width'].some(k=>entry.inputs[k]===value))assert.deepEqual(value,['zura_area_size',0],`${model.id}: ${id} width follows crop`);
      if(['height','custom_height'].some(k=>entry.inputs[k]===value))assert.deepEqual(value,['zura_area_size',1],`${model.id}: ${id} height follows crop`);
    }
    if(model.type==='flux3'){
      assert.deepEqual(graph.prompt_source_size.inputs.image,['zura_area_working',0],'Upsampler observes the actual painted source crop');
      assert.deepEqual(graph.prompt_images.inputs['images.image0'],['zura_area_working',0]);
      assert.deepEqual(graph.prompt_reference_2.inputs.image,['reference_2',0],'Appearance guide remains the full original reference');
      assert.deepEqual(graph.references.inputs['images.image0'],['zura_area_working',0]);
      assert.deepEqual(graph.references.inputs['images.image1'],['reference_2',0]);
      assert.deepEqual(graph.prompt.inputs.text,['expand_prompt',0]);
    }
    if(model.provider){
      assert.equal(graph.browser_image.inputs.size,'Custom');
      assert.deepEqual(graph.browser_image.inputs.reference_1,['zura_area_working',0]);
      assert.deepEqual(graph.browser_image.inputs.reference_2,['reference_2',0]);
    }
    const auto=buildImageGraph({...config,shape:'auto',edit_area:selected,smart_crop_schema:schema});
    assert.equal(auto.zura_area_working.class_type,'ImageScaleToTotalPixels');
    assert.equal(auto.zura_area_target.inputs.megapixels,0,'Auto resolves native crop area with a quality floor');
    assert.deepEqual(auto.zura_area_working.inputs.megapixels,['zura_area_target',0]);
  }
}
assert.throws(()=>buildImageGraph({model:'klein9b',prompt:'Edit',references:refs,edit_area:{...selected,source_key:'other.png'}}),/different main image/);
assert.throws(()=>buildImageGraph({model:'klein9b',prompt:'Edit',references:refs,edit_area:{...selected,mask:{file:'../invalid'}}}),/Paint and save/);
assert.throws(()=>buildImageGraph({model:'klein9b',prompt:'Edit',references:refs,edit_area:{...selected,feather:999}}),/valid context/);
assert.throws(()=>buildImageGraph({model:'flux2',prompt:'Create',references:refs,edit_area:selected}),/Choose Edit image/);
console.log('All local and browser edit graphs preserve source and guides, support both Hallett schemas, and composite the painted area.');

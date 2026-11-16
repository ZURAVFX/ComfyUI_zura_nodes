import assert from 'node:assert/strict';
import {IMAGE_MODELS,buildImageGraph} from '../web/image_recipes.js';
import {IMAGE_AREA_NODE_TYPES,imageAreaSourceKey,smartCropCapabilities} from '../web/studio_image_area_graph.js';

const refs=[{file:'images/main.png',width:1280,height:720},{file:'images/guide.png',width:512,height:512}];
const selected={enabled:true,source_key:refs[0].file,mask:{file:'images/selection.png'},context:64,feather:16};
assert.equal(imageAreaSourceKey(refs[0]),refs[0].file);
for(const type of ['VAEEncode','SetLatentNoiseMask','MaskToImage','ImageToMask'])assert.equal(IMAGE_AREA_NODE_TYPES.includes(type),false,`${type} is not needed to select a visible edit area`);
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
  const guideOnly={enabled:false,source_key:refs[0].file,guide:{file:'images/paint-guidance.png'}};
  const guided=buildImageGraph({...config,edit_area:guideOnly});
  assert.equal(guided.reference_1.inputs.image,guideOnly.guide.file,`${model.id}: guide-only painting reaches the model's Image 1 input`);
  assert.equal(guided.zura_area_mask,undefined,`${model.id}: guide-only painting does not invent an edit mask`);
  assert.equal(refs[0].file,'images/main.png',`${model.id}: source file identity remains unchanged`);
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
    if(!model.provider){
      const nativeLatent=full.sample?.inputs?.latent_image;
      assert.ok(Array.isArray(nativeLatent),`${model.id}: base recipe supplies its own sampler latent`);
      assert.deepEqual(graph.sample.inputs.latent_image,nativeLatent,`${model.id}: painting does not replace the model-native sampler latent`);
      assert.equal(graph[nativeLatent[0]]?.class_type,full[nativeLatent[0]]?.class_type,`${model.id}: native latent producer remains in the graph`);
      for(const id of ['zura_area_clean','zura_area_latent','zura_area_mask_pixels','zura_area_mask_size','zura_area_noise_mask','zura_area_masked_latent'])assert.equal(graph[id],undefined,`${model.id}: no generic latent-mask override node ${id}`);
    }
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
      assert.deepEqual(graph.source_size.inputs.image,['zura_area_working',0],'Upsampler and sampling share the actual painted source crop');
      assert.deepEqual(graph.prompt_images.inputs['images.image0'],['source_size',0]);
      assert.deepEqual(graph.prompt_reference_2.inputs.image,['reference_2',0],'Appearance guide remains the full original reference');
      assert.deepEqual(graph.references.inputs['images.image0'],['source_size',0]);
      assert.deepEqual(graph.references.inputs['images.image1'],['reference_working_2',0],'Every batched reference uses the working raster');
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
assert.throws(()=>buildImageGraph({model:'flux3edit',operation:'edit',prompt:'Edit',references:refs,edit_area:{enabled:false,source_key:'other.png',guide:{file:'images/paint-guidance.png'}}}),/different main image/);
console.log('All local and browser edit graphs preserve source and guides, support both Hallett schemas, and composite the painted area.');

const drawn=buildImageGraph({model:'flux3edit',operation:'edit',prompt:'Make the sketched balloon photoreal',shape:'auto',width:1024,height:1024,references:refs,seed:23,edit_area:{...selected,guide:{file:'images/drawing.png'},drawing_region:true}});
assert.equal(drawn.reference_1.inputs.image,refs[0].file);
assert.equal(drawn.zura_drawing.inputs.image,'images/drawing.png');
assert.deepEqual(drawn.zura_area_working.inputs.image,['zura_drawing_crop',0]);
assert.deepEqual(drawn.source_size.inputs.image,['zura_area_working',0]);
assert.deepEqual(drawn.zura_area_stitch.inputs.original_image,['reference_1',0]);
assert.deepEqual(drawn.zura_area_composite.inputs.destination,['reference_1',0]);
assert.equal(drawn.zura_area_mask.inputs.drawing_region,undefined,'A drawn guide must not widen the artist-painted selection to a rectangle');
assert.deepEqual(drawn.zura_area_composite.inputs.mask,['zura_area_mask',1],'The final blend uses the actual painted contour');
console.log('Drawing guide is model conditioning; original source and exact painted selection are retained');

const {PaintoutMaskViewer}=await import('../web/paintout_studio/paintout_viewer.js');
const strokes=()=>({count:0,save(){},restore(){},beginPath(){},moveTo(){},lineTo(){},stroke(){this.count++;},arc(){},fill(){}});
const guideMask=strokes(),guideSketch=strokes();
const separate={tool:'draw',separateGuide:true,guideOnly:true,maskPresent:false,sketchPresent:false,maskCtx:guideMask,sketchCtx:guideSketch,drawOpacity:1,drawColor:'#ff6347',brushSize:20};
PaintoutMaskViewer.prototype.paint.call(separate,{x:4,y:4},{x:6,y:6});
assert.equal(guideSketch.count,1,'A guidance stroke enters the coloured sketch');
assert.equal(guideMask.count,0,'A guidance stroke never enters the edit-area mask');
assert.equal(separate.maskPresent,false);
const legacyMask=strokes(),legacySketch=strokes();
const legacy={...separate,separateGuide:false,maskCtx:legacyMask,sketchCtx:legacySketch,maskPresent:false};
PaintoutMaskViewer.prototype.paint.call(legacy,{x:4,y:4},{x:6,y:6});
assert.equal(legacyMask.count,1,'Existing Paintout drawing still seeds its mask');
const restored=[];
const undoViewer={history:[{kind:'guide',mask:'old mask',sketch:'old guide',sketchPresent:true,positive:[],negative:[]},{kind:'area',mask:'new area',sketch:'new guide',sketchPresent:true,positive:[],negative:[]}],
  width:1,height:1,maskCtx:{putImageData(){restored.push('mask');}},sketchCtx:{clearRect(){},putImageData(){restored.push('guide');}},measureMask(){},changed(){}};
PaintoutMaskViewer.prototype.undo.call(undoViewer,'guide');
assert.deepEqual(restored,['guide'],'Undo in Paint guidance restores only guidance pixels');
assert.equal(undoViewer.history.length,1);assert.equal(undoViewer.history[0].kind,'area','The area undo remains available');
console.log('Guidance-only strokes remain independent of the edit mask; legacy Paintout keeps its behaviour.');

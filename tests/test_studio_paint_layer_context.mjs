import assert from 'node:assert/strict';
import {CreativeWorkspace} from '../web/studio_create.js';
import {IMAGE_MODELS,buildImageGraph} from '../web/image_recipes.js';

const references=[{file:'images/source.png',width:1920,height:1080}];
const area={enabled:true,source_key:references[0].file,mask:{file:'images/selection.png'},context:64,feather:16};
const fields={model:'flux3edit',prompt:'Add a fire hydrant',shape:'auto',width:'1920',height:'1080',seed:'42'};
const owner={mode:'image',imageOperation:'edit',imageIntent:'standard',references,imageLoras:[],imageArea:{config:()=>area},
  $(key){return {value:fields[key],checked:false};},rippleImage:{request:{id:'live-guide',workspace:{platePrimary:{}}},current:()=>true}};
const config=()=>CreativeWorkspace.prototype.config.call(owner);
assert.equal(config().retain_layer_context,true,'A live Paint/Replace handoff retains the generated context');
owner.rippleImage.current=()=>false;assert.equal(config().retain_layer_context,undefined,'A stale handoff cannot change output behaviour');
owner.rippleImage.current=()=>true;delete owner.rippleImage.request.workspace.platePrimary;
assert.equal(config().retain_layer_context,undefined,'Ordinary Ripple edits retain their original masked output');
owner.rippleImage.request.workspace.platePrimary={};owner.mode='paintout';
assert.equal(config().retain_layer_context,undefined,'The image handoff must be active');owner.mode='image';
owner.rippleImage.stored=owner.rippleImage.request;owner.rippleImage.request=null;
assert.equal(config().retain_layer_context,undefined,'A stored guide alone cannot enable layer context');
owner.rippleImage.request=owner.rippleImage.stored;
const paint=config();
for(const recipe of IMAGE_MODELS.filter(model=>model.edit)){
  const ordinary=buildImageGraph({...paint,model:recipe.id,retain_layer_context:undefined});
  const retained=buildImageGraph({...paint,model:recipe.id});
  assert.equal(ordinary.zura_area_stitch.inputs.blend_mode,'Mask Feather',recipe.id);
  assert.deepEqual(ordinary.save.inputs.images,['zura_area_composite',0],recipe.id);
  assert.equal(retained.zura_area_stitch.inputs.blend_mode,'Hard Paste',recipe.id);
  assert.equal(retained.zura_area_stitch.inputs.mask,undefined,'No mask is baked into the retained crop');
  assert.equal(retained.zura_area_composite,undefined,'The editable layer is not composited twice');
  assert.deepEqual(retained.save.inputs.images,['zura_area_stitch',0],recipe.id);
  assert.deepEqual(retained.zura_area_stitch.inputs.original_image,['reference_1',0]);
  assert.equal(retained.zura_area_stitch.inputs.resize_full_image_output,'Restore Original Size');
  assert.deepEqual(Object.entries(retained).filter(([,node])=>node.class_type==='SaveImage').map(([id])=>id),['save'],'AE intermediate preparation still has one canonical image output');
  assert.deepEqual(retained.sample,ordinary.sample,'The native sampling path is unchanged');
}
console.log('Paint/Replace retains generated context only for a live handoff; standalone/Ripple masking, native sampling and single source-sized output remain unchanged');

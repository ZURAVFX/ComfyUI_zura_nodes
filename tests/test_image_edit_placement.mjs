import assert from 'node:assert/strict';
import {PaintoutMaskViewer} from '../web/paintout_studio/paintout_viewer.js';
import {IMAGE_MODELS,buildImageGraph} from '../web/image_recipes.js';

// Drive the actual pointer inversion and brush implementation. DPR scales only
// the display backing store; selection/guide strokes share proxy coordinates.
const cases=[];
for(const [width,height,dpr,zoom] of [[1920,1080,1,1],[3840,2160,2,1.7],[1333,751,1.5,.8]]){
  const scale=Math.min(1,2048/Math.max(width,height)),pw=Math.round(width*scale),ph=Math.round(height*scale),marks={mask:[],guide:[]};
  const context=kind=>new Proxy({moveTo(x,y){marks[kind].push(['move',x,y]);},lineTo(x,y){marks[kind].push(['line',x,y]);},arc(x,y,r){marks[kind].push(['circle',x,y,r]);}},{get:(obj,key)=>obj[key]||(()=>{})});
  const v=Object.assign(Object.create(PaintoutMaskViewer.prototype),{width:pw,height:ph,cssWidth:960,cssHeight:600,zoom,pan:{x:31,y:-19},root:{getBoundingClientRect:()=>({left:117,top:73})},tool:'draw',brushSize:96*scale,drawOpacity:1,drawColor:'#ff6347',maskCtx:context('mask'),sketchCtx:context('guide')});
  const t=v.transform(),wanted={x:pw*.62,y:ph*.73},point=v.point({clientX:117+t.x+wanted.x*t.scale,clientY:73+t.y+wanted.y*t.scale});
  assert.ok(Math.abs(point.x-wanted.x)<1e-8&&Math.abs(point.y-wanted.y)<1e-8);
  v.paint(point,point);assert.deepEqual(marks.mask,marks.guide,'Guide and mask use identical source-space strokes');
  const [,x,y,r]=marks.mask.find(m=>m[0]==='circle');
  cases.push({width,height,dpr,zoom,proxyWidth:pw,proxyHeight:ph,x,y,r});
}
for(const recipe of IMAGE_MODELS.filter(m=>m.edit)){
  const source={file:'original-frame-68.png',width:3840,height:2160},area={enabled:true,source_key:source.file,mask:{file:'mask.png'},guide:{file:'guide-2048.png'},context:64,feather:16};
  const graph=buildImageGraph({model:recipe.id,operation:'edit',prompt:'add a fire hydrant',shape:'auto',references:[source],edit_area:area,retain_layer_context:true});
  assert.deepEqual(graph.zura_drawing_source.inputs.width,['zura_area_source_size',0]);
  assert.deepEqual(graph.zura_drawing_source.inputs.height,['zura_area_source_size',1]);
  assert.deepEqual(graph.zura_drawing_crop.inputs.mask,graph.zura_area_crop.inputs.mask);
  assert.equal(graph.zura_drawing_crop.inputs.context_padding,graph.zura_area_crop.inputs.context_padding);
  assert.deepEqual(graph.zura_area_stitch.inputs.original_image,['reference_1',0]);
  if(!recipe.provider){
    assert.deepEqual(graph.sample.inputs.latent_image,['zura_area_masked_latent',0],recipe.id);
    assert.deepEqual(graph.zura_area_masked_latent.inputs.samples,['zura_area_latent',0]);
    assert.deepEqual(graph.zura_area_latent.inputs.pixels,['zura_area_clean',0]);
    assert.deepEqual(graph.zura_area_clean.inputs.image,['zura_area_crop',0],'No guide pixels become the latent start image');
    assert.deepEqual(graph.zura_area_mask_pixels.inputs.mask,['zura_area_crop',1]);
    assert.deepEqual(graph.zura_area_mask_size.inputs.width,graph.zura_area_clean.inputs.width);
    assert.deepEqual(graph.zura_area_mask_size.inputs.height,graph.zura_area_clean.inputs.height);
  }else assert.equal(graph.zura_area_masked_latent,undefined,'Browser providers expose no native latent/mask API');
}
if(process.argv.includes('--fixture'))console.log(JSON.stringify(cases));
else console.log('Actual brush geometry at zoom/pan/high-DPI, 4K proxy alignment, clean source latents and pre-sampling mask wiring pass for every local edit model.');

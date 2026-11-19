import assert from 'node:assert/strict';
import {sourceMegapixelLimit} from '../web/studio_resolution.js';
import {buildPaintoutGraph,paintoutValidation,paintoutHDRFrameLimit} from '../web/paintout_studio/paintout_recipes.js';
import {buildRippleStudioGraph} from '../web/studio_ripple_recipes.js';

for(const [width,height] of [[2160,3840],[3840,2160],[1921,1081],[321,181],[640,320]])for(const limit of [.25,.5,1,2,4])for(const step of [32,64]){
 const size=sourceMegapixelLimit(width,height,limit,{step});
 assert.equal(size.width%step,0);assert.equal(size.height%step,0);
 assert.ok(size.width<=width&&size.height<=height,'A limit never enlarges a source axis');
 assert.ok(size.width*size.height<=limit*1e6,'Native-grid rounding never exceeds the chosen cap');
 assert.ok(size.width>=64&&size.height>=64);
}
assert.deepEqual(sourceMegapixelLimit(2160,3840),{width:2176,height:3840},'Source size retains the previous outward grid alignment');
assert.deepEqual(sourceMegapixelLimit(2160,3840,1),{width:704,height:1280});
assert.deepEqual(sourceMegapixelLimit(512,320,4),{width:512,height:320},'A source already below the cap stays native when aligned');
for(const limit of [-1,Infinity,17])assert.throws(()=>sourceMegapixelLimit(2160,3840,limit),/valid/);

const anchors=[{frame:17,file:'Z:/clean/original_2160x3840.exr',strength:.75,enabled:true,colour_space:'srgb_display'}];
const base={mode:'targeted',source:'Z:/source/portrait.mov',mask:'Z:/mask/source-size.mov',sourceWidth:2160,sourceHeight:3840,startFrame:7,frameCount:160,sequenceFps:25,sourceColour:'srgb_display',processingSpace:'SDR (sRGB)',colourPipeline:'sdr_sdr',outputMode:'SDR video',anchors,keepAudio:true};
for(const limit of [.5,1,2,4]){
 const size=sourceMegapixelLimit(2160,3840,limit),config={...base,...size,processingMegapixelLimit:limit},before=structuredClone(config);
 assert.equal(paintoutValidation(config),'');const graph=buildPaintoutGraph(config);
 assert.equal(graph.source.inputs.framing_mode,'Full frame (stretch to working size)');
 assert.deepEqual([graph.source.inputs.render_width,graph.source.inputs.render_height],[size.width,size.height]);
 assert.deepEqual(graph.source.inputs.plate_path,['colour_check',0]);assert.equal(graph.colour_check.inputs.source,base.source);assert.equal(graph.source.inputs.mask_path,base.mask);assert.equal(graph.source.inputs.start_frame,7);assert.equal(graph.source.inputs.frame_count,160);assert.equal(graph.source.inputs.sequence_fps,25);
 assert.deepEqual(graph.save.inputs.plate,['source',2],'Final output uses the original source geometry/clock retained by the preparation node');
 assert.deepEqual(JSON.parse(graph.anchors.inputs.anchors),anchors,'Clean frame files stay original size and source-frame numbered');assert.deepEqual(config,before);
 for(const engine of ['ltx','h3']){
  const processing=sourceMegapixelLimit(2160,3840,limit,{step:engine==='h3'?32:64});
  const propagated=buildRippleStudioGraph({...config,...processing,engine,sourceColour:'srgb_display'});
  assert.equal(propagated.source.inputs.framing_mode,'Full frame (stretch to working size)');assert.equal(propagated.source.inputs.render_width,processing.width);assert.equal(propagated.source.inputs.render_height,processing.height);assert.equal(propagated.source.inputs.frame_count,160);
 }
}
assert.match(paintoutValidation({...base,width:2176,height:3840,processingMegapixelLimit:1}),/within.*limit/);
assert.equal(paintoutHDRFrameLimit({...base,width:704,height:1280,processingMegapixelLimit:1}),paintoutHDRFrameLimit({...base,width:2176,height:3840}),'The independent HDR post-pass still budgets its restored original-sized input');
console.log('Processing MP cap: portrait/4K/odd grids stay below cap without upscaling; Remove/Add/Replace graphs resize full source/mask/guides coherently and retain original delivery metadata.');

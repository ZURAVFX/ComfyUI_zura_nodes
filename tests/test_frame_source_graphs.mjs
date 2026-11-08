import assert from 'node:assert/strict';
import {buildFrameVideoGraph} from '../web/frame_video_recipes.js';
import {buildLtxFrameVideoGraph} from '../web/ltx_frame_video_recipes.js';
import {buildWanFrameVideoGraph} from '../web/wan_frame_video_recipes.js';

const h3=buildFrameVideoGraph({
  first:{file:'first.png'},last:{file:'last.png'},width:1920,height:1088,outputWidth:1920,outputHeight:1080,
  frames:56,prompt:'A camera move.',seed:42,steps:8,
});
assert.deepEqual(h3.fit_first.inputs,{image:['first',0],upscale_method:'lanczos',width:1920,height:1088,crop:'disabled'});
assert.deepEqual(h3.source_last.inputs,{image:['last',0],upscale_method:'lanczos',width:1920,height:1080,crop:'center'});
assert.deepEqual(h3.fit_last.inputs,{image:['source_last',0],upscale_method:'lanczos',width:1920,height:1088,crop:'disabled'});
assert.deepEqual(h3.restore_output.inputs,{image:['decode',0],upscale_method:'lanczos',width:1920,height:1080,crop:'disabled'});
assert.deepEqual(h3.video.inputs.images,['restore_output',0]);

const portrait=buildWanFrameVideoGraph({
  first:{file:'first.png'},last:{file:'last.png'},width:1088,height:1920,outputWidth:1080,outputHeight:1918,
  frames:49,prompt:'A camera move.',seed:42,steps:4,
});
assert.equal(portrait.fit_first.inputs.crop,'disabled');
assert.deepEqual(portrait.source_last.inputs,{image:['last',0],upscale_method:'lanczos',width:1080,height:1918,crop:'center'});
assert.deepEqual(portrait.fit_last.inputs,{image:['source_last',0],upscale_method:'lanczos',width:1088,height:1920,crop:'disabled'});
assert.deepEqual(portrait.restore_output.inputs,{image:['decode',0],upscale_method:'lanczos',width:1080,height:1918,crop:'disabled'});
assert.deepEqual(portrait.video.inputs.images,['restore_output',0]);

const ltxBase={
  first:{file:'first.png'},last:{file:'last.png'},width:992,height:576,outputWidth:990,outputHeight:544,
  frames:49,prompt:'A camera move.',seed:42,steps:8,
};
for(const stage of [{fast:true},{twoStage:true}]){
  const graph=buildLtxFrameVideoGraph({...ltxBase,...stage});
  assert.deepEqual(graph.source_last.inputs,{image:['last',0],upscale_method:'lanczos',width:990,height:544,crop:'center'});
  assert.deepEqual(graph.fit_first.inputs,{image:['first',0],upscale_method:'lanczos',width:992,height:576,crop:'disabled'});
  assert.deepEqual(graph.fit_last.inputs,{image:['source_last',0],upscale_method:'lanczos',width:992,height:576,crop:'disabled'});
  assert.deepEqual(graph.crop_output.inputs,{image:['decode',0],width:992,height:576,x:0,y:0});
  assert.deepEqual(graph.restore_output.inputs,{image:['crop_output',0],upscale_method:'lanczos',width:990,height:544,crop:'disabled'});
  assert.deepEqual(graph.video.inputs.images,['restore_output',0]);
}

const plain=buildLtxFrameVideoGraph({...ltxBase,width:960,height:544,outputWidth:960,outputHeight:540,fast:false});
assert.deepEqual(plain.restore_output.inputs,{image:['decode',0],upscale_method:'lanczos',width:960,height:540,crop:'disabled'});
assert.deepEqual(plain.video.inputs.images,['restore_output',0]);

for(const [name,build,base] of [
  ['H3',buildFrameVideoGraph,{first:{file:'first.png'},width:1920,height:1088,frames:56,prompt:'p',steps:8}],
  ['LTX',buildLtxFrameVideoGraph,{first:{file:'first.png'},width:960,height:544,frames:49,prompt:'p',steps:8}],
  ['Wan',buildWanFrameVideoGraph,{first:{file:'first.png'},width:960,height:544,frames:49,prompt:'p',steps:4}],
]){
  assert.throws(()=>build({...base,outputWidth:base.width+2,outputHeight:base.height}),/cannot exceed/i,`${name} rejects oversized output`);
  assert.throws(()=>build({...base,outputWidth:base.width-1,outputHeight:base.height}),/even/i,`${name} rejects odd output`);
  assert.throws(()=>build({...base,outputWidth:4098,outputHeight:2}),/canvas limit/i,`${name} rejects dimensions over 4096`);
}

console.log('Frame source graphs: H3, LTX Fast/Two-stage and Wan preserve source aspect during processing and restore exact delivery size.');

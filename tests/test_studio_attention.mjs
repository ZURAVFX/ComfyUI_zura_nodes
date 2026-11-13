import assert from 'node:assert/strict';
import fs from 'node:fs';
import {attentionBackend,applyAvailableAttention} from '../web/studio_attention.js';
import {buildFrameVideoGraph} from '../web/frame_video_recipes.js';
import {buildLtxFrameVideoGraph} from '../web/ltx_frame_video_recipes.js';
import {buildWanFrameVideoGraph} from '../web/wan_frame_video_recipes.js';
import {buildReferenceVideoGraph} from '../web/reference_video_recipes.js';
import {buildRippleStudioGraph,rippleStudioAvailability} from '../web/studio_ripple_recipes.js';

const kitchen={ModelAttentionBackend:{input:{required:{attention:[['pytorch attention','comfy kitchen attention']]}}}};
const torchOnly={ModelAttentionBackend:{input:{required:{attention:['COMBO',{options:['pytorch attention']}]}}}};
assert.equal(attentionBackend(kitchen),'comfy kitchen attention');
assert.equal(attentionBackend(kitchen,'pytorch attention'),'pytorch attention');
assert.equal(attentionBackend(torchOnly),'pytorch attention');
assert.equal(attentionBackend({}),null);
const cases=[
  [info=>buildFrameVideoGraph({first:{file:'first.png'},prompt:'Move',width:1344,height:768,frames:73,seed:42,steps:8},info),['attention']],
  [info=>buildLtxFrameVideoGraph({first:{file:'first.png'},prompt:'Move',width:960,height:544,frames:49,seed:42,steps:8},info),['attention']],
  [info=>buildWanFrameVideoGraph({first:{file:'first.png'},prompt:'Move',width:736,height:416,frames:49,seed:42,steps:4},info),['high_attention','low_attention']],
  [info=>buildReferenceVideoGraph({images:[{file:'first.png'}],videos:[],audios:[],prompt:'Move',width:1344,height:768,frames:124,seed:42,steps:8},info),['attention']],
];
for(const [build,ids] of cases){
  const supported=build(kitchen),fallback=build(torchOnly),native=build({});
  for(const id of ids){
    assert.equal(supported[id].inputs.attention,'comfy kitchen attention');
    assert.equal(fallback[id].inputs.attention,'pytorch attention');
    assert.equal(native[id],undefined);
  }
  for(const graph of [supported,fallback,native])for(const node of Object.values(graph))
    for(const value of Object.values(node.inputs||{}))
      if(Array.isArray(value)&&value.length===2&&typeof value[0]==='string'&&Number.isInteger(value[1]))
        assert.ok(graph[value[0]],'Graph has a live input after attention fallback');
}

const info=JSON.parse(fs.readFileSync(new URL('./fixtures/ripple_nodes.json',import.meta.url),'utf8'));
for(const name of ['ZuraRippleGuide','ZuraRippleH3Guide','WN_RippleApply','BasicGuider'])info[name]={input:{required:{}}};
const c={engine:'ltx',source:'source.mp4',startFrame:0,frameCount:17,sequenceFps:24,width:512,height:512,seed:42,anchors:[{frame:0,file:'edit.png'}]};
for(const engine of ['ltx','h3']){
  const config={...c,engine};
  const original=buildRippleStudioGraph(config,{...info,...kitchen});
  const fallback=buildRippleStudioGraph(config,{...info,...torchOnly});
  const without={...info};delete without.ModelAttentionBackend;
  const native=buildRippleStudioGraph(config,without);
  assert.equal(original.attention.inputs.attention,engine==='ltx'?'pytorch attention':'comfy kitchen attention');
  assert.equal(fallback.attention.inputs.attention,'pytorch attention');
  assert.equal(native.attention,undefined);
  const consumers=Object.values(native).flatMap(node=>Object.values(node.inputs||{}));
  assert.ok(!consumers.some(v=>Array.isArray(v)&&v[0]==='attention'));
  // Removing only the optional patch must not make a previously ready graph unready.
  assert.deepEqual(rippleStudioAvailability(without,engine).missing,rippleStudioAvailability(info,engine).missing);
}
for(const intent of ['edit','relight']){
  const graph=buildRippleStudioGraph({...c,intent},{...info,...kitchen});
  assert.equal(graph.attention.inputs.attention,'pytorch attention',`${intent} uses the shared LTX Ripple quality default`);
  assert.equal(graph.source.inputs.frame_count,c.frameCount);
  assert.equal(graph.source.inputs.sequence_fps,c.sequenceFps);
  assert.deepEqual(graph.align.inputs.length,['take',4]);
  // Experts can still change an exported graph explicitly. The common
  // capability helper must not rewrite a supported deliberate selection.
  graph.attention.inputs.attention='comfy kitchen attention';
  assert.equal(applyAvailableAttention(graph,kitchen).attention.inputs.attention,'comfy kitchen attention');
}
console.log('Attention capability selection and connected fallback graphs pass for H3, LTX, Wan and both Ripple engines.');

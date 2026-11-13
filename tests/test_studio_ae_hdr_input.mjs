import assert from 'node:assert/strict';
import {HDRSourceTool} from '../web/studio_hdr.js';
import {studioModeAdapter} from '../web/studio_mode_adapters.js';
const controls=new Map(),tool={$(id){if(!controls.has(id))controls.set(id,{});return controls.get(id);},updateMode(){},updateRangeSummary(){},sourceChanged(){},status(){}};
const colour={encoding:'unknown',sceneLinear:false,management:'ocio',ocioWorkingSpace:'ACES - ACEScg',ocioConfigFileSha256:'a'.repeat(64)};
const mapped={encoding:'acescg',sceneLinear:true,source:'verified_ae_ocio',sourceColourSha256:'b'.repeat(64),ocioConfigFileSha256:colour.ocioConfigFileSha256};
const asset={id:'exr',count:9,width:512,height:512,nativeInputColour:mapped,resolved_colour:'acescg'};
const before=structuredClone(colour);
HDRSourceTool.prototype.setSequenceAsset.call(tool,asset,{fps:30000/1001,colour});
assert.equal(tool.$('mode').value,'native');assert.equal(tool.$('colour').value,'acescg');assert.equal(tool.$('sequence-fps').value,String(30000/1001));assert.deepEqual(colour,before);
for(const patch of [{source:'name_only'},{ocioConfigFileSha256:'c'.repeat(64)},{sourceColourSha256:''},{encoding:'acescg',sceneLinear:false}]){
  assert.throws(()=>HDRSourceTool.prototype.setSequenceAsset.call(tool,{...asset,nativeInputColour:{...mapped,...patch}},{colour}),/not mapped/);
}
assert.throws(()=>HDRSourceTool.prototype.setSequenceAsset.call(tool,{...asset,nativeInputColour:undefined},{colour}),/not mapped/);
const calls=[],hdr={setSequenceAsset(...args){calls.push(args);}},creative={mode:'home',studio:{hdrTool:hdr},openHDR(){this.mode='hdr';}};
const source={precision:{sourceBitDepth:32},width:512,height:512,frameCount:9,fps:24,colour,studioAsset:asset,nativeInputColour:mapped};
await studioModeAdapter('hdr').acceptInput(creative,source);
assert.equal(calls[0][0],asset);assert.equal(calls[0][1].nativeInputColour,mapped);assert.equal(calls[0][1].colour,colour);assert.deepEqual(colour,before);
console.log('AE HDR input uses a separately verified native interpretation, retains original OCIO identity and exact cadence, and rejects name-only/mismatched mappings');

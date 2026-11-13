import assert from 'node:assert/strict';
import {importRequest,importPrecisionLabel,studioImportAEActive,StudioMediaImport} from '../web/studio_media_import.js';
import {studioModeAdapter} from '../web/studio_mode_adapters.js';
import {buildAlphaVideoGraph,alphaVideoOutput} from '../web/studio_alpha_recipes.js';
import {alphaFixture} from './test_studio_alpha_recipes.mjs';

const sequence={id:'sequence',asset_kind:'hdr_sequence',frameCount:9,resolved_colour:'acescg'};
assert.deepEqual(importRequest(sequence,'ripple',{rate:29.97,start:2,count:4}),{asset_id:'sequence',colour_space:'acescg',startFrame:2,frameCount:4,frameRate:{numerator:30000,denominator:1001}});
assert.throws(()=>importRequest(sequence,'image',{rate:25}),/source frame/);
assert.equal(importRequest(sequence,'image',{rate:25,frame:7}).frame,7);
assert.equal(importRequest(sequence,'image',{rate:25,frame:0,colour:'auto'}).colour_space,'acescg','Read source tags preserves the actual detected colour identity');
assert.throws(()=>importRequest(sequence,'ripple',{}),/frame rate/);
assert.throws(()=>importRequest({id:'still',asset_kind:'image'},'swap'),/needs a video/);
assert.equal(importPrecisionLabel({storage:'video',codec:'prores',decodedBitDepth:12,effectiveBitDepth:null}),'prores · decoded 12-bit');
assert.equal(importPrecisionLabel({storageBitDepth:32,sampleType:'float'}),'32-bit float');
const config={source:'C:/proxy.mkv',sourceWidth:64,sourceHeight:48,sourceFrames:9,startFrame:0,frameCount:9,sequenceFps:25,processingScale:1,originalSource:{asset_id:'original',proxy_id:'proxy'}};
const graph=buildAlphaVideoGraph(config,alphaFixture());assert.deepEqual(JSON.parse(graph.source.inputs.original_source),config.originalSource);
const file=(role,filename)=>({role,filename,type:'output',subfolder:'alpha'});
const result=alphaVideoOutput({outputs:{save:{images:[file('alpha','alpha.mov'),file('matte','matte.mp4'),file('preview','preview.mp4')],files:[file('native_hdr','hdr.zip'),file('alpha_float','alpha_manifest.json')]}}},config);
assert.equal(result.native_hdr.filename,'hdr.zip');assert.equal(result.alpha_float.filename,'alpha_manifest.json');
assert.equal(studioImportAEActive({studio:{aeSession:{id:'pending'}}}),true,'A pending AE session owns the source before pixels arrive');
assert.equal(studioImportAEActive({studio:{aeBridge:{closed:false}}}),true);
assert.equal(studioImportAEActive({studio:{aeBridge:{closed:true}}}),false);
let picked=false;
StudioMediaImport.prototype.choose.call({owner:{studio:{aeSession:{id:'pending'}}},picker:{click(){picked=true;}},delivery:{message(){}}});
assert.equal(picked,false,'The actual picker path respects pending AE ownership');
const imported={originalAssetId:'original',frameCount:100,width:64,height:48,processingInput:{precision:{sourceBitDepth:8},studioAsset:{id:'proxy',duration:4,processingView:{kind:'sdr8_inference'}},mediaInfo:{path:'model.mkv',kind:'video',width:64,height:48,frames:100,fps:25}}};
for(const id of ['swap','viewport','camera','ripple','relight','alpha','paintout','watermark']){
  const controls={};const w={state:{},config:{},save(){},render(){},syncForm(){},showMedia(){},$(key){return controls[key]??={value:''};},setSource(info){this.source=info;this.state.frameCount=49;},applySourceInfo(info){this.sourceInfo=info;this.state.frameCount=81;}};
  const c={mode:id,studio:w,panorama:w,ripple:w,alpha:w,paintout:w,watermark:w,show(){},selectRelightEngine(){},ensureRippleWorkspace(){},videoComposer:{selectWorkflow(){}}};
  if(!['swap','viewport'].includes(id))c.studio={};
  await studioModeAdapter(id).acceptInput(c,imported);
  assert.equal(['swap','viewport'].includes(id)?w.config.duration:id==='camera'?w.state.config.duration:w.state.frameCount,['swap','viewport','camera'].includes(id)?4:100,`${id} retains the chosen interval instead of its default duration`);
}
const native=studioModeAdapter('alpha').getSelectedOutput({studio:{},alpha:{result:{native_hdr:file('native_hdr','original_hdr.zip'),alpha:file('alpha','view.mov')}}});
assert.equal(native.kind,'hdr_sequence');assert.equal(native.master.filename,'original_hdr.zip');
assert.equal(Object.hasOwn(native,'original'),false,'Only alpha_extract DTOs accept an original field');
console.log('Global media import and original HDR Alpha graph tests passed');

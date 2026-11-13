import assert from 'node:assert/strict';
import {aeFrameContract,aeFrameConfig,prepareAEFrameGraph} from '../web/studio_ae_frame_contract.js';
import {submitOwnedGraph} from '../web/studio_owned_jobs.js';

const base=Object.freeze({schemaVersion:1,sessionId:'ae-session',frameCount:9,modelFrames:9,trimFrames:9,width:1920,height:1080,frameRate:Object.freeze({numerator:30000,denominator:1001})});
const descriptor={schemaVersion:1,kind:'ripple_keyframe',handoffId:'handoff-1',anchorId:'anchor-1',sourceFrame:8,width:1920,height:1080,parentSessionId:'ae-session',parentFrameCount:9};
const calls=[],controls=new Map();
const owner={aeFrameBase:base,aeFrameMode:'image',api:{clientId:'test'},studio:{aeBridge:{prepareGraph:async(mode,graph,parent,intermediate)=>{
  calls.push({mode,parent,intermediate});
  return {graph:{...graph,match:{class_type:'ZuraComfyLinkMatchFrames',inputs:{frame_count:1}}},ae_frame_contract:{...parent,frameCount:1,trimFrames:1,modelFrames:1,ae_intermediate_image:intermediate}};
}}},save(){return true;},render(){},message(){},startPolling(){},stopPolling(){},$(id){if(!controls.has(id))controls.set(id,{});return controls.get(id);},fetch:async(path,body)=>{calls.push({path,body});return {prompt_id:'keyframe'};}};
const config={ae_intermediate_image:descriptor,prompt:'Change the shirt to red'};
const image=aeFrameContract(owner,config);
assert.equal(image.frameCount,1);assert.equal(image.modelFrames,1);assert.equal(image.height,1080);assert.deepEqual(image.frameRate,base.frameRate);
assert.equal(base.frameCount,9);assert.equal(owner.aeFrameBase,base);
assert.throws(()=>aeFrameContract(owner,{}),/one frame/,'A standalone image cannot silently shorten a video source');
assert.throws(()=>aeFrameContract({...owner,aeFrameMode:'paintout'},{ripple_guide:'stale'}),/image guide/,'A stale guide cannot inherit the full video contract');
assert.throws(()=>aeFrameContract({...owner,aeFrameMode:'paintout'},{outpaint_guide:'stale'}),/image guide/);
for(const patch of [{parentSessionId:'other'},{parentFrameCount:8},{sourceFrame:-1},{sourceFrame:9},{sourceFrame:1.5},{width:1088},{anchorId:''},{kind:'other'},{arbitrary:true}]){
  assert.throws(()=>aeFrameContract(owner,{ae_intermediate_image:{...descriptor,...patch}}),/image guide/);
}
const outpaint={...descriptor,kind:'outpaint_guide',sourceFrame:0,width:2560,height:1440};delete outpaint.anchorId;
assert.equal(aeFrameContract(owner,{ae_intermediate_image:outpaint}).width,2560);
assert.throws(()=>aeFrameContract(owner,{ae_intermediate_image:{...outpaint,sourceFrame:1}}),/source frame/);
const graph={save:{class_type:'SaveImage',inputs:{images:['decode',0]}}};
await submitOwnedGraph(owner,graph,aeFrameConfig(owner,config),'auto',{zura_image:true});
assert.equal(calls[0].mode,'image');assert.equal(calls[0].parent,base,'The authenticated server receives the unchanged parent source contract');
assert.deepEqual(calls[0].intermediate,descriptor);
const prompt=calls.find(call=>call.path==='/prompt').body;
assert.equal(prompt.extra_data.ae_frame_contract.frameCount,1);assert.deepEqual(prompt.extra_data.ae_intermediate_image,descriptor);
assert.equal(owner.job.config.ae_frame_contract.frameCount,1);
owner.aeFrameMode='paintout';
assert.equal(aeFrameContract(owner,{engine:'ltx'}).frameCount,9,'The final video still needs the entire source interval');
const normal={prompt:'Normal image'};assert.deepEqual(await prepareAEFrameGraph({},graph,normal),{graph,config:normal});
console.log('AE intermediate image: N1 keyframe, unchanged N9 parent, fractional rate, scoped guide raster, stale descriptor rejection and prompt provenance passed');

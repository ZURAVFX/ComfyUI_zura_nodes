import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(process.env.CAMERA_AE_RUNTIME_ROOT||path.join(here,'..'));
const {aeFramePolicy,modelAEFrameContract}=await import(pathToFileURL(path.join(root,'web/studio_ae_frame_contract.js')));
const python=process.env.CAMERA_TEST_PYTHON||'python';
const call=(source,config)=>JSON.parse(execFileSync(python,[path.join(here,'camera_ae_cadence_bridge.py'),root],{
 input:JSON.stringify({source,config}),encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
const base=(numerator,denominator=1,count=9)=>({schemaVersion:1,sessionId:'a'.repeat(32),frameCount:count,trimFrames:count,modelFrames:count,width:512,height:512,frameRate:{numerator,denominator}});
for(const [numerator,denominator] of [[24,1],[25,1],[30000,1001]])for(const count of [9,10,48,120]){
 const captured=base(numerator,denominator,count),fps=numerator/denominator;
 const contract=modelAEFrameContract(captured,aeFramePolicy('camera',{engine:'h3'}));
 const source={sha:'a'.repeat(64),duration:5,has_audio:true,file:'fixture-source.mp4',fps};
 const config={width:512,height:512,start:2,duration:4,ae_frame_contract:contract};
 const result=call(source,config);assert.equal(result.ok,true,result.error);
 assert.equal(result.frames,count);assert.equal(result.trimFrames,count);assert.equal(result.fps,fps);
 assert.equal(result.duration,count/fps);assert.deepEqual(result.contract.frameRate,captured.frameRate);
 assert.equal(contract.modelFrames,result.paddedFrames,'Frontend model padding must match the independent Camera planner');
 assert.deepEqual(result.preparedLatentLengths,[result.paddedFrames]);
 assert.ok(result.preparedFrameGuards.length>0);assert.ok(result.preparedFrameGuards.every(n=>n===count),'Actual bridge finalisation retains exactly the captured source count');
 for(const field of ['conditioningFPS','audioFPS','videoFPS'])assert.equal(result[field],fps,field);
 assert.equal(result.timeline.fps,fps);assert.equal(result.timeline.length,count);
 // The source's actual clock/raster still has to match, not just its AE label.
 const wrongRate=call({...source,fps:fps===24?25:24},config);assert.equal(wrongRate.ok,false);assert.match(wrongRate.error,/match all AE source frames/);
 const wrongRaster=call(source,{...config,width:520});assert.equal(wrongRaster.ok,false);assert.match(wrongRaster.error,/changes the source raster/);
 const tooShort=call({...source,duration:.1},config);assert.equal(tooShort.ok,false);assert.match(tooShort.error,/Trim inside/);
 const wrongCount=call(source,{...config,ae_frame_contract:{...contract,trimFrames:8}});assert.equal(wrongCount.ok,false);assert.match(wrongCount.error,/exact source frame count/);
 const ordinary=call(source,{width:512,height:512,start:0,duration:count/fps});assert.equal(ordinary.ok,true);assert.equal(ordinary.frames,count);assert.equal(ordinary.fps,fps);
}
assert.throws(()=>modelAEFrameContract(base(25,1,121),aeFramePolicy('camera',{})),/range of 121 frames/,'The existing120-source-frame cap remains even though native model padding can reach121');
for(const mode of ['swap','viewport','director','frames','references'])assert.throws(()=>modelAEFrameContract(base(25),aeFramePolicy(mode,{engine:'h3'})),/24 fps/,mode);
console.log('Camera AE cadence: real Python planner/LTX graph preserve 25 and 30000/1001 source clocks; count/raster/rate guards and H3 restrictions remain.');

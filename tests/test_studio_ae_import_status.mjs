import assert from 'node:assert/strict';
import {StudioAEBridge} from '../web/studio_comfylink.js';
const file={filename:'retained.png',subfolder:'result',type:'output'};
function fixture(statuses){
  const calls=[],messages=[],b=Object.create(StudioAEBridge.prototype);
  const attributes=new Map(),send={textContent:'Send to AE',setAttribute:(key,value)=>attributes.set(key,value),toggleAttribute:(key,on)=>on?attributes.set(key,''):attributes.delete(key),getAttribute:key=>attributes.get(key)};
  Object.assign(b,{closed:false,session:{id:'test-session',capability:'test-capability',context:{capabilities:{nativeVideoReturn:false}}},transferPollDelay:0,send,studio:{creative:{mode:'image',studio:{},items:[{file}],selectedImage:0}},
    message:value=>messages.push(value),request:async(path,body)=>{calls.push({path,body});return path==='/result'?{status:'import_pending'}:statuses.shift()||{status:'import_pending'};}});
  return {b,calls,messages};
}
{
  const {b,calls}=fixture([]);let releaseResult,releaseStatus;
  b.request=path=>{calls.push({path});return new Promise(resolve=>{if(path==='/result')releaseResult=resolve;else releaseStatus=resolve;});};
  const sending=b.sendResult();assert.equal(b.send.textContent,'Sending to AE…');
  assert.equal(b.send.getAttribute('aria-busy'),'true');assert.equal(b.send.getAttribute('data-busy'),'');
  await b.sendResult();assert.equal(calls.filter(call=>call.path==='/result').length,1,'Busy click cannot resubmit');
  releaseResult({status:'import_pending'});await sending;
  assert.equal(b.send.textContent,'Importing in AE…');assert.equal(b.send.disabled,true);
  for(let i=0;i<100&&!releaseStatus;i++)await new Promise(resolve=>setTimeout(resolve,2));
  assert.equal(typeof releaseStatus,'function');releaseStatus({status:'sent'});await settled(b);
  assert.equal(b.send.textContent,'Send to AE');assert.equal(b.send.getAttribute('aria-busy'),'false');
  assert.equal(b.send.getAttribute('data-busy'),undefined);
}
async function settled(b){for(let i=0;i<100&&b.importPolling;i++)await new Promise(resolve=>setTimeout(resolve,2));assert.equal(b.importPolling,false);}
for(const missing of [undefined,{id:'test-session'}]){
  const {b,messages}=fixture([]);b.session=missing;delete b.request;
  let fetched=false;b.api={fetchApi:()=>{fetched=true;throw Error('An ended session must not send a result');}};
  await b.sendResult();assert.equal(fetched,false,'Missing session authority cannot reach the local broker');
  assert.match(messages.at(-1),/AE link ended/);
}
{
  const {b,calls,messages}=fixture([{status:'import_pending'},{status:'sent'}]);
  await b.sendResult();assert.equal(b.send.disabled,true);await settled(b);
  assert.equal(messages.at(-1),'Sent to After Effects');assert.equal(b.importPending,false);assert.equal(b.send.textContent,'Send to AE');
  assert.equal(calls.filter(call=>call.path==='/result').length,1);
}
{
  const note='HDR master retained. Choose a scene-linear AE working space such as ACEScg for verified HDR transfer.';
  const {b,calls,messages}=fixture([{status:'import_pending',diagnostic:note},{status:'sent'}]);
  await b.sendResult();await settled(b);assert.equal(messages.at(-1),note);assert.equal(b.send.textContent,'Check transfer');
  await b.sendResult();await settled(b);assert.equal(messages.at(-1),'Sent to After Effects');
  assert.equal(calls.filter(call=>call.path==='/result').length,1,'Checking cannot resubmit the retained master');
}
{
  const {b,calls,messages}=fixture([{status:'import_pending'}]);b.transferPollTimeout=0;
  await b.sendResult();await settled(b);assert.match(messages.at(-1),/Check transfer/);assert.equal(b.send.disabled,false);
  b.closed=true;b.stopImportWatch();const count=calls.length;await new Promise(resolve=>setTimeout(resolve,5));assert.equal(calls.length,count);
}
{
  const {b,messages}=fixture([]);let release;const started=new Promise(resolve=>release=resolve);let response;
  b.request=async path=>path==='/result'?{status:'import_pending'}:new Promise(resolve=>{response=resolve;release();});
  await b.sendResult();for(let i=0;i<100&&!response;i++)await new Promise(resolve=>setTimeout(resolve,2));assert.equal(typeof response,'function');await started;b.closed=true;b.stopImportWatch();const count=messages.length;response({status:'sent'});
  await new Promise(resolve=>setTimeout(resolve,5));assert.equal(messages.length,count,'Late host confirmation cannot mutate a departed workspace');
}
{
  const {b,calls,messages}=fixture([]);b.session.context.transferPrecision='float32';
  let conversions=0,converted=false;
  const delivery={output:'hdr',hdrFormat:'acescg_exr',preparing:false,delivery:{busy:false},isBusyFor:()=>false,
    outputFor:(_mode,raw)=>converted?{kind:'hdr_sequence',master:{filename:'hdr.zip',subfolder:'hdr',type:'output'},
      colour:{encoding:'acescg',sceneLinear:true}}:raw,
    convertCurrent(){conversions++;}};
  b.studio.creative.outputSettings={delivery};
  await b.sendResult();assert.equal(conversions,1,'32-bit SDR result starts real HDR reconstruction');
  assert.equal(calls.length,0,'SDR image cannot be sent as a 32-bit HDR result');
  assert.match(messages.at(-1),/HDR reconstruction/);
  converted=true;b.request=async path=>{calls.push({path});return {status:'sent'};};
  await b.sendResult();assert.equal(calls.filter(call=>call.path==='/result').length,1);
}
{
  const {b,calls,messages}=fixture([]);
  b.session.context={capabilities:{nativeStillReturn:true},range:{mode:'frame'},transferPrecision:'prores12'};
  b.source={frameCount:1,manifest:{frames:[{}]},processingInput:{conversion:'raw_numeric_to_sdr8'},
    sourceTransfer:{kind:'native_still',profile:'png16'}};
  b.request=async(path,body)=>{calls.push({path,body});return {status:'sent'};};
  assert.equal(b.rawReturnHeld(),false,'Qualified one-frame PNG may return normally');
  await b.sendResult();assert.equal(calls.filter(call=>call.path==='/result').length,1);
  assert.equal(calls.find(call=>call.path==='/result').body.kind,'image');
  assert.equal(calls.find(call=>call.path==='/result').body.master.filename,'retained.png');
  b.session.context.capabilities.nativeStillReturn=false;
  await b.sendResult();assert.match(messages.at(-1),/not qualified/);
  assert.equal(calls.filter(call=>call.path==='/result').length,1,'Without authority the result is retained');
  b.session.context.capabilities.nativeStillReturn=true;
  b.studio.creative.mode='video';b.studio.creative.studio.config={workflow_mode:'swap'};
  b.studio.creative.studio.project={phase:'done',results:[{asset:{filename:'movie.mp4',subfolder:'output',type:'output'}}]};
  await b.sendResult();assert.match(messages.at(-1),/Only a finished Image Edit master/);
  assert.equal(calls.filter(call=>call.path==='/result').length,1,'A forged video cannot use the still authority');
}
{
  const {b,calls,messages}=fixture([]);
  b.session.context={capabilities:{nativeStillReturn:true},range:{mode:'frame'},transferPrecision:'prores12'};
  b.source={frameCount:1,manifest:{frames:[{}]},processingInput:{conversion:'raw_numeric_to_sdr8'},
    sourceTransfer:{kind:'native_still',profile:'png16'}};
  const master={filename:'master.exr',subfolder:'ZURA STUDIO/image-layers/receipt',type:'output'};
  b.studio.creative.items=[{file:{filename:'preview.png',subfolder:'preview',type:'output'},master,
    image_layers:{schemaVersion:1},colour:{encoding:'srgb_display',sceneLinear:false}}];
  b.request=async(path,body)=>{calls.push({path,body});return {status:'sent'};};
  await b.sendResult();assert.equal(calls.find(call=>call.path==='/result').body.kind,'image');
  assert.equal(calls.find(call=>call.path==='/result').body.master.filename,'master.exr');
  b.studio.creative.items=[{master,colour:{encoding:'srgb_display',sceneLinear:false}}];
  await b.sendResult();assert.match(messages.at(-1),/Only a finished Image Edit master/);
  assert.equal(calls.filter(call=>call.path==='/result').length,1,'Unreceipted EXR cannot use still return authority');
}
console.log('AE asynchronous import: confirmation, safe diagnostics, bounded checks, no resubmission and late-response fencing passed');

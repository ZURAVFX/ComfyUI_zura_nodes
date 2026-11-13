import assert from 'node:assert/strict';
import {StudioAEBridge} from '../web/studio_comfylink.js';
const file={filename:'retained.png',subfolder:'result',type:'output'};
function fixture(statuses){
  const calls=[],messages=[],b=Object.create(StudioAEBridge.prototype);
  Object.assign(b,{closed:false,transferPollDelay:0,send:{textContent:'Send to AE'},studio:{creative:{mode:'image',studio:{},items:[{file}],selectedImage:0}},
    message:value=>messages.push(value),request:async(path,body)=>{calls.push({path,body});return path==='/result'?{status:'import_pending'}:statuses.shift()||{status:'import_pending'};}});
  return {b,calls,messages};
}
async function settled(b){for(let i=0;i<100&&b.importPolling;i++)await new Promise(resolve=>setTimeout(resolve,2));assert.equal(b.importPolling,false);}
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
console.log('AE asynchronous import: confirmation, safe diagnostics, bounded checks, no resubmission and late-response fencing passed');

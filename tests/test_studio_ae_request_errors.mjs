import assert from 'node:assert/strict';
import {StudioAEBridge} from '../web/studio_comfylink.js';
const owner={closed:false,session:{id:'session',capability:'local-capability'},api:{}};
for(const [status,suffix,message] of [[403,'/source',/Send the shot again/],[410,'/result',/^AE link ended\. Send the shot again from After Effects, then choose your retained result\.$/],[422,'/prepare-graph',/range or dimensions/],[422,'/result',/retained/],[503,'/source',/Check the connection/]]){
  owner.api.fetchApi=async()=>({ok:false,status,json:async()=>{throw Error('Unexpected token from private server body');}});
  await assert.rejects(StudioAEBridge.prototype.request.call(owner,suffix,{}),error=>message.test(error.message));
}
owner.api.fetchApi=async()=>({ok:false,status:422,json:async()=>({diagnostic:'Source cadence does not match'})});
await assert.rejects(StudioAEBridge.prototype.request.call(owner,'/result',{}),/Source cadence does not match/);
const requestOptions=[];
owner.api.fetchApi=async(_path,options)=>{requestOptions.push(options);return {ok:true,status:200,json:async()=>({ok:true})};};
assert.deepEqual(await StudioAEBridge.prototype.request.call(owner,'/source',{}),{ok:true});
assert.equal(requestOptions.at(-1).timeoutMs,600000,'A large local AE source must outlive ComfyUI\'s short JSON timeout');
assert.deepEqual(await StudioAEBridge.prototype.request.call(owner,'/status'),{ok:true});
assert.equal(requestOptions.at(-1).timeoutMs,undefined,'Only source staging gets the longer timeout');
const ended='AE link ended. Send the shot again from After Effects, then choose your retained result.';
for(const status of [401,403,410]){
  owner.api.fetchApi=async()=>({ok:false,status,json:async()=>({error:'Private broker details should not replace recovery guidance'})});
  await assert.rejects(StudioAEBridge.prototype.request.call(owner,'/result',{}),error=>error.message===ended&&error.status===status);
}
const file={filename:'retained.png',subfolder:'result',type:'output'},item={file},calls=[];
const bridge=Object.assign(Object.create(StudioAEBridge.prototype),{closed:false,session:{id:'ended',capability:'existing-capability'},send:{textContent:'Send to AE'},status:{textContent:''},studio:{creative:{mode:'image',studio:{},items:[item],selectedImage:0}},
  api:{fetchApi:async(path,options)=>{calls.push({path,options});return {ok:false,status:410,json:async()=>{throw Error('410: Gone');}};}}});
await bridge.sendResult();assert.equal(bridge.status.textContent,ended);
assert.equal(bridge.studio.creative.items[0],item);assert.equal(bridge.studio.creative.selectedImage,0);assert.equal(bridge.send.disabled,false);
assert.equal(calls.length,1);assert.match(calls[0].path,/\/ended\/result$/);assert.equal(calls[0].options.method,'POST');
assert.equal(bridge.session.capability,'existing-capability','Error reporting does not invent or replace authority');
console.log('AE bridge HTTP errors remain actionable without exposing raw server bodies');

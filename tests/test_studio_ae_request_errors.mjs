import assert from 'node:assert/strict';
import {StudioAEBridge} from '../web/studio_comfylink.js';
const owner={closed:false,session:{id:'session',capability:'local-capability'},api:{}};
for(const [status,suffix,message] of [[403,'/source',/Send the shot again/],[422,'/prepare-graph',/range or dimensions/],[422,'/result',/retained/],[503,'/source',/Check the connection/]]){
  owner.api.fetchApi=async()=>({ok:false,status,json:async()=>{throw Error('Unexpected token from private server body');}});
  await assert.rejects(StudioAEBridge.prototype.request.call(owner,suffix,{}),message);
}
owner.api.fetchApi=async()=>({ok:false,status:422,json:async()=>({diagnostic:'Source cadence does not match'})});
await assert.rejects(StudioAEBridge.prototype.request.call(owner,'/result',{}),/Source cadence does not match/);
owner.api.fetchApi=async()=>({ok:true,status:200,json:async()=>({ok:true})});
assert.deepEqual(await StudioAEBridge.prototype.request.call(owner,'/source',{}),{ok:true});
console.log('AE bridge HTTP errors remain actionable without exposing raw server bodies');

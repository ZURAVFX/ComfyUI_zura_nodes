import assert from 'node:assert/strict';
import {fetchJsonWithTimeout} from '../web/media_picker_requests.js';

const response=(status,body)=>({ok:status>=200&&status<300,status,text:async()=>body});
const ok=await fetchJsonWithTimeout(async (_path,options)=>{assert.ok(options.signal);return response(200,'{"ok":true}');},'/ok',{},100);
assert.deepEqual(ok,{ok:true});
const hanging=(_path,{signal})=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})),{once:true}));
await assert.rejects(fetchJsonWithTimeout(hanging,'/timeout',{},10),/timed out or was cancelled/);
const controller=new AbortController();const cancelled=fetchJsonWithTimeout(hanging,'/cancel',{signal:controller.signal},1000);controller.abort();await assert.rejects(cancelled,/timed out or was cancelled/);
await assert.rejects(fetchJsonWithTimeout(async()=>response(200,'not-json'),'/bad',{},100),/invalid JSON/);
console.log('media picker request tests passed');

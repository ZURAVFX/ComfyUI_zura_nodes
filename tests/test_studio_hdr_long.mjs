import assert from 'node:assert/strict';
import {HDRLongJobClient} from '../web/studio_hdr_long.js';
const values=new Map();globalThis.localStorage={setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
let state='rendering',calls=[],fail=false;
const api={async fetchApi(path,options){
  calls.push([path,options]);if(fail)throw Error('offline');
  const data=path.endsWith('/cancel')?{}:path.endsWith('/jobs')?{id:'job',state:'ready'}:{id:'job',state,completed:1,total:3};
  return {ok:true,status:200,json:async()=>data};
}};
const updates=[];const client=new HDRLongJobClient(api,value=>updates.push(value));
await Promise.all([client.start({mode:'sdr'}),client.start({mode:'sdr'})]);
await new Promise(resolve=>setTimeout(resolve,5));clearTimeout(client.timer);
assert.equal(calls.filter(([path])=>path.endsWith('/jobs')).length,1);
assert.equal(client.id,'job');assert.equal(values.get('zura-hdr-long-job'),'job');
fail=true;await client.poll();clearTimeout(client.timer);assert.equal(updates.at(-1).state,'reconnecting');assert.equal(client.busy,true);
fail=false;await client.cancel();assert.equal(client.cancelPending,true);assert.equal(client.busy,true);
state='cancelled';await client.poll();assert.equal(client.busy,false);assert.equal(values.size,0);
const missing=new HDRLongJobClient({async fetchApi(){return {ok:false,status:400,json:async()=>({error:'Job unavailable. It was not restarted.'})};}},value=>updates.push(value));
missing.reconnect('old');await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(missing.busy,false);assert.match(updates.at(-1).error,/not restarted/);
let submits=0,recoveries=0;
const dropped=new HDRLongJobClient({async fetchApi(path){
  if(path.endsWith('/jobs')){submits++;throw Error('response lost');}
  if(path.includes('/requests/')){recoveries++;return {ok:true,status:200,json:async()=>({id:'recovered',state:'rendering'})};}
  return {ok:true,status:200,json:async()=>({id:'recovered',state:'complete'})};
}},value=>updates.push(value));
await dropped.start({mode:'sdr'});await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(submits,1);assert.equal(recoveries,1);assert.equal(dropped.busy,false);
assert.equal(values.size,0,'recovered completion clears both saved IDs');
console.log('Long HDR client keeps one job, reconnects safely and waits for cancellation.');

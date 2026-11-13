import assert from 'node:assert/strict';
import {StudioSessionLease} from '../web/studio_session_lease.js';

function fixture(){
  let clock=Date.now(),nextID=0;
  const timers=new Map(),calls=[],messages=[];
  const bridge={closed:false,root:{isConnected:true},session:{id:'scoped',capability:'adapter-token',expiresAt:new Date(clock+900000).toISOString(),lease:{renewable:true,maxExpiresAt:new Date(clock+28800000).toISOString()}},message:value=>messages.push(value),api:{}};
  bridge.api.fetchApi=async(path,options)=>{calls.push({path,options});return {ok:true,status:200,json:async()=>({ok:true,expiresAt:new Date(clock+900000).toISOString(),maxExpiresAt:bridge.session.lease.maxExpiresAt,token:'must never enter session'})};};
  const lease=new StudioSessionLease(bridge,{now:()=>clock,setTimer:(fn,ms)=>{const id=++nextID;timers.set(id,{fn,ms});return id;},clearTimer:id=>timers.delete(id)});
  return {bridge,lease,timers,calls,messages,advance:ms=>clock+=ms,now:()=>clock};
}
{
  const f=fixture();assert.equal(f.lease.start(),true);assert.equal(f.timers.size,1);assert.equal([...f.timers.values()][0].ms,300000);
  const original=f.now();
  for(let i=0;i<4;i++){f.advance(600000);assert.equal(await f.lease.renewNow(),true);}
  assert.ok(f.now()>original+1800000);assert.equal(f.timers.size,1);
  assert.equal(f.calls.length,4);assert.ok(f.calls.every(call=>call.path==='/zura/comfylink/v1/studio/sessions/scoped/renew'));
  assert.ok(f.calls.every(call=>call.options.body==='{}'&&call.options.headers['X-ComfyLink-Studio-Session']==='adapter-token'));
  assert.equal(f.bridge.session.token,undefined);assert.equal(f.messages.length,0);
  f.lease.dispose();assert.equal(f.timers.size,0);
}
{
  const f=fixture();let resolve;
  f.bridge.api.fetchApi=(path,options)=>{f.calls.push({path,options});return new Promise(done=>resolve=done);};
  const one=f.lease.renewNow(),two=f.lease.renewNow();assert.equal(one,two);assert.equal(f.calls.length,1);
  resolve({ok:true,status:200,json:async()=>({ok:true,expiresAt:new Date(f.now()+900000).toISOString(),maxExpiresAt:f.bridge.session.lease.maxExpiresAt})});
  assert.equal(await one,true);assert.equal(f.lease.pending,null);f.lease.dispose();
}
{
  const f=fixture();let resolve;
  f.bridge.api.fetchApi=(path,options)=>{f.calls.push({path,options});return new Promise(done=>resolve=done);};
  f.lease.start();const before=f.bridge.session.expiresAt,pending=f.lease.renewNow();f.lease.dispose();
  assert.equal(f.calls[0].options.signal.aborted,true);assert.equal(f.timers.size,0);
  resolve({ok:true,status:200,json:async()=>({ok:true,expiresAt:new Date(f.now()+1800000).toISOString(),maxExpiresAt:f.bridge.session.lease.maxExpiresAt})});
  assert.equal(await pending,false);assert.equal(f.bridge.session.expiresAt,before);assert.equal(f.lease.pending,null);
}
for(const status of [401,403,404,410]){
  const f=fixture();f.bridge.api.fetchApi=async()=>({ok:false,status});f.lease.start();
  assert.equal(await f.lease.renewNow(),false);assert.equal(f.lease.closed,true);assert.equal(f.timers.size,0);assert.match(f.messages.at(-1),/retained/);
}
{
  const f=fixture();const before=f.bridge.session.expiresAt;f.bridge.api.fetchApi=()=>{throw Error('offline');};
  assert.equal(await f.lease.renewNow(),false);assert.equal(f.lease.pending,null,'A synchronous transport failure cannot leave renewal stuck');
  assert.equal(f.bridge.session.expiresAt,before);assert.equal([...f.timers.values()][0].ms,30000);assert.equal(f.messages.length,0);
  f.advance(900001);assert.equal(await f.lease.renewNow(),false);assert.match(f.messages.at(-1),/retained/);assert.equal(f.timers.size,0);
}
for(const invalid of ['maximum','expiry','malformed']){
  const f=fixture(),before=f.bridge.session.expiresAt;
  f.bridge.api.fetchApi=async()=>({ok:true,status:200,json:async()=>({ok:true,expiresAt:invalid==='malformed'?'invalid':new Date(f.now()+(invalid==='expiry'?3600000:900000)).toISOString(),maxExpiresAt:new Date(f.now()+(invalid==='maximum'?30000000:28800000)).toISOString()})});
  assert.equal(await f.lease.renewNow(),false);assert.equal(f.bridge.session.expiresAt,before);assert.equal([...f.timers.values()][0].ms,30000);f.lease.dispose();
}
{
  const f=fixture();f.bridge.root.isConnected=false;assert.equal(await f.lease.renewNow(),false);assert.equal(f.calls.length,0);
}
{
  const f=fixture();f.bridge.session.lease.renewable=false;assert.equal(f.lease.start(),false);assert.equal(f.timers.size,0);f.lease.dispose();
}
console.log('Scoped AE session lease: long active renewal, absolute limit, concurrent requests, retry and disposal guards passed');

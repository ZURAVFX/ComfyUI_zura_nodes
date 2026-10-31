import assert from 'node:assert/strict';
import {HDRLongJobClient} from '../web/studio_hdr_long.js';

const storage=new Map();
globalThis.localStorage={setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
const response=data=>({ok:true,status:200,json:async()=>data});
const settle=()=>new Promise(resolve=>setImmediate(resolve));

// A status response can arrive after the artist leaves the workspace. It may
// update the saved job, but must not create another background polling loop.
let resolveStatus,requests=0;
const updates=[];
const client=new HDRLongJobClient({fetchApi(){requests++;return new Promise(resolve=>{resolveStatus=resolve;});}},job=>updates.push(job),'lifecycle');
client.reconnect('owned-job');
const observation=client.poll();
assert.equal(requests,1,'Repeated observation shares the current request');
client.close();resolveStatus(response({id:'owned-job',state:'rendering'}));
await observation;
assert.equal(client.timer,null,'A late response cannot restart polling after close');
assert.equal(client.busy,true,'Closing does not cancel a server job');
assert.equal(client.id,'owned-job');

const resumed=client.resume();client.resume();client.poll();
assert.equal(requests,2,'Repeated reopening starts only one status request');
client.close();client.resume();
assert.equal(requests,2,'Rapid close/reopen reuses the in-flight request');
resolveStatus(response({id:'owned-job',state:'complete'}));await resumed;
assert.equal(updates.filter(job=>job.state==='complete').length,1);
assert.equal(client.busy,false);assert.equal(client.timer,null);
assert.equal(storage.size,0);client.close();

// Recovering a finished request must deliver it once without asking for the
// same completed job again. This also preserves the original submission ID.
let submits=0,recoveries=0,statusReads=0;
const recovered=[];
const terminal=new HDRLongJobClient({async fetchApi(path){
  if(path.endsWith('/jobs')){submits++;throw Error('Acceptance response lost');}
  if(path.includes('/requests/')){recoveries++;return response({id:'finished-job',state:'complete',result:{files:['master']}});}
  statusReads++;return response({id:'finished-job',state:'complete'});
}},job=>recovered.push(job),'terminal');
await terminal.start({mode:'sdr'});await settle();
assert.equal(submits,1);assert.equal(recoveries,1);assert.equal(statusReads,0);
assert.equal(recovered.filter(job=>job.state==='complete').length,1);
assert.equal(terminal.busy,false);assert.equal(storage.size,0);terminal.close();

// Leaving during submission still remembers the accepted job. Reopening
// observes it; it never repeats the render submission.
let accept,acceptedSubmits=0,acceptedReads=0;
const acceptance=new HDRLongJobClient({async fetchApi(path){
  if(path.endsWith('/jobs')){acceptedSubmits++;return new Promise(resolve=>{accept=resolve;});}
  acceptedReads++;return response({id:'accepted-job',state:'complete'});
}},()=>{},'acceptance');
const submission=acceptance.start({mode:'sdr'});acceptance.close();
accept(response({id:'accepted-job',state:'queued'}));await submission;
assert.equal(acceptedSubmits,1);assert.equal(acceptedReads,0);
assert.equal(storage.get('acceptance-job'),'accepted-job');
await acceptance.resume();
assert.equal(acceptedSubmits,1);assert.equal(acceptedReads,1);
assert.equal(acceptance.busy,false);assert.equal(storage.size,0);acceptance.close();

// Request recovery is also single-flight, including when its result arrives
// after close. Only an explicit reopen resumes observation of the found job.
let resolveRecovery,recoveryReads=0,jobReads=0;
const recovering=new HDRLongJobClient({fetchApi(path){
  if(path.includes('/requests/')){recoveryReads++;return new Promise(resolve=>{resolveRecovery=resolve;});}
  jobReads++;return Promise.resolve(response({id:'found-job',state:'complete'}));
}},()=>{},'recovery');
recovering.reconnectRequest('request-id');const pending=recovering.recover();
assert.equal(recoveryReads,1);recovering.close();
resolveRecovery(response({id:'found-job',state:'rendering'}));await pending;
assert.equal(jobReads,0);assert.equal(recovering.timer,null);
await recovering.resume();assert.equal(jobReads,1);assert.equal(storage.size,0);
recovering.close();
console.log('PASS HDR lifecycle: one observer, retained accepted jobs, no hidden polling and one terminal delivery.');

import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createServer} from 'node:http';
import {scopedStudioAPI,fenceAEWorkspace,StudioAELifecycle} from '../web/studio_ae_lifecycle.js';
import {StudioAEBridge} from '../web/studio_comfylink.js';

const calls=[],normal={items:[{file:'normal-result.png'}],job:{id:'normal-running'}};
let finish;
const api={clientId:'desktop',fetchApi:async(path,options)=>{calls.push({path,options});if(path==='/zura/slow')return new Promise(resolve=>{finish=resolve;});return {ok:true,status:200,json:async()=>({})};},addEventListener(){assert.equal(this,api);}};
const session={id:'a'.repeat(32),capability:'b'.repeat(64),comfyOrigin:'http://127.0.0.1:8188'},scope=scopedStudioAPI(api,session);
scope.api.addEventListener('status',()=>{});
await scope.api.fetchApi('/prompt',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
assert.equal(calls[0].options.headers.get('X-ComfyLink-Studio-Id'),session.id);
assert.equal(calls[0].options.headers.get('X-ComfyLink-Studio-Session'),session.capability);
assert.equal(calls[0].options.headers.get('Content-Type'),'application/json');
for(const path of ['https://other.test/','/\\evil.test/x','/\n/evil.test/x','//evil.test/x','/unknown'])await assert.rejects(()=>scope.api.fetchApi(path),/local ComfyUI/);
assert.equal(calls[0].options.redirect,'error');
const late=scope.api.fetchApi('/zura/slow');scope.end();finish({ok:true});
await assert.rejects(late,error=>error.name==='AbortError');
await assert.rejects(()=>scope.api.fetchApi('/prompt'),error=>error.status===410);
assert.equal(calls.length,2,'An ended scope never sends another prompt');
await api.fetchApi('/normal');assert.equal(calls.at(-1).options,undefined,'Normal Studio API is untouched');
const prefixedCalls=[];
const prefixed=scopedStudioAPI({apiURL:path=>'/api'+path,fetchApi:async(path,options)=>{prefixedCalls.push({path,options});return {ok:true};}},session);
await prefixed.api.fetchApi('/zura/studio/hdr/jobs',{method:'POST',body:'{}'});
assert.equal(prefixedCalls.length,1,'The real Comfy /api prefix is accepted');assert.equal(prefixedCalls[0].options.redirect,'error');

let foreignHits=0;
const foreign=createServer((request,response)=>{foreignHits++;response.end('unexpected');});
await new Promise(resolve=>foreign.listen(0,'127.0.0.1',resolve));
const foreignOrigin='http://127.0.0.1:'+foreign.address().port;
const local=createServer((request,response)=>{response.writeHead(302,{Location:foreignOrigin+'/capture'});response.end();});
await new Promise(resolve=>local.listen(0,'127.0.0.1',resolve));
const localOrigin='http://127.0.0.1:'+local.address().port;
try{
  const redirectScope=scopedStudioAPI({fetchApi:(path,options)=>fetch(localOrigin+path,options)}, {...session,comfyOrigin:localOrigin});
  await assert.rejects(()=>redirectScope.api.fetchApi('/zura/redirect'),TypeError);
  assert.equal(foreignHits,0,'An actual HTTP redirect cannot send the session capability to another origin');
  let sent=0;const wrongBase=scopedStudioAPI({apiURL:path=>foreignOrigin+path,fetchApi(){sent++;}}, {...session,comfyOrigin:localOrigin});
  await assert.rejects(()=>wrongBase.api.fetchApi('/prompt'),/local ComfyUI/);assert.equal(sent,0,'The SDK base origin is checked too');
}finally{await Promise.all([new Promise(resolve=>local.close(resolve)),new Promise(resolve=>foreign.close(resolve))]);}

const accepted={file:'retained.exr'},creative={items:[accepted],job:{id:'old-image'},pendingSubmission:{requestId:'old'},stopPolling(){this.stopped=true;},frames:{job:{id:'frames'},items:[accepted]},outputSettings:{delivery:{close(){this.wasClosed=true;}}}};
const studio={creative,aeScope:scope,resetEpoch:4};fenceAEWorkspace(studio);
assert.equal(studio.resetEpoch,5);assert.equal(creative.job,null);assert.equal(creative.pendingSubmission,null);
assert.equal(creative.frames.job,null);assert.equal(creative.frames.aeSessionEnded,true);
assert.deepEqual(creative.items,[accepted]);assert.deepEqual(creative.frames.items,[accepted]);
assert.equal(creative.outputSettings.delivery.closed,true);assert.equal(creative.outputSettings.delivery.wasClosed,true);
assert.equal(normal.job.id,'normal-running');assert.equal(normal.items[0].file,'normal-result.png');

let ended=0;
const bridge={session:{...session},api:{fetchApi:async()=>({status:410,ok:false})},cancelAndLeave:async()=>{ended++;bridge.closed=true;}};
const lifecycle=new StudioAELifecycle(bridge);await lifecycle.poll();assert.equal(ended,1);await lifecycle.poll();assert.equal(ended,1);lifecycle.dispose();
let resolveStatus;
const stale={session:{...session},api:{fetchApi:()=>new Promise(resolve=>{resolveStatus=resolve;})},cancelAndLeave(){throw Error('A stale lifecycle must not end its replacement');}};
const staleLifecycle=new StudioAELifecycle(stale);const polling=staleLifecycle.poll();staleLifecycle.dispose();resolveStatus({ok:true,status:200,json:async()=>({status:'cancelled'})});await polling;

let releaseCancel,restored=0;
const ending={session:{...session},api:{fetchApi:async(path)=>{assert.match(path,/\/cancel$/);return new Promise(resolve=>{releaseCancel=resolve;});}},dispose(release){assert.equal(release,false);this.closed=true;},onLeave(){restored++;}};
const first=StudioAEBridge.prototype.cancelAndLeave.call(ending);
assert.equal(restored,1,'Cancel immediately restores the normal workspace');
assert.equal(StudioAEBridge.prototype.cancelAndLeave.call(ending),first,'Repeated cancellation shares one request');releaseCancel({ok:true});await first;

// Exercise the real handoff transition with a small DOM boundary. The previous
// AE session must be cancelled before a fresh source receives a new workspace.
const source=await fs.readFile(new URL('../web/studio.js',import.meta.url),'utf8');
const start=source.indexOf('async function openDesktopAESession('),end=source.indexOf('\napp.registerExtension(',start);
const constructed=[];
class FakeStudio{
  constructor(options){this.aeSession=options.aeSession;this.creative={items:[],show(){}};this.container={isConnected:false,querySelector:()=>({src:''}),querySelectorAll:()=>[],remove(){this.isConnected=false;}};constructed.push(this);}
  open(){this.container.isConnected=true;return Promise.resolve();}
  close(){this.container.isConnected=false;this.onClosed?.();}
}
const doc={documentElement:{classList:{add(){}}}};
const make=new Function('createStudioSession','api','ArtistStudio','studioLaunchStorage','StudioAEBridge','document','openZuraStudio',
  `let registeredStudio;${source.slice(start,end).replaceAll('import.meta.url',JSON.stringify(import.meta.url))};return {open:openDesktopAESession,set:value=>registeredStudio=value,get:()=>registeredStudio};`);
const harness=make(async()=>({...session}),api,FakeStudio,value=>({id:value.id}),class{constructor(){this.source=null;}},doc,()=>{});
const normalStudio={container:{isConnected:false},draft:normal};
const old={aeSession:{id:'old'},container:{isConnected:true},creative:{items:[{file:'old-selected.png'}]},aeBridge:{async cancelAndLeave(){restored++;harness.set(normalStudio);}}};
harness.set(old);assert.equal(await harness.open({}),true);assert.equal(constructed.length,1);
assert.notEqual(harness.get(),old);assert.deepEqual(harness.get().creative.items,[],'A new shot cannot inherit the previous selected image');
assert.equal(old.creative.items[0].file,'old-selected.png','The old completed result remains retained');
harness.get().close();assert.equal(harness.get(),normalStudio,'Leaving the replacement returns to the original normal Studio');
assert.equal(normalStudio.draft.job.id,'normal-running');
console.log('AE lifecycle: scoped cancellation, late callback fencing, HDR stop, fresh handoff and normal workspace preservation passed');

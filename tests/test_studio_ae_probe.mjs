import assert from 'node:assert/strict';
import fs from 'node:fs';
import {beginAEProbe,probeGlobals} from '../web/studio_ae_probe.js';

function fixture(){
  const handlers=new Map(),sent=[],status={textContent:'Connecting'};
  const parent={postMessage:(message,target)=>sent.push({message,target})};
  const scope={parent,location:{origin:'http://127.0.0.1:8222'},document:{querySelector:()=>status},addEventListener:(type,handler)=>handlers.set(type,handler),removeEventListener:type=>handlers.delete(type)};
  const message=(data,{source=parent,origin='null'}={})=>handlers.get('message')?.({data,source,origin});
  return {scope,parent,sent,status,message,handlers};
}
const nonce='a'.repeat(64),frame=fixture();let loaded=0,loadedHost=null;
beginAEProbe({scope:frame.scope,load:host=>{loaded++;loadedHost=host;}});
assert.deepEqual(frame.sent[0].message,{type:'zura-studio-probe-ready',hostSchema:1});
frame.message({type:'zura-studio-probe-challenge',hostSchema:1,nonce},{source:{}});
assert.equal(frame.sent.length,1,'Only the parent window can challenge the frame');
frame.message({type:'zura-studio-probe-challenge',hostSchema:1,nonce});
assert.equal(frame.sent[1].message.type,'zura-studio-probe-report');
assert.equal(frame.sent[1].message.nonce,nonce);
assert.equal(frame.sent[1].target,'*','Opaque CEP parent origins require a wildcard target');
assert.deepEqual(frame.sent[1].message.globals,{__adobe_cep__:false,cep:false,cep_node:false,require:false,process:false});
frame.message({type:'zura-studio-probe-allow',hostSchema:1,nonce:'b'.repeat(64)});
frame.message({type:'zura-studio-probe-allow',hostSchema:1,nonce},{origin:'http://other.example'});
frame.message({type:'zura-studio-probe-allow',hostSchema:1,nonce});
assert.equal(loaded,0,'A mismatched nonce, origin or missing proxy bootstrap cannot load Studio');
frame.message({type:'zura-studio-proxy-bootstrap',hostSchema:1,nonce,kind:'comfylink-ae-proxy-v1',uiOrigin:frame.scope.location.origin,backendOrigin:'http://127.0.0.1:8188'});
frame.message({type:'zura-studio-probe-allow',hostSchema:1,nonce});
assert.equal(loaded,1);assert.equal(frame.handlers.has('message'),false,'Allow loads once and removes the listener');
assert.equal(loadedHost.uiOrigin,frame.scope.location.origin);
assert.equal(loadedHost.backendOrigin,'http://127.0.0.1:8188');
await Promise.resolve();
assert.equal(frame.sent.at(-1).message.type,'zura-studio-mount-ready','Child reports only after load resolves');
assert.equal(frame.sent.at(-1).message.nonce,nonce);

const rejected=fixture();
beginAEProbe({scope:rejected.scope,load:async()=>{const error=new Error('private token');error.studioPhase='session';throw error;}});
rejected.message({type:'zura-studio-probe-challenge',hostSchema:1,nonce});
rejected.message({type:'zura-studio-proxy-bootstrap',hostSchema:1,nonce,kind:'comfylink-ae-proxy-v1',uiOrigin:rejected.scope.location.origin,backendOrigin:'http://127.0.0.1:8188'});
rejected.message({type:'zura-studio-probe-allow',hostSchema:1,nonce});
await new Promise(resolve=>setImmediate(resolve));
assert.equal(rejected.sent.at(-1).message.type,'zura-studio-mount-failed');
assert.equal(rejected.sent.at(-1).message.code,'session');
assert.doesNotMatch(JSON.stringify(rejected.sent.at(-1).message),/private token/);

const unsafe=fixture();unsafe.scope.require=()=>{};let unsafeLoads=0;
beginAEProbe({scope:unsafe.scope,load:()=>unsafeLoads++});
unsafe.message({type:'zura-studio-probe-challenge',hostSchema:1,nonce},{origin:'http://127.0.0.1:8199'});
assert.equal(unsafe.sent[1].message.globals.require,true);assert.equal(unsafe.sent[1].target,'http://127.0.0.1:8199');
unsafe.message({type:'zura-studio-probe-allow',hostSchema:1,nonce},{origin:'http://127.0.0.1:8199'});
assert.equal(unsafeLoads,0);assert.match(unsafe.status.textContent,/cannot run/);
assert.equal(probeGlobals(unsafe.scope).require,true);

const direct=fixture();direct.scope.parent=direct.scope;let directLoads=0;
beginAEProbe({scope:direct.scope,load:()=>directLoads++});assert.equal(directLoads,1,'Direct local browser loading stays available');
direct.scope.process={};beginAEProbe({scope:direct.scope,load:()=>directLoads++});assert.equal(directLoads,1,'Direct CEP or Node loading is refused');
const html=fs.readFileSync(new URL('../web/studio_ae.html',import.meta.url),'utf8');
assert.match(html,/src="\.\/studio_ae_probe\.js"/);
assert.doesNotMatch(html,/src="\.\/studio_ae_entry\.js"/);
console.log('AE iframe probe gates Studio on parent source, origin, nonce and host globals.');

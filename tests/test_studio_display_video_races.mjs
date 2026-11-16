import assert from 'node:assert/strict';
import {StudioDisplayBinding} from '../web/studio_display_binding.js';

const original='/view?filename=original.mov&type=input';
const preset=view=>({config:'adobe-ae://fixture',display:'ACES',view});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const response=url=>({ok:true,json:async()=>({preview_only:true,url})});
const flush=async()=>{for(let index=0;index<5;index++)await new Promise(resolve=>setImmediate(resolve));};

class Media extends EventTarget{
  constructor(){super();this.tagName='VIDEO';this._src=original;this.readyState=1;this.currentTime=.4;this.duration=2;
    this.paused=false;this.volume=.35;this.muted=true;this.playbackRate=1.25;this.loop=true;this.hidden=false;this.isConnected=true;this.loads=[];}
  get src(){return this._src;}
  set src(value){this._src=value;this.readyState=0;this.loads.push(value);}
  get currentSrc(){return this._src;}
  getAttribute(name){return name==='src'?this._src:null;}
  load(){}
  play(){return Promise.resolve();}
  closest(){return null;}
  finish(){this.readyState=1;this.dispatchEvent(new Event('loadedmetadata'));}
}

function harness(fetchApi){
  const media=new Media();let state={revision:1,selection:preset('A')};
  const selector={asset_id:'a'.repeat(32)},source={selector,key:'same-registered-original',colour:'auto'};
  const settings={closed:false,root:{contains:()=>true},status:{textContent:''},menu:null,
    displayStore:{get:()=>state},currentFor:()=>source,api:{fetchApi},response:async value=>value,sync(){}};
  const binding=new StudioDisplayBinding(settings,media);
  return {media,binding,settings,selector,choose(selection){state={revision:state.revision+1,selection};binding.refresh();}};
}

{
  const h=harness(async()=>response('/zura/studio/display/video/A'));
  h.binding.refresh();await flush();assert.equal(h.media.src,'/zura/studio/display/video/A');
  h.choose(null);await flush();assert.equal(h.media.src,'/zura/studio/display/video/A','The pending load is fenced until it settles');
  h.media.finish();await flush();assert.equal(h.media.src,original,'None queues original restoration behind the pending load');
  h.media.finish();await flush();assert.equal(h.media.src,original);
  assert.deepEqual([h.media.currentTime,h.media.volume,h.media.muted,h.media.playbackRate,h.media.loop],[.4,.35,true,1.25,true]);
  h.binding.close();
}

{
  const h=harness(async()=>response('/zura/studio/display/video/A'));
  h.binding.refresh();await flush();assert.equal(h.media.src,'/zura/studio/display/video/A');
  h.binding.close();h.media.finish();await flush();assert.equal(h.media.src,original,'Closing restores source after pending metadata');
  h.media.finish();await flush();assert.equal(h.media.src,original);
}

{
  const older=deferred(),requests=[];
  const h=harness(async(_path,options)=>{requests.push(JSON.parse(options.body));return requests.length===1?older.promise:response('/zura/studio/display/video/B');});
  h.binding.refresh();await flush();h.choose(preset('B'));await flush();
  assert.equal(h.media.src,'/zura/studio/display/video/B');
  older.resolve(response('/zura/studio/display/video/A'));await flush();
  assert.equal(h.media.src,'/zura/studio/display/video/B','An older server response cannot replace the new transform');
  h.media.finish();await flush();assert.equal(h.media.src,'/zura/studio/display/video/B');
  assert.deepEqual(requests.map(item=>item.source),[h.selector,h.selector]);
  h.binding.close();await flush();assert.equal(h.media.src,original);h.media.finish();await flush();
}

{
  const h=harness(async(_path,options)=>response('/zura/studio/display/video/'+JSON.parse(options.body).view));
  h.binding.refresh();await flush();assert.equal(h.media.src,'/zura/studio/display/video/A');
  h.choose(preset('B'));await flush();
  h.media.finish();await flush();assert.equal(h.media.src,original,'Old preview must restore the approved source first');
  h.media.finish();await flush();assert.equal(h.media.src,'/zura/studio/display/video/B');
  h.media.finish();await flush();assert.equal(h.media.src,'/zura/studio/display/video/B');
  h.binding.close();await flush();h.media.finish();await flush();assert.equal(h.media.src,original);
}

console.log('Display video races: None, close, late server response and overlapping media loads preserve approved source and latest transform');

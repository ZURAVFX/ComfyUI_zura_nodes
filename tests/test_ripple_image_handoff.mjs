import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {RippleImageHandoff} from '../web/studio_ripple_image.js';

const defer=()=>{let resolve;return {promise:new Promise(r=>{resolve=r;}),resolve:value=>resolve(value)};};
const storage=new Map();
globalThis.localStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
function fixture({clearStorage=true}={}){
  if(clearStorage)storage.clear();
  const fields=Object.fromEntries(['model','shape','width','height','seed','prompt','random'].map(k=>[k,{value:k,checked:false}]));
  let closed=0,draw=[];
  const doc={createElement(){return {getContext:()=>({drawImage(...args){draw=args;}}),toBlob(callback){callback(new Blob(['exact'],{type:'image/png'}));}};}};
  const old={filename:'previous.png',subfolder:'images'},owner={mode:'ripple',models:[{}],root:{ownerDocument:doc},items:[{file:old}],selectedImage:0,references:[],
    config:()=>({operation:'create',references:[{file:'old-ref.png'}],model:'oldmodel',shape:'auto',width:640,height:480,seed:9,prompt:'oldprompt',random:false,autoCanvasSuppressed:false}),
    api:{async fetchApi(path){if(path==='/upload/image')return {ok:true,json:async()=>({name:'source.png',subfolder:'zura_images/ripple'})};return {ok:true,blob:async()=>new Blob(['original'])};}},
    $(key){return fields[key];},async setImageOperation(value){this.operation=value;},show(mode){this.mode=mode;},save(){},render(){},renderGallery(){},message(value){this.error=value;}};
  const anchor={id:'anchor',frame:12,file:''};
  const workspace={source:{path:'source.mp4',width:1081,height:1919},revision:0,state:{engine:'h3',prompt:'replace object'},owner,
    anchors:()=>[anchor],busy:()=>false,$:()=>({value:'replace object'}),prepareAnchor:async()=>({url:'/original-frame'}),render(){},save(){},message(value){this.status=value;},
    async importAnchorFile(a,file,check){check();a.file=file.name;}};
  owner.ripple=workspace;owner.ensureRippleWorkspace=()=>workspace;
  const handoff=new RippleImageHandoff(owner);handoff.syncImageUI=()=>{};
  globalThis.createImageBitmap=async()=>({width:1024,height:1024,close(){closed++;}});
  return {handoff,owner,workspace,anchor,fields,old,closed:()=>closed,draw:()=>draw};
}

// First reference is always the original selected video frame, not a previous edit.
{
  const f=fixture();f.anchor.file='previous-edit.png';await f.handoff.edit(f.workspace,f.anchor);
  assert.equal(f.owner.mode,'image');assert.equal(f.owner.references[0].file,'zura_images/ripple/source.png');
  assert.equal(f.fields.prompt.value,'replace object');assert.equal(f.fields.shape.value,'auto');assert.equal(f.owner.selectedImage,-1);
  assert.equal(f.handoff.request.anchor,f.anchor);assert.equal(f.fields.width.value,1081);
  f.owner.items.unshift({file:{filename:'unrelated.png'}});await f.handoff.leave();
  assert.equal(f.owner.selectedImage,1);assert.equal(f.owner.mode,'ripple');assert.equal(f.fields.prompt.value,'oldprompt');assert.equal(f.handoff.request,null);
}
// Only this edit request's result can return. Stretch to exact source raster, no cover crop.
{
  const f=fixture();await f.handoff.edit(f.workspace,f.anchor);const id=f.handoff.request.id;
  f.owner.items=[{file:{filename:'edited.png'},ripple_guide:'other'}];f.owner.selectedImage=0;
  await f.handoff.useResult();assert.equal(f.anchor.file,'');
  f.owner.items[0].ripple_guide=id;f.fields.prompt.value='replace the car';await f.handoff.useResult();
  assert.equal(f.anchor.file,'ripple_frame_12.png');assert.deepEqual(f.draw().slice(1),[0,0,1081,1919]);assert.equal(f.closed(),1);
  assert.equal(f.workspace.state.prompt,'replace the car');assert.equal(f.owner.mode,'ripple');
}
// Source changes while preparing cannot hijack the image workspace.
{
  const f=fixture(),pending=defer(),started=defer();f.workspace.prepareAnchor=()=>{started.resolve();return pending.promise;};
  const work=f.handoff.edit(f.workspace,f.anchor);await started.promise;f.workspace.revision++;pending.resolve({url:'/old'});await work;
  assert.equal(f.handoff.request,null);assert.equal(f.owner.mode,'ripple');assert.match(f.workspace.status,/changed/);
}
// Navigation during import must not attach a late response to the keyframe.
{
  const f=fixture();await f.handoff.edit(f.workspace,f.anchor);f.owner.items=[{file:{filename:'edited.png'},ripple_guide:f.handoff.request.id}];f.owner.selectedImage=0;
  const pending=defer(),started=defer();f.workspace.importAnchorFile=async(a,file,check)=>{started.resolve();await pending.promise;check();a.file=file.name;};
  const work=f.handoff.useResult();await started.promise;f.owner.mode='video';pending.resolve();await work;
  assert.equal(f.anchor.file,'');assert.equal(f.owner.mode,'video');assert.match(f.owner.error,/workspace changed/);assert.equal(f.closed(),1);
}
// Existing image jobs and an unrelated active guide cannot be replaced.
{
  const f=fixture();f.owner.pendingSubmission={id:'pending'};await f.handoff.edit(f.workspace,f.anchor);assert.equal(f.handoff.request,null);
  f.owner.pendingSubmission=null;f.owner.outpaintGuide={request:{id:'outpaint'}};await f.handoff.edit(f.workspace,f.anchor);assert.match(f.workspace.status,/frame-extension/);
}
// A browser refresh rebinds the saved request to the restored source and anchor,
// not to the previous page's object references or revision counter.
{
  const original=fixture();await original.handoff.edit(original.workspace,original.anchor);const id=original.handoff.request.id;
  const fresh=fixture({clearStorage:false});fresh.workspace.revision=37;
  const source=fresh.workspace.source;fresh.workspace.source=null;
  fresh.workspace.restoreSource=async()=>{fresh.workspace.source=source;};
  fresh.owner.mode='image';await fresh.handoff.resume();
  assert.equal(fresh.handoff.request.id,id);assert.equal(fresh.handoff.request.workspace,fresh.workspace);assert.equal(fresh.handoff.request.anchor,fresh.anchor);
  fresh.owner.items=[{file:{filename:'recovered.png'},ripple_guide:id}];fresh.owner.selectedImage=0;fresh.fields.prompt.value='restored edit';
  await fresh.handoff.useResult();assert.equal(fresh.anchor.file,'ripple_frame_12.png');assert.equal(fresh.owner.mode,'ripple');
  assert.equal(fresh.fields.prompt.value,'oldprompt');assert.equal(fresh.fields.width.value,640);assert.equal(fresh.handoff.stored,null);assert.equal(storage.size,0);
}
// Closing Studio preserves the handoff; returning to Image recreates its controls.
{
  const f=fixture();await f.handoff.edit(f.workspace,f.anchor);
  const {document}=parseHTML('<main><section><header class="zc-image-heading"></header></section></main>');
  f.owner.root=document.querySelector('main');f.handoff.syncImageUI=RippleImageHandoff.prototype.syncImageUI;
  f.handoff.syncImageUI();assert.ok(f.handoff.banner?.isConnected);assert.match(f.handoff.banner.textContent,/Select an edit area or use the whole frame/);f.handoff.dispose();assert.equal(f.handoff.banner,null);assert.ok(f.handoff.request);
  await f.handoff.resume();assert.ok(f.handoff.banner?.isConnected);assert.equal(f.handoff.banner.hidden,false);
  assert.equal(f.handoff.banner.querySelector('[data-ripple-return]').disabled,false);
}
// Reset/replacement invalidates the tracked token even if an image import is
// already in flight, so its late response cannot populate a new keyframe.
{
  const f=fixture();await f.handoff.edit(f.workspace,f.anchor);const id=f.handoff.request.id;
  f.owner.items=[{file:{filename:'edited.png'},ripple_guide:id}];f.owner.selectedImage=0;
  const started=defer(),pending=defer();f.workspace.importAnchorFile=async(a,file,check)=>{started.resolve();await pending.promise;check();a.file=file.name;};
  const work=f.handoff.useResult();await started.promise;f.handoff.invalidate(f.workspace);pending.resolve();await work;
  assert.equal(f.anchor.file,'');assert.equal(f.handoff.request,null);assert.equal(f.handoff.stored,null);assert.equal(storage.size,0);
}
// A persisted keyframe no longer present in the restored workspace is rejected.
{
  const original=fixture();await original.handoff.edit(original.workspace,original.anchor);
  const fresh=fixture({clearStorage:false});fresh.workspace.anchors=()=>[];await fresh.handoff.resume();
  assert.equal(fresh.handoff.request,null);assert.equal(fresh.handoff.stored,null);assert.match(fresh.owner.error,/source or keyframe changed/);
}
// Temporary source-connection failures retain an obvious Back path. Returning
// restores the previous image draft even before its source can reconnect.
{
  const original=fixture();await original.handoff.edit(original.workspace,original.anchor);
  const fresh=fixture({clearStorage:false});fresh.owner.mode='image';fresh.workspace.source=null;fresh.workspace.restoreSource=async()=>{};
  await fresh.handoff.resume();assert.ok(fresh.handoff.stored);assert.equal(fresh.handoff.request,null);
  await fresh.handoff.leave();assert.equal(fresh.owner.mode,'ripple');assert.equal(fresh.fields.prompt.value,'oldprompt');assert.equal(storage.size,0);
}
// Do not mutate the image workspace if the handoff cannot be saved for recovery.
{
  const f=fixture(),write=localStorage.setItem;localStorage.setItem=()=>{throw Error('quota');};
  try{await f.handoff.edit(f.workspace,f.anchor);assert.equal(f.owner.mode,'ripple');assert.equal(f.handoff.request,null);assert.match(f.workspace.status,/storage/i);}finally{localStorage.setItem=write;}
}
// A local painted selection is flushed and saved before the temporary video
// frame replaces Image 1, then restored on return without leaking onto that frame.
{
  const f=fixture(),originalConfig=f.owner.config;
  const area={enabled:true,source_key:'old-ref.png',mask:{file:'masks/previous.png'},context:64,feather:16};
  let current=area,flushed=0,resets=0,restored;
  f.owner.config=()=>({...originalConfig(),edit_area:current});
  f.owner.imageArea={async flush(){flushed++;},reset(){resets++;current=null;},restore(value){restored=value;current=value;}};
  await f.handoff.edit(f.workspace,f.anchor);
  assert.equal(flushed,1);assert.equal(resets,1);assert.equal(current,null);
  assert.deepEqual(f.handoff.request.previous.config.edit_area,area);
  await f.handoff.leave();assert.deepEqual(restored,area);
}
console.log('Ripple image handoff preserves original frames, exact raster, shared prompts, refresh/reopen recovery, edit-area isolation and stale-result ownership.');

// Relight's return path survives reopening without becoming the ordinary edit draft.
{
 const f=fixture();f.workspace.intent='relight';await f.handoff.edit(f.workspace,f.anchor);
 assert.equal(f.handoff.stored.intent,'relight');
 let restoredIntent;f.owner.ensureRippleWorkspace=intent=>{restoredIntent=intent;return f.workspace;};
 await f.handoff.leave();assert.equal(restoredIntent,'relight');assert.equal(f.owner.mode,'ripple');
}

// Recovering an older image return must not replace the currently visible Relight workspace.
{
 const f=fixture();await f.handoff.edit(f.workspace,f.anchor);f.handoff.request=null;
 const visible={intent:'relight'};f.owner.mode='ripple';f.owner.ripple=visible;f.owner.rippleWorkspaces=new Map([['edit',f.workspace],['relight',visible]]);
 await f.handoff.resume();assert.equal(f.owner.ripple,visible);assert.equal(f.handoff.request.workspace,f.workspace);
}

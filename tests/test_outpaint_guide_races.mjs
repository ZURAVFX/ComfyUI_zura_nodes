import assert from 'node:assert/strict';
import {OutpaintFirstFrame} from '../web/studio_outpaint_first_frame.js';

let canvasKey='original', closed=0;
globalThis.document={createElement:()=>({width:0,height:0,getContext:()=>({drawImage(){}}),toBlob(cb){cb(new Blob(['image']));}})};
globalThis.createImageBitmap=async()=>({width:640,height:640,close(){closed++;}});
const fields={};
const owner={
  mode:'image',items:[{file:{filename:'old.png',subfolder:'images',type:'output'}}],selectedImage:0,
  api:{async fetchApi(){return {ok:true,async blob(){return new Blob(['result']);}};}},
  $(id){return fields[id]||(fields[id]={value:'',checked:false});},
  async setImageOperation(){},save(){},render(){},renderGallery(){},show(mode){this.mode=mode;},message(message){this.error=message;},
};
const workspace={owner,source:{id:'one'},config:()=>({source:canvasKey,start:0,mode:'expand',width:640,height:640,left:0,top:0,right:0,bottom:0}),
  dimensions:()=>({width:640,height:640}),hdrBusy:()=>false,paint(){},message(message){this.status=message;},result:{hidden:false},canvas:{hidden:false}};
function makeGuide(){
  const guide=Object.create(OutpaintFirstFrame.prototype);
  Object.assign(guide,{workspace,owner,asset:null,transferRevision:0,root:{open:false},preview:{hidden:true},syncImageUI(){},update(){},url(){return '/guide';}});
  return guide;
}
function defer(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
const blob=new Blob(['input'],{type:'image/png'});

// A source replacement while upload is in flight must not bind an old frame to the new source.
{
  const guide=makeGuide(),pending=defer(),started=defer();
  guide.store=async()=>{started.resolve();return pending.promise;};
  const upload=guide.upload(blob);await started.promise;canvasKey='replacement';pending.resolve({id:'old',file:'guide.png'});await upload;
  assert.equal(guide.asset,null);assert.match(workspace.status,/changed/);assert.equal(closed,1);
  workspace.submitting=false;canvasKey='original';
}
// A reset invalidates even a same-geometry upload while the server is responding.
{
  const guide=makeGuide(),pending=defer(),started=defer();
  guide.store=async()=>{started.resolve();return pending.promise;};
  const upload=guide.upload(blob);await started.promise;guide.clear();pending.resolve({id:'old',file:'guide.png'});await upload;
  assert.equal(guide.asset,null);assert.match(workspace.status,/changed/);
}
// A late result import must not attach an image to a changed canvas.
{
  const guide=makeGuide(),pending=defer(),started=defer();
  guide.request={id:'request',key:guide.key(),width:640,height:640};owner.items=[{file:{filename:'guide.png'},outpaint_guide:'request'}];
  guide.store=async()=>{started.resolve();return pending.promise;};
  const importing=guide.useResult();await started.promise;canvasKey='changed';pending.resolve({id:'old',file:'guide.png'});await importing;
  assert.equal(guide.asset,null);assert.match(owner.error,/changed/);assert.equal(guide.preview.hidden,true);canvasKey='original';
}
// Switching workspaces during import must not navigate the user back or attach the guide.
{
  const guide=makeGuide(),pending=defer(),started=defer();owner.mode='image';owner.error='';
  guide.request={id:'request',key:guide.key(),width:640,height:640};owner.items=[{file:{filename:'guide.png'},outpaint_guide:'request'}];
  guide.store=async()=>{started.resolve();return pending.promise;};
  const importing=guide.useResult();await started.promise;owner.mode='references';pending.resolve({id:'old',file:'guide.png'});await importing;
  assert.equal(guide.asset,null);assert.equal(owner.mode,'references');assert.match(owner.error,/workspace changed/);
}
// A current guide completes the hand-off and becomes the visible preview.
{
  const guide=makeGuide();owner.mode='image';
  guide.request={id:'request',key:guide.key(),width:640,height:640};owner.items=[{file:{filename:'guide.png'},outpaint_guide:'request'}];
  guide.store=async()=>({id:'accepted',file:'guide.png'});
  await guide.useResult();assert.equal(guide.asset.id,'accepted');assert.equal(guide.boundKey,guide.key());assert.equal(owner.mode,'outpaint');assert.equal(guide.preview.hidden,false);
}
// The selected pre-existing image follows its file identity when a new guide is prepended.
{
  const guide=makeGuide(),old={filename:'old.png',subfolder:'images',type:'output'};
  const c={operation:'edit',references:[],loras:[],model:'m',shape:'auto',width:640,height:640,seed:1,prompt:'',random:false};
  guide.request={id:'request'};guide.previous={config:c,selectedFile:old};owner.items=[{file:{filename:'new-guide.png'}},{file:old}];
  await guide.leave();assert.equal(owner.selectedImage,1);assert.equal(owner.mode,'outpaint');
  guide.previous={config:c,selectedFile:old};owner.items=[{file:{filename:'new-guide.png'}}];
  await guide.leave();assert.equal(owner.selectedImage,-1,'A removed previous image must not select an unrelated result');
}
assert.equal(closed,5,'Decoded image bitmaps close on successful and stale paths');
console.log('Outpaint guide rejects stale source/canvas uploads and restores the selected image by file identity.');

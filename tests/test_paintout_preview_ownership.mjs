import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';
import {PaintoutEditor} from '../web/paintout_studio/paintout_editor.js';

const {document}=parseHTML('<html><body><section><div class="zf-viewer"></div></section></body></html>');
globalThis.document=document;
const deferred=()=>{let resolve,reject;return {promise:new Promise((a,b)=>{resolve=a;reject=b;}),resolve,reject};};
function workspace(){
  const page=document.querySelector('section').cloneNode(true),controls=new Map();
  for(const key of ['message','comparison','image-slot','empty','history']){const e=document.createElement('div');controls.set(key,e);page.append(e);}
  const video=document.createElement('video');video.pause=()=>{};controls.set('video',video);page.append(video);
  const stages=[];
  const w=Object.assign(Object.create(PaintoutWorkspace.prototype),{page,state:{source:'old.mkv',mask:'',sourceColour:'auto',anchors:[],editorStage:'trim',mode:'targeted'},sourceInfo:{path:'old.mkv',width:512,height:320},playhead:0,view:'source',modelInfo:{},nativeSamplePreview:{clear(){},dispose(){}},
    $(id){return controls.get(id);},url:path=>path,fps:()=>29.97,render(){},save(){},stopPolling(){},editor:{active:false,stage:'trim',sequence:0,previewSequence:0,async setStage(stage){stages.push(stage);},close(){}},stages});
  return w;
}
{
  const w=workspace();w.preview();const old=w.$('image-slot').firstElementChild;
  assert.match(old.src,/space=auto/);old.onerror();assert.match(w.$('message').textContent,/Preview unavailable/);
  w.state.sourceColour='srgb_display';w.preview();const current=w.$('image-slot').firstElementChild;
  assert.notEqual(current,old);assert.match(current.src,/space=srgb_display/);
  current.onload();assert.equal(w.$('message').textContent,'');old.onerror();assert.equal(w.$('message').textContent,'','Late failure cannot resurrect a cleared preview error');
  w.message('Generation failed; your result is retained');current.onload();assert.match(w.$('message').textContent,/Generation failed/);
  w.preview();const pending=w.$('image-slot').firstElementChild;w.message('A newer meaningful error');pending.onerror();assert.equal(w.$('message').textContent,'A newer meaningful error');
  w.message('');w.preview();const beforeMask=w.$('image-slot').firstElementChild;w.editor.active=true;w.view='mask';beforeMask.onerror();assert.equal(w.$('message').textContent,'','Hidden trim preview cannot report after Mask opens');
}
{
  const w=workspace();w.state.sourceColour='srgb_display';w.sourceInfo.media_url='/original.mkv';w.preview();
  const failedVideo=w.$('video').onerror;failedVideo();
  assert.ok(w.videoFallback.has('old.mkv'));assert.match(w.$('message').textContent,/codec cannot play/);
  const fallback=w.$('image-slot').firstElementChild;assert.match(fallback.src,/space=srgb_display/);fallback.onload();assert.equal(w.$('message').textContent,'');
  failedVideo();assert.equal(w.$('message').textContent,'','A superseded video error cannot replace the successful frame fallback');
}
{
  const w=workspace();w.state.sourceColour='srgb_display';w.info=async()=>({path:'old.mkv',width:512,height:320,resolved_colour:'auto'});await w.open();
  assert.deepEqual(w.stages,['trim']);assert.equal(w.state.sourceColour,'srgb_display');assert.match(w.$('image-slot').firstElementChild.src,/space=srgb_display/,'An explicit source interpretation survives raw inspection');
}
{
  const w=workspace(),read=deferred();w.info=()=>read.promise;
  const opening=w.open();w.state.source='new.mkv';w.state.sourceColour='srgb_display';const currentInfo=w.sourceInfo={path:'new.mkv',resolved_colour:'srgb_display'};
  read.resolve({path:'old.mkv',colour_error:'unsupported tags'});await opening;
  assert.equal(w.sourceInfo,currentInfo);assert.deepEqual(w.stages,[]);assert.equal(w.$('image-slot').children.length,0);
}
{
  const w=workspace(),read=deferred();w.state.sourceColour='srgb_display';w.info=()=>read.promise;
  const opening=w.open();const rebound=w.sourceInfo={path:'old.mkv',resolved_colour:'srgb_display',broker:true};
  read.resolve({path:'old.mkv',resolved_colour:'auto',colour_error:'unsupported tags'});await opening;
  assert.equal(w.sourceInfo,rebound,'A verified rebind of the same path supersedes an old raw inspection');assert.deepEqual(w.stages,[]);
}
{
  const w=workspace(),read=deferred();w.info=()=>read.promise;const opening=w.open();w.close();read.reject(Error('late lookup failure'));await opening;
  assert.equal(w.$('message').textContent,'');assert.deepEqual(w.stages,[],'Closing invalidates pending source inspection');
}
{
  const w=workspace();w.state.sourceColour='srgb_display';const values={grow:{value:0},'grow-value':{},opacity:{value:45}};
  const editor=Object.assign(Object.create(PaintoutEditor.prototype),{w,active:true,stage:'mask',sequence:0,maskEditVersion:0,viewer:{frame:0,async setFrame(url){assert.match(url,/space=srgb_display/);},async setMask(){},setGrow(){},setOpacity(){}},
    selected:()=>null,maskSegment:()=>null,async flushManual(){},updateControls(){},async authoritativePreview(){},$(id){return values[id];}});w.editor=editor;
  w.previewFailed('Preview unavailable. Check the file and its colour space.');await editor.frameChanged(true);assert.equal(w.$('message').textContent,'','A successful real Mask frame load clears the owned trim-preview warning');
  w.message('Could not save the project');await editor.frameChanged(true);assert.equal(w.$('message').textContent,'Could not save the project','Frame success never clears a non-preview error');
}
{
  const w=workspace(),calls=[],values={grow:{value:0},'grow-value':{},opacity:{value:45},status:{textContent:''}};
  w.sourceInfo={path:'old.mkv',width:2160,height:3840,frames:121};w.state.anchors=[{id:'draft-99',frame:99,status:'draft'}];w.playhead=99;w.selected=0;w.updatePlayhead=()=>{};
  const viewer={frame:60,async setFrame(url,width,height,frame){calls.push({url,width,height,frame});if(url.includes('size=1280'))throw Error('Full preview timed out');this.frame=frame;},async setMask(){},getSelection:()=>({hasMask:false}),setGrow(){},setOpacity(){}};
  const editor=Object.assign(Object.create(PaintoutEditor.prototype),{w,active:true,stage:'clean',sequence:0,maskEditVersion:0,viewer,
    selected(){return w.state.anchors[w.selected];},maskSegment:()=>null,async flushManual(){},updateControls(){},async authoritativePreview(){},$(id){return values[id];}});w.editor=editor;
  assert.equal(await editor.frameChanged(true),true);assert.equal(calls.length,2);assert.match(calls[1].url,/size=512/);assert.deepEqual(calls.map(call=>[call.width,call.height,call.frame]),[[2160,3840,99],[2160,3840,99]],'Display fallback never changes source-space paint coordinates');assert.match(values.status.textContent,/smaller display preview/);
  viewer.setFrame=async()=>{throw Error('Frame decode failed');};editor.frameKey=null;editor.sequence=0;editor.active=true;viewer.frame=60;w.playhead=99;w.selected=0;
  assert.equal(await editor.frameChanged(true),false);assert.equal(w.playhead,60);assert.equal(w.selected,-1);assert.equal(w.state.anchors.length,1,'The new draft is retained for retry');assert.equal(w.view,'source','A failed frame load returns to the shot instead of a black editor');assert.match(values.status.textContent,/select it again to retry/);
}
console.log('Paintout preview ownership: late image failures, colour/source changes, verified same-path rebind, close races and successful Mask loading preserve current diagnostics.');

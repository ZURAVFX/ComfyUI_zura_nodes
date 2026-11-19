import assert from 'node:assert/strict';
import {PaintoutEditor} from '../web/paintout_studio/paintout_editor.js';

function fixture(action='paint'){
 const requests=[],messages=[],e=Object.create(PaintoutEditor.prototype);
 const existing={id:'previous',frame:3,file:'previous.exr',layers:[{id:'paint',file:'paint.exr',opacity:.45,enabled:false}],versions:[{file:'old.exr'}],editMask:'original-mask',editGrow:4};
 const w={state:{source:'original.mov',clipTrimConfirmed:true,startFrame:2,frameCount:12,sourceColour:'srgb_display',anchors:[existing],maskGrow:0,maskRevision:null},playhead:7,selected:-1,sourceInfo:{width:2160,height:3840},plate:{action},modelInfo:{},modelsReady:false,
  busy:()=>!!e.importing,render(){},save(){},pick:async()=>['external-edit.jpg'],fetch:async(path,body)=>{requests.push({path,body});if(path.endsWith('/import-local-frame'))return {frame:7,file:'owned-edit.jpg',colour_space:'srgb_display',width:2160,height:3840};if(path.endsWith('/review-import'))return {token:'review',changed_pixels:20};throw Error(path);}};
 Object.assign(e,{w,candidate:null,active:false,importing:false,project:'project',status:value=>messages.push(value),updateControls(){},flushManual:async()=>{},ensureProject:async()=>{},viewer:{getSelection:()=>({mask:'selected-source-mask'})},
  selected:()=>w.state.anchors[w.selected],selectFrame:async index=>{w.selected=index;e.stage='clean';},createFrame:async frame=>{w.state.anchors.push({id:'created',frame,file:'',layers:[],versions:[],status:'draft'});w.selected=w.state.anchors.length-1;e.stage='clean';}});
 return {e,w,existing,requests,messages};
}
for(const action of ['paint','remove','replace']){
 const {e,w,existing,requests}=fixture(action),before=structuredClone(existing);
 await e.importFrame({atPlayhead:true});
 assert.equal(w.state.anchors.length,2);assert.equal(e.selected().frame,7,'The filename cannot choose the destination frame');assert.equal(e.candidate.method,'manual');
 assert.equal(requests[0].body.frame,7);assert.equal(requests[0].body.source,'original.mov');assert.equal(requests[0].body.colour_space,'srgb_display');
 assert.equal(requests[1].body.mask,'selected-source-mask');assert.equal(requests[1].body.frame,7);assert.deepEqual(existing,before,'Existing guide opacity, visibility, masks and saved versions are preserved');assert.equal(w.modelsReady,false,'Manual import does not require a ready model');
}
{
 const {e,w,existing}=fixture();w.playhead=3;w.selected=0;w.fetch=async(path,body)=>path.endsWith('/import-local-frame')?{frame:3,file:'replacement.jpg',colour_space:'srgb_display',width:2160,height:3840}:{token:'review'};
 await e.importFrame({atPlayhead:true});assert.equal(w.state.anchors.length,1);assert.equal(e.selected(),existing);assert.equal(existing.file,'previous.exr','Import waits for review before replacing an accepted guide');assert.equal(existing.layers[0].opacity,.45);assert.deepEqual(existing.versions,[{file:'old.exr'}]);assert.equal(e.candidate.file,'replacement.jpg');
}
for(const change of ['cancel','source','frame','mode','range','bad-size','reject']){
 const {e,w,requests,messages}=fixture(),before=structuredClone(w.state.anchors);
 if(change==='cancel')w.pick=async()=>[];
 else if(['source','frame','mode','range'].includes(change))w.pick=async()=>{if(change==='source')w.state.source='different.mov';if(change==='frame')w.playhead=8;if(change==='mode')w.plate.action='remove';if(change==='range')w.state.frameCount=3;return ['edited.jpg'];};
 else w.fetch=async()=>{if(change==='reject')throw Error('Edited frame dimensions must match the original source exactly.');return {frame:7,file:'wrong.jpg',width:2176,height:3840,colour_space:'srgb_display'};};
 await e.importFrame({atPlayhead:true});assert.deepEqual(w.state.anchors,before,change+' never creates or alters a guide');assert.equal(e.candidate,null);if(change==='cancel')assert.equal(messages.length,0);if(['cancel','source','frame','mode','range'].includes(change))assert.equal(requests.length,0);
}
{
 const {e,w}=fixture();let release;w.fetch=async()=>new Promise(resolve=>release=resolve);const pending=e.importFrame({atPlayhead:true});for(let i=0;i<4;i++)await Promise.resolve();w.state.source='new.mov';release({frame:7,file:'late.jpg',width:2160,height:3840,colour_space:'srgb_display'});await pending;assert.equal(w.state.anchors.length,1);assert.equal(e.candidate,null,'A late validated upload cannot bind to a new shot');
}
{
 const {e,w}=fixture();let release,picks=0;w.pick=async()=>{picks++;return new Promise(resolve=>release=resolve);};const first=e.importFrame({atPlayhead:true});await e.importFrame({atPlayhead:true});assert.equal(picks,1,'Only one native file picker may be open');release([]);await first;assert.equal(e.importing,false);assert.equal(w.state.anchors.length,1);
}
for(const phase of ['review','accept'])for(const change of ['source','mode','range','project']){
 const {e,w,existing}=fixture();w.playhead=3;w.selected=0;let release;
 const before=structuredClone(existing);w.fetch=async()=>new Promise(resolve=>release=resolve);
 if(phase==='accept'){e.candidate={review:{token:'owned-review'},anchor:existing.id,file:'pending.jpg'};e.loadDocument=async()=>{};e.revision=3;e.ensureLayers=()=>[];e.addPaintLayer=()=>{throw Error('A stale acceptance must not add a layer');};}
 const pending=phase==='review'?e.reviewImportedFrame({file:'pending.jpg',colour_space:'srgb_display'},existing):e.acceptImported('include');
 for(let i=0;i<3;i++)await Promise.resolve();if(change==='source')w.state.source='different.mov';if(change==='mode')w.plate.action='remove';if(change==='range')w.state.frameCount=5;if(change==='project')e.project='different-project';release(phase==='review'?{token:'late-review'}:{file:'late-accepted.exr',mask:'late-mask',colour_space:'srgb_display'});
 if(phase==='review')await assert.rejects(pending,/changed/);else await pending;
 assert.deepEqual(existing,before,'A late '+phase+' response cannot change the previous guide after '+change+' changes');
}
console.log('Manual edited-frame import: all three operations, original raster/current frame, no AI requirement, preserved layers/versions, cancel and stale-source/mode/range protection pass.');

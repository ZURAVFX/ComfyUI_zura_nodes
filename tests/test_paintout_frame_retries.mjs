import assert from 'node:assert/strict';
import {PaintoutEditor,paintoutDraft} from '../web/paintout_studio/paintout_editor.js';
import {FRAME_EDIT_MODELS} from '../web/paintout_studio/paintout_frame_recipes.js';

// Exercise the real submit/result/version controller without running a model.
const info={};
for(const type of ['ZuraPaintoutFrameCrop','ZuraPaintoutFrameComposite','UNETLoader','CLIPLoader','VAELoader','CLIPTextEncode','ReferenceMultiLatent','KSampler','VAEDecode','TextGenerate','ModelSamplingFlux','ConditioningZeroOut','BatchImagesNode','ResizeAndPadImage'])info[type]={input:{required:{},optional:{}}};
info.ZuraPaintoutFrameCrop.input.optional.base_file=['STRING',{}];
info.UNETLoader.input.required.unet_name=[[FRAME_EDIT_MODELS.model]];
info.CLIPLoader.input.required.clip_name=[[FRAME_EDIT_MODELS.text,FRAME_EDIT_MODELS.upsampler]];
info.CLIPLoader.input.required.type=[['flux3']];
info.VAELoader.input.required.vae_name=[[FRAME_EDIT_MODELS.vae]];
let selection={hasMask:true,mask:'painted-people',positive:[],negative:[]},completedFrame,queued;
const anchor={id:'guide-50',frame:50,file:'',layers:[],editMask:selection.mask,editGrow:8,versions:[]};
const state={source:'shot.mp4',sourceColour:'srgb_display',seed:42,mode:'targeted',anchors:[anchor],mask:'shot-mask.mp4',maskRevision:7};
const controls=new Map();
const editor=Object.assign(Object.create(PaintoutEditor.prototype),{
  stage:'clean',candidate:null,selected:()=>state.anchors[0],
  $(key){if(!controls.has(key))controls.set(key,{value:key==='instruction'?'Remove the people and their shadows':key==='grow'?8:''});return controls.get(key);},
  viewer:{frame:50,getSelection:()=>selection,clear(){selection={...selection,hasMask:false,mask:'empty-mask'};},setGrow(){},setTool(){},setOpacity(){}},
  updateControls(){},frameChanged:async()=>{},status(message){this.message=message;},fullFrameMask:()=> 'whole-frame',
  async queue(graph,kind,id,details){queued={graph,kind,id,details};this.toolJob={id:'job',source:state.source,anchor:id,...details};state.editorJob=this.toolJob;},
  w:{state,playhead:50,modelInfo:info,busy:()=>false,save(){},changed(){},render(){},syncAnchorControls(){},
    async fetch(path){assert.equal(path,'/history/job');return {job:{status:{completed:true},outputs:{save:{zura_frame:[completedFrame]}}}};}}
});
async function finish(file){completedFrame={file,png_file:file+'.png',colour_space:'srgb_display',layer_mask:'effective-mask'};await editor.poll();assert.equal(editor.toolJob,null);}

await editor.cleanFrame();
assert.equal(queued.graph.frame_crop.inputs.mask,'painted-people');
assert.equal(queued.graph.frame_crop.inputs.base_file,undefined);
assert.equal(queued.graph.frame_sample.inputs.seed,42);
await finish('attempt-1.exr');
assert.equal(anchor.editMask,'painted-people','Successful cleanup retains the editable mask');
assert.equal(anchor.layers.length,1);
assert.equal(anchor.editSeed,43);
assert.equal(anchor.versions.length,1);
assert.match(editor.message,/Try again/);

await editor.cleanFrame();
assert.equal(queued.graph.frame_crop.inputs.base_file,undefined,'Retry uses the original, not attempt 1');
assert.equal(queued.graph.frame_sample.inputs.seed,43,'Retry varies the seed');
await finish('attempt-2.exr');
assert.equal(anchor.layers.length,1,'Alternative attempts do not accumulate as paint layers');
assert.equal(anchor.layers[0].file,'attempt-2.exr');
assert.deepEqual(anchor.versions.map(v=>v.file),['attempt-1.exr','attempt-2.exr']);
await editor.selectVersion('attempt-1.exr');
assert.equal(anchor.file,'attempt-1.exr');
assert.equal(anchor.layers[0].file,anchor.file,'Selecting an alternative restores its matching layer stack');
assert.equal(anchor.cleanAttempt.base_file,'');
await editor.cleanFrame();await finish('attempt-3.exr');
assert.equal(anchor.layers.length,1);
assert.equal(anchor.versions.length,3);

// New repair starts on the chosen plate; its retries keep that base frozen.
editor.newPaintArea();
assert.equal(anchor.file,'attempt-3.exr');assert.equal(anchor.cleanAttempt,undefined);
const before=queued;
await editor.cleanFrame();assert.equal(queued,before,'An empty selection is rejected before queueing');
assert.match(editor.message,/Paint the area/);
selection={...selection,hasMask:true,mask:'second-area'};anchor.editMask=selection.mask;
await editor.cleanFrame();
assert.equal(queued.graph.frame_crop.inputs.base_file,'attempt-3.exr');
await finish('repair-2-try-1.exr');
assert.equal(anchor.layers.length,2);
await editor.cleanFrame();
assert.equal(queued.graph.frame_crop.inputs.base_file,'attempt-3.exr');
await finish('repair-2-try-2.exr');
assert.equal(anchor.layers.length,2);
assert.equal(anchor.layers[0].file,'attempt-3.exr');
assert.equal(anchor.layers[1].file,'repair-2-try-2.exr');

// Persistence and choosing an earlier result retain the right base, mask and layers.
state.anchors[0]=JSON.parse(JSON.stringify(anchor));
selection={...selection,mask:state.anchors[0].editMask};
await editor.cleanFrame();assert.equal(queued.graph.frame_crop.inputs.base_file,'attempt-3.exr');
await finish('reopened-try.exr');
await editor.selectVersion('attempt-2.exr');
assert.equal(state.anchors[0].layers.length,1);
assert.equal(state.anchors[0].editMask,'painted-people');
assert.equal(state.anchors[0].cleanAttempt.base_file,'');
assert.equal(state.mask,'shot-mask.mp4');assert.equal(state.maskRevision,7,'Guide attempts never change the shot mask');

// Imported edits save only their fully composed plate, not an intermediate patch.
const current=state.anchors[0];
editor.addPaintLayer(current,{file:'import-patch.exr',layer_mask:'import-mask',colour_space:'srgb_display',method:'manual'},null,false);
current.file='composed-import.exr';editor.saveFrameVersion(current);
assert.ok(!current.versions.some(v=>v.file==='import-patch.exr'));
assert.equal(current.versions.at(-1).layers.length,2);
const legacy={frame:50,file:'old-attempt.exr',editMask:'old-blank-mask',layers:[{file:'old-attempt.exr',method:'flux3',layer_mask:'saved-selection'}],versions:[]};
assert.equal(editor.recoverFrameRetry(legacy,false),true,'Old drafts recover the erased selection');
assert.equal(legacy.editMask,'saved-selection');assert.equal(legacy.cleanAttempt.base_file,'');
legacy.editMask='explicitly-cleared';assert.equal(editor.recoverFrameRetry(legacy,false),false,'Explicit new-area selections never resurrect');
for(const mode of ['inpaint','ripple']){
  const draft=paintoutDraft({...state,mode},{paintoutOnly:true});
  assert.equal(draft.mode,'targeted');assert.equal(draft.source,state.source);assert.equal(draft.mask,state.mask);assert.deepEqual(draft.anchors,state.anchors);
  assert.equal(paintoutDraft({mode}).mode,mode,'Dedicated legacy editors retain their own explicit mode');
}
console.log('Paintout retries, result selection, new areas, persistence and import snapshots passed');

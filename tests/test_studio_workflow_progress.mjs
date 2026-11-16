import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {workflowProgress,StudioWorkflowProgress} from '../web/studio_workflow_progress.js';

assert.equal(workflowProgress({mode:'home'}),null);
assert.equal(workflowProgress({mode:'video'}),null,'Native video keeps its existing progress flow');
assert.equal(workflowProgress({mode:'image',imageOperation:'create'}),null,'Single-stage image creation stays uncluttered');
const p={mode:'paintout',plate:{action:'remove'},paintout:{state:{source:'shot.mp4',clipTrimConfirmed:false,anchors:[]},editor:{stage:'trim'}}};
assert.deepEqual(workflowProgress(p).labels,['Source','Trim clip','Mask','Clean frames','Video','Result']);
assert.equal(workflowProgress(p).active,1,'Unconfirmed clip trim highlights the Trim clip step');
p.paintout.state.clipTrimConfirmed=true;p.paintout.editor.stage='mask';
assert.equal(workflowProgress(p).active,2);p.paintout.editor.stage='clean';assert.equal(workflowProgress(p).active,3);
p.paintout.editor.stage='render';assert.equal(workflowProgress(p).active,4);
p.paintout.result={file:'done.mp4'};assert.equal(workflowProgress(p).active,5);
p.paintout.job={id:'next'};assert.equal(workflowProgress(p).active,4,'A running job takes priority over the previous result');delete p.paintout.job;
p.plate.action='paint';p.paintout.result=null;p.paintout.state.anchors=[{file:'edit.png'}];
assert.deepEqual(workflowProgress(p).labels,['Source','Trim clip','Paint frame','Video','Result']);
assert.equal(workflowProgress(p).active,3);
p.mode='image';p.rippleImage={request:{workspace:{platePrimary:true}}};assert.equal(workflowProgress(p).active,2,'A borrowed image editor stays within its video workflow');
const relight={mode:'ripple',ripple:{intent:'relight',source:{path:'clip'},ltxReference:()=>({file:'light.png'})}};
assert.deepEqual(workflowProgress(relight).labels,['Source','Lighting frame','Video','Result']);assert.equal(workflowProgress(relight).active,2);
for(const [mode,workspace,active]of [
 ['panorama',{state:{source:{id:'clip'},cameraReviewed:true}},2],
 ['outpaint',{source:{},result:{tagName:'VIDEO'}},1],
 ['alpha',{source:{},job:{id:'extract'}},2],
 ['paint_vfx',{state:{frames:9,keys:[{frame:0,painted:true,image:{file:'first.png'}},{frame:8,painted:true,image:{file:'last.png'}}]}},1],
 ['frames',{assets:{first:{},last:{}}},1],
 ['references',{assets:{images:[{}]}},1],
 ['director',{job:{id:'render'}},1],
 ['watermark',{state:{source:'clip'},result:{file:'done'}},3],
]){
 const key={panorama:'panorama',references:'referencesVideo'}[mode]||mode;
 const view=workflowProgress({mode,[key]:workspace});assert(view,mode);assert.equal(view.active,active,mode);
}
assert.equal(workflowProgress({mode:'hdr',studio:{hdrTool:{sourceInfo:{frames:17},outputRef:{file:'INPUT.mp4'}}}}).active,1,'An HDR input file is not a finished output');
assert.equal(workflowProgress({mode:'hdr',studio:{hdrTool:{sourceInfo:{frames:17},completedResult:{files:[{}]}}}}).active,3);
const hdr={mode:'ripple',ripple:{intent:'relight',source:{},result:{file:'SDR.mp4'}},outputSettings:{delivery:{output:'hdr',activeMode:'relight',delivery:{busy:true}}}};
assert.deepEqual(workflowProgress(hdr).labels,['Source','Lighting frame','Video','Convert HDR','Result']);assert.equal(workflowProgress(hdr).active,3);
hdr.outputSettings.delivery.delivery.busy=false;hdr.outputSettings.delivery.recordFor=()=>({state:'complete'});assert.equal(workflowProgress(hdr).active,4);

const {document}=parseHTML('<html><head></head><body><main><header class="gs-top"></header></main></body></html>');
let closed=0;const owner={mode:'ripple',root:document.querySelector('main'),ripple:relight.ripple,close(){closed++;}};
const progress=new StudioWorkflowProgress(owner);
assert.equal(progress.nav.querySelector('[aria-current=step] .zc-workflow-label').textContent,'Video');
owner.ripple.result={file:'done.mp4'};progress.sync();assert.equal(progress.nav.querySelector('[aria-current=step] .zc-workflow-label').textContent,'Result');
assert.equal(progress.nav.querySelectorAll('.complete').length,3);
owner.mode='image';owner.imageOperation='create';progress.sync();assert.equal(progress.nav.hidden,true);
progress.close();owner.close();assert.equal(closed,1);assert.equal(progress.nav.isConnected,false);
console.log('Shared workflow stages: real-state progression, borrowed editors, HDR delivery, all workspaces and cleanup pass.');

assert.equal(workflowProgress({mode:'paint_vfx',paint_vfx:{state:{frames:9,keys:[{frame:0,painted:true,image:{file:'first.png'}}]}}}).active,0,'One painted endpoint is still the paint step');
assert.equal(workflowProgress({mode:'frames',frames:{assets:{first:{file:'first.png'}}}}).active,1,'The optional last frame must not block Settings');

assert.equal(workflowProgress({mode:'references',referencesVideo:{assets:{audios:[{file:'voice.wav'}]}}}).active,1,'Audio-only references advance to settings');
assert.equal(workflowProgress({mode:'director',director:{resultView:false,selectedResult:{file:'old.mov'}}}).active,0,'Timeline editing is not the result step');

const stages=[],navigationOwner={mode:'paintout',plate:{action:'remove',surface:{navigateStage(label){stages.push(label);}}},paintout:{state:{source:'clip',clipTrimConfirmed:true,mask:'mask.mov',anchors:[{file:'clean.png'}]},editor:{stage:'clean'},busy:()=>false}};
const navRoot=document.createElement('main');document.body.append(navRoot);navigationOwner.root=navRoot;
const interactive=new StudioWorkflowProgress(navigationOwner);
const maskStep=[...interactive.nav.querySelectorAll('button')].find(button=>button.textContent.includes('Mask'));
maskStep.click();assert.deepEqual(stages,['Mask'],'Top steps navigate through the existing controller without generating');
assert.equal(interactive.nav.querySelector('button[aria-label=Video]').disabled,false,'Reviewed clean frames permit video review');
navigationOwner.paintout.busy=()=>true;interactive.sync();assert([...interactive.nav.querySelectorAll('button')].every(button=>button.disabled),'No stage switching during a running operation');interactive.close();

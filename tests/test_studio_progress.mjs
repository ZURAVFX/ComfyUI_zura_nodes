import assert from 'node:assert/strict';
import {stageProgress,durationLabel} from '../web/studio_progress.js';
assert.equal(durationLabel(61),'1m 1s');
assert.equal(durationLabel(0),'0s');
assert.deepEqual(stageProgress({state:'queued',queue_position:2,stage_percent:40}),{
  title:'Preparing your shot',detail:'Queue position 2',percent:null,meta:''});
assert.equal(stageProgress({stage_percent:null}).percent,null);
assert.equal(stageProgress({stage_percent:NaN}).percent,null);
assert.equal(stageProgress({stage_percent:150}).percent,100);
assert.equal(stageProgress({stage_remaining_seconds:90,eta_confidence:'estimating'}).detail,'Loading and preparing…');
const measured=stageProgress({stage_label:'Sampling video',stage_percent:25,stage_elapsed_seconds:30,stage_remaining_seconds:90,eta_confidence:'measured',step:2,total_steps:8});
assert.equal(measured.detail,'About 1m 30s left in this step');
assert.equal(measured.meta,'Step 2 of 8 · 30s elapsed');
assert.equal(stageProgress({state:'complete'}).detail,'Stage complete');
assert.equal(stageProgress(null,{state:'waiting'}).detail,'Switching models…');
const oldSampler={action_id:'image',action_stage:'design',state:'running',stage_label:'Sampling image',stage_percent:80,step:8,total_steps:10,stage_remaining_seconds:12,eta_confidence:'measured'};
const handoff=stageProgress(oldSampler,{state:'running',actionId:'video',stage:'h3',label:'Generating video · MiniMax H3'});
assert.deepEqual(handoff,{title:'Generating video · MiniMax H3',detail:'Loading and preparing…',percent:null,meta:''});
for(const state of ['preparing','queued']){
  const loading=stageProgress({...oldSampler,state,stage_label:'Loading inputs'},{label:'Creating your starting frame'});
  assert.equal(loading.percent,null);
  assert.doesNotMatch(loading.detail,/left|Sampling/);
  assert.doesNotMatch(loading.meta,/Step/);
}
const preparing=stageProgress({state:'preparing',stage_label:'Loading',stage_elapsed_seconds:24},{label:'Generating video · Wan 2.2'});
assert.equal(preparing.title,'Generating video · Wan 2.2');
assert.equal(preparing.detail,'Loading');
assert.equal(preparing.meta,'24s elapsed');
assert.equal(stageProgress({...oldSampler},{state:'queued'}).percent,null,'Queue transition overrides stale native sampling');
console.log('Studio progress shows actual stage percent, honest unknown states and measured stage ETA.');

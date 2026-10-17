import assert from 'node:assert/strict';
import {stageProgress,durationLabel} from '../web/studio_progress.js';
assert.equal(durationLabel(61),'1m 1s');
assert.equal(durationLabel(0),'0s');
assert.deepEqual(stageProgress({state:'queued',queue_position:2,stage_percent:40}),{
  title:'Preparing your shot',detail:'Queue position 2',percent:null,meta:''});
assert.equal(stageProgress({stage_percent:null}).percent,null);
assert.equal(stageProgress({stage_percent:NaN}).percent,null);
assert.equal(stageProgress({stage_percent:150}).percent,100);
assert.equal(stageProgress({stage_remaining_seconds:90,eta_confidence:'estimating'}).detail,'Estimating time for this stage…');
const measured=stageProgress({stage_label:'Sampling video',stage_percent:25,stage_elapsed_seconds:30,stage_remaining_seconds:90,eta_confidence:'measured',step:2,total_steps:8});
assert.equal(measured.detail,'About 1m 30s left in this stage');
assert.equal(measured.meta,'Step 2 of 8 · 30s elapsed');
assert.equal(stageProgress({state:'complete'}).detail,'Stage complete');
assert.equal(stageProgress(null,{state:'waiting'}).detail,'Waiting for the previous model to unload');
console.log('Studio progress shows actual stage percent, honest unknown states and measured stage ETA.');

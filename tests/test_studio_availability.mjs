import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'').split('app.registerExtension({')[0];
assert.ok(source.includes('<option value="restyle">LTX character animation</option>'),'The restored native LTX stage exists in the real selector');
const context={};vm.createContext(context);vm.runInContext(source+'\nthis.Studio=ArtistStudio;this.allowed=verifiedSetup;this.initial=defaults;',context);
assert.equal(context.initial.engine,'wan');assert.equal(context.initial.workflow_mode,'swap');assert.equal(context.initial.subject_mode,'people');
const good={...context.initial};assert.equal(context.allowed(good),true);
for(const changes of [{engine:'local'},{engine:'seedance'},{workflow_mode:'viewport'},{workflow_mode:'motion'},{workflow_mode:'relight'},{mask_method:'points'},{refine_lips:true}]){
  const ui=Object.create(context.Studio.prototype);ui.config={...good,...changes};
  const original=JSON.stringify(ui.config);let queued=false;
  ui.message=text=>{ui.notice=text;};ui.primaryRecipe=async()=>{queued=true;};
  await ui.primary();assert.equal(queued,false);assert.match(ui.notice,/Choose Character performance/);assert.equal(JSON.stringify(ui.config),original);
}
const field=()=>({hidden:false,disabled:false,textContent:'',closest(){return this.label??={hidden:false};}});
const modes=['motion','swap','viewport','relight'].map(value=>({...field(),value}));
const engines=['local','h3','wan','seedance'].map(value=>({...field(),value}));
const fields=new Map();const ui=Object.create(context.Studio.prototype);
ui.$=id=>fields.get(id)||(fields.set(id,field()),fields.get(id));
const stages=['auto','prepare','design','animate','wan_speech','h3','h3_enhance','background','restyle','wan21_relight','draft','final'].map(value=>({...field(),value}));
Object.assign(ui.$('graph-stage'),{options:stages,selectedOptions:[stages[0]],querySelector:selector=>stages.find(stage=>selector.includes(stage.value))||null});
Object.assign(ui,{config:good,container:{querySelectorAll:selector=>selector.includes('gs-workflow')?modes:engines,querySelector:selector=>selector===".gs-look-choice"?ui.lookChoice??={hidden:false}:null}});
ui.applyVerifiedSurface();
assert.deepEqual(modes.filter(m=>!m.label.hidden).map(m=>m.value),['swap','viewport','relight']);
assert.deepEqual(engines.filter(m=>!m.label.hidden).map(m=>m.value),['local','h3','wan']);
assert.ok(engines.find(m=>m.value==='seedance').disabled);
assert.ok(stages.filter(s=>['h3','h3_enhance','draft','final'].includes(s.value)).every(s=>s.hidden&&s.disabled));
assert.ok(stages.find(s=>s.value==='wan21_relight').disabled,'Wan relight graph stays unavailable outside relight mode');
for (const engine of ['h3']) {
  ui.config={...good,engine,workflow_mode:'viewport',edit_area:'scene',audio_id:'',lip_sync:false};
  assert.equal(context.allowed(ui.config),true);
  ui.applyVerifiedSurface();
  assert.deepEqual(engines.filter(m=>!m.label.hidden).map(m=>m.value),['h3']);
  assert.equal(ui.$('audio-settings').hidden,true);
  assert.equal(stages.find(s=>s.value==='h3').disabled,engine!=='h3');
  let queued=false;ui.primaryRecipe=async()=>{queued=true;};
  await ui.primary();assert.equal(queued,true);
  assert.equal(context.allowed({...ui.config,edit_area:'mask'}),false);
}
for(const engine of ['wan','h3','local'])for(const audio of [{audio_id:'',lip_sync:false},{audio_id:'voice',lip_sync:true}]){
  ui.config={...good,engine,workflow_mode:engine==='local'?'motion':'swap',edit_area:engine==='local'?'scene':'mask',...audio};
  assert.equal(context.allowed(ui.config),true);
  ui.applyVerifiedSurface();assert.equal(ui.$('audio-settings').hidden,false);
  assert.deepEqual(engines.filter(m=>!m.label.hidden).map(m=>m.value),['local','h3','wan']);
  const stage=engine==='local'?'restyle':engine==='h3'?'h3':'wan_speech';
  assert.equal(stages.find(s=>s.value===stage).hidden,false);
  let queued=false;ui.primaryRecipe=async()=>{queued=true;};await ui.primary();assert.equal(queued,true);
}
console.log('Approved character/audio routes restored across three models; rejected viewport and masked LTX stay blocked.');

const fresh=Object.create(context.Studio.prototype);
fresh.config={...good,workflow_mode:'viewport'};fresh.modelStatus={h3_attention_backends:{kitchen:true}};fresh.useGeneratedLook=()=>{};
fresh.selectWorkflow();assert.equal(fresh.config.h3_attention,'kitchen');assert.equal(fresh.config.engine,'h3');
assert.equal(fresh.config.h3_viewport_direct,true);assert.equal(fresh.config.audio_id,'');

assert.equal(context.allowed({...good,engine:'local',workflow_mode:'viewport',edit_area:'scene'}),false,'LTX stays a private development route until its keyframes qualify');
assert.equal(context.allowed({...good,engine:'h3',workflow_mode:'motion',edit_area:'scene'}),false,'Do not substitute unapproved H3 whole-scene character pipeline');
for(const engine of ['wan','h3','local']){
  fresh.config={...good,engine,workflow_mode:'swap',audio_id:'voice',lip_sync:true};fresh.selectWorkflow();
  assert.equal(fresh.config.engine,engine);assert.equal(fresh.config.workflow_mode,engine==='local'?'motion':'swap');
  assert.equal(fresh.config.edit_area,engine==='local'?'scene':'mask');assert.equal(fresh.config.audio_id,'voice');assert.equal(fresh.config.lip_sync,true);
}
ui.config={...good,engine:'h3',delivery_mode:'enhanced1080'};ui.project={h3_enhancement_ready:false};ui.applyVerifiedSurface();
assert.equal(stages.find(s=>s.value==='h3_enhance').disabled,true,'No enhancement graph before its generated base is ready');
ui.project.h3_enhancement_ready=true;ui.applyVerifiedSurface();assert.equal(stages.find(s=>s.value==='h3_enhance').disabled,false);
ui.config={...good};ui.applyVerifiedSurface();assert.equal(stages.find(s=>s.value==='wan_speech').disabled,true);
ui.config.audio_id='voice';ui.config.lip_sync=true;ui.applyVerifiedSurface();assert.equal(stages.find(s=>s.value==='wan_speech').disabled,false);

assert.equal(context.allowed({...good,engine:'h3',workflow_mode:'relight',edit_area:'scene'}),true);
assert.equal(context.allowed({...good,engine:'h3',workflow_mode:'relight',edit_area:'scene',audio_id:'voice'}),false);
fresh.config={...good,workflow_mode:'relight',h3_head_swap:true,audio_id:'old',lip_sync:true,h3_viewport_direct:true};fresh.selectWorkflow();
assert.equal(context.allowed(fresh.config),true);assert.equal(fresh.config.h3_viewport_direct,false);

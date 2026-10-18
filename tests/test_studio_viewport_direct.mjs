import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {clipLength,recoverClipLength} from '../web/studio_length.js';
const code=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').split('app.registerExtension({')[0];
let response;
const context={clipLength,recoverClipLength,localStorage:{setItem(){},removeItem(){}},api:{fetchApi:async()=>({ok:true,json:async()=>response})}};
vm.createContext(context);vm.runInContext(code+'\nthis.Studio=ArtistStudio;',context);
function ui(phase='review'){
  const value=Object.create(context.Studio.prototype);
  Object.assign(value,{config:{workflow_mode:'viewport',engine:'h3',h3_viewport_direct:true,length_mode:'custom',duration:2,start:0},lookMode:'build',references:[{id:'ref'}],source:{id:'source',duration:15},resetEpoch:0,busy:false,project:{id:'project',phase,review:'review',prepared_key:'approved',approval:phase==='review'?null:'approved'},$:()=>({value:'original'}),readConfig(){return this.config;},perform:fn=>fn(0),syncForm(){},render(){}});
  response=value.project;return value;
}
for(const phase of ['review','approved']){
  const value=ui(phase),actions=[];value.run=async stage=>actions.push(stage);
  await value.primaryRecipe();
  assert.deepEqual(actions,phase==='review'?['approve','h3']:['h3']);
  assert.equal(value.projectBody().look_mode,'build');assert.equal(value.projectBody().config.h3_viewport_direct,true);
}
const value=ui();value.config.h3_viewport_direct=false;value.selectWorkflow();
assert.equal(value.directViewport(),true,'Entering viewport recommends the proven direct route');
value.config.workflow_mode='relight';assert.equal(value.directViewport(),false);
value.config.workflow_mode='viewport';value.lookMode='ready';assert.equal(value.directViewport(),false,'An explicit finished frame retains its own path');
value.lookMode='build';value.config.h3_viewport_direct=false;assert.equal(value.directViewport(),false,'Restored explicit build choices remain build choices');
console.log('Direct viewport approves reviewed motion and renders H3 without generating or approving a dummy opening.');

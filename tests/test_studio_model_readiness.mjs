import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const code=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8')
  .replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'').split('app.registerExtension({')[0];
const context={};vm.createContext(context);
vm.runInContext(code+'\nthis.Studio=ArtistStudio;',context);
function check(config,status){
  const fields=Object.fromEntries(['models','model-checklist'].map(name=>[name,{classList:{toggle(){}}}]));
  const ui=Object.create(context.Studio.prototype);
  Object.assign(ui,{config,modelStatus:status,$:name=>fields[name]});
  ui.updateModelStatus();return fields;
}
const status={ready:true,engine_ready:{local_scene:true,local_viewport:false,h3:false,h3_viewport:true},
  model_files:{local_scene:[{ready:true,path:'union-control'}],local_viewport:[{ready:false,path:'layout-to-render'}],
    h3:[{ready:true,path:'fun-control'}],h3_viewport:[{ready:true,path:'h3-video-reference'}]},
  missing_ltx_scene_nodes:[],missing_ltx_viewport_nodes:['LTXVAddGuide'],
  missing_h3_nodes:['DepthAnythingV2Preprocessor'],missing_h3_viewport_nodes:[]};
let result=check({engine:'local',workflow_mode:'viewport',edit_area:'scene'},status);
assert.equal(result.models.textContent,'Model setup needs attention');
assert.match(result['model-checklist'].innerHTML,/Missing: <code>layout-to-render/);
assert.match(result['model-checklist'].innerHTML,/LTXVAddGuide/);
assert.doesNotMatch(result['model-checklist'].innerHTML,/union-control/);
result=check({engine:'local',workflow_mode:'motion',edit_area:'scene'},status);
assert.match(result.models.textContent,/whole-scene models ready/);
result=check({engine:'h3',workflow_mode:'viewport',edit_area:'scene'},status);
assert.match(result.models.textContent,/ready/);
assert.match(result['model-checklist'].innerHTML,/h3-video-reference/);
assert.doesNotMatch(result['model-checklist'].innerHTML,/DepthAnything|fun-control/);
result=check({engine:'h3',workflow_mode:'relight',edit_area:'scene'},status);
assert.equal(result.models.textContent,'Model setup needs attention');
assert.match(result['model-checklist'].innerHTML,/DepthAnythingV2Preprocessor/);
result=check({engine:'local',workflow_mode:'viewport',edit_area:'scene'},{ready:true,engine_ready:{local_scene:true}});
assert.equal(result.models.textContent,'Model setup needs attention','Legacy scene readiness must not mark an unknown viewport route ready');
console.log('Studio selects the actual model and native-node requirements for each viewport and regular route.');

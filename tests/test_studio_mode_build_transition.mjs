import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {clipLength,recoverClipLength} from '../web/studio_length.js';
const code=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').split('app.registerExtension({')[0];
const calls=[],removed=[];
const context={clipLength,recoverClipLength,localStorage:{setItem(){},removeItem:key=>removed.push(key)},api:{fetchApi:async(path,options)=>{
  const body=JSON.parse(options.body);calls.push({path,body});return {ok:true,json:async()=>({id:'new-build-project',phase:'new',look_mode:body.look_mode,config:body.config})};
}}};
vm.createContext(context);vm.runInContext(code+'\nthis.Studio=ArtistStudio;',context);
for(const scenario of ['relight','preserve']){
  calls.length=0;removed.length=0;
  const ui=Object.create(context.Studio.prototype),oldProject={id:'saved-ready',phase:'opening',look_mode:'ready',opening_input:{file:'old-ready.png'}};
  const config={workflow_mode:scenario==='relight'?'relight':'motion',engine:'h3',preserve_people:scenario==='preserve',edit_area:'scene',length_mode:'custom',duration:2,start:0,prompt:'Soft evening light',image_prompt:'',quality:'fast'};
  Object.assign(ui,{project:oldProject,config,lookMode:'ready',readyAsset:{id:'ready'},character:{id:'ready'},references:[{id:'scene-ref'}],source:{id:'source',duration:3},resetEpoch:0,busy:false,$:()=>({value:'original'}),readConfig(){return this.config;},perform:fn=>fn(0),syncForm(){},render(){}});
  if(scenario==='relight')ui.selectWorkflow();else ui.syncPreservedPeople();
  assert.equal(ui.lookMode,'build');assert.equal(ui.project,null,`${scenario} must recreate an existing finished-frame project rather than save config against its stale ready mode`);
  assert.equal(oldProject.look_mode,'ready','Existing saved project and its approved image stay intact');assert.equal(oldProject.opening_input.file,'old-ready.png');
  assert.deepEqual(removed,['genj-studio-project']);
  const actions=[];ui.run=async action=>actions.push(action);
  await ui.primaryRecipe();
  assert.equal(calls[0].path,'/zura/studio/projects','Prepare creates a new project carrying the changed look mode');
  assert.equal(calls[0].body.look_mode,'build');assert.equal(calls[0].body.config.workflow_mode,config.workflow_mode);assert.equal(calls[0].body.config.preserve_people,config.preserve_people);
  assert.deepEqual(calls[0].body.references,['scene-ref']);assert.deepEqual(actions,['prepare']);
}
const running=Object.create(context.Studio.prototype);running.project={id:'active',phase:'working',look_mode:'ready'};running.lookMode='ready';
assert.equal(running.useGeneratedLook(),false);assert.equal(running.project.id,'active');assert.equal(running.lookMode,'ready','A running job is never discarded by draft normalisation');
console.log('Existing ready projects recreate with build mode for Relight and protected-people changes, retaining saved originals and active runs.');

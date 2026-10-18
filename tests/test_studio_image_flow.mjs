import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {clipLength,recoverClipLength} from '../web/studio_length.js';
const code=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').split('app.registerExtension({')[0];
const config={engine:'h3',workflow_mode:'viewport',length_mode:'custom',duration:2,start:0,quality:'fast'};
const project={id:'shot',phase:'review',review:'review',prepared_key:'review',approval:null,config};
const context={clipLength,recoverClipLength,api:{fetchApi:async()=>({ok:true,json:async()=>project})}};
vm.createContext(context);vm.runInContext(code+'\nthis.Studio=ArtistStudio;',context);
const ui=Object.create(context.Studio.prototype),actions=[];
Object.assign(ui,{source:{duration:3},references:[],project,lookMode:'build',resetEpoch:0,readConfig:()=>config,
  $:()=>({value:'original'}),perform:fn=>fn(0),syncForm(){},
  run:async stage=>{actions.push(stage);if(stage==='create_look')project.approval='review';}});
await ui.primaryRecipe();assert.deepEqual(actions,['create_look'],'H3 viewport does not skip starting image generation');
actions.length=0;project.phase='opening';project.opening_input={file:'approved.png'};
await ui.primaryRecipe();assert.deepEqual(actions,['animate'],'Artist explicitly accepts visible starting frame before animation');
assert.ok(code.includes('id="gs-image_prompt"'));assert.ok(code.includes('Regenerate starting frame'));
assert.ok(code.includes('input.id==="gs-image_prompt"'),'Image edits are submitted with Generate, preventing blur/click double-action races');
console.log('H3 viewport review → starting-frame generation → explicit animation approval passes.');

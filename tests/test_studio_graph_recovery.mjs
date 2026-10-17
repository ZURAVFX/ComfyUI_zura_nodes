import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8')
  .replace(/^import .*;\r?\n/gm,'')
  .replaceAll('await import("./vendor/elk.bundled.js");','')
  .split('app.registerExtension({')[0];
const restored=[],loaded=[],original={nodes:[{id:'my-original-node'}]};
const exported={project_id:'project',stage:'h3',graph:{render:{class_type:'Render',inputs:{}}},name:'Test'};
const context={crypto:{randomUUID:()=> 'copy'},window:{ELK:class {}},
  api:{fetchApi:async()=>({ok:true,json:async()=>exported})},
  app:{rootGraph:{serialize:()=>original},loadApiJson:async graph=>loaded.push(graph),loadGraphData:async graph=>restored.push(graph)},
  tidyArtistGraph:async()=>{throw new Error('Routing failed');},attachWanGraphControls(){},tidyWanStage(){}};
vm.createContext(context);vm.runInContext(source+'\nthis.Studio=ArtistStudio;',context);
const ui=Object.create(context.Studio.prototype);
Object.assign(ui,{project:{id:'project',phase:'working'},resetEpoch:0,readConfig:()=>({}),$:()=>({value:'animate'}),perform:fn=>fn(0),close(){this.closed=true;}});
await assert.rejects(()=>ui.graphView(),/previous workflow has been restored.*Routing failed/);
assert.equal(loaded.length,1,'Never reload the raw export as a silent fallback');
assert.equal(restored[0],original,'Recover the user workflow, including native layout');
assert.equal(ui.closed,undefined,'Keep Studio open with a recoverable error');
const importer=context.app.loadApiJson;
context.app.loadApiJson=async()=>{throw new Error('Import failed');};
await assert.rejects(()=>ui.graphView(),/previous workflow has been restored.*Import failed/);
assert.equal(restored.length,2,'Restore even if the frontend clears the graph then fails during import');
context.app.loadApiJson=importer;
context.tidyArtistGraph=async()=>({crossings:0});
await ui.graphView();
assert.equal(ui.closed,true,'Only open Graph view after successful native layout');
console.log('Graph handoff preserves the previous workflow when artist layout fails.');

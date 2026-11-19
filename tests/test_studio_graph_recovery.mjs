import {runStudioVMInContext} from './studio_vm_fixture.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createComfyGraphHost} from '../web/studio_host_adapters.js';

const source=fs.readFileSync(new URL('../web/studio_core.js',import.meta.url),'utf8')
  .replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'')
  .replaceAll('await import("./vendor/elk.bundled.js");','')
  .split('app.registerExtension({')[0];
const restored=[],loaded=[],original={nodes:[{id:'my-original-node'}]};
const exported={project_id:'project',stage:'h3',graph:{render:{class_type:'Render',inputs:{}}},name:'Test'};
const context={crypto:{randomUUID:()=> 'copy'},window:{ELK:class {}},
  api:{fetchApi:async()=>({ok:true,json:async()=>exported})},
  app:{rootGraph:{serialize:()=>original},loadApiJson:async graph=>loaded.push(graph),loadGraphData:async graph=>restored.push(graph)},
  tidyArtistGraph:async()=>{throw new Error('Routing failed');},attachWanGraphControls(){},tidyWanStage(){}};
vm.createContext(context);runStudioVMInContext(source+'\nthis.Studio=ArtistStudio;',context);
const ui=Object.create(context.Studio.prototype);
Object.assign(ui,{project:{id:'project',phase:'working'},resetEpoch:0,readConfig:()=>({}),$:()=>({value:'animate'}),perform:fn=>fn(0),request:async()=>exported,showComfyGraph(){this.graphVisible=true;},
  graph:createComfyGraphHost(context.app,{request:async()=>exported,tidy:(...args)=>context.tidyArtistGraph(...args),attach:()=>{}})});
await assert.rejects(()=>ui.graphView(),/previous workflow has been restored.*Routing failed/);
assert.equal(loaded.length,1,'Never reload the raw export as a silent fallback');
assert.equal(restored[0],original,'Recover the user workflow, including native layout');
assert.equal(ui.graphVisible,undefined,'Keep Studio open with a recoverable error');
const importer=context.app.loadApiJson;
context.app.loadApiJson=async()=>{throw new Error('Import failed');};
await assert.rejects(()=>ui.graphView(),/previous workflow has been restored.*Import failed/);
assert.equal(restored.length,2,'Restore even if the frontend clears the graph then fails during import');
context.app.loadApiJson=importer;
context.tidyArtistGraph=async()=>({crossings:0});
await ui.graphView();
assert.equal(ui.graphVisible,true,'Only open Graph view after successful native layout');
console.log('Graph handoff preserves the previous workflow when artist layout fails.');

const {inspectStudioGraph,rememberStudioGraph}=await import('../web/studio_graph_view.js');
const exactGraph={render:{class_type:'Render',inputs:{steps:8}}};
const cachedGraph={render:{class_type:'Render',inputs:{steps:99}}};
const calls=[];
const graphStudio={graph:{available:true,async openApiGraph(value){calls.push(value);}},showComfyGraph(){calls.push('return available');},message(message){calls.push(message);}};
const alpha={source:{path:'shot.mov'},job:{id:'active'},graph(){calls.push('draft');}};
const owner={studio:graphStudio,mode:'alpha',alpha,api:{async fetchApi(path){
  assert.ok(['/history/active','/queue'].includes(path));
  return {ok:true,json:async()=>path==='/queue'?{queue_running:[[0,'other',cachedGraph],[1,'active',exactGraph]]}:{}};
}}};
rememberStudioGraph(alpha,'alpha',cachedGraph,'cached');
await inspectStudioGraph(owner);
assert.equal(calls[0].graph,exactGraph,'Open the actual active prompt, never the cached or unrelated running job');
assert.equal(calls[0].verbatim,true);
assert.deepEqual(calls.slice(1),['return available']);
calls.length=0;alpha.job=null;alpha.source={path:'new.mov'};
await inspectStudioGraph(owner);
assert.deepEqual(calls,['draft'],'A new source does not open the previous take');
calls.length=0;alpha.job={id:'active'};
owner.api.fetchApi=async()=>{owner.mode='director';return {ok:true,json:async()=>({active:{prompt:[0,'active',exactGraph]}})};};
await inspectStudioGraph(owner);
assert.deepEqual(calls,[],'Ignore a graph fetched after the user switches modes');

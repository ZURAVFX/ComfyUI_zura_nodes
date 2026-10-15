import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';import vm from 'node:vm';
const js=readFileSync(new URL('../web/dialogue_editor.js',import.meta.url),'utf8');
const code=js.match(/function connectedSource\(node\)\{[\s\S]*?\n\}/)[0];
const connectedSource=vm.runInNewContext(`(${code})`);
const source={id:100,comfyClass:'ZuraDialogueSource'};
const host={id:208,inputs:[{name:'value_6',type:'ZURA_DIALOGUE_EDIT',link:303}]};
const finish={id:101,inputs:[{name:'edit',type:'ZURA_DIALOGUE_EDIT',link:306}]};
const nodes=new Map([[100,source],[208,host],[101,finish]]);
for(const links of [new Map([[303,{origin_id:100}],[306,{origin_id:208}]]),{303:{origin_id:100},306:{origin_id:208}}]){
 const graph={links,getNodeById:id=>nodes.get(id)};host.graph=graph;finish.graph=graph;
 assert.equal(connectedSource(finish),source);assert.equal(connectedSource({}),null);
}
console.log('Video source timing resolves through native subgraph typed inputs and both link stores.');

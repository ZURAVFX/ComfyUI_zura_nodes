import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../web/audio_dialogue_editor.js',import.meta.url),'utf8');
const body=source.match(/function connectedInput\(n,name\)\{[\s\S]*?\n\}/)[0];
const connectedInput=vm.runInNewContext(`(${body})`);
assert.equal(connectedInput({inputs:[{name:'edit',link:1}]},'edit'),null);
assert.equal(connectedInput({graph:{},inputs:[{name:'edit',link:1}]},'edit'),null);
const original={id:1,comfyClass:'ZuraAudioDialogueSource'};
const host={id:5,subgraph:{},inputs:[{name:'edit',link:10}],getInputNode(){throw Error('Flattened native traversal must not run');}};
const select={id:6,inputs:[{name:'edit',link:11}]};
const nodes=new Map([[1,original],[5,host],[6,select]]);
for(const links of [new Map([[10,{origin_id:1}],[11,{origin_id:5}]]),{10:{origin_id:1},11:{origin_id:5}}]){
 const graph={links,getNodeById:id=>nodes.get(id)};
 host.graph=graph;select.graph=graph;
 assert.equal(connectedInput(connectedInput(select,'edit'),'edit'),original);
 assert.equal(connectedInput(select,'missing'),null);
}
console.log('Audio template loading: detached, incomplete, native host and both link stores passed.');

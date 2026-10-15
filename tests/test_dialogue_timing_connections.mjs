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
const windowCode=js.match(/function contextWindow\(fps,frames,start,end,contextStart,contextEnd\)\{[\s\S]*?\n\}/)[0];
const contextWindow=vm.runInNewContext(`(${windowCode})`);
for(const fps of [24,25,30,29.97,23.976023976023978]){
 const [a,b]=contextWindow(fps,Math.round(65*fps),29.223,33.666,27,60.435);
 assert(a<=29.223*fps);assert(b>=33.666*fps);assert(b-a<=241);
 const selectedA=Math.floor(29.223*fps),selectedB=Math.ceil(33.666*fps);
 const margin=Math.min(Math.floor(.75*fps+.5),Math.floor((241-(selectedB-selectedA))/2));
 assert.equal(a,Math.max(Math.floor(27*fps),selectedA-margin));
 assert.equal(b,Math.min(Math.ceil(60.435*fps),selectedB+margin));
}
assert.throws(()=>contextWindow(30,1950,1,12,0,65),/shorter takes/);
assert.deepEqual(Array.from(contextWindow(30,300,1,1.5,0,2)),[0,60]);
console.log('Automatic context windows retain selected frames and match backend rounding.');
const mouthCode=js.match(/function mouthSelectionConfirmed\(selection,box\)\{[\s\S]*?\n\}/)[0];
const confirmed=vm.runInNewContext(`(${mouthCode})`);
const box=[4,54,349,329],mouth=[178.5,267.85,34.9,26.32];
assert.equal(confirmed({mouth},box),false);
assert.equal(confirmed({mouth,mouth_confirmed:true},box),true);
assert.equal(confirmed({mouth:[178,300,35,26]},box),true);
assert.equal(confirmed({mouth:[178,300,35,26],mouth_confirmed:false},box),false);
const shiftCode=js.match(/function shiftReplacement\(range,edge,value,duration,length\)\{[\s\S]*?\n\}/)[0];
const shift=vm.runInNewContext(`(${shiftCode})`);
for(const [edge,value,expected] of [[0,2,[2,3]],[1,4,[3,4]],[0,-1,[0,1]],[1,7,[4,5]]]){
 const range=Array.from(shift([1,2],edge,value,5,1));assert.deepEqual(range,expected);assert.equal(range[1]-range[0],1);
}
console.log('Old crop guesses need lip placement; replacement handles shift together without retiming.');

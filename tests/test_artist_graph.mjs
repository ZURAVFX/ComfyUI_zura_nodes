import assert from 'node:assert/strict';
import fs from 'node:fs';
import {webcrypto} from 'node:crypto';
if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
const routing=fs.readFileSync(new URL('../web/graph_routing.js',import.meta.url),'utf8');
const routingUrl='data:text/javascript;base64,'+Buffer.from(routing).toString('base64');
const js=fs.readFileSync(new URL('../web/artist_graph.js',import.meta.url),'utf8').replace('"./graph_routing.js"',JSON.stringify(routingUrl));
const {promptFingerprint,expandStageSignals,crossingCount,trimStageSignals,visibleArtistInputs,initialiseArtistImages}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
const {routeFixedPorts}=await import(routingUrl);
const original={image:{class_type:'LoadImage',inputs:{image:'example_character.png'}},render:{class_type:'Render',inputs:{image:['image',0],seed:42}}};
const renamed={'10':{class_type:'LoadImage',inputs:{image:'example_character.png'}},'11':{class_type:'Render',inputs:{image:['10',0],seed:42}}};
assert.equal(await promptFingerprint(original),await promptFingerprint(renamed));
renamed['11'].inputs.seed=43;
assert.notEqual(await promptFingerprint(original),await promptFingerprint(renamed),'A changed seed must fail the graph safety check');
const routed={...original,pack:{class_type:'ZuraStudioSignals',inputs:{keys:'["image"]',value_0:['image',0]}},read:{class_type:'ZuraStudioReadSignal',inputs:{stage_data:['pack',0],key:'image'}},render:{...original.render,inputs:{image:['read',0],seed:42}}};
assert.deepEqual(expandStageSignals(routed),original);
assert.equal(await promptFingerprint(routed),await promptFingerprint(original));
routed.read.inputs.key='missing';assert.throws(()=>expandStageSignals(routed),/missing/);
const cross={edges:[{id:'a',sources:['a'],targets:['b'],sections:[{startPoint:{x:0,y:5},endPoint:{x:10,y:5}}]},
 {id:'b',sources:['c'],targets:['d'],sections:[{startPoint:{x:5,y:0},endPoint:{x:5,y:10}}]}]};
assert.equal(crossingCount(cross),1);
cross.edges[1].sections[0].startPoint.x=20;cross.edges[1].sections[0].endPoint.x=20;
assert.equal(crossingCount(cross),0);
cross.edges[1].sections[0]={startPoint:{x:5,y:5},endPoint:{x:15,y:5}};
assert.equal(crossingCount(cross),1,'Overlapping wires also count as an intersection');
cross.edges[1].sections[0]={startPoint:{x:10,y:5},endPoint:{x:10,y:15}};
assert.equal(crossingCount(cross),1,'An unrelated wire touching a bend is an intersection');
cross.edges[1].sources=cross.edges[0].sources;
assert.equal(crossingCount(cross),0,'A shared output can form an intentional signal junction');
const fixed={children:[
 {id:'nested:1',x:0,y:0,width:100,height:50},{id:'nested:2',x:500,y:200,width:100,height:50},
 {id:'nested:3',x:0,y:200,width:100,height:50},{id:'nested:4',x:500,y:0,width:100,height:50}],edges:[
 {id:'a',sources:['nested:1:out:0'],targets:['nested:2:in:0'],sections:[{startPoint:{x:100,y:25},bendPoints:[{x:300,y:25},{x:300,y:225}],endPoint:{x:500,y:225}}]},
 {id:'b',sources:['nested:3:out:0'],targets:['nested:4:in:0'],sections:[{startPoint:{x:100,y:225},bendPoints:[{x:250,y:225},{x:250,y:25}],endPoint:{x:500,y:25}}]}]};
assert(crossingCount(fixed)>0);
const clean=routeFixedPorts(fixed);assert(clean,'Route fixed sockets with nested node IDs');
assert.equal(crossingCount(clean),0);assert.deepEqual(clean.children,fixed.children,'Wire routing must not move native nodes');
for(const edge of clean.edges)for(const section of edge.sections){const points=[section.startPoint,...section.bendPoints,section.endPoint];
 for(let i=1;i<points.length;i++)assert(points[i].x===points[i-1].x||points[i].y===points[i-1].y,'Every segment is orthogonal');}
const handoff={widgets:[{name:'keys',value:'["image","audio"]'}],
 inputs:[{name:'keys'},{name:'previous'},...Array.from({length:64},(_,i)=>({name:'value_'+i,link:i===10?42:null}))],
 removeInput(index){this.inputs.splice(index,1)}};
trimStageSignals(handoff);
assert.deepEqual(handoff.inputs.map(i=>i.name),['keys','previous','value_0','value_1','value_10'],'Trim unused slots without disconnecting existing data');
const callbacks=[];
const imageNodes=['ref_0','ref_1'].map(id=>({id,type:'LoadImage',widgets:[{name:'image',value:'wrong.png',callback(value){callbacks.push([id,value]);}}]}));
const mediaGraph={_nodes:[...imageNodes,{id:'video',type:'LoadVideo'}]};
const mediaApi={ref_0:{class_type:'LoadImage',inputs:{image:'studio/project/ref0.png'}},ref_1:{class_type:'LoadImage',inputs:{image:'studio/project/ref1.png'}}};
await initialiseArtistImages(mediaGraph,mediaApi);
assert.deepEqual(callbacks,[['ref_0','studio/project/ref0.png'],['ref_1','studio/project/ref1.png']],'Each real native loader refreshes its own selected file once');
assert.deepEqual([...visibleArtistInputs(mediaGraph._nodes)],imageNodes,'All reference images remain native root nodes, not filename-only promoted widgets');
const rendered=Object.fromEntries(imageNodes.map(n=>[n.id,{class_type:n.type,inputs:{image:n.widgets[0].value}}]));
assert.equal(await promptFingerprint(mediaApi),await promptFingerprint(rendered),'Visible native image controls retain the exact executable file inputs');
const remapped={_nodes:[{id:'12_ref',type:'LoadImage',widgets:[{name:'image',value:''}]}]};
await initialiseArtistImages(remapped,{'12:ref':{class_type:'LoadImage',inputs:{image:'nested/reference.png'}}});
assert.equal(remapped._nodes[0].widgets[0].value,'nested/reference.png','Native API colon-ID remapping does not lose a loaded reference');
await assert.rejects(()=>initialiseArtistImages({_nodes:[]},mediaApi),/reference image is missing/);
console.log('Artist graph semantic checks and crossing detection passed.');

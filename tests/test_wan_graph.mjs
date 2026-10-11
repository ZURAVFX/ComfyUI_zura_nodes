// Offline native-shaped fixtures: no Comfy server, queue, media or model calls.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {webcrypto} from 'node:crypto';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
Error.prepareStackTrace = error => `${error.name}: ${error.message}`;
if (!globalThis.crypto) Object.defineProperty(globalThis, 'crypto', {value:webcrypto});
const data = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const routing = data(fs.readFileSync(new URL('../web/graph_routing.js', import.meta.url), 'utf8'));
const artist = data(fs.readFileSync(new URL('../web/artist_graph.js', import.meta.url), 'utf8').replace('"./graph_routing.js"', JSON.stringify(routing)));
const moduleURL = data(fs.readFileSync(new URL('../web/wan_graph.js', import.meta.url), 'utf8').replace('"./artist_graph.js"', JSON.stringify(artist)));
const {applyWanPatches, nativeNodes, attachWanGraphControls} = await import(moduleURL);
const {expandStageSignals} = await import(artist);
const copy = value => JSON.parse(JSON.stringify(value));
let passed = 0;
async function test(name, fn) { await fn(); passed++; console.log('PASS ' + name); }

// Fixture implements the native methods consumed by this controller. Native
// subgraph definitions and instance IDs survive serialization independently.
function graphFrom(prompt) {
  const graph = {extra:{}, _nodes:[], links:new Map(), inputNode:{id:-10},
    getLink(id) { return this.links.get(id); }, setDirtyCanvas() {},
    serialize() {
      const definitions = {subgraphs:[]};
      function encode(g) {
        return {id:g.definitionId, nodes:g._nodes.map(n => {
          if (n.subgraph) definitions.subgraphs.push(encode(n.subgraph));
          return {id:n.id, type:n.type, pos:n.pos, properties:copy(n.properties),
            inputs:copy(n.inputs), widgets_values:n.widgets.map(w=>w.value), widget_names:n.widgets.map(w=>w.name)};
        }), links:[...g.links.values()].map(copy), extra:copy(g.extra)};
      }
      return {...encode(this), definitions};
    }};
  let nextLink = 1;
  for (const [id, spec] of Object.entries(prompt)) {
    const node = {id, type:spec.class_type, graph, properties:{}, pos:[50,80],
      inputs:[], widgets:[], getWidgetFromSlot(slot) { return this.widgets.find(w=>w.name===slot.name); }};
    for (const [name,value] of Object.entries(spec.inputs || {})) {
      const input = {name,link:null}; node.inputs.push(input);
      if (Array.isArray(value) && prompt[String(value[0])]) {
        input.link = nextLink;
        graph.links.set(nextLink++, {origin_id:String(value[0]),origin_slot:value[1],target_id:id,target_slot:node.inputs.length-1});
      } else node.widgets.push({name,value});
    }
    graph._nodes.push(node);
  }
  return graph;
}
function restore(serialized) {
  const definitions = new Map((serialized.definitions?.subgraphs || []).map(g=>[g.id,g]));
  function decode(s) {
    const g = graphFrom({}); g.extra = copy(s.extra || {}); g.definitionId = s.id;
    g.links = new Map(s.links.map(l=>[l.id ?? s.links.indexOf(l)+1,l]));
    g._nodes = s.nodes.map(n => {
      const node = {id:n.id,type:n.type,graph:g,pos:copy(n.pos),properties:copy(n.properties),inputs:copy(n.inputs),
        widgets:n.widget_names.map((name,i)=>({name,value:n.widgets_values[i]})),
        getWidgetFromSlot(slot) { return this.widgets.find(w=>w.name===slot.name); }};
      if (definitions.has(n.type)) node.subgraph = decode(definitions.get(n.type));
      return node;
    });
    return g;
  }
  return decode(serialized);
}
function group(graph, id = '30') {
  const root = graphFrom({}); graph.definitionId = 'fixture-native-definition';
  const host = {id,type:graph.definitionId,subgraph:graph,graph:root,pos:[400,200],properties:{artistNote:'keep'},inputs:[],widgets:[],
    getWidgetFromSlot(slot) { return this.widgets.find(w=>w.name===slot.name); }};
  root._nodes.push(host); return root;
}
function compile(root) {
  const result = {};
  for (const item of nativeNodes(root)) {
    const {node,graph,path} = item; if (node.subgraph) continue;
    const prefix = path.split(':').slice(0,-1).join(':');
    const inputs = Object.fromEntries(node.widgets.map(w=>[w.name,w.value]));
    for (const input of node.inputs) if (input.link != null) {
      const link = graph.getLink(input.link);
      if (link.origin_id === graph.inputNode.id) {
        const host = nativeNodes(root).find(n=>n.node.subgraph===graph).node;
        inputs[input.name] = host.widgets.find(w=>w.name===host.inputs[link.origin_slot].name).value;
      } else inputs[input.name] = [(prefix ? prefix+':' : '')+link.origin_id,link.origin_slot];
    }
    result[path] = {class_type:node.type,inputs};
  }
  return result;
}
const recipe = {
  '1':{class_type:'ZuraWanGraphQueueGuard',inputs:{plan_json:'plan-one'}},
  '2':{class_type:'ZuraWanPreparationWindow',inputs:{start_frame:['1',1],frame_count:['1',2]}},
  '3':{class_type:'ZuraWanCarryPoseWindow',inputs:{cache_key:['1',0],pose:['5',0]}},
  '4':{class_type:'ZuraWanSavePreparationPart',inputs:{cache_key:['1',0],pose:['3',0]}},
  '5':{class_type:'PoseDraw',inputs:{face_padding:7,body:true}},
  '6':{class_type:'ArtistUnrelated',inputs:{note:'keep',seed:42}},
};
function plan(prompt, action='prepare') {
  const guard = Object.keys(prompt).find(id=>prompt[id].class_type==='ZuraWanGraphQueueGuard');
  const graph = copy(prompt); graph[guard].inputs.plan_json = 'plan-two';
  const patches = [];
  for (const [id,n] of Object.entries(expandStageSignals(prompt))) {
    const role = {ZuraWanPreparationWindow:'window',ZuraWanCarryPoseWindow:'carry',ZuraWanSavePreparationPart:'saver',VHS_LoadVideoFFmpegPath:'guide_loader'}[n.class_type];
    if (!role) continue;
    patches.push({node_id:id,class_type:n.class_type,role_id:'zura.wan.'+role,connections:Object.fromEntries(
      Object.entries(n.inputs).filter(([,v])=>Array.isArray(v)&&v[0]===guard).map(([k,v])=>[k,{source_role:'zura.wan.guard',output:v[1]}]))});
  }
  return {action,graph,patches,guard:{semantic_id:guard,plan_json:'plan-two'},context:{schema:'zura_wan_graph_context_v1',context_key:'fixture'},
    progress:{completed_frames:81,total_frames:162,section_index:1,section_total:2}};
}
function fixture({request,tidy,stage='wan_prepare',root=group(graphFrom(recipe)),dom=false}={}) {
  const app = {rootGraph:root,queueCalls:0,loadCalls:0,
    async graphToPrompt(graph) { return {output:compile(graph)}; },
    async loadApiJson(prompt) { this.loadCalls++; this.rootGraph=graphFrom(prompt); },
    async loadGraphData(workflow) { this.loadCalls++; this.rootGraph=restore(workflow); return true; },
    queuePrompt() { this.queueCalls++; throw Error('Queuing is forbidden in these tests'); }};
  const document = dom ? parseHTML('<html><head></head><body></body></html>').document : undefined;
  const options = {projectId:'fixture-project',stage,context:null,request:request || (async(path,body)=>plan(body.prompt)),tidy,document};
  const controls = attachWanGraphControls(app, options);
  return {app,controls,options,document};
}

await test('nested guard patch preserves artist controls, layout and all connections', async()=>{
  const {app,controls} = fixture(); const original=app.rootGraph.serialize();
  await controls.run(); const current=app.rootGraph.serialize();
  assert.equal(compile(app.rootGraph)['30:1'].inputs.plan_json,'plan-two');
  assert.equal(compile(app.rootGraph)['30:5'].inputs.face_padding,7);
  assert.deepEqual(current.nodes,original.nodes);
  assert.deepEqual(current.definitions.subgraphs[0].links,original.definitions.subgraphs[0].links);
  assert.equal(app.queueCalls,0);
});
await test('missing or changed guard links fail atomically', async()=>{
  const root=group(graphFrom(recipe)), before=root.serialize(), prompt=compile(root), result=plan(prompt);
  result.patches[0].connections.start_frame.output=0;
  assert.throws(()=>applyWanPatches(root,prompt,result),/queue guard/);
  assert.deepEqual(root.serialize(),before);
});
await test('artist-setting patch rejected without partial changes',async()=>{
  const root=group(graphFrom(recipe)), prompt=compile(root), result=plan(prompt), before=root.serialize();
  result.patches.push({node_id:'30:5',inputs:{face_padding:8}});
  assert.throws(()=>applyWanPatches(root,prompt,result),/unsupported/); assert.deepEqual(root.serialize(),before);
});
await test('promoted host widget and inner widget update together',async()=>{
  const inner=graphFrom({'1':{class_type:'ZuraWanGraphQueueGuard',inputs:{plan_json:'plan-one'}}}), root=group(inner);
  const host=root._nodes[0], node=inner._nodes[0];
  host.inputs=[{name:'Section plan',link:null}]; host.widgets=[{name:'Section plan',value:'plan-one'}];
  inner.links.set(1,{origin_id:-10,origin_slot:0,target_id:'1',target_slot:0}); node.inputs[0].link=1;
  const undo=applyWanPatches(root,compile(root),{patches:[{node_id:'30:1',inputs:{plan_json:'plan-two'}}]});
  assert.equal(host.widgets[0].value,'plan-two'); assert.equal(node.widgets[0].value,'plan-two');
  assert.equal(compile(root)['30:1'].inputs.plan_json,'plan-two');
  assert.equal(compile(restore(root.serialize()))['30:1'].inputs.plan_json,'plan-two');
  undo(); assert.equal(host.widgets[0].value,'plan-one');
});
const guideRecipe = {...copy(recipe),
  '7':{class_type:'VHS_LoadVideoFFmpegPath',inputs:{video:'guide.mp4',force_rate:24,
    custom_width:512,frame_load_cap:['1',2],start_time:['1',3]}},
};
await test('selected-guide colon paths preserve native range edges and artist edits',async()=>{
  const {app,controls}=fixture({root:group(graphFrom(guideRecipe),'44')});
  app.rootGraph._nodes[0].subgraph._nodes.find(n=>n.id==='7').pos=[170,250];
  const before=app.rootGraph.serialize(); await controls.run();
  const after=app.rootGraph.serialize(), compiled=compile(app.rootGraph);
  assert.deepEqual(compiled['44:7'].inputs.frame_load_cap,['44:1',2]);
  assert.deepEqual(compiled['44:7'].inputs.start_time,['44:1',3]);
  assert.equal(compiled['44:7'].inputs.custom_width,512);
  assert.equal(compiled['44:7'].inputs.force_rate,24);
  assert.equal(compiled['44:5'].inputs.face_padding,7);
  assert.deepEqual(after.definitions.subgraphs[0].links,before.definitions.subgraphs[0].links);
  assert.deepEqual(after.definitions.subgraphs[0].nodes.find(n=>n.id==='7').pos,[170,250]);
  assert.deepEqual(compile(restore(after))['44:7'].inputs,compiled['44:7'].inputs);
  assert.equal(app.queueCalls,0);
});
await test('selected-guide ranges resolve through native StageSignals without rewiring',async()=>{
  const routed=copy(guideRecipe);
  routed['8']={class_type:'ZuraStudioSignals',inputs:{keys:'["count","time"]',value_0:['1',2],value_1:['1',3]}};
  routed['9']={class_type:'ZuraStudioReadSignal',inputs:{stage_data:['8',0],key:'count'}};
  routed['10']={class_type:'ZuraStudioReadSignal',inputs:{stage_data:['8',0],key:'time'}};
  routed['7'].inputs.frame_load_cap=['9',0];routed['7'].inputs.start_time=['10',0];
  const {app,controls}=fixture({root:group(graphFrom(routed),'44')}), before=app.rootGraph.serialize();
  await controls.run();
  assert.deepEqual(app.rootGraph.serialize().definitions.subgraphs[0].links,before.definitions.subgraphs[0].links);
  assert.deepEqual(expandStageSignals(compile(app.rootGraph))['44:7'].inputs.start_time,['44:1',3]);
  assert.deepEqual(compile(app.rootGraph)['44:7'].inputs.start_time,['44:10',0]);
  assert.equal(app.queueCalls,0);
});
await test('stale, disconnected and wrong-output guide edges reject atomically',async()=>{
  for(const faulty of ['disconnected','wrong-output','wrong-guard']) {
    const input=copy(guideRecipe);
    if(faulty==='disconnected') input['7'].inputs.start_time=0;
    if(faulty==='wrong-output') input['7'].inputs.start_time=['1',2];
    if(faulty==='wrong-guard') {
      input['8']={class_type:'ZuraWanGraphQueueGuard',inputs:{plan_json:'unrelated-plan'}};
      input['7'].inputs.start_time=['8',3];
    }
    const root=group(graphFrom(input),'44'), before=root.serialize(), prompt=compile(root), result=plan(prompt);
    const guide=result.patches.find(p=>p.class_type==='VHS_LoadVideoFFmpegPath');
    guide.connections={frame_load_cap:{source_role:'zura.wan.guard',output:2},start_time:{source_role:'zura.wan.guard',output:3}};
    assert.throws(()=>applyWanPatches(root,prompt,result),/queue guard/,faulty);
    assert.deepEqual(root.serialize(),before,faulty);
  }
});
await test('literal guide range or artist-setting patches are forbidden',async()=>{
  for(const name of ['frame_load_cap','start_time','custom_width','force_rate','video']) {
    const root=group(graphFrom(guideRecipe),'44'), before=root.serialize(), prompt=compile(root), result=plan(prompt);
    result.patches.push({node_id:'44:7',class_type:'VHS_LoadVideoFFmpegPath',role_id:'zura.wan.guide_loader',inputs:{[name]:1}});
    assert.throws(()=>applyWanPatches(root,prompt,result),/artist setting/);
    assert.deepEqual(root.serialize(),before);
  }
});
await test('network error retains native graph and queue stays unused',async()=>{
  const {app,controls}=fixture({request:async()=>{throw Error('Unavailable');}}), before=app.rootGraph.serialize();
  await assert.rejects(()=>controls.run(),/Unavailable/); assert.deepEqual(app.rootGraph.serialize(),before); assert.equal(app.queueCalls,0);
});
await test('compiled mismatch rolls back guard and role tags',async()=>{
  const {app,controls}=fixture({request:async(p,b)=>{const r=plan(b.prompt);r.graph['30:5'].inputs.face_padding=90;return r;}});
  const before=app.rootGraph.serialize(); await assert.rejects(()=>controls.run(),/previous values/); assert.deepEqual(app.rootGraph.serialize(),before);
});
await test('artist edit during awaited planning cancels update',async()=>{
  const {app,controls}=fixture({request:async(p,b)=>{app.rootGraph._nodes[0].subgraph._nodes[4].widgets[0].value=9;return plan(b.prompt);}});
  await assert.rejects(()=>controls.run(),/changed during planning/);
  assert.equal(compile(app.rootGraph)['30:5'].inputs.face_padding,9); assert.equal(compile(app.rootGraph)['30:1'].inputs.plan_json,'plan-one');
});
await test('tab switch during planning preserves unrelated workflow',async()=>{
  const unrelated=graphFrom({'9':{class_type:'Unrelated',inputs:{seed:100}}});
  const {app,controls}=fixture({request:async(p,b)=>{app.rootGraph=unrelated;return plan(b.prompt);}});
  await assert.rejects(()=>controls.run(),/changed/); assert.equal(app.rootGraph,unrelated); assert.equal(app.loadCalls,0);
});
await test('guard required on preparation response',async()=>{
  const {controls}=fixture({request:async(p,b)=>{const r=plan(b.prompt);delete r.guard;return r;}});
  await assert.rejects(()=>controls.run(),/missing its queue guard/);
});
await test('merge and render retain native preparation and restore exact artist edits',async()=>{
  let phase=0;
  const {app,controls}=fixture({request:async(p,b)=>{
    assert(p.endsWith('/fixture-project/wan-graph/plan')); assert(b.prompt['30:5']);
    if (phase++===0) return {...plan(b.prompt,'merge'),graph:{'7':{class_type:'ZuraWanMergePreparation',inputs:{cache_key:'fixture'}}}};
    assert.equal(b.action,'render'); return {...plan(b.prompt,'render'),graph:{'8':{class_type:'ZuraWanStreamedRender',inputs:{cache_key:'fixture',seed:42}}}};
  },tidy:async a=>{
    const root=a.rootGraph, grouped=group(restore(root.serialize()),'45');
    root._nodes=grouped._nodes;root.links=grouped.links;root._nodes[0].graph=root;
  }});
  const before=app.rootGraph.serialize(); await controls.run(); assert.equal(controls.state.stage,'wan_merge');
  await controls.run(); assert.equal(controls.state.stage,'wan'); await controls.editMotion();
  assert.equal(controls.state.stage,'wan_prepare');
  const restored=app.rootGraph.serialize(); assert.deepEqual(restored.nodes,before.nodes); assert.deepEqual(restored.definitions,before.definitions);
  assert.equal(app.queueCalls,0);
});
await test('native grouping failure restores previous workflow',async()=>{
  const {app,controls}=fixture({request:async(p,b)=>({...plan(b.prompt,'merge'),graph:{'7':{class_type:'ZuraWanMergePreparation',inputs:{cache_key:'fixture'}}}}),
    tidy:async()=>{throw Error('Grouping failed');}}), before=app.rootGraph.serialize();
  await assert.rejects(()=>controls.run(),/Grouping failed/); assert.deepEqual(app.rootGraph.serialize(),before); assert(controls.current());
});
await test('saved native file reload restores context and removes stale toolbar',async()=>{
  const {app,controls,options,document}=fixture({dom:true}); await controls.run();
  const saved=app.rootGraph.serialize(); await app.loadGraphData(saved);
  const restored=attachWanGraphControls(app,{request:options.request,document});
  assert.equal(restored.state.context.context_key,'fixture'); assert.equal(document.querySelectorAll('.zura-wan-graph-controls').length,1);
  app.rootGraph=graphFrom({'1':{class_type:'Unrelated',inputs:{}}});
  assert.equal(attachWanGraphControls(app,{request:options.request,document}),null);
  assert.equal(document.querySelectorAll('.zura-wan-graph-controls').length,0);
  await assert.rejects(()=>restored.run(),/no longer active/);
});
await test('warm render can explicitly open fresh bounded motion graph',async()=>{
  const {app,controls}=fixture({stage:'wan',root:graphFrom({'8':{class_type:'ZuraWanStreamedRender',inputs:{seed:42}}}),
    request:async(p,b)=>{assert.equal(b.action,'edit_motion');return plan(recipe);}});
  await controls.editMotion(); assert.equal(controls.state.stage,'wan_prepare'); assert.equal(compile(app.rootGraph)['1'].inputs.plan_json,'plan-two');
  assert.equal(app.queueCalls,0);
});
await test('warm merge waits for external Queue completion then opens render',async()=>{
  let cacheComplete=false,requests=0;
  const {app,controls}=fixture({stage:'wan_merge',root:graphFrom({'7':{class_type:'ZuraWanMergePreparation',inputs:{cache_key:'fixture'}}}),
    request:async(p,b)=>{
      requests++; assert.equal(b.action,'render'); assert.equal(b.prompt['7'].class_type,'ZuraWanMergePreparation');
      assert.equal(b.context,null);
      return {action:cacheComplete?'render':'merge',context:null,progress:null,
        graph:cacheComplete?{'8':{class_type:'ZuraWanStreamedRender',inputs:{seed:42}}}:b.prompt};
    }});
  await controls.run(); assert.equal(controls.state.stage,'wan_merge');assert.equal(app.loadCalls,0);
  cacheComplete=true; await controls.run(); assert.equal(controls.state.stage,'wan');assert.equal(app.loadCalls,1);
  assert.equal(controls.state.savedPreparation,null);assert.equal(app.queueCalls,0);
});
await test('missing context is rejected for edited preparation plans',async()=>{
  const {controls}=fixture({request:async(p,b)=>({...plan(b.prompt),context:null})});
  await assert.rejects(()=>controls.run(),/incomplete response/);
});
await test('saved-motion load failure restores render state',async()=>{
  const {app,controls}=fixture({request:async(p,b)=>({...plan(b.prompt,'render'),graph:{'8':{class_type:'ZuraWanStreamedRender',inputs:{seed:42}}}})});
  await controls.run(); const before=app.rootGraph.serialize(), original=app.loadGraphData.bind(app); let first=true;
  app.loadGraphData=async data=>{if(first){first=false;app.rootGraph=restore(data);throw Error('Load failed');}return original(data);};
  await assert.rejects(()=>controls.editMotion(),/Load failed/); assert.deepEqual(app.rootGraph.serialize(),before);
});
await test('switching tabs during native grouping never restores over the new workflow',async()=>{
  const unrelated=graphFrom({'1':{class_type:'Unrelated',inputs:{artistNote:'keep'}}});
  const {app,controls}=fixture({request:async(p,b)=>({...plan(b.prompt,'merge'),graph:{'7':{class_type:'ZuraWanMergePreparation',inputs:{cache_key:'fixture'}}}}),
    tidy:async a=>{a.rootGraph=unrelated;throw Error('Workflow switched');}});
  await assert.rejects(()=>controls.run(),/Workflow switched/);
  assert.equal(app.rootGraph,unrelated); assert.equal(app.loadCalls,1); assert.equal(app.queueCalls,0);
});
await test('final-section toolbar sends explicit finish action',async()=>{
  let received;
  const {controls}=fixture({dom:true,request:async(p,b)=>{received=b.action;return plan(b.prompt);}});
  controls.state.progress={completed_frames:162,total_frames:162}; controls.refresh();
  assert.equal(controls.ui.primary.textContent,'Finish motion'); controls.ui.primary.onclick();
  while(controls.busy) await new Promise(r=>setTimeout(r,0)); assert.equal(received,'finish');
});
await test('toolbar accessibility, explicit action and duplicate click protection',async()=>{
  let resolve; const {app,controls,document}=fixture({dom:true,request:(p,b)=>new Promise(r=>{resolve=()=>r(plan(b.prompt));})});
  assert.equal(document.querySelector('section').getAttribute('aria-label'),'Wan motion graph controls');
  const pending=controls.run(); while(!resolve) await new Promise(r=>setTimeout(r,0));
  assert.equal(controls.ui.primary.disabled,true); assert.equal(controls.ui.box.getAttribute('aria-busy'),'true');
  await assert.rejects(()=>controls.run(),/Wait/); resolve(); await pending;
  assert.equal(controls.ui.primary.disabled,false); assert.equal(app.queueCalls,0);
  assert(!document.body.textContent.includes('fixture')); assert(!document.body.textContent.includes('plan-two'));
});
console.log(`${passed} Wan Graph offline behavioural checks passed.`);

/** Native, editable Paintout stages. Inference stays in the original native nodes. */
let promotionApi;
async function nativePromotionApi() {
  if (!promotionApi) promotionApi=(async()=>{
    // Resolve the current frontend export rather than pinning a build hash/alias.
    const assets=performance.getEntriesByType('resource').map(entry=>entry.name);
    const url=assets.find(url=>/\/assets\/settingStore-[^/]+\.js/.test(url));
    if (!url) throw new Error('Update ComfyUI to open the native artist graph.');
    const response=await fetch(url);
    if (!response.ok) throw new Error('Could not read ComfyUI native graph tools.');
    const alias=(await response.text()).match(/\bpromoteWidget as ([\w$]+)/)?.[1];
    if (!alias) throw new Error('This ComfyUI frontend does not expose native widget promotion.');
    const module=await import(url);
    if(typeof module[alias]!=='function') throw new Error('Native widget promotion is unavailable.');
    return module[alias];
  })().catch(error=>{promotionApi=null;throw error;});
  return promotionApi;
}

function arrange(graph) {
  const nodes=[...graph.nodes], byId=new Map(nodes.map(node=>[String(node.id),node]));
  const depth=new Map(), visiting=new Set(),links=[...graph.links.values()];
  const level=node=>{
    const id=String(node.id);
    if(depth.has(id))return depth.get(id);
    if(visiting.has(id))return 0;
    visiting.add(id);
    const parents=links.filter(link=>String(link.target_id)===id).map(link=>byId.get(String(link.origin_id))).filter(Boolean);
    const value=parents.length?1+Math.max(...parents.map(level)):0;
    visiting.delete(id);depth.set(id,value);return value;
  };
  const columns=new Map();
  for(const node of nodes){const column=level(node);if(!columns.has(column))columns.set(column,[]);columns.get(column).push(node);}
  let x=120;
  for(const [,column]of [...columns].sort(([a],[b])=>a-b)){
    let y=100,width=320;
    for(const node of column){node.size=[Math.max(300,node.size[0]),Math.max(node.size[1],node.computeSize?.()[1]||0)];node.pos=[x,y];width=Math.max(width,node.size[0]);y+=node.size[1]+100;}
    x+=width+180;
  }
  if(graph.inputNode){graph.inputNode.pos=[-140,100];graph.inputNode.arrange();}
  if(graph.outputNode){graph.outputNode.pos=[x+50,100];graph.outputNode.arrange();}
}

function stage(graph,ids,title) {
  const nodes=graph.nodes.filter(node=>ids.includes(String(node.id)));
  if(!nodes.length)return null;
  const result=graph.convertToSubgraph(new Set(nodes));
  result.node.title=title;result.subgraph.name=title;
  return result;
}

function reorderOutputs(host, order) {
  const sub=host.subgraph;
  const snapshot=sub.outputs.map((slot,index)=>({name:slot.name,type:slot.type,
    internal:slot.getLinks().map(link=>({node:sub.getNodeById(link.origin_id),slot:link.origin_slot})),
    external:(host.outputs[index].links||[]).map(id=>host.graph.links.get(id)).filter(Boolean).map(link=>({node:host.graph.getNodeById(link.target_id),slot:link.target_slot}))}));
  for(const slot of [...sub.outputs].reverse())sub.removeOutput(slot);
  for(const index of order){const entry=snapshot[index],slot=sub.addOutput(entry.name,entry.type);
    for(const old of entry.internal)slot.connect(old.node.outputs[old.slot],old.node);
    for(const old of entry.external)host.connect(sub.outputs.indexOf(slot),old.node,old.slot);
  }
}
function place(graph,id,x,y){const node=graph.nodes.find(node=>String(node.id)===String(id));if(node)node.pos=[x,y];return node;}
function layoutModels(graph){
  for(const [id,x,y]of [['model',120,100],['lora',620,100],['memory',1120,100],['text',1120,350],['video_vae',620,600],['float_vae',1120,600],['audio_vae',1120,850]])place(graph,id,x,y);
  graph.outputNode.pos=[1700,100];graph.outputNode.arrange();
}
function layoutInternals(graph) {
  const layouts={
    'Text conditioning':[['positive',120,100],['negative',120,450],['conditioning',720,280]],
    'Source samples':[['take',120,100],['latent',720,350],['audio',720,650]],
    'Generate and decode':[['sample',120,100],['separate',720,450],['crop_guides',1220,450],['decode',1720,450]],
    'Prepare guides':[['Models',120,100],['Source samples',620,650],['Text conditioning',1120,350],['Removal attention',1120,750],['guide',1720,350],['apply_anchors',2320,350],['combine',2820,650]]
  };
  const layout=layouts[graph.name];if(!layout)return;
  for(const [id,x,y] of layout){const node=graph.nodes.find(n=>String(n.id)===id||n.title===id);if(node)node.pos=[x,y];}
  // Give targeted removal attention a separate lower row before source guidance.
  if(graph.name==='Prepare guides'&&graph.nodes.some(node=>node.title==='Removal attention')){
    place(graph,'guide',1720,650);
    const attention=graph.nodes.find(node=>node.title==='Removal attention');attention.pos=[1120,1000];
  }
  const bounds=graph.nodes.map(n=>n.pos[0]+n.size[0]);
  graph.inputNode.pos=[-220,graph.name==='Prepare guides'?650:100];
  graph.outputNode.pos=[Math.max(...bounds)+380,100];
  graph.inputNode.arrange();graph.outputNode.arrange();
  const route=(origin,slot,target,points)=>{
    const node=graph.nodes.find(n=>String(n.id)===origin||n.title===origin);
    const dest=graph.nodes.find(n=>String(n.id)===target||n.title===target);
    const link=[...graph.links.values()].find(l=>String(l.origin_id)===String(node?.id??origin)&&(slot==null||l.origin_slot===slot)&&String(l.target_id)===String(dest?.id??target));
    if(link)for(const point of points)graph.createReroute(point,link);
  };
  if(graph.name==='Text conditioning')route('-10',3,'conditioning',[[-280,800],[650,800]]);
  if(graph.name==='Source samples'){
    route('-10',1,'audio',[[-280,600],[650,600]]);
    // Keep the frame-rate bypass below the video/audio sample branches.
    if(graph.outputs.length===5)route('take',5,'-20',[[500,900],[1350,900]]);
  }
  if(graph.name==='Generate and decode'){
    route('-10',1,'crop_guides',[[-280,0],[1150,0]]);
    route('-10',2,'crop_guides',[[-280,30],[1120,30]]);
    route('-10',4,'decode',[[-280,850],[1650,850]]);
  }
  if(graph.name==='Prepare guides'){
    route('-10',1,'apply_anchors',[[0,1200],[2250,1200]]);
    route('Models',2,'guide',[[500,240],[1650,240]]);
    route('Models',2,'apply_anchors',[[500,240],[2250,240]]);
    route('Source samples',0,'guide',[[1000,780],[1650,780]]);
    route('Source samples',null,'combine',[[1000,1100],[2750,1100]]);
  }
}
function layoutRoot(graph,preparation,generation){
  const hasMask=graph.nodes.some(node=>String(node.id)==='mask_source'),offset=hasMask?500:0;
  if(hasMask)place(graph,'mask_source',120,100);
  const source=place(graph,'source',120+offset,100);
  place(graph,'anchors',620+offset,550);
  if(preparation)preparation.node.pos=[1200+offset,100];
  if(generation)generation.node.pos=[1700+offset,100];
  const save=place(graph,'save',2200+offset,100);
  const link=[...graph.links.values()].find(link=>String(link.origin_id)==='source'&&String(link.target_id)==='save');
  if(link&&source&&save){graph.createReroute([source.pos[0]+source.size[0]+100,1000],link);graph.createReroute([save.pos[0]-100,1000],link);}
}

export async function tidyArtistGraph(app) {
  const graph=app.rootGraph||app.graph;
  if(!graph?.convertToSubgraph)throw new Error('Update ComfyUI to open native Paintout stages.');
  if(graph.nodes.some(node=>node.subgraph))return;
  const promote=await nativePromotionApi();
  const models=stage(graph,['model','lora','memory','text','video_vae','float_vae','audio_vae'],'Models');
  const prepareIds=['positive','negative','take','conditioning','latent','grow_mask','block_mask','invert_mask','guide','apply_anchors','audio','combine'];
  if(models)prepareIds.push(String(models.node.id));
  const preparation=stage(graph,prepareIds,'Prepare guides');
  if(preparation)reorderOutputs(preparation.node,[3,0,1,2,4]);
  const generation=stage(graph,['sample','separate','crop_guides','decode'],'Generate and decode');
  for(const [result,id,names]of [[preparation,'positive',['text']],[generation,'sample',['seed','steps']]]){
    if(!result)continue;
    const node=result.subgraph.nodes.find(node=>String(node.id)===id);
    for(const name of names){const widget=node?.widgets?.find(widget=>widget.name===name);if(widget)promote(node,widget,[result.node]);}
  }
  if(preparation){
    stage(preparation.subgraph,['positive','negative','conditioning'],'Text conditioning');
    const samples=stage(preparation.subgraph,['take','latent','audio'],'Source samples');
    if(samples?.subgraph.outputs.length===5)reorderOutputs(samples.node,[0,1,3,4,2]);
    stage(preparation.subgraph,['grow_mask','block_mask','invert_mask'],'Removal attention');
  }
  for(const subgraph of graph.subgraphs.values())arrange(subgraph);
  if(models)layoutModels(models.subgraph);
  for(const subgraph of graph.subgraphs.values())layoutInternals(subgraph);
  arrange(graph);layoutRoot(graph,preparation,generation);
  graph.setDirtyCanvas?.(true,true);app.canvas?.setGraph?.(graph);app.canvas?.fitView?.();
}

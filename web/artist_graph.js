// Native subgraph authoring and port-aware layout for Studio's editable copies.
// ELK computes geometry; ComfyUI creates/serializes all nodes and subgraphs.
import { routeFixedPorts, crossingEdgeIds, rerouteSingleEdge } from "./graph_routing.js";

const routedCanvases=new WeakSet();
// Comfy's default splines bow outside the paths checked by the layout router.
// Scope orthogonal drawing to these graphs, including their native subgraphs.
// Restore the canvas setting even if drawing fails; never write user settings.
export function installArtistLinkRendering(app) {
  const canvas=app.canvas;
  if(!canvas?.drawConnections || routedCanvases.has(canvas))return;
  const original=canvas.drawConnections;
  canvas.drawConnections=function(...args){
    const graph=args[2]||this.graph;
    const marked=graph?.extra?.zuraStudio?.nativeSubgraphs || graph?.rootGraph?.extra?.zuraStudio?.nativeSubgraphs;
    if(!marked || this.links_render_mode===-1)return original.apply(this,args);
    const previous=this.links_render_mode;
    try{this.links_render_mode=1;return original.apply(this,args);}
    finally{this.links_render_mode=previous;}
  };
  routedCanvases.add(canvas);
}

// Native loader nodes own their upload controls and asynchronous preview state.
// Keep them on the canvas: converting/promoting just the filename widget loses
// the linked upload/preview lifecycle on some Comfy frontend versions.
export function visibleArtistInputs(nodes) {
  return new Set([...nodes].filter(n=>["LoadImage","ZuraPaintoutCrop","ZuraPaintoutFullFrame","ZuraPaintoutAnchors"].includes(n.type)));
}

export async function initialiseArtistImages(graph, apiGraph) {
  const nodes=[...(graph._nodes||[])], taken=new Set(Object.keys(apiGraph).filter(id=>!id.includes(":")));
  const mapped=new Map();
  for(const id of Object.keys(apiGraph)){
    let local=id;
    if(id.includes(":")){local=id.replaceAll(":","_");while(taken.has(local))local+="_";taken.add(local);}
    mapped.set(id,local);
  }
  const loaders=[];
  for(const [id,data] of Object.entries(apiGraph)){
    if(data.class_type!=="LoadImage"||typeof data.inputs?.image!=="string")continue;
    const node=nodes.find(n=>String(n.id)===mapped.get(id));
    const widget=node?.widgets?.find(w=>w.name==="image");
    if(!node||node.type!=="LoadImage"||!widget)throw new Error("A reference image is missing from the editable graph.");
    widget.value=data.inputs.image;loaders.push({node,widget,value:data.inputs.image});
  }
  // Let native onNodeCreated's initial preview callback finish before refreshing
  // the selected value. No custom thumbnail or image network request is added.
  if(typeof requestAnimationFrame==="function")await new Promise(resolve=>requestAnimationFrame(resolve));
  for(const {node,widget,value} of loaders){
    await widget.callback?.call(widget,value);
    node.graph?.setDirtyCanvas?.(true,true);
  }
  return loaders.map(({node})=>node);
}
export async function promptFingerprint(prompt) {
  prompt=expandStageSignals(prompt);
  const memo=new Map(), active=new Set();
  async function signature(id) {
    id=String(id); if(memo.has(id))return memo.get(id);
    if(active.has(id))throw new Error("A workflow connection contains a cycle.");
    const n=prompt[id]; if(!n)throw new Error("A workflow connection is missing its source.");
    active.add(id);
    const inputs=[];
    for(const [key,v] of Object.entries(n.inputs||{}).sort(([a],[b])=>a.localeCompare(b)))
      inputs.push([key,Array.isArray(v)&&v.length===2&&prompt[String(v[0])] ? [await signature(v[0]),v[1]] : v]);
    const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(JSON.stringify([n.class_type,inputs])));
    const value=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("");
    active.delete(id);memo.set(id,value);return value;
  }
  const values=[];for(const id of Object.keys(prompt))values.push(await signature(id));
  return JSON.stringify(values.sort());
}

// Compare native inference after expanding the lossless data adapters.
export function expandStageSignals(prompt) {
  const result={}, active=new Set();
  function signal(packId,key){
    const marker=packId+"/"+key;if(active.has(marker))throw new Error("A stage hand-off contains a cycle.");active.add(marker);
    const p=prompt[String(packId)];if(p?.class_type!=="ZuraStudioSignals")throw new Error("A stage hand-off is missing.");
    const names=JSON.parse(p.inputs.keys),index=names.indexOf(key);
    const v=index>=0?p.inputs["value_"+index]:p.inputs.previous?signal(p.inputs.previous[0],key):null;
    active.delete(marker);if(v==null)throw new Error("A stage signal is missing: "+key);return resolve(v);
  }
  function resolve(v){const n=Array.isArray(v)&&v.length===2&&prompt[String(v[0])];
    return n?.class_type==="ZuraStudioReadSignal"?signal(n.inputs.stage_data[0],n.inputs.key):v;}
  for(const [id,n] of Object.entries(prompt))if(!["ZuraStudioSignals","ZuraStudioReadSignal"].includes(n.class_type))
    result[id]={...n,inputs:Object.fromEntries(Object.entries(n.inputs||{}).map(([k,v])=>[k,resolve(v)]))};
  return result;
}

function role(n) {
  if(["GenjRestoreSoundtrack","GenjSaveReview","SaveImage","PreviewImage","SaveVideo","GenjRecordDraft","VHS_VideoCombine","GenjVHSVideoFromFilenames","ZuraWanSpeechSaveGuide","ZuraWanSavePreparationPart","ZuraWanMergePreparation","ZuraPaintoutUncrop"].includes(n.type))return "save";
  if(n.type?.startsWith("ZuraSpeech")||String(n.id).startsWith("zura_speech_"))return "speech";
  if(["LoadImage","LoadVideo","LoadAudio","GenjLoadReviewedShot","GenjApplyReferenceAudio","ZuraApplyBoundedReferenceAudio","VHS_LoadVideoFFmpegPath","VHS_LoadVideoPath","VHS_BatchManager","ZuraPaintoutCrop","ZuraPaintoutFullFrame","ZuraPaintoutAnchors"].includes(n.type)||n.type?.startsWith("Primitive"))return "inputs";
  return "process";
}

function connectedStageSets(graph) {
  const result=new Map();
  for(const n of graph._nodes||[]){const key=role(n);if(!result.has(key))result.set(key,new Set());result.get(key).add(n);}
  // A speech guide inside Wan's preparation must remain before animation.
  // Shared finishing nodes receive the generated video after animation.
  const speech=result.get("speech");
  if(speech && [...speech].some(n=>String(n.id).startsWith("wan_"))){
    for(const n of [...speech])if(String(n.id).startsWith("wan_")){result.get("process").add(n);speech.delete(n);}
    if(!speech.size)result.delete("speech");
  }
  return result;
}

function innerRole(n) {
  if(n.type==="ZuraWanGraphQueueGuard")return "Motion and selection";
  if(n.type==="WanVideoBlockSwap")return "Models";
  if(/Loader|Lora|SamplingSD3|TorchSettings|Attention/.test(n.type) && !/ControlNetApply/.test(n.type))return "Models";
  if(/SAM3|ChoosePerformer|Pose|Mask|Depth|Detection|TrackingShots|Crop|Colour|Blockify|ReviewedFrames|Preparation|GetVideoComponents|GetImageSize|GetImageRange|ImageScale|Resize|EmptyImage|ComfyMathExpression|SpeechTimeline/.test(n.type))return "Motion and selection";
  if(/TextEncode|TextEmbed|ClipVisionEncode|Wav2VecEmbeds|ImageToVideoMultiTalk|Conditioning|ReferenceToVideo|AddGuide|LockReferenceAudio|PreserveBackground|VAEEncode|Modality|FramePad|SetLatent|Concat|Separate/.test(n.type))return "Guidance";
  return "Render and decode";
}

function acyclicBuckets(graph,buckets) {
  const owner=new Map();for(const [key,items] of buckets)for(const n of items)owner.set(String(n.id),key);
  const links=[...graph.links.values()].filter(l=>owner.has(String(l.origin_id))&&owner.has(String(l.target_id)));
  const reach=new Map([...buckets.keys()].map(k=>[k,new Set()]));
  for(const l of links){const a=owner.get(String(l.origin_id)),b=owner.get(String(l.target_id));if(a!==b)reach.get(a).add(b);}
  for(const k of reach.keys())for(const i of reach.keys())if(reach.get(i).has(k))for(const j of reach.get(k))reach.get(i).add(j);
  // Only fold convex stages; collapsing interdependent stages would make a cycle.
  return [...buckets].filter(([key])=>!reach.get(key).has(key));
}

function promote(host,names) {
  for(const n of host.subgraph.nodes||[])for(const w of n.widgets||[]){
    if(!names.has(w.name))continue;
    const nativeControl=w.name==="value" ? ({PrimitiveInt:{"Performance seed":"seed","Sampling steps":"steps"},PrimitiveFloat:{"Guidance strength":"cfg"},PrimitiveStringMultiline:{"Animation direction":"prompt"}}[n.type]?.[n.title]) : null;
    if(w.name==="text"&&!(n.type==="CLIPTextEncode"&&String(n.id)==="7"))continue;
    if(w.name==="value"&&!n.type.startsWith("PrimitiveString")&&!nativeControl)continue;
    let slot=n.getSlotFromWidget?.(w);
    if(!slot && n.convertWidgetToInput){n.convertWidgetToInput(w);slot=n.getSlotFromWidget?.(w);}
    if(!slot || slot.link!=null)continue;
    const controlName=nativeControl||w.name;
    const name=[...host.subgraph.inputs].some(i=>i.name===controlName)?`${n.title} · ${controlName}`:controlName;
    const input=host.subgraph.addInput(name,String(slot.type??w.type??"*"));
    if(!input.connect(slot,n)){host.subgraph.removeInput(input);continue;}
  }
  host.subgraph.inputNode.arrange();host.expandToFitContent?.();
}

// Rebuild a newly created interface through native APIs in destination order.
// Existing media links and newly promoted controls otherwise get interleaved.
function orderStageInputs(host) {
  const sub=host.subgraph;
  const entries=[...sub.inputs].map((input,index)=>{
    const targets=[...sub.links.values()].filter(l=>String(l.origin_id)===String(sub.inputNode.id)&&l.origin_slot===index)
      .map(l=>({node:sub.getNodeById(l.target_id),slot:l.target_slot}));
    const outside=host.inputs[index]?.link;
    const link=outside==null?null:host.graph.links.get(outside);
    return {input,targets,origin:link&&host.graph.getNodeById(link.origin_id),output:link?.origin_slot,index};
  });
  const destination=e=>Math.min(...e.targets.map(t=>(t.node.properties?.zuraStudioPacket??0)*1000+t.slot));
  const sorted=[...entries].sort((a,b)=>destination(a)-destination(b)||a.index-b.index);
  if(sorted.every((e,i)=>e===entries[i]))return;
  for(const {input} of [...entries].reverse())sub.removeInput(input);
  for(const e of sorted){
    const input=sub.addInput(e.input.name,e.input.type);
    for(const t of e.targets)if(!input.connect(t.node.inputs[t.slot],t.node))throw new Error("Could not restore an artist control connection.");
    if(e.origin&&!e.origin.connect(e.output,host,sub.inputs.indexOf(input)))throw new Error("Could not restore a reference connection.");
  }
}

function fold(graph,items,title,controls=new Set()) {
  if(!items.size)return null;
  const made=graph.convertToSubgraph(items);
  if(!made?.node)throw new Error("ComfyUI could not create the native subgraph.");
  made.node.title=title;made.subgraph.name=title;
  made.node.color="#313647";made.node.bgcolor="#1d2230";
  promote(made.node,controls);if(controls.size)orderStageInputs(made.node);return made.node;
}

export function layoutInput(graph, overrides={}) {
  const layerGap=overrides.nodeNodeBetweenLayers ?? 180;
  const edgeGap=overrides.edgeEdge ?? 24;
  const edgeNodeGap=overrides.edgeNodeBetweenLayers ?? 45;
  const nodes=[...(graph._nodes||[])];
  const io=[];for(const n of [graph.inputNode,graph.outputNode])if(n?.slots?.length){n.arrange();io.push(n);}
  const positions=new Map(nodes.map(n=>[String(n.id),n]));
  for(const n of io)positions.set(String(n.id),n);
  const children=nodes.map(n=>{
    const width=Math.max(280,n.size[0]),height=Math.max(100,n.size[1])+60;
    const ports=[];
    for(const [side,slots,input] of [["WEST",n.inputs||[],true],["EAST",n.outputs||[],false]]){
      slots.forEach((slot,index)=>{
        const point=n.getSlotPosition?.(index,input)||n.getConnectionPos(input,index);
        ports.push({id:`${n.id}:${input?"in":"out"}:${index}`,width:0,height:0,
          // ELK ports sit on the outside boundary. Native sockets are inset;
          // restore their exact endpoints after applying the node positions.
          x:input?0:width,y:point[1]-n.pos[1]+30,
          layoutOptions:{"elk.port.side":side}});
      });
    }
    return {id:String(n.id),width,height,ports,layoutOptions:{"elk.portConstraints":"FIXED_POS"}};
  });
  for(const n of io){const input=n===graph.outputNode;
    children.push({id:String(n.id),width:n.size[0],height:n.size[1],ports:n.slots.map((slot,index)=>({id:`${n.id}:${input?"in":"out"}:${index}`,width:0,height:0,
      x:slot.pos[0]-n.pos[0],y:slot.pos[1]-n.pos[1],layoutOptions:{"elk.port.side":input?"WEST":"EAST"}})),
      layoutOptions:{"elk.portConstraints":"FIXED_POS", "elk.layered.layering.layerConstraint":input?"LAST":"FIRST"}});
  }
  const edges=[...graph.links.values()].filter(l=>positions.has(String(l.origin_id))&&positions.has(String(l.target_id)))
    .map(l=>({id:String(l.id),sources:[`${l.origin_id}:out:${l.origin_slot}`],targets:[`${l.target_id}:in:${l.target_slot}`]}));
  return {id:"zura",children,edges,layoutOptions:{"elk.algorithm":"layered","elk.direction":"RIGHT",
    "elk.edgeRouting":"ORTHOGONAL","elk.spacing.nodeNode":"110","elk.layered.spacing.nodeNodeBetweenLayers":String(layerGap),
    "elk.layered.spacing.edgeNodeBetweenLayers":String(edgeNodeGap),"elk.spacing.edgeEdge":String(edgeGap),
    "elk.layered.crossingMinimization.strategy":"LAYER_SWEEP","elk.layered.nodePlacement.strategy":"NETWORK_SIMPLEX",
    "elk.padding":"[top=80,left=80,bottom=80,right=80]"}};
}

export function crossingCount(layout) {
  const edges=(layout.edges||[]).map(e=>({id:e.id,source:e.sources?.[0],target:e.targets?.[0],segments:(e.sections||[]).flatMap(s=>{
    const p=[s.startPoint,...s.bendPoints||[],s.endPoint];return p.slice(1).map((b,i)=>[p[i],b]);})}));
  let count=0;
  for(let i=0;i<edges.length;i++)for(let j=i+1;j<edges.length;j++){
    if(edges[i].source===edges[j].source||edges[i].target===edges[j].target)continue;
    const between=(v,a,b)=>v>=Math.min(a,b)&&v<=Math.max(a,b);
    const overlap=(a,b,c,d)=>Math.max(Math.min(a,b),Math.min(c,d))<=Math.min(Math.max(a,b),Math.max(c,d));
    if(edges[i].segments.some(([a,b])=>edges[j].segments.some(([c,d])=>{
      const av=a.x===b.x,cv=c.x===d.x;
      if(av===cv)return av?a.x===c.x&&overlap(a.y,b.y,c.y,d.y):a.y===c.y&&overlap(a.x,b.x,c.x,d.x);
      const v=av?[a,b]:[c,d],h=av?[c,d]:[a,b];
      return between(v[0].x,h[0].x,h[1].x)&&between(h[0].y,v[0].y,v[1].y);
    })))count++;
  }
  return count;
}

// Last-resort fallback for sealed placements (e.g. H3 viewport host 248+253,
// where frozen fan wires trap the prompt wire on all four sides): shift one
// crossing-involved node vertically with its wire endpoints, reroute fresh and
// keep the fewest crossings. Positions and wires only; inference inputs are
// untouched.
export function nudgeToClear(layout){
  const deltas=[60,-60,100,-100,140,-140,160,-160,200,-200];
  const nodeOf=id=>String(id).replace(/:(?:in|out):\d+$/,"");
  const wireLength=l=>(l.edges||[]).flatMap(e=>e.sections||[]).reduce((n,s)=>{
    const p=[s.startPoint,...s.bendPoints||[],s.endPoint];
    return n+p.slice(1).reduce((m,b,i)=>m+Math.abs(b.x-p[i].x)+Math.abs(b.y-p[i].y),0);},0);
  const involved=new Set();
  for(const id of crossingEdgeIds(layout)){
    const e=layout.edges.find(e=>String(e.id)===String(id));
    if(e){involved.add(nodeOf(e.sources[0]));involved.add(nodeOf(e.targets[0]));}
  }
  // Prefer interior nodes; moving a boundary input/output drags its whole fan.
  const ordered=[...involved].sort((a,b)=>(a.startsWith("-")?1:0)-(b.startsWith("-")?1:0)||(a<b?-1:1));
  let best=layout,bestKey=[crossingCount(layout),Infinity,wireLength(layout)];
  for(const nid of ordered){
    for(const dy of deltas){
      // Keep wires attached: shift the moved node's incident endpoints too.
      // The router only reads endpoints and node rects, then routes fresh.
      const moved={...layout,
        children:layout.children.map(c=>String(c.id)===nid?{...c,y:c.y+dy}:c),
        edges:layout.edges.map(e=>{
          const ms=nodeOf(e.sources[0])===nid,mt=nodeOf(e.targets[0])===nid;
          if(!ms&&!mt)return e;
          return {...e,sections:e.sections.map(s=>({...s,
            startPoint:ms?{x:s.startPoint.x,y:s.startPoint.y+dy}:s.startPoint,
            endPoint:mt?{x:s.endPoint.x,y:s.endPoint.y+dy}:s.endPoint}))};
        })};
      let candidate=moved;
      const routed=routeFixedPorts(moved);
      if(routed&&crossingCount(routed)<crossingCount(candidate))candidate=routed;
      if(crossingCount(candidate)){
        for(const id of crossingEdgeIds(candidate).slice(0,8)){
          const single=rerouteSingleEdge(candidate,id);
          if(single&&crossingCount(single)<crossingCount(candidate)){candidate=single;break;}
        }
      }
      const key=[crossingCount(candidate),Math.abs(dy),wireLength(candidate)];
      if(key[0]<bestKey[0]||key[0]===bestKey[0]&&(key[1]<bestKey[1]||key[1]===bestKey[1]&&key[2]<bestKey[2])){
        best=candidate;bestKey=key;
      }
      if(!bestKey[0])return best;
    }
  }
  return best;
}

export function nativeWireLayout(graph,layout) {
  const nodes=new Map((graph._nodes||[]).map(n=>[String(n.id),n]));
  for(const n of [graph.inputNode,graph.outputNode])if(n)nodes.set(String(n.id),n);
  const endpoint=id=>{
    const [,nodeId,direction,slot]=String(id).match(/^(.*):(in|out):(\d+)$/)||[];
    const n=nodes.get(nodeId),index=Number(slot),input=direction==="in";
    if(!n)throw new Error("A routed wire is missing its native node.");
    const p=n===graph.inputNode||n===graph.outputNode?n.slots[index].pos:
      n.getSlotPosition?.(index,input)||n.getConnectionPos(input,index);
    return {x:p[0],y:p[1]};
  };
  return {...layout,edges:layout.edges.map(e=>({...e,sections:e.sections.map((s,i,all)=>({...s,
    ...(i===0?{startPoint:endpoint(e.sources[0])}:{}),
    ...(i===all.length-1?{endPoint:endpoint(e.targets[0])}:{})}))}))};
}

export function trimStageSignals(node) {
  let keys;
  try { keys=JSON.parse(node.widgets?.find(w=>w.name==="keys")?.value||"[]"); } catch { return; }
  if(!Array.isArray(keys))return;
  for(let i=node.inputs.length-1;i>=0;i--)
    if(/^value_\d+$/.test(node.inputs[i].name)&&Number(node.inputs[i].name.slice(6))>=keys.length&&node.inputs[i].link==null)node.removeInput(i);
}

async function arrange(graph,elk) {
  for(const n of graph._nodes||[]){
    if(n.type==="ZuraStudioSignals")trimStageSignals(n);
    n.flags.collapsed=false;n._setConcreteSlots?.();
    const size=n.computeSize();n.setSize?.([Math.max(280,size[0]),size[1]]);n.arrange?.();
  }
  // Try each ELK candidate and route it immediately; keep the fewest crossings.
  // Dense fan-in (e.g. H3 viewport references) needs wider routing lanes.
  // Wires and positions only; inference inputs are untouched.
  async function consider(input){
    const laid=await elk.layout(input);
    let candidate=laid;
    if(crossingCount(laid)){
      const routed=routeFixedPorts(laid);
      if(routed&&crossingCount(routed)<crossingCount(candidate))candidate=routed;
    }
    // Targeted fallback: reroute one crossing wire around frozen others.
    if(crossingCount(candidate)){
      for(const id of crossingEdgeIds(candidate).slice(0,8)){
        const single=rerouteSingleEdge(candidate,id);
        if(single&&crossingCount(single)<crossingCount(candidate)){candidate=single;break;}
      }
    }
    return candidate;
  }
  const data=layoutInput(graph);
  let best=await consider(data);
  // Dense fan-in columns (e.g. 12 viewport ReadSignals) spread over ~3000px with
  // default pitch, sealing every prompt-wire corridor. Compact the stack so the
  // router's grid has room to thread a clean lane. Positions+wires only.
  if(crossingCount(best)&&(graph.links?.size??0)>20)for(const nodeGap of [60,40]){
    const compact=layoutInput(graph,{nodeNodeBetweenLayers:300,edgeEdge:32,edgeNodeBetweenLayers:60});
    const input={...compact,layoutOptions:{...compact.layoutOptions,"elk.spacing.nodeNode":String(nodeGap)}};
    const next=await consider(input);
    if(crossingCount(next)<crossingCount(best))best=next;
    if(!crossingCount(best))break;
  }

  if(crossingCount(best))for(const strategy of ["BRANDES_KOEPF","LINEAR_SEGMENTS"]){
    const input={...layoutInput(graph),layoutOptions:{...data.layoutOptions,"elk.layered.nodePlacement.strategy":strategy}};
    const next=await consider(input);
    if(crossingCount(next)<crossingCount(best))best=next;
    if(!crossingCount(best))break;
  }
  if(crossingCount(best))for(const gap of [300,450,650]){
    for(const strategy of ["NETWORK_SIMPLEX","BRANDES_KOEPF","LINEAR_SEGMENTS"]){
      const spaced=layoutInput(graph,{nodeNodeBetweenLayers:gap,edgeEdge:32,edgeNodeBetweenLayers:60});
      const input={...spaced,layoutOptions:{...spaced.layoutOptions,"elk.layered.nodePlacement.strategy":strategy}};
      const next=await consider(input);
      if(crossingCount(next)<crossingCount(best))best=next;
      if(!crossingCount(best))break;
    }
    if(!crossingCount(best))break;
  }
  // Sealed equilibrium (e.g. H3 viewport host 248+253): no wire-only reroute
  // can escape, so shift one involved node and reroute fresh. Wires+positions.
  if(crossingCount(best)){
    const nudged=nudgeToClear(best);
    if(crossingCount(nudged)<crossingCount(best))best=nudged;
  }
  try{
    if(typeof process!=="undefined"&&process.env?.ZURA_DUMP_LAYOUT&&(graph.links?.get?.(253)||graph.links?.get?.("253"))&&crossingCount(best))
      graph.extra={...(graph.extra||{}),zuraDebugLayout:best};
  }catch{}
  const nodes=new Map((graph._nodes||[]).map(n=>[String(n.id),n]));
  for(const n of [graph.inputNode,graph.outputNode])if(n)nodes.set(String(n.id),n);
  for(const item of best.children||[]){const n=nodes.get(item.id),io=n===graph.inputNode||n===graph.outputNode;
    n.setPos?.(item.x,item.y+(io?0:30));if(!n.setPos)n.pos=[item.x,item.y+(io?0:30)];if(io)n.arrange();}
  best=nativeWireLayout(graph,best);
  for(const e of best.edges||[]){const link=graph.links.get(Number(e.id))||graph.links.get(e.id);if(!link)continue;
    for(const s of e.sections||[])for(const point of s.bendPoints||[])graph.createReroute([point.x,point.y],link);
  }
  graph.extra??={};graph.extra.zuraWireCrossings=crossingCount(best);
  if(crossingCount(best)>0&&best.edges.length<40){
    const es=(best.edges||[]).map(e=>({id:e.id,s:e.sources?.[0],t:e.targets?.[0],seg:(e.sections||[]).flatMap(s=>{const p=[s.startPoint,...s.bendPoints||[],s.endPoint];return p.slice(1).map((b,i)=>[p[i],b]);})}));
    const pairs=[];
    for(let i=0;i<es.length&&pairs.length<8;i++)for(let j=i+1;j<es.length&&pairs.length<8;j++){
      if(es[i].s===es[j].s||es[i].t===es[j].t)continue;
      const btw=(v,a,b)=>v>=Math.min(a,b)&&v<=Math.max(a,b);
      const ov=(a,b,c,d)=>Math.max(Math.min(a,b),Math.min(c,d))<=Math.min(Math.max(a,b),Math.max(c,d));
      if(es[i].seg.some(([a,b])=>es[j].seg.some(([c,d])=>{const av=a.x===b.x,cv=c.x===d.x;
        if(av===cv)return av?a.x===c.x&&ov(a.y,b.y,c.y,d.y):a.y===c.y&&ov(a.x,b.x,c.x,d.x);
        const v=av?[a,b]:[c,d],h=av?[c,d]:[a,b];return btw(v[0].x,h[0].x,h[1].x)&&btw(h[0].y,v[0].y,v[1].y);})))
        pairs.push(es[i].id+"+"+es[j].id);
    }
    if(pairs.length)graph.extra.zuraDebugPairs=pairs;
  }
  graph.setDirtyCanvas?.(true,true);return crossingCount(best);
}

export function stagePlan(graph) {
  const nodes=[...graph._nodes],byId=new Map(nodes.map(n=>[String(n.id),n]));
  // Snapshot endpoints before rewiring. Native links read from a live store.
  const links=[...graph.links.values()].map(l=>({origin_id:l.origin_id,origin_slot:l.origin_slot,target_id:l.target_id,target_slot:l.target_slot})),incoming=new Map(nodes.map(n=>[n,0]));
  for(const l of links)incoming.set(byId.get(String(l.target_id)),incoming.get(byId.get(String(l.target_id)))+1);
  const ranks={inputs:0,Models:1,"Motion and selection":2,Guidance:3,"Render and decode":4,speech:5,save:6};
  function label(n){const r=role(n);return r==="process"?innerRole(n):r==="speech"&&String(n.id).startsWith("wan_")?"Motion and selection":r;}
  const ready=nodes.filter(n=>incoming.get(n)===0),ordered=[];
  while(ready.length){ready.sort((a,b)=>ranks[label(a)]-ranks[label(b)]||nodes.indexOf(a)-nodes.indexOf(b));const n=ready.shift();ordered.push(n);
    for(const l of links)if(String(l.origin_id)===String(n.id)){const next=byId.get(String(l.target_id));incoming.set(next,incoming.get(next)-1);if(incoming.get(next)===0)ready.push(next);}}
  if(ordered.length!==nodes.length)throw new Error("The graph contains a connection cycle.");
  const phases=new Map();
  for(const n of ordered){let phase=ranks[label(n)];for(const l of links)if(String(l.target_id)===String(n.id))phase=Math.max(phase,phases.get(String(l.origin_id)));phases.set(String(n.id),phase);}
  const phaseNames=Object.keys(ranks);ordered.sort((a,b)=>phases.get(String(a.id))-phases.get(String(b.id)));
  const chunks=[];for(const n of ordered){const name=phaseNames[phases.get(String(n.id))];let chunk=chunks.at(-1);
    if(!chunk||chunk.name!==name||chunk.nodes.length>=1){chunk={name,nodes:[]};chunks.push(chunk);}chunk.nodes.push(n);}
  return {chunks,links,byId};
}

export async function tidyArtistGraph(app,apiGraph,stage,ElkClass) {
  const graph=app.rootGraph||app.graph;
  if(!graph?.convertToSubgraph)throw new Error("Update ComfyUI to use native Studio subgraphs.");
  await initialiseArtistImages(graph,apiGraph);
  const visibleInputs=visibleArtistInputs(graph._nodes||[]);
  const before=(await app.graphToPrompt()).output;
  const elk=new ElkClass();let crossings=0;
  const {chunks,links,byId}=stagePlan(graph),owner=new Map();
  chunks.forEach((c,i)=>c.nodes.forEach(n=>owner.set(String(n.id),i)));
  const create=app.createNode||((type)=>window.LiteGraph.createNode(type));
  const connect=(origin,output,target,input)=>{if(!origin.connect(output,target,input))throw new Error("ComfyUI could not connect a stage hand-off.");};
  const packs=[];
  const names={inputs:"Your inputs",Models:"Load models","Motion and selection":"Prepare motion and mask",Guidance:"Guide the look and motion","Render and decode":"Animate and decode",speech:"Speech lip sync",save:"Save and preview"};
  if(stage==="h3_enhance"){
    names["Motion and selection"]="Resize delivery";
    names["Render and decode"]="Enhance frames";
  }
  for(let i=0;i<chunks.length;i++){
    const c=chunks[i];let frontier=new Map();
    for(const l of links)if(owner.get(String(l.origin_id))===i&&owner.get(String(l.target_id))>i)
      frontier.set(`${l.origin_id}/${l.origin_slot}`,l);
    frontier=new Map([...frontier].sort(([,a],[,b])=>c.nodes.indexOf(byId.get(String(a.origin_id)))-c.nodes.indexOf(byId.get(String(b.origin_id)))||a.origin_slot-b.origin_slot));
    const pack=create("ZuraStudioSignals");if(!pack)throw new Error("Restart ComfyUI to load the Zura graph hand-off nodes.");graph.add(pack);pack.title="Stage hand-off";
    pack.widgets.find(w=>w.name==="keys").value=JSON.stringify([...frontier.keys()]);
    for(let slot=pack.inputs.length-1;slot>=0;slot--){const input=pack.inputs[slot];if(input.name.startsWith("value_")&&Number(input.name.slice(6))>=frontier.size)pack.removeInput(slot);}
    if(i)connect(packs[i-1],0,pack,pack.inputs.findIndex(s=>s.name==="previous"));
    let index=0;for(const l of frontier.values()){
      const source=byId.get(String(l.origin_id)),name="value_"+index++,slot=pack.inputs.findIndex(s=>s.name===name);
      pack.inputs[slot].type=source.outputs[l.origin_slot].type;
      pack.inputs[slot].label=source.outputs[l.origin_slot].name;
      connect(source,l.origin_slot,pack,slot);
    }
    packs.push(pack);c.nodes.push(pack);
    for(const l of links)if(owner.get(String(l.target_id))===i&&owner.get(String(l.origin_id))<i){
      const read=create("ZuraStudioReadSignal");graph.add(read);
      read.title=byId.get(String(l.origin_id)).outputs[l.origin_slot].name||"Stage signal";
      read.outputs[0].type=byId.get(String(l.origin_id)).outputs[l.origin_slot].type;
      read.widgets.find(w=>w.name==="key").value=`${l.origin_id}/${l.origin_slot}`;
      connect(packs[i-1],0,read,read.inputs.findIndex(s=>s.name==="stage_data"));
      connect(read,0,byId.get(String(l.target_id)),l.target_slot);c.nodes.push(read);
    }
  }
  const controls=new Set(["image","file","audio","audio_start_seconds","render_long_edge","duration_seconds","start_seconds","use_original_length","prompt","text","value","seed","noise_seed","steps","cfg"]);
  if(stage==="h3_enhance")controls.add("video");
  const stages=[];
  for(let i=0;i<chunks.length;i++){
    const c=chunks[i];for(const n of c.nodes){n.properties??={};n.properties.zuraStudioPacket=i;}
    let group=stages.at(-1);if(!group||group.name!==c.name){group={name:c.name,nodes:[]};stages.push(group);}group.nodes.push(...c.nodes);
  }
  for(let i=0;i<stages.length;i++){
    const group=stages[i],host=fold(graph,new Set(group.nodes.filter(n=>!visibleInputs.has(n))),`${String(i+1).padStart(2,"0")} · ${names[group.name]}`,group.name==="Models"?new Set():controls);
    if(!host)continue;
    // Group actual cloned inner nodes; never refold existing subgraph hosts.
    const packets=new Map();
    for(const n of host.subgraph.nodes){const key=n.properties.zuraStudioPacket;delete n.properties.zuraStudioPacket;if(!packets.has(key))packets.set(key,new Set());packets.get(key).add(n);}
    for(const items of packets.size>1?packets.values():[]){
      const title=[...items].find(n=>!["ZuraStudioSignals","ZuraStudioReadSignal"].includes(n.type))?.title||"Stage hand-off";
      for(const n of items){n._setConcreteSlots?.();n.arrange?.();}
      // Native boundary ports follow selection order: incoming signals first,
      // then artist controls, then the outgoing hand-off.
      const ordered=[...items].sort((a,b)=>{
        const rank=n=>n.type==="ZuraStudioReadSignal"?0:n.type==="ZuraStudioSignals"?2:1;
        if(rank(a)!==rank(b))return rank(a)-rank(b);
        const target=n=>{const link=host.subgraph.links.get(n.outputs?.[0]?.links?.[0]),node=link&&host.subgraph.getNodeById(link.target_id);
          return node?.getSlotPosition?node.getSlotPosition(link.target_slot,true)[1]-node.pos[1]:link?.target_slot??0;};
        return rank(a)===0?target(a)-target(b):0;
      });
      // Dense single-processor packets (e.g. 12 viewport references fanning into
      // one node) seal every prompt-wire corridor: no wire-only routing can reach
      // zero crossings. Split the bottom-feeder settings into their own packet so
      // both sub-layouts have room for clean lanes. Links are untouched, so the
      // compiled render inputs are unchanged.
      const feeders=ordered.filter(n=>n.type==="ZuraStudioReadSignal");
      const processors=ordered.filter(n=>n.type!=="ZuraStudioReadSignal"&&n.type!=="ZuraStudioSignals");
      const take=Math.max(2,Math.floor(feeders.length/4));
      if(processors.length===1&&feeders.length>=9){
        const params=new Set(feeders.slice(-take));
        const main=new Set(ordered.filter(n=>!params.has(n)));
        const paramsPacket=fold(host.subgraph,params,title+" · Settings");
        crossings+=await arrange(paramsPacket.subgraph,elk);
        const mainPacket=fold(host.subgraph,main,title);
        crossings+=await arrange(mainPacket.subgraph,elk);
      }else{
        const packet=fold(host.subgraph,new Set(ordered),title);
        crossings+=await arrange(packet.subgraph,elk);
      }
    }
    crossings+=await arrange(host.subgraph,elk);
  }
  for(const n of visibleInputs)delete n.properties.zuraStudioPacket;
  const rootCrossings=await arrange(graph,elk);crossings+=rootCrossings;
  const after=(await app.graphToPrompt()).output;
  if(await promptFingerprint(before)!==await promptFingerprint(after))throw new Error("Native graph conversion changed the render inputs. The original editable graph will be restored.");
  if(rootCrossings)throw new Error("The main graph still contains intersecting wires. It has not replaced your current workflow.");
  // Exercise the native serializer now; no hand-authored subgraph definitions.
  graph.serialize();graph.extra??={};graph.extra.zuraStudio={stage,nativeSubgraphs:true,wireCrossings:crossings,rootWireCrossings:rootCrossings};
  installArtistLinkRendering(app);
  app.canvas?.setDirty(true,true);app.canvas?.fitView?.();return {crossings};
}

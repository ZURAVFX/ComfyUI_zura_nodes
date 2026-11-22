import {buildRippleStudioGraph} from './studio_ripple_recipes.js';

const submissions=new WeakMap();
const graphEntry=graph=>graph&&Object.values(graph).some(node=>node?.class_type)?graph:null;
const mediaKey=media=>typeof media==='string'?media:media?.id||media?.path||media?.file||media?.filename||'';
const graphStorage=ui=>ui.storage||ui.w?.storage||ui.owner?.storage;
const storageKey=(ui,kind)=>'zura-graph-receipt-v1:'+kind+(ui.w?.page?.classList.contains('zwm-page')?':watermark':'');

export function studioGraphScope(ui,kind){
  if(kind==='switch_x')return JSON.stringify([kind,ui.config?.method,ui.config?.source,ui.config?.matte]);
  if(kind==='project')return JSON.stringify([kind,mediaKey(ui.source),ui.$('graph-stage')?.value]);
  if(kind==='image'){
    const handoff=ui.rippleImage?.request?.id||ui.outpaintGuide?.request?.id;
    return JSON.stringify([kind,ui.imageIntent,ui.imageOperation,handoff,mediaKey(ui.references?.[0])]);
  }
  if(kind==='hdr'){
    const kind=ui.$('source-kind').value,asset=ui.getSource();
    return JSON.stringify(['hdr',kind,kind==='own'?mediaKey(ui.ownAsset):kind==='sequence'?mediaKey(ui.sequenceAsset):kind==='output'?mediaKey(ui.outputRef):mediaKey(asset)||asset?.projectId]);
  }
  if(kind==='frame'||kind==='mask'){
    return JSON.stringify([kind,ui.w.state.source,ui.w.plate?.action,kind==='frame'?ui.selected()?.frame:ui.activeMaskId?.()]);
  }
  const from=ui.sourceInfo||ui.source||ui.ownAsset||ui.sequenceAsset||ui.getSource?.();
  return JSON.stringify([kind,mediaKey(from)||mediaKey(ui.state?.source)||mediaKey(ui.outputRef),ui.plate?.action]);
}

export function rememberStudioGraph(ui,kind,graph,id,identity=studioGraphScope(ui,kind)){
  if(!graphEntry(graph)||!id)return;
  const stages=submissions.get(ui)||new Map();
  stages.set(kind,{id,graph,identity});submissions.set(ui,stages);
  try{graphStorage(ui)?.setItem(storageKey(ui,kind),JSON.stringify({id,identity}));}catch{}
}

export function studioGraphReceipt(ui,kind,identity=studioGraphScope(ui,kind)){
  let receipt=submissions.get(ui)?.get(kind);
  if(!receipt)try{receipt=JSON.parse(graphStorage(ui)?.getItem(storageKey(ui,kind))||'null');}catch{}
  return receipt?.identity===identity?receipt:null;
}

export async function readStudioPrompt(api,id){
  if(typeof id!=='string'||!id)return null;
  const read=async path=>{
    const response=await api.fetchApi(path);
    if(!response.ok)return {};
    return response.json();
  };
  const entry=await read('/history/'+encodeURIComponent(id));
  if(entry[id]?.prompt?.[1]===id)return graphEntry(entry[id].prompt[2]);
  const queue=await read('/queue');
  const active=[...(queue.queue_running||[]),...(queue.queue_pending||[])].find(row=>row[1]===id);
  return graphEntry(active?.[2]);
}

function activeTarget(owner){
  const studio=owner.studio,shared=owner.outputSettings?.delivery;
  const delivery=shared?.activeMode===owner.mode&&shared.delivery?.busy?shared.delivery:null;
  const main=owner.mode==='video'?owner.videoComposer?.ltxOutput?.delivery:null;
  const native=owner.mode==='frames'?owner.frames?.hdrOutput:owner.mode==='outpaint'?owner.outpaint?.hdrDelivery:null;
  const hdr=delivery||(main?.busy&&main.take?.projectId===studio.project?.id?main:null)||(native?.busy?native:null);
  if(hdr)return {workspace:hdr,kind:'hdr_delivery',title:'HDR conversion',id:hdr.activePrompt,managed:true,
    draft:()=>{throw Error('The next HDR graph will be available once it reaches the queue.');}};
  switch(owner.mode){
    case 'image':{
      const take=owner.items?.[owner.selectedImage],request=owner.rippleImage?.request?.id,guide=owner.outpaintGuide?.request?.id;
      const reviewing=!owner.imageArea?.editing&&!owner.editInputs?.showSource&&take?.operation===owner.imageOperation
        &&(take.ripple_guide||null)===(request||null)&&(take.outpaint_guide||null)===(guide||null);
      return {workspace:owner,kind:'image',title:request?'Frame edit':guide?'Frame extension guide':'Image',id:owner.job?.id||(reviewing?take.studio_prompt_id:null)};
    }
    case 'director':return {workspace:owner.director,kind:'director',title:'Director'};
    case 'paint_vfx':return {workspace:owner.paint_vfx,kind:'paint_vfx',title:'Paint VFX'};
    case 'frames':return {workspace:owner.frames,kind:'first_last',title:'First and last frame'};
    case 'switch_x':return {workspace:owner.switchX,kind:'switch_x',title:'Zura SwitchX',draft:async()=>{
      const graph=await owner.switchX.buildGraph();
      if(owner.mode==='switch_x')await openStudioGraph(studio,graph,'Zura SwitchX · Draft graph','switch_x');
    }};
    case 'references':return {workspace:owner.referencesVideo,kind:'reference_video',title:'Reference video'};
    case 'extend_length':return {workspace:owner.extendLength,kind:'extend_length',title:'Extend length'};
    case 'upscale':return {workspace:owner.upscale,kind:'upscale',title:'Upscale video'};
    case 'alpha':return {workspace:owner.alpha,kind:'alpha',title:'Extract alpha'};
    case 'panorama':return {workspace:owner.panorama,kind:'camera',title:'Panorama camera'};
    case 'outpaint':{
      const w=owner.outpaint;
      return {workspace:w,kind:'outpaint',title:'Frame extension',id:w?.hdrDelivery?.activePrompt||w?.job?.active_prompt_id||((w?.job||w?.completedResult)?w.lastGraphPrompt:null),managed:true};
    }
    case 'hdr':{
      const w=studio.hdrTool;
      return {workspace:w,kind:'hdr',title:'Convert to HDR',id:w?.longPrompt||w?.job||(w?.completedResult?w.lastGraphPrompt:null),draft:()=>w.graph(studio)};
    }
    case 'ripple':return {workspace:owner.ripple,kind:'ripple',title:'Ripple'};
    case 'paintout':
    case 'watermark':{
      const w=owner[owner.mode],editor=w?.editor;
      const label=owner.mode==='watermark'?'Remove watermark':owner.plate?.action==='replace'?'Replace':owner.plate?.action==='paint'?'Add':'Remove';
      if(editor&&(editor.toolJob||(!owner.plate?.propagation()||owner.mode==='watermark')&&['clean','mask'].includes(editor.stage))){
        const kind=editor.toolJob?.kind||({clean:'frame',mask:'mask'})[editor.stage];
        return {workspace:editor,kind,title:label+' · '+(kind==='mask'?'Mask':'Clean frame'),id:editor.toolJob?.id,
          draft:()=>{if(!editor.graphViewDraft)throw Error('Make a selection and start the mask or clean-frame step to inspect its graph.');return editor.graphViewDraft();}};
      }
      if(owner.mode==='paintout'&&owner.plate?.propagation()){
        const plate=owner.plate,runner=plate.runner;
        return {workspace:runner||w,kind:'ripple',title:label+' · Video',id:runner?.job?.id,draft:async()=>{
          const active=plate.ensureRunner();
          if(!active.modelInfo)await active.checkModels?.();
          const graph=buildRippleStudioGraph(plate.config(),active.modelInfo||{});
          await openStudioGraph(studio,graph,label+' · Current video settings','ripple');
        }};
      }
      return {workspace:w,kind:owner.mode,title:label+' · Video'};
    }
    default:return {workspace:studio,kind:'project',title:'Video',id:studio.$('graph-stage')?.value==='auto'?studio.activeGraphPrompt?.():null};
  }
}

export async function openStudioGraph(studio,graph,title,stage,{exact=false}={}){
  if(studio.graphViewCheck&&!studio.graphViewCheck())return;
  if(!graphEntry(graph))throw Error('This step has no ComfyUI graph yet.');
  await studio.graph.openApiGraph({graph,name:'Zura · '+title,stage,verbatim:exact});
  if(!studio.graphViewCheck||studio.graphViewCheck())studio.showComfyGraph();
}

function notify(studio,message){
  const doc=studio.container?.ownerDocument;
  if(!doc?.createElement){studio.message(message,true);return;}
  const dialog=doc.createElement('dialog');dialog.className='zura-graph-notice';
  dialog.innerHTML='<form method="dialog"><strong>Graph View</strong><p></p><button>Done</button></form>';
  dialog.querySelector('p').textContent=message;
  studio.container.append(dialog);
  if(typeof dialog.showModal!=='function'){dialog.remove();studio.message(message,true);return;}
  dialog.addEventListener('close',()=>dialog.remove(),{once:true});
  dialog.showModal();
}

export async function inspectStudioGraph(owner){
  const studio=owner.studio;
  if(!studio.graph?.available){notify(studio,'Open Studio inside ComfyUI to see editable graphs.');return;}
  if(owner.openingGraph)return;
  owner.openingGraph=true;
  const mode=owner.mode;
  try{
    const target=activeTarget(owner),w=target.workspace;
    if(!w)throw Error('This workspace is still loading.');
    const identity=studioGraphScope(w,target.kind);
    const isCurrent=()=>owner.mode===mode&&studioGraphScope(w,target.kind)===identity&&activeTarget(owner).kind===target.kind;
    studio.graphViewCheck=isCurrent;
    const current=studioGraphReceipt(w,target.kind,identity);
    const active=target.id||(!target.managed&&(w.job?.active_prompt_id||w.job?.id));
    if(!active&&(w.pendingSubmission||w.submitting||w.starting))throw Error('ComfyUI is preparing this stage. Open Graph View again once it reaches the queue.');
    const id=active||current?.id;
    let exact=null;
    if(id){
      try{exact=await readStudioPrompt(owner.api,id);}
      catch(error){if(current?.id!==id||!current.graph)throw error;}
      if(!exact&&current?.id===id)exact=current.graph;
    }
    if(!isCurrent())return;
    if(exact){
      await openStudioGraph(studio,exact,target.title+' · Submitted graph',target.kind,{exact:true});
      return;
    }
    if(id&&(target.id||w.job))throw Error('This submitted graph is no longer in the ComfyUI queue or history.');
    if(target.kind==='project')await studio.graphView();
    else if(target.draft)await target.draft();
    else if(w.graph)await w.graph();
    else throw Error('This stage has no ComfyUI graph yet.');
  }catch(error){
    if(!studio.graphViewCheck||studio.graphViewCheck())notify(studio,error.message||'This stage has no ComfyUI graph yet.');
  }finally{owner.openingGraph=false;studio.graphViewCheck=null;}
}

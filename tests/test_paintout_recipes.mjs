import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {buildPaintoutGraph,paintoutValidation,paintoutAvailability,PAINTOUT_MODELS,paintoutRangeFix} from '../web/paintout_recipes.js';

const config={mode:'targeted',source:'Z:/plates/street.mov',mask:'Z:/plates/mask.mov',anchors:[{file:'Z:/paint/clean.exr',frame:0,strength:.75,enabled:true,colour_space:'srgb_display'}],seed:74757503725004};
const targeted=buildPaintoutGraph(config),full=buildPaintoutGraph({...config,mode:'full'});

// Resolve the supplied native subgraphs rather than assuming the flat graph's
// wiring. A recursive signature compares every sampler input, guide and export
// operation, independent of node IDs and UI grouping.
async function nativeSignature(mode){
  const filename=mode==='targeted'?'Video - Targeted Paintout (LTX 2.5).json':'Video - Full Scene Clean Plate (LTX 2.5).json';
  const root=JSON.parse(await readFile(new URL('../workflows/'+filename,import.meta.url),'utf8'));
  const defs=new Map(root.definitions.subgraphs.map(s=>[s.id,s]));
  root.nodes.find(n=>n.id===1).widgets_values[0]=config.source;
  if(mode==='targeted'){
    root.nodes.find(n=>n.id===1).widgets_values[1]=config.mask;
    root.nodes.find(n=>n.type==='ZuraPaintoutAnchors').widgets_values[0]=JSON.stringify(config.anchors);
  }
  const exportNode=root.nodes.find(n=>n.type==='ZuraPaintoutUncrop');
  exportNode.widgets_values[0]='paintout/studio';
  const context=(graph,parent=null,instance=null)=>({graph,parent,instance,nodes:new Map(graph.nodes.map(n=>[n.id,n])),links:new Map(graph.links.map(l=>Array.isArray(l)?[l[0],{origin_id:l[1],origin_slot:l[2],target_id:l[3],target_slot:l[4]}]:[l.id,l]))});
  const widgets=node=>{
    const values=[...(node.widgets_values||[])];
    if(node.type==='KSampler')values.splice(1,1); // Seed's frontend variation control is not a backend input.
    return Object.fromEntries((node.inputs||[]).filter(i=>i.widget).map((input,i)=>[input.name,values[i]]));
  };
  const inputValue=(ctx,node,index)=>{
    const input=node.inputs[index];
    if(input.link!=null){const link=ctx.links.get(input.link);assert.ok(link,`Missing native link ${input.link}`);return output(ctx,link.origin_id,link.origin_slot);}
    return widgets(node)[input.name];
  };
  const output=(ctx,id,slot)=>{
    if(id===-10)return inputValue(ctx.parent,ctx.instance,slot);
    const node=ctx.nodes.get(id);assert.ok(node,`Native node ${id} exists`);
    if(node.type.startsWith('Primitive'))return node.widgets_values[0];
    if(defs.has(node.type)){
      const child=context(defs.get(node.type),ctx,node),link=[...child.links.values()].find(l=>l.target_id===-20&&l.target_slot===slot);
      assert.ok(link,`Native subgraph ${child.graph.name} output ${slot} is linked`);
      return output(child,link.origin_id,link.origin_slot);
    }
    const inputs=Object.fromEntries((node.inputs||[]).map((input,i)=>[input.name,inputValue(ctx,node,i)]).filter(([,value])=>value!==undefined));
    return {type:node.type,slot,inputs};
  };
  return output(context(root),exportNode.id,0);
}
function apiSignature(graph,id='save',slot=0){
  const n=graph[id];assert.ok(n,`API node ${id} exists`);
  return {type:n.class_type,slot,inputs:Object.fromEntries(Object.entries(n.inputs).map(([key,value])=>[key,Array.isArray(value)?apiSignature(graph,value[0],value[1]):value]))};
}
for(const [mode,graph] of [['targeted',targeted],['full',full]])assert.deepEqual(apiSignature(graph),await nativeSignature(mode),`${mode} preserves the complete native template pipeline`);

// Whole-shot time and canvas flow from the loader metadata, including padding
// and detected video fps, rather than independently guessed UI constants.
const ranged=buildPaintoutGraph({...config,startFrame:50,frameCount:50,sequenceFps:59.94,anchors:[{file:'Z:/paint/first.png',frame:50},{file:'Z:/paint/last.png',frame:-1}],width:1280,height:704});
assert.equal(ranged.source.inputs.start_frame,50);
assert.equal(ranged.source.inputs.frame_count,50);
assert.equal(ranged.source.inputs.sequence_fps,59.94);
assert.deepEqual(ranged.latent.inputs.length,['take',4]);
assert.deepEqual(ranged.conditioning.inputs.frame_rate,['take',5]);
assert.deepEqual(ranged.audio.inputs.frame_rate,['take',5]);
assert.equal(ranged.source.inputs.render_width,1280);
assert.equal(ranged.source.inputs.render_height,704);
assert.equal(ranged.save.inputs.match_context,true);
assert.equal(full.save.inputs.match_context,false);
assert.equal(full.save.inputs.motion_preview,true);
assert.ok(!Object.values(full).some(n=>['ZuraPaintoutAnchors','ZuraPaintoutCrop','GrowMask','BlockifyMask'].includes(n.class_type)),'Full-scene cleanup must not require mask/anchor preprocessing');

assert.match(paintoutValidation({...config,mask:''}),/removal mask/);
assert.match(paintoutValidation({...config,anchors:[]}),/at least one painted/);
assert.match(paintoutValidation({...config,anchors:[{file:'Z:/clean.png',frame:0,enabled:false}]}),/at least one painted/);
assert.equal(paintoutValidation({...config,mode:'full',mask:'',anchors:[]}), '');
assert.match(paintoutValidation({...config,anchors:[{file:'Z:/clean.png',frame:0.5}]}),/whole source-frame/);
assert.match(paintoutValidation({...config,anchors:[{file:'Z:/clean.png',frame:''}]}),/whole source-frame/);
assert.match(paintoutValidation({...config,startFrame:10}),/outside the selected source range/);
assert.match(paintoutValidation({...config,anchors:[{file:'Z:/clean.png',frame:80},{file:'Z:/other.png',frame:-1}]}),/already a painted image/);
assert.match(paintoutValidation({...config,frameCount:994}),/993/);
assert.match(paintoutValidation({...config,width:720}),/64-pixel/);
assert.match(paintoutValidation({...config,source:'relative.mov'}),/original footage/);
assert.match(paintoutValidation({...config,savePrefix:'../elsewhere'}),/inside the ComfyUI output/);
assert.match(paintoutValidation({...config,keepAudio:false}),/retain source audio/);
assert.match(paintoutValidation({...config,processingSpace:'HDR (ACEScct)',sourceColour:'hlg_rec2020',anchors:[{file:'Z:/clean.png',frame:0}]}),/EXR or high-bit-depth/);
assert.equal(paintoutValidation({...config,processingSpace:'HDR (ACEScct)',sourceColour:'hlg_rec2020'}),'');
const hdr=buildPaintoutGraph({...config,processingSpace:'HDR (ACEScct)',sourceColour:'hlg_rec2020',outputMode:'EXR + HLG video',exrPrecision:'float32'});
assert.equal(hdr.source.inputs.colour_space,'hlg_rec2020');
assert.equal(hdr.source.inputs.processing_mode,'HDR (ACEScct)');
assert.equal(hdr.save.inputs.export_format,'EXR + HLG video');
assert.equal(hdr.save.inputs.precision,'float32');
assert.throws(()=>buildPaintoutGraph({...config,mask:''}),/removal mask/);

// Each mode checks its own adapter and required nodes, so an absent optional
// workflow does not block a working clean-plate route.
const info={};
for(const n of [...Object.values(targeted),...Object.values(full)])info[n.class_type]={input:{required:{},optional:{}}};
const combo=(type,key,values,modern=false)=>{info[type].input.required[key]=modern?['COMBO',{options:values}]:[values];};
combo('UNETLoader','unet_name',[PAINTOUT_MODELS.model],true);
combo('CLIPLoader','clip_name',[PAINTOUT_MODELS.text]);
combo('VAELoader','vae_name',[PAINTOUT_MODELS.videoVae,PAINTOUT_MODELS.audioVae]);
combo('LoraLoaderModelOnly','lora_name',[PAINTOUT_MODELS.targetedLora]);
combo('LTXICLoRALoaderModelOnly','lora_name',[PAINTOUT_MODELS.fullLora],true);
combo('KSampler','scheduler',['linear_quadratic']);
info.LTXAddVideoICLoRAGuideAdvanced.input.optional.use_streaming=['BOOLEAN',{}];
assert.deepEqual(paintoutAvailability(info),{ready:true,missing:[]});
assert.deepEqual(paintoutAvailability(info,'full'),{ready:true,missing:[]});
delete info.ZuraPaintoutApplyAnchors;
assert.equal(paintoutAvailability(info).ready,false);
assert.equal(paintoutAvailability(info,'full').ready,true);
combo('LTXICLoRALoaderModelOnly','lora_name',[]);
assert.ok(paintoutAvailability(info,'full').missing.includes(PAINTOUT_MODELS.fullLora));
console.log('Paintout recipes preserve both native templates; range, anchor, HDR and availability checks passed.');

const sourceSize=buildPaintoutGraph({...config,resolutionMode:'source',sourceWidth:1920,sourceHeight:1080,width:1920,height:1088});
assert.equal(sourceSize.source.inputs.framing_mode,'Source resolution (pad, no resize)');
assert.equal(sourceSize.source.inputs.render_height,1088);
assert.equal(buildPaintoutGraph({...config,resolutionMode:'custom',width:640,height:640}).source.inputs.framing_mode,'Full frame (fit, no crop)');
assert.match(paintoutValidation({...config,resolutionMode:'source',sourceWidth:8192,sourceHeight:4096}),/smaller processing resolution/);

assert.deepEqual(paintoutRangeFix({...config,frameCount:127,anchors:[{file:'Z:/clean.png',frame:127}]},690,301).patch,{startFrame:0,frameCount:128});
assert.equal(paintoutRangeFix({...config,anchors:[{file:'Z:/clean.png',frame:700}]},690,301),null,'Never silently move an unavailable painted frame');
assert.deepEqual(paintoutRangeFix({...config,startFrame:20,frameCount:301,anchors:[{file:'Z:/clean.png',frame:28}]},690,301).patch,{startFrame:20,frameCount:281});
assert.equal(paintoutRangeFix({...config,frameCount:994,anchors:[{file:'Z:/clean.png',frame:993}]},1500,1500),null,'A correction must not discard a painted guide or exceed the shot limit');

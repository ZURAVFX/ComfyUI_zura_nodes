import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';
import {PaintoutEditor} from '../web/paintout_studio/paintout_editor.js';
import {buildPaintoutGraph,paintoutAvailability,PAINTOUT_MODELS} from '../web/paintout_studio/paintout_recipes.js';
assert.ok(fs.existsSync(new URL('../web/vendor/elk.bundled.js',import.meta.url)), 'The native graph layout dependency exists at the integrated workspace import path');

const messages=[],events=[];
function workspace(source=''){
 const w=Object.create(PaintoutWorkspace.prototype),fields=new Map();
 Object.assign(w,{state:{source,anchors:[]},busy:()=>false,render(){},save(){},renderAnchors(){},changed(){},preview(){},message:text=>messages.push(text),requestError:e=>e.message,$:id=>{if(!fields.has(id))fields.set(id,{hidden:false,value:'',removeAttribute(){}});return fields.get(id);},pick:async kind=>{events.push('pick:'+kind);return [];}});
 const editor=Object.create(PaintoutEditor.prototype);
 Object.assign(editor,{w,viewer:{setTool:tool=>events.push('tool:'+tool)},setStage:async stage=>events.push('stage:'+stage),flushManual:async()=>events.push('flush'),ensureProject:async()=>{events.push('ensure');if(!w.state.source)throw Error('Add footage first.');},projectData:()=>({})});w.editor=editor;
 return w;
}
for(const kind of ['footage','sequence']){
 const w=workspace();messages.length=0;events.length=0;
 await w.pickSource(kind);
 assert.deepEqual(events,['flush','pick:'+kind],'An empty workspace reaches the picker without requiring an editor project');
 assert.deepEqual(messages,[]);assert.equal(w.picking,false);assert.equal(w.state.source,'');
}
const w=workspace();w.pick=async()=>['plate.mp4'];w.info=async()=>({frames:120,width:1920,height:1080});
await w.pickSource('footage');assert.equal(w.state.source,'plate.mp4');assert.equal(w.state.frameCount,81);assert.equal(w.state.editorProject,null);assert.equal(w.state.activeMaskSegment,null);assert.equal(w.state.maskSegmentDraft,null);assert.equal(w.state.editorStage,'trim');assert.deepEqual(events.slice(-2),['flush','stage:trim']);assert.deepEqual(messages,[]);
// Replacing footage must still save the old project before opening the picker.
const previous=workspace('old.mp4');events.length=0;
previous.fetch=async()=>({revision:2});previous.editor.project='old';previous.editor.projectSource='old.mp4';
await previous.pickSource('footage');assert.deepEqual(events,['flush','ensure','pick:footage']);assert.equal(previous.state.source,'old.mp4','Cancelling preserves the existing source');
previous.editor.flushManual=async()=>{throw Error('Could not save mask');};events.length=0;messages.length=0;
await previous.pickSource('footage');assert.deepEqual(events,[]);assert.deepEqual(messages,['Could not save mask'],'Failed saves still prevent replacement');
const handoff=workspace();handoff.state.mode='full';handoff.editor.persist=async()=>{};let handoffRequest;
handoff.fetch=async(path,body)=>{handoffRequest={path,body};return {path:'C:/comfy/input/genj_studio/hdr.mov',kind:'video',frames:96,width:1920,height:1080,fps:24,colour_space:'hlg_rec2020'};};
await handoff.importStudioHDR('asset-123','hlg_rec2020','EXR + HLG video');
assert.equal(handoffRequest.path,'/zura/studio/assets/asset-123/paintout');assert.equal(handoffRequest.body.colour_space,'hlg_rec2020');assert.equal(handoff.state.source,'C:/comfy/input/genj_studio/hdr.mov');assert.equal(handoff.state.processingSpace,'HDR (ACEScct)');assert.equal(handoff.state.sourceColour,'hlg_rec2020');assert.equal(handoff.state.outputMode,'EXR + HLG video');assert.equal(handoff.state.frameCount,81);
const hdrRef={type:'output',subfolder:'genj/hdr',filename:'converted.mp4'};
await handoff.importStudioHDROutput(hdrRef,'HLG video');assert.equal(handoffRequest.path,'/zura/studio/hdr/output/paintout');assert.deepEqual(handoffRequest.body,{output_ref:hdrRef});assert.equal(handoff.state.outputMode,'HLG video');
handoff.fetch=async()=>{throw Error('Output is unavailable');};await assert.rejects(()=>handoff.importStudioHDROutput(hdrRef,'HLG video'),/unavailable/);assert.equal(handoff.state.source,'C:/comfy/input/genj_studio/hdr.mov','A failed handoff retains the current source');
const cancelling=workspace('old.mp4'),cancelCalls=[];let active=true;messages.length=0;
cancelling.job={id:'running',started:Date.now(),stages:{sample:'Sampling'}};cancelling.stopPolling=()=>{};
cancelling.fetch=async(path,body)=>{cancelCalls.push({path,body});if(path.startsWith('/history/'))return {};if(path==='/queue'&&!body)return {queue_running:active?[[0,'running']]:[],queue_pending:[]};return {};};
await cancelling.cancel();assert.equal(cancelling.job.cancelPending,true);assert.match(cancelling.$('progress-title').textContent,/Cancelling/);cancelling.updateProgress({prompt_id:'running',node:'sample',value:8,max:8});assert.match(cancelling.$('progress-title').textContent,/Cancelling/);await cancelling.cancel();assert.equal(cancelCalls.filter(c=>c.path==='/interrupt').length,1);active=false;await cancelling.poll();assert.equal(cancelling.job,null);assert.match(messages.at(-1),/left ComfyUI’s queue/);

const hdrConfig={mode:'targeted',source:'C:/test/hdr.mp4',mask:'C:/test/mask.png',anchors:[{file:'C:/test/frame.exr',frame:0}],startFrame:0,frameCount:9,sourceColour:'hlg_rec2020',processingSpace:'HDR (ACEScct)',colourPipeline:'hdr_hdr',width:128,height:64,outputMode:'EXR + HLG video'};
const required={};for(const n of Object.values(buildPaintoutGraph(hdrConfig)))required[n.class_type]={input:{required:{},optional:{}}};
for(const [type,key,values] of [['UNETLoader','unet_name',[PAINTOUT_MODELS.model]],['CLIPLoader','clip_name',[PAINTOUT_MODELS.text]],['VAELoader','vae_name',[PAINTOUT_MODELS.hdrVideoVae,PAINTOUT_MODELS.audioVae]],['LoraLoaderModelOnly','lora_name',[PAINTOUT_MODELS.targetedLora]],['KSampler','scheduler',['linear_quadratic']]])required[type].input.required[key]=[values];
required.LTXAddVideoICLoRAGuideAdvanced.input.optional.use_streaming=['BOOLEAN'];
assert.equal(paintoutAvailability(required,'targeted',hdrConfig).ready,true);
assert.equal(buildPaintoutGraph(hdrConfig,required).video_vae.inputs.vae_name,PAINTOUT_MODELS.hdrVideoVae,'Native HDR now uses the updated standalone non-convolutional VAE path');
assert.equal(paintoutAvailability(required,'targeted',{}).ready,false,'HDR VAE does not claim SDR readiness');
required.VAELoader.input.required.vae_name[0].push(PAINTOUT_MODELS.videoVae);
assert.equal(buildPaintoutGraph({...hdrConfig,sourceColour:'srgb_display',processingSpace:'SDR (sRGB)',colourPipeline:'sdr_sdr',outputMode:'SDR video'},required).video_vae.inputs.vae_name,PAINTOUT_MODELS.videoVae);

const {document}=parseHTML('<html><head></head><body></body></html>');let extension;const opened=[];
const code=fs.readFileSync(new URL('../web/studio_launchers.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replaceAll('import.meta.url',JSON.stringify(new URL('../web/studio_launchers.js',import.meta.url).href));
vm.runInNewContext(code,{document,URL,console,app:{registerExtension:e=>extension=e},openZuraStudio:()=>opened.push('zura'),openPaintout:()=>opened.push('paintout')});
extension.setup();extension.setup();assert.equal(document.querySelectorAll('#zura-studio-shortcuts').length,1,'Setup is idempotent');
const buttons=[...document.querySelectorAll('#zura-studio-shortcuts button')];assert.deepEqual(buttons.map(b=>b.textContent),['Zura Studio','Paintout Studio']);
for(const button of buttons)await button.onclick();assert.deepEqual(opened,['zura','paintout']);
assert.equal(document.querySelectorAll('link[href$="studio_launchers.css"]').length,1);
console.log('PASS: first footage/sequence import, cancellation, prior-project save and visible Studio shortcuts.');

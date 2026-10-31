import assert from 'node:assert/strict';
import fs from 'node:fs';
import {buildPaintoutGraph,buildPaintoutRepairGraph,buildPaintoutHDRGraph,paintoutValidation,paintoutAvailability,PAINTOUT_MODELS,paintoutHDRFrameLimit} from '../../web/paintout_studio/paintout_recipes.js';
const common={mode:'full',source:'C:/fixtures/plate.mp4',startFrame:0,frameCount:9,sequenceFps:24000/1001,sourceWidth:125,sourceHeight:73,width:128,height:128,seed:42};
const sdr=buildPaintoutGraph({...common,colourPipeline:'sdr_sdr',sourceColour:'srgb_display',outputMode:'SDR video'});
assert.ok(!sdr.hdr_sample);assert.equal(sdr.source.inputs.processing_mode,'SDR (sRGB)');
const hdr=buildPaintoutGraph({...common,colourPipeline:'hdr_hdr',sourceColour:'hlg_rec2020',outputMode:'EXR + HLG video'});
assert.ok(!hdr.hdr_sample);assert.equal(hdr.source.inputs.processing_mode,'HDR (ACEScct)');assert.equal(hdr.video_vae.inputs.vae_name,PAINTOUT_MODELS.hdrVideoVae);
const converted=buildPaintoutGraph({...common,colourPipeline:'sdr_hdr',sourceColour:'srgb_display',outputMode:'EXR + HLG video'});
assert.equal(converted.colour_check.inputs.sampling_mode,'tiled_fusion');assert.equal(converted.repair_save.inputs.export_format,'EXR sequence');assert.equal(converted.hdr_lora.inputs.lora_name,PAINTOUT_MODELS.hdrLora);assert.deepEqual(converted.hdr_lora.inputs.model,['hdr_model',0]);assert.equal(converted.save.class_type,'ZuraPaintoutHDRSave');assert.equal(converted.hdr_sampler.inputs.sampler_name,'euler');assert.deepEqual(converted.hdr_guide.inputs.vae,['hdr_vae',0]);assert.deepEqual(converted.source.inputs.plate_path,['colour_check',0]);
assert.match(paintoutValidation({...common,colourPipeline:'sdr_sdr',sourceColour:'hlg_rec2020'}),/HDR footage/);
assert.match(paintoutValidation({...common,colourPipeline:'hdr_hdr',sourceColour:'srgb_display',outputMode:'HLG video'}),/needs HLG/);
assert.equal(paintoutValidation({...common,colourPipeline:'sdr_hdr',sourceColour:'srgb_display',outputMode:'HLG video',sourceWidth:1920,sourceHeight:1080,width:1920,height:1088,frameCount:81}),'');
assert.equal(paintoutHDRFrameLimit({sourceWidth:1920,sourceHeight:1080}),121);
assert.equal(paintoutHDRFrameLimit({sourceWidth:640,sourceHeight:360}),121);
assert.equal(paintoutHDRFrameLimit({sourceWidth:4096,sourceHeight:4096}),0);
assert.match(paintoutValidation({...common,frameCount:122,colourPipeline:'sdr_hdr',sourceColour:'srgb_display',outputMode:'HLG video'}),/supports 121 frames/);
const conversionConfig={...common,colourPipeline:'sdr_hdr',sourceColour:'srgb_display',outputMode:'EXR + HLG video'};
const repair=buildPaintoutRepairGraph(conversionConfig);
assert.ok(repair.repair_save);assert.ok(!repair.hdr_prepare);assert.ok(!repair.save);
const standalone=buildPaintoutHDRGraph(conversionConfig,'C:/fixtures/repaired/frames');
assert.equal(converted.hdr_prepare.inputs.release_models,true);assert.ok(!standalone.hdr_prepare.inputs.release_models);
assert.equal(standalone.hdr_resume.class_type,'ZuraPaintoutHDRResume');
assert.deepEqual(standalone.hdr_prepare.inputs.saved_sequence,['hdr_resume',0]);
assert.deepEqual(standalone.hdr_prepare.inputs.plate,['hdr_resume',1]);
assert.ok(!standalone.source);assert.ok(!standalone.audio_vae);assert.ok(!standalone.text);
for(const graph of [converted,standalone]){
 assert.equal(graph.hdr_prepare.inputs.sampling_mode,'tiled_fusion');
 assert.equal(graph.hdr_guide.inputs.use_streaming,true);assert.equal(graph.hdr_guide.inputs.use_tiled_encode,false);
 assert.deepEqual(graph.hdr_guide.inputs.tile_frames,['hdr_prepare',6]);
 assert.deepEqual(graph.hdr_sample.inputs.tile_frames,graph.hdr_guide.inputs.tile_frames);
 assert.equal(graph.hdr_sample.class_type,'LTXVTiledFusionSampler');assert.equal(graph.hdr_sample.inputs.canvas_device,'cpu');
 assert.deepEqual(graph.hdr_sample.inputs.latents,['hdr_guide',2]);assert.deepEqual(graph.hdr_decode.inputs.samples,['hdr_sample',0]);
 for(const obsolete of ['hdr_audio','hdr_av','hdr_separate','hdr_crop','hdr_guider','hdr_noise'])assert.ok(!graph[obsolete]);
 for(const [id,node] of Object.entries(graph))for(const value of Object.values(node.inputs))if(Array.isArray(value)&&typeof value[0]==='string')assert.ok(graph[value[0]],`${id}: dangling ${value[0]}`);
}
assert.throws(()=>buildPaintoutHDRGraph(conversionConfig,'relative'),/checkpoint/);
const info=process.env.PAINTOUT_GRAPH_LIVE_INFO?await (await fetch(process.env.PAINTOUT_GRAPH_LIVE_INFO.replace(/\/$/,'')+'/object_info')).json():{};
if(info.ZuraPaintoutColourCheck)info.ZuraPaintoutColourCheck.input.optional={...info.ZuraPaintoutColourCheck.input.optional,sampling_mode:[['whole_clip','tiled_fusion']]};
if(process.env.PAINTOUT_GRAPH_LIVE_INFO){
 const live=await (await fetch(process.env.PAINTOUT_GRAPH_LIVE_INFO.replace(/\/$/,'')+'/object_info')).json();
 Object.assign(info,live);
 for(const graph of [sdr,hdr,converted,standalone,repair])for(const node of Object.values(graph))assert.ok(info[node.class_type],`Missing live node ${node.class_type}`);
}
const targeted={...common,mode:'targeted',mask:'C:/fixtures/mask.mp4',anchors:[{file:'C:/fixtures/guide.exr',frame:0,strength:.75,enabled:true,colour_space:'srgb_display'}]};
const block64=buildPaintoutGraph({...targeted,maskBlockSize:64});
assert.equal(block64.block_mask.inputs.block_size,64);
assert.deepEqual(block64.invert_mask.inputs.mask,['block_mask',0]);
const noBlocks=buildPaintoutGraph({...targeted,maskBlockSize:0});
assert.ok(!noBlocks.block_mask);
assert.deepEqual(noBlocks.invert_mask.inputs.mask,['grow_mask',0]);
assert.equal(noBlocks.grow_mask.inputs.expand,32,'guidance expansion is independent of block size');
assert.equal(noBlocks.save.class_type,'ZuraPaintoutUncrop');
assert.deepEqual(noBlocks.save,block64.save,'blockification must not change final compositor');
assert.equal(noBlocks.source.inputs.repair_grow,block64.source.inputs.repair_grow,'blockification must not change final repair boundary');
for(const maskBlockSize of [-1,7,513,8.5])assert.match(paintoutValidation({...targeted,maskBlockSize}),/Mask block size/);
const noBlockNode=structuredClone(info);delete noBlockNode.BlockifyMask;
assert.ok(!paintoutAvailability(noBlockNode,'targeted',{maskBlockSize:0}).missing.includes('BlockifyMask'));
assert.ok(paintoutAvailability(noBlockNode,'targeted',{maskBlockSize:32}).missing.includes('BlockifyMask'));
for(const g of [sdr,hdr,converted,standalone,repair])for(const [id,n]of Object.entries(g)){
 const schema=info[n.class_type];if(!schema)continue;
 const fields={...schema.input?.required,...schema.input?.optional};
 for(const key of Object.keys(schema.input?.required||{}))assert.ok(key in n.inputs,`${id}: missing ${key}`);
 for(const key of Object.keys(n.inputs))assert.ok(key in fields,`${id}: unknown ${key}`);
}
const missing=structuredClone(info);missing.ZuraPaintoutHDRConditioning={input:{required:{file_name:['COMBO',{options:[PAINTOUT_MODELS.hdrEmbeddings]}]}}};missing.ZuraPaintoutHDRConditioning.input.required.file_name=['COMBO',{options:[]}];
assert.ok(paintoutAvailability(missing,'full',{colourPipeline:'sdr_hdr'}).missing.includes(PAINTOUT_MODELS.hdrEmbeddings));assert.ok(!paintoutAvailability(missing,'full',{colourPipeline:'sdr_sdr'}).missing.includes(PAINTOUT_MODELS.hdrEmbeddings));
console.log('PASS three colour pipeline graphs, native input schemas, true HDR adapter isolation, float32 VAE links and bounded preflight');

assert.deepEqual(standalone.hdr_model.inputs.unet_name,['hdr_prepare',7]);
assert.ok(!standalone.model,'no independent model branch may run before checkpoint validation');
assert.deepEqual(converted.hdr_model.inputs.unet_name,['hdr_prepare',7]);

// ComfyUI returns relative model paths when files live in a subfolder.
const nestedInfo=structuredClone(info);
const nestedFields=[['UNETLoader','unet_name',[PAINTOUT_MODELS.model]],['CLIPLoader','clip_name',[PAINTOUT_MODELS.text]],['VAELoader','vae_name',[PAINTOUT_MODELS.videoVae,PAINTOUT_MODELS.hdrVideoVae,PAINTOUT_MODELS.audioVae]],['LoraLoaderModelOnly','lora_name',[PAINTOUT_MODELS.targetedLora]],['LTXICLoRALoaderModelOnly','lora_name',[PAINTOUT_MODELS.fullLora,PAINTOUT_MODELS.hdrLora]],['ZuraPaintoutHDRConditioning','file_name',[PAINTOUT_MODELS.hdrEmbeddings]]];
for(const [type,key,files]of nestedFields){nestedInfo[type]??={};nestedInfo[type].input??={};nestedInfo[type].input.required??={};nestedInfo[type].input.required[key]=['COMBO',{options:files.map(file=>'paintout/'+file)}];}
for(const pipeline of ['sdr_sdr','hdr_hdr','sdr_hdr']){
 const cfg={...common,colourPipeline:pipeline,sourceColour:pipeline==='hdr_hdr'?'hlg_rec2020':'srgb_display',outputMode:pipeline==='sdr_sdr'?'SDR video':'HLG video'};
 const graph=buildPaintoutGraph(cfg,nestedInfo);
 assert.equal(graph.model.inputs.unet_name,'paintout/'+PAINTOUT_MODELS.model);
 assert.equal(graph.text.inputs.clip_name,'paintout/'+PAINTOUT_MODELS.text);
 assert.equal(graph.lora.inputs.lora_name,'paintout/'+PAINTOUT_MODELS.fullLora);
 assert.equal(graph.video_vae.inputs.vae_name,'paintout/'+(pipeline==='hdr_hdr'?PAINTOUT_MODELS.hdrVideoVae:PAINTOUT_MODELS.videoVae));
 for(const file of Object.values(PAINTOUT_MODELS))assert.ok(!paintoutAvailability(nestedInfo,'full',cfg).missing.includes(file),'nested model recognised: '+file);
}
const nestedRepair=buildPaintoutRepairGraph(conversionConfig,nestedInfo),nestedHDR=buildPaintoutHDRGraph(conversionConfig,'C:/fixtures/repaired/frames',nestedInfo);
assert.equal(nestedRepair.model.inputs.unet_name,'paintout/'+PAINTOUT_MODELS.model);
assert.equal(nestedHDR.hdr_prepare.inputs.model_name,'paintout/'+PAINTOUT_MODELS.model);
assert.equal(nestedHDR.hdr_lora.inputs.lora_name,'paintout/'+PAINTOUT_MODELS.hdrLora);
assert.equal(nestedHDR.hdr_conditioning.inputs.file_name,'paintout/'+PAINTOUT_MODELS.hdrEmbeddings);
nestedInfo.UNETLoader.input.required.unet_name[1].options.unshift(PAINTOUT_MODELS.model);
assert.equal(buildPaintoutGraph({...common,colourPipeline:'sdr_sdr',sourceColour:'srgb_display',outputMode:'SDR video'},nestedInfo).model.inputs.unet_name,PAINTOUT_MODELS.model,'exact root file preferred when both choices exist');
console.log('PASS existing nested model files are reused by readiness and SDR/HDR repair/conversion graphs');

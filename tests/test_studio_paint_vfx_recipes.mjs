import assert from 'node:assert/strict';
import {buildPaintVfxGraph as build,paintVfxAvailability as available,paintVfxValidation as validate,paintVfxPrompt,PAINT_VFX_ADAPTER as adapter,PAINT_VFX_CAPABILITIES as caps} from '../web/studio_paint_vfx_recipes.js';
import {LTX_FRAME_VIDEO_MODELS as models,LTX_DISTILLED_SIGMAS,buildLtxFrameVideoGraph} from '../web/ltx_frame_video_recipes.js';
const base={width:512,height:512,frames:121,fps:24,prompt:'A billowing orange explosion with thick grey smoke',seed:42,keys:[{frame:120,image:'paint_vfx/last.png'},{frame:0,image:'paint_vfx/first.png'}]};
assert.equal(caps.defaultFrames,121);assert.equal(caps.defaultWidth,512);assert.equal(caps.defaultHeight,512);
const before=structuredClone(base),g=build(base);assert.deepEqual(base,before,'Graph assembly never mutates the source draft');
assert.deepEqual(JSON.parse(g.control.inputs.keys),[base.keys[1],base.keys[0]]);
assert.equal(g.adapter.inputs.lora_name,adapter.file);assert.equal(g.adapter.inputs.strength_model,1);
assert.deepEqual(g.guide.inputs.latent_downscale_factor,['adapter',1],'Use the adapter-reported factor, expected 2, rather than a guessed constant');
assert.deepEqual(g.guide.inputs.image,['control',0]);assert.deepEqual(g.guider.inputs.model,['attention',0]);
assert.deepEqual(g.av_latent.inputs.video_latent,['guide',2]);assert.deepEqual(g.crop_guides.inputs.positive,['guide',0]);
assert.equal(g.guider.inputs.cfg,1);assert.equal(g.sigmas.inputs.sigmas,LTX_DISTILLED_SIGMAS);assert.equal(g.sampler.inputs.sampler_name,'euler_ancestral');
assert.equal(g.video.inputs.bit_depth,8);assert.equal(g.video.inputs.color_space,'sRGB');assert.equal(g.save.class_type,'ZuraSaveProRes4444');
assert.ok(!Object.values(g).some(node=>/Alpha|ImgToVideo|Ripple/.test(node.class_type)),'No implicit alpha or unrelated endpoint propagation');
for(const fps of [24,25,50])assert.equal(build({...base,fps}).conditioning.inputs.frame_rate,fps);
assert.equal(paintVfxPrompt('ainvfxfluid, ainvfxfluid, smoke plume'),'ainvfxfluid, smoke plume');
assert.equal((build({...base,prompt:'ainvfxfluid smoke plume'}).positive.inputs.text.match(/ainvfxfluid/g)||[]).length,1);
const endpoint=buildLtxFrameVideoGraph({width:512,height:512,frames:121,fps:24,first:{file:'first.png'},prompt:'Smoke',seed:42});
for(const id of ['sampler','sigmas','noise','decode','decode_audio'])assert.deepEqual(g[id].inputs,endpoint[id].inputs,`Reuse the signed-off LTX sampler/decode contract: ${id}`);
for(const [override,pattern] of [[{width:544},/64-pixel/],[{frames:120},/8n/],[{fps:30},/24, 25 or 50/],[{prompt:'ainvfxfluid'},/Describe/],[{seed:-1},/seed/],[{steps:12},/eight-step/],[{keys:[null,null]},/unique/],[{alpha:true},/separate/],[{fast:true},/single-stage/],[{keys:[{frame:0,image:'a.png'}]},/first and last/],[{keys:[...base.keys,{frame:8,image:'a.png'}]},/1 \+ 8n/],[{keys:[...base.keys,{frame:1,image:'../escape.png'}]},/input folder/],[{keys:[...base.keys,{frame:0,image:'same.png'}]},/unique/],[{width:1920,height:1920,frames:321},/512 MiB/]])assert.match(validate({...base,...override}),pattern);
assert.equal(validate({...base,width:960,height:512,frames:81,keys:[{frame:0,image:'a.png'},{frame:1,image:'b.png'},{frame:73,image:'c.png'},{frame:80,image:'d.png'}]}),'');
assert.match(validate({...base,frames:321,width:256,height:256,keys:Array.from({length:34},(_,i)=>({frame:i?1+(i-1)*8:0,image:'a.png'}))}),/33/);
// Every graph connection is present and carries the consumer's expected type.
const types={ZuraPaintKeyframeVideo:['IMAGE'],UNETLoader:['MODEL'],LTXICLoRALoaderModelOnly:['MODEL','INT'],ModelAttentionBackend:['MODEL'],CLIPLoader:['CLIP'],CLIPTextEncode:['CONDITIONING'],VAELoader:['VAE'],LTXVConditioning:['CONDITIONING','CONDITIONING'],EmptyLTXVLatentVideo:['LATENT'],LTXAddVideoICLoRAGuide:['CONDITIONING','CONDITIONING','LATENT'],LTXVEmptyLatentAudio:['LATENT'],LTXVConcatAVLatent:['LATENT'],CFGGuider:['GUIDER'],KSamplerSelect:['SAMPLER'],ManualSigmas:['SIGMAS'],RandomNoise:['NOISE'],SamplerCustomAdvanced:['LATENT','LATENT'],LTXVSeparateAVLatent:['LATENT','LATENT'],LTXVCropGuides:['CONDITIONING','CONDITIONING','LATENT'],VAEDecodeTiled:['IMAGE'],LTXVAudioVAEDecode:['AUDIO'],CreateVideo:['VIDEO'],ZuraSaveProRes4444:[]};
const expected={model:'MODEL',clip:'CLIP',positive:'CONDITIONING',negative:'CONDITIONING',vae:'VAE',audio_vae:'VAE',latent:'LATENT',image:'IMAGE',latent_downscale_factor:'INT',video_latent:'LATENT',audio_latent:'LATENT',noise:'NOISE',guider:'GUIDER',sampler:'SAMPLER',sigmas:'SIGMAS',latent_image:'LATENT',av_latent:'LATENT',samples:'LATENT',images:'IMAGE',audio:'AUDIO',video:'VIDEO'};
for(const [id,node]of Object.entries(g))for(const [field,value]of Object.entries(node.inputs))if(Array.isArray(value)){
  assert.ok(g[value[0]],`${id}.${field} has a missing producer`);assert.equal(types[g[value[0]].class_type]?.[value[1]],expected[field],`${id}.${field} type`);
}
const info=Object.fromEntries(caps.nodeTypes.map(node=>[node,{input:{required:{}}}]));
info.UNETLoader.input.required.unet_name=[[models.model]];info.CLIPLoader.input.required.clip_name=[[models.text]];info.CLIPLoader.input.required.type=[['ltxv']];info.VAELoader.input.required.vae_name=[[models.videoVae,models.audioVae]];info.LTXICLoRALoaderModelOnly.input.required.lora_name=[['effects/'+adapter.file]];info.KSamplerSelect.input.required.sampler_name=[['euler_ancestral']];
assert.equal(available(info).ready,true);const portable=build(base,info);assert.equal(portable.attention,undefined);assert.deepEqual(portable.guider.inputs.model,['adapter',0]);assert.equal(portable.adapter.inputs.lora_name,'effects/'+adapter.file);
delete info.ZuraPaintKeyframeVideo;assert.ok(available(info).missing.includes('ZuraPaintKeyframeVideo'));info.LTXICLoRALoaderModelOnly.input.required.lora_name=[[]];assert.ok(available(info).missing.includes(adapter.file));
assert.equal(adapter.sha256.length,64);assert.equal(adapter.size,654446320);assert.match(adapter.url,/resolve\/[0-9a-f]{40}\//);assert.match(adapter.license,/Community/);
console.log('Paint VFX: exact sparse-control graph, typed edges, model readiness, resource limits, sampler baseline and source isolation pass.');

import assert from 'node:assert/strict';
import {
  DIRECTOR_ENGINES,
  directorFrameCount,
  directorAvailability,
  buildDirectorGraph,
  validateDirectorGraph,
} from '../web/director_recipes.js';
import {FRAME_VIDEO_MODELS} from '../web/frame_video_recipes.js';
import {LTX_FRAME_VIDEO_MODELS} from '../web/ltx_frame_video_recipes.js';

assert.deepEqual(DIRECTOR_ENGINES.map(item=>item.id),['ltx','h3']);
assert.equal(directorFrameCount('ltx',10),17);
assert.equal(directorFrameCount('ltx',361),361);
assert.equal(directorFrameCount('h3',23),39);
assert.equal(directorFrameCount('h3',362),362);
assert.throws(()=>directorFrameCount('h3',363),/up to 362/);
assert.throws(()=>buildDirectorGraph({
  engine:'h3',prompt:'x',width:1344,height:768,frames:22,steps:40,clips:[],
}),/between 8 and 8/);

const clips=[
  {id:'anchor',kind:'image',startFrame:0,endFrame:1,asset:{file:'inputs/frame.png'},text:'opening'},
  {id:'shot',kind:'prompt',startFrame:1,endFrame:10,text:'The camera moves left.'},
  {id:'audio',kind:'audio',startFrame:0,endFrame:10,asset:{file:'inputs/voice.wav'}},
];
const ltx=buildDirectorGraph({
  engine:'ltx',prompt:'A studio sequence.',globalPrompt:'Consistent studio lighting.',
  width:960,height:544,frames:10,startFrame:0,steps:8,seed:42,clips,
},{
  ModelAttentionBackend:{input:{required:{attention:[['comfy kitchen attention']]}}},
});
assert.deepEqual(ltx.director.inputs.model,['attention',0]);
assert.equal(ltx.director.inputs.end_frame,17);
assert.equal(ltx.positive,undefined,'LTX timeline conditioning comes from LTXDirector, not a dead CLIPTextEncode branch');
assert.deepEqual(ltx.guide.inputs.positive,['director',1]);
assert.deepEqual(ltx.guider.inputs.model,['guide',3]);
assert.deepEqual(ltx.guider.inputs.positive,['guide',0]);
const ltxTimeline=JSON.parse(ltx.director.inputs.timeline_data);
assert.equal(ltxTimeline.segments[0].start,0);
assert.equal(ltxTimeline.segments[0].length,1,'endFrame is exclusive and a one-frame image remains one frame');
assert.equal(ltxTimeline.segments.reduce((sum,segment)=>sum+segment.length,0),17);
assert.equal(ltxTimeline.segments.find(segment=>segment.type==='image').imageFile,'inputs/frame.png');
assert.equal(ltxTimeline.audioSegments[0].length,10);
assert.equal(ltx.director.inputs.local_prompts.split(' | ').length,ltxTimeline.segments.length);
assert.equal(ltx.director.inputs.segment_lengths.split(',').reduce((sum,value)=>sum+Number(value),0),17);
assert.doesNotThrow(()=>validateDirectorGraph(ltx));

const uploaded=buildDirectorGraph({
  engine:'ltx',prompt:'Upload response normalisation.',width:960,height:544,frames:9,startFrame:0,clips:[
    {kind:'image',startFrame:0,endFrame:1,asset:{file:'zura_director/response.png',filename:'response.png',subfolder:'zura_director'}},
  ],
});
assert.equal(JSON.parse(uploaded.director.inputs.timeline_data).segments[0].imageFile,'zura_director/response.png','asset.file is already input-relative and is not joined to subfolder twice');

const fallback=buildDirectorGraph({
  engine:'ltx',prompt:'A studio sequence.',width:960,height:544,frames:9,startFrame:0,clips:[],
},{
  ModelAttentionBackend:{input:{required:{attention:[['pytorch attention']]}}},
});
assert.equal(fallback.attention.inputs.attention,'pytorch attention');
assert.deepEqual(fallback.director.inputs.model,['attention',0]);
assert.deepEqual(fallback.guider.inputs.model,['guide',3]);

const pruned=buildDirectorGraph({
  engine:'ltx',prompt:'A studio sequence.',width:960,height:544,frames:9,startFrame:0,clips:[],
},{});
assert.equal(pruned.attention,undefined);
assert.deepEqual(pruned.director.inputs.model,['model',0]);
assert.deepEqual(pruned.guider.inputs.model,['guide',3]);

const h3=buildDirectorGraph({
  engine:'h3',prompt:'A commercial shot.',width:1344,height:768,frames:23,startFrame:12,steps:8,seed:7,
  clips:[
    {id:'a',kind:'image',startFrame:12,endFrame:13,asset:{file:'h3/first.png'}},
    {id:'p',kind:'prompt',startFrame:13,endFrame:23,text:'A close-up.'},
  ],
},{
  ModelAttentionBackend:{input:{required:{attention:[['comfy kitchen attention']]}}},
});
assert.deepEqual(h3.director.inputs.model,['attention',0]);
assert.deepEqual(h3.guider.inputs.model,['director',0]);
assert.deepEqual(h3.scheduler.inputs.model,['director',0]);
assert.deepEqual(h3.guider.inputs.conditioning,['director',1]);
assert.deepEqual(h3.sample.inputs.latent_image,['director',2]);
assert.equal(h3.director.inputs.end_frame,51);
const h3Timeline=JSON.parse(h3.director.inputs.timeline_data);
assert.equal(h3Timeline.normalStartFrame,12);
assert.equal(h3Timeline.segments[0].start,12);
assert.equal(h3Timeline.segments[0].length,1);
assert.equal(h3Timeline.segments.reduce((sum,segment)=>sum+segment.length,0),39);

assert.throws(()=>buildDirectorGraph({
  engine:'h3',prompt:'x',width:1344,height:768,frames:22,clips:[
    {kind:'image',startFrame:0,endFrame:2,asset:{file:'a.png'}},
    {kind:'image',startFrame:1,endFrame:2,asset:{file:'b.png'}},
  ],
}),/cannot overlap/);
assert.throws(()=>buildDirectorGraph({
  engine:'ltx',prompt:'x',width:960,height:544,frames:9,clips:[
    {kind:'image',startFrame:0,endFrame:2,asset:{file:'../secret.png'}},
  ],
}),/input-relative/);

const readyInfo={};
for(const node of ['UNETLoader','CLIPLoader','LoraLoaderModelOnly','VAELoader','MiniMaxH3DirectorCS',
  'BasicGuider','BasicScheduler','KSamplerSelect','VAEDecode','VAEDecodeAudio','RandomNoise',
  'SamplerCustomAdvanced','CreateVideo','SaveVideo']){
  readyInfo[node]={input:{required:{},optional:{}}};
}
readyInfo.UNETLoader.input.required.unet_name=[['other.safetensors',FRAME_VIDEO_MODELS.model]];
readyInfo.CLIPLoader.input.required.clip_name=[['other.safetensors',FRAME_VIDEO_MODELS.text]];
readyInfo.LoraLoaderModelOnly.input.required.lora_name=[['other.safetensors',FRAME_VIDEO_MODELS.lora]];
readyInfo.VAELoader.input.required.vae_name=[['other.safetensors',FRAME_VIDEO_MODELS.videoVae,FRAME_VIDEO_MODELS.audioVae]];
assert.equal(directorAvailability(readyInfo,{engine:'h3'}).ready,true);
readyInfo.MiniMaxH3DirectorCS={python_module:'custom_nodes.wrong-h3-director',input:{required:{},optional:{}}};
const wrongOwner=directorAvailability(readyInfo,{engine:'h3'});
assert.equal(wrongOwner.ready,false);
assert.equal(wrongOwner.wrongOwners[0].loaded,'custom_nodes.wrong-h3-director');
assert.throws(()=>buildDirectorGraph({
  engine:'h3',prompt:'x',width:1344,height:768,frames:22,clips:[],
},readyInfo),/expected custom_nodes\.minimaxh3-director/);
delete readyInfo.MiniMaxH3DirectorCS;
const missing=directorAvailability(readyInfo,{engine:'h3'});
assert.equal(missing.ready,false);
assert.deepEqual(missing.missingNodes,['MiniMaxH3DirectorCS']);

const ltxReady={};
for(const node of ['UNETLoader','CLIPLoader','VAELoader','CLIPTextEncode','LTXDirector','LTXDirectorGuide',
  'LTXVConcatAVLatent','CFGGuider','ManualSigmas','KSamplerSelect','LTXVSeparateAVLatent','LTXVCropGuides',
  'VAEDecodeTiled','LTXVAudioVAEDecode','RandomNoise','SamplerCustomAdvanced','CreateVideo','SaveVideo']){
  ltxReady[node]={input:{required:{},optional:{}}};
}
ltxReady.UNETLoader.input.required.unet_name=[[LTX_FRAME_VIDEO_MODELS.model]];
ltxReady.CLIPLoader.input.required.clip_name=[[LTX_FRAME_VIDEO_MODELS.text]];
ltxReady.VAELoader.input.required.vae_name=[[LTX_FRAME_VIDEO_MODELS.videoVae,LTX_FRAME_VIDEO_MODELS.audioVae]];
assert.equal(directorAvailability(ltxReady,{engine:'ltx'}).ready,true);

console.log('Director frame grids, exclusive clip ranges, native timeline payloads, attention patch routing, node pruning, reference validation and model availability pass.');

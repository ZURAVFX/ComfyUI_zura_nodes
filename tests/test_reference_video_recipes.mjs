import assert from 'node:assert/strict';
import {
  REFERENCE_VIDEO_CAPABILITIES as caps,
  REFERENCE_VIDEO_MODELS as models,
  buildReferenceVideoGraph,
  nextReferenceVideoFrameCount,
  referencePromptTags,
  referenceVideoAvailability,
  referenceVideoDimensions,
  referenceVideoFrames,
} from '../web/reference_video_recipes.js';

const config={
  images:[
    {file:'refs/person.png',name:'Person'},
    {file:'refs/jacket.png',name:'Jacket'},
  ],
  videos:[{
    file:'refs/room.mp4',
    name:'Room',
    audioFile:'refs/room.wav',
    start:1.5,
    duration:4,
  }],
  audios:[{file:'refs/voice.wav',name:'Voice',duration:8}],
  prompt:'The person from the pictures talks in the room.',
  width:1344,
  height:768,
  frames:124,
  seed:42,
  steps:8,
};

const tags=referencePromptTags(config);
assert.deepEqual(tags.map(item=>item.tag),[
  '<Picture 1>','<Picture 2>','<Audio 1>','<Video 1>','<Audio 2>',
]);

const graph=buildReferenceVideoGraph(config);
assert.equal(graph.model.inputs.unet_name,models.ref2va);
assert.equal(graph.model.inputs.weight_dtype,'default');
assert.equal(graph.turbo.inputs.lora_name,models.turbo);
assert.equal(graph.turbo.inputs.strength_model,1);
assert.equal(graph.attention.inputs.attention,'comfy kitchen attention');
assert.deepEqual(graph.shift.inputs,{
  model:['attention',0],shift_video:12,shift_audio:6,
});
assert.equal(graph.scheduler.inputs.steps,8);
assert.equal(graph.scheduler.inputs.scheduler,'simple');
assert.equal(graph.sampler.inputs.sampler_name,'res_multistep');
assert.equal(graph.text.inputs.type,'minimax');
assert.equal(graph.video_vae.inputs.vae_name,models.videoVae);
assert.equal(graph.audio_vae.inputs.vae_name,models.audioVae);
assert.equal(graph.image_1.inputs.image,'refs/person.png');
assert.equal(graph.image_2.inputs.image,'refs/jacket.png');
assert.equal(graph.video_1.inputs.file,'refs/room.mp4');
assert.equal(graph.video_window_1.class_type,'Video Slice');
assert.deepEqual(graph.video_window_1.inputs,{video:['video_1',0],start_time:1.5,duration:4,strict_duration:false});
assert.deepEqual(graph.components_1.inputs.video,['video_window_1',0]);
assert.equal(graph.reference_video_1.inputs.start_seconds,0);
assert.equal(graph.reference_video_1.inputs.seconds,4);
assert.deepEqual(graph.reference_video_1.inputs.source_fps,['components_1',2]);
assert.deepEqual(graph.reference_video_1.inputs.audio,['video_audio_guard_1',0]);
assert.deepEqual(graph.video_audio_window_1.inputs,{audio:['video_audio_1',0],start_index:1.5,duration:4});
assert.deepEqual(graph.references.inputs['ref_images.ref_image_0'],['image_1',0]);
assert.deepEqual(graph.references.inputs['ref_images.ref_image_1'],['image_2',0]);
assert.deepEqual(graph.references.inputs['ref_videos.ref_video_0'],['reference_video_1',0]);
assert.deepEqual(graph.references.inputs['ref_video_audios.ref_video_audio_0'],['reference_video_1',1]);
assert.deepEqual(graph.references.inputs['ref_audios.ref_audio_0'],['audio_guard_1',0]);
assert.equal(graph.audio_guard_1.inputs.max_seconds,8);
assert.equal(graph.references.inputs.length,124);
assert.equal(graph.video.inputs.fps,24);
assert.equal(graph.save.class_type,'SaveVideo');
assert.ok(Object.values(graph).every(node=>node._meta?.title));
assert.equal(
  graph.references.inputs.prompt,
  'The person from the pictures talks in the room.',
);

const noVideoSound=buildReferenceVideoGraph({
  ...config,
  videos:[{file:'refs/room.mp4',start:0,duration:2.5}],
  audios:[],
});
assert.equal(noVideoSound.reference_video_1.inputs.audio,undefined);
assert.equal(
  Object.keys(noVideoSound.references.inputs)
    .some(key=>key.startsWith('ref_video_audios.')),
  false,
);
assert.equal(
  noVideoSound.references.inputs.prompt,
  'The person from the pictures talks in the room.',
);

const explicitPrompt=buildReferenceVideoGraph({
  ...config,
  prompt:'Use <Picture 2> for the jacket and <Video 1> for the room.',
});
assert.equal(
  explicitPrompt.references.inputs.prompt,
  'Use <Picture 2> for the jacket and <Video 1> for the room.',
);

const spectrum=buildReferenceVideoGraph({...config,spectrum:true});
assert.equal(spectrum.spectrum.inputs.degree,4);
assert.equal(spectrum.spectrum.inputs.warmup_steps,5);
assert.equal(spectrum.spectrum.inputs.offline_smoothing_replay,true);
assert.equal(spectrum.spectrum.inputs.audio_blend_weight,0);

const quality=buildReferenceVideoGraph({...config,speedup:'quality',steps:40});
assert.equal(quality.turbo,undefined);
assert.equal(quality.scheduler.inputs.steps,40);
assert.equal(quality.scheduler.inputs.scheduler,'beta');

const viggle=buildReferenceVideoGraph({
  ...config,model:'viggle',speedup:'quality',steps:40,
});
assert.equal(viggle.model.inputs.unet_name,models.viggle);
assert.equal(viggle.turbo,undefined);

assert.throws(
  ()=>buildReferenceVideoGraph({...config,model:'viggle',speedup:'turbo'}),
  /Viggle/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({...config,spectrum:true,speedup:'quality',steps:40}),
  /Spectrum/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({
    ...config,
    images:Array.from({length:10},(_,index)=>({file:`${index}.png`})),
  }),
  /9 reference images/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({
    ...config,
    videos:Array.from({length:4},(_,index)=>({file:`${index}.mp4`})),
  }),
  /3 reference videos/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({
    ...config,
    audios:Array.from({length:4},(_,index)=>({file:`${index}.wav`})),
  }),
  /3 standalone/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({
    ...config,
    videos:[{file:'v.mp4',duration:16}],
  }),
  /2-15 seconds/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({
    ...config,
    images:[{file:'i.png',frame:12}],
  }),
  /frame positions/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({...config,prompt:'Use <Picture 3>.'}),
  /has 2 picture/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({...config,steps:12}),
  /eight sampling steps/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({...config,images:[],videos:[],audios:[]}),
  /at least one/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({...config,images:[{file:'../escape.png'}]}),
  /path is not valid/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({...config,frames:125}),
  /17k \+ 5/,
);
assert.throws(
  ()=>buildReferenceVideoGraph({...config,width:1504,height:896}),
  /smaller size/,
);
assert.throws(
  ()=>referenceVideoDimensions({width:720,height:1280}),
  /multiples of 32/,
);
assert.equal(referenceVideoFrames({frames:362}),362);
assert.equal(nextReferenceVideoFrameCount(120),124);
assert.equal(nextReferenceVideoFrameCount(125),141);
assert.equal(nextReferenceVideoFrameCount(999),362);
assert.equal(caps.maxImages,9);
assert.equal(caps.maxVideos,3);
assert.equal(caps.maxAudios,3);
assert.equal(caps.maxFrames,362);

const info={};
for(const type of caps.nodeTypes)info[type]={input:{required:{}}};
info.UNETLoader.input.required={
  unet_name:['COMBO',{options:[models.ref2va,models.viggle]}],
  weight_dtype:['COMBO',{options:['default']}],
};
info.CLIPLoader.input.required={
  clip_name:['COMBO',{options:[models.text]}],
  type:['COMBO',{options:['minimax']}],
};
info.VAELoader.input.required={
  vae_name:['COMBO',{options:[models.videoVae,models.audioVae]}],
};
info.LoraLoaderModelOnly.input.required={
  lora_name:['COMBO',{options:[models.turbo]}],
};
info.ModelAttentionBackend.input.required={
  attention:['COMBO',{options:['comfy kitchen attention','pytorch attention']}],
};
info.SpectrumApplyMiniMaxH3={input:{required:{}}};
assert.equal(referenceVideoAvailability(info,config).ready,true);
assert.equal(
  referenceVideoAvailability(info,{...config,spectrum:true}).ready,
  true,
);
assert.equal(
  referenceVideoAvailability(info,{...config,speedup:'quality',steps:40}).ready,
  true,
);
info.LoraLoaderModelOnly.input.required.lora_name=['COMBO',{options:[]}];
assert.deepEqual(
  referenceVideoAvailability(info,config).missing,
  [models.turbo],
);
info.LoraLoaderModelOnly.input.required.lora_name=[[models.turbo]];
assert.equal(
  referenceVideoAvailability(info,config).ready,
  true,
  'Legacy array model schemas also resolve',
);
delete info.H3ReferenceVideo;
assert.ok(
  referenceVideoAvailability(info,config).missing.includes('H3ReferenceVideo'),
);
assert.equal(
  referenceVideoAvailability(info,{...config,videos:[]}).ready,
  true,
  'The video trimmer is optional when no video is linked',
);

console.log(
  'H3 Ref2Video maps image/video/audio roles, trims supported media timing, uses the installed INT8 Ref2VA turbo/Kitchen chain, and reports exact availability.',
);

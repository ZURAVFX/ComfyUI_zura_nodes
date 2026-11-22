import assert from 'node:assert/strict';
import {test} from 'node:test';
import {buildReferenceVideoGraph} from '../web/reference_video_recipes.js';
import {nativeSwitchGraph} from '../web/switch_x_recipe.js';
const cfg={source:'performance.mov',refs:['carriage.jpg'],steps:8,prompt:'Edit <Video 1> using <Picture 1>.',audioMode:'source'};
const src={duration:124/24,width:1024,height:576,hasAudio:false};
test('the preferred visual graph is the native Ref2VA recipe',()=>{
  const expected=buildReferenceVideoGraph({model:'ref2va',speedup:'turbo',width:1024,height:576,
    frames:124,steps:8,seed:42,images:[{file:'carriage.jpg'}],videos:[{file:'performance.mov',start:0,duration:124/24}],prompt:cfg.prompt});
  delete expected.decode_audio;
  delete expected.video.inputs.audio;
  expected.save.inputs.filename_prefix='switch_x_native/Ref2VA-source-video';
  assert.deepEqual(nativeSwitchGraph(cfg,src),expected);
});
test('source or uploaded dialogue reaches both the sampler and video',()=>{
  for(const [options,file] of [[cfg,cfg.source],[{...cfg,audioMode:'upload',audioFile:'dialogue.wav'},'dialogue.wav']]){
    const g=nativeSwitchGraph(options,{...src,hasAudio:true});
    assert.equal(g.video_audio_1.inputs.audio,file);
    assert.deepEqual(g.guider.inputs.conditioning,['vocal_guide',0]);
    assert.deepEqual(g.vocal_guide.inputs.audio,g.video.inputs.audio);
    assert.equal(Object.values(g).filter(n=>n.class_type==='SamplerCustomAdvanced').length,1);
  }
});
test('mute does not synthesize a voice',()=>{
  const g=nativeSwitchGraph({...cfg,audioMode:'mute'},{...src,hasAudio:true});
  assert.equal(g.video.inputs.audio,undefined);
  assert.equal(g.decode_audio,undefined);
  assert.equal(g.vocal_guide,undefined);
});

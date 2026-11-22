import {buildReferenceVideoGraph,nextReferenceVideoFrameCount} from './reference_video_recipes.js';

// Use the same recipe as Studio's Reference to video workspace. Pairing the
// selected soundtrack with its video enables the existing vocal guide.
export function nativeSwitchGraph(config,source){
  if(source.duration>15.05)throw Error('Trim the native H3 reference clip to 15 seconds or less.');
  if(Math.floor(source.duration*24+1e-6)<5)throw Error('Choose at least five H3 frames of reference footage.');
  const file=config.audioMode==='upload'?config.audioFile:
    config.audioMode==='mute'?'':source.hasAudio?config.source:'';
  if(config.audioMode==='upload'&&!file)throw Error('Choose the audio file to drive the performance.');
  const frames=nextReferenceVideoFrameCount(Math.round(source.duration*24));
  const video={file:config.source,start:0,duration:Math.min(15,Math.max(2,source.duration))};
  if(file)video.audioFile=file;
  const graph=buildReferenceVideoGraph({
    model:'ref2va',speedup:Number(config.steps)===40?'quality':'turbo',width:source.width,height:source.height,
    frames,steps:Number(config.steps),seed:42,images:config.refs.map(file=>({file})),videos:[video],
    audioDriver:file?'video:'+config.source:'',prompt:config.prompt.trim()||'Edit <Video 1> using the supplied location and appearance references.',
  });
  if(file){
    graph.vocal_stereo.inputs.max_seconds=Math.min(15,graph.vocal_stereo.inputs.max_seconds);
  }else{
    delete graph.video.inputs.audio;
    delete graph.decode_audio;
  }
  graph.save.inputs.filename_prefix='switch_x_native/Ref2VA-source-video';
  return graph;
}

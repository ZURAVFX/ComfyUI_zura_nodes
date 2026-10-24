import {buildFrameVideoGraph,frameVideoAvailability,FRAME_LENGTHS,FRAME_SIZE_PRESETS,FRAME_MEGAPIXELS} from './frame_video_recipes.js';
import {buildWanFrameVideoGraph,wanFrameVideoAvailability,WAN_FRAME_VIDEO_CAPABILITIES} from './wan_frame_video_recipes.js';
import {buildLtxFrameVideoGraph,ltxFrameVideoAvailability,LTX_FRAME_VIDEO_CAPABILITIES} from './ltx_frame_video_recipes.js';

const h3={id:'h3',label:'MiniMax H3',fps:24,dimensionStep:32,minDimension:256,maxDimension:1536,maxPixels:1344*768,
  minFrames:22,maxFrames:362,frameStep:17,frameOffset:5,defaultFrames:73,defaultSteps:8,minSteps:4,maxSteps:40,
  supportsAudioReference:true,generatesAudio:true,precision:'INT8',
  nodeTypes:['UNETLoader','CLIPLoader','VAELoader','LoraLoaderModelOnly','ModelAttentionBackend','MiniMaxH3ImageToVideo','MiniMaxH3AddGuide','LoadAudio','LoadImage','ImageScale','BasicGuider','BasicScheduler','KSamplerSelect','RandomNoise','SamplerCustomAdvanced','VAEDecode','VAEDecodeAudio','CreateVideo','SaveVideo']};
export const ENDPOINT_RECIPES=[
  {...h3,build:buildFrameVideoGraph,availability:frameVideoAvailability,hint:'INT8 · Turbo 8-step · Kitchen attention'},
  {...WAN_FRAME_VIDEO_CAPABILITIES,build:buildWanFrameVideoGraph,availability:wanFrameVideoAvailability,hint:'FP8 · Lightx2v 4-step · Silent video'},
  {...LTX_FRAME_VIDEO_CAPABILITIES,build:buildLtxFrameVideoGraph,availability:ltxFrameVideoAvailability,hint:'INT8 · Distilled 8-step · Native audio'},
];
export const endpointRecipe=id=>ENDPOINT_RECIPES.find(r=>r.id===id)||ENDPOINT_RECIPES[0];
export function endpointLengths(id){
  const c=endpointRecipe(id);
  if(c.id==='h3')return FRAME_LENGTHS;
  const values=[];for(let n=c.minFrames;n<=c.maxFrames;n+=c.frameStep)values.push(n);
  return values;
}
export function endpointPresetSize(engine,shape,megapixels){
  const c=endpointRecipe(engine),preset=FRAME_SIZE_PRESETS.find(p=>p.id===shape),mp=Number(megapixels);
  if(!preset||!FRAME_MEGAPIXELS.includes(mp))throw new Error('Choose a shape and megapixel size.');
  const width=Math.round(Math.sqrt(mp*1e6*preset.ratio)/c.dimensionStep)*c.dimensionStep;
  const height=Math.round(Math.sqrt(mp*1e6/preset.ratio)/c.dimensionStep)*c.dimensionStep;
  return {width,height};
}

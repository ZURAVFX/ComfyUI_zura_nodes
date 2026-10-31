// Shared dependency guidance. Opening setup never installs or updates extensions.
export const NODE_PACKS=[
  {name:'Zura Nodes',url:'https://github.com/ZURAVFX/ComfyUI_zura_nodes',nodes:['GenjSelectClip','GenjLoadReviewedShot','GenjHoldImages','GenjHoldToModelLength','GenjPadAudioToFrames','GenjRestoreSoundtrack','GenjLTXFramePad','GenjApplyReferenceAudio','GenjH3FramePad','GenjH3ViewportFrameData','GenjSaveH3Conditioning','GenjLoadH3Conditioning','ZuraHDRWriteChunk','ZuraHDRReadChunkAnchor','ZuraHDRPadSDRAnchor','ZuraHDRNativePrepare','ZuraHDRLoadNativeSource','ZuraHDRCompositeOutpaint','ZuraHDRLoadSDRSource','ZuraHDRLoadAudioRange','ZuraHDRLoadTimedAudio','ZuraHDRPackageACEScct','ZuraHDRPackageEXR','ZuraHDRSaveExactRate','ZuraHDRSelectNativeTimeline','ZuraHDRTemporalHold','ZuraHDRTrimAudio','ZuraHDRTemporalDecodeCut','ZuraLTXHDRPrepare','ZuraLTXOutpaintCanvas','ZuraLTXOutpaintHDRCanvas','ZuraOutpaintTemporalHold','ZuraOutpaintReviewOverlay'],note:'Update Zura Nodes and restart ComfyUI to load the required nodes.'},
  {name:'ComfyUI',url:'https://github.com/Comfy-Org/ComfyUI',nodes:['LTXVImgToVideoInplace','LTXVAddGuide','UNETLoader','CLIPLoader','CLIPTextEncode','VAELoader','LoadImage','ImageScale','ImageFromBatch','GrowMask','InvertMask','ReferenceMultiLatent','CheckpointLoaderSimple','SAM3_Detect','SAM3_VideoTrack','ModelAttentionBackend','LTXVConditioning','EmptyLTXVLatentVideo','LTXVEmptyLatentAudio','LTXVConcatAVLatent','LTXVSeparateAVLatent','LTXVCropGuides','LTXVAudioVAELoader','LTXVAudioVAEEncode','LTXVAudioVAEDecode','LTXVLatentUpsampler','KSampler','KSamplerSelect','RandomNoise','CFGGuider','BasicGuider','SamplerCustomAdvanced','VAEDecode','VAEDecodeTiled','LoadAudio','CreateVideo','SaveVideo','MiniMaxH3ImageToVideo','MiniMaxH3ReferenceToVideo','MiniMaxH3AddGuide','EmptyMiniMaxH3LatentAV','MiniMaxH3SigmaShift'],note:'Update ComfyUI and restart it to load these built-in nodes.'},
  {name:'ComfyUI-SelfLift',url:'https://github.com/facok/comfyui-SelfLift',nodes:['SelfLiftH3Sampler']},
  {name:'H3 character swap runtime',url:'https://github.com/akatz-labs/h3-character-swap-tool/tree/0670e4fdf95adf2262caa4b81afed2a9c4ae4b7b/worker_nodes/h3_character_swap',nodes:['H3CharacterSwapPrepareVideo','H3CharacterSwapSelectSubject','H3CharacterSwapRecoverMasks','H3CharacterSwapExpandMask','H3CharacterSwapModels','H3CharacterSwapSettings','H3CharacterSwapShot','H3CharacterSwapWindowPlan','H3CharacterSwapController','H3CharacterSwapAssemble'],note:'This runtime also needs the OpenJutsu compatibility patch before installation. Use the pinned source; do not install an arbitrary newer checkout.',patch:'https://github.com/Comfy-Org/comfy-openjutsu/blob/70ec62df0eda7c58697ea3ac2050588513651583/build/h3_character_swap.patch'},
  {name:'ComfyUI-KJNodes',url:'https://github.com/kijai/ComfyUI-KJNodes',nodes:['PathchSageAttentionKJ','ImageResizeKJv2','BlockifyMask']},
  {name:'ComfyUI-Easy-Use',url:'https://github.com/yolain/ComfyUI-Easy-Use',nodes:['easy int']},
  {name:'ComfyUI Execution Inversion',url:'https://github.com/akatz-ai/ComfyUI-Execution-Inversion',nodes:['ForLoopOpen','ForLoopClose']},
  {name:'ComfyUI Essentials',url:'https://github.com/cubiq/ComfyUI_essentials',nodes:['SimpleMath+']},
  {name:'ComfyUI-WanAnimatePreprocess',url:'https://github.com/kijai/ComfyUI-WanAnimatePreprocess',nodes:['OnnxDetectionModelLoader','PoseAndFaceDetection','DrawViTPose']},
  {name:'ComfyUI-CrossViewWarp',url:'https://github.com/cseti007/ComfyUI-CrossViewWarp',nodes:['CrossViewWarp']},
  {name:'ComfyUI-LTXVideo',url:'https://github.com/Lightricks/ComfyUI-LTXVideo',nodes:['LTXVInpaintPreprocess','LTXAddVideoICLoRAGuide','LTXAddVideoICLoRAGuideAdvanced','LTXICLoRALoaderModelOnly','LTXVLaplacianPyramidBlend','LTXVSetAudioRefTokens','LTXVLoadConditioning','LTXVHDRDecodePostprocess','LTXVVAEForceFloat32','LTXVTiledFusionSampler']},
  {name:'MaskVidExperiments',url:'https://github.com/drozbay/MaskVidExperiments',nodes:['MVEx_SubjectCrop','MVEx_SubjectUncrop']},
  {name:'ComfyUI LayerStyle',url:'https://github.com/chflame163/ComfyUI_LayerStyle',nodes:['LayerUtility: Pad Image Batch to 8n+1']},
  {name:'ComfyUI ControlNet Aux',url:'https://github.com/Fannovel16/comfyui_controlnet_aux',nodes:['DWPreprocessor']},
  {name:'NKD Basic Tools',url:'https://github.com/Nekodificador/ComfyUI-NKD-Basic-Tools',nodes:['NKDMaskOps','NKDMaskOpsLean','NKDAVLatent']},
  {name:'NKD Sigmas Curve',url:'https://github.com/Nekodificador/ComfyUI-NKD-Sigmas-Curve',nodes:['NKDSigmasCurve']},
];

NODE_PACKS.find(pack=>pack.name==='ComfyUI').nodes.push('ResizeImageMaskNode','LTXVPreprocess','LatentUpscaleModelLoader','ManualSigmas');
NODE_PACKS.find(pack=>pack.name==='Zura Nodes').nodes.push('ZuraSaveVideoLatentData','ZuraLoadVideoLatentData');
NODE_PACKS.push({name:'ComfyUI-VideoHelperSuite',url:'https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite',nodes:['VHS_LoadImagesPath']});

// These image recipe classes ship in ComfyUI/comfy_extras. They require a
// ComfyUI update, not an unrelated custom-node installation.
NODE_PACKS.find(pack=>pack.name==='ComfyUI').nodes.push(
  'SaveImage','VAEEncode','ConditioningZeroOut','EmptyFlux2LatentImage',
  'EmptySD3LatentImage','FluxKVCache','Flux2Scheduler','ModelSamplingAuraFlow',
  'CFGNorm','TextEncodeQwenImageEditPlus','FluxKontextMultiReferenceLatentMethod',
  'LoraLoaderModelOnly');

// Zura owns these namespaces. Missing classes normally indicate that an older
// installation is loaded, so direct users to update the host pack.
const ownedNode=name=>/^(Genj|ZuraPaintout|ZuraHDR|ZuraLTX|ZuraOutpaint)/.test(name);
export function groupMissingNodes(nodes){
  const missing=[...new Set((Array.isArray(nodes)?nodes:[]).filter(name=>typeof name==='string'&&name.trim()&&!/\.(safetensors|onnx|pt|pth|ckpt|bin)$/i.test(name)))];
  const unknown=new Set(missing),packs=[];
  for(const pack of NODE_PACKS){
    const names=missing.filter(name=>unknown.has(name)&&(pack.nodes.includes(name)||(pack.name==='Zura Nodes'&&ownedNode(name))));
    if(!names.length)continue;
    names.forEach(name=>unknown.delete(name));packs.push({...pack,missing:names});
  }
  return {packs,unknown:[...unknown]};
}

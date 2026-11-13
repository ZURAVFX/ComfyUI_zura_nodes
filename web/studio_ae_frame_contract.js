// The AE range is an output contract. Model padding never changes its duration.
const whole=(value,min=1,max=10000)=>Number.isSafeInteger(value)&&value>=min&&value<=max;
export function sourceAEFrameContract(source,sessionId){
  const manifest=source?.manifest,rate=manifest?.frameRate,count=manifest?.frames?.length??source?.frameCount;
  if(!whole(count)||!rate||!whole(rate.numerator,1,1000000000)||!whole(rate.denominator,1,1000000000)||rate.numerator/rate.denominator>240||![source.width,source.height].every(v=>whole(v,1,16384))||typeof sessionId!=='string'||!/^[a-zA-Z0-9_-]{1,128}$/.test(sessionId))throw Error('The AE source has no valid frame count, rational frame rate or raster');
  return Object.freeze({schemaVersion:1,frameCount:count,frameRate:Object.freeze({numerator:rate.numerator,denominator:rate.denominator}),width:source.width,height:source.height,modelFrames:count,trimFrames:count,sessionId});
}
export const aeFrameDuration=contract=>contract.frameCount*contract.frameRate.denominator/contract.frameRate.numerator;
export const aeFrameRate=contract=>contract.frameRate.numerator/contract.frameRate.denominator;
export const aeFrameLabel=contract=>contract?`${contract.frameCount} frames @ ${contract.frameRate.denominator===1?contract.frameRate.numerator:contract.frameRate.numerator+'/'+contract.frameRate.denominator} fps`:'';
export function aeFrameOwner(owner){return owner?.aeFrameBase?owner:owner?.owner?.aeFrameBase?owner.owner:owner?.studio?.aeFrameBase?owner.studio:null;}
export function aeFramePolicy(mode,config={},owner={}){
  const engine=config.engine||owner.state?.engine||owner.draft?.engine;
  if(mode==='image')return {stride:1,offset:0,min:1,max:1,singleFrame:true};
  if(mode==='frames')return engine==='ltx'?{stride:8,offset:1,min:9,max:361}:engine==='wan'?{stride:4,offset:1,min:9,max:361}:{stride:17,offset:5,min:22,max:362,nativeFPS:24};
  if(mode==='references')return {stride:17,offset:5,min:5,max:362,nativeFPS:24};
  if(mode==='director')return engine==='h3'?{stride:17,offset:5,min:22,max:362,nativeFPS:24}:{stride:8,offset:1,min:9,max:361};
  if(mode==='hdr')return {stride:8,offset:1,min:9,max:owner.longAvailable?10000:121,sections:!!owner.longAvailable};
  if(mode==='alpha')return {stride:8,offset:1,min:9,max:145};
  if(mode==='paintout'||mode==='watermark')return {stride:8,offset:1,min:9,max:993};
  if(mode==='relight'&&(config.relight_engine==='wan21'||!owner.state&&config.workflow_mode==='relight'&&engine==='h3'))return {stride:4,offset:1,min:9,max:10000,sections:true,minSeconds:0.1,maxSeconds:30};
  if(mode==='ripple'||mode==='relight'&&owner.state)return engine==='ltx'?{stride:8,offset:1,min:9,max:985}:{stride:1,offset:0,min:1,max:993};
  if(mode==='outpaint')return {stride:8,offset:1,min:9,max:10000,sections:true};
  if(mode==='camera')return {stride:8,offset:1,min:9,max:121,maxSourceFrames:120};
  if(engine==='local'||engine==='ltx')return {stride:8,offset:1,min:9,max:mode==='viewport'?361:121};
  return {stride:1,offset:0,min:1,max:engine==='wan2'?81:120,...(engine==='h3'?{nativeFPS:24}:{})};
}
export function modelAEFrameContract(base,policy){
  if(policy.singleFrame&&base.frameCount!==1)throw Error('Image mode produces one frame. Choose Current frame in After Effects or use a video mode for this range');
  if(policy.nativeFPS&&base.frameRate.numerator!==policy.nativeFPS*base.frameRate.denominator)throw Error(`This native model generates at ${policy.nativeFPS} fps and cannot match the AE source frame rate. Choose another Studio mode`);
  if(policy.minSeconds!==undefined&&(aeFrameDuration(base)<policy.minSeconds||aeFrameDuration(base)>policy.maxSeconds))throw Error(`This mode needs an AE range between ${policy.minSeconds} and ${policy.maxSeconds} seconds`);
  const modelFrames=Math.max(policy.min,Math.ceil((base.frameCount-policy.offset)/policy.stride)*policy.stride+policy.offset);
  if(base.frameCount>(policy.maxSourceFrames??policy.max)||!policy.sections&&modelFrames>policy.max)throw Error(`This mode cannot generate the AE range of ${base.frameCount} frames. Choose a mode with longer sections or a shorter AE range`);
  return {...base,modelFrames,trimFrames:base.frameCount};
}
// A painted keyframe is an intermediate image. It never changes the source
// interval which the completed video must return to After Effects.
export function aeIntermediateImage(owner,config={}){
  const base=aeFrameOwner(owner)?.aeFrameBase;
  const value=config.ae_intermediate_image;
  if(value===undefined){if(base&&(config.ripple_guide||config.outpaint_guide))throw Error('This image guide no longer matches the active AE shot. Open the frame editor again');return null;}
  const id=value=>typeof value==='string'&&/^[a-zA-Z0-9_-]{1,128}$/.test(value);
  const allowed=new Set(['schemaVersion','kind','handoffId','anchorId','sourceFrame','width','height','parentSessionId','parentFrameCount']);
  if(!base||!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!allowed.has(key))||value.schemaVersion!==1||!['ripple_keyframe','outpaint_guide'].includes(value.kind)||!id(value.handoffId)||value.parentSessionId!==base.sessionId||value.parentFrameCount!==base.frameCount||!whole(value.sourceFrame,0,base.frameCount-1)||![value.width,value.height].every(v=>whole(v,1,16384)))throw Error('This image guide no longer matches the active AE shot. Open the frame editor again');
  if(value.kind==='ripple_keyframe'&&(!id(value.anchorId)||value.width!==base.width||value.height!==base.height)||value.kind==='outpaint_guide'&&(value.sourceFrame!==0||value.anchorId!==undefined))throw Error('This image guide does not match its AE source frame');
  return Object.freeze({...value});
}
export function aeFrameContract(owner,config={}){
  const found=aeFrameOwner(owner);if(!found)return null;
  const intermediate=aeIntermediateImage(owner,config);
  if(intermediate)return {...found.aeFrameBase,frameCount:1,modelFrames:1,trimFrames:1,width:intermediate.width,height:intermediate.height,ae_intermediate_image:intermediate};
  const mode=owner.aeFrameMode||found.aeFrameMode||'swap';return modelAEFrameContract(found.aeFrameBase,aeFramePolicy(mode,config,owner));
}
export function aeFrameConfig(owner,config){
  if(!aeFrameOwner(owner))return config;
  let contract;try{contract=aeFrameContract(owner,config);}catch(error){owner.aeFrameError=error.message;return {...config,ae_frame_contract:{...aeFrameOwner(owner).aeFrameBase},ae_frame_error:error.message};}
  owner.aeFrameError=null;const fps=aeFrameRate(contract),mode=owner.aeFrameMode||aeFrameOwner(owner).aeFrameMode;
  return {...config,start:0,startFrame:0,duration:aeFrameDuration(contract),length_mode:'custom',frameCount:contract.frameCount,sequenceFps:fps,fps,
    ...(mode==='relight'&&config.relight_engine==='wan21'?{relight_shape:'source_size'}:{}),
    ...(['frames','references','director'].includes(mode)?{frames:contract.modelFrames}:{}),ae_frame_contract:contract};
}
export function assertAEFrameConfig(owner,config={}){const contract=aeFrameContract(owner,config);if(config.ae_frame_error)throw Error(config.ae_frame_error);return contract;}
export function aeFrameRequest(owner,body={}){const contract=assertAEFrameConfig(owner,body.config||body);return contract?{...body,ae_frame_contract:contract}:body;}
export function bindAEFrameWorkspace(creative,mode,workspace,base){
  creative.aeFrameBase=base;creative.studio.aeFrameBase=base;workspace.aeFrameBase=base;workspace.aeFrameMode=mode;
  if(typeof workspace.config==='function'&&!workspace.aeOriginalConfig){workspace.aeOriginalConfig=workspace.config;workspace.config=function(...args){return aeFrameConfig(this,this.aeOriginalConfig(...args));};}
  const contract=assertAEFrameConfig(workspace,typeof workspace.config==='function'?workspace.config():workspace.config||{}),fps=aeFrameRate(contract);
  if(workspace===creative.studio)Object.assign(workspace.config,{start:0,duration:aeFrameDuration(base),length_mode:'custom',fps,ae_frame_contract:contract,...(mode==='relight'&&workspace.config.relight_engine==='wan21'?{relight_shape:'source_size'}:{})});
  if(workspace.state)Object.assign(workspace.state,{startFrame:0,frameCount:base.frameCount});
  if(mode==='camera')workspace.state.config={...workspace.state.config,start:0,duration:aeFrameDuration(base)};
  if(mode==='director')workspace.draft.frames=base.frameCount;
  if(mode==='hdr'){
    workspace.rangeEditRevision=(workspace.rangeEditRevision||0)+1;
    if(base.frameCount>121&&workspace.longAvailable)workspace.$('long').checked=true;
    workspace.$('start').value='0';workspace.$('count').value=String(base.frameCount);workspace.$('sequence-fps').value=String(fps);workspace.updateRangeSummary();
  }
  if(['frames','references'].includes(mode)){const select=workspace.$('length');if(select.options&&![...select.options].some(option=>option.value===String(base.frameCount))){const option=select.ownerDocument.createElement('option');option.value=String(base.frameCount);option.textContent=`AE range · ${base.frameCount} frames`;select.append(option);}select.value=String(base.frameCount);}
  workspace.syncForm?.();workspace.save?.();workspace.render?.();return contract;
}
export function aeBridgeFor(owner){return owner?.studio?.aeBridge||owner?.owner?.studio?.aeBridge||owner?.aeBridge;}
export async function prepareAEFrameGraph(owner,graph,config={}){
  const contract=assertAEFrameConfig(owner,config);if(!contract)return {graph,config};
  const intermediate=aeIntermediateImage(owner,config);
  const mode=intermediate?'image':owner.aeFrameMode||aeFrameOwner(owner).aeFrameMode;
  // Geometry and camera-guide jobs do not represent the final returned shot.
  if(mode==='camera'&&config.stage&&config.stage!=='render')return {graph,config:{...config,ae_frame_contract:contract}};
  const bridge=aeBridgeFor(owner);if(!bridge?.prepareGraph)throw Error('The AE frame-matching service is unavailable. Leave AE mode or reconnect from After Effects');
  const prepared=await bridge.prepareGraph(mode,graph,intermediate?aeFrameOwner(owner).aeFrameBase:contract,intermediate);
  return {graph:prepared.graph,config:{...config,ae_frame_contract:prepared.ae_frame_contract||contract}};
}

// Live guide identity only. This never changes the final AE delivery contract.
const integer=(v,min,max)=>Number.isSafeInteger(v)&&v>=min&&v<=max;
export function captureAEGuideParent(owner,workspace){
 const base=owner?.aeFrameBase||owner?.studio?.aeFrameBase||workspace?.aeFrameBase||workspace?.platePrimary?.aeFrameBase;
 if(!base)return null;
 if(typeof base.sessionId!=='string'||!base.sessionId||!integer(base.frameCount,1,10000)||!integer(base.width,1,16384)||!integer(base.height,1,16384)||!integer(base.frameRate?.numerator,1,1000000000)||!integer(base.frameRate?.denominator,1,1000000000))throw Error('Reconnect the AE source before preparing an image guide.');
 return {sessionId:base.sessionId,frameCount:base.frameCount,width:base.width,height:base.height,frameRate:{numerator:base.frameRate.numerator,denominator:base.frameRate.denominator}};
}
export function sameAEGuideParent(saved,owner,workspace){
 try{return JSON.stringify(saved||null)===JSON.stringify(captureAEGuideParent(owner,workspace));}catch{return false;}
}
export function aeIntermediateImage(owner){
 if(owner?.mode!=='image')return null;
 const ripple=owner.rippleImage,paint=owner.outpaintGuide;
 if(ripple?.request&&paint?.request)return null;
 let request,workspace,kind,frame,anchorId;
 if(ripple?.request){request=ripple.request;workspace=request.workspace;if(!ripple.current(request))return null;kind='ripple_keyframe';frame=request.anchor?.frame;anchorId=String(request.anchor?.id||'');if(!anchorId)return null;}
 else if(paint?.request){request=paint.request;workspace=paint.workspace;if(paint.key()!==request.key)return null;kind='outpaint_guide';frame=request.sourceFrame;}
 else return null;
 const parent=request.aeParent;
 if(!parent||!sameAEGuideParent(parent,owner,workspace)||!integer(frame,0,parent.frameCount-1)||!integer(request.width,1,16384)||!integer(request.height,1,16384)||typeof request.id!=='string'||!request.id)return null;
 return {schemaVersion:1,kind,handoffId:request.id,...(anchorId?{anchorId}:{}),sourceFrame:frame,width:request.width,height:request.height,parentSessionId:parent.sessionId,parentFrameCount:parent.frameCount};
}

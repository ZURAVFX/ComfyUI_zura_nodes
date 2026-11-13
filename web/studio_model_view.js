// A model's SDR input never replaces the original source in its editor.
const HDR=new Set(['acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020']);
const sourceKey=config=>JSON.stringify([String(config.source||'').replaceAll('\\','/').toLowerCase(),config.startFrame||0,config.frameCount,config.sequenceFps,
  config.sourceColour,config.detectedSourceColour,config.engine,config.width,config.height,
  config.anchors?.map(anchor=>[anchor.id,anchor.file,anchor.frame,anchor.colour_space,anchor.enabled!==false])]);
function selector(source){
  if(source?.display_source)return {source_token:source.display_source};
  if(source?.studioAssetId||source?.id&&/^[a-f0-9]{32}$/.test(source.id))return {asset_id:source.studioAssetId||source.id,...(source.frame_time!==undefined?{frame_time:source.frame_time}:{})};
  if(source?.file&&typeof source.file==='object')return {file:source.file};
  if(source?.filename&&source?.type)return {file:{filename:source.filename,subfolder:source.subfolder||'',type:source.type}};
  if(source?.media_url)return {media_url:source.media_url};
  return null;
}
export function restoreModelViewConfig(config){
  const view=config?.processingView;if(view?.kind!=='sdr8_inference'||!view.originalSource?.path)return config;
  const offset=view.originalStartFrame||0;
  return {...config,source:view.originalSource.path,startFrame:offset,
    sourceColour:view.sourceColour,detectedSourceColour:view.sourceColour,
    anchors:config.anchors?.map((anchor,index)=>({...anchor,...view.originalAnchors?.[index],frame:anchor.frame<0?anchor.frame:anchor.frame+offset}))};
}
export function installStudioModelViews(delivery,api){
  const output=delivery.owner,wrapped=new WeakSet(),busyWrapped=new WeakSet();
  const wrapBusy=workspace=>{if(!workspace||typeof workspace.busy!=='function'||busyWrapped.has(workspace))return;const busy=workspace.busy;workspace.busy=function(){return delivery.modelView?.workspace===this||delivery.modelView?.primary===this||busy.apply(this,arguments);};busyWrapped.add(workspace);};
  const previousBusy=delivery.isBusyFor.bind(delivery),previousCancel=delivery.cancel.bind(delivery);
  const previousClose=delivery.close?.bind(delivery);if(previousClose)delivery.close=(...args)=>{delivery.modelView?.controller.abort();return previousClose(...args);};
  delivery.isBusyFor=mode=>delivery.modelView?.mode===mode||previousBusy(mode);
  delivery.cancel=()=>{if(delivery.modelView){delivery.modelView.controller.abort();return;}return previousCancel();};
  const sourceFor=workspace=>{const primary=workspace.platePrimary||(output?.plate?.runner===workspace?output.paintout:workspace);return {primary,original:primary?.sourceInfo||workspace.sourceInfo||workspace.source};};
  // Readiness only: the real validator still runs after the actual view exists.
  delivery.modelInputValidationConfig=(workspace,config)=>{
    const colour=config.sourceColour&&config.sourceColour!=='auto'?config.sourceColour:config.detectedSourceColour;
    if(!HDR.has(colour)||!selector(sourceFor(workspace).original))return config;
    return {...config,sourceColour:'srgb_display',detectedSourceColour:'srgb_display',colourPipeline:'sdr_sdr',processingSpace:'SDR (sRGB)',outputMode:'SDR video'};
  };
  delivery.prepareInferenceView=async(workspace,mode,config)=>{
    // AE already provides a broker-authorised processingInput copy, whose
    // sourceColour is sRGB while the original FLOAT source remains separate.
    const colour=config.sourceColour&&config.sourceColour!=='auto'?config.sourceColour:config.detectedSourceColour;
    if(config.processingView?.kind==='sdr8_inference'||!HDR.has(colour))return config;
    if(mode==='alpha')return config;
    const {primary,original}=sourceFor(workspace);
    const chosen=selector(original);
    if(!chosen)throw Error('Reload this original HDR source to prepare its SDR model input.');
    if(delivery.modelView)throw Error('Wait for the current model input preparation or cancel it.');
    const beforeKey=sourceKey(config);
    wrapBusy(workspace);wrapBusy(primary);
    const controller=new AbortController(),record={controller,mode,workspace,primary};delivery.modelView=record;
    const cancelButton=delivery.$?.('cancel'),cancelLabel=cancelButton?.textContent;if(cancelButton)cancelButton.textContent='Cancel input preparation';
    delivery.message('Preparing SDR model input. The original HDR source is retained.');delivery.sync();
    try{
      const requestView=async body=>{
        const response=await api.fetchApi('/zura/studio/model-view',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify(body)});
        const info=await response.json();if(!response.ok)throw Error(info.error||'The HDR source could not be prepared for this model.');
        if(controller.signal.aborted||delivery.closed)throw Error('SDR model input preparation was cancelled.');
        if(info.processingView?.kind!=='sdr8_inference'||info.resolved_colour!=='srgb_display'||!info.path)throw Error('The server did not return a verified SDR model input.');
        return info;
      };
      const info=await requestView({source:chosen,colour_space:colour,
          startFrame:config.startFrame||0,frameCount:config.frameCount,
          ...(config.ae_frame_contract?.frameRate?{frameRate:config.ae_frame_contract.frameRate}:{sequenceFps:config.sequenceFps})});
      const originalAnchors=config.anchors?.map(anchor=>({file:anchor.file,colour_space:anchor.colour_space})),anchors=[];
      for(const anchor of config.anchors||[]){
        if(!HDR.has(anchor.colour_space)){anchors.push(anchor);continue;}
        const response=await api.fetchApi('/zura/paintout/info?'+new URLSearchParams({file:anchor.file}),{signal:controller.signal});
        const description=await response.json();if(!response.ok)throw Error(description.error||'The HDR edited frame could not be inspected.');
        const anchorSource=selector(description);if(!anchorSource)throw Error('Reload the HDR edited frame to prepare its model input.');
        const prepared=await requestView({source:anchorSource,colour_space:anchor.colour_space,startFrame:0,frameCount:1});
        anchors.push({...anchor,file:prepared.path,colour_space:'srgb_display'});
      }
      if(typeof workspace.config==='function'&&sourceKey(workspace.config())!==beforeKey)throw Error('The source, range or edited frames changed while preparing the model input. Try again.');
      if(typeof workspace.setResult==='function'&&!wrapped.has(workspace)){
        const setResult=workspace.setResult;
        workspace.setResult=function(result){return setResult.call(this,result?.config?{...result,config:restoreModelViewConfig(result.config)}:result);};
        wrapped.add(workspace);
      }
      const offset=info.processingView.originalStartFrame||0;
      delivery.message('SDR model input ready; the original HDR source is retained.');
      return {...config,source:info.path,startFrame:0,frameCount:info.frames,sequenceFps:info.fps,
        sourceColour:'srgb_display',detectedSourceColour:'srgb_display',colourPipeline:'sdr_sdr',processingSpace:'SDR (sRGB)',
        anchors:config.anchors?anchors.map(anchor=>({...anchor,frame:anchor.frame<0?anchor.frame:anchor.frame-offset})):undefined,
        processingView:{...info.processingView,inferencePath:info.path,inferenceStartFrame:0,originalAnchors}};
    }catch(error){if(controller.signal.aborted)throw Error('SDR model input preparation was cancelled. The original is retained.');throw error;}
    finally{if(delivery.modelView===record)delivery.modelView=null;if(cancelButton)cancelButton.textContent=cancelLabel;delivery.sync();}
  };
}

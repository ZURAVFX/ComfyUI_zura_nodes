import assert from 'node:assert/strict';
import {installStudioModelViews,restoreModelViewConfig} from '../web/studio_model_view.js';
import {PlateWorkspace} from '../web/studio_plate.js';
import {RippleWorkspace} from '../web/studio_ripple.js';
const source={path:'C:/selected/HDR.exr',display_source:'native-source-grant',resolved_colour:'acescg',frames:20,width:1920,height:1080};
const initial={engine:'ltx',source:source.path,startFrame:5,frameCount:9,sequenceFps:30000/1001,sourceColour:'acescg',detectedSourceColour:'acescg',anchors:[{id:'selected',frame:7,file:'edited.exr'},{frame:-1,file:'global.exr'}]};
function fixture(){
  let config=structuredClone(initial),result,fetches=[];
  const primary={sourceInfo:source,busy(){return false;}},workspace={config:()=>config,busy(){return false;},setResult(value){result=value;}};
  const delivery={owner:{paintout:primary,plate:{runner:workspace}},closed:false,close(){this.closed=true;},isBusyFor(){return false;},cancel(){this.originalCancelled=true;},message(value){this.lastMessage=value;},sync(){},$:()=>({textContent:'Cancel HDR'})};
  const proxy={path:'C:/input/model-view.mkv',resolved_colour:'srgb_display',frames:9,fps:30000/1001,
    processingView:{schemaVersion:1,kind:'sdr8_inference',originalSource:source,sourceColour:'acescg',originalStartFrame:5}};
  const api={fetchApi:async(path,options)=>{fetches.push({path,options});return {ok:true,json:async()=>structuredClone(proxy)};}};
  installStudioModelViews(delivery,api);
  return {delivery,primary,workspace,api,proxy,fetches,get result(){return result;},set config(value){config=value;}};
}
{
  const f=fixture(),prepared=await f.delivery.prepareInferenceView(f.workspace,'ripple',structuredClone(initial));
  assert.equal(prepared.source,f.proxy.path);assert.equal(prepared.startFrame,0);assert.equal(prepared.frameCount,9);assert.equal(prepared.sequenceFps,30000/1001);
  assert.equal(prepared.sourceColour,'srgb_display');assert.equal(prepared.detectedSourceColour,'srgb_display');assert.equal(prepared.anchors[0].frame,2);assert.equal(prepared.anchors[1].frame,-1);
  const body=JSON.parse(f.fetches[0].options.body);assert.deepEqual(body.source,{source_token:source.display_source});assert.equal(body.startFrame,5);
  f.workspace.setResult({config:prepared,file:{filename:'generated.mp4'}});
  assert.equal(f.result.config.source,source.path);assert.equal(f.result.config.startFrame,5);assert.equal(f.result.config.anchors[0].frame,7);
  assert.equal(f.result.config.processingView.kind,'sdr8_inference');assert.equal(f.primary.sourceInfo,source);assert.equal(f.delivery.isBusyFor('ripple'),false);
}
{
  const f=fixture();let release,signal;
  f.api.fetchApi=async(_path,options)=>{signal=options.signal;return new Promise(resolve=>release=()=>resolve({ok:true,json:async()=>f.proxy}));};
  const pending=f.delivery.prepareInferenceView(f.workspace,'ripple',structuredClone(initial));
  assert.equal(f.primary.busy(),true);assert.equal(f.workspace.busy(),true);assert.equal(f.delivery.isBusyFor('ripple'),true);
  f.delivery.cancel();assert.equal(signal.aborted,true);release();await assert.rejects(pending,/cancelled/);
  assert.equal(f.primary.busy(),false);assert.equal(f.workspace.busy(),false);assert.equal(f.delivery.isBusyFor('ripple'),false);
  f.delivery.cancel();assert.equal(f.delivery.originalCancelled,true,'HDR cancellation retains its existing handler');
}
{
  const f=fixture();f.config={...initial,startFrame:6};
  await assert.rejects(f.delivery.prepareInferenceView(f.workspace,'ripple',structuredClone(initial)),/changed/);
  assert.equal(f.delivery.modelView,null);
}
{
  const f=fixture();let release,signal;
  f.api.fetchApi=async(_path,options)=>{signal=options.signal;return new Promise(resolve=>release=()=>resolve({ok:true,json:async()=>f.proxy}));};
  const pending=f.delivery.prepareInferenceView(f.workspace,'ripple',structuredClone(initial));
  f.delivery.close();assert.equal(signal.aborted,true);assert.equal(f.delivery.closed,true);release();await assert.rejects(pending,/cancelled/);
}
{
  const f=fixture(),sdr={...initial,sourceColour:'srgb_display',detectedSourceColour:'srgb_display'};
  assert.equal(await f.delivery.prepareInferenceView(f.workspace,'ripple',sdr),sdr);assert.equal(f.fetches.length,0);
  assert.equal(await f.delivery.prepareInferenceView(f.workspace,'alpha',initial),initial,'Alpha requires source-beauty preservation rather than an RGB-only view handoff');
  assert.equal(restoreModelViewConfig(sdr),sdr);
}
{
  const f=fixture(),calls=[],config={...initial,anchors:[{id:'anchor',file:'C:/selected/edited.exr',frame:7,colour_space:'acescg'}]};f.config=config;
  f.api.fetchApi=async(path,options)=>{
    calls.push({path,options});
    if(path.startsWith('/zura/paintout/info?'))return {ok:true,json:async()=>({path:'C:/selected/edited.exr',display_source:'anchor-grant'})};
    const body=JSON.parse(options.body);
    return {ok:true,json:async()=>body.source.source_token==='anchor-grant'?{path:'C:/input/anchor.png',resolved_colour:'srgb_display',processingView:{kind:'sdr8_inference'}}:f.proxy};
  };
  const prepared=await f.delivery.prepareInferenceView(f.workspace,'ripple',config);
  assert.equal(prepared.anchors[0].file,'C:/input/anchor.png');assert.equal(prepared.anchors[0].colour_space,'srgb_display');assert.equal(prepared.anchors[0].frame,2);
  const restored=restoreModelViewConfig(prepared);assert.equal(restored.anchors[0].file,'C:/selected/edited.exr');assert.equal(restored.anchors[0].colour_space,'acescg');assert.equal(restored.anchors[0].frame,7);
  assert.equal(calls.filter(call=>call.path==='/zura/studio/model-view').length,2,'Source and HDR guide use the same guarded view conversion');
}
for(const kind of ['plate','ripple']){
  const f=fixture(),config={...initial,width:512,height:512,outputMode:'SDR video',anchors:[initial.anchors[0]]};f.config=config;
  f.workspace.state={};f.workspace.owner=f.delivery.owner;f.workspace.message=value=>f.workspace.lastMessage=value;f.workspace.render=()=>{};
  f.primary.state={source:source.path,anchors:config.anchors};f.primary.message=value=>f.primary.lastMessage=value;f.primary.render=()=>{};f.primary.preview=()=>{};
  let accepted;f.workspace.onGenerate=async value=>{accepted=value;f.workspace.job={id:'queued'};};
  if(kind==='plate'){
    const plate=Object.assign(Object.create(PlateWorkspace.prototype),{owner:f.delivery.owner,primary:f.primary,runner:f.workspace,config:()=>config,ensureRunner:()=>f.workspace});
    f.delivery.owner.outputSettings={delivery:f.delivery};f.delivery.owner.plate=plate;
    await plate.generate();
  }else{
    f.delivery.owner.outputSettings={delivery:f.delivery};f.delivery.owner.plate=null;f.workspace.sourceInfo=source;
    await RippleWorkspace.prototype.generate.call(f.workspace);
  }
  assert.ok(accepted,`${kind} must prepare HDR input before its strict SDR-only validation`);
  assert.equal(accepted.source,f.proxy.path);assert.equal(accepted.sourceColour,'srgb_display');assert.equal(accepted.startFrame,0);
  assert.equal(f.primary.state.source,source.path);assert.equal(f.fetches.length,1);
}
console.log('SDR model views retain original HDR editor state, exact range/anchor mapping, cancellation, stale-source checks and ordinary SDR behaviour');

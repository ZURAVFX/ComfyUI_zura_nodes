import assert from 'node:assert/strict';
import {studioModeAdapter} from '../web/studio_mode_adapters.js';
import {StudioAEBridge} from '../web/studio_comfylink.js';
import {imageDimensions} from '../web/image_recipes.js';

const media={path:'ae/derived/source.mkv',kind:'video',frames:9,width:512,height:512,fps:24,resolved_colour:'rec709_oetf',
  colour_error:'Video has no supported colour tags',thumbnail_url:'/zura/paintout/frame-preview?file=ae%2Fderived%2Fsource.mkv&space=auto&frame=0&size=1280'};
const source={width:512,height:512,frameCount:9,precision:{sourceBitDepth:32},manifest:{frames:Array.from({length:9},()=>({})),frameRate:{numerator:24,denominator:1}},
  processingInput:{precision:{sourceBitDepth:8},studioAsset:{id:'derived',duration:9/24},mediaInfo:media,stills:{first:{file:'first.png',width:512,height:512}}}};
function workspace(){
  const controls=new Map();return {state:{sourceColour:'acescg',sourceColourConfirmed:false,colourPipeline:'hdr_hdr',processingSpace:'HDR (ACEScct)',outputMode:'EXR + HLG video'},references:[],sourceLoads:0,
    $(id){if(!controls.has(id))controls.set(id,{value:''});return controls.get(id);},
    busy(){return false;},save(){},render(){},syncForm(){},clearImageResult(){},setImageOperation(){},
    applySourceInfo(info){this.sourceLoads++;this.sourceInfo=info;this.colourAtLoad={...this.state};},
    setSource(info){this.sourceLoads++;this.source=info;this.state.anchors=[];this.state.sourceColour=info.resolved_colour;},
    config(){return {engine:'ltx',startFrame:this.state.startFrame,frameCount:this.state.frameCount};}};
}
function creative(){const c={...workspace(),mode:'home',paintout:workspace(),watermark:workspace(),ripple:workspace(),alpha:workspace(),referencesVideo:{...workspace(),assets:{images:[],videos:[],audios:[]},preview(){}},director:{...workspace(),draft:{clips:[]}},
  studio:{...workspace(),config:{workflow_mode:'relight'}},show(id){this.mode=id;},selectRelightEngine(){this.mode='ripple';this.ripple.intent='relight';},ensureRippleWorkspace(){}};
  for(const w of [c.paintout,c.watermark,c.ripple,c.alpha]){w.owner=c;w.studio=c.studio;}return c;}

for(const id of ['paintout','watermark']){
  const c=creative(),w=c[id];await studioModeAdapter(id).acceptInput(c,source);
  assert.deepEqual(Object.fromEntries(['sourceColour','sourceColourConfirmed','colourPipeline','processingSpace','outputMode'].map(k=>[k,w.colourAtLoad[k]])),
    {sourceColour:'srgb_display',sourceColourConfirmed:true,colourPipeline:'sdr_sdr',processingSpace:'SDR (sRGB)',outputMode:'SDR video'},'AE SDR settings reset before the source setter reads them');
  assert.equal(w.$('colour').value,'srgb_display');assert.equal(w.$('processing').value,'SDR (sRGB)');assert.equal(w.$('output').value,'SDR video');
  assert.equal(w.sourceInfo.resolved_colour,'srgb_display');assert.equal(media.resolved_colour,'rec709_oetf','The native inspection descriptor is not mutated');
  assert.equal(w.sourceInfo.colour_error,undefined,'Verified derived input does not show an obsolete auto-detection error');
  const preview=new URL(w.sourceInfo.thumbnail_url,'http://studio.invalid');
  assert.equal(preview.searchParams.get('space'),'srgb_display');assert.equal(preview.searchParams.get('file'),media.path);assert.equal(preview.searchParams.get('size'),'1280');
  assert.equal(media.colour_error,'Video has no supported colour tags');assert.match(media.thumbnail_url,/space=auto/,'Original inspection is unchanged');
  const direct={...source,precision:{sourceBitDepth:8},processingInput:undefined,studioAsset:{id:'direct'},mediaInfo:{...media,resolved_colour:'rec709_gamma24'}};
  await studioModeAdapter(id).acceptInput(c,direct);assert.equal(w.state.sourceColour,'rec709_gamma24','A recognised direct SDR source retains its detected transfer');
  await studioModeAdapter(id).acceptInput(c,{...direct,mediaInfo:{...media,resolved_colour:'auto'}});assert.equal(w.state.sourceColour,'srgb_display');
}
for(const id of ['ripple','relight','alpha']){
  const c=creative();c.relightEngine='ltx';await studioModeAdapter(id).acceptInput(c,source);
  const w=studioModeAdapter(id).resolveWorkspace(c);assert.equal(w.source.resolved_colour,'srgb_display','Derived display-sRGB does not inherit an untagged-video Rec.709 fallback');
}

const image=creative();image.$('shape').value='square';image.$('width').value='1024';image.$('height').value='1024';image.$('prompt').value='Keep this instruction';image.$('model').value='flux3edit';
await studioModeAdapter('image').acceptInput(image,{...source,width:1920,height:1080,frameCount:1,manifest:{...source.manifest,frames:[{}]},processingInput:{...source.processingInput,stills:{first:{file:'single.png',width:1920,height:1080}}}});
assert.equal(image.$('shape').value,'auto');assert.equal(image.$('width').value,'1920');assert.equal(image.$('height').value,'1080');assert.equal(image.imageSizeRatio,1920/1080);
assert.equal(image.$('prompt').value,'Keep this instruction');assert.equal(image.$('model').value,'flux3edit');
assert.deepEqual(imageDimensions({model:'flux3edit',shape:image.$('shape').value,references:image.references}),[1920,1088],'Native model alignment remains explicit; final raster restoration is a separate graph boundary');

const single={...source,frameCount:1,manifest:{...source.manifest,frames:[{}]}};
{
  // The real 32-bit AE handoff supplies raster metadata on the source descriptor,
  // while its derived 8-bit still records can contain file identities only.
  const broker={...single,processingInput:{...single.processingInput,stills:{first:{file:'ae-view.png'},last:{file:'ae-last.png'}}}};
  for(const id of ['image','references','frames','director']){
    const c=creative();
    if(id==='frames')c.frames={...workspace(),assets:{},selectAvailability(){},preview(){}};
    await studioModeAdapter(id).acceptInput(c,broker);
    const w=studioModeAdapter(id).resolveWorkspace(c);
    const refs=id==='image'?w.references:id==='references'?w.assets.images:id==='frames'?[w.assets.first,w.assets.last]:w.draft.clips.map(clip=>clip.asset);
    assert.ok(refs.length>0);
    for(const ref of refs)assert.deepEqual([ref.width,ref.height],[512,512],`${id} retains the AE raster on every still`);
    if(id==='image')for(const model of ['qwen2511','klein9b','flux3edit'])assert.deepEqual(imageDimensions({model,shape:'auto',references:w.references}),[512,512],`${model} can consume a file-only broker still`);
    assert.equal(broker.processingInput.stills.first.width,undefined,'Source descriptors remain immutable');
  }
  const direct={...single,precision:{sourceBitDepth:8},processingInput:undefined,stills:[{file:'direct.png'}]};
  const c=creative();await studioModeAdapter('image').acceptInput(c,direct);
  assert.deepEqual([c.references[0].width,c.references[0].height],[512,512],'Direct SDR array stills use the same raster fallback');
}
{
  const c=creative(),user={file:'user-reference.png',name:'My reference'},same={file:'first.png',name:'User-supplied source',custom:'preserved'};
  c.references=[user,same];await studioModeAdapter('image').acceptInput(c,single);await studioModeAdapter('image').acceptInput(c,single);
  assert.deepEqual(c.references.map(item=>item.file),['first.png','user-reference.png']);assert.equal(c.references[0].custom,'preserved');assert.equal(c.references[1],user);
  const replaced={...single,processingInput:{...single.processingInput,stills:{first:{file:'replacement.png',width:512,height:512}}}};
  await studioModeAdapter('image').acceptInput(c,replaced);assert.deepEqual(c.references.map(item=>item.file),['replacement.png','first.png','user-reference.png'],'User-added references remain when the source changes');
  await studioModeAdapter('image').acceptInput(c,single);assert.deepEqual(c.references.map(item=>item.file),['first.png','user-reference.png'],'Only the previous source-owned entry is replaced');
  c.references=Array.from({length:9},(_,i)=>({file:`user-${i}.png`}));await studioModeAdapter('image').acceptInput(c,single);assert.equal(c.references.length,10,'Source loading never silently truncates user references');
}
{
  const c=creative(),w=c.referencesVideo,user={file:'user.png'};w.assets.images=[user];
  const clip={...source,processingInput:{...source.processingInput,stills:{first:{file:'first.png',width:512,height:512},last:{file:'last.png',width:512,height:512}}}};
  await studioModeAdapter('references').acceptInput(c,clip);await studioModeAdapter('references').acceptInput(c,clip);
  assert.deepEqual(w.assets.images.map(item=>item.file),['first.png','last.png','user.png']);assert.equal(w.assets.images[2],user);
  assert.equal(w.$('width').value,'512');assert.equal(w.$('height').value,'512');assert.equal(w.$('size-preset').value,'custom');
  await studioModeAdapter('references').acceptInput(c,{...clip,processingInput:{...clip.processingInput,stills:{first:{file:'first.png'},last:{filename:'first.png',subfolder:'',type:'input'}}}});
  assert.deepEqual(w.assets.images.map(item=>item.file),['first.png','user.png'],'The same first/last file becomes one reference');
  await studioModeAdapter('references').acceptInput(c,{...clip,width:1920,height:1080},{sessionId:'a'.repeat(32)});
  assert.equal(w.$('width').value,'1920');assert.equal(w.$('height').value,'1088');assert.equal(w.aeFrameBase.height,1080,'Model alignment never changes the final AE raster');
  await studioModeAdapter('references').acceptInput(c,{...clip,width:3840,height:2160},{sessionId:'a'.repeat(32)});
  assert.equal(w.$('width').value,'3840');assert.equal(w.$('height').value,'2176');assert.equal(w.aeFrameBase.width,3840);assert.equal(w.aeFrameBase.height,2160);
  const previous=w.assets.images;await assert.rejects(studioModeAdapter('references').acceptInput(c,{...clip,width:8192,height:512}),/cannot process.*4096/);assert.equal(w.assets.images,previous,'Unsupported raster fails before changing references');
  await assert.rejects(studioModeAdapter('references').acceptInput(c,{...clip,width:4096,height:4096}),/8.39 MP/);
}
{
  const c=creative(),w=c.director,user={id:'user-image',kind:'image',startFrame:3,endFrame:4,asset:{file:'user.png'}},prompt={id:'direction',kind:'prompt',startFrame:0,endFrame:9,text:'Keep my direction'};
  w.draft.clips=[user,prompt];await studioModeAdapter('director').acceptInput(c,source);const identity=w.draft.clips[0].id;
  await studioModeAdapter('director').acceptInput(c,source);assert.equal(w.draft.clips.length,3);assert.equal(w.draft.clips[0].id,identity);assert.equal(w.draft.clips[0].asset.file,'first.png');assert.equal(w.draft.clips[1],user);assert.equal(w.draft.clips[2],prompt);
  w.draft.clips[0].startFrame=1;w.draft.clips[0].endFrame=2;w.draft.clips[0].strength=.7;await studioModeAdapter('director').acceptInput(c,source);
  assert.equal(w.draft.clips[0].startFrame,1);assert.equal(w.draft.clips[0].strength,.7,'Reloading keeps edits to the source-owned clip');
  w.draft.clips=[{id:'old-one',kind:'image',startFrame:0,endFrame:1,asset:{file:'first.png'}},{id:'old-two',kind:'image',startFrame:0,endFrame:1,asset:{file:'first.png'}},user,prompt];
  await studioModeAdapter('director').acceptInput(c,source);assert.deepEqual(w.draft.clips.map(clip=>clip.id),['old-one','user-image','direction'],'Legacy duplicate source insertions collapse without changing the retained identity');
  const occupied=[{...user,startFrame:0,endFrame:2},prompt];w.draft.clips=occupied;await assert.rejects(studioModeAdapter('director').acceptInput(c,source),/already has an image at frame 0/);assert.equal(w.draft.clips,occupied,'An occupied first frame never deletes the user clip');
}

function bridgeFixture(){
  const c=creative(),w=c.ripple;c.mode='ripple';c.relightEngine='ltx';w.intent='relight';w.source=media;w.state.engine='ltx';w.state.startFrame=2;w.state.frameCount=3;w.state.anchors=[{id:'edited',file:'edited.png',frame:2}];w.result={file:{filename:'previous.mp4'}};
  const b=Object.create(StudioAEBridge.prototype);Object.assign(b,{studio:c.studio,session:{id:'a'.repeat(32)},closed:false,revision:0,loaded:new Map([['relight',c.studio]]),source,
    sourceButton:{},send:{},status:{},message(value){StudioAEBridge.prototype.message.call(this,value);this.lastMessage=value;},updateMeta(){},request(){throw Error('Source is already cached');}});
  c.studio.creative=c;c.studio.aeBridge=b;return {b,c,w};
}
{
  const {b,c,w}=bridgeFixture(),anchors=w.state.anchors,result=w.result;
  await b.loadSource();assert.equal(b.loaded.get('relight'),w);assert.equal(w.sourceLoads,0,'Same verified source is rebound without reloading');
  assert.equal(w.state.anchors,anchors);assert.equal(w.result,result);assert.equal(w.config().ae_frame_contract.frameCount,9);assert.equal(w.config().sequenceFps,24);assert.equal(w.state.startFrame,0);
  await b.loadSource();assert.equal(w.sourceLoads,0,'Repeated mode notifications do not reset the loaded workspace');
  assert.equal(c.studio.aeFrameBase,w.aeFrameBase);
}
{
  const {b,w}=bridgeFixture();w.source={...media,path:'different/source.mkv'};
  await b.loadSource();assert.equal(w.sourceLoads,1,'A workspace holding another source must receive the AE source');assert.equal(w.source.path,media.path);assert.equal(b.loaded.get('relight'),w);
}
{
  const {b,w}=bridgeFixture();w.busy=()=>true;
  await b.loadSource();assert.equal(w.sourceLoads,0);assert.notEqual(b.loaded.get('relight'),w);assert.match(b.lastMessage,/Finish/);
}
{
  const {b,w}=bridgeFixture();w.source={...media,path:'different/source.mkv'};w.state.studioAsset={id:'original-float'};
  assert.equal(studioModeAdapter('relight').matchesInput(b.studio.creative,source),false,'Original float and derived processing identities are distinct');
  w.state.studioAsset={id:'derived'};assert.equal(studioModeAdapter('relight').matchesInput(b.studio.creative,source),true);
}
{
  const {b,c,w}=bridgeFixture();w.source={...media,path:'old/source.mkv'};
  let releaseNavigation,enteredNavigation;
  const entered=new Promise(resolve=>enteredNavigation=resolve),gate=new Promise(resolve=>releaseNavigation=resolve);
  c.selectRelightEngine=async()=>{enteredNavigation();await gate;};
  const first=b.loadSource();await entered;
  const fresh=workspace();Object.assign(fresh,{owner:c,studio:c.studio,intent:'relight'});c.ripple=fresh;
  c.selectRelightEngine=()=>{};releaseNavigation();await first;
  for(let i=0;i<20&&(b.pending||b.loaded.get('relight')!==fresh);i++)await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(fresh.sourceLoads,1,'A workspace switched during navigation is actually loaded before being cached');
  assert.equal(fresh.aeFrameBase.frameCount,9);assert.equal(b.loaded.get('relight'),fresh);
  assert.equal(w.sourceLoads,0,'The abandoned navigation cannot load the old workspace');
}
console.log('AE source acceptance: SDR colour reset, image source sizing, same-source Relight rebinding and edit preservation passed');

{
  const {b,c,w}=bridgeFixture();await b.loadSource();const anchors=w.state.anchors,result=w.result;
  c.mode='image';await b.loadSource();assert.match(b.status.textContent,/Image mode produces one frame/);assert.equal(b.sourceErrorMode,'image');
  c.mode='ripple';await b.loadSource();assert.equal(b.status.textContent,'AE source ready');assert.equal(b.sourceErrorMode,null);
  assert.equal(w.state.anchors,anchors);assert.equal(w.result,result);assert.equal(w.sourceLoads,0,'Returning from an inline image edit keeps the video workspace');
  b.message('Master validation failed. Result retained');c.mode='image';c.mode='ripple';await b.loadSource();assert.match(b.status.textContent,/Master validation failed/,'Transfer diagnostics are not cleared by cached workspace notifications');
  b.message('Source cannot load');b.sourceErrorMode='image';b.importPending=true;await b.loadSource();assert.equal(b.status.textContent,'Source cannot load','A pending transfer is not overwritten');
  b.importPending=false;await b.loadSource();assert.equal(b.status.textContent,'AE source ready');
}

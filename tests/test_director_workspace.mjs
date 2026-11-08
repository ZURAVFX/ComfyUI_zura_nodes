import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {DirectorWorkspace} from '../web/studio_director.js';
import {DIRECTOR_ENGINES,buildDirectorGraph,directorAvailability} from '../web/director_recipes.js';
import {FRAME_VIDEO_MODELS} from '../web/frame_video_recipes.js';
import {LTX_FRAME_VIDEO_MODELS} from '../web/ltx_frame_video_recipes.js';

const {document,window}=parseHTML('<html><body></body></html>');
window.HTMLElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:960,height:540,bottom:540,right:960});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(value){this.toggleAttribute('checked',!!value);}});
for(const method of ['pause','play','load'])window.HTMLElement.prototype[method]=()=>{};
let storage={};const localStorage={getItem:key=>storage[key]||null,setItem:(key,value)=>storage[key]=value};
Object.assign(globalThis,{window,document,localStorage,createImageBitmap:async()=>({width:1001,height:563,close(){}})});
const info=Object.fromEntries(['TrimAudioDuration','MiniMaxH3AddGuide','LTXVAudioVAEEncode','SolidMask','SetLatentNoiseMask'].map(type=>[type,{input:{required:{}}}]));
for(const engine of DIRECTOR_ENGINES)for(const node of Object.values(buildDirectorGraph({engine:engine.id,prompt:'Test',width:960,height:544,frames:engine.defaultFrames,steps:8,seed:0,clips:[]})))info[node.class_type]={input:{required:{}}};
info.UNETLoader.input.required.unet_name=[[FRAME_VIDEO_MODELS.model,LTX_FRAME_VIDEO_MODELS.model]];
info.CLIPLoader.input.required.clip_name=[[FRAME_VIDEO_MODELS.text,LTX_FRAME_VIDEO_MODELS.text]];
info.VAELoader.input.required.vae_name=[[FRAME_VIDEO_MODELS.videoVae,FRAME_VIDEO_MODELS.audioVae,LTX_FRAME_VIDEO_MODELS.videoVae,LTX_FRAME_VIDEO_MODELS.audioVae]];
info.LoraLoaderModelOnly.input.required.lora_name=[[FRAME_VIDEO_MODELS.lora]];
for(const engine of DIRECTOR_ENGINES)assert.equal(directorAvailability(info,{engine:engine.id}).ready,true);
let uploadName='anchor.png';let history={},queue={queue_running:[],queue_pending:[]};const calls=[],listeners=new Map();
const api={clientId:'director-test',apiURL:path=>path,addEventListener(type,handler){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(handler);},removeEventListener(type,handler){listeners.get(type)?.delete(handler);},fetchApi:async(path,options)=>{calls.push({path,options});assert.equal(path,'/upload/image');return{ok:true,json:async()=>({name:uploadName,subfolder:'zura_director'})};}};
function emit(type,detail){for(const handler of listeners.get(type)||[])handler({detail});}
const owner={api,app:{},studio:{close(){}},root:document.body,async fetch(path,body){calls.push({path,body});if(path==='/object_info')return info;if(path.includes('model-downloads'))return{models:[]};if(path==='/prompt'){queue.queue_pending=[[0,'director-own']];return{prompt_id:'director-own'};}if(path.startsWith('/history'))return history;if(path==='/queue'&&body?.delete){queue={queue_running:[],queue_pending:[]};return{};}if(path==='/queue')return queue;return{};}};
const ui=new DirectorWorkspace(owner);await ui.loadModels();
assert.equal(ui.draft.frames,49);assert.equal(ui.defaults({engine:'h3'}).frames,73);
assert.equal(ui.defaults({seed:0}).seed,0);
assert.equal(ui.defaults({sizePreset:'custom'}).sizePreset,'custom');
ui.setPlayhead(24);ui.add('prompt');const direction=ui.clip();assert.equal(direction.startFrame,24);
ui.$('clip-text').value='Camera moves left';ui.$('clip-text').oninput();
ui.setPlayhead(12);await ui.upload('image',new File(['image'],'source.png',{type:'image/png'}));
assert.equal(ui.clip().startFrame,12);assert.equal(ui.clip().asset.file,'zura_director/anchor.png');
assert.match(ui.$('preview').src,/filename=anchor.png&subfolder=zura_director&type=input/);
ui.$('source-size').click();const size=ui.config();assert.equal(size.outputWidth,1002);assert.equal(size.outputHeight,564);assert.equal(size.width,1024);assert.equal(size.height,576);
assert.equal(ui.$('megapixels').disabled,false,'Source dimensions still allow direct megapixel scaling');
ui.$('megapixels').value=.4;ui.$('megapixels').oninput();assert.equal(ui.draft.sourceSize,false);assert.ok(ui.config().outputWidth<1002);
ui.$('source-size').click();assert.equal(ui.config().outputWidth,1002,'The explicit source-size action restores exact dimensions');
ui.audioMetadata=async()=>({duration:1.25});uploadName='voice.wav';await ui.upload('audio',new File(['audio'],'Voice over.wav',{type:'audio/wav'}));assert.equal(ui.clip().asset.name,'Voice over.wav');assert.equal(ui.clip().asset.file,'zura_director/voice.wav');assert.equal(ui.clip().endFrame,42);assert.equal(ui.clip().audioDurationFrames,30);
// Real gesture handlers: all tracks move/resize, frame-snap, persist and cancel.
const originalClips=structuredClone(ui.draft.clips);
const image=ui.draft.clips.find(c=>c.kind==='image');
const sound=ui.draft.clips.find(c=>c.kind==='audio');
const x=frame=>14+frame*932/ui.draft.frames;
function pointer(target,frame,id=7){return{target,clientX:x(frame),pointerId:id,button:0,isPrimary:true,altKey:true,preventDefault(){}};}
function dragClip(clip,edge,from,to,cancel=false){
  const element=ui.page.querySelector(`[data-clip="${clip.id}"]`),target=edge==='move'?element:element.querySelector(`[data-edge="${edge}"]`);
  ui.$('timeline-body').onpointerdown(pointer(target,from));
  ui.$('timeline-body').onpointermove(pointer(ui.$('timeline-body'),to));
  if(cancel)ui.$('timeline-body').onpointercancel();else {ui.$('timeline-body').onpointerup(pointer(ui.$('timeline-body'),to));ui.$('timeline-body').onclick(pointer(ui.$('timeline-body'),to));}
}
assert.equal(ui.$('clip-end').disabled,false);
dragClip(image,'end',13,20);assert.equal(image.endFrame,20,'Images have editable durations');
dragClip(image,'move',15,20);assert.deepEqual([image.startFrame,image.endFrame],[17,25]);
dragClip(image,'start',17,19);assert.deepEqual([image.startFrame,image.endFrame],[19,25]);
dragClip(image,'move',20,30,true);assert.deepEqual([image.startFrame,image.endFrame],[19,25],'Cancelled drag restores original interval');
const blocker={...image,id:'blocking-image',startFrame:30,endFrame:35};ui.draft.clips.push(blocker);ui.render();
dragClip(image,'end',25,40);assert.equal(image.endFrame,30,'Image resize stops at the next image');
dragClip(image,'move',20,45);assert.equal(image.endFrame,30,'Move cannot overlap the adjacent image');
ui.draft.clips=ui.draft.clips.filter(c=>c!==blocker);
dragClip(direction,'move',25,0);assert.equal(direction.startFrame,0);assert.equal(direction.endFrame,8,'Moving preserves duration at timeline boundary');
dragClip(direction,'end',8,14);assert.equal(direction.endFrame,14);
dragClip(sound,'start',12,15);assert.equal(sound.startFrame,15);assert.equal(sound.trimStart,3,'Trimming the left edge advances the audio source offset');
const soundLength=sound.endFrame-sound.startFrame;dragClip(sound,'move',20,100);assert.equal(sound.endFrame,ui.draft.frames);assert.equal(sound.endFrame-sound.startFrame,soundLength);
ui.selectClip(image.id);ui.$('clip-end').value=27;ui.$('clip-end').onchange();assert.equal(image.endFrame,27,'Numeric image duration is no longer forced to one frame');
const timelineGraph=buildDirectorGraph({...ui.config(),prompt:"Gesture test"},info);assert.ok(Object.values(timelineGraph).some(n=>n.inputs?.timeline_data?.includes('"length":8')),'Image duration reaches the native timeline');
ui.save();const gestureReload=new DirectorWorkspace(owner);assert.deepEqual(gestureReload.draft.clips,ui.draft.clips);gestureReload.dispose();
ui.draft.clips=originalClips;ui.render();
const clips=structuredClone(ui.draft.clips),modelElement=ui.$('model');
ui.$('engine').value='h3';ui.$('engine').onchange();assert.equal(ui.draft.engine,'h3');assert.deepEqual(ui.draft.clips,clips);assert.equal(ui.$('model'),modelElement);assert.equal(ui.draft.steps,8);assert.equal(ui.$('steps').disabled,true);
ui.$('engine').value='ltx';ui.$('engine').onchange();assert.deepEqual(ui.draft.clips,clips);
ui.$('playhead-frame').value=31;ui.$('playhead-frame').onchange();assert.equal(ui.draft.playhead,31);
ui.$('timeline-body').onclick({target:ui.$('timeline-body'),clientX:480});assert.equal(ui.draft.playhead,Math.round(ui.draft.frames/2));
let pickerClicks=0;ui.$('image-file').click=()=>pickerClicks++;ui.$('timeline-body').ondblclick({target:ui.$('timeline-body'),clientX:14});assert.equal(ui.draft.playhead,0);assert.equal(pickerClicks,1);
ui.save();const restored=new DirectorWorkspace(owner);assert.deepEqual(restored.draft.clips,ui.draft.clips);assert.equal(restored.draft.engine,'ltx');assert.equal(restored.config().outputWidth,1002);restored.dispose();
ui.draft.prompt='A camera move';ui.draft.seed=0;ui.save();
// All generation is a stub; no ComfyUI prompt is sent by this test.
ui.startPolling=()=>{};await ui.generate();assert.equal(ui.job.id,'director-own');assert.equal(ui.job.config.seed,0);assert.equal(calls.filter(call=>call.path==='/prompt').length,1);
emit('progress',{prompt_id:'foreign',node:'sample',value:1,max:8});assert.notEqual(ui.$('bar').value,12.5);
emit('progress',{prompt_id:'director-own',node:'sample',value:4,max:8});assert.equal(ui.$('bar').value,50);
emit('execution_start',{prompt_id:'director-own'});emit('executing','sample');assert.match(ui.$('progress-title').textContent,/Generate LTX Director/);
history={'director-own':{status:{completed:true},outputs:{save:{videos:[{filename:'shot.mp4',subfolder:'director',type:'output'}]}}}};await ui.poll();assert.equal(ui.job,null);assert.equal(ui.items.length,1);assert.equal(ui.$('result').hidden,false);
const video=ui.$('result');let srcWrites=0;const setAttribute=video.setAttribute.bind(video);video.setAttribute=(name,value)=>{if(name==='src')srcWrites++;return setAttribute(name,value);};ui.render();ui.setPlayhead(10);assert.equal(srcWrites,0,'Control updates retain current video transport');
const reloaded=new DirectorWorkspace(owner);assert.equal(reloaded.$('result').hidden,false);assert.equal(reloaded.items[0].file.filename,'shot.mp4');reloaded.dispose();
assert.equal(ui.reset(),true);assert.equal(ui.$('result').hidden,true);assert.equal(ui.$('preview').hidden,true);assert.equal(ui.draft.clips.length,0);assert.equal(ui.draft.prompt,'');assert.equal(ui.items.length,1);ui.$('history-toggle').click();assert.equal(ui.$('history').querySelectorAll('[data-result]').length,1);const resetReload=new DirectorWorkspace(owner);assert.equal(resetReload.$('result').hidden,true,'Reset remains empty after reopening');assert.equal(resetReload.items.length,1);resetReload.dispose();
ui.job={id:'cancel-own',started:Date.now(),config:ui.config()};history={};queue={queue_running:[[0,'cancel-own']],queue_pending:[]};await ui.cancel();assert.equal(ui.job,null);assert.deepEqual(calls.find(call=>call.path==='/interrupt').body,{prompt_id:'cancel-own'});assert.equal(ui.items.length,1);
// A late history response from an old job cannot become the new run's result.
let finishHistory;const originalFetch=ui.fetch.bind(ui);ui.fetch=path=>path.startsWith('/history/')?new Promise(resolve=>finishHistory=resolve):originalFetch(path);ui.job={id:'stale',config:ui.config()};const polling=ui.poll();const current={id:'current',config:ui.config()};ui.job=current;finishHistory({stale:{status:{completed:true},outputs:{save:{videos:[{filename:'stale.mp4'}]}}}});await polling;assert.equal(ui.job,current);assert.equal(ui.items.length,1);
ui.job=null;ui.dispose();assert.equal([...listeners.values()].reduce((sum,value)=>sum+value.size,0),0);
console.log('Director workspace regression checks passed (stubbed generation).');

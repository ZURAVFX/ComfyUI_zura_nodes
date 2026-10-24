import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source=fs.readFileSync(new URL("../web/studio.js",import.meta.url),"utf8")
  .replace(/^import .*;\r?\n/gm,"").split("app.registerExtension({")[0];
const context={api:{},document:{},crypto:{randomUUID:()=>"request-key"},FormData,Blob,URLSearchParams,AbortController,setInterval,clearInterval,setTimeout,clearTimeout};
vm.createContext(context);vm.runInContext(source+"\nthis.Studio=ArtistStudio;",context);

function makeStudio(fetchApi=async()=>({ok:true,json:async()=>({phase:"error"})})){
  const removed=[],fields=new Map();
  for(const id of ["audio-settings","source","character","ready","audio","opening-file","voice-sample","voice-script","voice-transcript","voice-mode","voice-clone-fields","voice-sample-name","voice-note","source-poster","ready-image","opening","takes"]){
    fields.set(id,{value:"private value",textContent:"private value",hidden:false,open:true,innerHTML:"private media",removeAttribute(name){if(name==="src")this.src="";},src:"old-media"});
  }
  context.api={clientId:"client",fetchApi};
  context.localStorage={removeItem:key=>removed.push(key)};
  const ui=Object.create(context.Studio.prototype);
  Object.assign(ui,{project:null,source:{id:"src",name:"source.mp4"},character:{id:"char"},audio:{id:"audio"},pendingReference:true,
    voiceJob:{id:"voice-job"},voiceSample:{id:"private-sample"},config:{start:12,finished_frame_number:8,mask_points:[{x:.2,y:.3}]},preview:"source",lastVideo:"old-video",
    references:[{id:"ref"}],readyAsset:{id:"ready"},lookMode:"ready",referenceFingerprint:"old-ref",resultFingerprint:"old-results",reviewPreviewKey:"old-review",
    pointFrameStart:9,voicePolling:true,polling:true,busy:false,resetEpoch:0,resetting:false,activeDialog:null,modelStatus:{ready:true},
    container:{querySelector:selector=>selector==='[data-step="0"]'?{click(){ui.sourceClicked=true;}}:{click(){ui.sourceClicked=true;}}}});
  ui.$=id=>fields.get(id) || (fields.set(id,{value:"",textContent:"",hidden:false,open:false,innerHTML:"",classList:{remove(){}},removeAttribute(){}}),fields.get(id));
  ui.syncForm=()=>{ui.synced=true;};ui.render=()=>{ui.rendered=(ui.rendered||0)+1;};ui.message=(text,error=false)=>{ui.lastMessage=text;ui.lastMessageError=error;};
  return {ui,fields,removed};
}

const calls=[];
{
  const {ui,fields,removed}=makeStudio(async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({id:"render-7",phase:"error",results:[{url:"saved-result"}]})};});
  ui.project={id:"render-7",phase:"working"};
  assert.equal(await ui.reset(),true);
  assert.deepEqual(calls.map(call=>call.url),["/zura/studio/projects/render-7/cancel"],"only the active Studio project is cancelled");
  assert.equal(ui.project,null);assert.equal(ui.source,null);assert.equal(ui.character,null);assert.equal(ui.audio,null);
  assert.equal(ui.voiceJob,null);assert.equal(ui.voiceSample,null);assert.equal(ui.pendingReference,false);
  assert.equal(Array.from(ui.references).length,0);assert.equal(ui.readyAsset,null);assert.equal(ui.lookMode,"build");
  assert.equal(ui.config.start,0);assert.equal(ui.config.finished_frame_position,"first");assert.equal(ui.config.finished_frame_number,1);
  assert.equal(ui.preview,"mask");assert.equal(ui.reviewPreviewKey,null);assert.equal(ui.voicePolling,false);assert.equal(ui.polling,false);
  assert.deepEqual(removed,["genj-studio-project","zura-studio-voice-job"]);
  for(const id of ["source","character","ready","audio","opening-file","voice-sample"])assert.equal(fields.get(id).value,"");
  assert.equal(fields.get("voice-script").value,"");assert.equal(fields.get("voice-transcript").value,"");
  assert.equal(fields.get("takes").innerHTML,"");assert.equal(ui.sourceClicked,true);
}

{
  const {ui}=makeStudio(async()=>{throw new Error("ComfyUI is offline");});
  const originalProject={id:"still-running",phase:"working"},originalSource=ui.source,originalAudio=ui.audio;
  ui.project=originalProject;
  assert.equal(await ui.reset(),false);
  assert.equal(ui.project,originalProject,"keep the running shot when cancellation fails");
  assert.equal(ui.source,originalSource);assert.equal(ui.audio,originalAudio);assert.equal(ui.resetting,false);assert.equal(ui.busy,false);
  assert.match(ui.lastMessage,/ComfyUI is offline/);
}

{
  let finishAction;
  const urls=[];
  const {ui}=makeStudio(async(url)=>{
    urls.push(url);
    if(url.endsWith("/action"))return await new Promise(resolve=>{finishAction=()=>resolve({ok:true,json:async()=>({id:"old-project",phase:"working"})});});
    return {ok:true,json:async()=>({id:"old-project",phase:"error"})};
  });
  ui.project={id:"old-project",phase:"approved"};
  const pending=ui.run("design");
  await Promise.resolve();
  assert.equal(await ui.reset(),true);
  finishAction();await pending;
  assert.equal(ui.project,null,"late action response cannot restore a reset project");
  assert.deepEqual(urls,["/zura/studio/projects/old-project/action","/zura/studio/projects/old-project/cancel"],"cancel a render that was queued after reset began");
}

{
  let finishUpload;
  const {ui}=makeStudio(async(url)=>{
    assert.match(url,/\/upload\?kind=video/);
    return await new Promise(resolve=>{finishUpload=()=>resolve({ok:true,json:async()=>({id:"late-source",file:"upload/video.mp4",name:"old.mp4",duration:4})});});
  });
  const pending=ui.upload("source",new Blob(["video"],{type:"video/mp4"}));
  await Promise.resolve();
  assert.equal(await ui.reset(),true);
  finishUpload();await pending;
  assert.equal(ui.source,null,"late upload response cannot repopulate the new shot");
  assert.equal(ui.busy,false);
}

{
  const {ui,fields}=makeStudio();ui.config.image_prompt='Keep my revised direction';
  const refs=ui.references,audio=ui.audio;ui.project={id:'previous',phase:'opening'};
  ui.removeInput('source');assert.equal(ui.source,null);assert.equal(ui.project,null);
  assert.equal(ui.references,refs);assert.equal(ui.audio,audio);assert.equal(ui.config.start,0);
  assert.equal(ui.config.mask_points.length,0);assert.equal(ui.config.image_prompt,'Keep my revised direction');
  assert.equal(fields.get('source').value,'');
  ui.removeInput('character');assert.equal(ui.references.length,0);assert.equal(fields.get('character').value,'');
  ui.removeInput('ready');assert.equal(ui.readyAsset,null);assert.equal(ui.lookMode,'build');
}
{
  const {ui}=makeStudio();ui.project={id:'active',phase:'working'};
  ui.removeInput('source');assert.equal(ui.source.id,'src');assert.equal(ui.project.id,'active');
}
{
  const {ui,fields}=makeStudio();ui.lookMode='build';ui.config.workflow_mode='swap';
  let focused=false;fields.set('image_prompt',{focus(){focused=true;}});
  ui.project={opening_input:{file:'old-result.png'},phase:'opening'};
  ui.editStartingFrame();assert.equal(ui.promptStage,'image');assert.equal(ui.preview,'original');
  assert.equal(ui.project.opening_input.file,'old-result.png','Retain previous result for Keep current image without making it the retry input');
  assert.equal(focused,true);
}
{
  const {ui}=makeStudio();ui.lookMode='build';ui.project={id:'prepared',phase:'opening'};
  ui.config.image_prompt='Keep this direction';ui.readConfig=()=>({...ui.config});
  const source=ui.source,refs=ui.references;
  ui.changeOpeningModel('qwen2511');
  assert.equal(ui.config.opening_model,'qwen2511');assert.equal(ui.config.image_prompt,'Keep this direction');
  assert.equal(ui.source,source);assert.equal(ui.references,refs);assert.equal(ui.project.id,'prepared','A model change reuses source preparation');
  assert.equal(ui.promptStage,'image');assert.equal(ui.preview,'original');
  ui.project.phase='working';ui.changeOpeningModel('qwen21');assert.equal(ui.config.opening_model,'qwen2511');
}
console.log("Input removal and model changes preserve the other inputs; image retries use the original source.");

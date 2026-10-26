import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'').split('app.registerExtension({')[0];
const context={FormData,URLSearchParams,AbortController,setInterval,clearInterval,setTimeout,clearTimeout,localStorage:{removeItem(){}}};
vm.createContext(context);vm.runInContext(source+'\nthis.Studio=ArtistStudio;',context);
for(const type of ['source','character','ready','audio']){
  const input={},classes=new Set(),drop={classList:{add:c=>classes.add(c),remove:c=>classes.delete(c)}};
  const ui=Object.create(context.Studio.prototype),uploads=[];ui.$=id=>id===type?input:drop;ui.upload=(...args)=>uploads.push(args);ui.bindUpload(type);
  const files=[{name:type==='source'?'source.mp4':'reference.png'},{name:'second.png'}];
  const event={target:{files,value:'selected'},dataTransfer:{files},preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
  drop.ondragover(event);assert.equal(event.stopped,true);assert.equal(event.prevented,true);assert.equal(event.dataTransfer.dropEffect,'copy');assert.ok(classes.has('dragging'));
  event.stopped=false;drop.ondrop(event);assert.equal(event.stopped,true,'Comfy graph importer must not receive a Studio media drop');assert.equal(classes.has('dragging'),false);
  assert.equal(uploads[0][0],type);assert.deepEqual(Array.from(type==='character'?uploads[0][1]:[uploads[0][1]]),type==='character'?files:[files[0]]);
  event.stopped=false;input.onchange(event);assert.equal(event.stopped,true);assert.equal(event.target.value,'');assert.equal(uploads.length,2,'File picker and drop use the same upload function');
  drop.ondrop({...event,dataTransfer:{files:[],items:files.map(file=>({kind:'file',getAsFile:()=>file}))}});assert.equal(uploads.length,3,'Accept file items when the host exposes an empty FileList');
}
// Exercise the complete client upload path: a returned video updates the source,
// resets the old shot and retains a working thumbnail URL for the loaded clip.
const ui=Object.create(context.Studio.prototype);const calls=[];
context.api={apiURL:p=>p,fetchApi:async(path,options)=>{calls.push(path);assert.equal(options.body.get('file').name,'source.mp4');return {ok:true,json:async()=>({id:'video',file:'genj_studio/video/reference.mp4',duration:15,thumbnail_url:'/view?thumbnail'})};}};
Object.assign(ui,{resetEpoch:0,resetting:false,busy:false,project:{phase:'done'},config:{duration:9,start:4},message(){},render(){},syncForm(){this.synced=true;}});
await ui.upload('source',new File(['video bytes'],'source.mp4',{type:'video/mp4'}));
assert.deepEqual(calls,['/zura/studio/upload?kind=video']);assert.equal(ui.source.id,'video');assert.equal(ui.source.thumbnail_url,'/view?thumbnail');assert.equal(ui.project,null);assert.equal(ui.config.duration,2);assert.equal(ui.config.start,0);assert.equal(ui.busy,false);assert.equal(ui.synced,true);
ui.message=(text,error)=>{ui.notice=text;ui.noticeError=error;};
await ui.upload('source',undefined);assert.match(ui.notice,/No file was received/);
ui.busy=true;await ui.upload('source',new File(['x'],'clip.mp4'));assert.match(ui.notice,/Wait for/);
ui.busy=false;ui.project={phase:'working'};await ui.upload('source',new File(['x'],'clip.mp4'));assert.match(ui.notice,/Cancel/);assert.equal(calls.length,1,'Never replace media during an active run');
ui.project=null;
await ui.upload('source',{size:2*1024**3+1,name:'huge.mp4'});assert.match(ui.notice,/larger than 2 GB/);assert.equal(calls.length,1,'Reject oversized files before transferring bytes');
const notices=[];ui.message=text=>notices.push(text);
context.api.fetchApi=async(path,options)=>{assert.ok(options.signal);assert.equal(options.timeoutMs,null,'Large uploads must bypass the default one-minute JSON timeout');const error=new Error('timeout');error.name='AbortError';throw error;};
await ui.upload('source',new File(['x'],'clip.mp4'));assert.ok(notices.some(t=>/clip.mp4.*MB.*0s/.test(t)));assert.ok(notices.some(t=>/Loading was stopped/.test(t)));assert.equal(ui.busy,false,'An aborted upload must not lock the next upload');
console.log('Studio file picker/drop ownership and MP4 upload-to-thumbnail handoff pass.');

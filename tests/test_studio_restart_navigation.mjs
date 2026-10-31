import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {
  installStudioRestartNavigation,
  resetStudioWorkspace,
} from '../web/studio_restart.js';

const {document} = parseHTML('<!doctype html><html><head></head><body></body></html>');
Object.defineProperty(document.defaultView.HTMLSelectElement.prototype,'value',{
  configurable:true,
  get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},
  set(value){
    this.querySelectorAll('option').forEach(option=>{
      if(option.value===String(value))option.setAttribute('selected','');
      else option.removeAttribute('selected');
    });
  },
});
const storage=new Map();
Object.assign(globalThis,{
  document,
  window:document.defaultView,
  localStorage:{
    getItem:key=>storage.get(key)??null,
    setItem:(key,value)=>storage.set(key,String(value)),
    removeItem:key=>storage.delete(key),
  },
});

function input(id,value,defaultValue=value){
  const node=document.createElement('input');
  node.id=id;
  node.value=value;
  node.defaultValue=defaultValue;
  return node;
}

const root=document.createElement('div');
root.id='genj-studio';
const imagePage=document.createElement('section');
imagePage.className='zc-image-page';
const prompt=input('zc-prompt','Change this image','');
const model=document.createElement('select');
model.id='zc-model';
model.innerHTML='<option value="flux3">Flux 3</option><option value="qwen2511">Qwen 2511</option>';
model.value='qwen2511';
const width=input('zc-width','768');
imagePage.append(prompt,model,width);
const videoPage=document.createElement('section');
videoPage.className='gs-workspace';
const videoPrompt=input('gs-prompt','Keep this video prompt');
videoPage.append(videoPrompt);
root.append(imagePage,videoPage);

const gallery=document.createElement('div');
gallery.id='zc-gallery';
const empty=document.createElement('div');
empty.id='zc-image-empty';
empty.hidden=true;
let savedImage=null;
let shown=null;
const imageCreative={
  mode:'image',
  root,
  imageOperation:'edit',
  draft:{model:'qwen2511',operation:'edit'},
  job:{id:'image-job'},
  pendingSubmission:{id:'pending'},
  submitting:true,
  uploading:true,
  references:[{file:'reference.png'}],
  imageLoras:[{name:'portrait.safetensors'}],
  selectedImage:1,
  imageSizeRatio:1.5,
  $(id){return ({"image-empty":empty,gallery,prompt,model,width})[id]||root.querySelector('#'+id);},
  stopPolling(){this.stopped=true;},
  save(){savedImage={draft:{...this.draft},items:this.items,job:this.job,pendingSubmission:this.pendingSubmission};},
  renderGallery(){gallery.innerHTML='<figure>old result</figure>';},
  render(){this.rendered=true;},
  message(text){this.messageText=text;},
  show(mode){shown=mode;},
};
imageCreative.items=[{file:{filename:'old.png'}}];

assert.equal(await resetStudioWorkspace(imageCreative),true);
assert.equal(imageCreative.imageOperation,'edit','Reset preserves the Image create/edit operation');
assert.equal(model.value,'qwen2511','Reset preserves a valid selected image model');
assert.equal(prompt.value,'','Reset clears the current image prompt');
assert.equal(width.value,'768','Reset restores the default image dimensions');
assert.equal(videoPrompt.value,'Keep this video prompt','Image reset does not touch other workspaces');
assert.equal(imageCreative.selectedImage,-1,'Reset presents no old selected result');
assert.equal(gallery.innerHTML,'','Reset clears the current canvas even while History retains thumbnails');
assert.equal(empty.hidden,false);
assert.equal(savedImage.draft.operation,'edit');
assert.equal(savedImage.draft.model,'qwen2511');
assert.equal(savedImage.items.length,1,'Reset preserves saved image history');
assert.equal(shown,'image');

function workspaceResetFixture(mode,className){
  const page=document.createElement('section');
  page.className=className;
  const prompt=input(mode+'-prompt','old prompt','');
  const task=document.createElement('select');
  task.id='zc-video-task';
  task.innerHTML='<option value="frames">First &amp; last frame</option><option value="references">Reference to video</option>';
  task.value=mode;
  page.append(prompt,task);
  const fields={
    result:{hidden:false,src:'old.mp4',pause(){this.paused=true;},removeAttribute(name){if(name==='src')this.src='';},load(){}},
    empty:{hidden:true},
  };
  let saves=0;
  const workspace={
    page,
    assets:mode==='frames'?{first:{file:'first.png'}}:{images:[{file:'image.png'}]},
    $(id){return fields[id]||page.querySelector('#'+id);},
    stopPolling(){this.stopped=true;},
    selectAvailability(){this.available=true;},
    renderHistory(){this.historyRendered=true;},
    save(){saves++;this.saved=true;},
    render(){this.rendered=true;},
    preview(){this.previewed=true;},
    message(text){this.messageText=text;},
  };
  return {workspace,page,prompt,task,saves:()=>saves};
}

const frames=workspaceResetFixture('frames','zf-page');
const framesCreative={mode:'frames',frames:frames.workspace,show(mode){shown=mode;}};
assert.equal(await resetStudioWorkspace(framesCreative),true);
assert.equal(frames.prompt.value,'');
assert.equal(frames.task.value,'frames','Frame reset keeps the shared workflow selector');
assert.equal(frames.saves(),1,'Frame reset persists the cleared draft');

const references=workspaceResetFixture('references','zf-page zr-page');
const referenceCreative={mode:'references',referencesVideo:references.workspace,show(mode){shown=mode;}};
assert.equal(await resetStudioWorkspace(referenceCreative),true);
assert.equal(references.prompt.value,'');
assert.equal(references.task.value,'references','Reference reset keeps the shared workflow selector');
assert.equal(references.saves(),1,'Reference reset persists the cleared draft');

for(const key of ['zura-outpaint-hdr-record','zura-outpaint-hdr-take','zura-outpaint-hdr-job','zura-outpaint-hdr-request'])storage.set(key,'old');
let oldClosed=false,oldDisposed=false,newConstructed=0;
class OutpaintCtor{
  constructor(owner){this.owner=owner;newConstructed++;}
  save(){this.saved=true;}
}
const oldOutpaint={constructor:OutpaintCtor,close(){oldClosed=true;},dispose(){oldDisposed=true;}};
const outpaintCreative={
  mode:'outpaint',
  outpaint:oldOutpaint,
  show(mode){shown=mode;},
};
assert.equal(await resetStudioWorkspace(outpaintCreative),true);
assert.equal(oldClosed,true);
assert.equal(oldDisposed,true);
assert.equal(newConstructed,1);
assert.equal(outpaintCreative.outpaint.saved,true);
for(const key of ['zura-outpaint-hdr-record','zura-outpaint-hdr-take','zura-outpaint-hdr-job','zura-outpaint-hdr-request'])assert.equal(storage.has(key),false);

let hdrResetOptions=null;
const hdrCreative={
  mode:'hdr',
  studio:{hdrTool:{async reset(options){hdrResetOptions=options;return true;}}},
  show(mode){shown=mode;},
};
assert.equal(await resetStudioWorkspace(hdrCreative),true);
assert.deepEqual(hdrResetOptions,{keepSource:false});

const videoStudio={
  config:{workflow_mode:'relight',engine:'h3',relight_engine:'wan21',resolution:1280},
  navigationStep:1,
  async reset(){this.config={workflow_mode:'motion',engine:'wan'};return true;},
  syncForm(){this.synced=true;},
  render(){this.rendered=true;},
};
assert.equal(await resetStudioWorkspace({mode:'video',studio:videoStudio}),true);
assert.equal(videoStudio.config.workflow_mode,'relight');
assert.equal(videoStudio.config.engine,'h3','Relight keeps H3 as the Studio route');
assert.equal(videoStudio.config.relight_engine,'wan21','Relight keeps Wan 2.1 as the native relight engine');
assert.equal(videoStudio.navigationStep,null);

const topActions=document.createElement('div');
topActions.className='gs-top-actions';
const exit=document.createElement('button');
exit.id='gs-exit';
const primary=document.createElement('button');
primary.id='gs-primary';
topActions.append(primary,exit);
const navRoot=document.createElement('div');
navRoot.id='genj-studio';
navRoot.append(topActions);
document.body.append(navRoot);
let selectedPanel='';
let renders=0;
const studio={
  creative:{
    root:navRoot,
    mode:'video',
    selectPanel(name){selectedPanel=name;},
    show(){},
  },
  source:{id:'source'},
  project:{phase:'done',opening_url:'/opening.png',results:[{url:'/result.mp4'}]},
  frameAccepted:()=>true,
  $(id){return id==='primary'?primary:null;},
  render(){renders++;},
};
studio.creative.studio=studio;
const controller=installStudioRestartNavigation(studio);
assert.equal(controller.navigateStep(2),true);
assert.equal(studio.navigationStep,2);
assert.equal(studio.preview,'look');
assert.equal(selectedPanel,'settings');
studio.busy=true;
assert.equal(controller.navigateStep(0),false,'Navigation is locked while a run owns the workspace');
studio.busy=false;
assert.equal(controller.navigateStep(0),true);
assert.equal(studio.navigationStep,0);
assert.equal(studio.preview,'original','Source navigation explicitly shows source playback, not a stale look');
assert.equal(selectedPanel,'source');
assert.equal(controller.navigateStep(2),false,'Forward navigation cannot claim uncompleted stages');
primary.click();
assert.equal(studio.navigationStep,null,'Starting the next action clears a backward-navigation override');
assert.equal(renders,2);
controller.dispose();

console.log('Studio restart resets preserve mode state, persist cleared drafts, and expose guarded backward navigation.');

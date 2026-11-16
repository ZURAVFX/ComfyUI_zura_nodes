import assert from 'node:assert/strict';
import {PaintoutMaskViewer} from '../web/paintout_studio/paintout_viewer.js';
import {StudioPaintDisplayBinding,paintPreviewSource} from '../web/studio_display_binding.js';
import {StudioDisplaySettings} from '../web/studio_display_settings.js';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';

const origin='http://127.0.0.1:8188';
const sourceURL=origin+'/zura/paintout/frame-preview?'+new URLSearchParams({file:'C:\\source.mkv',frame:'7',space:'srgb_display',size:'1280'});
const candidateURL=origin+'/zura/paintout/frame-preview?'+new URLSearchParams({file:'C:\\accepted.png',frame:'0',space:'srgb_display',size:'1280'});
assert.equal(paintPreviewSource('https://elsewhere.invalid/zura/paintout/frame-preview?file=x&frame=0',origin),null);
assert.equal(paintPreviewSource(origin+'/zura/paintout/frame-preview?file=x&frame=-1',origin),null);
assert.deepEqual(paintPreviewSource(sourceURL,origin),{file:'C:\\source.mkv',frame:7,space:'srgb_display'});

const dom=parseHTML('<html><body><section class="zp-page"><div class="zf-viewer"><div id="zps-image-slot"><img></div><video id="zps-video"></video></div></section></body></html>');
Object.defineProperty(dom.window,'location',{configurable:true,value:{origin}});
const image=dom.document.querySelector('#zps-image-slot img'),video=dom.document.querySelector('#zps-video');
image.src=sourceURL;
const paintWorkspace={page:dom.document.querySelector('.zp-page'),view:'source',state:{source:'C:\\source.mkv',sourceColour:'srgb_display',anchors:[{file:'C:\\accepted.png'}]},sourceInfo:{display_source:'source-grant'},
  resultPreviewFile:()=>({filename:'paintout.mp4',subfolder:'ZURA STUDIO',type:'output'})};
const selectorSettings=Object.assign(Object.create(StudioDisplaySettings.prototype),{
  root:dom.document.body,owner:{paintout:paintWorkspace},paintBindings:new Map(),choices:()=>({original:null,result:null})});
assert.equal(selectorSettings.currentFor(image).paint.frame,7,'The normal Paintout image binds its actual source frame.');
assert.equal(selectorSettings.mediaTarget(image).selected.paint.file,'C:\\source.mkv','Right-click targets the real visible Paintout image.');
assert.deepEqual(selectorSettings.currentFor(video).selector,{source_token:'source-grant'});
paintWorkspace.view='anchor';image.src=candidateURL;
assert.equal(selectorSettings.currentFor(image).paint.file,'C:\\accepted.png');
image.src=origin+'/zura/paintout/frame-preview?'+new URLSearchParams({file:'C:\\unselected.png',frame:'0',space:'srgb_display'});
assert.equal(selectorSettings.currentFor(image),null,'A thumbnail URL cannot grant an unselected local file.');
paintWorkspace.view='result';
assert.deepEqual(selectorSettings.currentFor(video).selector,{file:{filename:'paintout.mp4',subfolder:'ZURA STUDIO',type:'output'}});

const images=[];
globalThis.Image=class {
  set src(value){this._src=value;images.push(this);queueMicrotask(()=>this.onload?.());}
  get src(){return this._src;}
};
let id=0;const oldCreate=URL.createObjectURL,oldRevoke=URL.revokeObjectURL,revoked=[];
URL.createObjectURL=()=>`blob:display-${++id}`;URL.revokeObjectURL=value=>revoked.push(value);
const drawn=[];
const viewer=Object.assign(Object.create(PaintoutMaskViewer.prototype),{
  root:{title:'',closest:()=>null},image:{name:'original'},displaySourceURL:sourceURL,version:1,colourVersion:0,
  ctx:{clearRect(){},drawImage(image){drawn.push(image);},save(){},restore(){}},
  cssWidth:100,cssHeight:100,width:100,height:100,opacity:.45,overlay:{name:'mask'},tool:'brush',positive:[],negative:[],
  transform:()=>({x:0,y:0,scale:1}),buildOverlay(){},
});
const preset={config:'adobe-ae://fixture',display:'sRGB',view:'View'};
let selection=preset,revision=1;const requests=[],inspected=[];
const settings={closed:false,root:{contains:()=>true,ownerDocument:{defaultView:{location:{origin}}}},
  displayStore:{get:()=>({selection,revision})},
  api:{fetchApi:async(path,options)=>{requests.push({path,body:JSON.parse(options.body)});return {ok:true,blob:async()=>new Blob(['display'])};}},
  response:async response=>response};
const workspace={page:{hidden:false},state:{source:'C:\\source.mkv',anchors:[{file:'C:\\accepted.png'}]},sourceInfo:{display_source:'source-grant'},
  info:async file=>{inspected.push(file);return {display_source:'candidate-grant'};}};
const binding=new StudioPaintDisplayBinding(settings,workspace,viewer);
const flush=async()=>{await new Promise(resolve=>setTimeout(resolve,100));for(let i=0;i<3;i++)await new Promise(resolve=>setImmediate(resolve));};
await flush();
assert.equal(requests.length,1);
assert.deepEqual(requests[0].body,{source:{source_token:'source-grant'},frame:7,colour_space:'srgb_display',...preset});
assert.equal(viewer.image.name,'original','The actual source bitmap is retained for editing.');
assert.equal(drawn.at(-2),images.at(-1),'The selected display bitmap is drawn beneath the mask.');
assert.equal(drawn.at(-1),viewer.overlay,'The editable mask is drawn after the display bitmap.');
assert.deepEqual(revoked,['blob:display-1']);

selection=null;revision++;binding.refresh();
assert.equal(viewer.colourImage,null);
assert.equal(drawn.at(-2),viewer.image,'None restores original pixels in the canvas.');
viewer.displaySourceURL=candidateURL;viewer.onDisplaySourceChange();selection=preset;revision++;binding.refresh();await flush();
assert.deepEqual(inspected,['C:\\accepted.png']);
assert.deepEqual(requests[1].body,{source:{source_token:'candidate-grant'},frame:0,colour_space:'srgb_display',...preset});
assert.equal(viewer.image.name,'original');
assert.equal(drawn.at(-2),images.at(-1));
binding.close();assert.equal(viewer.onDisplaySourceChange,null);assert.equal(viewer.colourImage,null);
URL.createObjectURL=oldCreate;URL.revokeObjectURL=oldRevoke;
console.log('Paintout canvas colour: current scoped source and accepted frame, actual background draw beneath mask, None identity and source retention passed');

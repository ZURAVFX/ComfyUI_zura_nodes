import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {ImageEditArea} from '../web/studio_image_area.js';
import {StudioImageLayers} from '../web/studio_image_layers.js';

const {document}=parseHTML('<html><body><main><div class="zc-image-tools"></div><div id="source"></div></main></body></html>');
globalThis.document=document;
if(!globalThis.crypto?.randomUUID)globalThis.crypto={randomUUID:()=> 'area-size-test'};
const root=document.querySelector('main');
const source={filename:'large.png',subfolder:'zura_images/references',file:'zura_images/references/large.png',width:3072,height:2048};
const uploads=[];
const owner={root,mode:'image',imageOperation:'edit',editMainMissing:false,references:[source],draft:{},items:[],selectedImage:-1,
  editInputs:{source:document.querySelector('#source'),showSource:false},
  api:{apiURL:value=>value,async fetchApi(path,{body}){
    assert.equal(path,'/upload/image');uploads.push(body.get('image'));
    return {ok:true,json:async()=>({name:'large-area.png',subfolder:'zura_images/edit_areas'})};
  }},
  save(){},render(){},message(value){throw Error(value);},$(id){return root.querySelector('#'+id);}};
const area=new ImageEditArea(owner);
area.restore({enabled:true,source_key:source.file});
const proxyMask={width:2048,height:1365,toBlob(){throw Error('Proxy mask must not be uploaded.');}};
area.viewer={width:2048,height:1365,sourceWidth:3072,sourceHeight:2048,maskCanvas:proxyMask,maskPresent:true,history:[],
  measureMask(){return true;},measureSketch(){return false;},setTool(){},dispose(){}};
const originalCreate=document.createElement.bind(document),draws=[];
document.createElement=(tag,...args)=>{
  if(tag!=='canvas')return originalCreate(tag,...args);
  const canvas={width:0,height:0};
  canvas.getContext=()=>({imageSmoothingEnabled:true,drawImage(...args){draws.push({canvas,args,smoothing:this.imageSmoothingEnabled});}});
  canvas.toBlob=callback=>callback(new Blob([JSON.stringify({width:canvas.width,height:canvas.height})],{type:'image/png'}));
  canvas.toDataURL=()=> 'data:image/png;base64,source-sized';
  return canvas;
};
area.changed({kind:'area'});clearTimeout(area.saveTimer);
const saved=await area.persist();
assert.equal(saved.file,'zura_images/edit_areas/large-area.png');
assert.equal(uploads.length,1);
assert.deepEqual(JSON.parse(await uploads[0].text()),{width:3072,height:2048},'The uploaded mask uses full source dimensions');
assert.equal(draws.length,1);
assert.equal(draws[0].smoothing,false,'Nearest-neighbour scaling preserves the selected binary region');
assert.deepEqual(draws[0].args,[proxyMask,0,0,3072,2048],'The proxy is mapped directly to the full source raster');
assert.equal(proxyMask.width,2048,'The responsive painting canvas is retained');

let composeRequest;
const layers=Object.create(StudioImageLayers.prototype);
layers.owner={async fetch(path,body){
  assert.equal(path,'/zura/studio/image-layers/compose');composeRequest=body;
  return {hasAlpha:false,source_sha256:'a'.repeat(64),colour:{encoding:'srgb_display',sceneLinear:false},
    width:3072,height:2048,sourceWidth:3072,sourceHeight:2048,
    master:{filename:'master.exr',type:'output'},preview:{filename:'preview.png',type:'output'},
    conditioningInput:{filename:'condition.png',type:'input'},applied:body.layers.map(layer=>({...layer}))};
}};
layers.conditioning=async result=>result.conditioningInput;
const config={operation:'edit',image_intent:'standard',prompt:'Change this area',references:[source],edit_area:{enabled:true,mask:saved},
  image_layer_base:{schemaVersion:1,source:{filename:source.filename,subfolder:source.subfolder,type:'input'},source_colour:'srgb_display',width:3072,height:2048,layers:[]}};
const accepted=await layers.accept(config,{filename:'generated.png',type:'output'});
assert.equal(composeRequest.width,3072);assert.equal(composeRequest.height,2048);
assert.equal(composeRequest.layers[0].mask.filename,saved.filename,'The real accept path sends the source-sized uploaded selection');
assert.equal(accepted.master.filename,'master.exr','A valid composite becomes the retained master');

// A source reference may omit dimensions; the loaded viewer retains the verified
// natural size and the source-bound layer mask must use it after painting.
owner.references=[{...source,width:undefined,height:undefined}];
area.viewer.sourceKey=source.file;
const originalImage=globalThis.Image;
globalThis.Image=class {set src(value){this.url=value;this.onload();}};
try{
  assert.equal(await area.layerMask(),'data:image/png;base64,source-sized');
  assert.equal(draws.at(-1).canvas.width,3072);assert.equal(draws.at(-1).canvas.height,2048);
  assert.equal(draws.at(-1).smoothing,false);
  assert.deepEqual(draws.at(-1).args.slice(1),[0,0,3072,2048]);
  area.viewer.sourceKey='another-source';
  await assert.rejects(area.layerMask(),/valid whole-pixel dimensions/,'A stale viewer cannot supply missing source dimensions');
}finally{globalThis.Image=originalImage;owner.references=[source];area.viewer.sourceKey=source.file;}

area.viewer.sourceWidth=5000;area.viewer.sourceHeight=4000;
area.changed({kind:'area'});clearTimeout(area.saveTimer);
await assert.rejects(area.persist(),/16 MP editable-layer limit/);
assert.equal(uploads.length,1,'An unsupported source never uploads a downsized mask');
document.createElement=originalCreate;
console.log('Image Paint Area uploads a source-sized nearest-neighbour mask and rejects unsupported dimensions.');

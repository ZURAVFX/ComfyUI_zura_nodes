import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {frameSourceResolution,frameOutputSize} from '../web/frame_source_resolution.js';
import {ENDPOINT_RECIPES} from '../web/video_recipe_catalog.js';
import {FrameVideoWorkspace} from '../web/studio_frames.js';

for(const cap of ENDPOINT_RECIPES){
  const exact=frameSourceResolution({width:1920,height:1080},cap);
  assert.deepEqual([exact.outputWidth,exact.outputHeight],[1920,1080]);
  assert.equal(exact.height%cap.dimensionStep,0);
  for(const source of [{width:1136,height:1760},{width:3840,height:2160},{width:8000,height:5000},{width:100,height:2000}]){
    for(const mp of [null,.25,1.35,4.35,8.35]){
      const size=frameSourceResolution(source,cap,mp);
      assert.ok(size.width*size.height<=cap.maxPixels);
      assert.ok(size.width<=cap.maxDimension&&size.height<=cap.maxDimension);
      assert.equal(size.width%cap.dimensionStep,0);assert.equal(size.height%cap.dimensionStep,0);
      assert.ok(Math.abs(size.outputWidth/size.outputHeight-source.width/source.height)<.02);
      assert.deepEqual(frameOutputSize(size),{width:size.outputWidth,height:size.outputHeight});
    }
  }
}
assert.equal(frameSourceResolution({},ENDPOINT_RECIPES[0]),null);
assert.deepEqual(frameOutputSize({width:512,height:512}),null);
assert.throws(()=>frameOutputSize({width:512,height:512,outputWidth:512}));
assert.throws(()=>frameOutputSize({width:512,height:512,outputWidth:514,outputHeight:512}));
assert.throws(()=>frameOutputSize({width:512,height:512,outputWidth:511,outputHeight:512}));

const {document,window}=parseHTML('<html><body></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(v){for(const o of this.querySelectorAll('option'))o.toggleAttribute('selected',o.value===String(v));}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(v){this.toggleAttribute('checked',!!v);}});
window.HTMLElement.prototype.pause=()=>{};
const stored={};Object.assign(globalThis,{document,window,localStorage:{getItem:k=>stored[k],setItem:(k,v)=>stored[k]=v}});
const owner=()=>({root:document.createElement('section'),studio:{close(){}},app:{},api:{apiURL:p=>p,addEventListener(){}},fetch:async()=>({})});
const frames=new FrameVideoWorkspace(owner());
assert.equal(frames.config().sizePreset,'source');
frames.assets.first={file:'image1.png',filename:'image1.png'};
frames.assets.last={file:'image2.png',filename:'image2.png',width:800,height:800};
frames.preview();
const preview=frames.$('image-slot').querySelector('img');
Object.defineProperties(preview,{naturalWidth:{value:1920},naturalHeight:{value:1080}});preview.onload();
assert.deepEqual([frames.config().outputWidth,frames.config().outputHeight],[1920,1080]);
assert.equal(frames.$('size-label').textContent,'1920 × 1080');
assert.equal(frames.$('megapixels-setting').hidden,false,'Source proportions keep the MP slider visible');
assert.match(frames.$('canvas-note').textContent,/1920 × 1088/);
for(const cap of ENDPOINT_RECIPES){
  frames.$('engine').value=cap.id;frames.$('engine').onchange();
  assert.deepEqual([frames.config().outputWidth,frames.config().outputHeight],[1920,1080]);
}
frames.$('megapixels').value='1.35';frames.$('megapixels').oninput();
let config=frames.config();assert.equal(config.sourceSize,false);
assert.ok(Math.abs(config.outputWidth/config.outputHeight-16/9)<.01);
assert.ok(Math.abs(config.outputWidth*config.outputHeight/1e6-1.35)<.01);
const reopened=new FrameVideoWorkspace(owner());
assert.equal(reopened.config().sizePreset,'source');assert.equal(reopened.config().sourceSize,false);
assert.deepEqual(reopened.sourceResolution(),frames.sourceResolution());reopened.close();
frames.$('source-size').onclick();
assert.deepEqual([frames.config().outputWidth,frames.config().outputHeight],[1920,1080]);
const hdr={asset_kind:'hdr_endpoint',file:'hdr-preview.png',width:1920,height:1080};
frames.assets.last=hdr;frames.rememberFrameSize(hdr,1024,576);
assert.deepEqual([hdr.width,hdr.height],[1920,1080],'An HDR thumbnail cannot overwrite original EXR dimensions');
frames.assets.last={file:'image2.png',filename:'image2.png',width:800,height:800};
frames.$('swap').onclick();assert.deepEqual([frames.config().outputWidth,frames.config().outputHeight],[800,800]);
frames.$('swap').onclick();
// Submit must not commit hidden custom inputs and silently replace source sizing.
frames.availability={ready:true};frames.hdrOutput.preflight=async()=>{};
let submitted;frames.buildGraph=async c=>{submitted=c;throw new Error('Stopped before queue submission');};
frames.$('width').commitDimension=()=>{throw new Error('Hidden custom control committed');};
await frames.generate();assert.equal(submitted.sizePreset,'source');assert.equal(submitted.outputHeight,1080);
frames.$('size-preset').value='landscape';frames.$('size-preset').onchange();
assert.equal(frames.config().outputWidth,undefined,'Preset shapes retain their original graph path');
frames.$('size-preset').value='source';frames.$('size-preset').onchange();frames.removeFrame('first');
assert.equal(frames.$('source-size').disabled,true);assert.equal(frames.config().outputWidth,undefined);
frames.close();
console.log('Source sizing: exact source, MP scaling, model grids/budgets, image metadata, swaps, persistence and submission pass.');

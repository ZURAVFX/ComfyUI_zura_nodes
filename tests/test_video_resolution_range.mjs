import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {ENDPOINT_RECIPES,endpointPresetSize} from '../web/video_recipe_catalog.js';
import {FrameVideoWorkspace} from '../web/studio_frames.js';
import {ReferenceVideoWorkspace} from '../web/studio_references.js';
import {referenceVideoDimensions} from '../web/reference_video_recipes.js';
import {megapixelMaximum} from '../web/studio_resolution.js';

// Every endpoint graph must accept what its slider offers, including 4K-sized
// portrait and landscape canvases. This only builds graphs, never queues them.
for(const cap of ENDPOINT_RECIPES){
  for(const shape of ['landscape','portrait','square','standard','vertical']){
    for(const mp of [1.5,2.1,4,8.35]){
      const size=endpointPresetSize(cap.id,shape,mp);
      assert.ok(size.width*size.height<=cap.maxPixels);
      assert.ok(size.width*size.height>mp*1e6*.95);
      assert.equal(size.width%cap.dimensionStep,0);
      assert.equal(size.height%cap.dimensionStep,0);
      assert.doesNotThrow(()=>cap.build({...size,first:{file:'first.png'},last:{file:'last.png'},prompt:'A person turns.',frames:cap.defaultFrames,steps:cap.defaultSteps}));
    }
  }
  assert.equal(megapixelMaximum(cap),8.35);
  assert.throws(()=>endpointPresetSize(cap.id,'landscape',9));
}
assert.deepEqual(referenceVideoDimensions({width:3840,height:2176}),{width:3840,height:2176});
assert.throws(()=>referenceVideoDimensions({width:4096,height:4096}));

const {document,window}=parseHTML('<html><body></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(v){for(const o of this.querySelectorAll('option'))o.toggleAttribute('selected',o.value===String(v));}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(v){this.toggleAttribute('checked',!!v);}});
window.HTMLElement.prototype.pause=()=>{};
const stored={};Object.assign(globalThis,{document,window,localStorage:{getItem:k=>stored[k],setItem:(k,v)=>stored[k]=v}});
const owner=()=>({root:document.createElement('section'),studio:{close(){}},app:{},api:{apiURL:p=>p,addEventListener(){}},fetch:async()=>({})});
const frames=new FrameVideoWorkspace(owner());
for(const cap of ENDPOINT_RECIPES){
  frames.$('engine').value=cap.id;frames.$('engine').dispatchEvent(new window.Event('change'));
  assert.equal(Number(frames.$('megapixels').max),8.35);
  frames.$('size-preset').value='landscape';frames.$('megapixels').value='4.35';frames.$('megapixels').oninput();
  assert.ok(frames.config().width*frames.config().height>4e6);
  assert.match(frames.$('size-label').textContent,new RegExp(String(frames.config().width)));
  const restored=new FrameVideoWorkspace(owner());
  assert.equal(Number(restored.$('megapixels').value),4.35,'Non-preset values survive reopening');
  assert.equal(restored.config().width,frames.config().width);restored.close();
}
frames.$('fast').checked=true;frames.render();assert.match(frames.$('canvas-note').textContent,/Samples at.*without refinement/);
frames.close();
const refs=new ReferenceVideoWorkspace(owner());
assert.equal(Number(refs.$('megapixels').max),8.35);
refs.$('size-preset').value='portrait';refs.$('megapixels').value='5.15';refs.$('megapixels').oninput();
assert.ok(refs.config().height>refs.config().width);assert.ok(refs.config().width*refs.config().height>5e6);
const restoredRefs=new ReferenceVideoWorkspace(owner());assert.equal(Number(restoredRefs.$('megapixels').value),5.15);restoredRefs.close();refs.close();
console.log('Video resolution: all endpoint graphs, model grids, 4K canvas budgets, live sliders and saved decimal values pass without generation.');

import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutEditor} from '../web/paintout_studio/paintout_editor.js';
import {PlateWorkspace} from '../web/studio_plate.js';

const {document,window}=parseHTML('<html><body><section id="genj-studio" data-workspace="paintout"><aside class="zplate-sidebar"><section class="zp-editor-paint-layers"></section></aside></section></body></html>');
Object.assign(globalThis,{document,window});
const layer={id:'one',file:'generated.exr',layer_mask:'original-mask',colour_space:'srgb_display',method:'image',prompt:'Add a fire hydrant',retain_layer_context:true};
const anchor={id:'frame',frame:0,file:'initial-composite.exr',layers:[layer],versions:[]};
let saved,wrongExpansion=false,counter=0;
const calls=[];
const editor=Object.assign(Object.create(PaintoutEditor.prototype),{
  project:'project',revision:1,stage:'clean',candidate:null,selected:()=>anchor,
  layersPanel:document.querySelector('.zp-editor-paint-layers'),status(value){this.message=value;},updateControls(){},frameChanged:async()=>{},fullFrameMask:()=> 'full',
  w:{state:{source:'shot.mov',sourceColour:'srgb_display'},sourceInfo:{width:1920,height:1080},playhead:0,busy:()=>false,
    thumbnail:()=> 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="32" height="32"%3E%3Crect width="32" height="32" fill="%23666"/%3E%3C/svg%3E',
    syncAnchorControls(){},changed(){},save(){saved=JSON.parse(JSON.stringify(anchor));},render(){},
    async fetch(path,body){calls.push({path,body});return {file:`composite-${++counter}.exr`,png_file:'preview.png',colour_space:'srgb_display',
      blend_widths:body.layers.map(l=>l.blend_pixels),expansion_widths:body.layers.map(l=>wrongExpansion?0:l.expand_pixels),brightness_values:body.layers.map(l=>l.brightness_ev),enabled_values:body.layers.map(l=>l.enabled),opacity_values:body.layers.map(l=>l.opacity)};}}
});
editor.renderLayers(anchor,true,false);
assert.deepEqual([...editor.layersPanel.querySelectorAll('.zp-editor-layer-adjustments label>span')].map(n=>n.textContent),['Opacity','Expand mask','Blend edge','Brightness']);
assert.equal(Number(editor.layersPanel.querySelector('[aria-label="Expand mask of paint layer 1"]').max),256);
assert.equal(Number(editor.layersPanel.querySelector('[aria-label="Blend edge of paint layer 1"]').max),256);
await editor.expandPaintLayer('one',24);
assert.equal(layer.expand_pixels,24);assert.equal(saved.layers[0].expand_pixels,24);
assert.equal(calls.at(-1).body.layers[0].expand_pixels,24);
assert.equal(anchor.versions.at(-1).layers[0].expand_pixels,24,'Frame history retains the adjustable mask width');
await editor.blendPaintLayer('one',128);
assert.equal(calls.at(-1).body.layers[0].expand_pixels,24,'Feathering preserves expansion');assert.equal(layer.blend_pixels,128);
await editor.brightnessPaintLayer('one',.25);assert.equal(calls.at(-1).body.layers[0].expand_pixels,24);
wrongExpansion=true;await editor.expandPaintLayer('one',32);assert.equal(layer.expand_pixels,24,'An old or mismatched server cannot silently accept expansion');assert.match(editor.message,/mask expansion/);wrongExpansion=false;
const before=calls.length;for(const invalid of [-1,257,1.5,NaN,true])await editor.expandPaintLayer('one',invalid);assert.equal(calls.length,before);
await editor.selectVersion('initial-composite.exr');assert.equal(anchor.layers[0].expand_pixels,undefined,'Selecting the original version restores its zero-default mask');
await editor.selectVersion('composite-3.exr');assert.equal(anchor.layers[0].expand_pixels,24);
anchor.layers.push({id:'two',file:'other.exr',layer_mask:'other-mask',expand_pixels:7,blend_pixels:4});
await editor.movePaintLayer('two',-1);assert.deepEqual(calls.at(-1).body.layers.map(l=>l.expand_pixels),[7,24]);
await editor.removePaintLayer('two');assert.deepEqual(calls.at(-1).body.layers.map(l=>l.expand_pixels),[24]);
editor.layerPanelKey=null;editor.renderLayers(anchor,true,false);
export const fixtureHTML=document.body.innerHTML;

// The full-context master no longer bakes feathering. Carry the chosen edit
// softness into a new layer, while retaining deliberate layer overrides.
const plateAnchor={id:'plate',frame:0,layers:[]},compositions=[];
const primary={state:{source:'shot.mov',sourceColour:'srgb_display',anchors:[plateAnchor]},sourceInfo:{width:1920,height:1080},selected:0,save(){},
  editor:{project:'project',revision:1,ensureProject:async()=>{},ensureLayers:a=>a.layers,fullFrameMask:()=> 'full',saveFrameVersion(){}},
  api:{fetchApi:async()=>({ok:true,json:async()=>({file:'imported.exr',colour_space:'srgb_display'})})},
  fetch:async(path,body)=>{compositions.push(body);return {file:'composed.exr',colour_space:'srgb_display'};}};
const owner={items:[{retain_layer_context:true,edit_area:{enabled:true,feather:18}}],selectedImage:0,imageArea:{layerMask:async()=> 'selection'},$:()=>({value:'Add a fire hydrant'})};
const plate=Object.assign(Object.create(PlateWorkspace.prototype),{primary,owner});
const facade=plate.imageWorkspace(),file=new File(['pixels'],'edit.png',{type:'image/png'});
await facade.importAnchorFile(plateAnchor,file,()=>{});
assert.equal(plateAnchor.layers[0].blend_pixels,18);assert.equal(plateAnchor.layers[0].retain_layer_context,true);
plateAnchor.layers[0].blend_pixels=0;plateAnchor.layers[0].expand_pixels=20;
await facade.importAnchorFile(plateAnchor,file,()=>{});
assert.equal(plateAnchor.layers.length,1);assert.equal(plateAnchor.layers[0].blend_pixels,0,'Regeneration preserves an explicit hard-edge choice');
assert.equal(compositions.at(-1).layers[0].expand_pixels,20,'Regeneration preserves the selected expansion');
console.log('Paint layers: expansion controls, range validation, server readback, undo/history, reorder/delete and retained-context feathering passed');

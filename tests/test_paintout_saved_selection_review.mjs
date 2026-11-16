import assert from 'node:assert/strict';
import {PaintoutEditor} from '../web/paintout_studio/paintout_editor.js';
const anchor={frame:7,file:'repair.exr',editMask:'saved-source-mask'},mask={pixels:'unchanged'},views=[],opacities=[];
let wait=null;
const editor=Object.assign(Object.create(PaintoutEditor.prototype),{sequence:1,showOriginal:false,selected:()=>anchor,$:()=>({value:'45'}),updateControls(){},status(message){throw Error(message);},
 w:{state:{source:'source.mov',sourceColour:'srgb_display'},playhead:7,thumbnail:(file,frame)=>`${file}:${frame}`},
 viewer:{maskCanvas:mask,zoom:2,pan:{x:13,y:-8},async setDisplayImage(url){views.push(url);if(wait)await wait;},setOpacity(value){opacities.push(value);}}});
await editor.compareFrame();assert.equal(views.at(-1),'source.mov:7');assert.equal(opacities.at(-1),.45,'Saved repair area is visible on the original source');
await editor.compareFrame();assert.equal(views.at(-1),'repair.exr:0');assert.equal(opacities.at(-1),0,'Generated result review remains un-tinted');
assert.equal(editor.viewer.maskCanvas,mask);assert.equal(editor.viewer.zoom,2);assert.deepEqual(editor.viewer.pan,{x:13,y:-8});assert.equal(anchor.editMask,'saved-source-mask','Comparison never mutates exported/inference masks');
let release;wait=new Promise(resolve=>release=resolve);const pending=editor.compareFrame();editor.sequence++;editor.w.playhead=8;release();await pending;assert.equal(opacities.length,2,'A late source comparison cannot change another frame overlay');
wait=null;await editor.compareFrame();assert.equal(views.length,3,'A selected guide from another frame is never displayed');
console.log('Paintout saved selection review: source overlay, clean result isolation, zoom/pan/mask preservation and stale frame fencing pass.');

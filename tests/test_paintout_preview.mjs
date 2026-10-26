import assert from 'node:assert/strict';
import {PaintoutEditor} from '../web/paintout_studio/paintout_editor.js';
import {PaintoutMaskViewer} from '../web/paintout_studio/paintout_viewer.js';

const requests=[],applied=[];let grow=32;
const editor=Object.create(PaintoutEditor.prototype);
Object.assign(editor,{stage:'clean',active:true,sequence:1,previewSequence:0,w:{playhead:4,sourceInfo:{width:1920,height:1080},state:{source:'plate.mp4',maskGrow:32,anchors:[]},selected:-1,api:{fetchApi:async(path,options)=>{const body=JSON.parse(options.body);requests.push(body);return {ok:true,blob:async()=>new Blob(['mask'])};}}},$:id=>({value:grow}),viewer:{getSelection:()=>({hasMask:true,mask:'raw-mask'}),setEffectiveMask:async()=>applied.push(grow)},status(){}});
await editor.authoritativePreview();assert.equal(requests.at(-1).grow,32,'Clean preview without a guide card must use the displayed expansion');
editor.w.state.anchors=[{frame:0,editGrow:7}];editor.w.selected=0;grow=48;
await editor.authoritativePreview();assert.equal(requests.at(-1).grow,48,'A different selected frame must not override the current slider');
let completeOld;editor.w.api.fetchApi=async()=>new Promise(resolve=>{completeOld=resolve;});
const old=editor.authoritativePreview();
editor.w.api.fetchApi=async()=>({ok:true,blob:async()=>new Blob(['new-mask'])});grow=64;
await editor.authoritativePreview();const count=applied.length;completeOld({ok:true,blob:async()=>new Blob(['old-mask'])});await old;assert.equal(applied.length,count,'An older server response cannot replace the current overlay');

const pending=[];const priorImage=globalThis.Image,priorDocument=globalThis.document;
globalThis.Image=class{constructor(){this.width=1;this.height=1;}set src(value){pending.push(this);}};
const viewer=Object.create(PaintoutMaskViewer.prototype);Object.assign(viewer,{maskVersion:1,effectiveVersion:0,draw(){}});
let canvases=0;
globalThis.document={createElement:()=>{canvases++;return {getContext:()=>({drawImage(){},getImageData:()=>({data:new Uint8ClampedArray([255,255,255,255])}),putImageData(){}})};}};
const stale=viewer.setEffectiveMask('previous-grow');viewer.setGrow(32,0);pending.shift().onload();await stale;assert.equal(canvases,0,'A late decoded image cannot overwrite a newer slider preview');
const fresh=viewer.setEffectiveMask('current-grow');pending.shift().onload();await fresh;assert.ok(viewer.effectiveOverlay);assert.equal(canvases,1);
globalThis.Image=priorImage;globalThis.document=priorDocument;
console.log('PASS: clean-frame expansion matches displayed controls and stale requests/images cannot overwrite it.');

import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {installBlenderCameraNavigation} from '../web/studio_panorama_controls.js';

const {document,window}=parseHTML('<html><body><div id="editor"><canvas data-stage-canvas></canvas><input/><button data-value="camera"></button></div></body></html>');
const root=document.querySelector('#editor'),canvas=root.querySelector('canvas');
const gestures=[],wheels=[];let keys=0,frames=0,settled=0,nativeDown=0;
window.WheelEvent=class extends window.Event {constructor(type,options){super(type,options);Object.assign(this,options);}};
const session={state:{camera:{locked:false}}};
const stage={knobDown(action,event){gestures.push([action,event.button,event.shiftKey]);},frameSelected(){frames++;},settle(){settled++;}};
const dispose=installBlenderCameraNavigation({session,stage:()=>stage},root,{keyCamera:()=>keys++});
canvas.addEventListener('wheel',event=>wheels.push(event.deltaY));
// Linkedom does not implement the capture phase. A subsequent root listener
// checks that the adapter consumes a handled press before other handlers run.
root.addEventListener('pointerdown',()=>nativeDown++);
const fire=(target,type,values={})=>{const event=new window.Event(type,{bubbles:true,cancelable:true});Object.assign(event,{button:1,pointerId:7,clientX:200,clientY:200,code:'',...values});target.dispatchEvent(event);return event;};
fire(canvas,'pointerdown');
fire(canvas,'pointerdown',{shiftKey:true});
assert.deepEqual(gestures,[['orbit',0,false],['pan',0,false]],'Blender gestures call native depth-aware orbit and pan');
assert.equal(nativeDown,0,'Native middle-mouse pan cannot run a second time');
fire(canvas,'pointerdown',{ctrlKey:true});
fire(window,'pointermove',{clientY:175});
assert.deepEqual(wheels,[-100],'Ctrl-middle drag up moves nearer through native wheel navigation');
fire(window,'pointerup');fire(window,'pointermove',{clientY:150});
assert.equal(wheels.length,1,'Dolly stops when the button is released');
fire(canvas,'keydown',{code:'KeyI'});assert.equal(keys,1);
fire(canvas,'keydown',{code:'KeyI',repeat:true});assert.equal(keys,1);
fire(root.querySelector('input'),'keydown',{code:'KeyI'});assert.equal(keys,1,'Typing never inserts a camera keyframe');
fire(canvas,'keydown',{code:'Home'});fire(canvas,'keydown',{code:'NumpadDecimal'});assert.equal(frames,2);
session.state.camera.locked=true;fire(canvas,'pointerdown');assert.equal(gestures.length,2,'Locked cameras cannot be navigated');
session.state.camera.locked=false;
fire(canvas,'pointerdown',{ctrlKey:true});fire(window,'blur');fire(window,'pointermove',{clientY:140});assert.equal(wheels.length,1,'Losing focus ends dolly');
dispose();fire(canvas,'pointerdown');assert.equal(nativeDown,1,'Closing restores native viewport behaviour');
fire(canvas,'keydown',{code:'KeyI'});assert.equal(keys,1,'Closing removes custom shortcuts');
assert.ok(settled>=3);
console.log('PASS Blender orbit/pan/dolly mapping, native event isolation, keyframe shortcuts, text-entry safety, lock and cleanup');

import assert from 'node:assert/strict';
import {sizePreviewOverlay, bindPreviewDrag} from '../web/dialogue_face_picker.js';

// Screen coordinates change with graph zoom; the CSS layout coordinates must not.
for (const zoom of [.25,.44,.7,1,1.5,2]) {
  const video={clientWidth:351,clientHeight:290,offsetLeft:0,offsetTop:0,
    getBoundingClientRect(){return {width:351*zoom,height:290*zoom};}};
  const overlay={style:{}};
  sizePreviewOverlay(video,overlay,1080,1080);
  assert.deepEqual(overlay.style,{left:'30.5px',top:'0px',width:'290px',height:'290px'});
  const cssWidth=Number.parseFloat(overlay.style.width);
  assert.equal(cssWidth*zoom,video.getBoundingClientRect().height);
}
for (const [source,expected] of [
  [[1920,1080],{left:'7px',top:'80.625px',width:'300px',height:'168.75px'}],
  [[1080,1920],{left:'67px',top:'5px',width:'180px',height:'320px'}]
]) {
  const overlay={style:{}};
  sizePreviewOverlay({clientWidth:300,clientHeight:320,offsetLeft:7,offsetTop:5},overlay,...source);
  assert.deepEqual(overlay.style,expected);
}

const calls=[],captured=new Set();
const overlay={focus(){calls.push('focus');},setPointerCapture(id){captured.add(id);},hasPointerCapture(id){return captured.has(id);},releasePointerCapture(id){captured.delete(id);this.onlostpointercapture?.(event(id));}};
function event(id=1,more={}) {return {pointerId:id,button:0,isPrimary:true,clientX:0,clientY:0,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},...more};}
let allowed=true;
const dispose=bindPreviewDrag(overlay,{
  start(e){calls.push(['start',e.clientX]);return allowed;},move(e){calls.push(['move',e.clientX]);},finish(){calls.push('finish');},cancel(){calls.push('cancel');}
});
let e=event(1,{clientX:20});overlay.onpointerdown(e);assert(e.prevented&&e.stopped);assert(captured.has(1));
overlay.onpointerdown(event(2));overlay.onpointermove(event(2,{clientX:500}));overlay.onpointerup(event(2));
assert.equal(calls.filter(x=>x==='finish').length,0);
// Release position is used even when the browser omits the last move event.
overlay.onpointerup(event(1,{clientX:200}));
assert.deepEqual(calls,['focus',['start',20],['move',200],'finish']);assert.equal(captured.size,0);
for (const kind of ['pointercancel','lostpointercapture','keydown']) {
  calls.length=0;overlay.onpointerdown(event());
  overlay['on'+kind](kind==='keydown'?event(undefined,{pointerId:undefined,key:'Escape'}):event());
  overlay.onpointerup(event());assert.equal(calls.filter(x=>x==='cancel').length,1);assert(!calls.includes('finish'));assert.equal(captured.size,0);
}
calls.length=0;
overlay.onpointerdown(event(1,{button:2}));overlay.onpointerdown(event(1,{isPrimary:false}));
assert.deepEqual(calls,[]);assert.equal(captured.size,0);
allowed=false;overlay.onpointerdown(event());overlay.onpointerup(event());
assert(!calls.includes('finish'));assert(!calls.includes('cancel'));assert.equal(captured.size,0);
allowed=true;calls.length=0;overlay.onpointerdown(event());dispose();
assert(calls.includes('cancel'));assert.equal(captured.size,0);assert.equal(overlay.onpointerdown,null);
console.log('Zoom-independent portrait/landscape alignment, isolated pointer capture, final coordinates, cancellation and rejected gestures passed.');

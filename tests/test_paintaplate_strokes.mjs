import assert from 'node:assert/strict';
import {drawStroke} from '../web/vendor/paintaplate/strokes.mjs';
import {dabsAlong} from '../web/vendor/paintaplate/stroke_logic.mjs';
import {PaintoutMaskViewer} from '../web/paintout_studio/paintout_viewer.js';

function canvas(){
  const surface={width:64,height:48},operations=[];
  const ctx={operations,globalCompositeOperation:'source-over',globalAlpha:1,
    save(){this.saved={g:this.globalCompositeOperation,a:this.globalAlpha};},restore(){if(this.saved){this.globalCompositeOperation=this.saved.g;this.globalAlpha=this.saved.a;}},
    beginPath(){},moveTo(x,y){this.from=[x,y];},lineTo(x,y){this.to=[x,y];},
    stroke(){operations.push({kind:'line',from:this.from,to:this.to,width:this.lineWidth,color:this.strokeStyle,op:this.globalCompositeOperation});},
    clearRect(){operations.length=0;},fillRect(x,y,w,h){operations.push({kind:'fill',rect:[x,y,w,h],style:this.fillStyle,op:this.globalCompositeOperation});},
    createRadialGradient(...args){const gradient={args,stops:[],addColorStop(at,color){this.stops.push([at,color]);}};return gradient;},
    drawImage(image,...args){operations.push({kind:'image',image,args,op:this.globalCompositeOperation});},
    getImageData(){return {data:new Uint8ClampedArray(64*48*4)};},putImageData(){},
  };
  surface.getContext=()=>ctx;return surface;
}
globalThis.document={createElement(tag){assert.equal(tag,'canvas');return canvas();}};

// Upstream's pressure formula: mouse pressure .5 gives the selected diameter;
// full pen pressure gives 1.5 times that diameter, on both paint and mask.
{
  const d={paint:canvas(),mask:canvas()},s={tool:'paint',color:'#12ab34',size:20,points:[[2,3,.5],[10,9,1]]};
  drawStroke(d,s);
  assert.deepEqual(d.paint.getContext().operations.map(op=>op.width),[20,30]);
  assert.deepEqual(d.mask.getContext().operations.map(op=>op.width),[20,30]);
  assert.deepEqual(d.paint.getContext().operations[1].to,[10,9]);
  assert.equal(d.paint.getContext().operations[1].color,'#12ab34');
}
// The reference light brush walks a fixed dab distance. Incremental pointer
// events produce the same light dabs as replaying the saved vector stroke.
{
  const points=[[0,0,10],[11,0,10],[30,0,10]],whole=dabsAlong(points,0,()=>2.5);
  // Each call needs the pointer prefix, just as app.mjs receives a growing stroke.
  let carry=0,got=[];for(let i=0;i<points.length;i++){const step=dabsAlong(points.slice(0,i+1),i,()=>2.5,carry);carry=step.carry;got.push(...step.dabs);}
  assert.deepEqual(got,whole.dabs);
  const s={tool:'light',color:'#ff8000',size:20,points:[[2,3,.5],[10,9,.5],[30,9,.5]]};
  const full={paint:canvas(),mask:canvas()},incremental={paint:canvas(),mask:canvas()};
  drawStroke(full,s);const growing={...s,points:[]};
  for(const point of s.points){growing.points.push(point);drawStroke(incremental,growing,growing.points.length-1);}
  assert.deepEqual(JSON.parse(JSON.stringify(incremental.paint.getContext().operations)),JSON.parse(JSON.stringify(full.paint.getContext().operations)));
  assert(full.paint.getContext().operations.every(op=>op.op==='lighter'));
  const shade={paint:canvas(),mask:canvas()};drawStroke(shade,{...s,color:'#000000'});
  assert(shade.shade,'Dark Light strokes use the reference shade layer');
}
{
  const d={paint:canvas(),mask:canvas(),shade:canvas()};
  drawStroke(d,{tool:'rub',size:12,color:'#fff',points:[[2,2,.5],[9,2,.5]]});
  for(const layer of [d.paint,d.mask,d.shade]){
    assert(layer.getContext().operations.every(op=>op.op==='destination-out'));
    assert.equal(layer.getContext().globalCompositeOperation,'source-over');
  }
}
function viewer(){
  const v=Object.create(PaintoutMaskViewer.prototype);Object.assign(v,{width:64,height:48,version:1,
    root:{dataset:{},setAttribute(){}},history:[],tool:'draw',brushSize:12,drawColor:'#ff8000',
    sketchCanvas:canvas(),maskCanvas:canvas(),image:{},draw(){},changed(kind){this.changeKind=kind;},
    measureMask(){this.maskPresent=!!this.paintAPlateStrokes?.length;return this.maskPresent;},
    measureSketch(){this.sketchPresent=this.paintAPlateStrokes?.some(s=>s.tool==='paint'||s.tool==='light');return this.sketchPresent;},
  });v.sketchCtx=v.sketchCanvas.getContext();v.maskCtx=v.maskCanvas.getContext();v.setPaintAPlateMode(true);return v;
}
{
  const v=viewer();v.snapshot('guide');v.drag={};v.paint({x:1,y:2},{x:1,y:2},.5);v.paint({x:1,y:2},{x:12,y:9},1);v.drag=null;
  v.setTool('light');v.snapshot('area');v.drag={};v.paint({x:4,y:4},{x:4,y:4},.5);v.drag=null;
  assert.equal(v.paintAPlateStrokes.length,2);
  const state=v.exportPaintAPlateState();assert.equal(state.past.length,2);assert.equal(JSON.stringify(state).includes('data:image'),false);
  v.undo('guide');assert.equal(v.paintAPlateStrokes.length,1,'Add undo ignores the old guide/area split');
  v.redo('area');assert.equal(v.paintAPlateStrokes.length,2);
  const restored=viewer();assert.equal(await restored.restorePaintAPlateState(state),true);
  assert.deepEqual(restored.paintAPlateStrokes,state.strokes);assert.equal(restored.history.length,2);
  restored.clear('guide');assert.equal(restored.paintAPlateStrokes.length,0);restored.undo('area');assert.equal(restored.paintAPlateStrokes.length,2);
  assert.equal(await restored.restorePaintAPlateState({...state,past:{}}),false);
  const bad=structuredClone(state);bad.strokes[0].points[0][2]=NaN;assert.equal(await restored.restorePaintAPlateState(bad),false);
}
console.log('Paint-a-Plate source renderer: pressure, deterministic light dabs, shade, rub, vector replay and unified undo/redo pass.');

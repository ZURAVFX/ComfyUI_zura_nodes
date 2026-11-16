import {drawStroke as drawPaintAPlateStroke} from '../vendor/paintaplate/strokes.mjs';
const make=(tag,cls)=>{const element=document.createElement(tag);element.className=cls;return element;};
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const clone=value=>JSON.parse(JSON.stringify(value));

function loadImage(url){return new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('The frame preview could not load.'));image.src=url;});}

/** One source-space editor. Display transforms never affect saved mask coordinates. */
export class PaintoutMaskViewer{
  constructor(container,{onChange=()=>{},onCommit=()=>{},separateGuide=false}={}){
    this.container=container;this.onChange=onChange;this.onCommit=onCommit;this.separateGuide=separateGuide;this.guideOnly=false;this.width=1;this.height=1;this.frame=-1;
    this.tool='include';this.opacity=.45;this.grow=0;this.feather=0;this.brushSize=30;this.zoom=1;this.pan={x:0,y:0};
    this.positive=[];this.negative=[];this.history=[];this.maskPresent=false;this.version=0;this.maskVersion=0;
    this.root=make('div','zp-editor-viewer');this.root.tabIndex=0;this.root.setAttribute('role','application');this.root.setAttribute('aria-label','Paintout frame editor. Click to include a point. Use the toolbar to change tools.');
    this.canvas=make('canvas','zp-editor-viewer__canvas');this.root.append(this.canvas);container.append(this.root);
    this.ctx=this.canvas.getContext('2d');this.maskCanvas=document.createElement('canvas');this.maskCtx=this.maskCanvas.getContext('2d',{willReadFrequently:true});
    this.sketchCanvas=document.createElement('canvas');this.sketchCtx=this.sketchCanvas.getContext('2d',{willReadFrequently:true});this.sketchPresent=false;this.drawColor='#ff6347';this.drawOpacity=1;
    this.proxy=document.createElement('canvas');this.proxyCtx=this.proxy.getContext('2d',{willReadFrequently:true});this.overlay=document.createElement('canvas');
    this.pointerDown=event=>this.startPointer(event);this.pointerMove=event=>this.movePointer(event);this.pointerUp=event=>this.endPointer(event);
    this.root.addEventListener('pointerdown',this.pointerDown);this.root.addEventListener('pointermove',this.pointerMove);this.root.addEventListener('pointerup',this.pointerUp);this.root.addEventListener('pointercancel',this.pointerUp);
    this.root.addEventListener('wheel',event=>this.wheel(event),{passive:false});
    this.root.addEventListener('keydown',event=>{const key=event.key.toLowerCase();if((event.ctrlKey||event.metaKey)&&(key==='z'||this.paintAPlateMode&&key==='y')){event.preventDefault();if(this.paintAPlateMode&&(event.shiftKey||key==='y'))this.redo();else this.undo(this.separateGuide?(this.guideOnly?'guide':'area'):undefined);this.onCommit();}else if(this.paintAPlateMode&&!event.ctrlKey&&!event.metaKey&&['b','e','l','[',']'].includes(key)){event.preventDefault();if(key==='['||key===']')this.setBrushSize(this.brushSize*(key==='['?.8:1.25));else this.setTool(({b:'draw',e:'protect',l:'light'})[key]);this.onToolChange?.(this.tool,this.brushSize);}else if(event.key==='0'||key==='f'){event.preventDefault();event.stopPropagation();this.fit();}else if(event.key==='Escape'){this.drag=null;this.draw();}});
    this.root.addEventListener('contextmenu',event=>event.preventDefault());
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(this.root);this.resize();
  }
  async setFrame(url,width,height,frame){
    const key=`${url}|${width}|${height}|${frame}`;if(key===this.frameKey)return;
    const version=++this.version,image=await loadImage(url);if(version!==this.version)return;
    this.frameKey=key;this.image=image;this.displaySourceURL=url;this.colourImage=null;this.colourVersion=(this.colourVersion||0)+1;this.effectiveOverlay=null;this.contextOverlay=null;this.contextVersion=(this.contextVersion||0)+1;this.width=Math.max(1,Math.round(width));this.height=Math.max(1,Math.round(height));this.frame=frame;
    this.maskCanvas.width=this.width;this.maskCanvas.height=this.height;this.sketchCanvas.width=this.width;this.sketchCanvas.height=this.height;this.sketchPresent=false;this.maskCtx.fillStyle='black';this.maskCtx.fillRect(0,0,this.width,this.height);
    this.positive=[];this.negative=[];this.history=[];this.maskPresent=false;this.maskSourceURL=null;this.sketchSourceURL=null;this.maskImage=null;this.sketchImage=null;this.paintAPlateStrokes=[];this.paintAPlateFuture=[];this.paintAPlateBase={};this.paintAPlateLight=null;this.paintAPlateShade=null;this.maskVersion++;this.overlayKey='';this.zoom=1;this.pan={x:0,y:0};this.draw();this.onDisplaySourceChange?.();
  }
  async setMask(url){
    const version=this.version,revision=++this.maskVersion;this.effectiveOverlay=null;
    if(!url){this.maskPresent=false;this.maskCtx.fillStyle='black';this.maskCtx.fillRect(0,0,this.width,this.height);this.overlayKey='';this.draw();return;}
    const image=await loadImage(url);if(version!==this.version||revision!==this.maskVersion)return;
    this.maskCtx.fillStyle='black';this.maskCtx.fillRect(0,0,this.width,this.height);this.maskCtx.drawImage(image,0,0,this.width,this.height);this.maskSourceURL=url;this.maskImage=image;this.measureMask();this.history=[];this.overlayKey='';this.draw();
  }
  async setDisplayImage(url){const version=this.version,display=this.displayVersion=(this.displayVersion||0)+1,image=await loadImage(url);if(version!==this.version||display!==this.displayVersion)return;this.image=image;this.displaySourceURL=url;this.colourImage=null;this.colourVersion=(this.colourVersion||0)+1;this.draw();this.onDisplaySourceChange?.();}
  async setColourDisplayImage(url,sourceURL){const version=this.version,colour=this.colourVersion=(this.colourVersion||0)+1,image=await loadImage(url);if(version!==this.version||colour!==this.colourVersion||sourceURL!==this.displaySourceURL)return false;this.colourImage=image;this.draw();return true;}
  clearColourDisplay(){this.colourVersion=(this.colourVersion||0)+1;if(this.colourImage){this.colourImage=null;this.draw();}}
  setSelection({positive=[],negative=[]}={}){this.positive=positive.map(p=>({...p}));this.negative=negative.map(p=>({...p}));this.draw();}
  setTool(tool){tool=({paint:'draw',erase:'protect'})[tool]||tool;if(!['include','exclude','brush','draw','protect','pan',...(this.paintAPlateMode?['light']:[])].includes(tool))return;this.tool=tool;this.root.dataset.tool=tool;this.root.setAttribute('aria-label',`Paintout frame editor. ${tool==='include'?'Click to include a point':tool==='exclude'?'Click to exclude a point':tool==='brush'?'Paint the edit area':tool==='draw'?'Paint a visual guide':tool==='light'?'Paint light or shade':tool==='protect'?'Erase painted strokes':'Drag to pan'}.`);this.draw();}
  setGrow(grow,feather){this.effectiveVersion=(this.effectiveVersion||0)+1;this.grow=clamp(Math.round(Number(grow)||0),0,256);this.feather=clamp(Math.round(Number(feather)||0),0,256);this.effectiveOverlay=null;this.overlayKey='';this.draw();}
  async setEffectiveMask(url){const version=this.maskVersion,effective=this.effectiveVersion,image=await loadImage(url);if(version!==this.maskVersion||effective!==this.effectiveVersion)return;const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);for(let i=0;i<pixels.data.length;i+=4){const alpha=pixels.data[i]>127?255:0;pixels.data[i]=245;pixels.data[i+1]=62;pixels.data[i+2]=66;pixels.data[i+3]=alpha;}ctx.putImageData(pixels,0,0);this.effectiveOverlay=canvas;this.draw();}
  async setContextMask(url){
    const version=this.version,request=this.contextVersion=(this.contextVersion||0)+1;
    this.contextOverlay=null;if(!url){this.draw();return;}
    const image=await loadImage(url);if(version!==this.version||request!==this.contextVersion)return;
    const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
    const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);for(let i=0;i<pixels.data.length;i+=4){const alpha=pixels.data[i]>127?255:0;pixels.data[i]=245;pixels.data[i+1]=62;pixels.data[i+2]=66;pixels.data[i+3]=alpha;}ctx.putImageData(pixels,0,0);this.contextOverlay=canvas;this.draw();
  }
  setOpacity(value){this.opacity=clamp(Number(value)||0,0,1);this.draw();}
  setBrushSize(value){this.brushSize=clamp(Number(value)||1,1,1000);}
  fit(){this.zoom=1;this.pan={x:0,y:0};this.draw();}
  resize(){const rect=this.root.getBoundingClientRect();this.cssWidth=Math.max(1,rect.width);this.cssHeight=Math.max(1,rect.height);const dpr=Math.min(2,window.devicePixelRatio||1);this.canvas.width=Math.round(this.cssWidth*dpr);this.canvas.height=Math.round(this.cssHeight*dpr);this.ctx.setTransform(dpr,0,0,dpr,0,0);this.draw();}
  transform(){const scale=Math.min(this.cssWidth/this.width,this.cssHeight/this.height)*this.zoom;return {scale,x:(this.cssWidth-this.width*scale)/2+this.pan.x,y:(this.cssHeight-this.height*scale)/2+this.pan.y};}
  point(event){const rect=this.root.getBoundingClientRect(),t=this.transform();return {x:(event.clientX-rect.left-t.x)/t.scale,y:(event.clientY-rect.top-t.y)/t.scale};}
  inside(point){return point.x>=0&&point.y>=0&&point.x<this.width&&point.y<this.height;}
  snapshot(kind='selection'){if(this.paintAPlateMode){this.history.push({kind:'paint',paintAPlate:this.exportPaintAPlateState(false)});this.paintAPlateFuture=[];if(this.history.length>12)this.history.shift();return;}this.history.push({kind,positive:this.positive.map(p=>({...p})),negative:this.negative.map(p=>({...p})),mask:this.maskCtx.getImageData(0,0,this.width,this.height),sketch:this.sketchPresent||this.tool==='draw'?this.sketchCtx.getImageData(0,0,this.width,this.height):null,sketchPresent:this.sketchPresent});if(this.history.length>12)this.history.shift();}
  changed(kind='selection'){if(kind!=='guide')this.maskVersion++;this.effectiveOverlay=null;this.overlayKey='';this.draw();this.onChange({kind,frame:this.frame,positive:this.positive.map(p=>({...p})),negative:this.negative.map(p=>({...p}))});}
  startPointer(event){
    if(!this.image||event.button>1)return;this.root.focus();const p=this.point(event);if(!this.inside(p)&&this.tool!=='pan'&&event.button!==1)return;
    event.preventDefault();this.root.setPointerCapture(event.pointerId);
    if(this.tool==='pan'||event.button===1){this.drag={kind:'pan',x:event.clientX,y:event.clientY,pan:{...this.pan}};return;}
    this.snapshot(this.paintAPlateMode?'paint':this.separateGuide?(this.guideOnly?'guide':'area'):['brush','draw','protect',...(this.paintAPlateMode?['light']:[])].includes(this.tool)?'paint':'selection');
    if(this.tool==='include'||this.tool==='exclude'){
      const array=this.tool==='include'?this.positive:this.negative,t=this.transform();const found=array.findIndex(existing=>Math.hypot(existing.x-p.x,existing.y-p.y)<10/t.scale);
      if(found>=0)array.splice(found,1);else array.push({x:clamp(Math.round(p.x),0,this.width-1),y:clamp(Math.round(p.y),0,this.height-1)});this.changed();return;
    }
    this.drag={kind:'paint',last:p};this.paint(p,p,event.pressure||.5);this.changed(this.paintAPlateMode?'paint':this.separateGuide?(this.guideOnly?'guide':'area'):'paint');
  }
  paint(a,b,pressure=.5){if(this.paintAPlateMode){this.paintAPlatePoint(b,pressure);return;}if(this.tool==='draw'||this.tool==='protect'&&(this.separateGuide?this.guideOnly:this.sketchPresent)){const ctx=this.sketchCtx;ctx.save();ctx.globalCompositeOperation=this.tool==='protect'?'destination-out':'source-over';ctx.globalAlpha=this.drawOpacity;ctx.strokeStyle=this.drawColor;ctx.fillStyle=this.drawColor;ctx.lineWidth=this.brushSize;ctx.lineCap='round';ctx.lineJoin='round';ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();ctx.beginPath();ctx.arc(b.x,b.y,this.brushSize/2,0,Math.PI*2);ctx.fill();ctx.restore();if(this.tool==='draw')this.sketchPresent=true;}if(this.separateGuide&&(this.tool==='draw'||this.guideOnly))return;if(this.tool!=='protect')this.maskPresent=true;this.maskCtx.save();this.maskCtx.strokeStyle=this.tool==='protect'?'black':'white';this.maskCtx.fillStyle=this.maskCtx.strokeStyle;this.maskCtx.lineWidth=this.brushSize;this.maskCtx.lineCap='round';this.maskCtx.lineJoin='round';this.maskCtx.beginPath();this.maskCtx.moveTo(a.x,a.y);this.maskCtx.lineTo(b.x,b.y);this.maskCtx.stroke();this.maskCtx.beginPath();this.maskCtx.arc(b.x,b.y,this.brushSize/2,0,Math.PI*2);this.maskCtx.fill();this.maskCtx.restore();}
  setDrawColor(color){if(/^#[0-9a-f]{6}$/i.test(color))this.drawColor=color;}
  async setSketch(url){if(!url)return;const revision=this.version,image=await loadImage(url);if(revision!==this.version)return;this.sketchCtx.clearRect(0,0,this.width,this.height);this.sketchCtx.drawImage(image,0,0,this.width,this.height);this.sketchSourceURL=url;this.sketchImage=image;this.sketchPresent=true;this.draw();}

  movePointer(event){this.cursor=this.point(event);if(!this.drag){this.draw();return;}if(this.drag.kind==='pan'){this.pan.x=this.drag.pan.x+event.clientX-this.drag.x;this.pan.y=this.drag.pan.y+event.clientY-this.drag.y;this.draw();return;}const p=this.point(event);this.paint(this.drag.last,p,event.pressure||.5);this.drag.last=p;this.changed(this.paintAPlateMode?'paint':this.separateGuide?(this.guideOnly?'guide':'area'):'paint');}
  endPointer(event){if(this.drag){const painted=this.drag.kind==='paint';this.drag=null;if(painted&&this.paintAPlateMode){this.measureMask();this.measureSketch();}this.draw();if(painted)this.onCommit();}if(this.root.hasPointerCapture(event.pointerId))this.root.releasePointerCapture(event.pointerId);}
  wheel(event){if(event.defaultPrevented||!this.image)return;event.preventDefault();event.stopPropagation?.();const rect=this.root.getBoundingClientRect(),p=this.point(event);this.zoom=clamp(this.zoom*Math.exp(-event.deltaY*.0015),.05,64);const next=this.transform();this.pan.x+=event.clientX-rect.left-(next.x+p.x*next.scale);this.pan.y+=event.clientY-rect.top-(next.y+p.y*next.scale);if(this.zoom===1)this.pan={x:0,y:0};this.draw();}
  setPaintAPlateMode(enabled=true){
    const next=enabled===true;if(this.paintAPlateMode===next)return;
    this.paintAPlateMode=next;this.root.dataset.paintaplate=String(next);this.paintAPlateStrokes=[];this.paintAPlateFuture=[];this.history=[];
    this.paintAPlateBase={mask:this.maskImage||null,sketch:this.sketchImage||null,maskURL:this.maskSourceURL||null,sketchURL:this.sketchSourceURL||null};this.paintAPlateImages=new Map();
    if(this.maskSourceURL&&this.maskImage)this.paintAPlateImages.set(this.maskSourceURL,this.maskImage);if(this.sketchSourceURL&&this.sketchImage)this.paintAPlateImages.set(this.sketchSourceURL,this.sketchImage);
    if(!next&&this.tool==='light')this.setTool('draw');this.draw();
  }
  paintAPlateLayer(light=false){
    if(light&&!this.paintAPlateLight){this.paintAPlateLight=document.createElement('canvas');this.paintAPlateLight.width=this.width;this.paintAPlateLight.height=this.height;}
    return {paint:light?this.paintAPlateLight:this.sketchCanvas,mask:this.maskCanvas,shade:light?this.paintAPlateShade:null};
  }
  applyPaintAPlateStroke(stroke,from=0){
    if(stroke.tool==='rub'){
      const regular=this.paintAPlateLayer(false);drawPaintAPlateStroke(regular,stroke,from);
      if(this.paintAPlateLight){const light=this.paintAPlateLayer(true);drawPaintAPlateStroke(light,stroke,from);}
    }else{
      const layer=this.paintAPlateLayer(stroke.tool==='light');drawPaintAPlateStroke(layer,stroke,from);
      if(stroke.tool==='light')this.paintAPlateShade=layer.shade||null;
    }
    // Reference masks store alpha; Zura mask assets store opaque RGB.
    this.maskCtx.save();this.maskCtx.globalCompositeOperation='destination-over';this.maskCtx.fillStyle='#000';this.maskCtx.fillRect(0,0,this.width,this.height);this.maskCtx.restore();
    if(stroke.tool!=='rub'){this.maskPresent=true;if(stroke.tool==='paint'||stroke.tool==='light')this.sketchPresent=true;}
  }
  paintAPlatePoint(point,pressure){
    let stroke=this.drag?.stroke;
    if(!stroke){stroke={tool:this.tool==='protect'?'rub':this.tool==='light'?'light':this.tool==='brush'?'erase':'paint',color:this.drawColor,size:this.brushSize,points:[]};(this.paintAPlateStrokes||=[]).push(stroke);if(this.drag)this.drag.stroke=stroke;}
    stroke.points.push([point.x,point.y,clamp(Number(pressure)||.5,0,1)]);
    this.applyPaintAPlateStroke(stroke,stroke.points.length-1);
  }
  drawGuide(ctx,image=this.image,preview=false){
    if(image)ctx.drawImage(image,0,0,this.width,this.height);
    ctx.save();ctx.globalAlpha=preview&&this.paintAPlateMode ? .9 : 1;ctx.drawImage(this.sketchCanvas,0,0);
    ctx.globalAlpha=1;if(this.paintAPlateShade)ctx.drawImage(this.paintAPlateShade,0,0);
    if(this.paintAPlateLight){ctx.globalCompositeOperation='lighter';ctx.drawImage(this.paintAPlateLight,0,0);}ctx.restore();
  }
  guideSketchCanvas(){
    if(!this.paintAPlateMode||!this.paintAPlateLight&&!this.paintAPlateShade)return this.sketchCanvas;
    const canvas=document.createElement('canvas');canvas.width=this.width;canvas.height=this.height;this.drawGuide(canvas.getContext('2d'),null);return canvas;
  }
  exportPaintAPlateState(includeHistory=true){
    if(!this.paintAPlateMode)return null;
    const state={schemaVersion:1,width:this.width,height:this.height,strokes:clone(this.paintAPlateStrokes||[]),baseMask:this.paintAPlateBase?.maskURL||null,baseSketch:this.paintAPlateBase?.sketchURL||null};
    if(includeHistory){state.past=this.history.filter(entry=>entry.paintAPlate).map(entry=>clone(entry.paintAPlate));state.future=clone(this.paintAPlateFuture||[]);}return state;
  }
  validatePaintAPlateState(value){
    if(!value||value.schemaVersion!==1||!Number.isSafeInteger(value.width)||!Number.isSafeInteger(value.height)||value.width<1||value.height<1||!Array.isArray(value.strokes)||value.strokes.length>1000||(value.past!==undefined&&!Array.isArray(value.past))||(value.future!==undefined&&!Array.isArray(value.future))||[value.baseMask,value.baseSketch].some(url=>url!=null&&(typeof url!=='string'||url.length>8192)))return false;
    let count=0;return value.strokes.every(stroke=>stroke&&typeof stroke==='object'&&['paint','erase','light','rub'].includes(stroke.tool)&&/^#[0-9a-f]{6}$/i.test(stroke.color)&&Number.isFinite(stroke.size)&&stroke.size>0&&stroke.size<=1000&&Array.isArray(stroke.points)&&(count+=stroke.points.length)<=100000&&stroke.points.every(point=>Array.isArray(point)&&point.length===3&&point.every(Number.isFinite)&&point[2]>=0&&point[2]<=1));
  }
  replayPaintAPlateState(state,notify=true){
    const sx=this.width/state.width,sy=this.height/state.height;
    this.paintAPlateBase={mask:this.paintAPlateImages?.get(state.baseMask)||null,sketch:this.paintAPlateImages?.get(state.baseSketch)||null,maskURL:state.baseMask||null,sketchURL:state.baseSketch||null};
    this.maskCtx.clearRect(0,0,this.width,this.height);this.maskCtx.fillStyle='#000';this.maskCtx.fillRect(0,0,this.width,this.height);
    this.sketchCtx.clearRect(0,0,this.width,this.height);this.paintAPlateLight=null;this.paintAPlateShade=null;
    if(this.paintAPlateBase?.mask)this.maskCtx.drawImage(this.paintAPlateBase.mask,0,0,this.width,this.height);
    if(this.paintAPlateBase?.sketch)this.sketchCtx.drawImage(this.paintAPlateBase.sketch,0,0,this.width,this.height);
    this.paintAPlateStrokes=clone(state.strokes).map(stroke=>({...stroke,size:stroke.size*Math.sqrt(sx*sy),points:stroke.points.map(([x,y,p])=>[x*sx,y*sy,p])}));
    for(const stroke of this.paintAPlateStrokes)this.applyPaintAPlateStroke(stroke);
    this.measureMask();this.measureSketch();if(notify)this.changed('paint');else this.draw();
  }
  async restorePaintAPlateState(state){
    if(!this.paintAPlateMode||!this.validatePaintAPlateState(state))return false;
    const revision=this.version;
    const states=[state,...(state.past||[]).slice(-12),...(state.future||[]).slice(-12)].filter(item=>this.validatePaintAPlateState(item)),urls=[...new Set(states.flatMap(item=>[item.baseMask,item.baseSketch]).filter(Boolean))];
    const images=await Promise.all(urls.map(async url=>[url,await loadImage(url)]));
    if(revision!==this.version||!this.paintAPlateMode)return false;
    this.paintAPlateImages=new Map(images);this.replayPaintAPlateState(state,false);
    this.history=(state.past||[]).slice(-12).filter(item=>this.validatePaintAPlateState(item)).map(item=>({kind:'paint',paintAPlate:clone(item)}));
    this.paintAPlateFuture=(state.future||[]).slice(-12).filter(item=>this.validatePaintAPlateState(item)).map(clone);return true;
  }
  redo(){if(!this.paintAPlateMode||!this.paintAPlateFuture?.length)return;const state=this.paintAPlateFuture.pop();this.history.push({kind:'paint',paintAPlate:this.exportPaintAPlateState(false)});this.replayPaintAPlateState(state);}
  buildOverlay(){
    const size=Math.min(640,Math.max(this.width,this.height)),scale=Math.min(1,size/Math.max(this.width,this.height)),w=Math.max(1,Math.round(this.width*scale)),h=Math.max(1,Math.round(this.height*scale));
    const key=`${this.maskVersion}:${w}:${h}:${this.grow}:${this.feather}`;if(this.overlayKey===key)return;this.overlayKey=key;
    this.proxy.width=w;this.proxy.height=h;this.proxyCtx.imageSmoothingEnabled=false;this.proxyCtx.drawImage(this.maskCanvas,0,0,w,h);const input=this.proxyCtx.getImageData(0,0,w,h),binary=new Uint8Array(w*h),grown=new Uint8Array(w*h);
    for(let i=0;i<binary.length;i++)binary[i]=input.data[i*4]>0?1:0;
    const radius=Math.round(this.grow*scale),horizontal=new Uint8Array(w*h);
    // Two sliding windows implement a square maximum filter at the preview scale.
    for(let y=0;y<h;y++){let count=0;for(let x=0;x<=Math.min(radius,w-1);x++)count+=binary[y*w+x];for(let x=0;x<w;x++){horizontal[y*w+x]=count>0?1:0;const remove=x-radius,add=x+radius+1;if(remove>=0)count-=binary[y*w+remove];if(add<w)count+=binary[y*w+add];}}
    for(let x=0;x<w;x++){let count=0;for(let y=0;y<=Math.min(radius,h-1);y++)count+=horizontal[y*w+x];for(let y=0;y<h;y++){grown[y*w+x]=count>0?1:0;const remove=y-radius,add=y+radius+1;if(remove>=0)count-=horizontal[remove*w+x];if(add<h)count+=horizontal[add*w+x];}}
    const distance=new Float32Array(w*h);for(let i=0;i<distance.length;i++)distance[i]=grown[i]?0:1e6;
    // Chamfer preview only. Authoritative source-resolution feather comes from backend.
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){const i=y*w+x;if(x)distance[i]=Math.min(distance[i],distance[i-1]+1);if(y)distance[i]=Math.min(distance[i],distance[i-w]+1);if(x&&y)distance[i]=Math.min(distance[i],distance[i-w-1]+Math.SQRT2);if(x<w-1&&y)distance[i]=Math.min(distance[i],distance[i-w+1]+Math.SQRT2);}
    for(let y=h-1;y>=0;y--)for(let x=w-1;x>=0;x--){const i=y*w+x;if(x<w-1)distance[i]=Math.min(distance[i],distance[i+1]+1);if(y<h-1)distance[i]=Math.min(distance[i],distance[i+w]+1);if(x<w-1&&y<h-1)distance[i]=Math.min(distance[i],distance[i+w+1]+Math.SQRT2);if(x&&y<h-1)distance[i]=Math.min(distance[i],distance[i+w-1]+Math.SQRT2);}
    this.overlay.width=w;this.overlay.height=h;const ctx=this.overlay.getContext('2d'),out=ctx.createImageData(w,h),feather=this.feather*scale;
    for(let i=0;i<grown.length;i++){const alpha=grown[i]?1:feather?clamp(1-distance[i]/feather,0,1):0;out.data[i*4]=245;out.data[i*4+1]=62;out.data[i*4+2]=66;out.data[i*4+3]=Math.round(alpha*255);}ctx.putImageData(out,0,0);
  }
  draw(){
    if(!this.ctx)return;const ctx=this.ctx;ctx.clearRect(0,0,this.cssWidth||1,this.cssHeight||1);if(!this.image)return;const t=this.transform();ctx.drawImage(this.colourImage||this.image,t.x,t.y,this.width*t.scale,this.height*t.scale);if(this.sketchPresent){if(this.paintAPlateMode){ctx.save();ctx.translate(t.x,t.y);ctx.scale(t.scale,t.scale);this.drawGuide(ctx,null,true);ctx.restore();}else ctx.drawImage(this.sketchCanvas,t.x,t.y,this.width*t.scale,this.height*t.scale);}this.buildOverlay();if(this.contextOverlay&&this.tool!=='draw'){ctx.save();ctx.globalAlpha=this.opacity;ctx.imageSmoothingEnabled=false;ctx.drawImage(this.contextOverlay,t.x,t.y,this.width*t.scale,this.height*t.scale);ctx.restore();}ctx.save();ctx.globalAlpha=this.tool==='draw'||this.paintAPlateMode&&this.tool==='light'?0:this.opacity;ctx.imageSmoothingEnabled=false;ctx.drawImage(this.effectiveOverlay||this.overlay,t.x,t.y,this.width*t.scale,this.height*t.scale);ctx.restore();
    for(const [points,positive] of [[this.positive,true],[this.negative,false]])for(const p of points){const x=t.x+p.x*t.scale,y=t.y+p.y*t.scale;ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.fillStyle=positive?'#caff00':'#f2f2f0';ctx.fill();ctx.strokeStyle='#101013';ctx.lineWidth=2;ctx.stroke();ctx.beginPath();ctx.moveTo(x-3,y);ctx.lineTo(x+3,y);if(positive){ctx.moveTo(x,y-3);ctx.lineTo(x,y+3);}ctx.stroke();}
    if(this.cursor&&this.inside(this.cursor)&&['brush','draw','protect',...(this.paintAPlateMode?['light']:[])].includes(this.tool)){ctx.beginPath();ctx.arc(t.x+this.cursor.x*t.scale,t.y+this.cursor.y*t.scale,this.brushSize*t.scale/2,0,Math.PI*2);ctx.strokeStyle='#101013';ctx.lineWidth=3;ctx.stroke();ctx.strokeStyle='#ffffff';ctx.lineWidth=1;ctx.stroke();}
  }
  measureMask(){const data=this.maskCtx.getImageData(0,0,this.width,this.height).data;let hasMask=false;for(let i=0;i<data.length;i+=4){if(data[i]>0){hasMask=true;break;}}this.maskPresent=hasMask;return hasMask;}
  measureSketch(){let hasSketch=false;for(const canvas of [this.sketchCanvas,...(this.paintAPlateMode?[this.paintAPlateLight,this.paintAPlateShade]:[])].filter(Boolean)){const data=canvas.getContext('2d').getImageData(0,0,this.width,this.height).data;for(let i=3;i<data.length;i+=4){if(data[i]>0){hasSketch=true;break;}}if(hasSketch)break;}this.sketchPresent=hasSketch;return hasSketch;}
  getSelection(includeImage=true){return {positive:this.positive.map(p=>({...p})),negative:this.negative.map(p=>({...p})),hasMask:includeImage?this.measureMask():this.maskPresent,mask:includeImage?this.maskCanvas.toDataURL('image/png'):undefined};}
  clear(kind){if(this.paintAPlateMode){this.snapshot('paint');this.replayPaintAPlateState({schemaVersion:1,width:this.width,height:this.height,strokes:[]});return;}this.snapshot(kind||'paint');if(kind!=='guide'){this.positive=[];this.negative=[];this.maskCtx.fillStyle='black';this.maskCtx.fillRect(0,0,this.width,this.height);this.maskPresent=false;}if(kind!=='area'){this.sketchCtx.clearRect(0,0,this.width,this.height);this.sketchPresent=false;}this.changed(kind||'selection');}
  undo(kind){if(this.paintAPlateMode){const previous=this.history.pop();if(!previous?.paintAPlate)return;(this.paintAPlateFuture||=[]).push(this.exportPaintAPlateState(false));this.replayPaintAPlateState(previous.paintAPlate);return;}const index=kind?this.history.findLastIndex(entry=>entry.kind===kind):this.history.length-1;if(index<0)return;const [previous]=this.history.splice(index,1);if(kind!=='guide'){this.positive=previous.positive;this.negative=previous.negative;this.maskCtx.putImageData(previous.mask,0,0);this.measureMask();}if(kind!=='area'){this.sketchCtx.clearRect(0,0,this.width,this.height);if(previous.sketch)this.sketchCtx.putImageData(previous.sketch,0,0);this.sketchPresent=!!previous.sketchPresent;}this.changed(previous.kind||'selection');}
  dispose(){this.version++;this.colourVersion=(this.colourVersion||0)+1;this.maskVersion++;this.onDisplaySourceChange=null;this.resizeObserver.disconnect();this.root.remove();}
}

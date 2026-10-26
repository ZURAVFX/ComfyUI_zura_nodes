const make=(tag,cls)=>{const element=document.createElement(tag);element.className=cls;return element;};
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

function loadImage(url){return new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('The frame preview could not load.'));image.src=url;});}

/** One source-space editor. Display transforms never affect saved mask coordinates. */
export class PaintoutMaskViewer{
  constructor(container,{onChange=()=>{},onCommit=()=>{}}={}){
    this.container=container;this.onChange=onChange;this.onCommit=onCommit;this.width=1;this.height=1;this.frame=-1;
    this.tool='include';this.opacity=.45;this.grow=0;this.feather=0;this.brushSize=30;this.zoom=1;this.pan={x:0,y:0};
    this.positive=[];this.negative=[];this.history=[];this.maskPresent=false;this.version=0;this.maskVersion=0;
    this.root=make('div','zp-editor-viewer');this.root.tabIndex=0;this.root.setAttribute('role','application');this.root.setAttribute('aria-label','Paintout frame editor. Click to include a point. Use the toolbar to change tools.');
    this.canvas=make('canvas','zp-editor-viewer__canvas');this.root.append(this.canvas);container.append(this.root);
    this.ctx=this.canvas.getContext('2d');this.maskCanvas=document.createElement('canvas');this.maskCtx=this.maskCanvas.getContext('2d',{willReadFrequently:true});
    this.proxy=document.createElement('canvas');this.proxyCtx=this.proxy.getContext('2d',{willReadFrequently:true});this.overlay=document.createElement('canvas');
    this.pointerDown=event=>this.startPointer(event);this.pointerMove=event=>this.movePointer(event);this.pointerUp=event=>this.endPointer(event);
    this.root.addEventListener('pointerdown',this.pointerDown);this.root.addEventListener('pointermove',this.pointerMove);this.root.addEventListener('pointerup',this.pointerUp);this.root.addEventListener('pointercancel',this.pointerUp);
    this.root.addEventListener('wheel',event=>this.wheel(event),{passive:false});
    this.root.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){event.preventDefault();this.undo();this.onCommit();}else if(event.key==='0'){event.preventDefault();this.fit();}else if(event.key==='Escape'){this.drag=null;this.draw();}});
    this.root.addEventListener('contextmenu',event=>event.preventDefault());
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(this.root);this.resize();
  }
  async setFrame(url,width,height,frame){
    const key=`${url}|${width}|${height}|${frame}`;if(key===this.frameKey)return;
    const version=++this.version,image=await loadImage(url);if(version!==this.version)return;
    this.frameKey=key;this.image=image;this.effectiveOverlay=null;this.width=Math.max(1,Math.round(width));this.height=Math.max(1,Math.round(height));this.frame=frame;
    this.maskCanvas.width=this.width;this.maskCanvas.height=this.height;this.maskCtx.fillStyle='black';this.maskCtx.fillRect(0,0,this.width,this.height);
    this.positive=[];this.negative=[];this.history=[];this.maskPresent=false;this.maskVersion++;this.overlayKey='';this.zoom=1;this.pan={x:0,y:0};this.draw();
  }
  async setMask(url){
    const version=this.version,revision=++this.maskVersion;this.effectiveOverlay=null;
    if(!url){this.maskPresent=false;this.maskCtx.fillStyle='black';this.maskCtx.fillRect(0,0,this.width,this.height);this.overlayKey='';this.draw();return;}
    const image=await loadImage(url);if(version!==this.version||revision!==this.maskVersion)return;
    this.maskCtx.fillStyle='black';this.maskCtx.fillRect(0,0,this.width,this.height);this.maskCtx.drawImage(image,0,0,this.width,this.height);this.measureMask();this.history=[];this.overlayKey='';this.draw();
  }
  async setDisplayImage(url){const version=this.version,display=this.displayVersion=(this.displayVersion||0)+1,image=await loadImage(url);if(version!==this.version||display!==this.displayVersion)return;this.image=image;this.draw();}
  setSelection({positive=[],negative=[]}={}){this.positive=positive.map(p=>({...p}));this.negative=negative.map(p=>({...p}));this.draw();}
  setTool(tool){if(!['include','exclude','brush','protect','pan'].includes(tool))return;this.tool=tool;this.root.dataset.tool=tool;this.root.setAttribute('aria-label',`Paintout frame editor. ${tool==='include'?'Click to include a point':tool==='exclude'?'Click to exclude a point':tool==='brush'?'Paint the removal area':tool==='protect'?'Erase from the removal mask':'Drag to pan'}.`);this.draw();}
  setGrow(grow,feather){this.effectiveVersion=(this.effectiveVersion||0)+1;this.grow=clamp(Math.round(Number(grow)||0),0,256);this.feather=clamp(Math.round(Number(feather)||0),0,256);this.effectiveOverlay=null;this.overlayKey='';this.draw();}
  async setEffectiveMask(url){const version=this.maskVersion,effective=this.effectiveVersion,image=await loadImage(url);if(version!==this.maskVersion||effective!==this.effectiveVersion)return;const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);for(let i=0;i<pixels.data.length;i+=4){const alpha=pixels.data[i]>127?255:0;pixels.data[i]=245;pixels.data[i+1]=62;pixels.data[i+2]=66;pixels.data[i+3]=alpha;}ctx.putImageData(pixels,0,0);this.effectiveOverlay=canvas;this.draw();}
  setOpacity(value){this.opacity=clamp(Number(value)||0,0,1);this.draw();}
  setBrushSize(value){this.brushSize=clamp(Number(value)||1,1,1000);}
  fit(){this.zoom=1;this.pan={x:0,y:0};this.draw();}
  resize(){const rect=this.root.getBoundingClientRect();this.cssWidth=Math.max(1,rect.width);this.cssHeight=Math.max(1,rect.height);const dpr=Math.min(2,window.devicePixelRatio||1);this.canvas.width=Math.round(this.cssWidth*dpr);this.canvas.height=Math.round(this.cssHeight*dpr);this.ctx.setTransform(dpr,0,0,dpr,0,0);this.draw();}
  transform(){const scale=Math.min(this.cssWidth/this.width,this.cssHeight/this.height)*this.zoom;return {scale,x:(this.cssWidth-this.width*scale)/2+this.pan.x,y:(this.cssHeight-this.height*scale)/2+this.pan.y};}
  point(event){const rect=this.root.getBoundingClientRect(),t=this.transform();return {x:(event.clientX-rect.left-t.x)/t.scale,y:(event.clientY-rect.top-t.y)/t.scale};}
  inside(point){return point.x>=0&&point.y>=0&&point.x<this.width&&point.y<this.height;}
  snapshot(kind='selection'){this.history.push({kind,positive:this.positive.map(p=>({...p})),negative:this.negative.map(p=>({...p})),mask:this.maskCtx.getImageData(0,0,this.width,this.height)});if(this.history.length>12)this.history.shift();}
  changed(kind='selection'){this.maskVersion++;this.effectiveOverlay=null;this.overlayKey='';this.draw();this.onChange({kind,frame:this.frame,positive:this.positive.map(p=>({...p})),negative:this.negative.map(p=>({...p}))});}
  startPointer(event){
    if(!this.image||event.button>1)return;this.root.focus();const p=this.point(event);if(!this.inside(p)&&this.tool!=='pan'&&event.button!==1)return;
    event.preventDefault();this.root.setPointerCapture(event.pointerId);
    if(this.tool==='pan'||event.button===1){this.drag={kind:'pan',x:event.clientX,y:event.clientY,pan:{...this.pan}};return;}
    this.snapshot(['brush','protect'].includes(this.tool)?'paint':'selection');
    if(this.tool==='include'||this.tool==='exclude'){
      const array=this.tool==='include'?this.positive:this.negative,t=this.transform();const found=array.findIndex(existing=>Math.hypot(existing.x-p.x,existing.y-p.y)<10/t.scale);
      if(found>=0)array.splice(found,1);else array.push({x:clamp(Math.round(p.x),0,this.width-1),y:clamp(Math.round(p.y),0,this.height-1)});this.changed();return;
    }
    this.drag={kind:'paint',last:p};this.paint(p,p);this.changed('paint');
  }
  paint(a,b){if(this.tool!=='protect')this.maskPresent=true;this.maskCtx.save();this.maskCtx.strokeStyle=this.tool==='protect'?'black':'white';this.maskCtx.fillStyle=this.maskCtx.strokeStyle;this.maskCtx.lineWidth=this.brushSize;this.maskCtx.lineCap='round';this.maskCtx.lineJoin='round';this.maskCtx.beginPath();this.maskCtx.moveTo(a.x,a.y);this.maskCtx.lineTo(b.x,b.y);this.maskCtx.stroke();this.maskCtx.beginPath();this.maskCtx.arc(b.x,b.y,this.brushSize/2,0,Math.PI*2);this.maskCtx.fill();this.maskCtx.restore();}
  movePointer(event){this.cursor=this.point(event);if(!this.drag){this.draw();return;}if(this.drag.kind==='pan'){this.pan.x=this.drag.pan.x+event.clientX-this.drag.x;this.pan.y=this.drag.pan.y+event.clientY-this.drag.y;this.draw();return;}const p=this.point(event);this.paint(this.drag.last,p);this.drag.last=p;this.changed('paint');}
  endPointer(event){if(this.drag){const painted=this.drag.kind==='paint';this.drag=null;this.draw();if(painted)this.onCommit();}if(this.root.hasPointerCapture(event.pointerId))this.root.releasePointerCapture(event.pointerId);}
  wheel(event){if(!this.image)return;event.preventDefault();const rect=this.root.getBoundingClientRect(),p=this.point(event),old=this.transform();this.zoom=clamp(this.zoom*Math.exp(-event.deltaY*.0015),1,12);const next=this.transform();this.pan.x+=event.clientX-rect.left-(next.x+p.x*next.scale);this.pan.y+=event.clientY-rect.top-(next.y+p.y*next.scale);if(this.zoom===1)this.pan={x:0,y:0};this.draw();}
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
    if(!this.ctx)return;const ctx=this.ctx;ctx.clearRect(0,0,this.cssWidth||1,this.cssHeight||1);if(!this.image)return;const t=this.transform();ctx.drawImage(this.image,t.x,t.y,this.width*t.scale,this.height*t.scale);this.buildOverlay();ctx.save();ctx.globalAlpha=this.opacity;ctx.imageSmoothingEnabled=false;ctx.drawImage(this.effectiveOverlay||this.overlay,t.x,t.y,this.width*t.scale,this.height*t.scale);ctx.restore();
    for(const [points,positive] of [[this.positive,true],[this.negative,false]])for(const p of points){const x=t.x+p.x*t.scale,y=t.y+p.y*t.scale;ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.fillStyle=positive?'#caff00':'#f2f2f0';ctx.fill();ctx.strokeStyle='#101013';ctx.lineWidth=2;ctx.stroke();ctx.beginPath();ctx.moveTo(x-3,y);ctx.lineTo(x+3,y);if(positive){ctx.moveTo(x,y-3);ctx.lineTo(x,y+3);}ctx.stroke();}
    if(this.cursor&&this.inside(this.cursor)&&['brush','protect'].includes(this.tool)){ctx.beginPath();ctx.arc(t.x+this.cursor.x*t.scale,t.y+this.cursor.y*t.scale,this.brushSize*t.scale/2,0,Math.PI*2);ctx.strokeStyle='#101013';ctx.lineWidth=3;ctx.stroke();ctx.strokeStyle='#ffffff';ctx.lineWidth=1;ctx.stroke();}
  }
  measureMask(){const data=this.maskCtx.getImageData(0,0,this.width,this.height).data;let hasMask=false;for(let i=0;i<data.length;i+=4){if(data[i]>0){hasMask=true;break;}}this.maskPresent=hasMask;return hasMask;}
  getSelection(includeImage=true){return {positive:this.positive.map(p=>({...p})),negative:this.negative.map(p=>({...p})),hasMask:includeImage?this.measureMask():this.maskPresent,mask:includeImage?this.maskCanvas.toDataURL('image/png'):undefined};}
  clear(){this.snapshot('paint');this.positive=[];this.negative=[];this.maskCtx.fillStyle='black';this.maskCtx.fillRect(0,0,this.width,this.height);this.maskPresent=false;this.changed();}
  undo(){const previous=this.history.pop();if(!previous)return;this.positive=previous.positive;this.negative=previous.negative;this.maskCtx.putImageData(previous.mask,0,0);this.measureMask();this.changed(previous.kind||'selection');}
  dispose(){this.version++;this.maskVersion++;this.resizeObserver.disconnect();this.root.remove();}
}

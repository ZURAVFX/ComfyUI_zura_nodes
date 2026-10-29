// Zoom the image surface while keeping video transport controls stationary.
export class PreviewZoom {
  constructor(canvas, getMedia) {
    this.canvas=canvas; this.getMedia=getMedia;
    this.scale=1; this.x=0; this.y=0; this.drag=null; this.key=''; this.raf=0;this.observedMedia=null;
    this.toolbar=document.createElement('div');this.toolbar.className='gs-zoom-tools';
    this.toolbar.setAttribute('role','group');this.toolbar.setAttribute('aria-label','Preview zoom');
    this.toolbar.innerHTML='<button type="button" data-zoom="out" aria-label="Zoom out">−</button><button type="button" data-zoom="reset" aria-label="Reset preview position and zoom">100%</button><button type="button" data-zoom="in" aria-label="Zoom in">+</button>';
    this.toolbar.title='Scroll to zoom; drag to pan';canvas.append(this.toolbar);
    this.overlay=document.createElement('canvas');this.overlay.className='gs-zoom-video';this.overlay.hidden=true;canvas.append(this.overlay);
    this.click=e=>{const action=e.target.closest?.('[data-zoom]')?.dataset.zoom;if(!action)return;e.stopPropagation();if(action==='reset')this.reset();else this.setScale(this.scale*(action==='in'?1.25:.8));};
    this.wheel=e=>{if(!this.active() || e.target.closest?.('.gs-zoom-tools, button, input'))return;e.preventDefault();this.setScale(this.scale*Math.exp(-e.deltaY*.0015));};
    this.down=e=>{
      const node=this.active();if(this.scale<=1 || !node || ![0,1].includes(e.button) || e.target.closest?.('.gs-zoom-tools,button,input'))return;
      // Do not intercept the native video transport controls.
      if(node.tagName==='VIDEO' && e.clientY>node.getBoundingClientRect().bottom-55)return;
      e.preventDefault();this.drag={id:e.pointerId,x:e.clientX,y:e.clientY,moved:false};
      this.canvas.setPointerCapture?.(e.pointerId);this.canvas.classList.add('is-panning');
    };
    this.move=e=>{if(!this.drag || e.pointerId!==this.drag.id)return;const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;this.x+=dx;this.y+=dy;this.drag.x=e.clientX;this.drag.y=e.clientY;this.drag.moved ||= Math.abs(dx)+Math.abs(dy)>1;this.paint();};
    this.up=e=>{if(this.drag?.id!==e.pointerId)return;this.suppressClick=this.drag.moved;this.drag=null;this.canvas.classList.remove('is-panning');};
    this.cancelClick=e=>{if(this.suppressClick){e.preventDefault();e.stopPropagation();this.suppressClick=false;}};
    this.reset=()=>{this.scale=1;this.x=0;this.y=0;this.paint();};
    this.refresh=()=>this.paint();
    canvas.addEventListener('wheel',this.wheel,{passive:false});canvas.addEventListener('pointerdown',this.down);
    canvas.addEventListener('pointermove',this.move);canvas.addEventListener('pointerup',this.up);canvas.addEventListener('pointercancel',this.up);
    canvas.addEventListener('click',this.cancelClick,true);this.toolbar.addEventListener('click',this.click);this.paint();
  }
  active(){const node=this.getMedia();return node && !node.hidden ? node : null;}
  observe(node){
    if(this.observedMedia===node)return;
    for(const event of ['loadeddata','play','pause','seeked','timeupdate'])this.observedMedia?.removeEventListener(event,this.refresh);
    this.observedMedia=node?.tagName==='VIDEO'?node:null;
    for(const event of ['loadeddata','play','pause','seeked','timeupdate'])this.observedMedia?.addEventListener(event,this.refresh);
  }
  update(key){if(this.key!==key){this.key=key;this.reset();}else this.paint();}
  setScale(value){this.scale=Math.max(1,Math.min(5,value));if(this.scale===1){this.x=0;this.y=0;}this.paint();}
  paint(){
    const node=this.active(),rect=this.canvas.getBoundingClientRect();this.observe(node);
    const limitX=rect.width*(this.scale-1)/2,limitY=rect.height*(this.scale-1)/2;
    this.x=Math.max(-limitX,Math.min(limitX,this.x));this.y=Math.max(-limitY,Math.min(limitY,this.y));
    this.toolbar.hidden=!node;this.toolbar.querySelector('[data-zoom="reset"]').textContent=`${Math.round(this.scale*100)}%`;
    this.canvas.classList.toggle('is-zoomed',this.scale>1);
    if(node && node.tagName!=='VIDEO')node.style.transform=this.scale===1?'':`translate(${this.x}px, ${this.y}px) scale(${this.scale})`;
    if(node && node.tagName==='VIDEO' && this.scale>1){this.drawVideo(node);}else{this.overlay.hidden=true;this.stopDraw();}
  }
  drawVideo(video){
    const area=this.canvas.getBoundingClientRect(),bounds=video.getBoundingClientRect();
    if(!bounds.width || !bounds.height || !video.videoWidth || !video.videoHeight)return;
    const ratio=Math.min(globalThis.devicePixelRatio||1,2),width=Math.round(bounds.width*ratio),height=Math.round(bounds.height*ratio);
    if(this.overlay.width!==width)this.overlay.width=width;if(this.overlay.height!==height)this.overlay.height=height;
    Object.assign(this.overlay.style,{left:`${bounds.left-area.left}px`,top:`${bounds.top-area.top}px`,width:`${bounds.width}px`,height:`${bounds.height}px`});
    const context=this.overlay.getContext('2d');if(!context)return;
    const fitted=Math.min(bounds.width/video.videoWidth,bounds.height/video.videoHeight),w=video.videoWidth*fitted*this.scale,h=video.videoHeight*fitted*this.scale;
    context.setTransform(ratio,0,0,ratio,0,0);context.fillStyle='#000';context.fillRect(0,0,bounds.width,bounds.height);
    try{context.drawImage(video,(bounds.width-w)/2+this.x,(bounds.height-h)/2+this.y,w,h);this.overlay.hidden=false;}catch{return;}
    this.stopDraw();if(!video.paused && globalThis.requestAnimationFrame)this.raf=requestAnimationFrame(()=>{this.raf=0;if(this.active()===video && this.scale>1)this.drawVideo(video);});
  }
  stopDraw(){if(this.raf && globalThis.cancelAnimationFrame)cancelAnimationFrame(this.raf);this.raf=0;}
  dispose(){this.stopDraw();this.observe(null);this.canvas.removeEventListener('wheel',this.wheel);this.canvas.removeEventListener('pointerdown',this.down);this.canvas.removeEventListener('pointermove',this.move);this.canvas.removeEventListener('pointerup',this.up);this.canvas.removeEventListener('pointercancel',this.up);this.canvas.removeEventListener('click',this.cancelClick,true);this.toolbar.removeEventListener('click',this.click);const node=this.active();if(node && node.tagName!=='VIDEO')node.style.transform='';this.toolbar.remove();this.overlay.remove();}
}

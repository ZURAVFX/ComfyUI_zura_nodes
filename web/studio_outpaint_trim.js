import {ClipTrimmer} from './studio_trim.js';

// Long selections are available only when the verified backend advertises them.
const FPS=24, MAX_FRAMES=120, MAX_START_SECONDS=86400, MAX_HDR_LONG_FRAMES=10000;
const HDR_PIXEL_FRAMES=40_000_000;
const framesFor=seconds=>Math.max(0,Math.ceil(Number(seconds)*FPS-1e-6));

export function hdrOutpaintFrameLimit(source,width,height){
  if(!source || !Number.isInteger(source.width) || !Number.isInteger(source.height) || source.width<1 || source.height<1)return 113;
  if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1)return 0;
  const canvasWidth=Math.ceil(width/64)*64,canvasHeight=Math.ceil(height/64)*64;
  const budget=Math.min(113,Math.floor(HDR_PIXEL_FRAMES/(source.width*source.height)),Math.floor(HDR_PIXEL_FRAMES/(canvasWidth*canvasHeight)));
  return budget<9?0:1+8*Math.floor((budget-1)/8);
}

export class OutpaintTrim {
  constructor(workspace){
    this.workspace=workspace;
    const doc=workspace.page.ownerDocument;
    this.container=doc.createElement('section');
    this.container.className='zo-trim';
    this.container.innerHTML=`<details class="zo-trim-menu"><summary aria-label="Trim footage"><span>Trim footage</span><span data-selection></span><span aria-hidden="true">⌄</span></summary><div class="zo-trim-panel"><div class="zo-trim-toolbar"><strong>Clip length</strong><div><button type="button" data-play>Play selection</button><button type="button" data-use-source>Use entire source</button></div></div><label class="zo-long-option" data-long-option hidden><input type="checkbox" data-long-mode> <span>Long clip · blend transitions</span></label><p data-limit></p><div data-timeline></div><details class="zo-precision"><summary>Precise timing</summary><div data-precision></div></details></div></details>`;
    workspace.$('prompt').before(this.container);
    const precision=this.container.querySelector('[data-precision]');
    for(const id of ['start','duration'])precision.append(workspace.$(id).closest('label'));
    this.button=this.container.querySelector('[data-use-source]');
    this.play=this.container.querySelector('[data-play]');
    this.limit=this.container.querySelector('[data-limit]');
    this.longOption=this.container.querySelector('[data-long-option]');
    this.longMode=this.container.querySelector('[data-long-mode]');
    this.menu=this.container.querySelector('.zo-trim-menu');
    this.selection=this.container.querySelector('[data-selection]');
    this.onOutside=e=>{if(this.menu.open&&!this.container.contains(e.target))this.menu.open=false;};
    this.onEscape=e=>{if(e.key==='Escape'&&this.menu.open){e.preventDefault();e.stopPropagation();this.menu.open=false;this.menu.querySelector('summary').focus({preventScroll:true});}};
    this.menu.addEventListener('toggle',()=>{
      if(this.menu.open){doc.addEventListener('pointerdown',this.onOutside,true);doc.addEventListener('keydown',this.onEscape,true);this.update();}
      else {doc.removeEventListener('pointerdown',this.onOutside,true);doc.removeEventListener('keydown',this.onEscape,true);}
    });
    this.longMode.onchange=()=>this.commit({start:Number(workspace.$('start').value),duration:Number(workspace.$('duration').value)});
    this.trimmer=new ClipTrimmer(this.container.querySelector('[data-timeline]'),{
      onCommit:range=>this.commit(range),
      onSeek:time=>this.seek(time)
    });
    this.button.onclick=()=>this.useSource();
    this.play.onclick=()=>{
      if(workspace.video.paused===false){workspace.video.pause();return;}
      Promise.resolve(workspace.video.play()).catch(()=>workspace.message('Could not play this source preview.'));
    };
    workspace.video.addEventListener('play',()=>{this.play.textContent='Pause';});
    workspace.video.addEventListener('pause',()=>{this.play.textContent='Play selection';});
    for(const id of ['start','duration'])workspace.$(id).onchange=()=>this.commit({start:Number(workspace.$('start').value),duration:Number(workspace.$('duration').value)});
    workspace.video.addEventListener('timeupdate',()=>{
      this.trimmer.setPlayhead(workspace.video.currentTime);
      if(!workspace.video.paused && workspace.video.currentTime>=this.trimmer.range.end)workspace.video.pause();
    });
    workspace.video.addEventListener('play',()=>{
      const {start,end}=this.trimmer.range;
      if(workspace.video.currentTime<start || workspace.video.currentTime>=end)workspace.video.currentTime=start;
    });
  }
  seek(time){try{this.workspace.video.currentTime=time;}catch{/* Metadata may still be loading. */}}
  maxFrames(){if(!this.workspace.$('hdr-output')?.checked)return MAX_FRAMES;const size=this.workspace.dimensions?.();return size?hdrOutpaintFrameLimit(this.workspace.source,size.width,size.height):113;}
  canLong(){const hdr=!!this.workspace.$('hdr-output')?.checked;
    if(hdr)return this.workspace.mode==='black'?this.workspace.capabilities?.hdr_black_long_experiment===true:this.workspace.mode==='expand'&&this.workspace.capabilities?.hdr_expand_long_experiment===true;
    return this.workspace.mode==='expand'&&this.workspace.longReady===true;}
  get long(){return this.canLong() && this.longMode.checked;}
  modeChanged(){
    if(!this.canLong() && this.longMode.checked){this.longMode.checked=false;this.commit({start:Number(this.workspace.$('start').value),duration:Number(this.workspace.$('duration').value)});}
    this.update();
  }
  initial(){
    const source=this.workspace.source;
    this.longMode.checked=false;
    const count=Math.min(this.maxFrames(),framesFor(source?.duration));
    this.workspace.$('start').value='0';
    this.workspace.$('duration').value=String(Math.min(count/FPS, Number(source?.duration)||0));
    this.update();
  }
  commit(range){
    const w=this.workspace,total=Math.min(MAX_START_SECONDS*FPS,framesFor(w.source?.duration));
    if(!total)return;
    if(total<3)return;
    const start=Math.max(0,Math.min(MAX_START_SECONDS*FPS,total-3,Math.round((Number(range.start)||0)*FPS)));
    const maximum=this.long ? Math.min(total-start,w.$('hdr-output')?.checked?MAX_HDR_LONG_FRAMES:total-start) : this.maxFrames();
    const count=Math.max(3,Math.min(maximum,total-start,Math.ceil((Number(range.duration)||0)*FPS-1e-6)));
    w.$('start').value=String(start/FPS);
    w.$('duration').value=String(Math.min(count/FPS, Math.max(0, Number(w.source.duration)-start/FPS)));
    w.invalidate();w.updateModelContext?.();this.update();this.seek(start/FPS);
  }
  useSource(){
    const total=framesFor(this.workspace.source?.duration);
    if(total<3||total>MAX_START_SECONDS*FPS||(this.workspace.$('hdr-output')?.checked&&total>MAX_HDR_LONG_FRAMES))return;
    if(total>this.maxFrames()){if(!this.canLong())return;this.longMode.checked=true;}
    this.commit({start:0,duration:Number(this.workspace.source.duration)});
  }
  update(){
    const w=this.workspace,source=w.source,total=framesFor(source?.duration),busy=!!w.job||w.submitting;
    this.container.hidden=!source;
    this.longOption.hidden=!this.canLong();this.longMode.disabled=busy;
    const maxFrames=this.maxFrames();
    const hdr=!!w.$('hdr-output')?.checked,longMax=hdr?MAX_HDR_LONG_FRAMES:MAX_START_SECONDS*FPS;
    this.button.disabled=busy||total<3||maxFrames<3||total>longMax||(total>maxFrames&&!this.canLong());
    this.play.disabled=busy||total<3;
    this.limit.textContent=total<3?'Choose a source at least 3 frames long.':maxFrames<3?'This HDR source or canvas exceeds the frame memory limit. Use smaller footage or a smaller canvas.':total>MAX_START_SECONDS*FPS?'Select a range within the first 24 hours of the source.':this.long&&hdr?'HDR preview uses overlapping sections, up to 10,000 frames per selection.':this.long?'Long clips use guided, blended sections; rendering takes longer.':total>maxFrames?(this.canLong()?'Use the full source or enable long clips to select a longer range.':`Up to ${Number((maxFrames/FPS).toFixed(2))} seconds per render. Trim the source to continue.`):'The final frame is held if needed for the model.';
    const duration=Number(w.$('duration').value)||0;
    this.selection.textContent=`${duration.toFixed(2).replace(/\.?0+$/,'')}s${this.long?' · long':''}`;
    const url=w.video.currentSrc||w.video.src||'';
    this.trimmer.update(source?{...source,url}:null,{length_mode:'custom',start:Number(w.$('start').value),duration:Number(w.$('duration').value)},{disabled:busy||maxFrames<3,maximum:this.long?(hdr?MAX_HDR_LONG_FRAMES/FPS:null):Math.max(3,maxFrames)/FPS});
  }
  close(){this.menu.open=false;const doc=this.workspace.page.ownerDocument;doc.removeEventListener('pointerdown',this.onOutside,true);doc.removeEventListener('keydown',this.onEscape,true);this.trimmer.close();}
}

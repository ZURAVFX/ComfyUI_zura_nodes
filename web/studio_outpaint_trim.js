import {ClipTrimmer} from './studio_trim.js';

// Long selections are available only when the verified backend advertises them.
const FPS=24, MAX_FRAMES=120, MAX_START_SECONDS=86400, MAX_HDR_LONG_FRAMES=10000;
const HDR_PIXEL_FRAMES=40_000_000;
const framesFor=(seconds,fps=FPS)=>Math.max(0,Math.ceil(Number(seconds)*fps-1e-6));

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
    this.container.setAttribute('aria-label','Frame extension timeline');
    this.container.innerHTML=`<div data-timeline></div>
      <div class="zo-trim-toolbar">
        <button type="button" class="zo-trim-play" data-play><svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path data-play-icon d="M6 3.5 16 10 6 16.5Z" fill="currentColor"/></svg><span data-play-label>Play selection</span></button>
        <div class="zo-trim-options">
          <button type="button" data-trim-result hidden>Show result</button>
          <button type="button" data-use-source>Use entire source</button>
          <label class="zo-long-option" data-long-option hidden><input type="checkbox" data-long-mode>Long clip</label>
          <details class="zo-precision"><summary>Precise timing</summary><div data-precision></div></details>
        </div>
      </div><p data-limit hidden></p>`;
    workspace.stage.after(this.container);
    const precision=this.container.querySelector('[data-precision]');
    for(const id of ['start','duration'])precision.append(workspace.$(id).closest('label'));
    this.button=this.container.querySelector('[data-use-source]');
    this.play=this.container.querySelector('[data-play]');
    this.limit=this.container.querySelector('[data-limit]');
    this.longOption=this.container.querySelector('[data-long-option]');
    this.longMode=this.container.querySelector('[data-long-mode]');
    this.resultButton=this.container.querySelector('[data-trim-result]');
    this.resultButton.onclick=()=>{workspace.showResultAfterTrim();this.syncResultButton();};
    this.longMode.onchange=()=>this.commit({start:Number(workspace.$('start').value),duration:Number(workspace.$('duration').value)});
    this.trimmer=new ClipTrimmer(this.container.querySelector('[data-timeline]'),{
      onCommit:range=>this.commit(range),
      onSeek:time=>{this.showSource();this.seek(time);}
    });
    this.button.onclick=()=>this.useSource();
    this.play.onclick=()=>{
      if(workspace.video.paused===false){workspace.video.pause();return;}
      this.showSource();
      const {start,end}=this.trimmer.range;
      if(workspace.video.currentTime<start||workspace.video.currentTime>=end)this.seek(start);
      Promise.resolve(workspace.video.play()).catch(()=>workspace.message('Could not play this source preview.'));
    };
    const playbackLabel=playing=>{
      this.play.querySelector('[data-play-label]').textContent=playing?'Pause':'Play selection';
      this.play.querySelector('[data-play-icon]').setAttribute('d',playing?'M5 4h3v12H5zM12 4h3v12h-3z':'M6 3.5 16 10 6 16.5Z');
    };
    workspace.video.addEventListener('play',()=>playbackLabel(true));
    for(const event of ['pause','ended','emptied'])workspace.video.addEventListener(event,()=>playbackLabel(false));
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
  showSource(){this.workspace.showSourceForTrim?.();this.syncResultButton();}
  syncResultButton(){this.resultButton.hidden=!(this.workspace.outputRef&&this.workspace.result?.hidden);}
  seek(time){try{this.workspace.video.currentTime=time;}catch{/* Metadata may still be loading. */}}
  fps(){if(this.workspace.$('hdr-output')?.checked)return FPS;const source=this.workspace.source,rate=Number(source?.fps_num)/Number(source?.fps_den);return Number.isFinite(rate)&&rate>=1&&rate<=120?rate:FPS;}
  maxFrames(){if(!this.workspace.$('hdr-output')?.checked)return MAX_FRAMES;const size=this.workspace.dimensions?.();return size?hdrOutpaintFrameLimit(this.workspace.source,size.width,size.height):113;}
  canLong(){const hdr=!!this.workspace.$('hdr-output')?.checked;
    if(hdr)return this.workspace.mode==='black'?this.workspace.capabilities?.hdr_black_long_experiment===true:this.workspace.mode==='expand'&&this.workspace.capabilities?.hdr_expand_long_experiment===true;
    return ['expand','black'].includes(this.workspace.mode)&&this.workspace.longReady===true;}
  get long(){return this.canLong() && this.longMode.checked;}
  modeChanged(){
    if(!this.canLong() && this.longMode.checked){this.longMode.checked=false;this.commit({start:Number(this.workspace.$('start').value),duration:Number(this.workspace.$('duration').value)});}
    this.update();
  }
  initial(){
    const source=this.workspace.source,fps=this.fps();
    this.longMode.checked=false;
    const count=Math.min(this.maxFrames(),framesFor(source?.duration,fps));
    this.workspace.$('start').value='0';
    this.workspace.$('duration').value=String(Math.min(count/fps, Number(source?.duration)||0));
    this.update();
  }
  commit(range){
    const w=this.workspace,fps=this.fps(),total=Math.min(MAX_START_SECONDS*fps,framesFor(w.source?.duration,fps));
    if(!total)return;
    if(total<3)return;
    const start=Math.max(0,Math.min(MAX_START_SECONDS*fps,total-3,Math.round((Number(range.start)||0)*fps)));
    const maximum=this.long ? Math.min(total-start,w.$('hdr-output')?.checked?MAX_HDR_LONG_FRAMES:total-start) : this.maxFrames();
    const count=Math.max(3,Math.min(maximum,total-start,Math.ceil((Number(range.duration)||0)*fps-1e-6)));
    w.$('start').value=String(start/fps);
    w.$('duration').value=String(Math.min(count/fps, Math.max(0, Number(w.source.duration)-start/fps)));
    w.invalidate();w.updateModelContext?.();this.update();this.seek(start/fps);
  }
  useSource(){
    const fps=this.fps(),total=framesFor(this.workspace.source?.duration,fps);
    if(total<3||total>MAX_START_SECONDS*fps||(this.workspace.$('hdr-output')?.checked&&total>MAX_HDR_LONG_FRAMES))return;
    if(total>this.maxFrames()){if(!this.canLong())return;this.longMode.checked=true;}
    this.commit({start:0,duration:Number(this.workspace.source.duration)});
  }
  update(){
    const w=this.workspace,source=w.source,fps=this.fps(),total=framesFor(source?.duration,fps),busy=!!w.job||w.submitting||!!w.hdrBusy?.();
    this.container.hidden=!source;
    this.longOption.hidden=!this.canLong();this.longMode.disabled=busy;
    const maxFrames=this.maxFrames();
    const hdr=!!w.$('hdr-output')?.checked,longMax=hdr?MAX_HDR_LONG_FRAMES:MAX_START_SECONDS*fps;
    this.button.disabled=busy||total<3||maxFrames<3||total>longMax||(total>maxFrames&&!this.canLong());
    const url=w.video.src||w.video.currentSrc||'';
    this.play.disabled=busy||total<3||!url;
    if(busy&&w.video.paused===false)w.video.pause();
    this.syncResultButton();
    this.limit.textContent=total<3?'Choose a source at least 3 frames long.':maxFrames<3?'This HDR source or canvas exceeds the frame memory limit. Use smaller footage or a smaller canvas.':total>MAX_START_SECONDS*fps?'Select a range within the first 24 hours of the source.':this.long&&hdr?'HDR preview uses overlapping sections, up to 10,000 frames per selection.':this.long?'Long clips render in sections and take longer.':total>maxFrames?(this.canLong()?'Use the full source or enable long clips to select a longer range.':`Up to ${Number((maxFrames/fps).toFixed(2))} seconds per render. Trim the source to continue.`):'';
    this.limit.hidden=!this.limit.textContent;
    this.trimmer.update(source?{...source,url}:null,{length_mode:'custom',start:Number(w.$('start').value),duration:Number(w.$('duration').value)},{disabled:busy||maxFrames<3,maximum:this.long?(hdr?MAX_HDR_LONG_FRAMES/fps:null):Math.max(3,maxFrames)/fps});
    // ClipTrimmer defaults to 24 fps; this workspace follows the source rate.
    this.trimmer.fps=fps;this.trimmer.paint();
    this.trimmer.setPlayhead(Number(w.video.currentTime)||0);
  }
  close(){this.container.querySelector('.zo-precision').open=false;this.trimmer.close();}
}

import {ClipTrimmer} from './studio_trim.js';

// Long selections are available only when the verified backend advertises them.
const FPS=24, MAX_FRAMES=120, MAX_START_SECONDS=86400;
const framesFor=seconds=>Math.max(0,Math.floor(Number(seconds)*FPS+1e-6));

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
  canLong(){return this.workspace.longReady===true && this.workspace.mode==='expand';}
  get long(){return this.canLong() && this.longMode.checked;}
  modeChanged(){
    if(!this.canLong() && this.longMode.checked){this.longMode.checked=false;this.commit({start:Number(this.workspace.$('start').value),duration:Number(this.workspace.$('duration').value)});}
    this.update();
  }
  initial(){
    const source=this.workspace.source;
    this.longMode.checked=false;
    const count=Math.min(MAX_FRAMES,framesFor(source?.duration));
    this.workspace.$('start').value='0';
    this.workspace.$('duration').value=String(count/FPS);
    this.update();
  }
  commit(range){
    const w=this.workspace,total=Math.min(MAX_START_SECONDS*FPS,framesFor(w.source?.duration));
    if(!total)return;
    if(total<3)return;
    const start=Math.max(0,Math.min(MAX_START_SECONDS*FPS,total-3,Math.round((Number(range.start)||0)*FPS)));
    const maximum=this.long ? total-start : MAX_FRAMES;
    const count=Math.max(3,Math.min(maximum,total-start,Math.round((Number(range.duration)||0)*FPS)));
    w.$('start').value=String(start/FPS);
    w.$('duration').value=String(count/FPS);
    w.invalidate();w.updateModelContext?.();this.update();this.seek(start/FPS);
  }
  useSource(){
    const total=framesFor(this.workspace.source?.duration);
    if(total<3||total>MAX_START_SECONDS*FPS)return;
    if(total>MAX_FRAMES){if(!this.canLong())return;this.longMode.checked=true;}
    this.commit({start:0,duration:total/FPS});
  }
  update(){
    const w=this.workspace,source=w.source,total=framesFor(source?.duration),busy=!!w.job||w.submitting;
    this.container.hidden=!source;
    this.longOption.hidden=!this.canLong();this.longMode.disabled=busy;
    this.button.disabled=busy||total<3||total>MAX_START_SECONDS*FPS||(total>MAX_FRAMES&&!this.canLong());
    this.play.disabled=busy||total<3;
    this.limit.textContent=total<3?'Choose a source at least 3 frames long.':total>MAX_START_SECONDS*FPS?'Select a range within the first 24 hours of the source.':this.long?'Long clips use guided, blended sections; rendering takes longer.':total>MAX_FRAMES?(this.canLong()?'Use the full source or enable long clips to select more than 5 seconds.':'Up to 5 seconds per render. Trim the source to continue.'):'Your output uses the selected source range at 24 fps.';
    const duration=Number(w.$('duration').value)||0;
    this.selection.textContent=`${duration.toFixed(2).replace(/\.?0+$/,'')}s${this.long?' · long':''}`;
    const url=w.video.currentSrc||w.video.src||'';
    this.trimmer.update(source?{...source,url}:null,{length_mode:'custom',start:Number(w.$('start').value),duration:Number(w.$('duration').value)},{disabled:busy,maximum:this.long?null:MAX_FRAMES/FPS});
  }
  close(){this.menu.open=false;const doc=this.workspace.page.ownerDocument;doc.removeEventListener('pointerdown',this.onOutside,true);doc.removeEventListener('keydown',this.onEscape,true);this.trimmer.close();}
}

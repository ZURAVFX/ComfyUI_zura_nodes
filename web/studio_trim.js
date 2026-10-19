const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));
export function trimRange(config={},seconds=0){
  const total=Math.max(0,Number(seconds)||0),original=config.length_mode==="original";
  const start=original?0:clamp(Number(config.start)||0,0,total);
  return {start,end:original?total:clamp(start+(Number(config.duration)||2),start,total),total};
}
export function trimEdge(range,edge,time,maximum=null){
  const min=Math.min(.25,range.total),max=maximum||range.total;
  const snap=Math.round(time*24)/24;
  if(edge==="start"){
    const start=clamp(snap,0,Math.max(0,range.end-min));
    return {...range,start,end:Math.min(range.end,start+max)};
  }
  const end=clamp(snap,Math.min(range.total,range.start+min),range.total);
  return {...range,end,start:Math.max(range.start,end-max)};
}
export function trimTime(seconds){
  const frames=Math.max(0,Math.round((Number(seconds)||0)*24));
  return `${Math.floor(frames/1440)}:${String(Math.floor(frames/24)%60).padStart(2,'0')}.${String(frames%24).padStart(2,'0')}`;
}

/** Local source trimming. One commit on release, never an API call per pointer move. */
export class ClipTrimmer {
  constructor(host,{onCommit,onSeek}={}){
    this.host=host;this.onCommit=onCommit;this.onSeek=onSeek;this.range={start:0,end:0,total:0};
    host.innerHTML=`<div class="gs-trim-heading"><strong>Trim source</strong><output data-range></output></div>
      <div class="gs-trim-track" data-track><div class="gs-trim-film" data-film aria-hidden="true"></div><div class="gs-trim-shade is-before"></div><div class="gs-trim-shade is-after"></div><div class="gs-trim-selection" aria-hidden="true"></div><span class="gs-trim-playhead" data-playhead hidden></span><button type="button" class="gs-trim-handle is-start" data-edge="start" role="slider" aria-label="Trim start" aria-valuemin="0" aria-valuemax="0" aria-valuenow="0"></button><button type="button" class="gs-trim-handle is-end" data-edge="end" role="slider" aria-label="Trim end" aria-valuemin="0" aria-valuemax="0" aria-valuenow="0"></button></div>
      <div class="gs-trim-caption"><span>Drag either edge · click to scrub</span><output data-duration></output></div>`;
    this.track=host.querySelector('[data-track]');
    for(const handle of host.querySelectorAll('[data-edge]')){
      handle.onpointerdown=e=>{
        if(this.disabled || e.button>0)return;
        e.preventDefault();e.stopPropagation();this.drag={edge:handle.dataset.edge,id:e.pointerId,handle,before:{...this.range}};
        handle.setPointerCapture?.(e.pointerId);handle.focus({preventScroll:true});
      };
      handle.onpointermove=e=>{if(this.drag?.handle===handle && this.drag.id===e.pointerId)this.move(handle.dataset.edge,this.timeAt(e.clientX));};
      handle.onpointerup=e=>{
        if(this.drag?.handle!==handle || this.drag.id!==e.pointerId)return;
        this.move(handle.dataset.edge,this.timeAt(e.clientX));this.drag=null;handle.releasePointerCapture?.(e.pointerId);this.commit();
      };
      handle.onpointercancel=handle.onlostpointercapture=()=>{if(this.drag?.handle===handle){this.range=this.drag.before;this.drag=null;this.paint();}};
      handle.onkeydown=e=>{
        if(this.disabled || !['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
        e.preventDefault();e.stopPropagation();
        const edge=handle.dataset.edge,value=this.range[edge];
        const time=e.key==='Home'?0:e.key==='End'?this.range.total:value+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?1:1/24);
        this.move(edge,time);this.commit();
      };
    }
    this.track.onpointerdown=e=>{if(!this.disabled && !e.target.closest('[data-edge]'))this.onSeek?.(this.timeAt(e.clientX));};
  }
  timeAt(clientX){const box=this.track.getBoundingClientRect();return clamp((clientX-box.left)/Math.max(1,box.width),0,1)*this.range.total;}
  move(edge,time){this.range=trimEdge(this.range,edge,time,this.maximum);this.paint();this.onSeek?.(this.range[edge]);}
  commit(){this.onCommit?.({start:this.range.start,duration:this.range.end-this.range.start});}
  update(source,config,{disabled=false,maximum=null}={}){
    const key=source?.url||'';
    if(disabled || key!==this.sourceKey)this.drag=null;
    this.disabled=disabled;this.maximum=maximum;
    this.host.hidden=!source || !(Number(source.duration)>0);
    if(!this.drag)this.range=trimRange(config,source?.duration);
    for(const handle of this.host.querySelectorAll('[data-edge]'))handle.disabled=disabled;
    this.paint();
    if(key!==this.sourceKey){this.sourceKey=key;this.clearFilm();if(key)this.loadFilm(key);}
  }
  paint(){
    const {start,end,total}=this.range;
    this.host.style.setProperty('--trim-in',`${total?start/total*100:0}%`);
    this.host.style.setProperty('--trim-out',`${total?end/total*100:100}%`);
    this.host.querySelector('[data-range]').textContent=`${trimTime(start)} – ${trimTime(end)}`;
    this.host.querySelector('[data-duration]').textContent=`${(end-start).toFixed(2)}s selected${this.maximum?` · ${this.maximum.toFixed(2).replace(/\.?0+$/,'')}s max`:''}`;
    for(const handle of this.host.querySelectorAll('[data-edge]')){
      const edge=handle.dataset.edge,value=this.range[edge];
      handle.setAttribute('aria-valuenow',String(value));handle.setAttribute('aria-valuetext',trimTime(value));
      handle.setAttribute('aria-valuemax',String(edge==='start'?Math.max(0,end-.25):total));
      handle.setAttribute('aria-valuemin',String(edge==='end'?Math.min(total,start+.25):0));
    }
  }
  setPlayhead(time){const line=this.host.querySelector('[data-playhead]');line.hidden=!this.range.total;line.style.left=`${this.range.total?clamp(time/this.range.total,0,1)*100:0}%`;}
  clearFilm(){
    this.filmEpoch=(this.filmEpoch||0)+1;this.stopFilm?.();this.stopFilm=null;
    this.host.querySelector('[data-film]').replaceChildren();
    this.host.querySelector('[data-playhead]').hidden=true;
  }
  async loadFilm(url){
    // Eight small frames, decoded sequentially on the client. No model or upload.
    if(typeof this.host.ownerDocument.defaultView?.HTMLVideoElement?.prototype?.canPlayType!=='function')return;
    const epoch=this.filmEpoch,doc=this.host.ownerDocument,video=doc.createElement('video');
    video.muted=true;video.preload='metadata';video.playsInline=true;
    let cancelWait;
    const stop=()=>{cancelWait?.();video.pause();video.removeAttribute('src');video.load();};this.stopFilm=stop;
    const wait=event=>new Promise((resolve,reject)=>{
      const cleanup=()=>{clearTimeout(timer);video.removeEventListener(event,ok);video.removeEventListener('error',fail);cancelWait=null;};
      const ok=()=>{cleanup();resolve();},fail=()=>{cleanup();reject(new Error('Preview unavailable'));};
      const timer=setTimeout(fail,6000);cancelWait=fail;video.addEventListener(event,ok,{once:true});video.addEventListener('error',fail,{once:true});
    });
    try{
      const loaded=wait('loadedmetadata');video.src=url;video.load();await loaded;
      const canvas=doc.createElement('canvas');canvas.width=128;canvas.height=72;const ctx=canvas.getContext('2d');if(!ctx)return;
      for(let i=0;i<8 && epoch===this.filmEpoch;i++){
        const ready=wait('seeked');video.currentTime=Math.min(Math.max(0,video.duration-.01),(.5+i)/8*video.duration);await ready;
        if(epoch!==this.filmEpoch)break;
        ctx.drawImage(video,0,0,128,72);const image=doc.createElement('img');image.alt='';image.src=canvas.toDataURL('image/jpeg',.65);this.host.querySelector('[data-film]').appendChild(image);
      }
    }catch{/* Trimming remains usable when this browser cannot decode a preview. */}
    finally{stop();if(this.stopFilm===stop)this.stopFilm=null;}
  }
  close(){this.sourceKey='';this.clearFilm();}
}

import {maskIcons} from './paintout_icons.js';
const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
const finite=(value,fallback)=>Number.isFinite(Number(value))?Number(value):fallback;

/** Timeline with distinct seek and clean-frame lanes. Frame labels stay absolute. */
export class PaintoutTimeline{
  constructor(container,{onSeek=()=>{},onCreate=()=>{},onSelect=()=>{},onRemove=()=>{},onMaskSelect=()=>{},onTrim=()=>{}}={}){
    this.container=container;this.callbacks={onSeek,onCreate,onSelect,onRemove,onMaskSelect,onTrim};
    this.state={startFrame:0,frameCount:1,fps:24,playhead:0,anchors:[],selected:-1,busy:false,thumbnail:null,maskRanges:[]};
    this.windowSize=Infinity;this.windowStart=0;this.dragging=false;
    this.root=el('section','zp-editor-timeline');this.root.setAttribute('aria-label','Paintout source timeline');
    this.header=el('div','zp-editor-timeline__header');this.title=el('strong','', 'Source timeline');
    this.zoomOut=el('button','zp-editor-icon-button','−');this.zoomOut.type='button';this.zoomOut.setAttribute('aria-label','Zoom out timeline');
    this.zoomIn=el('button','zp-editor-icon-button','+');this.zoomIn.type='button';this.zoomIn.setAttribute('aria-label','Zoom in timeline');
    this.zoomValue=el('span','zp-editor-timeline__zoom','100%');this.addFrame=el('button','zp-editor-add-frame');this.addFrame.type='button';this.addFrame.innerHTML=maskIcons['circle-plus']+'<span>Add clean frame</span>';this.addFrame.title='Add a clean frame at the playhead (K)';this.addFrame.onclick=()=>{if(!this.state.busy)this.callbacks.onCreate(this.state.playhead);};this.header.append(this.title,this.addFrame,this.zoomOut,this.zoomValue,this.zoomIn);
    this.lanes=el('div','zp-editor-timeline__lanes');
    this.cleanLane=el('div','zp-editor-timeline__clean-lane');this.cleanLane.setAttribute('role','group');this.cleanLane.setAttribute('aria-label','Clean frame cards. Click an empty position to add a clean frame.');
    this.cleanLabel=el('span','zp-editor-timeline__lane-label','Clean frames');
    this.cards=el('div','zp-editor-timeline__cards');this.cleanLane.append(this.cleanLabel,this.cards);
    this.ruler=el('div','zp-editor-timeline__ruler');this.ruler.setAttribute('role','group');this.ruler.setAttribute('aria-label','Scrub source footage');this.ruler.tabIndex=0;
    this.ticks=el('div','zp-editor-timeline__ticks');this.coverage=el('div','zp-editor-timeline__coverage');this.playheadLine=el('div','zp-editor-timeline__playhead');
    this.range=el('input','zp-editor-timeline__scrub');this.range.type='range';this.range.min='0';this.range.max='0';this.range.value='0';this.range.step='1';this.range.setAttribute('aria-label','Source frame');
    this.maskAnchors=el('div','zp-editor-timeline__mask-anchors');
    this.trimSelection=el('div','zp-editor-timeline__selected-range');
    this.trimHandles={};
    for(const edge of ['in','out']){
      const handle=el('button','zp-editor-trim-handle zp-editor-trim-handle--'+edge);handle.type='button';handle.dataset.trim=edge;handle.setAttribute('aria-label',edge==='in'?'Trim start frame':'Trim end frame');handle.innerHTML='<svg width="10" height="20" viewBox="0 0 10 20" aria-hidden="true"><path d="M3 4v12M7 4v12" stroke="currentColor" stroke-width="1.5"/></svg>';
      handle.onpointerdown=event=>{if(this.state.busy)return;event.preventDefault();event.stopPropagation();this.trimDrag=edge;handle.setPointerCapture(event.pointerId);};
      handle.onpointermove=event=>{if(this.trimDrag!==edge)return;event.preventDefault();this.trimToPointer(edge,event,false);};
      handle.onpointerup=event=>{if(this.trimDrag!==edge)return;event.preventDefault();event.stopPropagation();this.trimToPointer(edge,event,true);this.trimDrag=null;if(handle.hasPointerCapture(event.pointerId))handle.releasePointerCapture(event.pointerId);};
      handle.onpointercancel=event=>{if(this.trimDrag===edge){this.trimDrag=null;this.callbacks.onTrim(this.state.startFrame,this.state.startFrame+this.state.frameCount-1,true);}};
      handle.onkeydown=event=>{if(this.state.busy||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();event.stopPropagation();const current=edge==='in'?this.state.startFrame:this.state.startFrame+this.state.frameCount-1;this.trimTo(edge,event.key==='Home'?0:event.key==='End'?this.totalFrames-1:current+(event.key==='ArrowLeft'?-1:1)*(event.shiftKey?10:1),true);};
      this.trimHandles[edge]=handle;
    }
    this.ruler.append(this.trimSelection,this.trimHandles.in,this.trimHandles.out);
    this.ruler.append(this.ticks,this.coverage,this.playheadLine,this.range,this.maskAnchors);
    this.readout=el('div','zp-editor-timeline__readout');this.frameText=el('span','','Frame 0');this.timeText=el('span','','00:00:00:00');this.help=el('span','zp-editor-timeline__hint','Scrub to a frame, then choose Add clean frame · K');
    this.trimText=el('span','zp-editor-timeline__trim-readout');this.trimText.title='Drag the In and Out handles to trim. Arrow keys adjust a focused handle.';this.readout.append(this.frameText,this.timeText,this.trimText,this.help);this.lanes.append(this.cleanLane,this.ruler,this.readout);this.root.append(this.header,this.lanes);container.append(this.root);
    this.range.addEventListener('input',()=>{this.dragging=true;this.seekFromInput(true);});
    this.range.addEventListener('change',()=>{this.dragging=false;this.seekFromInput(false);});
    this.range.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End','PageUp','PageDown'].includes(event.key)){event.stopPropagation();}});
    this.cleanLane.addEventListener('click',event=>this.createAtPointer(event));
    this.ruler.addEventListener('click',event=>{if(event.target===this.range||event.target.closest('button'))return;const rect=this.ruler.getBoundingClientRect();const t=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width));this.seek(Math.round(this.visibleStart()+t*(this.visibleEnd()-this.visibleStart()-1)));});
    this.root.addEventListener('keydown',event=>this.onKeydown(event));
    this.zoomIn.onclick=()=>this.setZoom(this.windowSize/1.5);this.zoomOut.onclick=()=>this.setZoom(this.windowSize*1.5);
    this.resizeObserver=typeof ResizeObserver!=='undefined'?new ResizeObserver(()=>this.render()):null;this.resizeObserver?.observe(this.root);
    this.render();
  }
  update(next={}){
    Object.assign(this.state,next);
    this.state.startFrame=Math.max(0,Math.trunc(finite(this.state.startFrame,0)));
    this.state.frameCount=Math.max(1,Math.trunc(finite(this.state.frameCount,1)));
    this.state.fps=Math.max(.001,finite(this.state.fps,24));
    this.state.playhead=Math.max(0,Math.trunc(finite(this.state.playhead,0)));
    const total=this.state.totalFrames||this.state.sourceFrames||this.state.startFrame+this.state.frameCount;
    this.totalFrames=Math.max(1,Math.trunc(finite(total,this.state.startFrame+this.state.frameCount)));
    if(!this.userZoom||this.windowSize>=this.totalFrames)this.windowSize=this.totalFrames;
    if(this.state.playhead<this.windowStart||this.state.playhead>=this.visibleEnd())this.windowStart=this.state.playhead-Math.floor(this.windowSize/2);
    this.windowStart=Math.max(0,Math.min(this.totalFrames-this.windowSize,this.windowStart));
    this.render();
  }
  visibleStart(){return this.windowStart;}
  visibleEnd(){return Math.min(this.totalFrames,this.windowStart+this.windowSize);}
  position(frame){const span=Math.max(1,this.visibleEnd()-this.visibleStart()-1);return Math.max(0,Math.min(100,(frame-this.visibleStart())/span*100));}
  seek(frame){const f=Math.max(0,Math.min(this.totalFrames-1,Math.round(frame)));this.state.playhead=f;this.range.value=String(f);this.updateReadout();this.updatePlayheadLine();this.callbacks.onSeek(f);}
  seekFromInput(final){const f=Number(this.range.value);this.state.playhead=f;this.updateReadout();this.updatePlayheadLine();this.callbacks.onSeek(f,{preview:!final});}
  createAtPointer(event){
    if(event.target.closest('.zp-editor-frame-card')||this.state.busy)return;
    const rect=this.cards.getBoundingClientRect();const fraction=Math.max(0,Math.min(1,(event.clientX-rect.left)/Math.max(1,rect.width)));
    const frame=Math.max(0,Math.min(this.totalFrames-1,Math.round(this.visibleStart()+fraction*(this.visibleEnd()-this.visibleStart()-1))));
    this.callbacks.onCreate(frame);
  }
  trimToPointer(edge,event,commit){const rect=this.ruler.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,(event.clientX-rect.left)/Math.max(1,rect.width)));this.trimTo(edge,Math.round(this.visibleStart()+fraction*(this.visibleEnd()-this.visibleStart()-1)),commit);}
  trimTo(edge,frame,commit){
    let start=this.state.startFrame,end=start+this.state.frameCount-1;
    if(edge==='in')start=Math.max(0,end-992,Math.min(end,Math.round(frame)));
    else end=Math.min(this.totalFrames-1,start+992,Math.max(start,Math.round(frame)));
    this.state.startFrame=start;this.state.frameCount=end-start+1;this.render();this.callbacks.onTrim(start,end,commit);
  }
  setZoom(frames){
    this.userZoom=true;
    this.windowSize=Math.max(Math.min(32,this.totalFrames),Math.min(this.totalFrames,Math.max(12,Math.round(frames/12)*12)));
    this.windowStart=Math.max(0,Math.min(this.totalFrames-this.windowSize,this.state.playhead-Math.floor(this.windowSize/2)));this.render();
  }
  onKeydown(event){
    if(event.defaultPrevented||event.target.matches('input,textarea,select,[contenteditable=true]'))return;
    if(event.key.toLowerCase()==='k'&&!event.ctrlKey&&!event.metaKey&&!this.state.busy){event.preventDefault();this.callbacks.onCreate(this.state.playhead);return;}
    if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();this.seek(this.state.playhead+(event.key==='ArrowLeft'?-1:1));}
  }
  updateReadout(){
    const frame=this.state.playhead;this.frameText.textContent=`Frame ${frame}`;
    const start=this.state.startFrame,end=start+this.state.frameCount-1;this.trimText.textContent=`In ${start} · Out ${end} · ${this.state.frameCount} frames`;this.trimSelection.style.left=this.position(start)+'%';this.trimSelection.style.width=Math.max(0,this.position(end)-this.position(start))+'%';
    for(const [edge,frame]of [['in',start],['out',end]]){const handle=this.trimHandles[edge];handle.style.left=this.position(frame)+'%';handle.disabled=this.state.busy;handle.title=`${edge==='in'?'In':'Out'}: frame ${frame}. Drag to trim.`;handle.setAttribute('aria-valuetext',String(frame));handle.hidden=frame<this.visibleStart()||frame>=this.visibleEnd();}
    this.timeText.textContent=`${(frame/this.state.fps).toFixed(3)} s · ${Number(this.state.fps.toFixed(3))} fps`;
    this.range.setAttribute('aria-valuetext',`Frame ${frame}`);
  }
  updatePlayheadLine(){this.playheadLine.style.left=`${this.position(this.state.playhead)}%`;}
  renderTicks(){
    this.ticks.replaceChildren();const start=this.visibleStart(),end=this.visibleEnd(),span=Math.max(1,end-start);
    const count=5;for(let index=0;index<=count;index++){
      const fraction=index/count,frame=Math.round(start+fraction*(span-1));const tick=el('span','zp-editor-timeline__tick',String(frame));tick.style.left=`${fraction*100}%`;this.ticks.append(tick);
    }
    this.coverage.replaceChildren();for(const range of this.state.maskRanges||[]){
      const from=Math.max(start,Math.trunc(finite(range.start??range.start_frame,0))),to=Math.min(end,Math.trunc(finite(range.end??range.end_frame,from)));
      if(to<from)continue;const mark=el('span','zp-editor-timeline__coverage-range');mark.style.left=`${this.position(from)}%`;mark.style.width=`${Math.max(.35,this.position(to)-this.position(from))}%`;mark.classList.toggle('is-review',range.status==='review'||range.status==='needs_review');mark.title=range.label|| (range.status==='review'||range.status==='needs_review'?'Mask needs review (advisory)':'Tracked mask');this.coverage.append(mark);
    }
    this.maskAnchors.replaceChildren();const seen=new Set();
    for(const range of this.state.maskRanges||[]){const frame=range.metadata?.frame;if(!Number.isInteger(frame)||frame<start||frame>=end||seen.has(frame))continue;seen.add(frame);const marker=el('button','zp-editor-timeline__mask-anchor');marker.type='button';marker.disabled=this.state.busy;marker.style.left=`${this.position(frame)}%`;marker.title=`Mask correction at source frame ${frame}`;marker.setAttribute('aria-label',marker.title);marker.onclick=event=>{event.stopPropagation();this.callbacks.onMaskSelect(frame);};this.maskAnchors.append(marker);}
  }
  renderCards(){
    this.cards.replaceChildren();const {anchors,selected,thumbnail,busy}=this.state,start=this.visibleStart(),end=this.visibleEnd(),rows=[];let tallest=0;
    anchors.forEach((anchor,index)=>{
      const frame=Math.trunc(finite(anchor.frame,0));if(frame<start||frame>=end)return;
      const position=this.position(frame),pixel=(this.cards.clientWidth||600)*position/100;let row=rows.findIndex(positions=>positions.every(last=>Math.abs(pixel-last)>=102));if(row<0){row=rows.length;rows.push([]);}rows[row].push(pixel);tallest=Math.max(tallest,row);
      const outsideTrim=frame<this.state.startFrame||frame>=this.state.startFrame+this.state.frameCount;
      const card=el('article','zp-editor-frame-card');card.classList.toggle('is-outside-trim',outsideTrim);card.title=outsideTrim?'Outside trim. Kept for later; extend the In/Out range to use this guide.':'';card.style.left=`${position}%`;card.style.bottom=`${8+row*82}px`;card.classList.toggle('is-selected',index===selected);card.classList.toggle('is-disabled',anchor.enabled===false);card.classList.toggle('is-review',anchor.status==='needs_review'||anchor.status==='failed');
      const pick=el('button','zp-editor-frame-card__select');pick.type='button';pick.disabled=busy;pick.setAttribute('aria-pressed',String(index===selected));pick.setAttribute('aria-label',`${anchor.status==='accepted'?'Accepted clean frame':'Clean frame'} at source frame ${frame}${outsideTrim?', outside trim, excluded from render':anchor.enabled===false?', disabled':''}`);
      const image=el('img','zp-editor-frame-card__image');image.alt='';image.loading='lazy';image.draggable=false;const src=typeof thumbnail==='function'?thumbnail(anchor):anchor.thumbnail||anchor.url||anchor.file;if(src)image.src=src;image.onerror=()=>{image.removeAttribute('src');image.classList.add('is-unavailable');};
      const state=outsideTrim?'Outside trim':anchor.enabled===false?'Disabled':anchor.status==='accepted'?'Ready':anchor.status==='needs_review'?'Review':anchor.status==='failed'?'Failed':anchor.status==='generating'?'Working':'Draft';
      const meta=el('span','zp-editor-frame-card__meta');meta.append(el('strong','',String(frame)),el('small','',state));pick.append(image,meta);pick.onclick=event=>{event.stopPropagation();this.callbacks.onSelect(index);};
      const remove=el('button','zp-editor-frame-card__remove','×');remove.type='button';remove.disabled=busy;remove.setAttribute('aria-label',`Remove clean frame at source frame ${frame}`);remove.onclick=event=>{event.stopPropagation();this.callbacks.onRemove(index);};
      card.append(pick,remove);this.cards.append(card);
    });
    this.cards.style.height=`${82*(tallest+1)}px`;this.cleanLane.style.minHeight=`${108+82*tallest}px`;
  }
  render(){
    this.root.style.setProperty('--zp-editor-timeline-zoom',String(this.totalFrames/Math.max(1,this.windowSize)));
    this.zoomValue.textContent=`${Math.round(this.totalFrames/Math.max(1,this.windowSize)*100)}%`;
    this.addFrame.disabled=this.state.busy;
    this.zoomIn.disabled=this.windowSize<=Math.min(32,this.totalFrames)||this.state.busy;this.zoomOut.disabled=this.windowSize>=this.totalFrames||this.state.busy;
    this.range.min=String(this.visibleStart());this.range.max=String(Math.max(this.visibleStart(),this.visibleEnd()-1));if(!this.dragging)this.range.value=String(Math.min(this.state.playhead,this.totalFrames-1));
    this.renderCards();this.renderTicks();this.updateReadout();this.updatePlayheadLine();
    this.cleanLane.setAttribute('aria-description',`${this.state.anchors.length} clean frames. Click an empty position above the ruler to add one. Press K at the playhead to add one.`);
  }
  dispose(){this.resizeObserver?.disconnect();this.root.remove();}
}

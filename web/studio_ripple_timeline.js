import {PaintoutTimeline} from './paintout_studio/paintout_timeline.js';

/** Reuse Paintout's visual cards, trim handles and timeline navigation. */
export class RippleTimeline extends PaintoutTimeline {
  constructor(host,workspace){
    super(host,{
      onSeek:frame=>workspace.seek(frame),
      onCreate:frame=>workspace.addAnchor(frame),
      onSelect:index=>workspace.selectAnchor(workspace.anchors()[index]?.id),
      onRemove:index=>{workspace.selectAnchor(workspace.anchors()[index]?.id);workspace.removeAnchor();},
      onTrim:(start,end,commit)=>{if(commit)workspace.setTrim({start:start/workspace.fps(),duration:(end-start+1)/workspace.fps()});},
    });
    this.workspace=workspace;this.root.classList.add('zru-visual-timeline');
    this.addFrame.onclick=()=>{if(this.state.busy)return;if(workspace.state.engine==='ltx')workspace.addAnchor(workspace.state.startFrame);else workspace.addAtPlayhead();};
    this.root.setAttribute('aria-label','Ripple source timeline');
    this.addFrame.dataset.addOnTrack='';this.range.dataset.scrub='';
    this.film=host.ownerDocument.createElement('div');this.film.className='zru-film';this.film.setAttribute('aria-hidden','true');this.ruler.prepend(this.film);
    this.ruler.addEventListener('dblclick',event=>{
      if(this.state.busy||event.target.closest('button,.zp-editor-frame-card,.zp-editor-trim-handle'))return;
      const rect=this.ruler.getBoundingClientRect();
      const fraction=Math.max(0,Math.min(1,(event.clientX-rect.left)/Math.max(1,rect.width)));
      const frame=Math.round(this.visibleStart()+fraction*(this.visibleEnd()-this.visibleStart()-1));
      event.preventDefault();workspace.addAnchor(frame);
    });
    this.render();
  }
  setPlayhead(frame){
    this.state.playhead=frame;this.range.value=String(frame);this.updateReadout();this.updatePlayheadLine();this.updateAddAction();
  }
  onKeydown(event){
    if(!event.defaultPrevented&&this.state.stage==='clean'&&event.key.toLowerCase()==='k'&&!event.ctrlKey&&!event.metaKey&&!this.state.busy&&!event.target.closest('input,textarea,select,[contenteditable="true"]')){event.preventDefault();this.workspace.addAtPlayhead();return;}
    super.onKeydown(event);
  }
  updateAddAction(){
    const first=this.workspace?.state.engine==='ltx',frame=first?this.workspace.state.startFrame:this.state.playhead;
    this.addFrame.querySelector('span').textContent=first?`Edit first frame · ${frame}`:'Add keyframe';
    this.addFrame.title=first?`LTX uses only the first frame of the selected clip: source frame ${frame}`:`Add an edited keyframe at source frame ${frame} (K)`;
  }
  render(){
    super.render();
    this.title.textContent='Edit timeline';this.cleanLabel.textContent='Edited frames';
    this.updateAddAction();
    this.help.textContent=this.workspace?.state.engine==='ltx'?'LTX edits the clip’s first frame only · Use H3 for other keyframes':'Double-click footage or click above it to add a keyframe · K';
    this.cleanLane.setAttribute('aria-label','Edited keyframes. Click an empty position to add one.');
    this.cleanLane.setAttribute('aria-description',`${this.state.anchors.length} edited keyframes. ${this.workspace?.state.engine==='ltx'?`LTX uses only source frame ${this.state.startFrame}. Choose Edit first frame to edit it.`:'Press K to add one at the playhead.'}`);
    const visible=this.state.anchors.filter(a=>Number(a.frame)>=this.visibleStart()&&Number(a.frame)<this.visibleEnd());
    this.root.classList.toggle('has-keyframes',visible.length>0);
    [...this.cards.children].forEach((card,index)=>{
      const anchor=visible[index],ltxUnused=this.workspace?.state.engine==='ltx'&&Number(anchor?.frame)!==this.state.startFrame;
      const frame=card.querySelector('strong').textContent,pick=card.querySelector('.zp-editor-frame-card__select'),remove=card.querySelector('.zp-editor-frame-card__remove');
      card.classList.add('zru-keyframe-card');pick.dataset.keyframe=frame;
      if(ltxUnused){card.classList.add('is-outside-trim');card.title=`Kept for H3. LTX uses frame ${this.state.startFrame}.`;}
      const alternate=anchor?.legacyVariant&&anchor.enabled===false;
      pick.setAttribute('aria-label',`Edit keyframe at source frame ${frame}${ltxUnused?', kept for H3':alternate?', alternate edit, select to use':''}`);remove.setAttribute('aria-label',`Remove keyframe at source frame ${frame}`);remove.title=`Remove keyframe ${frame}`;
      const outside=Number(anchor?.frame)<this.state.startFrame||Number(anchor?.frame)>=this.state.startFrame+this.state.frameCount;
      card.querySelector('small').textContent=ltxUnused?'Kept for H3':outside?'Outside trim':alternate?'Alternate':anchor?.file?'Edited':'Original';
    });
    const w=this.workspace;if(!w?.source||!this.film)return;
    const start=this.visibleStart(),end=this.visibleEnd(),key=JSON.stringify([w.source.path,w.colourSpace(),start,end]);
    if(key===this.filmKey)return;this.filmKey=key;
    this.film.replaceChildren(...Array.from({length:8},(_,index)=>{
      const image=this.container.ownerDocument.createElement('img');image.alt='';image.loading='lazy';image.draggable=false;
      image.src=w.thumbnail(w.source.path,Math.round(start+(end-start-1)*(index+.5)/8),w.colourSpace(),160);return image;
    }));
  }
}

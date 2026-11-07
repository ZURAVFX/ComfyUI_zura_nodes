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
    this.state.playhead=frame;this.range.value=String(frame);this.updateReadout();this.updatePlayheadLine();
  }
  render(){
    super.render();
    this.title.textContent='Edit timeline';this.cleanLabel.textContent='Edited frames';
    this.addFrame.querySelector('span').textContent='Add keyframe';this.addFrame.title='Add an edited keyframe at the playhead (K)';
    this.help.textContent=this.workspace?.state.engine==='ltx'?'LTX uses the first selected frame · Other keyframes are kept':'Double-click footage or click above it to add a keyframe · K';
    this.cleanLane.setAttribute('aria-label','Edited keyframes. Click an empty position to add one.');
    this.cleanLane.setAttribute('aria-description',`${this.state.anchors.length} edited keyframes. Press K to add one at the playhead.`);
    const visible=this.state.anchors.filter(a=>Number(a.frame)>=this.visibleStart()&&Number(a.frame)<this.visibleEnd());
    this.root.classList.toggle('has-keyframes',visible.length>0);
    [...this.cards.children].forEach((card,index)=>{
      const anchor=visible[index],ltxUnused=this.workspace?.state.engine==='ltx'&&Number(anchor?.frame)!==this.state.startFrame;
      const frame=card.querySelector('strong').textContent,pick=card.querySelector('.zp-editor-frame-card__select'),remove=card.querySelector('.zp-editor-frame-card__remove');
      card.classList.add('zru-keyframe-card');pick.dataset.keyframe=frame;
      if(ltxUnused){card.classList.add('is-outside-trim');card.title=`Kept for H3. LTX uses frame ${this.state.startFrame}.`;}
      const alternate=anchor?.legacyVariant&&anchor.enabled===false;
      pick.setAttribute('aria-label',`Edit keyframe at source frame ${frame}${ltxUnused?', kept for H3':alternate?', alternate edit, select to use':''}`);remove.setAttribute('aria-label',`Remove keyframe at source frame ${frame}`);remove.title=`Remove keyframe ${frame}`;
      card.querySelector('small').textContent=ltxUnused?'Kept for H3':alternate?'Alternate':anchor?.file?'Edited':'Original';
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

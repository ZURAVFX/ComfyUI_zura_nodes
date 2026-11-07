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
    this.render();
  }
  setPlayhead(frame){
    this.state.playhead=frame;this.range.value=String(frame);this.updateReadout();this.updatePlayheadLine();
  }
  render(){
    super.render();
    this.title.textContent='Edit timeline';this.cleanLabel.textContent='Edited frames';
    this.addFrame.querySelector('span').textContent='Add keyframe';this.addFrame.title='Add an edited keyframe at the playhead (K)';
    this.help.textContent=this.workspace?.state.engine==='ltx'?'LTX uses the first selected frame':'Click above the footage to add a keyframe · K';
    this.cleanLane.setAttribute('aria-label','Edited keyframes. Click an empty position to add one.');
    this.cleanLane.setAttribute('aria-description',`${this.state.anchors.length} edited keyframes. Press K to add one at the playhead.`);
    for(const card of this.cards.children){
      const frame=card.querySelector('strong').textContent,pick=card.querySelector('.zp-editor-frame-card__select'),remove=card.querySelector('.zp-editor-frame-card__remove');
      card.classList.add('zru-keyframe-card');pick.dataset.keyframe=frame;
      pick.setAttribute('aria-label',`Edit keyframe at source frame ${frame}`);remove.setAttribute('aria-label',`Remove keyframe at source frame ${frame}`);remove.title=`Remove keyframe ${frame}`;
      card.querySelector('small').textContent=this.state.anchors.find(a=>String(a.frame)===frame)?.file?'Edited':'Original';
    }
    const w=this.workspace;if(!w?.source||!this.film)return;
    const start=this.visibleStart(),end=this.visibleEnd(),key=JSON.stringify([w.source.path,w.colourSpace(),start,end]);
    if(key===this.filmKey)return;this.filmKey=key;
    this.film.replaceChildren(...Array.from({length:8},(_,index)=>{
      const image=this.container.ownerDocument.createElement('img');image.alt='';image.loading='lazy';image.draggable=false;
      image.src=w.thumbnail(w.source.path,Math.round(start+(end-start-1)*(index+.5)/8),w.colourSpace(),160);return image;
    }));
  }
}

import {PaintoutTimeline} from './paintout_studio/paintout_timeline.js';

/** Reuse Paintout's visual cards, trim handles and timeline navigation. */
export class RippleTimeline extends PaintoutTimeline {
  constructor(host,workspace){
    super(host,{
      onSeek:frame=>workspace.seek(frame),
      onCreate:frame=>workspace.addAnchor(frame),
      onSelect:index=>workspace.previewAnchor(workspace.anchors()[index]?.id),
      onRemove:index=>{workspace.selectAnchor(workspace.anchors()[index]?.id);workspace.removeAnchor();},
      onTrim:(start,end,commit)=>{if(commit)workspace.setTrim({start:start/workspace.fps(),duration:(end-start+1)/workspace.fps()});},
    });
    this.workspace=workspace;this.root.classList.add('zru-visual-timeline');
    this.addFrame.onclick=()=>{if(!this.state.busy)workspace.addAtPlayhead();};
    this.root.setAttribute('aria-label',workspace.intent==='relight'?'Relight source timeline':'Ripple source timeline');
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
    this.addFrame.querySelector('span').textContent='Add keyframe';
    this.addFrame.title=`Add an edited frame at source frame ${this.state.playhead} (K)`;
  }
  render(){
    super.render();
    this.title.textContent=this.workspace?.intent==='relight'?'Lighting timeline':'Edit timeline';this.cleanLabel.textContent=this.workspace?.intent==='relight'?'Lighting frames':'Edited frames';
    this.updateAddAction();
    this.help.textContent=this.workspace?.state.engine==='ltx'?'One visual reference for the whole clip · Select an edited frame to use it':'Double-click footage or click above it to add a keyframe · K';
    this.cleanLane.setAttribute('aria-label','Edited keyframes. Click an empty position to add one.');
    this.cleanLane.setAttribute('aria-description',`${this.state.anchors.length} edited keyframes. Press K to add one at the playhead. ${this.workspace?.state.engine==='ltx'?'LTX uses one selected edit as a whole-clip visual reference. ':''}Click an edited thumbnail to preview its image.`);
    const visible=this.state.anchors.filter(a=>Number(a.frame)>=this.visibleStart()&&Number(a.frame)<this.visibleEnd());
    this.root.classList.toggle('has-keyframes',visible.length>0);
    [...this.cards.children].forEach((card,index)=>{
      const anchor=visible[index],ltx=this.workspace?.state.engine==='ltx',reference=this.workspace?.ltxReference();
      const frame=card.querySelector('strong').textContent,pick=card.querySelector('.zp-editor-frame-card__select'),remove=card.querySelector('.zp-editor-frame-card__remove');
      card.classList.add('zru-keyframe-card');pick.dataset.keyframe=frame;
      if(ltx)card.title=anchor?.id===reference?.id?'LTX visual reference for the whole clip':'Select this edit to use it as the LTX visual reference';
      const alternate=anchor?.legacyVariant&&anchor.enabled===false;
      pick.setAttribute('aria-label',`${anchor?.file?'Preview edited':'Edit'} keyframe at source frame ${frame}${ltx&&anchor?.id===reference?.id?', LTX reference':alternate?', alternate edit, select to use':''}`);remove.setAttribute('aria-label',`Remove keyframe at source frame ${frame}`);remove.title=`Remove keyframe ${frame}`;
      const outside=Number(anchor?.frame)<this.state.startFrame||Number(anchor?.frame)>=this.state.startFrame+this.state.frameCount;
      card.querySelector('small').textContent=outside?'Outside trim':ltx&&anchor?.id===reference?.id&&anchor?.file?'LTX reference':alternate?'Alternate':anchor?.file?'Edited':'Original';
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

let previewId=0;

/** A large, dismissible preview of an edited timeline anchor. */
export class RippleAnchorPreview {
  constructor(workspace){
    this.workspace=workspace;this.revision=0;this.active=false;
    const doc=workspace.root.ownerDocument;
    this.dialog=doc.createElement('dialog');this.dialog.className='zru-anchor-preview';
    this.dialog.setAttribute('aria-modal','true');this.dialog.setAttribute('aria-labelledby',`zru-anchor-preview-${++previewId}`);
    this.dialog.innerHTML=`<header class="zru-anchor-preview__header"><strong id="zru-anchor-preview-${previewId}"></strong><button type="button" aria-label="Close image preview" title="Close preview (Escape)">×</button></header><div class="zru-anchor-preview__stage"><p role="status" aria-live="polite">Loading image…</p></div>`;
    this.title=this.dialog.querySelector('strong');this.closeButton=this.dialog.querySelector('button');this.stage=this.dialog.querySelector('.zru-anchor-preview__stage');this.status=this.stage.querySelector('[role=status]');
    this.closeButton.onclick=()=>this.close();
    this.dialog.addEventListener('cancel',event=>{event.preventDefault();event.stopPropagation();this.close();});
    this.dialog.addEventListener('close',()=>{if(!this.dialog.hasAttribute('open'))this.finishClose();});
    this.dialog.addEventListener('click',event=>{
      if(event.target!==this.dialog)return;
      const box=this.dialog.getBoundingClientRect();
      if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)this.close();
    });
    this.dialog.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();this.close();}
      // The native dialog traps focus. This also gives its non-modal fallback a safe loop.
      if(event.key==='Tab'){event.preventDefault();this.closeButton.focus();}
    });
    workspace.root.append(this.dialog);
  }
  open(anchor,trigger){
    if(typeof anchor?.file!=='string'||!anchor.file.trim())return false;
    const revision=++this.revision,doc=this.dialog.ownerDocument;
    this.trigger=trigger||doc.activeElement;this.active=true;
    this.title.textContent=`Edited frame ${anchor.frame}`;this.stage.setAttribute('aria-busy','true');
    this.status.textContent='Loading image…';this.status.hidden=false;
    const image=doc.createElement('img');image.alt=`Edited source frame ${anchor.frame}`;image.hidden=true;
    image.onload=()=>{if(revision!==this.revision||!this.active)return;image.hidden=false;this.status.hidden=true;this.stage.setAttribute('aria-busy','false');};
    image.onerror=()=>{if(revision!==this.revision||!this.active)return;this.status.textContent='Could not load this image preview. Close it and try again.';this.stage.setAttribute('aria-busy','false');};
    this.image?.remove();this.image=image;this.stage.prepend(image);
    image.src=this.workspace.thumbnail(anchor.file,0,anchor.colour_space||'srgb_display',1280);
    if(!this.dialog.hasAttribute('open')){
      try{if(typeof this.dialog.showModal==='function')this.dialog.showModal();else this.dialog.setAttribute('open','');}
      catch{this.dialog.setAttribute('open','');}
    }
    this.closeButton.focus({preventScroll:true});
    return true;
  }
  close(){
    if(!this.active)return;
    if(typeof this.dialog.close==='function'&&this.dialog.hasAttribute('open'))this.dialog.close();
    else this.dialog.removeAttribute('open');
    this.finishClose();
  }
  finishClose(){
    if(!this.active)return;
    this.active=false;++this.revision;
    const trigger=this.trigger?.isConnected?this.trigger:this.workspace.timeline?.cards.querySelector('.is-selected [data-keyframe]');this.trigger=null;
    if(trigger?.isConnected&&typeof trigger.focus==='function')trigger.focus({preventScroll:true});
  }
  dispose(){this.close();this.image?.removeAttribute('src');this.dialog.remove();}
}

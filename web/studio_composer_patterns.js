/** Common composer affordances, preserving each mode's inputs and submit handler. */
const surfaces='.gs-composer,.zc-image-composer,.zf-composer,.zr-composer,.zru-composer,.zvfx-composer,.zalpha-composer,.zo-composer,.zdir-composer';
const keys=new WeakMap();
export function applyComposerPatterns(root){
  for(const composer of root.querySelectorAll(surfaces)){
    composer.classList.add('zc-shared-composer');
    for(const prompt of composer.querySelectorAll('textarea')){
      prompt.classList.add('zc-shared-prompt');prompt.setAttribute('aria-keyshortcuts','Control+Enter Meta+Enter');
      if(!prompt.getAttribute('aria-label')&&!prompt.labels?.length)prompt.setAttribute('aria-label','Describe your edit');
    }
  }
  for(const composer of root.querySelectorAll('.zpx-prompt'))composer.classList.add('zc-shared-composer','zc-shared-inline-composer');
  if(keys.has(root))return;
  const key=event=>{
    if(event.defaultPrevented||event.isComposing||event.key!=='Enter'||!event.ctrlKey&&!event.metaKey||!event.target?.matches?.('textarea'))return;
    const composer=event.target.closest('.zc-shared-composer');if(!composer)return;
    const action=[...composer.querySelectorAll('button.gs-primary,[data-plate-run]')].find(button=>!button.disabled&&!button.closest('[hidden]'));
    if(!action)return;event.preventDefault();event.stopPropagation();action.click();
  };
  root.addEventListener('keydown',key,true);keys.set(root,()=>root.removeEventListener('keydown',key,true));
}
export function disposeComposerPatterns(root){keys.get(root)?.();keys.delete(root);}

/** A removable attachment keeps its primary action and corner action separate. */
export function removableAttachment(button,label,onRemove){
  const doc=button.ownerDocument,slot=doc.createElement('div'),remove=doc.createElement('button');
  slot.className='zc-attachment-slot';
  button.before(slot);slot.append(button,remove);
  remove.type='button';remove.className='zf-remove-frame zc-remove-input';remove.hidden=true;
  remove.setAttribute('aria-label',label);remove.title=label;
  remove.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m7 7 10 10M7 17 17 7"/></svg>';
  remove.onclick=()=>{if(remove.disabled)return;onRemove();if(!button.disabled&&!slot.hidden)button.focus({preventScroll:true});};
  return {slot,remove};
}

export function setAttachmentThumbnail(button,url){
  let image=button.querySelector('img');
  if(!url){image?.remove();return;}
  if(!image){image=button.ownerDocument.createElement('img');image.alt='';button.prepend(image);}
  if(image.getAttribute('src')!==url)image.src=url;
}

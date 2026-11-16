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

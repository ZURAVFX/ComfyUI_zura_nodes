const floatingDetails = [
  'details.zc-tool-popup',
  '.zc-composer-audio>details',
  '.zc-viewer-tools>details',
  'details.zc-image-takes',
  '.zf-heading>details',
].join(',');

const listeners = new WeakMap();

/** Light-dismiss floating controls without swallowing the artist's next click. */
export function installPopoverDismissal(root) {
  listeners.get(root)?.();
  const document = root.ownerDocument;
  const opened = () => [...root.querySelectorAll(floatingDetails)].filter(detail => detail.open);
  const outside = event => {
    const path = event.composedPath?.() || [event.target];
    for (const detail of opened()) {
      if (!path.some(node => node === detail || (node?.nodeType && detail.contains(node)))) detail.open = false;
    }
  };
  const escape = event => {
    if (!root.contains(event.target)) return;
    if (['ArrowDown','ArrowUp','Home','End'].includes(event.key) && event.target.matches?.('button,summary')) {
      const detail=event.target.closest('details');
      const menu=event.target.closest('.zc-workflow-menu')||detail?.querySelector('.zc-workflow-menu');
      if(menu && detail?.open){
        const choices=[...menu.querySelectorAll('button')].filter(button=>!button.disabled&&!button.hidden&&!button.closest('[hidden]'));
        if(choices.length){
          const current=choices.indexOf(event.target);
          const index=event.key==='Home'?0:event.key==='End'?choices.length-1:current<0?(event.key==='ArrowUp'?choices.length-1:0):(current+(event.key==='ArrowUp'?-1:1)+choices.length)%choices.length;
          choices[index].focus({preventScroll:true});event.preventDefault();event.stopPropagation();return;
        }
      }
    }
    if (event.key !== 'Escape') return;
    const detail = opened().at(-1);
    if (!detail) return;
    for (const other of opened()) other.open = false;
    detail.querySelector('summary')?.focus({preventScroll:true});
    event.preventDefault();
    event.stopPropagation();
  };
  const toggle = event => {
    const detail=event.target;
    if(!detail.matches?.(floatingDetails)||!detail.open)return;
    for(const other of opened())if(other!==detail&&!other.contains(detail)&&!detail.contains(other))other.open=false;
  };
  root.addEventListener('toggle',toggle,true);
  document.addEventListener('pointerdown', outside, true);
  document.addEventListener('keydown', escape, true);
  const dispose = () => {
    root.removeEventListener('toggle',toggle,true);
    document.removeEventListener('pointerdown', outside, true);
    document.removeEventListener('keydown', escape, true);
    if (listeners.get(root) === dispose) listeners.delete(root);
  };
  listeners.set(root, dispose);
  return dispose;
}

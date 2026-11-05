const floatingDetails = [
  'details.zc-tool-popup',
  '.zc-composer-audio>details',
  '.zc-viewer-tools>details',
  'details.zc-image-takes',
  '.zf-heading>details',
].join(',');

const listeners = new WeakMap();

// Fixed positioning keeps menus out of scrolling/clipped workspace containers.
// Keep their DOM ownership intact for delegated controls and accessible labels.
export function positionStudioPopover(detail, root) {
  const panel=detail.querySelector(':scope > .zc-tool-panel, :scope > .zc-workflow-menu');
  const trigger=detail.querySelector('summary'), view=root.ownerDocument.defaultView;
  if(!detail.open||!panel||!trigger?.getBoundingClientRect||!view?.innerWidth)return;
  const anchor=trigger.getBoundingClientRect(), bounds=root.getBoundingClientRect();
  const margin=12, gap=8, left=Math.max(margin,bounds.left+margin), right=Math.min(view.innerWidth-margin,bounds.right-margin);
  const top=Math.max(margin,bounds.top+margin), bottom=Math.min(view.innerHeight-margin,bounds.bottom-margin);
  if(anchor.bottom<top||anchor.top>bottom){detail.open=false;return;}
  const width=Math.min(Math.max(panel.getBoundingClientRect().width,240),right-left);
  const below=Math.max(0,bottom-anchor.bottom-gap), above=Math.max(0,anchor.top-top-gap);
  const available=below>=Math.min(panel.scrollHeight||240,240)||below>=above?below:above;
  const height=Math.min(panel.scrollHeight||240,available);
  Object.assign(panel.style,{position:'fixed',inset:'auto',left:`${Math.max(left,Math.min(anchor.left,right-width))}px`,
    top:`${available===below?anchor.bottom+gap:anchor.top-gap-height}px`,width:`${width}px`,minWidth:'0',
    maxWidth:`${right-left}px`,maxHeight:`${available}px`,overflowY:'auto',margin:'0',boxSizing:'border-box',zIndex:'200'});
}

/** Light-dismiss floating controls without swallowing the artist's next click. */
export function installPopoverDismissal(root) {
  listeners.get(root)?.();
  const document = root.ownerDocument;
  const opened = () => [...root.querySelectorAll(floatingDetails)].filter(detail => detail.open);
  const view=document.defaultView;
  const reposition=()=>{for(const detail of opened())positionStudioPopover(detail,root);};
  const observer=view?.ResizeObserver?new view.ResizeObserver(reposition):null;
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
    positionStudioPopover(detail,root);
    const panel=detail.querySelector(':scope > .zc-tool-panel, :scope > .zc-workflow-menu');
    if(panel)observer?.observe(panel);
  };
  const scroll=event=>{if(!opened().some(detail=>detail.contains(event.target)))reposition();};
  root.addEventListener('toggle',toggle,true);
  root.addEventListener('scroll',scroll,true);
  view?.addEventListener('resize',reposition);
  document.addEventListener('pointerdown', outside, true);
  document.addEventListener('keydown', escape, true);
  const dispose = () => {
    root.removeEventListener('toggle',toggle,true);
    root.removeEventListener('scroll',scroll,true);
    view?.removeEventListener('resize',reposition);
    observer?.disconnect();
    document.removeEventListener('pointerdown', outside, true);
    document.removeEventListener('keydown', escape, true);
    if (listeners.get(root) === dispose) listeners.delete(root);
  };
  listeners.set(root, dispose);
  return dispose;
}

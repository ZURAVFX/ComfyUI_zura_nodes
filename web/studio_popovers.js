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
    if (event.key !== 'Escape' || !root.contains(event.target)) return;
    const detail = opened().at(-1);
    if (!detail) return;
    for (const other of opened()) other.open = false;
    detail.querySelector('summary')?.focus({preventScroll:true});
    event.preventDefault();
    event.stopPropagation();
  };
  document.addEventListener('pointerdown', outside, true);
  document.addEventListener('keydown', escape, true);
  const dispose = () => {
    document.removeEventListener('pointerdown', outside, true);
    document.removeEventListener('keydown', escape, true);
    if (listeners.get(root) === dispose) listeners.delete(root);
  };
  listeners.set(root, dispose);
  return dispose;
}

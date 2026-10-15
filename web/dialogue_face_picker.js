// Layout coordinates must stay local to the node. Viewport rectangles already
// include ComfyUI's graph zoom and would apply that scale a second time in CSS.
export function sizePreviewOverlay(video, overlay, sourceWidth, sourceHeight) {
  const ratio = sourceWidth / sourceHeight;
  const width = Math.min(video.clientWidth, video.clientHeight * ratio);
  const height = width / ratio;
  overlay.style.left = `${video.offsetLeft + (video.clientWidth - width) / 2}px`;
  overlay.style.top = `${video.offsetTop + (video.clientHeight - height) / 2}px`;
  overlay.style.width = `${width}px`;
  overlay.style.height = `${height}px`;
}

export function bindPreviewDrag(overlay, {start, move, finish, cancel}) {
  let pointer = null;
  const stop = event => {event.preventDefault(); event.stopPropagation();};
  function release(id) {
    if (overlay.hasPointerCapture(id)) overlay.releasePointerCapture(id);
  }
  function abort(event) {
    if (pointer === null || (event?.pointerId !== undefined && event.pointerId !== pointer)) return;
    if (event) stop(event);
    const id = pointer; pointer = null;
    cancel(); release(id);
  }
  overlay.onpointerdown = event => {
    stop(event);
    if (pointer !== null || event.button !== 0 || event.isPrimary === false) return;
    pointer = event.pointerId;
    overlay.focus({preventScroll: true});
    overlay.setPointerCapture(pointer);
    if (start(event) === false) {const id = pointer; pointer = null; release(id);}
  };
  overlay.onpointermove = event => {
    stop(event);
    if (event.pointerId === pointer) move(event);
  };
  overlay.onpointerup = event => {
    stop(event);
    if (event.pointerId !== pointer) return;
    // The last movement can be coalesced; release coordinates are authoritative.
    move(event);
    const id = pointer; pointer = null;
    finish(event); release(id);
  };
  overlay.onpointercancel = overlay.onlostpointercapture = abort;
  overlay.onkeydown = event => {if (event.key === 'Escape') abort(event);};
  return () => {
    abort();
    for (const name of ['pointerdown','pointermove','pointerup','pointercancel','lostpointercapture','keydown']) overlay[`on${name}`] = null;
  };
}

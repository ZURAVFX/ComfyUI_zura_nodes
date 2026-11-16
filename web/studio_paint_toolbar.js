import {BrushSizeControl} from './studio_brush_size.js';
// Paint/erase/light/history glyphs follow AInVFX Paint a plate's tool rail.
// Upstream-derived paths: Apache-2.0, see vendor/paintaplate/NOTICE.md and LICENSE.
const paths={
  draw:'<path d="m4 20 1-5L16 4a3 3 0 0 1 4 4L9 19l-5 1ZM14 6l4 4"/>',
  protect:'<path d="m16 3 5 5-10 10H6l-3-3L16 3ZM9 9l6 6M6 21h14"/>',
  pan:'<path d="M8 12V7a2 2 0 0 1 4 0v5-8a2 2 0 0 1 4 0v8-5a2 2 0 0 1 4 0v9c0 4-3 6-6 6h-2c-2 0-3-1-4-3l-4-6a2 2 0 0 1 3-2l1 1Z"/>',
  light:'<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  select:'<path d="M8 4H4v4m12-4h4v4M4 16v4h4m8 0h4v-4M9 9h6v6H9Z"/>',
  undo:'<path d="m9 14-5-5 5-5M4 9h10a6 6 0 0 1 0 12h-3"/>',
  redo:'<path d="m15 14 5-5-5-5M20 9H10a6 6 0 0 0 0 12h3"/>',
  clear:'<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5m4-5v5"/>',
  fit:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5h5v-5M8 8h8v8H8Z"/>',
  addFrame:'<path d="M3 5h13v14H3ZM8 9v6m-3-3h6M19 8h3m-3 4h3m-3 4h3"/>',
  removeFrame:'<path d="M3 5h13v14H3ZM5 12h6M19 8h3m-3 4h3m-3 4h3"/>',
  background:'<rect x="3" y="4" width="18" height="16" rx="1"/><circle cx="8" cy="9" r="2"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
  settings:'<path d="M5 4v16M12 4v16M19 4v16M2 8h6m1 8h6m1-9h6"/>',
  keyframe:'<path d="m12 3 9 9-9 9-9-9 9-9Z"/>',
};
export const PAINT_SWATCHES=[['#000000','Black'],['#ffffff','White'],['#c8c8c8','Light grey'],['#d32f2f','Red'],['#f57c00','Orange'],['#fbc02d','Yellow'],['#388e3c','Green'],['#1976d2','Blue'],['#6d4c41','Brown'],['#ffd890','Warm light']];
export function paintToolIcon(name){
  const key=({paint:'draw',erase:'protect',eraser:'protect',brush:'select',area:'select'})[name]||name;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[key]||paths.draw}</svg>`;
}

/** Upgrade the existing image controls; the same nodes move into video edits. */
export function installImagePaintControls(area,rail=null){
  const tools=area.tools,doc=tools.ownerDocument;
  tools.classList.add('zia-shared-paint');
  area.brush.max='1000';area.brush.step='1';
  for(const [key,label]of [['draw','Paint'],['brush','Select area'],['protect','Eraser'],['pan','Pan']]){
    const button=tools.querySelector('[data-area-tool='+key+']');
    button.innerHTML=paintToolIcon(key)+'<span>'+label+'</span>';button.setAttribute('aria-label',label);button.title=label;
  }
  for(const [key,label]of [['undo','Undo'],['clear','Clear'],['fit','Fit']]){
    const button=tools.querySelector('[data-area-action='+key+']');button.innerHTML=paintToolIcon(key)+'<span>'+label+'</span>';button.setAttribute('aria-label',label);
  }
  area.brushControl=new BrushSizeControl(area.brush);
  const palette=doc.createElement('div');palette.className='pap-swatches';palette.setAttribute('role','group');palette.setAttribute('aria-label','Paint colour');
  for(const [colour,name]of PAINT_SWATCHES){const button=doc.createElement('button');button.type='button';button.style.background=colour;button.title=name;button.setAttribute('aria-label',name+' paint');button.onclick=()=>{area.colour.value=colour;area.colour.oninput();for(const b of palette.children)b.setAttribute('aria-pressed',String(b===button));};palette.append(button);}
  area.paintPalette=palette;(rail||area.host).append(palette);
  area.brush.parentElement.classList.add('zia-brush-wide');area.host.querySelector('.zia-toolbar').append(area.brush.parentElement);
}

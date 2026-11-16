// One owner mounts the shared Image Edit canvas on the video workbench.
// Tool order, swatches and shortcuts follow AInVFX Paint a plate (Apache-2.0).
import {paintToolIcon} from './studio_paint_toolbar.js';


export class PlateInlineEditor {
  constructor(surface){this.surface=surface;this.plate=surface.plate;this.owner=surface.o;
    const doc=surface.root.ownerDocument,href=new URL('./studio_plate_inline.css',import.meta.url).href;
    if(![...doc.querySelectorAll('link[rel=stylesheet]')].some(link=>link.href===href)){const style=doc.createElement('link');style.rel='stylesheet';style.href=href;doc.head.append(style);}
  }
  mount(){
    if(this.record)return this.record;
    const s=this.surface,o=this.owner,w=s.w,doc=s.root.ownerDocument,host=doc.createElement('section');
    host.className='zplate-inline-image';host.setAttribute('aria-label','Edited frame canvas');
    const record={host,moved:[],composer:o.root.querySelector('.zc-image-composer'),viewer:w.page.querySelector('.zf-viewer')};
    this.record=record;record.viewerHidden=record.viewer.hidden;host.hidden=true;s.$('view').append(host);
    const move=(node,target)=>{if(!node)return;const marker=doc.createComment('plate-inline-home');node.before(marker);record.moved.push({node,marker});target.append(node);};
    move(o.editInputs.source,host);move(o.$('gallery'),host);move(o.imageComparison?.host,host);move(o.imageArea.host,host);
    move(o.imageArea.tools,s.$('brushes'));move(o.$('progress'),s.root.querySelector('.zpx-stage'));
    move(o.browserConnection?.host,s.$('account'));move(o.root.querySelector('.zc-image-settings'),s.$('image-settings-body'));
    if(o.imageComparison?.button)move(o.imageComparison.button,s.root.querySelector('.zpx-header'));
    record.oldLayers=s.w.editor.layersPanel;record.oldLayersHidden=record.oldLayers.hidden;
    move(o.imageLayers?.host,s.$('layers'));
    const paintMode=this.plate.propagation?this.plate.propagation():this.plate.action!=='remove';
    o.imageArea.inline=true;o.imageArea.setPaintAPlateMode?.(paintMode);
    this.tools();w.page.classList.add('is-editing-image');w.page.querySelector('.zf-composer').hidden=true;
    this.keyHandler=event=>{
      if(event.defaultPrevented||!this.record||!(this.plate.propagation?this.plate.propagation():this.plate.action!=='remove'))return;
      if(event.target?.closest?.('input,textarea,select,[contenteditable=true]')){return;}
      const area=o.imageArea,key=event.key.toLowerCase();
      if((event.ctrlKey||event.metaKey)&&key==='z'){event.preventDefault();event.stopPropagation();event.shiftKey?area.viewer?.redo?.('paint'):area.viewer?.undo('paint');area.scheduleSave();return;}
      if(event.ctrlKey||event.metaKey||event.altKey)return;
      const tool={b:'draw',m:'brush',x:'protect',e:'protect',l:'light'}[key];if(tool){event.preventDefault();event.stopPropagation();area.setTool(tool);}
      else if(key==='['||key===']'){event.preventDefault();this.brushNumber.value=String(Math.max(1,Math.min(1000,area.brushSize+(key==='['?-8:8))));this.brushNumber.oninput();}
    };
    s.root.addEventListener('keydown',this.keyHandler);this.sync();return record;
  }
  tools(){
    const o=this.owner,area=o.imageArea,tools=area.tools,doc=tools.ownerDocument;
    if(!tools.dataset.paintaplate){
      tools.dataset.paintaplate='true';tools.classList.add('pap-tools');
      const names={draw:['Paint','Paint something new (B)'],brush:['Select area','Limit the editable area (M)'],protect:['Eraser','Rub out painted strokes (X)'],pan:['Pan','Pan the frame']};
      for(const [key,[label,title]]of Object.entries(names)){const button=tools.querySelector('[data-area-tool='+key+']');button.innerHTML=paintToolIcon(key)+'<span>'+label+'</span>';button.title=title;button.setAttribute('aria-label',label);}
      const light=doc.createElement('button');light.type='button';light.dataset.areaTool='light';light.innerHTML=paintToolIcon('light')+'<span>Light</span>';light.title='Paint a light source (L)';light.setAttribute('aria-pressed','false');light.onclick=()=>area.setTool('light');tools.querySelector('[data-area-tool=draw]').after(light);
      const redo=doc.createElement('button');redo.type='button';redo.dataset.areaAction='redo';redo.innerHTML=paintToolIcon('redo')+'<span>Redo</span>';redo.title='Redo stroke (Ctrl+Shift+Z)';redo.onclick=()=>{area.viewer?.redo?.('paint');area.scheduleSave();area.refreshTools();};tools.append(redo);
      for(const [key,label]of [['undo','Undo'],['clear','Clear'],['fit','Fit']]){const button=tools.querySelector('[data-area-action='+key+']');if(button)button.innerHTML=paintToolIcon(key)+'<span>'+label+'</span>';}
      this.brushNumber=area.brushControl.number;
    }
    if(area.paintPalette&&area.paintPalette.parentElement!==tools){
      const marker=doc.createComment('plate-palette-home');area.paintPalette.before(marker);
      this.record.moved.push({node:area.paintPalette,marker});area.colour.parentElement.before(area.paintPalette);
    }
    const paintMode=this.plate.propagation?this.plate.propagation():this.plate.action!=='remove';
    this.brushNumber=area.brushControl.number;area.brushControl.sync();
    tools.querySelector('[data-area-tool=light]').hidden=!paintMode;
    tools.querySelector('[data-area-action=redo]').hidden=!paintMode;
  }
  sync(){
    if(!this.record)return;
    const o=this.owner,area=o.imageArea,ready=!!area.viewer?.image&&!area.load&&!area.error,painting=area.editing;
    const revealed=ready&&this.record.host.hidden;
    this.record.host.hidden=!ready;this.record.viewer.hidden=ready||this.record.viewerHidden;
    this.record.host.classList.toggle('is-painting',painting);this.surface.root.dataset.inline='image';
    if(o.imageLayers?.host&&!o.imageLayers.host.hidden)this.record.oldLayers.hidden=true;
    if(revealed)area.viewer?.resize?.();
  }
  restore(){
    const record=this.record;if(!record)return;this.record=null;
    this.owner.imageArea.setPaintAPlateMode?.(false);this.owner.imageArea.inline=false;
    this.surface.root.removeEventListener('keydown',this.keyHandler);
    for(const {node,marker}of record.moved)if(marker.parentNode)marker.replaceWith(node);
    record.viewer.hidden=record.viewerHidden;record.oldLayers.hidden=record.oldLayersHidden;
    record.host.remove();delete this.surface.root.dataset.inline;
    this.surface.w.page.classList.remove('is-editing-image');this.surface.w.page.querySelector('.zf-composer').hidden=false;
  }
}

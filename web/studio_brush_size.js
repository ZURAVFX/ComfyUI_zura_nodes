/** Shared pixel-size control. Painting engines retain their original input node. */
const bounded=(value,min,max)=>Math.max(min,Math.min(max,Math.round(value)));
export class BrushSizeControl{
  constructor(source,{number=null,min=1,max=1000}={}){
    if(source.brushSizeControl)return source.brushSizeControl;
    this.source=source;this.min=min;this.max=max;const doc=source.ownerDocument;
    const id=source.id;this.slider=doc.createElement('input');this.slider.type='range';this.slider.min='0';this.slider.max='1000';this.slider.step='1';this.slider.dataset.brushSizeSlider='';this.slider.setAttribute('aria-label','Brush size');
    this.slider.title='Brush size · drag for broad changes; arrow keys for 1 px, Shift for 10 px';
    if(id){source.removeAttribute('id');this.slider.id=id;}
    source.before(this.slider);source.type='hidden';source.hidden=true;source.parentElement.classList.add('zc-brush-control');source.min=String(min);source.max=String(max);
    this.number=number||doc.createElement('input');this.number.type='number';this.number.min=String(min);this.number.max=String(max);this.number.step='1';this.number.classList.add('pap-brush-number');this.number.setAttribute('aria-label','Brush size in pixels');
    if(!number)source.parentElement.append(this.number);
    this.slider.oninput=()=>this.commit(min+(max-min)*(Number(this.slider.value)/1000)**2);
    this.slider.onkeydown=event=>{const delta={ArrowLeft:-1,ArrowDown:-1,ArrowRight:1,ArrowUp:1,PageDown:-25,PageUp:25}[event.key];if(delta!==undefined||event.key==='Home'||event.key==='End'){event.preventDefault();event.stopPropagation();this.commit(event.key==='Home'?min:event.key==='End'?max:this.value()+delta*(event.shiftKey?10:1));}};
    this.number.oninput=()=>{if(this.number.value&&Number.isFinite(Number(this.number.value)))this.commit(Number(this.number.value));};
    this.number.onchange=()=>{this.commit(Number(this.number.value)||this.value());this.number.value=String(this.value());};
    source.addEventListener('input',()=>this.sync());source.brushSizeControl=this;this.sync();
  }
  value(){return bounded(Number(this.source.value)||this.min,this.min,this.max);}
  commit(value){if(this.source.disabled)return;this.source.value=String(bounded(value,this.min,this.max));const Event=this.source.ownerDocument.defaultView?.Event||globalThis.Event;this.source.dispatchEvent(new Event('input',{bubbles:true}));this.sync();}
  sync(){const value=this.value();this.slider.value=String(Math.round(Math.sqrt((value-this.min)/(this.max-this.min))*1000));this.slider.setAttribute('aria-valuetext',value+' px');this.slider.disabled=this.number.disabled=this.source.disabled;const active=this.number.ownerDocument.activeElement;if(active!==this.number)this.number.value=String(value);}
}

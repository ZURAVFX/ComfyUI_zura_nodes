// Shared size maths and editing behaviour for every Studio composer.
export function resolutionSize(ratio, megapixels, {step=32,min=256,max=1536,maxPixels=Infinity}={}) {
  const pixels=Math.min(Number(megapixels)*1e6,maxPixels);
  if(!(ratio>0&&pixels>0))throw new Error('Choose a valid image size.');
  const snap=n=>Math.max(min,Math.min(max,Math.round(n/step)*step));
  let width=snap(Math.sqrt(pixels*ratio)),height=snap(Math.sqrt(pixels/ratio));
  while(width*height>maxPixels){if(width>=height&&width>min)width-=step;else if(height>min)height-=step;else break;}
  return {width,height};
}

// Text inputs allow clearing, selecting and replacing a complete number. Only
// commit on blur/Enter; never rewrite a partial value during an input event.
export function selectNumberOnFocus(input) {
  let selectOnRelease=false;
  input.addEventListener('focus',()=>{selectOnRelease=true;input.select?.();});
  input.addEventListener('mouseup',e=>{if(selectOnRelease){e.preventDefault();input.select?.();selectOnRelease=false;}});
}
export function editableDimension(input, commit, limits=()=>({step:32,min:256,max:1536})) {
  input.type='text';input.inputMode='numeric';input.setAttribute('inputmode','numeric');input.autocomplete='off';input.spellcheck=false;
  let previous=input.value;
  selectNumberOnFocus(input);input.addEventListener('focus',()=>{previous=input.value;});
  input.addEventListener('input',e=>{e.stopImmediatePropagation();input.removeAttribute('aria-invalid');},true);
  const finish=()=>{
    const raw=input.value.trim(),cap=limits(),n=Number(raw);
    if(!/^\d+$/.test(raw)||!Number.isSafeInteger(n)){input.setAttribute('aria-invalid','true');return false;}
    input.value=String(Math.max(cap.min,Math.min(cap.max,Math.round(n/cap.step)*cap.step)));
    previous=input.value;input.removeAttribute('aria-invalid');commit();return true;
  };
  input.addEventListener('change',e=>{e.stopImmediatePropagation();finish();},true);
  input.addEventListener('blur',()=>{if(input.value!==previous)finish();});
  input.addEventListener('keydown',e=>{e.stopPropagation();if(e.key==='Enter'){e.preventDefault();finish();}if(e.key==='Escape'){e.preventDefault();input.value=previous;input.removeAttribute('aria-invalid');}});
  input.commitDimension=finish;
}

export function megapixelSlider(select,{min=.25,max=1,step=.05}={}) {
  const input=select.ownerDocument.createElement('input');input.type='range';input.id=select.id;input.min=min;input.max=max;input.step=step;input.value=select.value||1;input.setAttribute('aria-label','Megapixels');
  const output=select.ownerDocument.createElement('output');output.className='zc-resolution-readout';output.setAttribute('for',input.id);output.setAttribute('aria-live','polite');
  const handler=select.onchange;
  select.replaceWith(input);input.after(output);
  const update=()=>{output.textContent=`${Number(input.value).toFixed(2)} MP`;input.setAttribute('aria-valuetext',output.textContent);};
  input.oninput=()=>{update();handler?.call(input);};input.onchange=input.oninput;input.updateReadout=update;update();return input;
}

export const RESOLUTION_SHAPES=[['source','Source proportions',null],['landscape','Widescreen · 16:9',16/9],['portrait','Portrait · 9:16',9/16],['square','Square · 1:1',1],['standard','Landscape · 4:3',4/3],['vertical','Portrait · 3:4',3/4],['custom','Custom dimensions',null]];
export function resolutionMarkup(prefix){return `<strong>Resolution</strong><label>Shape<select id="${prefix}-shape">${RESOLUTION_SHAPES.map(([id,label])=>`<option value="${id}">${label}</option>`).join('')}</select></label><label>Megapixels<input id="${prefix}-mp" type="range" min="0.25" max="1" step="0.05" value="1"/><output id="${prefix}-mp-label" class="zc-resolution-readout"></output></label><div class="zf-dimensions" id="${prefix}-custom"><label>Width (px)<input id="${prefix}-width" value="1280"/></label><label>Height (px)<input id="${prefix}-height" value="720"/></label></div><output id="${prefix}-dimensions" class="zc-resolution-dimensions" aria-live="polite"></output><p id="${prefix}-hint"></p>`;}

/** Uses actual pipeline controls; fixed recipes expose their supported sizes. */
export class VideoResolutionControl {
  constructor(studio,panel){
    this.studio=studio;this.panel=panel;panel.innerHTML=resolutionMarkup('zvr');
    this.$=id=>panel.querySelector('#zvr-'+id);
    this.$('shape').onchange=()=>{this.apply();this.commit();};this.$('mp').oninput=()=>this.apply();this.$('mp').onchange=()=>this.commit();
    for(const key of ['width','height'])editableDimension(this.$(key),()=>{this.apply(true);this.commit();},()=>this.context().cap);
  }
  context(){
    const s=this.studio,c=s.config,source=s.source||{},ratio=(source.width||16)/(source.height||9),opening=s.composerStage()!=='video',camera=c.workflow_mode==='camera',relight=c.workflow_mode==='relight';
    const exact=opening||camera||relight;
    const cap=opening?{step:c.opening_model==='qwen21'?32:16,min:256,max:2048,maxPixels:2e6}:camera?{step:32,min:128,max:1280,maxPixels:1280*1280}:{step:16,min:256,max:1920,maxPixels:1920*1088};
    return {s,c,source,ratio,opening,camera,relight,exact,cap,key:opening?'opening':camera?'camera':'relight'};
  }
  apply(custom=false){
    const x=this.context(),shape=this.$('shape').value,mp=Number(this.$('mp').value);
    if(x.s.busy||x.s.project?.phase==='working'||x.opening&&x.camera)return;
    if(!x.exact){
      const choices=[...x.s.$('resolution').options].filter(o=>!o.disabled&&!o.hidden&&o.value!=='1920-enhanced');
      const edge=Math.sqrt(mp*1e6*Math.max(x.ratio,1/x.ratio));
      if(choices.length)x.s.$('resolution').value=choices.reduce((a,b)=>Math.abs(Number(a.value)-edge)<Math.abs(Number(b.value)-edge)?a:b).value;
      x.s.config.resolution=Number(x.s.$('resolution').value);this.sync();return;
    }
    const ratio=shape==='custom'?(x.c[x.key+'_width']/x.c[x.key+'_height']||x.ratio):RESOLUTION_SHAPES.find(p=>p[0]===shape)?.[2]||x.ratio;
    let size=custom?{width:Number(this.$('width').value),height:Number(this.$('height').value)}:resolutionSize(ratio,mp,x.cap);
    if(Object.values(size).some(n=>!Number.isInteger(n)||n<x.cap.min||n>x.cap.max||n%x.cap.step)){this.$('hint').textContent=`Enter both dimensions in multiples of ${x.cap.step}.`;return;}
    if(size.width*size.height>x.cap.maxPixels){this.$('hint').textContent='Reduce the dimensions to fit this model’s pixel limit.';return;}
    if(custom)this.$('shape').value='custom';
    Object.assign(x.c,{[x.key+'_width']:size.width,[x.key+'_height']:size.height,[x.key+'_shape']:this.$('shape').value,[x.key+'_megapixels']:mp});
    this.$('width').value=size.width;this.$('height').value=size.height;this.sync();
  }
  commit(){this.studio.$('resolution').dispatchEvent(new this.panel.ownerDocument.defaultView.Event('change',{bubbles:true}));}
  sync(){
    const x=this.context(),busy=x.s.busy||x.s.project?.phase==='working';
    const sourceWidth=x.source.width||1280,sourceHeight=x.source.height||720;
    const fallback=x.opening?resolutionSize(x.ratio,1,x.cap):x.camera?{width:768,height:448}:{width:Math.max(256,Math.round(sourceWidth*1280/Math.max(sourceWidth,sourceHeight)/16)*16),height:Math.max(256,Math.round(sourceHeight*1280/Math.max(sourceWidth,sourceHeight)/16)*16)};
    const size=x.exact?{width:x.c[x.key+'_width']||fallback.width,height:x.c[x.key+'_height']||fallback.height}:resolutionSize(x.ratio,(Number(x.c.resolution)||1280)**2/Math.max(x.ratio,1/x.ratio)/1e6,{step:x.c.engine==='wan2'?16:64,min:64,max:1920});
    if(x.opening&&x.camera){size.width=1024;size.height=576;}
    if(this.nativeQuality)this.nativeQuality.hidden=x.exact;
    this.$('mp').max=x.opening?2:x.camera?1.6:x.exact?2:2.1;
    this.$('mp').value=x.exact?(x.c[x.key+'_megapixels']??size.width*size.height/1e6):size.width*size.height/1e6;
    this.$('mp-label').textContent=`${(size.width*size.height/1e6).toFixed(2)} MP`;
    this.$('shape').value=x.exact?(x.c[x.key+'_shape']||'source'):'source';this.$('shape').disabled=busy||!x.exact||x.opening&&x.camera;
    this.$('custom').hidden=this.$('shape').value!=='custom';
    for(const key of ['width','height']){const field=this.$(key);if(field!==this.panel.ownerDocument.activeElement)field.value=size[key];field.disabled=busy;}
    this.$('mp').disabled=busy||x.opening&&x.camera||(!x.exact&&(x.c.engine==='wan2'||x.c.h3_head_swap));
    this.$('dimensions').textContent=`${size.width} × ${size.height} px`;
    this.$('hint').textContent=x.opening&&x.camera?'Camera still uses the verified 1024 × 576 recipe. Choose animation resolution at the video stage.':x.opening?`Image generation · ${x.cap.step}-pixel grid. Saved frame stays ${sourceWidth} × ${sourceHeight}; the original shot is preserved.`:x.exact?`${x.camera?'H3':'Wan 2.1'} · ${x.cap.step}-pixel grid. Images fit proportionally and crop to fill; no stretching.`:'Keeps the source framing. The slider selects supported native sizes for this verified workflow.';
    return size;
  }
}

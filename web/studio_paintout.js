import {megapixelSlider,selectNumberOnFocus} from './studio_resolution.js';
import {buildPaintoutGraph,paintoutValidation,paintoutAvailability,PAINTOUT_DEFAULT_PROMPTS,PAINTOUT_OUTPUT_MODES,PAINTOUT_SIZE_PRESETS,paintoutPresetSize,paintoutRangeFix} from './paintout_recipes.js';
import {composerIcons as icons} from './studio_composer.js';
import {attachWorkspaceSamplePreview} from './studio_live_preview.js';
import {durationLabel} from './studio_progress.js';
import {ShotComparison} from './studio_compare.js';
import {tidyArtistGraph} from './artist_graph.js';

const KEY='zura-paintout-workspace-v1';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const name=p=>String(p||'').split(/[\\/]/).pop();
const closeIcon='<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8"/></svg>';
const colours=[['srgb_display','sRGB / standard images'],['auto','Detect video tags'],['rec709_gamma24','Rec.709 gamma 2.4'],['rec709_oetf','Rec.709 camera'],['acescg','ACEScg'],['acescct','ACEScct'],['hlg_rec2020','HLG Rec.2020'],['pq_rec2020','PQ Rec.2020'],['linear_rec709','Linear Rec.709']];
const options=(items,value)=>items.map(([id,label])=>`<option value="${id}" ${id===value?'selected':''}>${label}</option>`).join('');

/** Whole-shot native paintout. Painted anchors always use original source frame IDs. */
export class PaintoutWorkspace{
  constructor(owner){
    this.owner=owner;this.api=owner.api;this.app=owner.app;this.studio=owner.studio;
    let saved={};try{saved=JSON.parse(localStorage.getItem(KEY))||{};}catch{}
    this.state={mode:'targeted',source:'',mask:'',anchors:[],startFrame:0,frameCount:81,sequenceFps:25,sourceColour:'srgb_display',processingSpace:'SDR (sRGB)',width:1152,height:640,resolutionMode:'default',megapixels:.75,outputMode:'SDR video',seed:42,...saved.draft};
    this.state.anchors=Array.isArray(this.state.anchors)?this.state.anchors:[];this.prompts=saved.prompts||{};this.sourceInfo=saved.sourceInfo||null;this.maskInfo=saved.maskInfo||null;this.job=saved.job||null;this.items=Array.isArray(saved.items)?saved.items.slice(0,12):[];this.playhead=this.state.startFrame;this.selected=-1;this.view='source';this.result=saved.result||this.items.find(item=>item.config?.source===this.state.source)||null;
    this.page=document.createElement('section');this.page.className='zf-page zp-page';
    this.page.innerHTML=`
      <div class="zf-heading"><h2>Paintout</h2><div class="zps-view-tabs" role="group" aria-label="Paintout preview">${[['source','Source'],['mask','Mask'],['anchor','Painted frame'],['result','Result']].map(([id,label])=>`<button type="button" data-view="${id}">${label}</button>`).join('')}</div><button type="button" id="zps-compare" hidden>Compare</button><a id="zps-download" hidden download>Download</a><details id="zps-history"><summary>History</summary><div id="zps-takes"></div></details><button type="button" id="zps-new">Start over</button></div>
      <div class="zf-viewer">
        <div id="zps-empty"><h3>Leave the scene. Remove the distractions.</h3><p>Add footage, then choose a targeted repair or an empty clean plate.</p><button type="button" id="zps-begin">Add footage</button></div>
        <div id="zps-image-slot" hidden></div><video id="zps-video" controls playsinline hidden></video><div id="zps-comparison" hidden></div>
        <div id="zps-progress" hidden><strong id="zps-progress-title" role="status" aria-live="polite">Queued</strong><button type="button" id="zps-cancel">Cancel run</button><progress id="zps-bar" max="100" aria-label="Paintout progress"></progress><span id="zps-progress-detail"></span></div>
        <p id="zps-result-status" role="status" hidden></p><p id="zps-message" role="status" hidden></p>
        <div id="zps-scrubber" hidden><label for="zps-frame">Source frame</label><input id="zps-scrub" type="range" min="0" max="80" step="1" value="0" aria-label="Preview source frame"/><input id="zps-frame" type="text" inputmode="numeric" min="0" step="1" value="0" aria-label="Source frame number"/><button id="zps-export" type="button">Save frame to paint</button><a id="zps-export-link" hidden download>Download frame</a><button type="button" id="zps-expand" aria-label="Fullscreen preview">${icons.size}</button></div>
      </div>
      <form class="zf-composer zc-prompt-card" novalidate>
        <div class="zps-composer-heading"><strong id="zps-title">Targeted paintout</strong><div class="zps-mode" role="group" aria-label="Paintout method"><button type="button" data-mode="targeted">Targeted repair</button><button type="button" data-mode="full">Full-scene clean plate</button></div></div>
        <div class="zc-composer-attachments">
          <div class="zf-frame-slot"><button class="zc-attachment" type="button" id="zps-source">${icons.video||icons.image}<span>Add footage</span></button><button class="zf-remove-frame" type="button" id="zps-remove-source" aria-label="Remove source footage" hidden>${closeIcon}</button></div>
          <div class="zf-frame-slot" id="zps-mask-control"><button class="zc-attachment" type="button" id="zps-mask">${icons.image}<span>Removal mask</span></button><button class="zf-remove-frame" type="button" id="zps-remove-mask" aria-label="Remove removal mask" hidden>${closeIcon}</button></div>
          <button class="zc-attachment" type="button" id="zps-add-anchor">${icons.image}<span>Add painted frames</span></button>
          <details class="zc-tool-popup"><summary class="zc-tool">Image sequence ${icons.chevron}</summary><div class="zc-tool-panel"><p>Use an EXR, TIFF or PNG folder instead of a video.</p><button type="button" id="zps-sequence">Choose sequence folder</button></div></details>
        </div>
        <section id="zps-anchors-section" aria-label="Painted anchor frames"><div id="zps-anchors" class="zps-anchor-strip"></div><p id="zps-anchor-help">Add full-size painted frames, then enter their original source frame numbers. Numbers start at 0.</p></section>
        <label for="zps-prompt" class="zc-sr-only">Describe the paintout</label><textarea id="zps-prompt" maxlength="12000" placeholder="Describe what to remove and what should remain…"></textarea>
        <div class="zc-prompt-bottom"><div class="zc-prompt-tools">
          <div class="zc-tool-group"><span class="zc-tool zf-model">${icons.model} LTX 2.5</span></div>
          <details class="zc-tool-popup" id="zps-resolution"><summary class="zc-tool" aria-label="Processing resolution">${icons.size}<span id="zps-resolution-label">1152 × 640</span>${icons.chevron}</summary><div class="zc-tool-panel"><strong>Processing resolution</strong><label>Size<select id="zps-size-mode">${options([['default','Default · 1152 × 640'],['source','Use source'],...PAINTOUT_SIZE_PRESETS.map(([id,label])=>[id,label]),['custom','Custom dimensions']],this.state.resolutionMode)}</select></label><label id="zps-megapixels-control">Detail<select id="zps-megapixels">${options([['0.25','0.25 MP · fastest'],['0.5','0.5 MP'],['0.75','0.75 MP'],['1','1 MP'],['2','2 MP · more memory']],String(this.state.megapixels))}</select></label><div class="zf-dimensions" id="zps-custom-size"><label>Width<input id="zps-width" type="text" inputmode="numeric" min="64" max="4096" step="64" value="1152"/></label><label>Height<input id="zps-height" type="text" inputmode="numeric" min="64" max="4096" step="64" value="640"/></label></div><p id="zps-size-help"></p><p id="zps-framing-help"></p></div></details>
          <details class="zc-tool-popup" id="zps-range"><summary class="zc-tool">${icons.clock}<span id="zps-range-label">81 frames</span>${icons.chevron}</summary><div class="zc-tool-panel"><strong>Source range</strong><div class="zf-dimensions"><label>First source frame<input id="zps-start" type="text" inputmode="numeric" autocomplete="off" spellcheck="false" aria-describedby="zps-range-help" min="0" step="1" value="0"/></label><label>Frame count<input id="zps-count" type="text" inputmode="numeric" autocomplete="off" spellcheck="false" aria-describedby="zps-range-help" min="1" max="993" step="1" value="81"/></label></div><button type="button" id="zps-full-range">Use entire source</button><p id="zps-range-help">One continuous shot per run. Longer ranges need more memory.</p><label id="zps-fps-control" hidden>Sequence frame rate<input id="zps-fps" type="number" min="1" max="120" step="0.001" value="25"/></label></div></details>
          <details class="zc-tool-popup"><summary class="zc-tool" aria-label="Paintout settings">${icons.settings}</summary><div class="zc-tool-panel"><strong>Processing & delivery</strong><p>INT8 · 8 steps · original-resolution delivery</p><label>Source colour space<select id="zps-colour">${options(colours,this.state.sourceColour)}</select></label><label>Process as<select id="zps-processing"><option>SDR (sRGB)</option><option>HDR (ACEScct)</option></select></label><label>Save as<select id="zps-output">${PAINTOUT_OUTPUT_MODES.map(mode=>`<option>${mode}</option>`).join('')}</select></label><label>Seed<input id="zps-seed" type="number" min="0" max="9007199254740991" step="1" value="42"/></label><div id="zps-setup"></div><button type="button" id="zps-refresh">Refresh models</button></div></details>
          <details class="zc-tool-popup" id="zps-anchor-settings" hidden><summary class="zc-tool">Painted frame ${icons.chevron}</summary><div class="zc-tool-panel"><strong id="zps-selected-name"></strong><div class="zps-anchor-shortcuts"><button type="button" data-anchor-frame="first">First selected</button><button type="button" data-anchor-frame="current">Use playhead</button><button type="button" data-anchor-frame="last">Last selected</button></div><label>Guide strength<input id="zps-anchor-strength" type="number" min="0.01" max="1" step="0.01" value="0.75"/></label><label>Image colour space<select id="zps-anchor-colour">${options(colours.filter(([id])=>id!=='auto'),'srgb_display')}</select></label><label class="zf-check"><input type="checkbox" id="zps-anchor-enabled" checked/>Use this painted frame</label><button type="button" id="zps-replace-anchor">Replace image</button></div></details>
        </div><div class="zc-prompt-submit"><button type="submit" class="gs-primary" id="zps-generate" disabled>Generate clean plate</button></div></div>
        <p id="zps-note" aria-live="polite"></p>
      </form>`;
    owner.root.append(this.page);
    this.$('prompt').value=this.prompts[this.state.mode]||PAINTOUT_DEFAULT_PROMPTS[this.state.mode];
    for(const [id,key] of Object.entries({start:'startFrame',count:'frameCount',fps:'sequenceFps',colour:'sourceColour',processing:'processingSpace',width:'width',height:'height',output:'outputMode',seed:'seed'}))this.$(id).value=this.state[key];
    this.$('source').onclick=this.$('begin').onclick=()=>this.pickSource('footage');this.$('sequence').onclick=()=>this.pickSource('sequence');this.$('mask').onclick=()=>this.pickMask();this.$('add-anchor').onclick=()=>this.pickAnchors();
    this.$('remove-source').onclick=()=>this.resetSource();this.$('remove-mask').onclick=()=>{this.state.mask='';this.maskInfo=null;this.changed();if(this.view==='mask')this.preview('source');};
    this.$('new').onclick=()=>this.reset();
    this.page.querySelector('form').onsubmit=e=>{e.preventDefault();this.generate();};
    this.$('size-mode').onchange=()=>{this.state.resolutionMode=this.$('size-mode').value;this.applySize();this.changed();};
    this.$('megapixels').onchange=()=>{this.state.megapixels=Number(this.$('megapixels').value);this.applySize();this.changed();};
    megapixelSlider(this.$('megapixels'),{max:2});
    for(const button of this.page.querySelectorAll('[data-mode]'))button.onclick=()=>this.setMode(button.dataset.mode);
    for(const button of this.page.querySelectorAll('[data-view]'))button.onclick=()=>this.preview(button.dataset.view);
    this.$('prompt').oninput=()=>{this.prompts[this.state.mode]=this.$('prompt').value;this.save();};
    for(const [id,key] of Object.entries({fps:'sequenceFps',colour:'sourceColour',processing:'processingSpace',output:'outputMode',seed:'seed'}))this.$(id).onchange=()=>{
      const input=this.$(id);if(input.type==='number'&&(!input.value||!input.checkValidity())){this.message('Enter a valid '+input.closest('label').firstChild.textContent.toLowerCase()+'.');return;}
      this.state[key]=input.type==='number'?Number(input.value):input.value;this.changed();if(['colour','processing'].includes(id))this.preview(this.view);
    };
    for(const [id,key,min,max] of [['start','startFrame',0,100000],['count','frameCount',1,993]])this.bindNumber(this.$(id),()=>this.state[key],value=>{this.state[key]=value;this.changed();},{min,max});
    for(const key of ['width','height'])this.bindNumber(this.$(key),()=>this.state[key],value=>{const snapped=Math.max(64,Math.min(4096,Math.round(value/64)*64));this.state[key]=snapped;this.$(key).value=snapped;this.changed();if(snapped!==value)this.message(`${key==='width'?'Width':'Height'} adjusted from ${value} to ${snapped} pixels for LTX.`);},{min:1,max:100000});
    this.$('full-range').onclick=()=>{if(!this.sourceInfo||this.busy())return;this.state.startFrame=0;this.state.frameCount=this.sourceInfo.frames;this.$('start').value=0;this.$('count').value=this.state.frameCount;this.changed();};
    this.$('scrub').oninput=()=>this.seek(Number(this.$('scrub').value));this.bindNumber(this.$('frame'),()=>this.playhead,value=>this.seek(value),{min:0,max:()=>Math.max(0,(this.sourceInfo?.frames||1)-1)});
    this.$('video').ontimeupdate=()=>{if(this.view==='source'&&this.sourceInfo?.kind==='video'){this.playhead=Math.min(this.sourceInfo.frames-1,Math.floor(this.$('video').currentTime*this.fps()));this.updatePlayhead();}};
    this.$('video').onerror=()=>{if(this.view==='source'||this.view==='mask'){this.videoFallback??=new Set();this.videoFallback.add(this.view==='source'?this.state.source:this.state.mask);this.preview(this.view);this.message('This codec cannot play in the browser. Use the frame slider to inspect the footage.');}else this.message('The result video could not load. Download it to play in your video editor.');};
    this.$('export').onclick=()=>this.exportFrame();this.$('expand').onclick=()=>this.page.querySelector('.zf-viewer').requestFullscreen?.();
    this.$('refresh').onclick=()=>this.loadModels();this.$('cancel').onclick=()=>this.cancel();this.$('compare').onclick=()=>this.compare();
    this.$('anchors').onclick=e=>{const remove=e.target.closest('[data-remove-anchor]'),select=e.target.closest('[data-select-anchor]');if(remove){if(this.busy())return;this.state.anchors.splice(Number(remove.dataset.removeAnchor),1);this.selected=-1;this.renderAnchors();this.changed();this.preview('source');}else if(select)this.selectAnchor(Number(select.dataset.selectAnchor));};
    for(const button of this.page.querySelectorAll('[data-anchor-frame]'))button.onclick=()=>{const a=this.state.anchors[this.selected];if(!a||this.busy())return;a.frame=button.dataset.anchorFrame==='first'?this.state.startFrame:button.dataset.anchorFrame==='last'?this.state.startFrame+this.state.frameCount-1:this.playhead;this.renderAnchors();this.changed();};
    for(const [id,key] of [['anchor-strength','strength'],['anchor-colour','colour_space'],['anchor-enabled','enabled']])this.$(id).onchange=()=>{const a=this.state.anchors[this.selected],input=this.$(id);if(!a||this.busy())return;if(input.type==='number'&&(!input.value||!input.checkValidity()))return;a[key]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;this.changed();this.renderAnchors();if(id==='anchor-colour')this.preview('anchor');};
    this.$('replace-anchor').onclick=()=>this.pickAnchors(this.selected);
    this.$('takes').onclick=e=>{const b=e.target.closest('[data-take]');if(b){this.result=this.items[Number(b.dataset.take)];this.preview('result');this.$('history').open=false;}};
    this.api.addEventListener?.('progress',e=>this.updateProgress(e.detail));
    this.api.addEventListener?.('executing',e=>{const d=e.detail;if(!this.job||d?.prompt_id!==this.job.id||!d.node)return;this.job.currentNode=d.node;this.sampleStarted=null;this.progressSnapshot=null;this.$('bar').removeAttribute('value');this.$('progress-title').textContent=this.job.stages?.[d.node]||'Processing paintout';this.$('progress-detail').textContent=this.elapsed();this.save();});
    for(const type of ['execution_success','execution_error','execution_interrupted'])this.api.addEventListener?.(type,e=>{if(e.detail?.prompt_id===this.job?.id)this.poll();});
    this.renderAnchors();this.render();
  }
  bindNumber(input,getValue,setValue,{min,max}){
    input.dataset.freeNumber='true';
    const commit=()=>{
      if(input.disabled||this.busy())return true;
      const text=input.value.trim(),value=Number(text),limit=typeof max==='function'?max():max;
      if(!/^\d+$/.test(text)||!Number.isSafeInteger(value)||value<min||value>limit){
        input.dataset.inputError=`Enter a whole number from ${min} to ${limit} for ${(input.getAttribute('aria-label')||input.closest('label')?.firstChild?.textContent||'this field').trim().toLowerCase()}.`;
        input.setAttribute('aria-invalid','true');this.render();this.message(input.dataset.inputError);return false;
      }
      delete input.dataset.inputError;input.removeAttribute('aria-invalid');input.value=String(value);
      if(value!==getValue())setValue(value);else this.render();return true;
    };
    selectNumberOnFocus(input);
    input.onchange=input.onblur=commit;
    input.oninput=()=>{delete input.dataset.inputError;input.removeAttribute('aria-invalid');this.message('');};
    input.onkeydown=e=>{e.stopPropagation();if(e.key==='Enter'){e.preventDefault();commit();}else if(e.key==='Escape'){e.preventDefault();input.value=String(getValue());delete input.dataset.inputError;input.removeAttribute('aria-invalid');this.render();}};
  }
  $(id){return this.page.querySelector('#zps-'+id);}
  fetch(path,body){return this.owner.fetch(path,body);}
  busy(){return !!(this.job||this.submitting||this.picking||this.exporting);}
  fps(){return this.sourceInfo?.kind==='video'?this.sourceInfo.fps:this.state.sequenceFps;}
  config(){const c={...this.state,sourceWidth:this.sourceInfo?.width,sourceHeight:this.sourceInfo?.height,anchors:this.state.anchors.map(a=>({...a})),prompt:this.$('prompt').value,keepAudio:true,savePrefix:'paintout/studio',exrPrecision:'float32'};if(c.resolutionMode==='source'&&this.sourceInfo){c.width=Math.ceil(c.sourceWidth/64)*64;c.height=Math.ceil(c.sourceHeight/64)*64;}return c;}
  applySize(){const mode=this.state.resolutionMode;if(mode==='default'){this.state.width=1152;this.state.height=640;}else if(PAINTOUT_SIZE_PRESETS.some(p=>p[0]===mode))Object.assign(this.state,paintoutPresetSize(mode,this.state.megapixels));this.$('width').value=this.state.width;this.$('height').value=this.state.height;}
  save(){try{localStorage.setItem(KEY,JSON.stringify({draft:this.state,prompts:this.prompts,sourceInfo:this.sourceInfo,maskInfo:this.maskInfo,job:this.job,items:this.items,result:this.result}));}catch{this.message('Browser storage is full. Your output files remain on disk.');}}
  changed(){this.message('');this.save();this.render();}
  message(text){this.$('message').textContent=text||'';this.$('message').hidden=!text;}
  url(path){return this.api.apiURL(path);}
  thumbnail(file,frame=0,space=this.state.sourceColour,size=240){return this.url('/zura/paintout/frame-preview?'+new URLSearchParams({file,frame,space,size}));}
  async pick(kind){const data=await this.fetch('/zura/paintout/pick',{kind});return data.paths||[];}
  async info(path){return this.fetch('/zura/paintout/info?'+new URLSearchParams({file:path}));}
  async pickSource(kind){
    if(this.busy())return;this.picking=true;this.render();
    try{const [file]=await this.pick(kind);if(!file)return;const info=await this.info(file);this.state.source=file;this.sourceInfo=info;this.state.mask='';this.maskInfo=null;this.state.anchors=[];this.selected=-1;this.state.startFrame=0;this.state.frameCount=Math.min(81,info.frames);this.playhead=0;this.result=null;this.$('export-link').hidden=true;this.$('export-link').removeAttribute('href');this.$('start').value=0;this.$('count').value=this.state.frameCount;this.renderAnchors();this.changed();this.preview('source');}
    catch(e){this.message(this.requestError(e));}finally{this.picking=false;this.save();this.render();}
  }
  async pickMask(){
    if(this.busy())return;this.picking=true;this.render();
    try{const [file]=await this.pick('mask');if(!file)return;const info=await this.info(file);if(this.sourceInfo&&(info.width!==this.sourceInfo.width||info.height!==this.sourceInfo.height))throw new Error('Use a full-resolution mask matching the source footage.');this.state.mask=file;this.maskInfo=info;this.changed();this.preview('mask');}
    catch(e){this.message(this.requestError(e));}finally{this.picking=false;this.render();}
  }
  async pickAnchors(replace=-1){
    if(this.busy())return;this.picking=true;this.render();
    try{const files=await this.pick('anchor');if(!files.length)return;const rows=[];
      for(const file of replace>=0?files.slice(0,1):files){const info=await this.info(file);if(this.sourceInfo&&(info.width!==this.sourceInfo.width||info.height!==this.sourceInfo.height))throw new Error(`${name(file)} must match the full source resolution (${this.sourceInfo.width} × ${this.sourceInfo.height}).`);const n=name(file).replace(/\.[^.]+$/,'').match(/(\d+)$/),frame=n?Number(n[1]):this.playhead;rows.push({file,frame,strength:0.75,enabled:true,colour_space:/\.(exr)$/i.test(file)?'acescg':'srgb_display'});}
      if(replace>=0)this.state.anchors[replace]={...this.state.anchors[replace],file:rows[0].file};else this.state.anchors.push(...rows);this.selected=replace>=0?replace:this.state.anchors.length-1;this.renderAnchors();this.changed();this.selectAnchor(this.selected);
    }catch(e){this.message(this.requestError(e));}finally{this.picking=false;this.renderAnchors();this.render();}
  }
  requestError(e){return /404|405|not found|could not complete this request/i.test(e.message)?'Restart ComfyUI after your current work finishes to enable the new Paintout browser.':e.message;}
  resetSource(){if(this.busy())return;this.state.source='';this.state.mask='';this.state.anchors=[];this.sourceInfo=this.maskInfo=null;this.selected=-1;this.result=null;this.$('export-link').hidden=true;this.$('export-link').removeAttribute('href');this.renderAnchors();this.changed();this.preview('source');}
  reset(){if(this.busy())return;this.resetSource();this.items=[];this.state.startFrame=0;this.state.frameCount=81;this.playhead=0;this.$('start').value=0;this.$('count').value=81;this.save();this.render();}
  setMode(mode){if(this.busy()||!['targeted','full'].includes(mode))return;this.prompts[this.state.mode]=this.$('prompt').value;this.state.mode=mode;this.$('prompt').value=this.prompts[mode]||PAINTOUT_DEFAULT_PROMPTS[mode];this.changed();if(mode==='full'&&['mask','anchor'].includes(this.view))this.preview('source');}
  renderAnchors(){
    this.$('anchors').innerHTML=this.state.anchors.map((a,i)=>`<div class="zps-anchor ${a.enabled===false?'is-disabled':''} ${i===this.selected?'is-selected':''}"><button type="button" data-select-anchor="${i}" aria-label="Preview painted frame ${a.frame}" title="${esc(name(a.file))}"><img src="${esc(this.thumbnail(a.file,0,a.colour_space))}" alt="Painted frame ${a.frame}"/></button><label>Frame<input data-frame-index="${i}" type="text" inputmode="numeric" min="${this.state.startFrame}" max="${this.state.startFrame+this.state.frameCount-1}" step="1" value="${a.frame===-1?this.state.startFrame+this.state.frameCount-1:a.frame}" aria-label="Source frame for painted image ${i+1}"/></label><button class="zps-remove" type="button" data-remove-anchor="${i}" aria-label="Remove painted image ${i+1}">${closeIcon}</button></div>`).join('');
    for(const input of this.$('anchors').querySelectorAll('input'))this.bindNumber(input,()=>{const a=this.state.anchors[Number(input.dataset.frameIndex)];return a.frame===-1?this.state.startFrame+this.state.frameCount-1:a.frame;},value=>{this.state.anchors[Number(input.dataset.frameIndex)].frame=value;this.changed();},{min:0,max:100000});
    this.$('anchors').querySelectorAll('button,input').forEach(el=>el.disabled=this.busy());
  }
  selectAnchor(index){this.selected=index;const a=this.state.anchors[index];if(!a)return;this.$('selected-name').textContent=name(a.file);this.$('anchor-strength').value=a.strength;this.$('anchor-colour').value=a.colour_space;this.$('anchor-enabled').checked=a.enabled!==false;this.$('anchors').querySelectorAll('.zps-anchor').forEach((e,i)=>e.classList.toggle('is-selected',i===index));this.preview('anchor');this.render();}
  seek(frame){if(!this.sourceInfo)return;this.playhead=Math.max(0,Math.min(this.sourceInfo.frames-1,Math.round(frame)));this.updatePlayhead();if(this.view!=='source')this.preview('source');else if(this.sourceInfo.media_url&&!this.videoFallback?.has(this.state.source))this.$('video').currentTime=this.playhead/this.fps();else this.preview('source');}
  updatePlayhead(){if(document.activeElement!==this.$('frame'))this.$('frame').value=this.playhead;this.$('scrub').value=this.playhead;}
  preview(kind=this.view){
    if(kind==='result'&&!this.result||kind==='anchor'&&!this.state.anchors[this.selected]||kind==='mask'&&!this.state.mask)kind='source';this.view=kind;this.comparison?.hide();this.$('comparison').hidden=true;this.$('video').pause();this.$('video').hidden=true;this.$('image-slot').hidden=true;this.$('empty').hidden=!!this.state.source||kind==='result';
    let src='',video=false;
    if(kind==='result'){this.nativeSamplePreview?.clear();src=this.outputURL(this.result.file);video=true;this.$('history').open=false;for(const popup of this.page.querySelectorAll('form details[open]'))popup.open=false;}
    else if(kind==='anchor'){const a=this.state.anchors[this.selected];src=this.thumbnail(a.file,0,a.colour_space,1280);}
    else if(kind==='mask'&&this.maskInfo){video=!!this.maskInfo.media_url&&!this.videoFallback?.has(this.state.mask);src=video?this.url(this.maskInfo.media_url):this.thumbnail(this.state.mask,Math.min(this.playhead,this.maskInfo.frames-1),'srgb_display',1280);}
    else if(this.sourceInfo&&this.state.source){video=!!this.sourceInfo.media_url&&!this.videoFallback?.has(this.state.source);src=video?this.url(this.sourceInfo.media_url):this.thumbnail(this.state.source,this.playhead,this.state.sourceColour,1280);}
    if(src&&video){const el=this.$('video');if(el.getAttribute('src')!==src)el.src=src;el.hidden=false;el.currentTime=kind==='result'?0:this.playhead/this.fps();}
    else if(src){let image=this.$('image-slot').querySelector('img');if(!image){image=document.createElement('img');image.alt='Paintout preview';this.$('image-slot').append(image);}image.src=src;image.onerror=()=>this.message('Preview unavailable. Check the file and its colour space.');this.$('image-slot').hidden=false;}
    this.render();
  }
  outputURL(file){return this.url('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:'output'}));}
  async exportFrame(){
    if(this.busy()||!this.state.source)return;this.exporting=true;this.render();this.message('Saving the full-resolution source frame…');
    try{const data=await this.fetch('/zura/paintout/export-frame',{file:this.state.source,frame:this.playhead,colour_space:this.state.sourceColour});const link=this.$('export-link');link.href=this.url(data.url);link.hidden=false;link.textContent=`Download frame ${this.playhead}`;this.message(`Frame ${this.playhead} saved. Paint over the unwanted object, then add the finished image as a painted frame.`);}
    catch(e){this.message(this.requestError(e));}finally{this.exporting=false;this.render();}
  }
  async loadModels(){if(this.loading)return;this.loading=true;this.render();try{this.modelInfo=await this.fetch('/object_info');this.modelError='';}catch(e){this.modelError=e.message;}finally{this.loading=false;this.render();}}
  async open(){attachWorkspaceSamplePreview(this);if(!this.modelInfo)this.loadModels();if(this.state.source){try{this.sourceInfo=await this.info(this.state.source);if(this.state.mask)this.maskInfo=await this.info(this.state.mask);}catch(e){this.message(this.requestError(e));}}this.preview(this.result?'result':'source');if(this.job)this.startPolling();}
  render(){
    const busy=this.busy(),targeted=this.state.mode==='targeted',availability=this.modelInfo?paintoutAvailability(this.modelInfo,this.state.mode):null,c=this.config();let error=[...this.page.querySelectorAll('[data-input-error]')].find(input=>!input.disabled)?.dataset.inputError||paintoutValidation(c);
    if(!error&&this.sourceInfo&&c.startFrame+c.frameCount>this.sourceInfo.frames)error='The selected frame range exceeds your footage.';
    if(!error&&targeted&&this.maskInfo&&this.maskInfo.frames>1&&this.maskInfo.frames<c.startFrame+c.frameCount)error='The mask does not cover the selected source range.';
    this.validationError=error;this.availability=availability;
    this.$('title').textContent=targeted?'Targeted paintout':'Full-scene clean plate';
    for(const b of this.page.querySelectorAll('[data-mode]')){b.setAttribute('aria-pressed',String(b.dataset.mode===this.state.mode));b.disabled=busy;}
    this.$('mask-control').hidden=!targeted;this.$('add-anchor').hidden=!targeted;this.$('add-anchor').disabled=busy||!this.state.source;this.$('mask').disabled=busy||!this.state.source;this.$('anchors-section').hidden=!targeted;
    this.$('anchor-help').textContent=this.state.anchors.length?`Original source frames · numbers start at 0 · selected range ${c.startFrame}–${c.startFrame+c.frameCount-1}. Click a thumbnail to preview or adjust its guide.`:'Add full-size painted frames, then enter their original source frame numbers. Numbers start at 0.';
    this.$('anchors').hidden=!this.state.anchors.length;
    for(const [id,path,label] of [['source',c.source,'Add footage'],['mask',c.mask,'Removal mask']]){const b=this.$(id);b.querySelector('span').textContent=path?name(path):label;b.title=path||label;this.$('remove-'+id).hidden=!path;this.$('remove-'+id).disabled=busy;b.classList.toggle('has-media',!!path);let image=b.querySelector('img');if(path){if(!image){image=document.createElement('img');image.alt='';b.prepend(image);}const src=this.thumbnail(path,0,id==='mask'?'srgb_display':c.sourceColour);if(image.getAttribute('src')!==src)image.src=src;}else image?.remove();}
    this.$('anchor-settings').hidden=!targeted||this.selected<0;
    this.$('fps-control').hidden=!this.sourceInfo||this.sourceInfo.kind==='video';
    this.$('range-label').textContent=`${c.frameCount} frames · ${(c.frameCount/this.fps()).toFixed(2)}s`;
    this.$('range-help').textContent=this.sourceInfo?`Source frames 0–${this.sourceInfo.frames-1}. Up to 993 frames per run. Press Enter or click away to apply. ${c.frameCount>81?'Long ranges can exceed VRAM; this workflow samples the whole range at once.':'Longer ranges need more memory.'}`:'Add footage to choose its frame range.';
    const sizeMode=this.state.resolutionMode,preset=PAINTOUT_SIZE_PRESETS.some(p=>p[0]===sizeMode);
    this.$('resolution-label').textContent=(sizeMode==='source'?'Source · ':'')+`${c.width} × ${c.height}`;
    this.$('size-mode').value=sizeMode;this.$('megapixels').value=this.state.megapixels;this.$('megapixels').updateReadout?.();
    this.$('custom-size').hidden=sizeMode!=='custom';this.$('megapixels-control').hidden=!preset;
    const original=this.sourceInfo?`${this.sourceInfo.width} × ${this.sourceInfo.height}`:'the source resolution';
    this.$('size-help').textContent=`AI processing: ${c.width} × ${c.height} · ${(c.width*c.height/1e6).toFixed(2)} MP. Saved output: ${original}.`;
    this.$('framing-help').textContent=sizeMode==='source'?'Keeps every source pixel without resizing. Pads to the 64-pixel model grid; padding is removed on export. Larger frames need more memory.':sizeMode==='default'&&targeted?'Default centre framing. The whole removal mask must fit inside this processing frame.':'Fits the whole source without stretching or cropping. Custom sizes snap to the nearest 64 pixels.';
    this.$('scrubber').hidden=!this.sourceInfo||this.view==='result';this.$('scrub').max=this.$('frame').max=Math.max(0,(this.sourceInfo?.frames||1)-1);this.updatePlayhead();
    for(const b of this.page.querySelectorAll('[data-view]')){b.setAttribute('aria-pressed',String(b.dataset.view===this.view));b.disabled=b.dataset.view==='mask'?(!targeted||!c.mask):b.dataset.view==='anchor'?(!targeted||this.selected<0):b.dataset.view==='result'?!this.result:!c.source;}
    for(const id of ['source','sequence','begin','new','prompt','start','count','fps','colour','processing','size-mode','megapixels','output','seed','full-range','refresh','anchor-strength','anchor-colour','anchor-enabled','replace-anchor'])this.$(id).disabled=busy;
    for(const id of ['width','height'])this.$(id).disabled=busy||sizeMode!=='custom';
    this.$('fps').disabled=busy||this.sourceInfo?.kind==='video';this.$('megapixels').disabled=busy||!preset;
    this.$('anchors').querySelectorAll('button,input').forEach(el=>{el.disabled=busy||!targeted;if(el.tagName==='INPUT'){el.min=c.startFrame;el.max=c.startFrame+c.frameCount-1;}});
    for(const id of ['anchor-strength','anchor-colour','anchor-enabled','replace-anchor'])this.$(id).disabled=busy||!targeted||this.selected<0;
    this.$('full-range').disabled=busy||!this.sourceInfo||this.sourceInfo.frames>993;this.$('full-range').title=this.sourceInfo?.frames>993?'This native workflow supports up to 993 frames per shot. Choose a shorter range.':'';
    this.$('result-status').hidden=this.view!=='result'||!this.result||!!this.job||this.submitting;if(this.result)this.$('result-status').textContent=`Ready · ${this.result.config.frameCount} frames · Your finished clean plate is ready to play`;
    this.$('export').disabled=busy;this.$('progress').hidden=!this.job&&!this.submitting;this.$('cancel').disabled=!this.job;
    this.$('generate').disabled=busy;this.$('generate').setAttribute('aria-describedby','zps-note');this.$('generate').textContent=this.job?'Generating…':this.submitting?'Submitting…':error||!availability?.ready?'Review setup':'Generate clean plate';
    this.$('setup').textContent=this.loading?'Checking installed models…':this.modelError||(!availability?'Open Paintout to check installed models.':availability.ready?'Required models and nodes are installed.':'Missing: '+availability.missing.join(', '));
    this.$('note').textContent=error||(!availability?.ready?this.$('setup').textContent:targeted?'White removes. Black preserves. Painted frames restore the background.':'Removes people, vehicles and moving obstructions. No mask or painted frames needed.');
    this.$('note').classList.toggle('is-error',!!error||!availability?.ready);
    const rangeFix=paintoutRangeFix(c,this.sourceInfo?.frames,this.maskInfo?.frames);
    if(error&&rangeFix){const button=document.createElement('button');button.type='button';button.textContent=rangeFix.label;button.disabled=busy;button.onclick=()=>{Object.assign(this.state,rangeFix.patch);this.$('start').value=this.state.startFrame;this.$('count').value=this.state.frameCount;for(const id of ['start','count']){delete this.$(id).dataset.inputError;this.$(id).removeAttribute('aria-invalid');}this.changed();};this.$('note').append(' ',button);}
    this.$('compare').hidden=!this.result||this.result.config.source!==c.source||!this.sourceInfo?.media_url||this.view!=='result';
    this.$('download').hidden=!this.result||this.view!=='result';if(this.result){this.$('download').href=this.outputURL(this.result.master||this.result.file);this.$('download').textContent=this.result.config.outputMode==='EXR sequence'?'Download preview':'Download video';}
    this.$('takes').innerHTML=this.items.map((item,i)=>`<button type="button" data-take="${i}">${item.config.mode==='full'?'Clean plate':'Targeted repair'} · ${esc(name(item.config.source))}</button>`).join('');
  }
  updateProgress(d){
    if(!this.job||d?.prompt_id!==this.job.id||!Number.isFinite(d.value)||!Number.isFinite(d.max)||d.max<=0)return;
    const node=d.node||this.job.currentNode||'sample',now=Date.now();
    if(!this.progressSnapshot||this.progressSnapshot.node!==node)this.progressSnapshot={node,first:d.value,at:now};
    Object.assign(this.progressSnapshot,{value:d.value,max:d.max});this.job.currentNode=node;
    const label=this.job.stages?.[node]||'Processing paintout',unit=node==='sample'?'Step':['source','save'].includes(node)?'Frame':'Progress';
    this.$('progress-title').textContent=`${label} · ${unit} ${d.value} of ${d.max}`;
    this.$('bar').value=100*d.value/d.max;
    if(node==='save'&&d.value>=d.max){this.$('progress-title').textContent='Finalising video files and audio';this.$('bar').removeAttribute('value');}
    this.$('progress-detail').textContent=this.elapsed();
  }
  elapsed(){
    if(!this.job)return '';
    const now=Date.now(),p=this.progressSnapshot,elapsed=durationLabel((now-this.job.started)/1000);
    const rate=p&&p.value>p.first&&now>p.at?(p.value-p.first)/((now-p.at)/1000):null;
    const remaining=rate&&p.value<p.max?`About ${durationLabel((p.max-p.value)/rate)} left in this stage · `:'';
    return remaining+elapsed+' elapsed';
  }
  async generate(){
    if(this.busy())return;
    for(const input of this.page.querySelectorAll('[data-free-number]'))if(!input.onchange()){input.closest('details')?.setAttribute('open','');input.focus();return;}
    this.render();
    const invalid=[...this.page.querySelectorAll('form input[type="number"]')].find(input=>!input.disabled&&(!input.value||!input.checkValidity()));
    if(invalid){this.message('Enter a valid '+(invalid.closest('label')?.firstChild?.textContent||'frame number').trim().toLowerCase()+'.');invalid.closest('details')?.setAttribute('open','');invalid.focus();return;}
    if(this.validationError||!this.availability?.ready){const reason=this.validationError||this.$('setup').textContent;this.message(reason);const id=/frame|range|mask.*cover/i.test(reason)?'range':/width|height|resolution|pixel/i.test(reason)?'resolution':null;if(id)this.$(id).open=true;else if(!this.availability?.ready)this.$('setup').closest('details').open=true;return;}
    this.submitting=true;this.message('');this.$('progress-title').textContent='Submitting clean plate';this.$('progress-detail').textContent='Sending your run to ComfyUI…';this.$('bar').removeAttribute('value');this.render();
    try{
      const config=this.config(),graph=buildPaintoutGraph(config),response=await this.fetch('/prompt',{prompt:graph,client_id:this.api.clientId,extra_data:{zura_paintout:true,preview_method:'auto'}});
      if(!response.prompt_id)throw new Error('ComfyUI did not confirm this run. Check the queue before retrying.');
      this.job={id:response.prompt_id,started:Date.now(),config,previewMethod:'auto',stages:Object.fromEntries(Object.entries(graph).map(([id,n])=>[id,n._meta?.title||n.class_type]))};
      this.$('progress-title').textContent='Queued';this.$('progress-detail').textContent='Waiting for ComfyUI to start';this.sampleStarted=null;this.progressSnapshot=null;this.save();this.startPolling();
    }catch(e){this.message('Could not start paintout: '+e.message);}finally{this.submitting=false;this.render();}
  }
  startPolling(){if(this.timer)return;this.timer=setInterval(()=>this.poll(),1500);this.poll();}
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  async poll(){if(!this.job||this.polling)return;const job=this.job;this.polling=true;try{const history=await this.fetch('/history/'+encodeURIComponent(job.id)),entry=history[job.id];if(this.job!==job)return;if(this.connectionLost){this.message('');this.connectionLost=false;}if(entry?.status?.completed||entry?.status?.status_str==='error'){
      const files=entry.outputs?.save?.images||[],file=files.find(f=>/motion_preview/.test(f.filename))||files.find(f=>/SDR/.test(f.filename))||files[0];this.job=null;this.nativeSamplePreview?.clear();this.stopPolling();if(file){this.result={file,master:files.find(f=>! /motion_preview/.test(f.filename))||file,config:job.config,saved:entry.outputs?.save?.text?.join('\n')||''};this.items.unshift(this.result);this.items=this.items.slice(0,12);this.preview('result');this.message(job.config.outputMode.includes('EXR')?this.result.saved:'');}else {const failure=entry.status.messages?.find(m=>m[0]==='execution_error')?.[1],interrupted=entry.status.messages?.some(m=>m[0]==='execution_interrupted');this.message(interrupted?'Paintout cancelled. Your previous results are safe.':failure?'Paintout stopped · '+(job.stages?.[failure.node_id]||failure.node_type||'Processing')+': '+failure.exception_message:'No motion preview was saved. Check ComfyUI for the export details.');}this.save();this.render();
    }else{const queue=await this.fetch('/queue');if(this.job!==job)return;const running=queue.queue_running?.some(r=>r[1]===job.id),pending=queue.queue_pending?.some(r=>r[1]===job.id);if(!running&&!pending){this.job=null;this.nativeSamplePreview?.clear();this.stopPolling();this.save();this.message('This run is no longer in ComfyUI’s queue. It has not been resubmitted.');this.render();}else {if(running&&this.$('progress-title').textContent==='Queued')this.$('progress-title').textContent=this.job.stages?.[this.job.currentNode]||'Starting paintout';const position=queue.queue_pending?.findIndex(r=>r[1]===job.id);this.$('progress-detail').textContent=running?this.elapsed():`Queue position ${(position??0)+1} · Waiting for ComfyUI · ${this.elapsed()}`;}}}
    catch{this.connectionLost=true;this.message('Connection interrupted. Reconnecting to your saved run…');}finally{this.polling=false;}}
  async cancel(){if(!this.job)return;try{const id=this.job.id;await this.fetch('/queue',{delete:[id]});await this.fetch('/interrupt',{prompt_id:id});this.message('Cancellation requested.');await this.poll();}catch(e){this.message(e.message);}}
  compare(){if(!this.result||this.result.config.source!==this.state.source||!this.sourceInfo?.media_url)return;this.$('video').pause();this.comparison??=new ShotComparison(this.$('comparison'));this.$('comparison').hidden=false;this.comparison.onClose=()=>{this.$('comparison').hidden=true;};const c=this.result.config;this.comparison.show(this.url(this.sourceInfo.media_url),this.outputURL(this.result.file),c.startFrame/(this.sourceInfo.kind==='video'?this.sourceInfo.fps:c.sequenceFps),{resultLabel:'Clean plate'});}
  async graph(){try{const graph=buildPaintoutGraph(this.job?.config||this.config()),original=(this.app.rootGraph||this.app.graph)?.serialize?.();if(!original||typeof this.app.loadApiJson!=='function')throw new Error('Update ComfyUI to open this editable graph.');try{await this.app.loadApiJson(graph,`Zura Paintout · ${Date.now()}.json`);await import('./vendor/elk.bundled.js');await tidyArtistGraph(this.app,graph,'paintout',window.ELK);}catch(e){await this.app.loadGraphData(original);throw e;}this.studio.close();}catch(e){this.message(e.message);}}
  close(){this.save();this.stopPolling();this.nativeSamplePreview?.dispose();this.nativeSamplePreview=null;this.comparison?.hide();this.$('video').pause();}
}

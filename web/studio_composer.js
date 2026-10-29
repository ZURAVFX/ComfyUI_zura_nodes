import {VideoResolutionControl} from './studio_resolution.js';
import {clipLength} from './studio_length.js';
const svg=body=>`<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
export const composerIcons={
  video:svg('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3z"/>'),
  image:svg('<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1"/><path d="m3 16 6-6 6 6 3-3 3 3"/>'),
  model:svg('<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>'),
  size:svg('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h4M7 9v4m10 2h-4m4 0v-4"/>'),
  clock:svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  audio:svg('<path d="M4 10v4m4-7v10m4-13v16m4-13v10m4-7v4"/>'),
  settings:svg('<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="var(--zc-composer)"/><circle cx="15" cy="17" r="3" fill="var(--zc-composer)"/>'),
  chevron:svg('<path d="m8 10 4 4 4-4"/>'),
  trim:svg('<path d="M6 3v12a3 3 0 0 0 3 3h12M3 6h12a3 3 0 0 1 3 3v12"/>'),
  view:svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  compare:svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16M6 9h3m-3 6h3m6-6h3m-3 6h3"/>'),
  history:svg('<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6M12 7v5l3 2"/>'),
  takes:svg('<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M7 3h10m-8 9 6 3-6 3z"/>'),
  download:svg('<path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4"/>'),
};
export const VIDEO_WORKFLOWS=[['swap','Character replacement'],['viewport','Viewport to final'],['camera','Change camera angle'],['relight','Relight'],['paintout','Paintout / clean plate'],['outpaint','Frame extension · preview'],['frames','First & last frame'],['references','Reference to video']];

/** A compact surface over the existing controls, never a second configuration. */
export class VideoComposer {
  constructor(studio,workspace){
    this.studio=studio;this.workspace=workspace;this.root=studio.container;
    const composer=this.root.querySelector('.gs-composer');composer.classList.add('zc-prompt-card');
    const task=document.createElement('details');task.className='zc-task-control zc-tool-popup';
    task.innerHTML=`<summary aria-label="Video workflow" aria-haspopup="menu"><span data-workflow-label></span>${composerIcons.chevron}</summary><select id="zc-video-task" aria-label="Video workflow" hidden aria-hidden="true" tabindex="-1">${VIDEO_WORKFLOWS.map(([id,label])=>`<option value="${id}">${label}</option>`).join('')}</select><div class="zc-tool-panel zc-workflow-menu" role="menu" aria-label="Video workflow">${VIDEO_WORKFLOWS.map(([id,label])=>`<button type="button" role="menuitemradio" aria-checked="false" data-workflow="${id}">${label}<span aria-hidden="true"></span></button>`).join('')}</div>`;
    this.task=task;
    this.root.querySelector('.gs-workflow-choice').hidden=true;
    task.querySelector('select').onchange=e=>this.selectWorkflow(e.target.value);
    task.addEventListener('click',e=>{if(task.querySelector('select').disabled){e.preventDefault();return;}const option=e.target.closest('[data-workflow]');if(!option||option.disabled)return;task.open=false;this.selectWorkflow(option.dataset.workflow);task.querySelector('summary').focus({preventScroll:true});});
    task.addEventListener('keydown',e=>{if(!['ArrowDown','ArrowUp','Home','End','Escape'].includes(e.key))return;if(e.key==='Escape'){task.open=false;task.querySelector('summary').focus({preventScroll:true});e.preventDefault();return;}e.preventDefault();task.open=true;const items=[...task.querySelectorAll('[data-workflow]')].filter(b=>!b.disabled),index=items.indexOf(this.root.ownerDocument.activeElement);const next=e.key==='Home'?0:e.key==='End'?items.length-1:index<0?(e.key==='ArrowUp'?items.length-1:0):(index+(e.key==='ArrowUp'?-1:1)+items.length)%items.length;items[next]?.focus({preventScroll:true});});
    const attachments=document.createElement('div');attachments.className='zc-composer-attachments';
    attachments.innerHTML=`<button type="button" id="zc-attach-source" class="zc-attachment">${composerIcons.video}<span>Source video</span></button><button type="button" id="zc-attach-refs" class="zc-attachment">${composerIcons.image}<span>References</span></button><button type="button" id="zc-attach-frame" class="zc-attachment">${composerIcons.image}<span>Finished frame</span></button>`;
    for(const [id,type,label] of [['source','source','source video'],['refs','character','references'],['frame','ready','finished frame']]){
      const input=attachments.querySelector('#zc-attach-'+id),slot=document.createElement('div');slot.className='zc-attachment-slot';input.before(slot);slot.append(input);
      const remove=document.createElement('button');remove.type='button';remove.className='zf-remove-frame zc-remove-input';remove.id='zc-remove-'+id;remove.setAttribute('aria-label','Remove '+label);remove.innerHTML=svg('<path d="m7 7 10 10M7 17 17 7"/>');remove.hidden=true;
      remove.onclick=()=>studio.removeInput(type);slot.append(remove);
    }
    composer.insertBefore(attachments,studio.$('prompt-composer'));
    const bottom=document.createElement('div');bottom.className='zc-prompt-bottom';
    const tools=document.createElement('div');tools.className='zc-prompt-tools';bottom.append(tools);this.tools=tools;
    const recipeTools=document.createElement('div');recipeTools.className='zc-tool-group';recipeTools.setAttribute('role','group');recipeTools.setAttribute('aria-label','Model and workflow');tools.append(recipeTools);
    const model=document.createElement('label');model.className='zc-model-control zc-tool';
    model.innerHTML=`${composerIcons.model}<span class="zc-sr-only">Video model</span><select id="zc-video-model" aria-label="Video model"></select>${composerIcons.chevron}`;
    recipeTools.append(model);
    const imageModel=document.createElement('details');imageModel.className='zc-tool-popup zc-frame-model';
    imageModel.innerHTML=`<summary aria-label="Starting image model" aria-haspopup="menu">${composerIcons.model}<span data-opening-model-label>FLUX Klein 9B</span>${composerIcons.chevron}</summary><select id="zc-opening-model" hidden aria-hidden="true" tabindex="-1" aria-label="Starting image model"><option value="flux3">Flux 3 Klein</option><option value="klein9b">FLUX Klein 9B</option><option value="qwen2511">Qwen Image Edit 2511</option><option value="qwen21">Qwen Image 2.1</option></select><div class="zc-tool-panel zc-workflow-menu zc-opening-menu" role="menu" aria-label="Starting image generator"><button type="button" role="menuitemradio" aria-checked="false" data-opening-model="flux3">Flux 3 Klein<span aria-hidden="true"></span></button><button type="button" role="menuitemradio" aria-checked="true" data-opening-model="klein9b">FLUX Klein 9B<span aria-hidden="true"></span></button><button type="button" role="menuitemradio" aria-checked="false" data-opening-model="qwen2511">Qwen Image Edit 2511<span aria-hidden="true"></span></button><button type="button" role="menuitemradio" aria-checked="false" data-opening-model="qwen21">Qwen Image 2.1<span aria-hidden="true"></span></button><p data-opening-status hidden></p><button type="button" role="menuitemradio" aria-checked="false" data-use-finished-image>Use finished image<span aria-hidden="true"></span></button></div>`;
    imageModel.querySelector('select').onchange=e=>studio.changeOpeningModel(e.target.value);
    imageModel.addEventListener('click',e=>{if(studio.busy||studio.project?.phase==='working'){e.preventDefault();return;}const option=e.target.closest('[data-opening-model]');if(option&&!option.disabled){imageModel.open=false;studio.changeOpeningModel(option.dataset.openingModel);}const ready=e.target.closest('[data-use-finished-image]');if(ready&&!ready.disabled){imageModel.open=false;const input=this.root.querySelector('input[name="gs-look"][value="ready"]');if(input&&!input.disabled){input.checked=true;input.dispatchEvent(new this.root.ownerDocument.defaultView.Event('change',{bubbles:true}));studio.$('ready').click();}}});
    imageModel.addEventListener('keydown',e=>{if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key)||studio.busy||studio.project?.phase==='working')return;e.preventDefault();imageModel.open=true;const items=[...imageModel.querySelectorAll('[role="menuitemradio"]')].filter(b=>!b.disabled),index=items.indexOf(this.root.ownerDocument.activeElement),next=e.key==='Home'?0:e.key==='End'?items.length-1:index<0?0:(index+(e.key==='ArrowUp'?-1:1)+items.length)%items.length;items[next]?.focus({preventScroll:true});});
    recipeTools.append(imageModel,task);this.imageModel=imageModel;this.model=model;
    const outputTools=document.createElement('div');outputTools.className='zc-tool-group';outputTools.setAttribute('role','group');outputTools.setAttribute('aria-label','Video size and length');tools.append(outputTools);
    const nativeQuality=studio.$('quality-setting');
    this.resolution=this.popup('resolution','Resolution',composerIcons.size,nativeQuality);outputTools.append(this.resolution);
    // Keep the original native quality control as the configuration bridge.
    nativeQuality.hidden=true;this.resolution.before(nativeQuality);
    this.sizeControl=new VideoResolutionControl(studio,this.resolution.querySelector('.zc-tool-panel'));this.sizeControl.nativeQuality=nativeQuality;this.resolution.querySelector('.zc-tool-panel').append(nativeQuality);
    const lengthControls=this.root.querySelector('.gs-clip-length');studio.$('trim-precision').querySelector('.gs-two').append(studio.$('duration-setting'));
    this.length=this.popup('length','Clip length',composerIcons.clock,lengthControls);this.length.classList.add('zc-trim-popup');
    const timing=this.root.querySelector('.zc-video-timing');if(timing){timing.querySelector('summary').onclick=e=>{e.preventDefault();this.length.open=!this.length.open;};}
    const trimPanel=this.length.querySelector('.zc-tool-panel');trimPanel.append(studio.$('trimmer'),studio.$('trim-precision'));outputTools.append(this.length);
    // Original audio fields keep their listeners, uploads and model restrictions.
    this.audio=document.createElement('div');this.audio.className='zc-tool-popup zc-composer-audio';
    this.audio.append(studio.$('audio-settings'));tools.append(this.audio);
    const settings=document.createElement('button');settings.type='button';settings.className='zc-tool';settings.innerHTML=composerIcons.settings;settings.setAttribute('aria-label','More video settings');settings.title='More video settings';
    settings.onclick=()=>{workspace.selectPanel('settings');this.openControls();};tools.append(settings);this.settings=settings;
    const action=document.createElement('div');action.className='zc-prompt-submit';action.append(studio.$('primary'));bottom.append(action);composer.append(bottom,studio.$('action-note'));
    this.root.querySelector('#zc-video-model').onchange=e=>{
      const input=this.root.querySelector(`input[name="gs-engine"][value="${e.target.value}"]`);
      if(input&&!input.disabled){for(const radio of this.root.querySelectorAll('input[name="gs-engine"]'))radio.checked=radio===input;input.dispatchEvent(new this.root.ownerDocument.defaultView.Event('change',{bubbles:true}));}
    };
    for(const [id,type,input] of [['source','source','source'],['refs','character','character'],['frame','ready','ready']]){
      const button=this.root.querySelector('#zc-attach-'+id);
      button.onclick=()=>studio.$(input).click();
      button.ondragover=e=>{e.preventDefault();e.stopPropagation();button.classList.add('is-dragging');};
      button.ondragleave=()=>button.classList.remove('is-dragging');
      button.ondrop=e=>{e.preventDefault();e.stopPropagation();button.classList.remove('is-dragging');const files=Array.from(e.dataTransfer?.files||[]);studio.upload(type,type==='character'?files:files[0]);};
    }
    // One popover at a time. Escape returns focus to its trigger.
    composer.addEventListener('toggle',e=>{const detail=e.target;if(detail.tagName==='DETAILS'&&detail.open)for(const other of composer.querySelectorAll('details.zc-tool-popup,.zc-composer-audio>details'))if(other!==detail&&!other.contains(detail)&&!detail.contains(other))other.open=false;},true);
    composer.addEventListener('keydown',e=>{if(e.key!=='Escape')return;const open=Array.from(composer.querySelectorAll('details')).find(d=>d.open);if(open){open.open=false;open.querySelector('summary').focus({preventScroll:true});e.stopPropagation();}});
    this.composer=composer;this.sync();
  }
  selectWorkflow(value){
    if(['frames','references','paintout','outpaint'].includes(value)){this.workspace.show(value);return;}
    if(!VIDEO_WORKFLOWS.some(([id])=>id===value))return;
    const input=this.root.querySelector(`input[name="gs-workflow"][value="${value}"]`);
    if(input&&!input.disabled){
      for(const radio of this.root.querySelectorAll('input[name="gs-workflow"]'))radio.checked=radio===input;
      input.dispatchEvent(new this.root.ownerDocument.defaultView.Event('change',{bubbles:true}));
      this.workspace.show('video');
    }
  }
  mountWorkflow(mode){
    // Reuse the same control and handler in both composers. Its place in the
    // tool row stays immediately after the model, including endpoint video.
    const select=this.task.querySelector('select'),focused=this.root.ownerDocument.activeElement===select;
    const model=mode==='frames'?this.workspace.frames.page.querySelector('.zf-model'):mode==='references'?this.workspace.referencesVideo.page.querySelector('.zf-model'):mode==='paintout'?this.workspace.paintout.page.querySelector('.zf-model'):mode==='outpaint'?this.workspace.outpaint.page.querySelector('.zo-model'):this.imageModel;
    if(model.nextElementSibling!==this.task)model.after(this.task);
    this.syncWorkflow();
    if(focused)select.focus({preventScroll:true});
  }
  syncWorkflow(){
    const independent=['frames','references','paintout','outpaint'].includes(this.workspace.mode),select=this.task.querySelector('select');
    select.value=independent?this.workspace.mode:this.studio.config.workflow_mode==='motion'?'swap':this.studio.config.workflow_mode;
    select.disabled=!independent&&(this.studio.busy||this.studio.project?.phase==='working');
    for(const option of select.querySelectorAll('option')){
      const input=this.root.querySelector(`input[name="gs-workflow"][value="${option.value}"]`);
      option.disabled=!!input?.disabled;
      const item=this.task.querySelector(`[data-workflow="${option.value}"]`);item.disabled=select.disabled||option.disabled;item.setAttribute('aria-checked',String(option.value===select.value));
    }
    const label=VIDEO_WORKFLOWS.find(([id])=>id===select.value)?.[1]||'Video workflow';this.task.querySelector('[data-workflow-label]').textContent=label;
    const trigger=this.task.querySelector('summary');trigger.setAttribute('aria-label','Video workflow: '+label);trigger.setAttribute('aria-disabled',String(select.disabled));
    if(select.disabled)this.task.open=false;
  }
  syncOpeningModel(working){
    const chosen=this.studio.config.opening_model||'klein9b',status=this.studio.modelStatus?.opening_models,ready=this.studio.lookMode==='ready';
    this.imageModel.querySelector('select').value=chosen;
    const names={flux3:'Flux 3 Klein',klein9b:'FLUX Klein 9B',qwen2511:'Qwen Image Edit 2511',qwen21:'Qwen Image 2.1'};
    this.imageModel.querySelector('[data-opening-model-label]').textContent=ready?'Finished image':names[chosen]||names.klein9b;
    this.imageModel.querySelector('summary').setAttribute('aria-disabled',String(working));
    for(const option of this.imageModel.querySelectorAll('[data-opening-model]')){
      const model=status?.[option.dataset.openingModel],needsRestart=!model&&option.dataset.openingModel!=='klein9b';option.disabled=working||needsRestart||model?.ready===false;
      option.setAttribute('aria-checked',String(!ready&&chosen===option.dataset.openingModel));
      option.title=needsRestart?'Restart ComfyUI to enable the new image models.':model?.ready===false?'Model setup needed. Check Models & setup.':option.dataset.openingModel==='flux3'?'16-step INT8 edit Â· original frame + up to 9 references':option.dataset.openingModel==='qwen21'?'Experimental base model - 40 steps, INT8, up to 9 references':option.dataset.openingModel==='qwen2511'?'4-step INT8 edit Â· original frame + up to 2 references':'4-step FP8 edit Â· original frame + up to 3 references';
    }
    const note=this.imageModel.querySelector('[data-opening-status]'),missing=status&&Object.values(status).some(m=>!m.ready);note.hidden=!missing&&chosen!=='qwen21';note.textContent=chosen==='qwen21'?'Qwen Image 2.1 is experimental and has not been render-tested here.':missing?'Unavailable generators need their model files or nodes installed.':'';
    const finished=this.imageModel.querySelector('[data-use-finished-image]'),input=this.root.querySelector('input[name="gs-look"][value="ready"]');finished.disabled=working||!!input?.disabled;finished.setAttribute('aria-checked',String(ready));
    if(working)this.imageModel.open=false;
  }
  popup(id,label,icon,content){
    const detail=document.createElement('details');detail.className='zc-tool-popup';detail.innerHTML=`<summary aria-label="${label}">${icon}<span id="zc-tool-${id}"></span>${composerIcons.chevron}</summary><div class="zc-tool-panel"></div>`;
    detail.querySelector('div').append(content);return detail;
  }
  openControls(){this.root.querySelector('.gs-workspace').classList.add('zc-controls-open');this.root.querySelector('#zc-video-controls').setAttribute('aria-expanded','true');}
  attachment(id,asset,label){
    const button=this.root.querySelector('#zc-attach-'+id);let thumb=button.querySelector('img');
    if(asset?.url){if(!thumb){thumb=document.createElement('img');thumb.alt='';button.prepend(thumb);}thumb.src=asset.poster_url||asset.url;}
    else thumb?.remove();
    const remove=this.root.querySelector('#zc-remove-'+id);remove.hidden=!asset;remove.disabled=this.studio.busy||this.studio.project?.phase==='working';button.parentElement.hidden=false;button.classList.toggle('has-media',!!asset);button.querySelector('span').textContent=label;button.title=asset?.name||label;
  }
  sync(){
    const s=this.studio,working=s.busy||s.project?.phase==='working',stage=s.composerStage();
    this.composer.dataset.stage=stage;
    const select=this.root.querySelector('#zc-video-model'),radios=Array.from(this.root.querySelectorAll('input[name="gs-engine"]')).filter(r=>!r.closest('label').hidden);
    const key=radios.map(r=>r.value+':'+r.disabled).join('|');
    if(select.dataset.choices!==key){select.replaceChildren();for(const radio of radios){const option=document.createElement('option');option.value=radio.value;option.textContent={local:'LTX 2.5',h3:'MiniMax H3',wan:'Wan 2.2',wan2:'Wan Animate 2',wan21:'Wan 2.1',seedance:'Seedance'}[radio.value];option.disabled=radio.disabled;select.append(option);}select.dataset.choices=key;}
    select.value=s.config.engine;select.disabled=working;this.model.hidden=stage!=='video';this.imageModel.hidden=stage==='video';
    this.syncOpeningModel(working);
    this.syncWorkflow();
    this.resolution.hidden=false;this.settings.hidden=stage!=='video'||['relight','camera'].includes(s.config.workflow_mode);this.audio.hidden=s.$('audio-settings').hidden||stage!=='video';
    this.root.querySelector('#zc-tool-resolution').textContent=s.$('resolution').selectedOptions?.[0]?.textContent?.split(' Â· ')[0]||'Resolution';
    const length=clipLength(s.config,s.source?.duration),lengthLabel=this.root.querySelector('#zc-tool-length');
    const local24=['wan','wan2','h3','local'].includes(s.config.engine);
    lengthLabel.textContent=local24&&Number.isFinite(length.outputSeconds)?`${length.outputSeconds.toFixed(2)}s · ${length.frames}f`:(s.config.length_mode==='original'?'Full clip':`${s.config.duration}s`);
    lengthLabel.title=local24&&Number.isFinite(length.frames)?`${length.frames} frames at 24 fps`:'';
    const audioSummary=s.$('audio-summary');audioSummary.textContent=s.config.audio_id?'Reference audio':'Original audio';audioSummary.title='Audio and facial performance';
    const source=s.source?{...s.source,url:s.source.thumbnail_url}:null;
    this.attachment('source',source,s.source?'Source video':'Add video');
    this.attachment('refs',s.references?.[0],s.references?.length?`${s.references.length} reference${s.references.length===1?'':'s'}`:'References');
    this.root.querySelector('#zc-remove-refs').setAttribute('aria-label',s.references?.length>1?'Remove all references':'Remove reference');this.root.querySelector('#zc-remove-refs').title=s.references?.length>1?'Remove all references':'Remove reference';
    this.attachment('frame',s.readyAsset,s.readyAsset?'Finished frame':'Finished frame');
    this.root.querySelector('#zc-attach-refs').parentElement.hidden=s.lookMode==='ready';this.root.querySelector('#zc-attach-frame').parentElement.hidden=s.lookMode!=='ready';
    for(const button of this.composer.querySelectorAll('.zc-attachment'))button.disabled=working;
    this.length.querySelector('summary').setAttribute('aria-label','Clip length: '+this.root.querySelector('#zc-tool-length').textContent);
  }
}

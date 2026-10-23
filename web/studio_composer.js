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
};

/** A compact surface over the existing controls, never a second configuration. */
export class VideoComposer {
  constructor(studio,workspace){
    this.studio=studio;this.workspace=workspace;this.root=studio.container;
    const composer=this.root.querySelector('.gs-composer');composer.classList.add('zc-prompt-card');
    const task=document.createElement('label');task.className='zc-task-control';
    task.innerHTML=`<span class="zc-sr-only">Video workflow</span><select id="zc-video-task" aria-label="Video workflow"><option value="swap">Character replacement</option><option value="viewport">Viewport to final</option><option value="camera">Change camera angle</option><option value="relight">Relight</option><option value="frames">First & last frame</option></select>`;
    studio.$('prompt-stage').append(task);
    this.root.querySelector('.gs-workflow-choice').hidden=true;
    task.querySelector('select').onchange=e=>{
      if(e.target.value==='frames'){workspace.show('frames');return;}
      const input=this.root.querySelector(`input[name="gs-workflow"][value="${e.target.value}"]`);
      if(input&&!input.disabled){for(const radio of this.root.querySelectorAll('input[name="gs-workflow"]'))radio.checked=radio===input;input.dispatchEvent(new this.root.ownerDocument.defaultView.Event('change',{bubbles:true}));}
    };
    const attachments=document.createElement('div');attachments.className='zc-composer-attachments';
    attachments.innerHTML=`<button type="button" id="zc-attach-source" class="zc-attachment">${composerIcons.video}<span>Source video</span></button><button type="button" id="zc-attach-refs" class="zc-attachment">${composerIcons.image}<span>References</span></button><button type="button" id="zc-attach-frame" class="zc-attachment">${composerIcons.image}<span>Finished frame</span></button>`;
    composer.insertBefore(attachments,studio.$('prompt-composer'));
    const bottom=document.createElement('div');bottom.className='zc-prompt-bottom';
    const tools=document.createElement('div');tools.className='zc-prompt-tools';bottom.append(tools);
    const model=document.createElement('label');model.className='zc-model-control zc-tool';
    model.innerHTML=`${composerIcons.model}<span class="zc-sr-only">Video model</span><select id="zc-video-model" aria-label="Video model"></select>${composerIcons.chevron}`;
    tools.append(model);
    const imageModel=document.createElement('span');imageModel.className='zc-tool zc-frame-model';imageModel.innerHTML=`${composerIcons.model}<span>FLUX Klein</span>`;tools.append(imageModel);this.imageModel=imageModel;this.model=model;
    this.resolution=this.popup('resolution','Output resolution',composerIcons.size,studio.$('quality-setting'));tools.append(this.resolution);
    const lengthControls=this.root.querySelector('.gs-clip-length');lengthControls.append(studio.$('duration-setting'));
    this.length=this.popup('length','Clip length',composerIcons.clock,lengthControls);tools.append(this.length);
    // Original audio fields keep their listeners, uploads and model restrictions.
    this.audio=document.createElement('div');this.audio.className='zc-tool-popup zc-composer-audio';
    this.audio.append(studio.$('audio-settings'));tools.append(this.audio);
    const settings=document.createElement('button');settings.type='button';settings.className='zc-tool';settings.innerHTML=composerIcons.settings;settings.setAttribute('aria-label','More video settings');settings.title='More video settings';
    settings.onclick=()=>{workspace.selectPanel('settings');this.openControls();};tools.append(settings);
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
    composer.addEventListener('toggle',e=>{const detail=e.target;if(detail.tagName==='DETAILS'&&detail.open)for(const other of composer.querySelectorAll('details'))if(other!==detail)other.open=false;},true);
    composer.addEventListener('keydown',e=>{if(e.key!=='Escape')return;const open=Array.from(composer.querySelectorAll('details')).find(d=>d.open);if(open){open.open=false;open.querySelector('summary').focus({preventScroll:true});e.stopPropagation();}});
    this.composer=composer;this.sync();
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
    button.classList.toggle('has-media',!!asset);button.querySelector('span').textContent=label;button.title=asset?.name||label;
  }
  sync(){
    const s=this.studio,working=s.busy||s.project?.phase==='working',stage=s.composerStage();
    this.composer.dataset.stage=stage;
    const select=this.root.querySelector('#zc-video-model'),radios=Array.from(this.root.querySelectorAll('input[name="gs-engine"]')).filter(r=>!r.closest('label').hidden);
    const key=radios.map(r=>r.value+':'+r.disabled).join('|');
    if(select.dataset.choices!==key){select.replaceChildren();for(const radio of radios){const option=document.createElement('option');option.value=radio.value;option.textContent={local:'LTX 2.5',h3:'MiniMax H3',wan:'Wan 2.2',wan2:'Wan Animate 2',wan21:'Wan 2.1',seedance:'Seedance'}[radio.value];option.disabled=radio.disabled;select.append(option);}select.dataset.choices=key;}
    select.value=s.config.engine;select.disabled=working;this.model.hidden=stage!=='video';this.imageModel.hidden=stage!=='image'||s.lookMode==='ready';
    const task=this.root.querySelector('#zc-video-task');task.value=s.config.workflow_mode==='motion'?'swap':s.config.workflow_mode;task.disabled=working;
    this.resolution.hidden=stage!=='video';this.audio.hidden=s.$('audio-settings').hidden||stage!=='video';
    this.root.querySelector('#zc-tool-resolution').textContent=s.$('resolution').selectedOptions?.[0]?.textContent?.split(' · ')[0]||'Resolution';
    this.root.querySelector('#zc-tool-length').textContent=s.config.length_mode==='original'?'Full clip':`${s.config.duration}s`;
    const audioSummary=s.$('audio-summary');audioSummary.textContent=s.config.audio_id?'Reference audio':'Original audio';audioSummary.title='Audio and facial performance';
    const source=s.source?{...s.source,url:s.source.thumbnail_url}:null;
    this.attachment('source',source,s.source?'Source video':'Add video');
    this.attachment('refs',s.references?.[0],s.references?.length?`${s.references.length} reference${s.references.length===1?'':'s'}`:'References');
    this.attachment('frame',s.readyAsset,s.readyAsset?'Finished frame':'Finished frame');
    this.root.querySelector('#zc-attach-refs').hidden=s.lookMode==='ready';this.root.querySelector('#zc-attach-frame').hidden=s.lookMode!=='ready';
    for(const button of this.composer.querySelectorAll('.zc-attachment'))button.disabled=working;
    this.length.querySelector('summary').setAttribute('aria-label','Clip length: '+this.root.querySelector('#zc-tool-length').textContent);
  }
}

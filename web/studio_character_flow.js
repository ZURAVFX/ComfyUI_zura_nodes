import {characterSwapStage} from './studio_workflow_progress.js';
/** Explicit artist checkpoints for Character Replacement. Never queues a video. */
export {characterSwapStage} from './studio_workflow_progress.js';
export class CharacterSwapFlow{
  constructor(studio){
    this.s=studio;const doc=studio.container.ownerDocument;
    if(!doc.getElementById('zura-character-flow-styles')){const css=doc.createElement('link');css.id='zura-character-flow-styles';css.rel='stylesheet';css.href=new URL('./studio_character_flow.css',import.meta.url).href;doc.head.append(css);}
    this.legacy=studio.container.querySelector('.gs-steps');
    this.panel=doc.createElement('section');this.panel.className='zc-character-selection';this.panel.setAttribute('aria-label','Mask the subject');
    this.panel.innerHTML='<h3>Mask the subject</h3><p>Choose who to replace. White is editable; black keeps the original shot.</p><div class="zc-character-mask-controls"><label>Find subject<input type="text" maxlength="500" value="person" placeholder="person, red coat" aria-label="Subject mask prompt"></label><button type="button" class="gs-quiet" data-upload>Use mask video</button><button type="button" class="gs-quiet" data-clear hidden>Use automatic mask</button><input type="file" accept="video/mp4,video/quicktime,video/webm,.mkv" hidden aria-label="Black and white mask video"></div><p data-mask-note role="status"></p>';
    studio.$('prompt-stage').before(this.panel);
    this.input=this.panel.querySelector('input[type=text]');this.file=this.panel.querySelector('input[type=file]');this.note=this.panel.querySelector('[data-mask-note]');
    this.input.onchange=()=>void this.update({mask_prompt:this.input.value.trim()||'person',mask_video:''});
    this.panel.querySelector('[data-upload]').onclick=()=>this.file.click();
    this.panel.querySelector('[data-clear]').onclick=()=>void this.update({mask_video:''});
    this.file.onchange=()=>{const file=this.file.files?.[0];this.file.value='';if(file)void this.upload(file);};
  }
  get nav(){return this.s.creative?.workflowProgress?.nav;}
  async update(fields){
    const s=this.s;if(s.busy||s.project?.phase==='working')return;
    return s.perform(async epoch=>{
      const config={...s.readConfig(),...fields,openjutsu_direct:false};
      if(s.project){const id=s.project.id,p=await s.request(`/projects/${id}/config`,s.configBody(config));if(epoch!==s.resetEpoch||s.project?.id!==id)return;s.project=p;}
      s.config=config;s.promptStage=null;s.preview='mask';s.syncForm();
    });
  }
  async upload(file){
    const s=this.s;if(s.busy||s.project?.phase==='working')return;
    return s.perform(async epoch=>{
      this.note.textContent='Loading mask video…';const form=new FormData();form.append('file',file);
      const response=await s.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body:form,timeoutMs:300000});
      const asset=await response.json();if(!response.ok)throw Error(asset.error||'Could not load the mask video.');
      if(epoch!==s.resetEpoch)return;
      const config={...s.readConfig(),mask_video:asset.id,openjutsu_direct:false};
      if(s.project){const id=s.project.id,p=await s.request(`/projects/${id}/config`,s.configBody(config));if(epoch!==s.resetEpoch||s.project?.id!==id)return;s.project=p;}
      s.config=config;s.promptStage=null;s.preview='mask';s.syncForm();
    });
  }
  sync(){
    const s=this.s,enabled=s.creative?.mode==='video'&&s.config.workflow_mode==='swap'&&!s.headSwap();
    this.panel.hidden=!enabled||characterSwapStage(s)!==1;this.legacy.style.display=enabled?'none':'';
    if(!enabled)return;
    const stage=characterSwapStage(s),working=s.busy||s.project?.phase==='working';
    const custom=!!s.config.mask_video;
    const imagePicker=s.creative?.videoComposer?.imageModel;if(imagePicker&&stage===1)imagePicker.hidden=true;
    if(this.input!==this.input.ownerDocument.activeElement)this.input.value=s.config.mask_prompt||'person';
    this.input.disabled=working||custom;this.file.disabled=working;
    this.panel.querySelector('[data-upload]').disabled=working;this.panel.querySelector('[data-clear]').hidden=!custom;this.panel.querySelector('[data-clear]').disabled=working;
    this.note.textContent=custom?'Custom mask selected. Use a full-length mask aligned to the source video, or a mask matching the trimmed clip.':'Describe the subject, then generate and review its tracked mask. Default: person.';
    const direct=s.container.querySelector('input[name="gs-look"][value="direct"]');if(direct)direct.closest('label').hidden=true;
    if(stage===1){
      s.$('preview-title').textContent=s.project?.phase==='review'?'Review the tracked subject mask':'Mask the subject';
      s.$('preview-description').textContent=s.project?.phase==='review'?'Check the selection through the whole clip before building the replacement frame.':'Describe who to replace, or supply a black and white mask video.';
      const loras=s.creative?.videoComposer?.openingLoras?.el;if(loras)loras.hidden=true;
      for(const id of ['refs','frame']){const b=s.container.querySelector('#zc-attach-'+id);if(b)b.parentElement.hidden=true;}
      s.$('prompt-heading').textContent=s.project?.phase==='review'?'Review the subject mask':'Select the subject to replace';
      s.$('model-prompt').hidden=true;s.$('image-editor').hidden=true;s.$('frame-review').hidden=true;
      if(!working){s.$('primary').textContent=s.project?.phase==='review'?'Use mask & continue':'Generate subject mask';s.$('primary').disabled=!s.source;s.$('action-note').textContent=s.project?.phase==='review'?'Watch the mask over the whole clip. Continue when it follows the correct subject.':'First, mask the subject. No replacement image or video is generated yet.';}
    }else if(stage===2){s.$('prompt-heading').textContent=s.composerStage()==='review'?'Review your replacement frame':'Build the replacement reference frame';}
    // A mask can be reviewed before a replacement reference is chosen.
    if(stage===2&&!s.hasLook()&&!working){s.$('primary').disabled=true;s.$('action-note').textContent='Add a replacement reference image, or upload a finished frame. Choose an image model to build the reference.';}
  }
}

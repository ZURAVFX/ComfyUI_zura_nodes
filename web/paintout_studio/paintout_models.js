import {maskIcons} from './paintout_icons.js';
import {groupMissingNodes} from '../studio_node_setup.js';

const ROUTE='/zura/paintout/model-downloads';
const ACTIVE=new Set(['queued','downloading','verifying','cancelling']);
const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
const bytes=value=>{const size=Number(value)||0;return size>=1e9?`${(size/1e9).toFixed(1)} GB`:size>=1e6?`${Math.ceil(size/1e6)} MB`:`${Math.max(0,Math.round(size/1e3))} KB`;};
const safeError=value=>String(value||'The download could not finish. Try again.').replace(/hf_[A-Za-z0-9_-]+/g,'[token hidden]').replace(/Bearer\s+\S+/gi,'Bearer [hidden]');
const REASONS={targeted:'For the final video repair. Your mask and painted frames guide the removal.',full:'For a full-scene clean plate without a removal mask.',mask:'For automatic point selection and tracking, including a painted starting mask. You can import a finished mask video instead.',clean:'For painting clean-frame guides with FLUX. You can also import frames edited elsewhere.',targeted_hdr:'For targeted repair of footage that is already HDR.',full_hdr:'For a full-scene clean plate from HDR footage.',_sdr_hdr:'For the video repair and the separate HDR conversion. The repaired clip saves before conversion starts.',hdr_conversion:'For converting a repaired SDR clip to HDR after the repair has saved.'};

/** An explicit, local-only downloader. Opening this panel never starts a download. */
export class PaintoutModels{
  constructor(workspace){
    this.w=workspace;this.models=[];this.job=null;this.context={};this.loading=false;this.closed=false;this.generation=0;
    const style=el('link');style.rel='stylesheet';style.href=new URL('./paintout_models.css',import.meta.url).href;workspace.page.append(style);style.onload=()=>this.positionPanel();
    this.root=el('details');this.root.className='zps-models';
    this.root.innerHTML=`<summary title="Check and download Paintout models">${maskIcons.download}<span>Models</span><span data-model-badge></span></summary><section class="zps-models-panel" aria-label="Paintout model setup"><header><div><h3>Set up your models</h3><p>Files already on this computer are reused.</p></div><button type="button" data-model-close aria-label="Close model setup">${maskIcons.x}</button></header><label class="zps-models-choice">Models for<select data-model-package aria-label="Choose what to set up"></select></label><p class="zps-models-reason" data-model-reason></p><div data-model-files></div><details class="zps-models-access"><summary>Model licences and access</summary><div data-model-licences></div><p>Some publishers require you to accept their licence on Hugging Face before downloading.</p><label>Hugging Face read token <span>(only if needed)</span><input data-model-token type="password" autocomplete="off" spellcheck="false" placeholder="Paste a read token" /></label><p>Your token is used for this download only and is not saved in Paintout.</p></details><div class="zps-models-actions"><button type="button" data-model-download>${maskIcons.download}<span>Download missing models</span></button><button type="button" data-model-refresh>Check again</button></div><div class="zps-models-download" data-model-job hidden><strong data-model-job-title></strong><progress data-model-progress aria-label="Model download progress"></progress><p data-model-progress-text></p><button type="button" data-model-cancel>Cancel download</button></div><p class="zps-models-status" data-model-status role="status" aria-live="polite"></p><div class="zps-models-nodes" data-model-nodes hidden></div></section>`;
    this.$=key=>this.root.querySelector(`[data-model-${key}]`);
    this.$('close').onclick=()=>this.close();this.$('package').onchange=()=>this.render();this.$('download').onclick=()=>this.start();this.$('refresh').onclick=()=>this.refresh();this.$('cancel').onclick=()=>this.cancel();
    this.root.ontoggle=()=>{if(this.root.open){this.closed=false;this.positionPanel();void this.load();}else{this.stopPolling();this.$('token').value='';}};
    this.root.addEventListener('keydown',event=>{event.stopPropagation();if(event.key==='Escape'){event.preventDefault();this.close();}});
    this.outside=event=>{if(this.root.open&&!this.root.contains(event.target))this.close();};document.addEventListener('pointerdown',this.outside);this.viewport=()=>this.positionPanel();window.addEventListener('resize',this.viewport);document.addEventListener('scroll',this.viewport,true);
    workspace.page.querySelector('.zf-heading').append(this.root);
    this.render();
  }
  positionPanel(){if(!this.root?.open)return;const panel=this.root.querySelector('.zps-models-panel'),button=this.root.querySelector('summary').getBoundingClientRect(),width=Math.min(560,innerWidth-24),top=innerWidth<=700?70:Math.max(12,Math.min(button.bottom+8,innerHeight-160));Object.assign(panel.style,{left:`${Math.max(12,Math.min(button.right-width,innerWidth-width-12))}px`,right:'auto',top:`${top}px`,width:`${width}px`,maxHeight:`${Math.max(120,Math.min(720,innerHeight-top-12))}px`});}
  active(){return !!this.job&&ACTIVE.has(this.job.phase);}
  videoGroup(){return (this.context.mode==='full'?'full':'targeted')+(this.context.pipeline==='hdr_hdr'?'_hdr':'');}
  recommended(){const c=this.context;if(c.stage==='mask')return 'mask';if(c.stage==='clean')return 'clean';if(c.phase==='hdr')return 'hdr_conversion';if(c.pipeline==='sdr_hdr')return '_sdr_hdr';return this.videoGroup();}
  updatePackages(raw){
    this.catalogue=raw;this.models=[...raw];
    if(this.context.pipeline==='sdr_hdr'){const video=raw.find(model=>model.id===this.videoGroup()),hdr=raw.find(model=>model.id==='hdr_conversion');if(video&&hdr){const files=[...new Map([...video.files,...hdr.files].map(file=>[(file.folder||'')+'/'+file.filename,file])).values()];this.models.unshift({id:'_sdr_hdr',name:video.name+' + HDR conversion',model_ids:[video.id,hdr.id],files,remaining_bytes:files.filter(file=>!file.installed).reduce((sum,file)=>sum+(Number(file.size_bytes)||0),0),gated:video.gated||hdr.gated});}}
    const previous=this.$('package').value;this.$('package').replaceChildren(...this.models.map(model=>{const option=el('option',model.name);option.value=model.id;return option;}));if(this.models.some(model=>model.id===previous))this.$('package').value=previous;
  }
  setContext(context){const previous=this.context;this.context=context||{};if(this.catalogue&&(previous.mode!==this.context.mode||previous.pipeline!==this.context.pipeline))this.updatePackages(this.catalogue);this.renderSummary();this.renderNodes();}
  open(scope){this.closed=false;this.root.open=true;this.requested=scope==='video'?(this.context.pipeline==='sdr_hdr'?'_sdr_hdr':this.videoGroup()):scope==='hdr_source'?(this.context.mode==='full'?'full_hdr':'targeted_hdr'):scope||this.recommended();if(this.models.some(model=>model.id===this.requested)){this.$('package').value=this.requested;this.render();}if(!this.loading)void this.load();this.root.querySelector('summary').scrollIntoView?.({block:'nearest'});}
  close(){this.closed=true;this.root.open=false;this.stopPolling();this.$('token').value='';}
  stopPolling(){clearTimeout(this.timer);this.timer=null;}
  async refresh(){await this.load();try{await this.w.loadModels();}catch{} }
  async load(){
    if(this.loading)return;this.loading=true;this.render();
    try{
      const data=await this.w.fetch(ROUTE);
      if(!Array.isArray(data?.models))throw Error('Model setup is unavailable. Update Paintout and restart ComfyUI, then check again.');
      const previous=this.$('package').value;this.updatePackages(data.models);
      const selection=this.requested||previous||this.recommended();this.requested=null;if(this.models.some(model=>model.id===selection))this.$('package').value=selection;
      this.error='';this.submissionUnknown=false;if(data.active?.id){this.job=data.active;if(!this.job.phase)this.job.phase='queued';}
      this.render();if(this.active()&&this.root.open)this.schedulePoll(0);
    }catch(error){this.error=safeError(error.message);this.render();}
    finally{this.loading=false;this.render();}
  }
  renderSummary(){const badge=this.$('badge');if(this.active()){badge.textContent='Downloading';return;}const model=this.models.find(model=>model.id===this.recommended());const missing=model?.files?.filter(file=>!file.installed).length;badge.textContent=missing?`${missing} missing`:'';}
  renderNodes(){
    const nodeBox=this.$('nodes'),missing=(this.context.missingNodes||[]).filter(name=>typeof name==='string'&&!/\.(safetensors|onnx|pt|pth|ckpt|bin)$/i.test(name));
    nodeBox.hidden=!missing.length;nodeBox.replaceChildren();if(!missing.length)return;
    nodeBox.append(el('strong','Required ComfyUI nodes'),el('p','Follow the setup links below, then restart ComfyUI. Downloading models does not install extensions.'));
    for(const pack of groupMissingNodes(missing).packs){
      const row=el('p'),link=this.link(pack.name,pack.url);if(link)row.append(link);nodeBox.append(row);
      if(pack.note){const note=el('p',pack.note);if(pack.patch){const patch=this.link('OpenJutsu compatibility patch',pack.patch);if(patch)note.append(' ',patch);}nodeBox.append(note);}
    }
    const detail=el('details'),summary=el('summary','Show missing nodes');detail.append(summary,el('p',missing.join(', ')));nodeBox.append(detail);
  }
  link(label,url){try{const parsed=new URL(url);if(parsed.protocol!=='https:')return null;const link=el('a',label);link.href=parsed.href;link.target='_blank';link.rel='noopener noreferrer';return link;}catch{return null;} }
  render(){
    const model=this.models.find(model=>model.id===this.$('package').value),active=this.active(),files=model?.files||[],missing=files.filter(file=>!file.installed),incomplete=missing.some(file=>file.incomplete),total=Number(model?.remaining_bytes)||0;
    this.$('package').disabled=active||this.loading||!this.models.length;
    this.$('reason').textContent=model?(REASONS[model.id]||model.note||'Download the missing files for this step.'):this.loading?'Checking installed model files…':'Choose what you want to set up.';
    this.$('files').replaceChildren();
    if(model){
      const heading=el('p',missing.length?`${files.length-missing.length} of ${files.length} files ready · ${total?bytes(total)+' to download':'download size checked when it starts'}`:'All model files for this step are installed.');heading.className='zps-models-file-summary';this.$('files').append(heading);
      const list=el('ul');list.className='zps-models-file-list';
      for(const file of files){const row=el('li'),label=el('span'),state=el('small',file.installed?'Installed':file.incomplete?'Check existing file':file.size_bytes?bytes(file.size_bytes):'Missing');label.append(el('strong',file.label||file.filename),el('small',file.folder?`models/${file.folder}`:''));row.append(label,state);row.dataset.state=file.installed?'installed':file.incomplete?'incomplete':'missing';list.append(row);}
      this.$('files').append(list);
      if(incomplete)this.$('files').append(el('p','An existing file does not match this package. It will not be overwritten. Check its version or move it out of the model folder, then check again.'));
    }
    this.$('licences').replaceChildren();for(const url of [...new Set([model?.license_url,...files.map(file=>file.model_card||file.repo&&`https://huggingface.co/${file.repo}`)].filter(Boolean))]){const link=this.link('Review model terms',url);if(link)this.$('licences').append(link);}
    this.$('download').disabled=active||this.loading||!model||!missing.length||incomplete;this.$('download').querySelector('span').textContent=active?'Download in progress':this.submissionUnknown?'Check download status':incomplete?'Check existing files':!missing.length&&model?'Models ready':this.job?.phase==='failed'&&(this.job.model_id===model?.id||model?.model_ids?.some(id=>this.job.model_ids?.includes(id)))?'Retry missing models':'Download missing models';
    this.$('refresh').disabled=this.loading;this.$('cancel').disabled=!active||!!this.cancelling||this.job?.phase==='cancelling';
    const job=this.job;this.$('job').hidden=!job;this.$('cancel').hidden=!active;
    if(job){
      const title={queued:'Waiting to download',downloading:'Downloading models',verifying:'Checking downloaded files',done:'Models ready',failed:'Download stopped',cancelled:'Download cancelled',cancelling:'Stopping download'}[job.phase]||'Checking download';this.$('job-title').textContent=title;
      const progress=this.$('progress');progress.max=Number(job.total_bytes)||1;if(Number(job.total_bytes)>0)progress.value=Math.min(Number(job.done_bytes)||0,Number(job.total_bytes));else progress.removeAttribute('value');
      this.$('progress-text').textContent=job.phase==='done'?'Your files are installed. You can continue in Paintout.':job.phase==='failed'?safeError(job.error):job.phase==='cancelling'?'Stopping safely. Completed files will be kept.':job.phase==='cancelled'?'Completed files are kept. Download missing models to resume.':`${job.current_file||'Preparing the download'}${job.done_bytes?' · '+bytes(job.done_bytes)+(job.total_bytes?' of '+bytes(job.total_bytes):''):''}`;
    }
    this.$('status').textContent=this.error||(!model&&!this.loading?'Open this panel to check model files.':'');
    this.$('status').classList.toggle('is-error',!!this.error);
    if(model?.auth_required||job?.phase==='failed'&&/licen[cs]e|gated|hugging|authori[sz]|access|401|403/i.test(job.error||''))this.root.querySelector('.zps-models-access').open=true;
    this.renderSummary();this.renderNodes();this.positionPanel();
  }
  async start(){
    if(this.loading||this.active())return;
    if(this.submissionUnknown){await this.load();return;}
    const model=this.models.find(model=>model.id===this.$('package').value);if(!model)return;
    const token=this.$('token').value.trim();this.$('token').value='';this.error='';this.loading=true;this.render();
    try{const data=await this.w.fetch(ROUTE,{...(model.model_ids?{model_ids:model.model_ids}:{model_id:model.id}),...(token?{token}:{})});if(!data?.id)throw Error('The download did not start. Check again and retry.');this.job={id:data.id,model_id:model.id,phase:'queued',done_bytes:0,total_bytes:model.remaining_bytes||0};this.render();this.schedulePoll(0);}
    catch(error){
      this.submissionUnknown=true;
      try{
        const data=await this.w.fetch(ROUTE);
        if(!Array.isArray(data?.models))throw Error('Download status is unavailable.');
        this.updatePackages(data.models);this.submissionUnknown=false;
        if(data.active?.id){this.job={...data.active,phase:data.active.phase||'queued'};this.error='';this.schedulePoll(0);}
        else this.error=safeError(error.message)+' No active download was found. Check the files before retrying.';
      }catch{this.error='The download may have started. Check its status before retrying. Your download has not been restarted.';}
      this.render();
    }
    finally{this.loading=false;this.render();}
  }
  schedulePoll(delay=1000){this.stopPolling();if(!this.closed&&this.root.open)this.timer=setTimeout(()=>void this.poll(),delay);}
  async poll(){
    if(!this.job?.id||this.polling||this.closed||!this.root.open)return;this.polling=true;
    try{const data=await this.w.fetch(`${ROUTE}/${encodeURIComponent(this.job.id)}`);if(!data?.id)throw Error('Waiting to reconnect to the download…');this.job=data;this.error='';this.render();if(data.phase==='done'){await this.w.loadModels();await this.load();}else if(ACTIVE.has(data.phase))this.schedulePoll();}
    catch(error){this.error=safeError(error.message)+' Your download has not been restarted.';this.render();this.schedulePoll(2000);}
    finally{this.polling=false;}
  }
  async cancel(){if(!this.active()||this.cancelling||this.job?.phase==='cancelling')return;this.cancelling=true;this.render();try{await this.w.fetch(`${ROUTE}/${encodeURIComponent(this.job.id)}/cancel`,{});this.job.phase='cancelling';this.schedulePoll(0);}catch(error){this.error=safeError(error.message);}finally{this.cancelling=false;this.render();}}
  destroy(){this.close();document.removeEventListener('pointerdown',this.outside);window.removeEventListener('resize',this.viewport);document.removeEventListener('scroll',this.viewport,true);}
}

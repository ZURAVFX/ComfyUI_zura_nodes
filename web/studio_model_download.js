// Model packages are allowlisted by the backend. Fetching the list never starts a download.
export class StudioModelDownloads {
  constructor(panel, request, onInstalled) {
    this.panel=panel;this.request=request;this.onInstalled=onInstalled;this.packages=[];this.job=null;this.closed=false;
    panel.innerHTML='<summary>Download video models</summary><div class="gs-advanced-body"><label>Model package <select data-model-package aria-label="Model package"></select></label><div data-model-files></div><div data-model-actions></div><p data-model-progress role="status" aria-live="polite"></p></div>';
    this.select=panel.querySelector('[data-model-package]');this.files=panel.querySelector('[data-model-files]');this.actions=panel.querySelector('[data-model-actions]');this.progress=panel.querySelector('[data-model-progress]');
    this.select.onchange=()=>this.render();panel.ontoggle=()=>{if(panel.open && !this.packages.length)this.load();};
  }
  el(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
  async load(){
    try{const data=await this.request('/model-downloads');this.packages=(data.models||[]).filter(p=>['openjutsu_h3','wan_animate_2','ltx25_core','ltx25_full_vae','ltx25_refine','ltx25_sdr_hdr','flux2_klein_start'].includes(p.id));
      const previous=this.select.value;this.select.replaceChildren(...this.packages.map(p=>{const e=this.el('option',p.name);e.value=p.id;return e;}));if(this.packages.some(p=>p.id===previous))this.select.value=previous;this.render();
    }catch(e){this.progress.textContent=e.message||'Could not load model packages.';}
  }
  render(){
    const pack=this.packages.find(p=>p.id===this.select.value);this.files.replaceChildren();this.actions.replaceChildren();if(!pack)return;
    this.files.append(this.el('p',pack.note||''));
    if(pack.error){this.files.append(this.el('p',pack.error));return;}
    const gb=n=>`${(n/1e9).toFixed(2)} GB`;this.files.append(this.el('p',`${gb(pack.remaining_bytes)} to download`));
    for(const file of pack.files){const p=this.el('p',`${file.installed?'Installed':file.incomplete?'Existing file has the wrong size; check or move it':'Needed'} · ${file.filename} · ${gb(file.size_bytes)}`);p.className='gs-note';this.files.append(p);}
    this.files.append(this.el('p','Review each source’s terms and access requirements before downloading:'));
    for(const repo of [...new Set(pack.files.map(file=>file.repo))]){const link=this.el('a',repo);link.href=`https://huggingface.co/${repo}`;link.target='_blank';link.rel='noopener noreferrer';this.files.append(link,document.createElement('br'));}
    const blocked=pack.files.some(file=>file.incomplete);const button=this.el('button',this.job?'Download in progress':blocked?'Check existing files':pack.remaining_bytes?'Download missing files':'Files installed');button.type='button';button.disabled=!!this.job||blocked||!pack.remaining_bytes;button.onclick=()=>this.start(pack.id);this.actions.append(button);
    if(this.job){const cancel=this.el('button','Cancel download');cancel.type='button';cancel.onclick=()=>this.request(`/model-downloads/${this.job}/cancel`,{}).catch(e=>this.progress.textContent=e.message);this.actions.append(cancel);}
  }
  async start(id){
    if(this.job)return;
    try{this.progress.textContent='Starting download…';const result=await this.request('/model-downloads',{model_id:id});this.job=result.id;this.select.disabled=true;this.render();
      while(this.job && !this.closed){const state=await this.request(`/model-downloads/${this.job}`);const percent=state.total_bytes?Math.floor(state.done_bytes/state.total_bytes*100):0;
        this.progress.textContent=state.phase==='done'?'Download complete.':state.phase==='failed'?state.error:state.phase==='cancelled'?'Download cancelled.':`${state.current_file||'Preparing download'} · ${percent}%`;
        if(['done','failed','cancelled'].includes(state.phase)){this.job=null;this.select.disabled=false;await this.load();if(state.phase==='done')await this.onInstalled?.();break;}
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
    }catch(e){this.progress.textContent=e.message||'Download failed.';this.job=null;this.select.disabled=false;this.render();}
  }
  dispose(){this.closed=true;this.panel.ontoggle=null;}
}

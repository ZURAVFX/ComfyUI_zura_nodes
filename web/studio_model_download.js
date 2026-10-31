import {groupMissingNodes} from './studio_node_setup.js';
// Model packages are allowlisted by the backend. Fetching the list never starts a download.
const PACKAGE_IDS=['openjutsu_h3','sam31','fasth3_draft','h3_reference_core','wan_animate_2','wan21_relight','wan22_animate_core','wan22_pose','wan22_style','wan22_first_last','h3_birefnet','h3_head_acceleration','h3_head_adapters','h3_taomate','h3_dmd_ref2va','h3_int8_vae','h3_control','h3_crossview','h3_first_last','ltx25_core','ltx25_full_vae','ltx25_refine','ltx25_sdr_hdr','ltx25_text_encoder','ltx25_text_int8','ltx25_clean_plate','ltx25_outpaint','ltx25_in_outpaint','ltx_control','flux2_klein_start','flux3_klein','qwen2511','qwen21'];
const ROUTE_NAMES={openjutsu:'OpenJutsu character replacement',wan2:'Wan Animate 2',wan:'Wan 2.2 character replacement',wan21_relight:'Wan 2.1 relight',h3_camera:'H3 camera angle',h3_head_swap:'H3 head swap',h3_viewport:'H3 viewport to final',h3:'MiniMax H3',local:'LTX 2.5',local_scene:'LTX 2.5 whole scene',h3_first_last:'H3 first & last frame',ltx_first_last:'LTX first & last frame',wan_first_last:'Wan first & last frame',h3_reference:'H3 reference video',ltx_outpaint_hdr_long:'LTX long HDR frame extension',ltx_outpaint_hdr:'LTX HDR frame extension',ltx_outpaint_expand:'LTX frame extension',ltx_outpaint_black:'LTX black-area fill',ltx_outpaint_long:'LTX long frame extension',paintout_targeted:'Targeted paintout',paintout_full:'Full-scene clean plate',hdr_sdr:'SDR to HDR',hdr_native:'HDR to HDR',ltx_hdr_endpoints:'LTX native HDR first and last frame'};

const MANUAL_SOURCES={
  'yolox_l.onnx':{url:'https://huggingface.co/yzd-v/DWPose/blob/main/yolox_l.onnx',note:'DWPose body detector · 216.75 MB. Place this file at the location shown below.'},
  'dw-ll_ucoco_384_bs5.torchscript.pt':{url:'https://huggingface.co/hr16/DWPose-TorchScript-BatchSize5/blob/main/dw-ll_ucoco_384_bs5.torchscript.pt',note:'DWPose pose estimator · 135.06 MB. Place this file at the location shown below.'},
  'wan_2.1_idv2v_int8_convrot.safetensors':{url:'https://huggingface.co/Kijai/Wan_ID_V2V_comfy',note:'The conversion publisher does not state a licence. Review its terms and the upstream ID-V2V licence.'},
  'lightx2v_i2v_14b_480p_cfg_step_distill_rank64_bf16.safetensors':{url:'https://huggingface.co/Kijai/WanVideo_comfy/tree/main/Lightx2v',note:'The exact converted file has no stated repository licence. Review its terms before use.'},
  'minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors':{url:'https://huggingface.co/RunningHubAI/rh-minimax-h3-dmd-ref2va-8step-turbo-pruned.safetensors-lora',note:'The publisher does not state a licence. Review its terms before use.'},
};
const gb=n=>`${(Number(n||0)/1e9).toFixed(2)} GB`;
const fileKey=file=>`${file.folder||''}/${file.filename||''}`.toLowerCase();
ROUTE_NAMES.ltx_performance_hdr='LTX performance + HDR delivery';

export class StudioModelDownloads {
  constructor(panel, request, onInstalled) {
    this.panel=panel;this.request=request;this.onInstalled=onInstalled;this.packages=[];this.job=null;this.closed=false;this.context=null;this.uncertain=false;this.starting=false;
    const floating=panel.classList.contains('zc-tool-popup');panel.classList.add('gs-model-downloads');
    panel.innerHTML=`<summary>${floating?'Models':'Download video models'}</summary><div class="gs-advanced-body${floating?' zc-tool-panel':''}"><label>Model package <select data-model-package aria-label="Model package"></select></label><div data-model-files></div><div data-model-actions></div><p data-model-progress role="status" aria-live="polite"></p></div>`;
    this.select=panel.querySelector('[data-model-package]');this.files=panel.querySelector('[data-model-files]');this.actions=panel.querySelector('[data-model-actions]');this.progress=panel.querySelector('[data-model-progress]');
    this.select.onchange=()=>this.render();panel.ontoggle=()=>{if(panel.open && !this.packages.length)this.load();};
  }
  el(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
  async load(){
    try{const data=await this.request('/model-downloads');this.uncertain=false;this.packages=(data.models||[]).filter(p=>PACKAGE_IDS.includes(p.id));
      const previous=this.select.value;const overview=this.el('option','Current workflow');overview.value='__workflow__';this.select.replaceChildren(overview,...this.packages.map(p=>{const e=this.el('option',p.name);e.value=p.id;return e;}));if(previous==='__workflow__'||this.packages.some(p=>p.id===previous))this.select.value=previous;else if(!this.context&&this.packages.length)this.select.value=this.packages[0].id;if(this.missingContext)this.applyMissingContext();this.render();
      if(data.active?.id&&!this.job&&!this.closed){this.job=data.active.id;this.select.disabled=true;this.progress.textContent='Reconnecting to the existing download…';this.render();void this.poll();}
    }catch(e){this.progress.textContent=this.uncertain?'Could not confirm whether the download started. Check its status before trying again.':e.message||'Could not load model packages.';this.render();}
  }
  setContext(context){
    const next=context&&Array.isArray(context.files)&&Array.isArray(context.missingNodes)?context:null;
    const changed=next?.route!==this.context?.route;
    this.context=next;
    if(changed&&next&&this.packages.length&&!this.job)this.select.value='__workflow__';
    if(this.packages.length && this.select.value==='__workflow__')this.render();
  }
  setMissingContext(route,missing){
    this.missingContext=Array.isArray(missing)?{route,missing}:null;
    this.applyMissingContext();
  }
  applyMissingContext(){
    if(!this.missingContext){this.setContext(null);return;}
    const {route,missing}=this.missingContext,files=[],missingNodes=[];
    for(const name of missing){
      if(typeof name!=='string')continue;
      if(/\.(safetensors|onnx|pt|pth|ckpt)$/i.test(name)){
        const match=this.packages.flatMap(pack=>pack.files||[]).find(file=>file.filename?.toLowerCase()===name.toLowerCase());
        files.push({folder:match?.folder||'',filename:name,ready:false});
      }else missingNodes.push(name);
    }
    this.setContext({route,files,missingNodes});
  }
  link(label,url){const link=this.el('a',label);link.href=url;link.target='_blank';link.rel='noopener noreferrer';return link;}
  renderWorkflow(){
    if(!this.context){this.files.append(this.el('p','Choose a workflow to see its setup.'));return;}
    const {route,files,missingNodes}=this.context;
    this.files.append(this.el('strong',ROUTE_NAMES[route]||'Current workflow'));
    const missing=files.filter(file=>file&&file.ready===false),keys=new Set(missing.map(fileKey));
    const candidates=this.packages.filter(pack=>!pack.error&&Array.isArray(pack.files));
    const remaining=new Set(keys),packs=[];
    while(remaining.size){
      const ranked=candidates.filter(pack=>!packs.includes(pack)).map(pack=>({pack,count:pack.files.filter(file=>remaining.has(fileKey(file))).length})).filter(x=>x.count);
      ranked.sort((a,b)=>b.count-a.count||Number(a.pack.remaining_bytes||0)-Number(b.pack.remaining_bytes||0));
      if(!ranked.length)break;
      const pack=ranked[0].pack;packs.push(pack);for(const file of pack.files)remaining.delete(fileKey(file));
    }
    const matched=new Set(packs.flatMap(pack=>pack.files.map(fileKey)));
    // Package downloads include their other absent dependencies. Count these
    // once, rather than adding overlapping package totals together.
    const unique=new Map();for(const pack of packs)for(const file of pack.files)if(!file.installed&&!unique.has(fileKey(file)))unique.set(fileKey(file),Number(file.size_bytes)||0);
    const manual=missing.filter(file=>!matched.has(fileKey(file)));
    if(!missing.length)this.files.append(this.el('p','No missing model files reported for this workflow.'));
    else if(packs.length)this.files.append(this.el('p',`${gb([...unique.values()].reduce((sum,n)=>sum+n,0))} in available packages${manual.length?' · some files need manual setup':''}`));
    else this.files.append(this.el('p','The missing files below need manual setup.'));
    for(const pack of packs){
      const row=this.el('div','');row.className='gs-model-package';row.append(this.el('strong',pack.name),this.el('p',`${gb(pack.remaining_bytes)} to download${pack.note?' · '+pack.note:''}`));
      if(!pack.remaining_bytes)row.append(this.el('p','Files are present. Refresh setup or restart ComfyUI if the workflow still cannot see them.'));
      for(const file of pack.files.filter(file=>!file.installed))row.append(this.el('p',`${file.incomplete?'Existing file differs from this download; check its version':'Needed'} · ${file.filename} · ${gb(file.size_bytes)}`));
      for(const repo of [...new Set(pack.files.map(file=>file.repo).filter(Boolean))]) row.append(this.link(`Review ${repo}`,`https://huggingface.co/${repo}`),' ');
      if(pack.license_url)row.append(this.link('Review licence',pack.license_url),' ');
      const blocked=pack.files.some(file=>file.incomplete);const button=this.el('button',this.job||this.starting?'Download in progress':blocked?'Check existing files':pack.remaining_bytes?'Download missing files':'Files installed');button.type='button';button.disabled=!!this.job||this.starting||this.uncertain||blocked||!pack.remaining_bytes;button.onclick=()=>this.start(pack.id);row.append(button);this.files.append(row);
    }
    if(manual.length){this.files.append(this.el('p','Not included in an automatic download:'));for(const file of manual){const row=this.el('p',`${file.filename||file.path||'Unknown model file'}`),source=MANUAL_SOURCES[String(file.filename||'').toLowerCase()];if(source){row.append(' · ',this.link('Source',source.url),' · '+source.note);}if(file.path&&file.path!==file.filename)row.append(' Save to: '+file.path);this.files.append(row);}}
    if(missingNodes.length){
      this.files.append(this.el('p','Required ComfyUI nodes:'));const grouped=groupMissingNodes(missingNodes);
      for(const pack of grouped.packs){const row=this.el('p','');row.append(this.link(pack.name,pack.url),' · '+pack.missing.join(', '));this.files.append(row);if(pack.note){const note=this.el('p',pack.note);if(pack.patch)note.append(' ',this.link('OpenJutsu compatibility patch',pack.patch));this.files.append(note);}}
      if(grouped.unknown.length)this.files.append(this.el('p',`Other nodes: ${grouped.unknown.join(', ')}. Check the workflow setup guide for their packs.`));
      this.files.append(this.el('p','Install the required node packs, then restart ComfyUI.'));
    }
  }
  render(){
    this.files.replaceChildren();this.actions.replaceChildren();if(this.job){const cancel=this.el('button','Cancel download');cancel.type='button';cancel.onclick=()=>this.request(`/model-downloads/${this.job}/cancel`,{}).catch(e=>this.progress.textContent=e.message);this.actions.append(cancel);}if(this.uncertain){const check=this.el('button','Check download status');check.type='button';check.onclick=()=>this.load();this.actions.append(check);}if(this.select.value==='__workflow__'){this.renderWorkflow();return;}const pack=this.packages.find(p=>p.id===this.select.value);if(!pack)return;
    this.files.append(this.el('p',pack.note||''));
    if(pack.error){this.files.append(this.el('p',pack.error));return;}
    this.files.append(this.el('p',`${gb(pack.remaining_bytes)} to download`));
    for(const file of pack.files){const p=this.el('p',`${file.installed?'Installed':file.incomplete?'Existing file differs; check its version before moving it':'Needed'} · ${file.filename} · ${gb(file.size_bytes)}`);p.className='gs-note';this.files.append(p);}
    this.files.append(this.el('p','Review each source’s terms and access requirements before downloading:'));
    if(pack.license_url)this.files.append(this.link('Review licence',pack.license_url),document.createElement('br'));
    for(const repo of [...new Set(pack.files.map(file=>file.repo))]){const link=this.el('a',repo);link.href=`https://huggingface.co/${repo}`;link.target='_blank';link.rel='noopener noreferrer';this.files.append(link,document.createElement('br'));}
    const blocked=pack.files.some(file=>file.incomplete);const button=this.el('button',this.job||this.starting?'Download in progress':blocked?'Check existing files':pack.remaining_bytes?'Download missing files':'Files installed');button.type='button';button.disabled=!!this.job||this.starting||this.uncertain||blocked||!pack.remaining_bytes;button.onclick=()=>this.start(pack.id);this.actions.append(button);
  }
  async start(id){
    if(this.job||this.starting||this.uncertain)return;
    this.starting=true;this.render();
    try{this.progress.textContent='Starting download…';const result=await this.request('/model-downloads',{model_id:id});if(!result.id)throw new Error('Could not confirm the download started. Refresh setup before retrying.');this.job=result.id;this.starting=false;this.select.disabled=true;this.render();await this.poll();
    }catch(e){this.starting=false;this.job=null;this.uncertain=true;this.select.disabled=false;this.progress.textContent='Checking whether the download started…';this.render();await this.load();if(!this.job&&!this.uncertain)this.progress.textContent=e.message||'The download did not start. Try again.';}
  }
  async poll(){
    if(this.polling)return;
    this.polling=true;
    try{
      while(this.job && !this.closed){let state;
        try{state=await this.request(`/model-downloads/${this.job}`);}
        catch(error){
          if(/unknown model download/i.test(error.message||'')){this.progress.textContent='Download status is no longer available. Refresh setup and check the files before retrying.';this.job=null;this.select.disabled=false;this.render();break;}
          this.progress.textContent='Connection lost. Reconnecting to the existing download…';
          await new Promise(resolve=>setTimeout(resolve,1000));continue;
        }
        const percent=state.total_bytes?Math.floor(state.done_bytes/state.total_bytes*100):0;
        this.progress.textContent=state.phase==='done'?'Download complete.':state.phase==='failed'?state.error:state.phase==='cancelled'?'Download cancelled.':`${state.current_file||'Preparing download'} · ${percent}%`;
        if(['done','failed','cancelled'].includes(state.phase)){this.job=null;this.select.disabled=false;await this.load();if(state.phase==='done')await this.onInstalled?.();break;}
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
    }catch(e){this.progress.textContent=e.message||'Could not refresh model setup.';this.job=null;this.select.disabled=false;this.render();}
    finally{this.polling=false;}
  }
  resume(){this.closed=false;if(this.job)void this.poll();}
  close(){this.closed=true;this.panel.open=false;}
  dispose(){this.close();this.panel.ontoggle=null;}
}

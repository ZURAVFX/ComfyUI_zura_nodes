// Model packages are allowlisted by the backend. Fetching the list never starts a download.
const PACKAGE_IDS=['openjutsu_h3','wan_animate_2','wan21_relight','wan22_animate_core','wan22_pose','h3_birefnet','h3_head_acceleration','h3_head_adapters','h3_dmd_ref2va','h3_int8_vae','h3_control','h3_crossview','h3_first_last','ltx25_core','ltx25_full_vae','ltx25_refine','ltx25_sdr_hdr','ltx25_text_encoder','ltx25_text_int8','ltx25_clean_plate','ltx25_outpaint','ltx25_in_outpaint','ltx_control','flux2_klein_start'];
const ROUTE_NAMES={openjutsu:'OpenJutsu character replacement',wan2:'Wan Animate 2',wan:'Wan 2.2 character replacement',wan21_relight:'Wan 2.1 relight',h3_camera:'H3 camera angle',h3_head_swap:'H3 head swap',h3_viewport:'H3 viewport to final',h3:'MiniMax H3',local:'LTX 2.5',local_scene:'LTX 2.5 whole scene',h3_first_last:'H3 first & last frame',ltx_first_last:'LTX first & last frame',wan_first_last:'Wan first & last frame',h3_reference:'H3 reference video',ltx_outpaint_long:'LTX long frame extension',paintout_targeted:'Targeted paintout',paintout_full:'Full-scene clean plate',hdr_sdr:'SDR to HDR',hdr_native:'HDR to HDR'};
const NODE_PACKS=[
  {name:'ComfyUI-KJNodes',url:'https://github.com/kijai/ComfyUI-KJNodes',nodes:['PathchSageAttentionKJ','ImageResizeKJv2']},
  {name:'ComfyUI-Easy-Use',url:'https://github.com/yolain/ComfyUI-Easy-Use',nodes:['easy int']},
  {name:'ComfyUI-WanAnimatePreprocess',url:'https://github.com/kijai/ComfyUI-WanAnimatePreprocess',nodes:['OnnxDetectionModelLoader','PoseAndFaceDetection','DrawViTPose']},
  {name:'ComfyUI-CrossViewWarp',url:'https://github.com/cseti007/ComfyUI-CrossViewWarp',nodes:['CrossViewWarp']},
  {name:'ComfyUI-LTXVideo',url:'https://github.com/Lightricks/ComfyUI-LTXVideo',nodes:['LTXVInpaintPreprocess','LTXAddVideoICLoRAGuide','LTXAddVideoICLoRAGuideAdvanced','LTXICLoRALoaderModelOnly','LTXVLaplacianPyramidBlend','LTXVSetAudioRefTokens','LTXVLoadConditioning','LTXVHDRDecodePostprocess','LTXVVAEForceFloat32','LTXVTiledFusionSampler']},
];
const MANUAL_SOURCES={
  'wan_2.1_idv2v_int8_convrot.safetensors':{url:'https://huggingface.co/Kijai/Wan_ID_V2V_comfy',note:'The conversion publisher does not state a licence. Review its terms and the upstream ID-V2V licence.'},
  'lightx2v_i2v_14b_480p_cfg_step_distill_rank64_bf16.safetensors':{url:'https://huggingface.co/Kijai/WanVideo_comfy/tree/main/Lightx2v',note:'The exact converted file has no stated repository licence. Review its terms before use.'},
  'minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors':{url:'https://huggingface.co/RunningHubAI/rh-minimax-h3-dmd-ref2va-8step-turbo-pruned.safetensors-lora',note:'The publisher does not state a licence. Review its terms before use.'},
};
const gb=n=>`${(Number(n||0)/1e9).toFixed(2)} GB`;
const fileKey=file=>`${file.folder||''}/${file.filename||''}`.toLowerCase();
export class StudioModelDownloads {
  constructor(panel, request, onInstalled) {
    this.panel=panel;this.request=request;this.onInstalled=onInstalled;this.packages=[];this.job=null;this.closed=false;this.context=null;
    const floating=panel.classList.contains('zc-tool-popup');panel.classList.add('gs-model-downloads');
    panel.innerHTML=`<summary>${floating?'Models':'Download video models'}</summary><div class="gs-advanced-body${floating?' zc-tool-panel':''}"><label>Model package <select data-model-package aria-label="Model package"></select></label><div data-model-files></div><div data-model-actions></div><p data-model-progress role="status" aria-live="polite"></p></div>`;
    this.select=panel.querySelector('[data-model-package]');this.files=panel.querySelector('[data-model-files]');this.actions=panel.querySelector('[data-model-actions]');this.progress=panel.querySelector('[data-model-progress]');
    this.select.onchange=()=>this.render();panel.ontoggle=()=>{if(panel.open && !this.packages.length)this.load();};
  }
  el(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
  async load(){
    try{const data=await this.request('/model-downloads');this.packages=(data.models||[]).filter(p=>PACKAGE_IDS.includes(p.id));
      const previous=this.select.value;const overview=this.el('option','Current workflow');overview.value='__workflow__';this.select.replaceChildren(overview,...this.packages.map(p=>{const e=this.el('option',p.name);e.value=p.id;return e;}));if(previous==='__workflow__'||this.packages.some(p=>p.id===previous))this.select.value=previous;else if(!this.context&&this.packages.length)this.select.value=this.packages[0].id;if(this.missingContext)this.applyMissingContext();this.render();
    }catch(e){this.progress.textContent=e.message||'Could not load model packages.';}
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
      const blocked=pack.files.some(file=>file.incomplete);const button=this.el('button',this.job?'Download in progress':blocked?'Check existing files':pack.remaining_bytes?'Download missing files':'Files installed');button.type='button';button.disabled=!!this.job||blocked||!pack.remaining_bytes;button.onclick=()=>this.start(pack.id);row.append(button);this.files.append(row);
    }
    if(manual.length){this.files.append(this.el('p','Not included in an automatic download:'));for(const file of manual){const row=this.el('p',`${file.filename||file.path||'Unknown model file'}`),source=MANUAL_SOURCES[String(file.filename||'').toLowerCase()];if(source){row.append(' · ',this.link('Source',source.url),' · '+source.note);}this.files.append(row);}}
    if(missingNodes.length){
      this.files.append(this.el('p','Missing custom nodes:'));const unmapped=new Set(missingNodes);
      for(const pack of NODE_PACKS){const names=pack.nodes.filter(name=>unmapped.has(name));if(!names.length)continue;names.forEach(name=>unmapped.delete(name));const row=this.el('p','');row.append(this.link(pack.name,pack.url),' · '+names.join(', '));this.files.append(row);}
      if(unmapped.size)this.files.append(this.el('p',`Other nodes: ${[...unmapped].join(', ')}. Check the workflow setup guide for their packs.`));
      this.files.append(this.el('p','Install the required node packs, then restart ComfyUI.'));
    }
    if(this.job){const cancel=this.el('button','Cancel download');cancel.type='button';cancel.onclick=()=>this.request(`/model-downloads/${this.job}/cancel`,{}).catch(e=>this.progress.textContent=e.message);this.actions.append(cancel);}
  }
  render(){
    this.files.replaceChildren();this.actions.replaceChildren();if(this.select.value==='__workflow__'){this.renderWorkflow();return;}const pack=this.packages.find(p=>p.id===this.select.value);if(!pack)return;
    this.files.append(this.el('p',pack.note||''));
    if(pack.error){this.files.append(this.el('p',pack.error));return;}
    this.files.append(this.el('p',`${gb(pack.remaining_bytes)} to download`));
    for(const file of pack.files){const p=this.el('p',`${file.installed?'Installed':file.incomplete?'Existing file differs; check its version before moving it':'Needed'} · ${file.filename} · ${gb(file.size_bytes)}`);p.className='gs-note';this.files.append(p);}
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

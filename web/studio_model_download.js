import {groupMissingNodes} from './studio_node_setup.js';
import {ModelStorage} from './studio_model_storage.js';
import {ModelAccess,importModelFile} from './studio_model_access.js';
// Model packages are allowlisted by the backend. Fetching the list never starts a download.
const PACKAGE_IDS=['ltx_paint_vfx','panorama_hdri','ltx25_camera','panorama_geometry','openjutsu_h3','sam31','fasth3_draft','h3_reference_core','wan_animate_2','wan21_relight','wan22_animate_core','wan22_pose','wan22_style','wan22_first_last','h3_birefnet','h3_head_acceleration','h3_head_adapters','h3_taomate','h3_dmd_ref2va','h3_int8_vae','h3_control','h3_crossview','h3_first_last','h3_ripple','ltx_ripple','ltx_alpha','relayvsr_x2','ltx25_core','ltx25_full_vae','ltx25_refine','ltx25_sdr_hdr','ltx25_text_encoder','ltx25_text_int8','ltx25_clean_plate','ltx25_outpaint','ltx25_in_outpaint','ltx_control','flux2_klein_start','flux2_klein_9b','flux2_klein_9b_bf16','flux3_klein','flux3_klein_bf16','zimage_turbo','qwen2511','qwen21','flux2_dev','ph3_image_edit'];
const ROUTE_NAMES={panorama:'Change camera angle',openjutsu:'OpenJutsu character replacement',wan2:'Wan Animate 2',wan:'Wan 2.2 character replacement',wan21_relight:'Wan 2.1 relight',h3_camera:'H3 camera angle',h3_head_swap:'H3 head swap',h3_viewport:'H3 viewport to final',h3:'MiniMax H3',local:'LTX 2.5',local_scene:'LTX 2.5 whole scene',h3_first_last:'H3 first & last frame',ltx_first_last:'LTX first & last frame',wan_first_last:'Wan first & last frame',h3_reference:'H3 reference video',ltx_outpaint_hdr_long:'LTX long HDR frame extension',ltx_outpaint_hdr:'LTX HDR frame extension',ltx_outpaint_expand:'LTX frame extension',ltx_outpaint_black:'LTX black-area fill',ltx_outpaint_long:'LTX long frame extension',paintout_targeted:'Targeted paintout',paintout_full:'Full-scene clean plate',hdr_sdr:'SDR to HDR',hdr_native:'HDR to HDR',ltx_hdr_endpoints:'LTX native HDR first and last frame'};

const MANUAL_SOURCES={
  'yolox_l.onnx':{url:'https://huggingface.co/yzd-v/DWPose/blob/main/yolox_l.onnx',note:'DWPose body detector · 216.75 MB. Place this file at the location shown below.'},
  'dw-ll_ucoco_384_bs5.torchscript.pt':{url:'https://huggingface.co/hr16/DWPose-TorchScript-BatchSize5/blob/main/dw-ll_ucoco_384_bs5.torchscript.pt',note:'DWPose pose estimator · 135.06 MB. Place this file at the location shown below.'},
  'wan_2.1_idv2v_int8_convrot.safetensors':{url:'https://huggingface.co/Kijai/Wan_ID_V2V_comfy',note:'The conversion publisher does not state a licence. Review its terms and the upstream ID-V2V licence.'},
  'lightx2v_i2v_14b_480p_cfg_step_distill_rank64_bf16.safetensors':{url:'https://huggingface.co/Kijai/WanVideo_comfy/tree/main/Lightx2v',note:'The exact converted file has no stated repository licence. Review its terms before use.'},
  'minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors':{url:'https://huggingface.co/RunningHubAI/rh-minimax-h3-dmd-ref2va-8step-turbo-pruned.safetensors-lora',note:'The publisher does not state a licence. Review its terms before use.'},
};
const gb=n=>`${(Number(n||0)/1e9).toFixed(2)} GB`;
const shortGb=n=>{const v=Number(n||0);return v>=1e9?`${(v/1e9).toFixed(1)} GB`:v>=1e6?`${Math.ceil(v/1e6)} MB`:'';};
const fileKey=file=>`${file.folder||''}/${file.filename||''}`.replaceAll('\\','/').toLowerCase();
const leafKey=file=>String(file?.filename||file||'').replaceAll('\\','/').split('/').pop().toLowerCase();
const downloadSvg='<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.5v7.5m-3-3 3 3 3-3M3 13h10"/></svg>';

export const MODEL_OPTION_PACKAGES={
  local:['ltx25_core','ltx25_text_int8'],
  local_scene:['ltx25_core','ltx25_text_int8'],
  local_viewport:['ltx25_core','ltx25_text_int8','ltx_control'],
  ltx:['ltx25_core','ltx25_text_int8'],
  ltx_first_last:['ltx25_core','ltx25_text_int8'],
  ltx_director:['ltx25_core','ltx25_text_int8','ltx_control'],
  ltx_ripple:['ltx_ripple'],
  'relight-ltx':['ltx_ripple'],
  h3:['h3_reference_core','h3_dmd_ref2va'],
  openjutsu:['openjutsu_h3'],
  h3_viewport:['h3_reference_core','h3_dmd_ref2va','h3_control'],
  h3_camera:['h3_reference_core','h3_dmd_ref2va','h3_crossview','flux3_klein'],
  h3_head_swap:['h3_reference_core','h3_control','h3_birefnet','h3_head_acceleration','h3_head_adapters','h3_taomate'],
  h3_first_last:['h3_first_last','h3_dmd_ref2va'],
  h3_director:['h3_reference_core','h3_dmd_ref2va'],
  h3_reference:['h3_reference_core','h3_dmd_ref2va'],
  ref2va:['h3_reference_core','h3_dmd_ref2va'],
  viggle:['h3_reference_core'],
  fasth3_draft:['fasth3_draft'],
  h3_ripple:['h3_ripple'],
  'relight-h3':['h3_ripple'],
  wan:['wan22_animate_core','wan22_pose','wan22_style','sam31'],
  wan_first_last:['wan22_first_last'],
  wan2:['wan_animate_2','sam31'],
  wan21:['wan21_relight'],
  wan21_relight:['wan21_relight'],
  flux2:['flux2_klein_9b'],
  flux2bf16:['flux2_klein_9b_bf16'],
  klein9b:['flux2_klein_9b'],
  klein9b_start:['flux2_klein_start'],
  klein9bbf16:['flux2_klein_9b_bf16'],
  flux3:['flux3_klein'],
  flux3bf16:['flux3_klein_bf16'],
  flux3edit:['flux3_klein'],
  flux3editbf16:['flux3_klein_bf16'],
  zimage:['zimage_turbo'],
  qwen2511:['qwen2511'],
  qwen21:['qwen21'],
  qwen21edit:['qwen21'],
  flux2devedit:['flux2_dev'],
  ph3:['ph3_image_edit'],
  ph3edit:['ph3_image_edit'],
};
ROUTE_NAMES.image='Image generation';
ROUTE_NAMES.ltx_director='LTX 2.5 · Director';
ROUTE_NAMES.h3_director='MiniMax H3 · Director';
ROUTE_NAMES.ltx_performance_hdr='LTX performance + HDR delivery';
ROUTE_NAMES.h3_ripple='H3 Ripple';
ROUTE_NAMES.relayvsr_x2='Relay VSR 2×';
ROUTE_NAMES.ltx_ripple='LTX Ripple';
ROUTE_NAMES.ltx_alpha='Extract alpha';
ROUTE_NAMES.ltx_paint_vfx='Paint VFX';
ROUTE_NAMES.paint_vfx='Paint VFX';

export class StudioModelDownloads {
  constructor(panel, request, onInstalled) {
    this.panel=panel;this.request=request;this.onInstalled=onInstalled;this.packages=[];this.job=null;this.closed=false;this.context=null;this.uncertain=false;this.starting=false;this.pickers=new Set();
    const floating=panel.classList.contains('zc-tool-popup');panel.classList.add('gs-model-downloads');
    panel.innerHTML=`<summary>${floating?'Models':'Download models'}</summary><div class="gs-advanced-body${floating?' zc-tool-panel':''}"><label>Model package <select data-model-package aria-label="Model package"></select></label><div data-model-files></div><div data-model-actions></div><p data-model-progress role="status" aria-live="polite"></p></div>`;
    this.select=panel.querySelector('[data-model-package]');this.files=panel.querySelector('[data-model-files]');this.actions=panel.querySelector('[data-model-actions]');this.progress=panel.querySelector('[data-model-progress]');
    panel.addEventListener('keydown',event=>{if(event.key==='Escape'&&panel.open){panel.open=false;panel.querySelector('summary')?.focus();event.preventDefault();event.stopPropagation();}});
    this.select.onchange=()=>{if(!this.job){this.startIntent=null;this.retryRequest=null;this.accessFailure=null;}this.render();};panel.ontoggle=()=>{if(panel.open && !this.packages.length)this.load();};
    this.storage=new ModelStorage(panel.querySelector('.gs-advanced-body'),request,async()=>{await this.load();await this.onInstalled?.();});
    this.access=new ModelAccess(panel.querySelector('.gs-advanced-body'),request,()=>this.retryRequest?this.start(this.retryRequest):undefined);this.token=this.access.$('token');
  }
  el(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
  load(){
    if(this.cataloguePromise)return this.cataloguePromise;
    this.cataloguePromise=this.loadCatalogue().finally(()=>{this.cataloguePromise=null;});
    return this.cataloguePromise;
  }
  async loadCatalogue(){
    this.loadingCatalogue=true;
    try{const data=await this.request('/model-downloads');this.uncertain=false;this.packages=(data.models||[]).filter(p=>PACKAGE_IDS.includes(p.id));
      const previous=this.select.value;const overview=this.el('option','Current workflow');overview.value='__workflow__';this.select.replaceChildren(overview,...this.packages.map(p=>{const e=this.el('option',p.name);e.value=p.id;return e;}));if(previous==='__workflow__'||this.packages.some(p=>p.id===previous))this.select.value=previous;else if(!this.context&&this.packages.length)this.select.value=this.packages[0].id;if(this.missingContext)this.applyMissingContext();this.render();
      if(data.active?.id&&!this.job&&!this.closed){this.job=data.active.id;this.jobState=data.active;this.select.disabled=true;this.progress.textContent='Reconnecting to the existing download…';this.render();void this.poll();}
    }catch(e){this.progress.textContent=this.uncertain?'Could not confirm whether the download started. Check its status before trying again.':e.message||'Could not load model packages.';this.render();}
    finally{this.loadingCatalogue=false;this.renderQuick();}
  }
  setContext(context,keepMissing=false){
    if(!keepMissing)this.missingContext=null;
    const next=context&&Array.isArray(context.files)&&Array.isArray(context.missingNodes)?context:null;
    const changed=next?.route!==this.context?.route||JSON.stringify((next?.files||[]).map(fileKey))!==JSON.stringify((this.context?.files||[]).map(fileKey));
    if(changed&&!this.job){this.startIntent=null;this.retryRequest=null;this.accessFailure=null;this.progress.textContent='';}
    const previousRoute=this.context?.route;
    if(previousRoute!==next?.route&&!this.checkingSetup){this.setupCheck='';this.detailsOpen=false;}
    this.context=next;
    if(next&&!this.packages.length&&!this.loadingCatalogue)void this.load();
    if(next?.route!==previousRoute&&next&&this.packages.length&&!this.job)this.select.value='__workflow__';
    if(this.packages.length && this.select.value==='__workflow__')this.render();
    this.renderQuick();
  }
  setMissingContext(route,missing,label){
    this.missingContext=Array.isArray(missing)?{route,missing,label}:null;
    this.applyMissingContext();
  }
  applyMissingContext(){
    if(!this.missingContext){this.setContext(null);return;}
    const {route,missing,label}=this.missingContext,files=[],missingNodes=[];
    for(const name of missing){
      if(typeof name!=='string')continue;
      if(/\.(safetensors|onnx|pt|pth|ckpt|bin)$/i.test(name)){
        const match=this.packages.flatMap(pack=>pack.files||[]).find(file=>file.filename?.replaceAll('\\','/').split('/').pop().toLowerCase()===name.replaceAll('\\','/').split('/').pop().toLowerCase());
        files.push({folder:match?.folder||'',filename:match?.filename||name,ready:false});
      }else missingNodes.push(name);
    }
    this.setContext({route,files,missingNodes,label},true);
  }
  link(label,url){const link=this.el('a',label);link.href=url;link.target='_blank';link.rel='noopener noreferrer';return link;}
  workflowPlan(){
    const missing=(this.context?.files||[]).filter(file=>file.ready===false),remaining=new Set(missing.map(fileKey)),packs=[];
    while(remaining.size){
      const ranked=this.packages.filter(p=>!p.error&&!packs.includes(p)).map(pack=>({pack,count:(pack.files||[]).filter(f=>remaining.has(fileKey(f))).length})).filter(p=>p.count);
      ranked.sort((a,b)=>b.count-a.count||Number(a.pack.remaining_bytes||0)-Number(b.pack.remaining_bytes||0));
      if(!ranked.length)break;const pack=ranked[0].pack;packs.push(pack);for(const file of pack.files)remaining.delete(fileKey(file));
    }
    const needed=new Set(missing.map(fileKey)),files=[...new Map(packs.flatMap(p=>p.files.filter(f=>needed.has(fileKey(f))&&!f.installed)).map(f=>[fileKey(f),f])).values()];
    return {packs,files,keys:files.map(fileKey),manual:missing.filter(f=>remaining.has(fileKey(f))),bytes:files.reduce((n,f)=>n+Number(f.size_bytes||0),0),blocked:files.some(f=>f.incomplete)};
  }
  mountQuick(host){
    if(!host)return;
    if(!this.quick){
      this.quick=this.el('section','');this.quick.className='gs-model-quick';this.quick.hidden=true;this.quick.setAttribute('aria-label','Workflow model setup');
      this.quick.innerHTML='<div class="gs-model-quick-copy"><strong data-quick-title></strong><small data-quick-size></small></div><button type="button" data-quick-install></button><button type="button" data-quick-details>Setup details</button><button type="button" data-quick-refresh>Check setup</button><button type="button" data-quick-cancel hidden>Cancel install</button><progress hidden aria-label="Model installation progress"></progress><p data-quick-status role="status" aria-live="polite"></p><div class="gs-model-setup-details" data-quick-requirements hidden></div>';
      this.quick.querySelector('[data-quick-install]').onclick=()=>this.workflowPlan().files.length?this.startWorkflow():this.onInstalled?.();
      this.quick.querySelector('[data-quick-details]').onclick=()=>{
        if(this.inlineSetup){
          this.detailsOpen=!this.detailsOpen;
          this.renderQuick();
          return;
        }
        for(let parent=this.panel;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
        this.select.value='__workflow__';
        this.render();
      };
      this.quick.querySelector('[data-quick-refresh]').onclick=async()=>{
        if(this.inlineSetup)return this.checkSetup();
        await this.load();
        await this.onInstalled?.();
      };
      this.quick.querySelector('[data-quick-cancel]').onclick=()=>this.request(`/model-downloads/${this.job}/cancel`,{}).catch(e=>{this.progress.textContent=e.message;this.renderQuick();});
      this.quickStorage=new ModelStorage(this.quick,this.request,async()=>{await this.load();await this.onInstalled?.();});
      this.quickStorage.root.querySelector('summary').textContent='Model folders';
    }
    if(this.quick.parentNode!==host)host.prepend(this.quick);
  }
  jobMatchesPlan(plan){
    if(!this.job)return false;
    const ids=this.jobState?.model_ids||[this.jobState?.model_id];
    return !!plan?.packs?.some(pack=>ids.includes(pack.id));
  }
  jobLabel(){
    const ids=this.jobState?.model_ids||[this.jobState?.model_id];
    return ids.map(id=>this.packages.find(pack=>pack.id===id)?.name||id).filter(Boolean).join(' + ')||'Model download';
  }
  renderQuick(){
    if(!this.quick){const owner=this.panel.closest('.zf-page,.zo-page,.zh-page,.zpc-page,.zvfx-page,.zalpha-page,.zc-image-page')||this.panel.closest('#genj-studio')?.querySelector('.gs-workspace');this.mountQuick(owner?.querySelector('.zc-prompt-card,.zo-composer,.gs-composer,.zvfx-composer,.zalpha-composer,.zc-image-composer')||owner);}
    if(!this.quick)return;
    const plan=this.workflowPlan(),missing=this.context?.files?.some(f=>f.ready===false),nodes=this.context?.missingNodes?.length||0;
    this.quick.hidden=!this.job&&!this.starting&&!missing&&!nodes&&!this.setupCheck;
    this.quick.querySelector('[data-quick-title]').textContent=this.job?`Downloading ${this.jobLabel()}`:`${ROUTE_NAMES[this.context?.route]||'This mode'} · setup`;
    this.quick.querySelector('[data-quick-size]').textContent=!missing&&!this.job?(nodes?'Required extensions or features are missing.':'All required files and extensions are available.'):this.packages.length?`${plan.files.length} missing file${plan.files.length===1?'':'s'} · ${gb(plan.bytes)} to download${nodes?' · extensions also needed':''}${plan.manual.length?' · some files need manual setup':''}`:'Checking download sizes…';
    const button=this.quick.querySelector('[data-quick-install]');button.textContent=this.job||this.starting?'Installing…':this.loadingCatalogue&&!this.packages.length?'Checking models…':plan.blocked?'Check existing files':plan.files.length?`Install missing models · ${gb(plan.bytes)}`:'Refresh models';
    button.hidden=!missing&&!this.job;button.disabled=!!this.job||this.starting||this.uncertain||this.loadingCatalogue&&!this.packages.length||plan.blocked||!!plan.manual.length&&!plan.files.length;
    this.quickStorage.root.hidden=!missing;
    this.quick.querySelector('[data-quick-cancel]').hidden=!this.job;
    this.quick.querySelector('[data-quick-refresh]').disabled=!!this.job||this.starting||this.checkingSetup;
    this.quick.querySelector('[data-quick-refresh]').textContent=this.checkingSetup?'Checking…':'Check setup';
    this.renderQuickRequirements(plan);
    if(!this.quickAccess){this.quickAccess=this.el('button','Hugging Face access');this.quickAccess.type='button';this.quickAccess.onclick=()=>this.showAccess();this.quick.querySelector('[data-quick-status]').before(this.quickAccess);}
    this.quickAccess.hidden=!this.accessFailure&&!plan.files.some(file=>file.gated);
    this.quick.querySelector('[data-quick-status]').textContent=this.job&&!this.jobMatchesPlan(plan)?`${this.jobLabel()} � ${this.progress.textContent}. Cancel this download before installing the selected model.`:this.progress.textContent;
    if(this.setupCheck&&!this.job&&!this.starting)this.quick.querySelector('[data-quick-status]').textContent=this.setupCheck;
    const bar=this.quick.querySelector('progress');bar.hidden=!this.job;if(this.downloadTotal){bar.max=this.downloadTotal;bar.value=this.downloadDone||0;}else bar.removeAttribute('value');
    this.syncPickers();
  }
  async checkSetup(){
    if(this.checkingSetup)return;
    this.checkingSetup=true;
    const route=this.context?.route;
    this.setupCheck='Checking files and extensions…';
    this.progress.textContent='';
    this.renderQuick();
    try{
      await this.load();
      const result=await this.onInstalled?.();
      if(route&&route!==this.context?.route){this.setupCheck='';return;}
      if(result===null)throw Error('Could not check setup. Check the ComfyUI connection and try again.');
      const files=this.context?.files.filter(file=>file.ready===false).length||0;
      const nodes=this.context?.missingNodes.length||0;
      const pending=[files&&`${files} model file${files===1?'':'s'}`,nodes&&`${nodes} required feature${nodes===1?'':'s'}`].filter(Boolean);
      this.setupCheck=pending.length?`Still missing: ${pending.join(' and ')}.`:'Setup complete. This model is ready.';
      this.detailsOpen=pending.length>0;
      if(!nodes)this.rippleRestartNeeded=false;
    }catch(error){this.setupCheck=error.message;}
    finally{this.checkingSetup=false;this.renderQuick();}
  }
  renderQuickRequirements(plan){
    const panel=this.quick.querySelector('[data-quick-requirements]');
    const details=this.quick.querySelector('[data-quick-details]');
    details.textContent=this.detailsOpen?'Hide setup details':'Setup details';
    details.setAttribute('aria-expanded',String(!!this.detailsOpen));
    panel.hidden=!this.inlineSetup||!this.detailsOpen;
    if(panel.hidden)return;
    const {packs,unknown}=groupMissingNodes(this.context?.missingNodes||[]);
    panel.replaceChildren();
    for(const pack of packs){
      const row=this.el('div','');
      row.append(this.link(pack.guide?`${pack.name} installation guide`:pack.name,pack.guide||pack.registry||pack.url),this.el('p',pack.missing.join(', ')));
      if(pack.note)row.append(this.el('p',pack.note));
      if(pack.patch)row.append(this.link('Compatibility patch',pack.patch));
      if(pack.missing.includes('WN_RippleApply')&&this.installRippleExtension){
        const button=this.el('button',this.installingExtension?'Installing extension…':'Install WepeNerd extension');
        button.type='button';
        button.disabled=!!this.installingExtension||this.rippleRestartNeeded;
        button.onclick=()=>this.installRippleNodes();
        row.append(button);
      }
      panel.append(row);
    }
    for(const name of unknown)panel.append(this.el('p',name));
    for(const file of this.context?.files.filter(file=>file.ready===false)||[]){
      const row=this.el('div',file.filename);
      const pack=plan.packs.find(pack=>pack.files.some(item=>fileKey(item)===fileKey(file)));
      const item=pack?.files.find(item=>fileKey(item)===fileKey(file));
      if(item?.incomplete)row.append(this.el('p','An existing file differs from the published version. Check it in Model folders.'));
      const actions=item&&this.browserActions(pack,item);
      if(actions)row.append(actions);
      panel.append(row);
    }
    if(!panel.childNodes.length)panel.append(this.el('p','All required files and extensions are available.'));
  }
  async installRippleNodes(){
    if(this.installingExtension||this.rippleRestartNeeded)return;
    this.installingExtension=true;
    this.setupCheck='Installing the WepeNerd extension through ComfyUI Manager…';
    this.progress.textContent='';
    this.renderQuick();
    try{
      await this.installRippleExtension();
      this.rippleRestartNeeded=true;
      this.setupCheck='Extension installed. Save your work and restart ComfyUI, then choose Check setup.';
    }catch(error){this.setupCheck=error.message;}
    finally{this.installingExtension=false;this.renderQuick();}
  }
  setCatalogue(models){
    if(!Array.isArray(models))return;
    this.packages=models.filter(p=>PACKAGE_IDS.includes(p.id));
    if(this.missingContext)this.applyMissingContext();
    this.syncPickers();
  }
  planForOption(optionKey,{statusFiles,readyOverride,provider}={}){
    if(provider||['seedance','chatgpt','gemini'].includes(optionKey))return {provider:true,loaded:true,ready:true,packs:[],files:[],keys:[],bytes:0,blocked:false,gated:false};
    const ids=Array.isArray(optionKey)?optionKey:(MODEL_OPTION_PACKAGES[optionKey]||[optionKey]);
    const packs=ids.map(id=>this.packages.find(p=>p.id===id&&!p.error)).filter(Boolean);
    const statusMap=new Map();
    if(Array.isArray(statusFiles)){
      for(const sf of statusFiles)if(sf&&sf.filename)statusMap.set(leafKey(sf),sf.ready===true);
      const missingLeaves=new Set(statusFiles.filter(sf=>sf&&sf.ready===false).map(leafKey));
      for(const pack of this.packages){
        if(!pack.error&&!packs.includes(pack)&&(pack.files||[]).some(f=>missingLeaves.has(leafKey(f))))packs.push(pack);
      }
    }
    const filesMap=new Map(),activePacks=[];
    for(const pack of packs){
      let used=false;
      for(const file of pack.files||[]){
        const key=fileKey(file),leaf=leafKey(file);
        const alreadyReady=file.installed===true||statusMap.get(leaf)===true;
        if(!alreadyReady&&!filesMap.has(key)){filesMap.set(key,file);used=true;}
      }
      if(used)activePacks.push(pack);
    }
    const files=readyOverride===true?[]:[...filesMap.values()];
    const blocked=files.some(f=>f.incomplete);
    const loaded=this.packages.length>0||readyOverride===true;
    const ready=readyOverride===true||(loaded&&packs.length>0&&files.length===0&&!blocked);
    return {loaded,ready,packs:activePacks,files,keys:files.map(fileKey),bytes:files.reduce((sum,f)=>sum+Number(f.size_bytes||0),0),blocked,gated:files.some(f=>f.gated)};
  }
  async installOption(optionKey,opts={}){
    if(!this.packages.length&&!this.loadingCatalogue)await this.load();
    const plan=this.planForOption(optionKey,opts);
    if(!plan.files.length||plan.blocked)return;
    return this.start({model_ids:plan.packs.map(p=>p.id),file_keys:plan.keys});
  }
  attachPicker(select,options={}){
    if(!select)return null;
    for(const existing of this.pickers)if(existing.select===select)return existing;
    const picker=new StudioModelPicker(this,select,options);
    this.pickers.add(picker);
    return picker;
  }
  syncPickers(){for(const picker of this.pickers)picker.sync();}
  showAccess(){this.revealPanel?.();this.panel.hidden=false;for(let parent=this.panel;parent;parent=parent.parentElement){parent.hidden=false;if(parent.tagName==='DETAILS')parent.open=true;}this.access.root.open=true;void this.access.load();}
  browserActions(pack,file){
    if(file.installed||!file.browser_url||!file.gated&&!this.accessFailure)return null;
    const row=this.el('div','');row.className='zura-browser-model-actions';row.append(this.link('Download in browser',file.browser_url));
    const button=this.el('button','Install downloaded file');button.type='button';button.disabled=!!this.job||this.starting||file.incomplete;button.onclick=()=>this.importFile(pack,file);row.append(button);return row;
  }
  async importFile(pack,file){
    if(this.job||this.starting)return;this.starting=true;this.closed=false;this.render();
    try{this.progress.textContent='Choose the completed model download.';const data=await importModelFile('/zura/studio/model-downloads',pack.id,file,(done,total)=>{this.downloadDone=done;this.downloadTotal=total;this.progress.textContent=`Importing ${file.filename} · ${Math.floor(done/total*100)}%`;this.renderQuick();});if(data.cancelled){this.progress.textContent='';return;}this.job=data.id;this.select.disabled=true;this.starting=false;await this.poll();}
    catch(error){this.progress.textContent=error.message;await this.load();}
    finally{this.starting=false;this.render();}
  }
  async startWorkflow(){
    const plan=this.workflowPlan();if(!plan.files.length||plan.blocked)return;
    await this.start({model_ids:plan.packs.map(p=>p.id),file_keys:plan.keys});
  }
  renderWorkflow(){
    if(!this.context){this.files.append(this.el('p','Choose a workflow to see its setup.'));return;}
    const {route,files,missingNodes}=this.context;
    this.files.append(this.el('strong',this.context.label||ROUTE_NAMES[route]||'Current workflow'));
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
    const unique=new Map();for(const pack of packs)for(const file of pack.files)if(keys.has(fileKey(file))&&!file.installed&&!unique.has(fileKey(file)))unique.set(fileKey(file),Number(file.size_bytes)||0);
    const manual=missing.filter(file=>!matched.has(fileKey(file)));
    if(!missing.length)this.files.append(this.el('p','No missing model files reported for this workflow.'));
    else if(packs.length)this.files.append(this.el('p',`${gb([...unique.values()].reduce((sum,n)=>sum+n,0))} in available packages${manual.length?' · some files need manual setup':''}`));
    else this.files.append(this.el('p','The missing files below need manual setup.'));
    if(unique.size){const plan=this.workflowPlan(),install=this.el('button',this.job||this.starting?'Installing…':`Install missing models · ${gb(plan.bytes)}`);install.type='button';install.disabled=!!this.job||this.starting||this.uncertain||plan.blocked;install.onclick=()=>this.startWorkflow();this.files.append(install);}
    const detail=this.el('details',''),summary=this.el('summary','Files and model terms');detail.className='gs-model-file-details';detail.append(summary);if(packs.length)this.files.append(detail);
    for(const pack of packs){
      const neededBytes=pack.files.filter(file=>keys.has(fileKey(file))&&!file.installed).reduce((sum,file)=>sum+Number(file.size_bytes||0),0);
      const row=this.el('div','');row.className='gs-model-package';row.append(this.el('strong',pack.name),this.el('p',`${gb(neededBytes)} needed for this workflow${pack.note?' · '+pack.note:''}`));
      if(!pack.remaining_bytes)row.append(this.el('p','Files are present. Refresh setup or restart ComfyUI if the workflow still cannot see them.'));
      for(const file of pack.files.filter(file=>keys.has(fileKey(file))&&!file.installed)){const entry=this.el('p',`${file.incomplete?'Existing file differs from this download; check its version':'Needed'} · ${file.filename} · ${gb(file.size_bytes)}`);const actions=this.browserActions(pack,file);if(actions)entry.append(actions);row.append(entry);}
      for(const repo of [...new Set(pack.files.filter(file=>keys.has(fileKey(file))).map(file=>file.repo).filter(Boolean))]) row.append(this.link(`Review ${repo}`,`https://huggingface.co/${repo}`),' ');
      if(pack.license_url)row.append(this.link('Review licence',pack.license_url),' ');
      detail.append(row);
    }
    if(manual.length){this.files.append(this.el('p','Not included in an automatic download:'));for(const file of manual){const row=this.el('p',`${file.filename||file.path||'Unknown model file'}`),source=MANUAL_SOURCES[String(file.filename||'').toLowerCase()];if(source){row.append(' · ',this.link('Source',source.url),' · '+source.note);}if(file.path&&file.path!==file.filename)row.append(' Save to: '+file.path);this.files.append(row);}}
    if(missingNodes.length){
      this.files.append(this.el('p','Required ComfyUI nodes:'));const grouped=groupMissingNodes(missingNodes);
      for(const pack of grouped.packs){const row=this.el('p','');row.append(this.link(pack.name,pack.registry||pack.url),' · '+pack.missing.join(', '));this.files.append(row);if(pack.note){const note=this.el('p',pack.note);if(pack.patch)note.append(' ',this.link('OpenJutsu compatibility patch',pack.patch));this.files.append(note);}}
      if(grouped.unknown.length)this.files.append(this.el('p',`Other nodes: ${grouped.unknown.join(', ')}. Check the workflow setup guide for their packs.`));
      this.files.append(this.el('p',grouped.packs.length&&grouped.packs.every(pack=>pack.name==='Zura Nodes')&&!grouped.unknown.length?'These helpers are included with Zura Nodes and load automatically at startup. Save your work and restart ComfyUI, then choose Check setup. If they are still missing, update Zura Nodes and restart again.':'1. Open ComfyUI Manager and search for each extension above. 2. Install or update it. 3. Save your work and restart ComfyUI, return to this mode and choose Check setup.'));
    }
  }
  render(){
    this.renderQuick();
    const accessFiles=this.select.value==='__workflow__'?this.workflowPlan().files:this.packages.find(p=>p.id===this.select.value)?.files||[];this.access?.setFiles(accessFiles,this.accessFailure);
    this.files.replaceChildren();this.actions.replaceChildren();if(this.job){const cancel=this.el('button','Cancel download');cancel.type='button';cancel.onclick=()=>this.request(`/model-downloads/${this.job}/cancel`,{}).catch(e=>this.progress.textContent=e.message);this.actions.append(cancel);}if(this.uncertain){const check=this.el('button','Check download status');check.type='button';check.onclick=()=>this.load();this.actions.append(check);}if(this.select.value==='__workflow__'){this.renderWorkflow();return;}const pack=this.packages.find(p=>p.id===this.select.value);if(!pack)return;
    this.files.append(this.el('p',pack.note||''));
    if(pack.error){this.files.append(this.el('p',pack.error));return;}
    this.files.append(this.el('p',`${gb(pack.remaining_bytes)} to download`));
    for(const file of pack.files){const p=this.el('p',`${file.installed?'Installed':file.incomplete?'Existing file differs; check its version before moving it':'Needed'} · ${file.filename} · ${gb(file.size_bytes)}`);p.className='gs-note';const actions=this.browserActions(pack,file);if(actions)p.append(actions);this.files.append(p);}
    this.files.append(this.el('p','Review each source’s terms and access requirements before downloading:'));
    if(pack.license_url)this.files.append(this.link('Review licence',pack.license_url),document.createElement('br'));
    for(const repo of [...new Set(pack.files.map(file=>file.repo))]){const link=this.el('a',repo);link.href=`https://huggingface.co/${repo}`;link.target='_blank';link.rel='noopener noreferrer';this.files.append(link,document.createElement('br'));}
    const blocked=pack.files.some(file=>file.incomplete);const button=this.el('button',this.job||this.starting?'Download in progress':blocked?'Check existing files':pack.remaining_bytes?'Download missing files':'Files installed');button.type='button';button.disabled=!!this.job||this.starting||this.uncertain||blocked||!pack.remaining_bytes;button.onclick=()=>this.start(pack.id);this.actions.append(button);
  }
  async start(id){
    if(this.job||this.starting||this.uncertain)return;
    this.setupCheck='';
    const intent={};this.startIntent=intent;this.retryRequest=id;this.accessFailure=null;this.closed=false;this.starting=true;this.render();
    const ids=typeof id==='object'?id.model_ids:[id],keys=typeof id==='object'?id.file_keys:null;
    const selected=this.packages.filter(pack=>ids?.includes(pack.id)).flatMap(pack=>pack.files).filter(file=>!keys||keys.includes(fileKey(file)));
    const popup=this.access.reservePopup(selected);
    const allowed=await this.access.check(selected,{interactive:true,popup});
    if(this.startIntent!==intent){this.starting=false;this.render();return;}
    if(!allowed){this.starting=false;this.render();this.showAccess();return;}
    if(this.access?.root)this.access.root.open=false;
    const token=this.token?.value.trim();if(this.token)this.token.value='';
    try{this.progress.textContent='Starting download…';const result=await this.request('/model-downloads',{...(typeof id==='object'?id:{model_id:id}),...(token?{token}:{})});if(!result.id)throw new Error('Could not confirm the download started. Refresh setup before retrying.');this.job=result.id;this.jobState={model_ids:ids};this.starting=false;this.select.disabled=true;this.render();await this.poll();
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
        this.jobState=state;
        const percent=state.total_bytes?Math.floor(state.done_bytes/state.total_bytes*100):0;
        this.downloadTotal=state.total_bytes;this.downloadDone=state.done_bytes;
        this.progress.textContent=state.phase==='done'?'Download complete.':state.phase==='failed'?state.error:state.phase==='cancelled'?'Download cancelled.':`${state.current_file||'Preparing download'} · ${percent}%`;
        this.renderQuick();
        if(['done','failed','cancelled'].includes(state.phase)){if(state.phase==='failed'&&state.auth_required){this.accessFailure=state;this.showAccess();}else if(state.phase==='done')this.accessFailure=null;this.job=null;this.select.disabled=false;await this.load();await this.onInstalled?.();break;}
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
    }catch(e){this.progress.textContent=e.message||'Could not refresh model setup.';this.job=null;this.select.disabled=false;this.render();}
    finally{this.polling=false;}
  }
  resume(){this.closed=false;if(this.job)void this.poll();}
  close(){this.closed=true;this.panel.open=false;for(const picker of this.pickers)picker.close();}
  dispose(){for(const picker of this.pickers)picker.dispose();this.pickers.clear();this.access.dispose();this.close();this.panel.ontoggle=null;}
}

export class StudioModelPicker {
  constructor(downloads,select,options={}){
    this.downloads=downloads;this.select=select;this.options=options;
    this.doc=select.ownerDocument||globalThis.document;this.win=this.doc.defaultView||globalThis.window;
    this.host=select.closest('.zc-model-control,.zdir-model,label')||select.parentElement;
    if(!this.host)return;
    this.host.classList.add('zura-has-model-picker');
    this.inlineBtn=this.doc.createElement('span');
    this.inlineBtn.className='zura-inline-install-btn';
    this.inlineBtn.setAttribute('role','button');
    this.inlineBtn.setAttribute('tabindex','0');
    this.inlineBtn.dataset.inlineInstall='';
    this.inlineBtn.hidden=true;
    this.menu=this.doc.createElement('div');
    this.menu.className='zura-model-picker-menu zc-tool-panel zc-workflow-menu';
    this.menu.setAttribute('role','menu');
    this.menu.setAttribute('aria-label',select.getAttribute('aria-label')||'Choose model');
    this.menu.hidden=true;
    this.host.append(this.inlineBtn,this.menu);
    this.onHostClick=event=>{
      if(this.menu.contains(event.target))return;
      if(this.inlineBtn.contains(event.target)){
        event.preventDefault();event.stopPropagation();
        void this.installOption(this.select.value);
        return;
      }
      if(this.select.disabled||this.select.hidden)return;
      event.preventDefault();event.stopPropagation();
      this.toggle();
    };
    this.onMenuClick=event=>{
      event.stopPropagation();
      const install=event.target.closest('[data-install-model]');
      if(install){
        event.preventDefault();
        const val=install.dataset.installModel;
        this.pickOption(val,false);
        void this.installOption(val);
        return;
      }
      const cancel=event.target.closest('[data-cancel-model]');
      if(cancel){
        event.preventDefault();
        const dl=this.activeDownloads();
        if(dl?.job)void dl.request(`/model-downloads/${dl.job}/cancel`,{}).catch(()=>{});
        return;
      }
      const choice=event.target.closest('[data-pick-model]');
      if(choice&&choice.getAttribute('aria-disabled')!=='true'){
        event.preventDefault();
        this.pickOption(choice.dataset.pickModel,true);
      }
    };
    this.onOutside=event=>{
      if(this.menu.hidden)return;
      const path=event.composedPath?.()||[event.target];
      if(!path.some(node=>node===this.host||(node?.nodeType&&this.host.contains(node))))this.close();
    };
    this.onKeyDown=event=>{
      const target=event.target;
      if((event.key==='Enter'||event.key===' ')&&this.host.contains(target)&&target.matches?.('[role=button],[data-pick-model]')){event.preventDefault();event.stopPropagation();target.click();return;}
      if(target===this.select&&['Enter',' ','ArrowDown'].includes(event.key)){event.preventDefault();event.stopPropagation();this.open();this.menu.querySelector('[data-pick-model]:not([aria-disabled=true])')?.focus();return;}
      if(!this.menu.hidden&&this.menu.contains(target)&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();event.stopPropagation();const items=[...this.menu.querySelectorAll('[data-pick-model]:not([aria-disabled=true])')],index=items.indexOf(target),next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowUp'?-1:1)+items.length)%items.length;items[next]?.focus();return;}
      if(event.key==='Escape'&&!this.menu.hidden){
        this.close();this.select.focus();event.preventDefault();event.stopPropagation();
      }
    };
    this.host.addEventListener('click',this.onHostClick);
    this.menu.addEventListener('click',this.onMenuClick);
    this.doc.addEventListener('pointerdown',this.onOutside,true);
    this.doc.addEventListener('keydown',this.onKeyDown,true);
    this.sync();
  }
  activeDownloads(){return this.options.getDownloads?this.options.getDownloads():this.downloads;}
  resolve(value){
    const raw=this.options.resolveOption?this.options.resolveOption(value):{key:value};
    return typeof raw==='string'?{key:raw}:(raw||{key:value});
  }
  pickOption(value,closeMenu=true){
    if(this.select.disabled)return;
    if(this.select.value!==value){
      this.select.value=value;
      const Evt=this.win?.Event||globalThis.Event;
      if(Evt)this.select.dispatchEvent(new Evt('change',{bubbles:true}));
      else this.select.onchange?.({target:this.select});
    }
    if(closeMenu)this.close();
    else this.sync();
  }
  async installOption(value){
    const dl=this.activeDownloads();if(!dl)return;
    const info=this.resolve(value);
    if(typeof info.customInstall==='function'){await info.customInstall();this.sync();return;}
    await dl.installOption(info.key,info);
    this.sync();
  }
  toggle(){if(this.menu.hidden)this.open();else this.close();}
  open(){
    if(this.select.disabled)return;
    const dl=this.activeDownloads();
    if(dl&&!dl.packages.length&&!dl.loadingCatalogue)void dl.load().then(()=>this.sync());
    this.menu.hidden=false;
    this.host.classList.add('is-picker-open');
    this.sync();
    this.position();
  }
  close(){
    if(!this.menu)return;
    this.menu.hidden=true;
    this.host?.classList.remove('is-picker-open');
  }
  position(){
    if(this.menu.hidden||!this.host?.getBoundingClientRect||!this.win?.innerWidth)return;
    const anchor=this.host.getBoundingClientRect();
    const width=Math.min(316,this.win.innerWidth-24);
    const left=Math.max(12,Math.min(anchor.left,this.win.innerWidth-width-12));
    const spaceAbove=anchor.top-16,spaceBelow=this.win.innerHeight-anchor.bottom-16;
    const preferAbove=spaceBelow<220&&spaceAbove>spaceBelow;
    const maxH=Math.max(140,Math.min(340,preferAbove?spaceAbove:spaceBelow));
    Object.assign(this.menu.style,{
      position:'fixed',
      inset:'auto',
      left:`${left}px`,
      width:`${width}px`,
      maxHeight:`${maxH}px`,
      top:preferAbove?'auto':`${anchor.bottom+6}px`,
      bottom:preferAbove?`${this.win.innerHeight-anchor.top+6}px`:'auto',
      zIndex:'400',
    });
  }
  sync(){
    if(!this.host||!this.select)return;
    const dl=this.activeDownloads();

    const pct=dl?.downloadTotal?Math.floor((dl.downloadDone||0)/dl.downloadTotal*100):0;
    const selectedVal=this.select.value;
    const selectedInfo=selectedVal?this.resolve(selectedVal):null;
    const selectedPlan=selectedInfo&&dl?dl.planForOption(selectedInfo.key,selectedInfo):null;
    const activeJob=!!(dl?.jobMatchesPlan(selectedPlan)||(dl?.starting&&!dl?.job));
    if(activeJob){
      this.inlineBtn.hidden=false;
      this.inlineBtn.className='zura-inline-install-btn is-installing';
      this.inlineBtn.textContent=pct>0?`Installing ${pct}%`:'Installing…';
      this.inlineBtn.title='Model download in progress';
    }else if(selectedPlan&&!selectedPlan.ready&&(selectedPlan.files.length>0||typeof selectedInfo.customInstall==='function')){
      this.inlineBtn.hidden=false;
      this.inlineBtn.className='zura-inline-install-btn';
      this.inlineBtn.innerHTML=`${downloadSvg}<span>Install${selectedPlan.bytes?' · '+shortGb(selectedPlan.bytes):''}</span>`;
      this.inlineBtn.title=`Install missing models for the selected option (${gb(selectedPlan.bytes)})`;
    }else{
      this.inlineBtn.hidden=true;
    }
    if(this.menu.hidden)return;
    this.menu.replaceChildren();
    const options=[...this.select.querySelectorAll('option')].filter(o=>!o.hidden);
    for(const opt of options){
      const val=opt.value;if(!val)continue;
      const cleanLabel=String(opt.textContent||val).replace(/\s*·\s*Setup needed\s*$/i,'').trim();
      const info=this.resolve(val);
      const plan=dl?dl.planForOption(info.key,info):{loaded:false,ready:false,files:[],bytes:0};
      const row=this.doc.createElement('div');
      row.className='zura-model-picker-row';
      row.dataset.modelOption=val;
      const choice=this.doc.createElement('div');
      choice.className='zura-model-picker-choice';
      choice.setAttribute('role','menuitemradio');
      choice.setAttribute('tabindex',opt.disabled?'-1':'0');
      choice.setAttribute('aria-checked',String(val===selectedVal));
      if(opt.disabled)choice.setAttribute('aria-disabled','true');
      choice.dataset.pickModel=val;
      const nameSpan=this.doc.createElement('span');
      nameSpan.className='zura-model-picker-label';
      nameSpan.textContent=cleanLabel;
      const dot=this.doc.createElement('span');
      dot.className='zura-model-picker-dot';
      dot.setAttribute('aria-hidden','true');
      choice.append(dot,nameSpan);
      row.append(choice);
      const actionWrap=this.doc.createElement('div');
      actionWrap.className='zura-model-picker-action';
      if(activeJob&&val===selectedVal){
        const cancel=this.doc.createElement('span');
        cancel.className='zura-picker-install-btn is-installing';
        cancel.setAttribute('role','button');
        cancel.setAttribute('tabindex','0');
        cancel.dataset.cancelModel=val;
        cancel.textContent=pct>0?`Installing ${pct}%`:'Installing…';
        cancel.title='Click to cancel download';
        actionWrap.append(cancel);
      }else if(!plan.ready&&(plan.files.length>0||typeof info.customInstall==='function')){
        const btn=this.doc.createElement('span');
        btn.className='zura-picker-install-btn';
        btn.setAttribute('role','button');
        btn.setAttribute('tabindex','0');
        btn.dataset.installModel=val;
        const sizeText=shortGb(plan.bytes);
        btn.innerHTML=`${downloadSvg}<span>Install${sizeText?' · '+sizeText:''}</span>`;
        btn.title=`Install missing ${cleanLabel} models (${gb(plan.bytes)}) to ComfyUI's default models folder`;
        actionWrap.append(btn);
      }else if(plan.ready){
        const ready=this.doc.createElement('span');
        ready.className='zura-picker-ready-badge';
        ready.textContent=plan.provider?'Account':'Ready';
        actionWrap.append(ready);
      }
      row.append(actionWrap);
      this.menu.append(row);
    }
  }
  dispose(){
    this.close();
    this.host?.removeEventListener('click',this.onHostClick);
    this.doc?.removeEventListener('pointerdown',this.onOutside,true);
    this.doc?.removeEventListener('keydown',this.onKeyDown,true);
    this.inlineBtn?.remove();
    this.menu?.remove();
  }
}

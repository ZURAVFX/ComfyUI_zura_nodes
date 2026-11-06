// Shared by Image, Video and Paintout. These are paths on the ComfyUI host.
export class ModelStorage {
  constructor(host,request,onChange){
    this.request=request;this.onChange=onChange;this.busy=false;this.folders=[];this.target='';this.revision=0;
    this.root=document.createElement('details');this.root.className='zura-model-storage';
    this.root.innerHTML='<summary>Model storage</summary><div><p>Search all saved folders for existing models. Choose where new downloads go.</p><label>Download new models to<select data-storage-target aria-label="Download new models to"></select></label><ul data-storage-folders aria-label="Saved model folders"></ul><label>Add a models folder on the ComfyUI computer<input type="text" data-storage-path spellcheck="false" placeholder="Full path to your models folder" /></label><div class="zura-storage-actions"><button type="button" data-storage-save>Add folder</button></div><p data-storage-status role="status" aria-live="polite"></p></div>';
    host.append(this.root);this.$=key=>this.root.querySelector(`[data-storage-${key}]`);
    this.root.ontoggle=()=>{if(this.root.open)void this.load();};
    this.$('save').onclick=()=>this.add();
    this.$('target').onchange=()=>this.save(this.folders,this.$('target').value);
    this.$('path').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();void this.add();}});
    if(!document.querySelector('[data-zura-model-setup-style]')){const style=document.createElement('link');style.rel='stylesheet';style.href=new URL('./studio_model_setup.css',import.meta.url).href;style.dataset.zuraModelSetupStyle='';(document.head||host).append(style);}
  }
  async load(){
    if(this.busy)return;
    const revision=++this.revision;
    try{const info=await this.request('/model-folders');if(revision===this.revision)this.show(info);}
    catch(error){if(revision===this.revision)this.$('status').textContent=error.message||'Could not read model storage. Try again.';}
  }
  show(info){
    this.loaded=true;this.folders=info.folders|| (info.external?[info.external]:[]);this.target=info.external||'';
    const option=(label,value)=>{const e=document.createElement('option');e.textContent=label;e.value=value;return e;};
    this.$('target').replaceChildren(option(`ComfyUI folders · ${info.default}`,''),...this.folders.map(path=>option(path,path)));this.$('target').value=this.target;
    this.$('folders').replaceChildren(...this.folders.map(path=>{
      const row=document.createElement('li'),label=document.createElement('span'),remove=document.createElement('button');
      label.textContent=path;remove.type='button';remove.textContent='Remove';remove.setAttribute('aria-label',`Remove model folder ${path}`);
      remove.onclick=()=>this.save(this.folders.filter(value=>value!==path),this.target===path?'':this.target);
      row.append(label,remove);return row;
    }));
    this.$('folders').hidden=!this.folders.length;
    this.$('status').textContent=`New downloads: ${info.download_to||info.default}. All saved and configured ComfyUI folders are searched.`;
  }
  async add(){
    const path=this.$('path').value.trim();if(!path){this.$('status').textContent='Enter a full models folder path first.';return;}
    if(!this.loaded)await this.load();if(!this.loaded)return;
    if(await this.save([...new Set([...this.folders,path])],path))this.$('path').value='';
  }
  async save(folders,download_to){
    if(this.busy)return false;this.busy=true;++this.revision;this.controls(true);this.$('status').textContent='Checking folders and refreshing models…';
    try{const info=await this.request('/model-folders',{folders,download_to});this.show(info);try{await this.onChange?.();}catch{this.$('status').textContent='Folder saved. Model status could not refresh; choose Check setup to try again.';}return true;}
    catch(error){this.$('target').value=this.target;this.$('status').textContent=error.message||'Could not save model folders. Check their paths and permissions.';return false;}
    finally{this.busy=false;this.controls(false);}
  }
  controls(disabled){for(const node of this.root.querySelectorAll('button,select,input'))node.disabled=disabled;}
  open(){this.root.open=true;void this.load();}
}

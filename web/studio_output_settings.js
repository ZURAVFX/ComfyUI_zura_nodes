import {workspaceStorage} from './studio_storage.js';
import {EXRExportPreference} from './studio_exr_precision.js';
/** One saved delivery folder for the whole Studio, independent of each model. */
export class StudioOutputSettings {
  constructor(root, api, owner) {
    this.api=api;this.owner=owner;this.precision=new EXRExportPreference(workspaceStorage(owner));
    const panel=document.createElement('details');
    panel.className='zc-tool-popup zc-global-models zc-output-settings';
    panel.innerHTML='<summary>Settings</summary><form class="zc-tool-panel"><h3>Save your work</h3><label>Output folder<input name="folder" type="text" spellcheck="false" autocomplete="off" placeholder="Loading saved folder…"/></label><p>Finished images, videos and EXR archives are copied here. ComfyUI keeps the originals for your history.</p><div class="zc-output-actions"><button type="button" data-default>Use default</button><button type="submit" class="gs-primary">Save folder</button></div><p role="status" aria-live="polite"></p></form>';
    this.panel=panel;this.form=panel.querySelector('form');this.input=panel.querySelector('input');this.status=panel.querySelector('[role="status"]');
    const advanced=document.createElement('details');advanced.className='zc-output-advanced';
    advanced.innerHTML='<summary>Advanced export settings</summary><label>EXR precision<select aria-label="EXR precision"><option value="half">HALF · 16-bit float</option><option value="float32">FLOAT · 32-bit float</option></select></label><p>Controls saved EXR files. Model processing precision is separate.</p>';
    this.form.querySelector('.zc-output-actions').before(advanced);this.exrSelect=advanced.querySelector('select');this.exrSelect.value=this.exrStorage('acescg_exr');
    this.exrSelect.onchange=()=>{this.precision.set(this.exrSelect.value);this.exrSelect.value=this.exrStorage('acescg_exr');this.owner?.studio?.aeBridge?.updateMeta();};
    if(owner?.studio?.hdrTool)owner.studio.hdrTool.outputSettings=this;
    root.querySelector('.gs-top-actions').prepend(panel);
    panel.addEventListener('toggle',()=>{if(panel.open)void this.load();});
    this.form.onsubmit=event=>{event.preventDefault();void this.save(this.input.value);};
    panel.querySelector('[data-default]').onclick=()=>void this.save('');
    void this.load();
  }
  exrStorage(output){return this.precision.value(output);}
  preferSourcePrecision(bitDepth){this.precision.preferSource(bitDepth);this.exrSelect.value=this.exrStorage('acescg_exr');}
  exrLabel(){return 'EXR export '+(this.exrStorage('acescg_exr')==='float32'?'FLOAT':'HALF');}
  async request(path, data){
    const response=await this.api.fetchApi('/zura/studio/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    if(!response.ok){let message;try{message=(await response.json()).error;}catch{}throw Error(message||'Restart ComfyUI after this render to enable the new save controls.');}
    return response.json();
  }
  async load(){
    try{const settings=await this.request('output-settings');this.folder=settings.folder;if(this.input!==document.activeElement)this.input.value=settings.folder;this.status.textContent=settings.error||'Images / Videos / Sequences';}
    catch(error){this.status.textContent=error.message;}
  }
  async save(folder){
    const buttons=this.form.querySelectorAll('button');buttons.forEach(button=>button.disabled=true);this.status.textContent='Checking folder…';
    try{const settings=await this.request('output-settings',{folder});this.folder=settings.folder;this.input.value=settings.folder;this.status.textContent='Saved. New finished work will appear here.';}
    catch(error){this.status.textContent=error.message;}
    finally{buttons.forEach(button=>button.disabled=false);}
  }
  async saveImage(file, button){
    button.disabled=true;button.textContent='Saving…';
    try{const result=await this.request('save-output',{assets:[file]});button.textContent='Saved';button.title=result.saved[0];this.status.textContent='Saved to '+result.saved[0];return result.saved[0];}
    catch(error){button.textContent='Save image';throw error;}
    finally{button.disabled=false;}
  }
}

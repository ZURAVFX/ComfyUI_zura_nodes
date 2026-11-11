import {workspaceStorage} from './studio_storage.js';
import {openPanoramaEditor} from './studio_panorama_editor.js';
import {StudioModelDownloads} from './studio_model_download.js';

const KEY='zura-hdri-builder-v1',ERP='flux-2-klein-9B-360-erp-outpaint-lora_V1.safetensors';
const view=file=>'/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'});
const clone=value=>JSON.parse(JSON.stringify(value));
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function environmentGeneration(config){
  if(config.hdri_prepared)return config;
  const area=Math.max(256*512,Number(config.width||2048)*Number(config.height||1024));
  const height=Math.max(256,Math.min(2048,Math.round(Math.sqrt(area/2)/32)*32));
  return {...config,image_intent:'hdri',shape:'landscape',width:height*2,height,
    prompt:'Create a seamless 360-degree equirectangular environment panorama, full sphere, 2:1 aspect ratio, level horizon, matching left and right edges. Fill any green missing regions from the surrounding scene. Do not draw a border or labels. '+config.prompt};
}

/** Environment tools share the ordinary image canvas, providers and history. */
export class HDRIBuilder{
  constructor(owner){
    this.owner=owner;this.storage=workspaceStorage(owner);owner.imageIntent=owner.draft.image_intent||'standard';
    try{this.state=JSON.parse(this.storage.getItem(KEY))||{};}catch{this.state={};}
    this.state={yaw:0,exposure:0,view_exposure:0,lights:[],color_space:'auto',export_space:'linear_rec709',...this.state};
    this.serial=0;this.loading=false;this.previewing=false;this.placing=false;
    const doc=owner.root.ownerDocument;this.root=doc.createElement('section');this.root.className='zhe-controls';this.root.hidden=true;
    this.root.innerHTML=`<div class="zhe-main"><button type="button" data-hdri="import">Import HDRI</button><button type="button" data-hdri="compose">Compose 360°</button><label>Rotate<input data-hdri="yaw" type="number" min="-360" max="360" step="1" aria-label="Environment rotation in degrees"/></label><label>Light intensity<input data-hdri="exposure" type="number" min="-20" max="20" step="0.5" aria-label="Environment exposure in stops"/></label><label>View exposure<input data-hdri="view_exposure" type="number" min="-12" max="12" step="0.5" aria-label="Preview-only exposure in stops"/></label><button type="button" data-hdri="add">Add light</button><details class="zc-tool-popup zhe-export"><summary>EXR options</summary><div class="zc-tool-panel"><label>Source colour<select data-hdri="color_space"><option value="auto">Detect tags</option><option value="acescg">ACEScg</option><option value="linear_rec709">Linear sRGB / Rec.709</option><option value="srgb_display">sRGB</option></select></label><label>EXR colour<select data-hdri="export_space"><option value="linear_rec709">Linear sRGB / Rec.709</option><option value="acescg">ACEScg</option></select></label><p>32-bit float. View exposure changes the preview only.</p></div></details><button type="button" class="gs-primary" data-hdri="export">Save EXR</button><a data-hdri="download" download hidden>Download EXR</a><input type="file" data-hdri="file" accept="image/*,.exr,.hdr,.tif,.tiff" hidden/></div>
      <div class="zhe-lights" data-hdri="light-row" hidden><label>Light<select data-hdri="light"></select></label><label>Colour<input data-hdri="color" type="color" value="#ffffff"/></label><label>Stops<input data-hdri="stops" type="number" min="-10" max="24" step="0.5"/></label><label>Size °<input data-hdri="radius" type="number" min="0.1" max="90" step="0.5"/></label><label>Azimuth<input data-hdri="azimuth" type="number" step="1"/></label><label>Elevation<input data-hdri="elevation" type="number" min="-90" max="90" step="1"/></label><button type="button" data-hdri="delete">Remove light</button></div><div class="zhe-feedback"><span data-hdri="range">360° / 2:1 environment</span><span data-hdri="status" role="status" aria-live="polite"></span><details data-hdri="setup" class="zc-tool-popup"></details></div>`;
    owner.root.querySelector('.zc-image-composer').prepend(this.root);
    this.setup=new StudioModelDownloads(this.$('setup'),(path,body)=>owner.fetch('/zura/studio'+path,body),()=>{this.modelChecked=null;void owner.loadModels();this.sync();});
    this.setup.mountQuick(this.root.querySelector('.zhe-feedback'));
    for(const key of ['yaw','exposure','view_exposure','color_space','export_space']){this.$(key).value=this.state[key];this.$(key).onchange=()=>{this.state[key]=key.includes('space')?this.$(key).value:Number(this.$(key).value);this.changed();};}
    this.$('import').onclick=()=>this.$('file').click();this.$('file').onchange=event=>{const file=event.target.files?.[0];event.target.value='';if(file)void this.import(file);};
    this.$('compose').onclick=()=>void this.compose();this.$('export').onclick=()=>void this.export();
    this.$('add').onclick=async()=>{if(this.state.lights.length>=16)return;if(this.owner.imageArea?.editing)await this.owner.imageArea.finishEditor();this.placing=!this.placing;this.message(this.placing?'Click the panorama to place a light. Escape cancels.':'');};
    this.$('light').onchange=()=>{this.selected=this.$('light').value;this.renderLights();};
    for(const key of ['stops','radius','azimuth','elevation','color'])this.$(key).oninput=()=>{const light=this.light();if(!light)return;if(key==='color')light.color=this.$(key).value.match(/\w\w/g).map(hex=>parseInt(hex,16)/255);else light[key]=Number(this.$(key).value);this.changed();};
    this.$('delete').onclick=()=>{this.state.lights=this.state.lights.filter(light=>light.id!==this.selected);this.selected=this.state.lights[0]?.id;this.renderLights();this.changed();};
    this.pointer=event=>this.placeLight(event);owner.$('gallery').addEventListener('pointerdown',this.pointer,true);
    owner.root.addEventListener('keydown',event=>{if(event.key==='Escape'&&this.placing){this.placing=false;this.message('');event.preventDefault();}});
  }
  $(key){return this.root.querySelector('[data-hdri="'+key+'"]');}
  active(){return this.owner.mode==='image'&&this.owner.imageIntent==='hdri';}
  light(){return this.state.lights.find(light=>light.id===this.selected)||this.state.lights[0];}
  message(text=''){this.$('status').textContent=text;}
  source(){const o=this.owner,item=o.items[o.selectedImage];if(item?.hdri_source_id)return{source_id:item.hdri_source_id,color_space:this.state.color_space};if(item?.file)return{file:item.file,color_space:'srgb_display'};const ref=o.references[0];return ref?{file:{...ref,type:'input'},color_space:'srgb_display'}:null;}
  save(){try{this.storage.setItem(KEY,JSON.stringify(this.state));}catch{this.message('Could not save the environment controls.');}}
  changed(){this.save();this.serial++;clearTimeout(this.debounce);this.debounce=setTimeout(()=>void this.preview(),160);}
  sync(){
    const o=this.owner,active=this.active();this.root.hidden=!active;if(!active){this.placing=false;return;}
    if(o.studio.aeBridge&&!o.studio.aeBridge.closed){this.root.hidden=true;o.imageIntent='standard';o.message('Leave the AE session to build a panorama or HDRI. This operation changes the source raster.');return;}
    o.imageTask.querySelector('[data-image-operation-label]').textContent='Panorama / HDRI';
    for(const button of o.imageTask.querySelectorAll('[data-image-operation]')){const chosen=button.dataset.imageOperation==='hdri';button.setAttribute('aria-pressed',String(chosen));button.setAttribute('aria-checked',String(chosen));}
    const shapes=o.root.querySelector('.zc-shapes');if(shapes)shapes.hidden=true;o.imageSizeRatio=2;
    const key=JSON.stringify(this.source());if(key!==this.sourceKey&&!this.loading){this.sourceKey=key;this.previewURL=null;this.meta=null;this.serial++;clearTimeout(this.debounce);this.debounce=setTimeout(()=>void this.preview(),0);}
    if(this.modelChecked!==o.$('model').value){this.modelChecked=o.$('model').value;void this.checkModels();}
    this.$('add').disabled=!this.source()||this.meta?.is_erp!==true||this.loading;this.$('compose').disabled=!this.source()||this.loading;this.$('export').disabled=!this.source()||this.loading||this.meta?.is_erp===false;
    const image=o.$('gallery').querySelector('figure');if(this.previewURL&&image?.querySelector('img'))image.querySelector('img').src=this.previewURL;const save=image?.querySelector('[data-save-image]');if(save)save.hidden=true;
    const download=image?.querySelector('figcaption a[download]');if(download)download.textContent='Download preview';
    this.renderLights();
  }
  renderLights(){const selected=this.light();this.$('light-row').hidden=!selected;this.$('light').innerHTML=this.state.lights.map((light,index)=>`<option value="${escape(light.id)}" ${light===selected?'selected':''}>Light ${index+1}</option>`).join('');if(!selected)return;for(const key of ['stops','radius','azimuth','elevation'])if(this.$(key)!==document.activeElement)this.$(key).value=selected[key];this.$('color').value='#'+selected.color.map(c=>Math.round(c*255).toString(16).padStart(2,'0')).join('');}
  async preview(){
    if(!this.active()||!this.source())return;if(this.previewing){this.pending=true;return;}
    this.previewing=true;const revision=this.serial,source=this.source();
    try{const result=await this.owner.fetch('/zura/studio/hdri/preview',{...source,...this.state});if(revision!==this.serial||!this.active())return;this.meta={...result,is_erp:true};this.previewURL=this.owner.api.apiURL(view(result.file))+'&hdri='+revision;const image=this.owner.$('gallery').querySelector('figure img');if(image)image.src=this.previewURL;this.$('range').textContent=(result.source_hdr||result.hdr_range?'HDR lighting':'SDR panorama')+' · '+result.width+' × '+result.height+' · SDR preview';this.message('');this.$('export').disabled=false;this.$('add').disabled=false;}
    catch(error){if(revision===this.serial){this.meta={is_erp:false};this.message(error.message);this.$('export').disabled=true;}}
    finally{this.previewing=false;if(this.pending){this.pending=false;void this.preview();}}
  }
  async checkModels(){
    if(this.checking)return this.checking;
    const work=(async()=>{try{const [info,pano]=await Promise.all([this.owner.fetch('/object_info/LoraLoaderModelOnly'),this.owner.fetch('/object_info/PanoramaStudio')]),field=info.LoraLoaderModelOnly?.input?.required?.lora_name,options=Array.isArray(field?.[0])?field[0]:field?.[1]?.options||[];this.adapter=options.find(name=>name.replaceAll('\\','/').split('/').at(-1)===ERP)||null;const model=this.owner.$('model').value,needed=['flux2','flux2bf16'].includes(model)||model.startsWith('klein9b');this.setup.setMissingContext('hdri',[...(needed&&!this.adapter?[ERP]:[]),...(!pano.PanoramaStudio?['PanoramaStudio']:[])],'Panorama / HDRI');}catch(error){this.message(error.message);}})();
    this.checking=work;try{return await work;}finally{if(this.checking===work)this.checking=null;}
  }
  async uploadReference(file,width,height){const form=new FormData();form.append('image',file,file.name);form.append('subfolder','zura_hdri/guides');form.append('type','input');const response=await this.owner.api.fetchApi('/upload/image',{method:'POST',body:form});if(!response.ok)throw Error('Could not prepare the panorama guide.');const ref=await response.json();return{file:[ref.subfolder,ref.name].filter(Boolean).join('/'),filename:ref.name,subfolder:ref.subfolder||'',name:file.name,width,height};}
  async import(file){
    if(this.loading||this.owner.job||this.owner.submitting)return;this.loading=true;this.message('Loading environment…');
    try{const form=new FormData();form.append('file',file,file.name);const response=await this.owner.api.fetchApi('/zura/studio/hdri/import?color_space='+this.state.color_space,{method:'POST',body:form});const result=await response.json();if(!response.ok)throw Error(result.error||'Could not read the environment.');await this.owner.setImageOperation('edit',{useCanvas:false});this.owner.imageIntent='hdri';const proxy=await this.owner.api.fetchApi(view(result.file));const ref=await this.uploadReference(new File([await proxy.blob()],'Environment preview.png',{type:'image/png'}),result.file.width,result.file.height);this.owner.references=[ref];this.owner.editMainMissing=false;this.owner.imageArea?.reset();this.owner.items.unshift({file:result.file,model:'HDRI preview',prompt:file.name,hdri_source_id:result.source_id,source_hdr:result.source_hdr});this.owner.selectedImage=0;this.owner.save();this.owner.renderGallery();this.owner.render();}
    catch(error){this.message(error.message);}finally{this.loading=false;this.sourceKey=null;this.sync();}
  }
  async compose(){
    if(this.loading||!this.source())return;this.loading=true;this.message('Opening panorama composer…');
    try{const source=this.source(),prepared=await this.owner.fetch('/zura/studio/hdri/scene',source);this.editor=await openPanoramaEditor({app:this.owner.app,state:prepared.state,output:prepared.ui,environment:true,sky:{file:prepared.source_file,port:prepared.port},onCancel:()=>{this.editor=null;this.message('');},onError:error=>this.message(error.message),onApply:async state=>{this.editor=null;const result=await this.owner.fetch('/zura/studio/hdri/scene',{...source,state});await this.useComposition(result);}});this.message('');}
    catch(error){this.message(error.message);}finally{this.loading=false;this.sync();}
  }
  async useComposition(result){const response=await this.owner.api.fetchApi(view(result.file));if(!response.ok)throw Error('Could not read the composed panorama.');const ref=await this.uploadReference(new File([await response.blob()],'Panorama guide.png',{type:'image/png'}),result.file.width||result.width,result.file.height||result.height);await this.owner.setImageOperation('edit',{useCanvas:false});this.owner.imageIntent='hdri';this.owner.references=[ref];this.owner.editMainMissing=false;this.owner.imageArea?.reset();this.owner.$('shape').value='landscape';this.owner.$('width').value=result.width;this.owner.$('height').value=result.height;if(this.owner.models.some(model=>model.id==='klein9b'&&model.ready))this.owner.$('model').value='klein9b';this.owner.items.unshift({file:result.file,model:'Panorama guide',prompt:'Composed panorama'});this.owner.selectedImage=0;this.owner.save();this.owner.renderGallery();this.owner.render();this.message('Describe the surrounding scene, then generate to fill the missing areas.');}
  async prepareConfig(config){
    if(config.image_intent!=='hdri')return config;
    const result=environmentGeneration(config);
    if(!result.hdri_prepared&&result.references[0]&&result.references[0].width!==2*result.references[0].height){const scene=await this.owner.fetch('/zura/studio/hdri/scene',{file:{...result.references[0],type:'input'},color_space:'srgb_display'});const response=await this.owner.api.fetchApi(view(scene.file));result.references=[await this.uploadReference(new File([await response.blob()],'Panorama layout.png',{type:'image/png'}),scene.file.width||scene.width,scene.file.height||scene.height),...result.references.slice(1)];result.edit_area=null;}
    if(['flux2','flux2bf16'].includes(result.model)||result.model.startsWith('klein9b')){
      await this.checkModels();if(!this.adapter){this.setup.panel.open=true;throw Error('Install the 360° panorama adapter below, or choose another image model.');}
      if(!result.loras.some(lora=>lora.name.endsWith(ERP))){if(result.loras.length>=4)throw Error('Use at most three other LoRAs with the panorama adapter.');result.loras=[...result.loras,{name:this.adapter,strength:.9,confirm_unknown:true}];}
    }
    result.hdri_prepared=true;Object.assign(config,result);return config;
  }
  async export(){if(this.loading||!this.source())return;this.$('export').disabled=true;this.message('Saving float EXR…');try{const result=await this.owner.fetch('/zura/studio/hdri/export',{...this.source(),...this.state});const saved=await this.owner.fetch('/zura/studio/save-output',{assets:[result.file]});this.$('download').href=this.owner.api.apiURL(view(result.file));this.$('download').download=result.file.filename;this.$('download').hidden=false;this.message(saved.saved?.[0]?'Saved to '+saved.saved[0]:'EXR ready to download.');}catch(error){this.message(error.message);}finally{this.$('export').disabled=false;}}
  placeLight(event){if(!this.active()||!this.placing||this.meta?.is_erp===false)return;const image=event.target.closest('figure img');if(!image)return;event.preventDefault();event.stopImmediatePropagation();const rect=image.getBoundingClientRect(),ratio=image.naturalWidth/image.naturalHeight||2,width=Math.min(rect.width,rect.height*ratio),height=width/ratio,left=rect.x+(rect.width-width)/2,top=rect.y+(rect.height-height)/2,u=(event.clientX-left)/width,v=(event.clientY-top)/height;if(u<0||u>1||v<0||v>1)return;const light={id:crypto.randomUUID(),azimuth:u*360-180-this.state.yaw,elevation:90-v*180,radius:5,stops:6,color:[1,1,1]};this.state.lights.push(light);this.selected=light.id;this.placing=false;this.renderLights();this.changed();}
  close(){this.editor?.cancel();this.editor=null;clearTimeout(this.debounce);this.setup.close();}
}

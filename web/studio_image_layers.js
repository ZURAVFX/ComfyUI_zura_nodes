import {PaintoutEditor} from './paintout_studio/paintout_editor.js';
import {PlateSurface} from './studio_plate_surface.js';
import {imageAreaSourceKey} from './studio_image_area.js';
const copy=value=>structuredClone(value);
const reference=file=>{if(!file)return null;const path=typeof file.file==='string'?file.file:[file.subfolder,file.filename].filter(Boolean).join('/'),parts=path.replaceAll('\\','/').split('/'),filename=parts.pop(),folder=file.subfolder??parts.join('/'),subfolder=typeof folder==='string'?folder.replaceAll('\\','/'):folder;
 if(typeof subfolder!=='string'||subfolder.startsWith('/')||subfolder.includes(':')||subfolder.includes('\0')||subfolder.split('/').some(part=>part==='.'||part==='..'))throw Error('Choose a valid stored media reference.');
 return {filename:file.filename||filename,subfolder,type:file.type||'input'};};
const identity=file=>{const value=reference(file);return value?`${value.type}:${value.subfolder}/${value.filename}`:'';};
const url=file=>'/view?'+new URLSearchParams(reference(file));
const normal=config=>config.operation==='edit'&&config.image_intent!=='hdri'&&!config.ripple_guide;
/** Normal image edits share Paintout's controls and CPU layer compositing. */
export class StudioImageLayers{
 constructor(owner){
  this.owner=owner;this.closed=false;this.busy=false;this.epoch=0;this.layerDisclosureState=new Map();const doc=owner.root.ownerDocument;
  this.host=doc.createElement('section');this.host.className='zi-image-layers zpx-side zplate-sidebar';this.host.hidden=true;this.empty=doc.createElement('div');this.empty.className='zi-image-layers-empty';this.empty.innerHTML='<strong>Layers</strong><p>New edits appear here as layers. Earlier flattened results have no editable layer data.</p>';this.panel=doc.createElement('section');this.panel.className='zp-editor-paint-layers';this.panel.setAttribute('aria-label','Image edit layers');this.host.append(this.empty,this.panel);owner.$('gallery').after(this.host);
  for(const path of ['./paintout_studio/paintout_editor.css','./studio_plate_surface.css','./studio_image_layers.css']){const href=new URL(path,import.meta.url).href;if(![...doc.querySelectorAll('link[rel=stylesheet]')].some(link=>link.href===href)){const css=doc.createElement('link');css.rel='stylesheet';css.href=href;doc.head.append(css);}}
  this.renderer={layersPanel:this.panel,candidate:null,ensureLayers:anchor=>anchor.layers,w:{thumbnail:file=>owner.api.apiURL(url(file))},
   adjustPaintLayer:(id,change)=>this.adjust(id,change),expandPaintLayer:(id,value)=>this.adjust(id,{expand_pixels:value}),blendPaintLayer:(id,value)=>this.adjust(id,{blend_pixels:value}),brightnessPaintLayer:(id,value)=>this.adjust(id,{brightness_ev:value}),movePaintLayer:(id,delta)=>this.move(id,delta),removePaintLayer:id=>this.remove(id)};
  this.guardDownload=event=>{if(this.busy&&event.target.closest('[download]')){event.preventDefault();event.stopPropagation();owner.message('Wait for the image layers to finish updating.');}};owner.$('gallery').addEventListener('click',this.guardDownload,true);
  const close=owner.close;if(typeof close==='function')owner.close=(...args)=>{this.closed=true;++this.epoch;this.host.remove();owner.$('gallery').removeEventListener('click',this.guardDownload,true);return close.apply(owner,args);};
  this.surface={root:owner.root,$:key=>key==='layers'?this.panel:null,layerDisclosureState:this.layerDisclosureState,w:{editor:{selected:()=>this.current()?.image_layers,movePaintLayer:(id,delta)=>this.move(id,delta)},busy:()=>this.isBusy()}};
 }
 isBusy(){const o=this.owner;return this.busy||!!(o.job||o.pendingSubmission||o.submitting||o.uploading);}
 current(){if(this.closed)return null;const o=this.owner,item=o.items?.[o.selectedImage],stack=item?.image_layers,key=identity(o.references?.[0]);return o.mode==='image'&&o.imageOperation==='edit'&&!o.rippleImage?.request&&(item?.outpaint_guide||null)===(o.outpaintGuide?.request?.id||null)&&stack?.schemaVersion===1&&(key===identity(stack.source)||key===identity(stack.conditioningInput))?item:null;}
 generationBase(config){
  if(!normal(config)||!config.references?.[0])return null;const selected=this.current(),stack=selected?.image_layers,key=identity(config.references[0]);
  if(stack&&(key===identity(stack.conditioningInput)||key===identity(stack.source)))return copy(stack);
  const metadata=copy(config.references[0]),original=metadata.processingView?.originalSource||metadata;
  return {schemaVersion:1,id:crypto.randomUUID(),source:reference(metadata),source_colour:'srgb_display',originalSourceMetadata:metadata,originalMaster:copy(original.master||original.native_hdr||original.file||reference(original)),width:metadata.width||config.width,height:metadata.height||config.height,layers:[]};
 }
 originalSourceMetadata(){const stack=this.current()?.image_layers;return stack?.originalSourceMetadata?copy(stack.originalSourceMetadata):null;}
 async request(stack,layers){
  const result=await this.owner.fetch('/zura/studio/image-layers/compose',{schemaVersion:1,source:stack.source,source_colour:stack.source_colour,...(stack.source_sha256?{expected_source_sha256:stack.source_sha256}:{}),layers:layers.map(layer=>({id:layer.id,file:reference(layer.file),mask:layer.layer_mask?reference(layer.layer_mask):null,colour_space:layer.colour_space,enabled:layer.enabled!==false,opacity:layer.opacity??1,expand_pixels:layer.expand_pixels||0,blend_pixels:layer.blend_pixels||0,brightness_ev:layer.brightness_ev||0})),width:stack.width,height:stack.height,...(stack.delivery?{delivery:stack.delivery}:{})});
  if(result.hasAlpha!==false)throw Error('The image layer master is not a verified opaque RGB result.');
  if(!/^[a-f0-9]{64}$/.test(result.source_sha256||'')||result.colour?.encoding!=='srgb_display'||result.colour?.sceneLinear!==false)throw Error('The image layer source and colour identity could not be verified.');
  if(result.source_sha256&&stack.source_sha256&&result.source_sha256!==stack.source_sha256)throw Error('The original image changed. Start a new edit.');
  const size=stack.delivery||stack;if((result.sourceWidth??stack.width)!==stack.width||(result.sourceHeight??stack.height)!==stack.height||result.width!==size.width||result.height!==size.height||!result.master?.filename||result.master.type!=='output'||!result.preview?.filename||!Array.isArray(result.applied)||result.applied.length!==layers.length)throw Error('The image layer composite could not be verified. Your previous result is retained.');
  for(let i=0;i<layers.length;i++){const read=result.applied[i],layer=layers[i];for(const [key,value]of Object.entries({id:layer.id,enabled:layer.enabled!==false,opacity:layer.opacity??1,expand_pixels:layer.expand_pixels||0,blend_pixels:layer.blend_pixels||0,brightness_ev:layer.brightness_ev||0}))if(read[key]!==value)throw Error('The saved layer settings differ from the requested composite. Your previous result is retained.');}
  return result;
 }
 async conditioning(result){
  if(result.conditioningInput?.filename&&result.conditioningInput.type==='input')return result.conditioningInput;
  const response=await this.owner.api.fetchApi(url(result.canonicalPreview||result.preview));if(!response.ok)throw Error('Could not prepare the current composite for the next edit.');const blob=await response.blob(),form=new FormData();form.append('image',blob,'image_layers_'+crypto.randomUUID()+'.png');form.append('subfolder','zura_images/layers');form.append('type','input');
  const uploaded=await this.owner.api.fetchApi('/upload/image',{method:'POST',body:form}),file=await uploaded.json();if(!uploaded.ok||!file.name)throw Error('Could not retain the layer composite as an image input.');return {filename:file.name,subfolder:file.subfolder||'',type:'input',file:[file.subfolder,file.name].filter(Boolean).join('/')};
 }
 async accept(config,file){
  const stack=config.image_layer_base;if(!normal(config)||!stack)return {...config,file};
  const next=copy(stack);if(config.image_delivery_size)next.delivery=copy(config.image_delivery_size);const mask=config.edit_area?.enabled?config.edit_area.mask:null;
  next.layers.push({id:crypto.randomUUID(),file:reference(file),layer_mask:mask?reference(mask):null,colour_space:'srgb_display',method:'image',prompt:config.prompt,enabled:true,opacity:1,expand_pixels:0,blend_pixels:0,brightness_ev:0});
  const result=await this.request(next,next.layers);next.conditioningInput=await this.conditioning(result);if(result.source_sha256)next.source_sha256=result.source_sha256;
  return {...config,file:result.preview,master:result.master,preview:result.preview,hasAlpha:false,canonicalMaster:result.canonicalMaster||result.master,canonicalPreview:result.canonicalPreview||result.preview,colour:result.colour,width:result.width,height:result.height,image_layers:next};
 }
 selectInput(item){
  const stack=item?.image_layers;if(!stack?.conditioningInput||(item.outpaint_guide||null)!==(this.owner.outpaintGuide?.request?.id||null))return;const o=this.owner,oldKey=imageAreaSourceKey(o.references?.[0]),input=stack.conditioningInput;
  o.references=[{...input,file:input.file||[input.subfolder,input.filename].filter(Boolean).join('/'),name:'Current image composite',width:stack.width,height:stack.height,colour:{encoding:'srgb_display',sceneLinear:false},resolved_colour:'srgb_display',hasAlpha:false,precision:{storageBitDepth:8,sampleType:'uint'}},...o.references.slice(1)];
  const newKey=imageAreaSourceKey(o.references[0]);
  if(newKey!==oldKey)o.imageArea?.disposeViewer();
  if(o.imageArea?.state?.source_key===oldKey)o.imageArea.state.source_key=newKey;
 }
 sync(){const o=this.owner;for(const button of o.$('gallery').querySelectorAll('[data-save-image]'))button.disabled=this.busy;for(const link of o.$('gallery').querySelectorAll('[download]')){if(this.busy)link.setAttribute('aria-disabled','true');else link.removeAttribute('aria-disabled');}if(this.busy&&o.$('generate'))o.$('generate').disabled=true;const item=this.current(),hasLayers=!!item?.image_layers.layers.length;this.host.hidden=this.closed||o.mode!=='image'||o.imageOperation!=='edit'||o.imageIntent==='hdri'||!!o.editMainMissing||!!o.rippleImage?.request||!o.references?.[0];this.panel.hidden=!hasLayers;this.empty.hidden=hasLayers;if(this.host.hidden)return;if(!hasLayers){this.empty.querySelector('p').textContent=item?'No edit layers. Your original image is shown.':'New edits appear here as layers. Earlier flattened results have no editable layer data.';return;}PaintoutEditor.prototype.renderLayers.call(this.renderer,item.image_layers,true,this.isBusy());PlateSurface.prototype.syncLayerDisclosures.call(this.surface);}
 async commit(layers){
  const item=this.current();if(!item||this.isBusy())return;const stack=item.image_layers,referenceKey=identity(this.owner.references[0]),epoch=++this.epoch;this.busy=true;this.sync();this.owner.outpaintGuide?.syncImageUI?.();this.owner.message('Updating image layers…');
  try{const result=await this.request(stack,layers),input=await this.conditioning(result);if(this.epoch!==epoch||this.current()!==item||item.image_layers!==stack||identity(this.owner.references[0])!==referenceKey)throw Error('The image changed. Your previous result is retained.');item.image_layers={...stack,layers:copy(layers),conditioningInput:input};item.file=result.preview;item.master=result.master;item.preview=result.preview;item.hasAlpha=false;delete item.alpha;delete item.alphaAssociation;item.canonicalMaster=result.canonicalMaster||result.master;item.canonicalPreview=result.canonicalPreview||result.preview;item.width=result.width;item.height=result.height;item.colour=result.colour;this.selectInput(item);this.owner.save();this.owner.renderGallery();this.owner.render();this.owner.message('');}
  catch(error){this.owner.message(error.message);}finally{this.busy=false;this.renderer.layerPanelKey=null;this.sync();this.owner.render();if(item.image_layers!==stack&&this.current()===item)this.owner.outputSettings?.imageCommitted?.(item);this.owner.outpaintGuide?.syncImageUI?.();}
 }
 adjust(id,change){const item=this.current();if(item)return this.commit(item.image_layers.layers.map(layer=>layer.id===id?{...layer,...change}:layer));}
 move(id,delta){const item=this.current();if(!item)return;const layers=copy(item.image_layers.layers),from=layers.findIndex(layer=>layer.id===id),to=from+delta;if(from<0||to<0||to>=layers.length)return;layers.splice(to,0,layers.splice(from,1)[0]);return this.commit(layers);}
 remove(id){const item=this.current();if(item)return this.commit(item.image_layers.layers.filter(layer=>layer.id!==id));}
}

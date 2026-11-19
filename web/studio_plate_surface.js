import {PlateInlineEditor} from './studio_plate_inline.js';
import {PaintoutEditor} from './paintout_studio/paintout_editor.js';
import {PaintoutStyleGate} from './paintout_studio/style_ready.js';
import {createResultExportRow,renderPaintoutResultExports} from './studio_result_exports.js';
// Canvas-first presentation. The existing Paintout and image controllers own all jobs and data.
export class PlateSurface{
 constructor(plate){
  this.plate=plate;this.w=plate.primary;this.o=plate.owner;const w=this.w,d=w.page.ownerDocument;
  this.presentation=new PaintoutStyleGate(w.page,{beforeReveal:()=>{this.sync();w.editor.viewer?.resize();w.editor.timeline?.render();}});
  this.root=d.createElement('div');this.root.className='zplate-surface';
  this.root.innerHTML=`<header class="zpx-header"><span data-plate-spec>Open a video or image sequence</span><button data-plate-source>Open video</button><button data-plate-sequence>Image sequence</button><button data-plate-trim hidden>Trim clip</button><button data-plate-side-toggle aria-expanded="false">Layers &amp; settings</button><a data-plate-export hidden download>Export</a></header><nav class="zpx-rail" aria-label="Editing tools"><div data-plate-operations></div><div data-plate-brushes></div></nav><main class="zpx-stage"><div class="zpx-prompt"><textarea data-plate-prompt rows="2" placeholder="Describe your edit" aria-label="Describe your edit"></textarea><button type="button" data-plate-prompt-reference title="Add an extra reference image for inpainting control" hidden>Add reference</button><button data-plate-edit>Edit frame</button><button data-plate-new-edit hidden>New edit</button><button data-plate-retry hidden>Try again</button><button data-plate-run class="gs-primary">Generate video</button><button data-plate-stop hidden>Cancel run</button></div><div class="zpx-removal-flow" data-plate-removal-flow hidden></div><div class="zpx-view" data-plate-view></div><div class="zpx-status" data-plate-status role="status"></div><div data-plate-timeline></div></main><aside class="zpx-side zplate-sidebar"><div class="zpx-properties"><label>Model<select data-plate-model></select><span class="zpx-model-name" data-plate-model-name hidden>LTX 2.5 · Paintout</span></label><label data-plate-scale-label hidden>Processing<select data-plate-scale><option value="auto">Auto · source aspect</option><option value="0.5">0.5 MP</option><option value="1">1 MP</option><option value="2">2 MP</option><option value="4">4 MP</option><option value="8">8 MP</option></select></label><div class="zpx-processing" data-plate-processing hidden><div class="zpx-processing-heading"><label for="zpx-processing-mp">Processing</label><output data-plate-processing-mp for="zpx-processing-mp"></output></div><input type="range" id="zpx-processing-mp" data-plate-megapixels min="0.2" step="0.05" aria-label="Video processing megapixels"><div class="zpx-processing-heading"><span data-plate-processing-size></span><button type="button" data-plate-processing-native title="Process at the source size, aligned to the model grid">Source size</button></div></div><div data-plate-references hidden><div class="zpx-references-head"><button type="button" data-plate-add-reference>Add reference</button><span data-plate-reference-count></span></div><input data-plate-reference-file type="file" accept="image/*" multiple hidden/><div data-plate-reference-list></div></div></div><details data-plate-image-settings hidden><summary>Image settings</summary><div data-plate-image-settings-body></div></details><div data-plate-account></div><div data-plate-setup></div><div data-plate-clean-controls hidden></div><div data-plate-layers></div><div data-plate-details></div></aside>`;
  this.$=key=>this.root.querySelector('[data-plate-'+key+']');
  this.sourceMenu=d.createElement('details');this.sourceMenu.className='zpx-source-menu';
  const sourceSummary=d.createElement('summary');sourceSummary.textContent='Options';sourceSummary.setAttribute('aria-label','Source options');
  const sourceActions=d.createElement('div');sourceActions.setAttribute('role','group');sourceActions.setAttribute('aria-label','Source actions');
  sourceActions.append(...['sequence','trim'].map(key=>this.$(key)));this.sourceMenu.append(sourceSummary,sourceActions);
  this.sourceControl=d.createElement('div');this.sourceControl.className='zpx-source-control';this.sourceControl.setAttribute('role','group');this.sourceControl.setAttribute('aria-label','Video source');this.sourceControl.append(this.$('source'),this.sourceMenu);this.$('spec').before(this.sourceControl);sourceActions.addEventListener('click',event=>{const action=event.target.closest('button');if(action&&!action.disabled)this.sourceMenu.open=false;});
  this.layerDisclosureState=new Map();
  this.$('view').after(this.root.querySelector('.zpx-prompt'));
  this.resultExportsRow=createResultExportRow(d);this.root.querySelector('.zpx-prompt').after(this.resultExportsRow);
  const toolIcons={paint:'M4 20c2 0 4-1 4-4 0-1.5 1-2.5 2.5-2.5S13 14.5 13 16c0 3-3 4-9 4zM12.5 12.5 20 5l-1-1-7.5 7.5',remove:'M15 4l5 5-9 9H6l-2-2 11-12zM9 18h11',replace:'M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4'};
  for(const button of plate.strip.querySelectorAll('button')){const text=button.textContent;button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="'+toolIcons[button.dataset.plateAction]+'"/></svg><span>'+text+'</span>';}
  this.trimControls=d.createElement('div');this.trimControls.className='zpx-trim-controls';this.trimControls.hidden=true;const trimHelp=d.createElement('span');trimHelp.textContent='Choose the clip range below, then continue.';this.trimControls.append(trimHelp);
  this.$('operations').append(plate.strip);this.$('view').append(w.page.querySelector('.zf-viewer'));this.$('timeline').append(this.trimControls,w.editor.timelineHost);this.$('layers').append(w.editor.layersPanel);this.$('details').append(w.editor.tools);
  // Keep the native Remove controller's navigation and clean-frame actions
  // on the rebuilt surface, rather than in the hidden legacy composer.
  const cleanButton=w.editor.$('clean');
  this.$('removal-flow').append(w.editor.nav,w.editor.maskSummary);
  this.$('clean-controls').append(w.editor.cleanActions,plate.frameActions);plate.frameActionsHome=this.$('clean-controls');
  const nativeNewArea=w.editor.$('new-area')?.onclick;
  if(w.editor.$('new-area'))w.editor.$('new-area').onclick=event=>plate.propagation()?plate.newEditButton.click():nativeNewArea?.(event);
  this.$('run').before(cleanButton);
  const importFrame=this.root.querySelector('[data-editor=import]');importFrame.dataset.plateImport='';this.$('edit').after(importFrame);importFrame.onclick=()=>w.editor.importFrame({atPlayhead:true});
  this.root.querySelector('.zpx-properties').append(w.$('resolution'),w.$('render-settings'));this.root.querySelector('.zpx-stage').append(w.$('progress'));
  this.method=d.createElement('select');this.method.setAttribute('aria-label','Removal method');for(const [value,text]of [['targeted','Selected objects'],['full','Full-scene clean plate']]){const option=d.createElement('option');option.value=value;option.textContent=text;this.method.append(option);}this.method.onchange=()=>w.setMode(this.method.value);this.methodLabel=d.createElement('label');this.methodLabel.append(d.createTextNode('Removal area'),this.method);this.root.querySelector('.zpx-properties').prepend(this.methodLabel);
  for(const child of [...w.page.children])if(!['LINK','STYLE'].includes(child.tagName))child.classList.add('zplate-legacy');
  w.page.append(this.root);w.page.classList.add('zplate-rebuilt');
  this.modelSetupHost=d.createElement('div');this.modelSetupHost.className='zpx-model-setup';this.modelSetupHost.hidden=true;this.root.querySelector('.zpx-header').append(this.modelSetupHost);
  // The original Models details lived in the now-hidden workspace heading.
  // Keep its real catalogue and download actions, but mount it on this surface.
  w.openModelSetup=scope=>this.openModelSetup(scope);
  this.$('side-toggle').onclick=()=>{const open=this.root.classList.toggle('is-side-open');this.$('side-toggle').setAttribute('aria-expanded',String(open));};
  this.$('source').onclick=async()=>{if(plate.inline)await this.o.rippleImage.leave();if(!plate.inline)await w.pickSource('footage');};this.$('sequence').onclick=async()=>{if(plate.inline)await this.o.rippleImage.leave();if(!plate.inline)await w.pickSource('sequence');};this.$('trim').onclick=async()=>{if(plate.inline)await this.o.rippleImage.leave();if(!plate.inline)await(w.editor.stage==='trim'?w.editor.confirmClipTrim():w.editor.setStage('trim'));};
  this.$('prompt').oninput=()=>{const target=plate.inline?this.o.$('prompt'):!plate.propagation()&&w.editor.stage==='clean'?w.editor.$('instruction'):w.$('prompt');target.value=this.$('prompt').value;target.dispatchEvent(new Event('input',{bubbles:true}));};
  this.$('edit').onclick=()=>plate.backToShot();
  this.$('run').onclick=()=>{if(plate.inline){const request=this.o.rippleImage.request,item=this.o.items[this.o.selectedImage];if(request&&item&&item.ripple_guide===request.id){
    const draft=plate.frameDraft;
    if(plate.propagation()&&draft?.error&&!draft.composed&&draft.item===item&&draft.request===request){
      plate.frameDraft=null;this.sync();return;
    }
    return plate.propagation()?plate.usePaintResult(request):this.o.rippleImage.useResult();
  }if(plate.propagation()){plate.paintGenerateRequested=false;plate.rememberPrompt(this.o.$('prompt').value);}return this.o.generate();}return w.generate();};
  this.$('new-edit').onclick=()=>plate.newEditButton.click();
  this.$('retry').onclick=()=>this.o.generate();this.$('stop').onclick=()=>plate.inline?this.o.cancel():w.editor.toolJob?w.editor.cancel():w.cancel();
  const closeSide=()=>{this.root.classList.remove('is-side-open');this.$('side-toggle').setAttribute('aria-expanded','false');};this.root.addEventListener('keydown',e=>{if(e.key==='Escape'&&this.sourceMenu.open){this.sourceMenu.open=false;this.sourceMenu.querySelector('summary').focus();e.stopPropagation();return;}if(e.key==='Escape'&&this.root.classList.contains('is-side-open')&&!e.target.closest('details[open]')){closeSide();this.$('side-toggle').focus();e.stopPropagation();}});this.root.addEventListener('pointerdown',e=>{if(this.sourceMenu.open&&!this.sourceMenu.contains(e.target))this.sourceMenu.open=false;if(this.root.classList.contains('is-side-open')&&!e.target.closest('.zpx-side,[data-plate-side-toggle]'))closeSide();});
  this.$('model').onchange=()=>{if(plate.inline){this.o.$('model').value=this.$('model').value;this.o.$('model').dispatchEvent(new Event('change',{bubbles:true}));}else{plate.engine.querySelector('select').value=this.$('model').value;plate.engine.querySelector('select').onchange();}};
  this.$('scale').onchange=()=>{if(plate.inline){this.imageScale=this.$('scale').value;this.o.$('shape').value=this.imageScale==='auto'?'auto':'landscape';if(this.imageScale!=='auto'){const ref=this.o.references[0],ratio=ref.width/ref.height,mp=Number(this.imageScale),step=this.o.models.find(m=>m.id===this.o.$('model').value)?.sizeStep||16;this.o.$('width').value=Math.ceil(Math.sqrt(mp*1000000*ratio)/step)*step;this.o.$('height').value=Math.ceil(Math.sqrt(mp*1000000/ratio)/step)*step;}this.o.save();this.o.render();return;}};
  const megapixels=this.$('megapixels');
  megapixels.oninput=()=>{
    if(w.busy()||!w.sourceInfo||!plate.propagation()||plate.inline)return;
    w.state.plateProcessingMegapixels=Number(megapixels.value);
    this.syncVideoProcessing(false);
  };
  megapixels.onchange=()=>{megapixels.oninput();w.save();w.render();};
  this.$('processing-native').onclick=()=>{
    if(w.busy()||!w.sourceInfo||!plate.propagation()||plate.inline)return;
    w.state.plateProcessingMegapixels=0;
    w.save();w.render();
  };
  this.$('add-reference').onclick=()=>this.$('reference-file').click();this.$('prompt-reference').onclick=()=>this.$('reference-file').click();
  this.$('reference-file').onchange=e=>{const files=[...e.target.files];e.target.value='';void this.uploadPlateReferences(files);};
  for(const zone of [this.$('references'),this.root.querySelector('.zpx-prompt')]){zone.addEventListener('dragover',e=>{if(plate.propagation()&&w.state.source){e.preventDefault();}});zone.addEventListener('drop',e=>{const files=[...(e.dataTransfer?.files||[])].filter(f=>/^image\//i.test(f.type)||/\.(png|jpe?g|webp)$/i.test(f.name||''));if(files.length&&plate.propagation()&&w.state.source){e.preventDefault();e.stopPropagation();void this.uploadPlateReferences(files);}});}
  this.inlineEditor=new PlateInlineEditor(this);
  this.modelPicker=this.o.imageModelSetup?.attachPicker?.(this.$('model'),{
   getDownloads:()=>this.plate.inline?this.o.imageModelSetup:(this.plate.runner?.modelDownloads||this.o.studio?.modelDownloads||this.o.imageModelSetup),
   resolveOption:val=>{
    if(this.plate.inline){
     const m=this.o.models.find(x=>x.id===val);
     return {key:val,readyOverride:m?.ready,provider:!!m?.provider};
    }
    if(val==='remove'){
     const pm=this.w.modelDownloads,rec=pm?.modelForContext?.(pm.recommended());
     const missing=rec?.files?.filter(f=>!f.installed)||[];
     return {key:'ltx25_clean_plate',readyOverride:!!rec&&!missing.length,customInstall:async()=>{await pm.load();pm.$('package').value=pm.recommended();pm.closed=false;pm.inlineActive=true;return pm.start();}};
    }
    return {key:val==='h3'?'h3_ripple':'ltx_ripple'};
   }
  });
  this.presentationReady=this.presentation.show();
 }
 async uploadPlateReferences(files){
  const p=this.plate,w=this.w,o=this.o;if(!files?.length||w.busy()||o.rippleImage?.importing)return;
  if(!p.inline&&p.propagation()&&w.state.source){
   if(!w.state.clipTrimConfirmed)await w.editor.confirmClipTrim();
   if(!w.editor.selected()){w.editor.createFrame(w.playhead);await w.editor.frameChanged(true);}
   if(!p.inline)await p.editFrame();
  }
  if(p.inline){
   await o.uploadReferences(files);
   if(o.rippleImage?.request?.anchor){o.rippleImage.request.anchor.image_references=o.references.slice(1).map(ref=>({...ref}));w.save();}
   this.sync();
  }
 }
 syncImageTools(){
  const tools=this.$('brushes').querySelector('.zia-tools');if(!tools||tools.classList.contains('pap-tools')||tools.dataset.iconRail==='true')return;
  const paths={draw:'M4 20l4-1 11-11a2.1 2.1 0 0 0-3-3L5 16l-1 4zm10-14 4 4',brush:'M5 4h4m6 0h4v4m0 8v4h-4m-6 0H5v-4M5 8V4m5 6h4v4h-4z',protect:'m14 4 6 6-9 10H6l-3-4L14 4zm-7 8 7 7m-4 1h11',pan:'M8 11V6a2 2 0 0 1 4 0v5-7a2 2 0 0 1 4 0v7-5a2 2 0 0 1 4 0v8c0 4-3 7-7 7h-1c-2 0-3-1-4-3l-4-6a2 2 0 0 1 3-2l1 1',undo:'M4 10h9a6 6 0 0 1 0 12M4 10l5-5M4 10l5 5',clear:'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5m4-5v5',fit:'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M8 8h8v8H8z'};
  const descriptions={draw:'Draw a guide for the image edit',brush:'Select the area the model may edit',protect:'Erase the painted selection',pan:'Pan the image',undo:'Undo the last stroke',clear:'Clear the drawing and selection',fit:'Fit the image in the viewport'};
  for(const button of tools.querySelectorAll('button')){
   const key=button.dataset.areaTool||button.dataset.areaAction;if(!paths[key])continue;
   const label=button.getAttribute('aria-label')||button.textContent.trim();button.setAttribute('aria-label',label);button.title=descriptions[key];
   button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="'+paths[key]+'"/></svg><span class="zia-tool-label">'+label+'</span>';
  }
  const group=(name,selector)=>{const section=tools.ownerDocument.createElement('div');section.className='zia-tool-group zia-tool-group--'+name;section.setAttribute('role','group');section.setAttribute('aria-label',name==='paint'?'Drawing and selection tools':name==='settings'?'Brush settings':'History and view');section.append(...tools.querySelectorAll(selector));return section;};
  const paint=group('paint','[data-area-tool]'),settings=group('settings','.zia-colour,.zia-brush'),history=group('history','[data-area-action=undo],[data-area-action=clear],[data-area-action=fit]');
  tools.append(paint,settings,history);tools.classList.add('zia-icon-tools');tools.dataset.iconRail='true';
 }
 syncDraftLayers(draft,busy){
  if(!this.draftLayerPanel){
   this.draftLayerPanel=this.root.ownerDocument.createElement('section');
   this.draftLayerPanel.className='zp-editor-paint-layers';
   this.draftLayerPanel.setAttribute('aria-label','Draft frame layers');
   this.$('layers').append(this.draftLayerPanel);
  }
  this.draftLayerPanel.hidden=!draft?.layers;
  if(!draft?.layers)return null;
  const pending=busy||draft.pending,plate=this.plate;
  const selected=()=>({id:draft.item.file?.filename,layers:draft.layers.map(layer=>({...layer,draft:layer.id===draft.layerId}))});
  const adjust=(id,change)=>plate.updateFrameDraft(draft,draft.layers.map(layer=>layer.id===id?{...layer,...change}:layer));
  const editor={draftFrame:true,layersPanel:this.draftLayerPanel,w:this.w,selected,ensureLayers:frame=>frame.layers,adjustPaintLayer:adjust,
   expandPaintLayer:(id,value)=>adjust(id,{expand_pixels:value}),blendPaintLayer:(id,value)=>adjust(id,{blend_pixels:value}),brightnessPaintLayer:(id,value)=>adjust(id,{brightness_ev:value}),
   canRemoveLayer:id=>id!==draft.layerId,
   removePaintLayer:id=>id!==draft.layerId&&plate.updateFrameDraft(draft,draft.layers.filter(layer=>layer.id!==id)),
   movePaintLayer:(id,delta)=>{
    const layers=[...draft.layers],from=layers.findIndex(layer=>layer.id===id),to=from+delta;
    if(from<0||to<0||to>=layers.length)return;
    const [layer]=layers.splice(from,1);layers.splice(to,0,layer);return plate.updateFrameDraft(draft,layers);
   },layerPanelKey:this.draftLayerKey};
  PaintoutEditor.prototype.renderLayers.call(editor,selected(),true,pending);
  this.draftLayerKey=editor.layerPanelKey;
  return editor;
 }
 syncLayerDisclosures(editor=this.w.editor){
  const layers=editor.selected()?.layers||[];
  const panel=editor.layersPanel||this.$('layers');
  for(const adjustments of panel.querySelectorAll('.zp-editor-layer-adjustments')){
   if(adjustments.parentElement.classList.contains('zpx-layer-adjustments'))continue;
   const row=adjustments.closest('li'),menu=row.querySelector('.zp-layer-menu'),buttons=[...menu.querySelectorAll('button')],visibility=row.querySelector('.zp-layer-visibility');
   const index=[...row.parentElement.children].indexOf(row),layer=layers[layers.length-1-index],key=layer?.id||row.querySelector('strong')?.textContent;
   const details=this.root.ownerDocument.createElement('details'),summary=this.root.ownerDocument.createElement('summary');
   details.className='zpx-layer-adjustments';summary.textContent='Adjust layer';summary.setAttribute('aria-label','Adjust '+(row.querySelector('strong')?.textContent||'layer'));
   const disclosureKey=layer?.draft?'draft:'+key:key;
   details.open=this.layerDisclosureState.get(disclosureKey)??!!layer?.draft;details.ontoggle=()=>this.layerDisclosureState.set(disclosureKey,details.open);
   row.append(details);details.append(summary,adjustments);
   for(const slider of adjustments.querySelectorAll('input[type=range]')){slider.ondblclick=()=>{if(slider.disabled)return;const def=slider.closest('.zp-editor-layer-opacity')?'100':'0';if(slider.value===def)return;slider.value=def;slider.oninput?.();slider.onchange?.();};}
   const order=this.root.ownerDocument.createElement('div');order.className='zpx-layer-order';order.append(...buttons.slice(0,2));const edit=menu.querySelector('[data-edit-plate-layer]');if(edit)details.append(edit);details.append(order);
   const remove=buttons.at(-1);remove.classList.add('zpx-layer-delete');menu.replaceWith(remove);
   const shown=visibility.getAttribute('aria-pressed')==='true';visibility.title=visibility.getAttribute('aria-label');visibility.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'+(shown?'':'<path d="M3 3l18 18"/>')+'</svg>';
   const handle=this.root.ownerDocument.createElement('button');handle.type='button';handle.className='zpx-layer-drag';handle.title='Drag to reorder. Use Alt + Up or Down with the layer focused.';handle.setAttribute('aria-label','Reorder '+(row.querySelector('strong')?.textContent||'layer'));handle.innerHTML='<svg viewBox="0 0 16 24" aria-hidden="true"><path d="M5 6h1m4 0h1M5 12h1m4 0h1M5 18h1m4 0h1"/></svg>';handle.disabled=visibility.disabled;handle.draggable=!visibility.disabled;row.prepend(handle);
   row.dataset.layerId=key;row.onkeydown=event=>{if(event.altKey&&['ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();buttons[event.key==='ArrowUp'?0:1].click();}};
   handle.ondragstart=event=>{if(handle.disabled||this.w.busy()||editor.candidate){event.preventDefault();return;}this.dragLayerId=layer?.id;event.dataTransfer?.setData('text/plain',layer?.id||'');if(event.dataTransfer)event.dataTransfer.effectAllowed='move';};
   row.ondragover=event=>{if(this.dragLayerId&&this.dragLayerId!==layer?.id&&!this.w.busy()){event.preventDefault();row.classList.add('is-drop-target');}};
   row.ondragleave=()=>row.classList.remove('is-drop-target');handle.ondragend=()=>{this.dragLayerId=null;for(const target of this.$('layers').querySelectorAll('.is-drop-target'))target.classList.remove('is-drop-target');};
   row.ondrop=event=>{event.preventDefault();row.classList.remove('is-drop-target');const id=this.dragLayerId;this.dragLayerId=null;const current=editor.selected()?.layers||[],from=current.findIndex(item=>item.id===id),to=current.findIndex(item=>item.id===layer?.id);if(from>=0&&to>=0&&from!==to&&!this.w.busy()&&!editor.candidate)void editor.movePaintLayer(id,to-from);};
  }
 }
 async navigateStage(label){
  const w=this.w,p=this.plate;
  if(w.busy())return false;
  if(label==='Source'){this.sourceMenu.open=true;this.sourceMenu.querySelector('summary').focus();return true;}
  if(!w.state.source)return false;
  const target=({'Trim clip':'trim','Mask':'mask','Clean frames':'clean','Paint frame':'clean','Reference frame':'clean','Video':'render','Result':'render'})[label];
  if(!target)return false;this.sourceMenu.open=false;
  if(p.inline&&target!=='clean')await this.o.rippleImage.leave();
  if(label==='Result'&&w.result){w.preview('result');this.sync();return true;}
  await w.editor.setStage(target);this.sync();return true;
 }
 async openModelSetup(scope='video'){
  const propagation=this.plate.propagation()&&scope==='video';
  const owner=propagation?this.plate.ensureRunner():this.w,models=owner.modelDownloads;
  if(!models)return this.w.message('Model setup is still loading. Try again in a moment.');
  const panel=models.root||models.panel;
  if(!panel)return this.w.message('Model setup is unavailable. Refresh Studio and try again.');
  this.modelSetupHost.replaceChildren(panel);this.modelSetupHost.hidden=false;this.modelSetupAction=this.plate.action;
  if(models.open){models.open(scope);return;}
  panel.classList.add('zc-tool-popup');panel.querySelector('.gs-advanced-body')?.classList.add('zc-tool-panel');panel.querySelector('summary').textContent='Models';panel.open=true;
  await owner.checkModels?.();await models.load();models.select.value='__workflow__';models.render();
 }
 syncVideoProcessing(busy){
  const p=this.plate,w=this.w,control=this.$('processing'),slider=this.$('megapixels');
  control.hidden=!!p.inline||!p.propagation();
  if(control.hidden)return;
  const {min,max}=p.processingRange(),{width,height}=p.processingSize(),hasSource=width>0&&height>0;
  slider.min=String(min);slider.max=String(max);slider.disabled=busy||!hasSource;
  const mp=width*height/1e6,selected=w.state.plateProcessingMegapixels;
  slider.value=String(Math.max(min,Math.min(max,selected>0?selected:mp)));
  this.$('processing-mp').textContent=hasSource?mp.toFixed(2)+' MP':'';
  const dimensions=hasSource?width+' × '+height:'Add source footage';
  this.$('processing-size').textContent=dimensions;
  slider.setAttribute('aria-valuetext',hasSource?mp.toFixed(2)+' megapixels, '+width+' by '+height+' pixels':'Add source footage');
  const native=this.$('processing-native');
  native.disabled=busy||!hasSource;
  native.setAttribute('aria-pressed',String(selected===0||selected==null&&!w.state.processingMegapixelLimit&&w.state.plateScale===1));
 }
 sync(){
  const p=this.plate,w=this.w,o=this.o,editing=!!p.inline,busy=(p.propagation()?p.jobBusy():w.busy())||!!o.rippleImage?.importing,source=w.sourceInfo;
  renderPaintoutResultExports(this.resultExportsRow,o.api,editing?null:w.result);
  const removal=!editing&&!p.propagation(),cleaning=removal&&w.state.mode!=='full'&&w.editor.stage==='clean',selectedAnchor=w.editor.selected(),hasFrameControls=!!source&&(cleaning||!editing&&p.propagation()&&w.editor.stage==='clean'&&!!(selectedAnchor?.file||selectedAnchor?.layers?.length));
  if(this.modelSetupAction!==p.action||editing){for(const panel of this.modelSetupHost.children)panel.open=false;this.modelSetupHost.hidden=true;}
  const cancellable=editing?!!o.job:!!(w.job||w.editor.toolJob||p.runner?.job||p.runner?.pendingSubmission);
  this.$('spec').textContent=source?`${source.path.split(/[\\/]/).pop()} · ${source.width} × ${source.height} · ${Number(w.fps().toFixed(3))} fps`:'Open a video or image sequence';
  const trimAction=this.$('trim'),choosingClip=!!source&&w.editor.stage==='trim';
  trimAction.hidden=!source;trimAction.textContent=choosingClip?(removal?'Continue to masking':'Continue to painting'):'Trim clip';
  trimAction.classList.remove('zp-editor-next');trimAction.classList.toggle('gs-primary',choosingClip);
  this.trimControls.hidden=!choosingClip;
  if(choosingClip){if(trimAction.parentElement!==this.trimControls)this.trimControls.append(trimAction);}
  else{const actions=this.sourceMenu.querySelector('[role=group]');if(trimAction.parentElement!==actions)actions.append(trimAction);}
  this.$('source').textContent=source?'Replace video':'Add video';this.$('sequence').disabled=busy;this.$('source').disabled=this.$('trim').disabled=busy;
  const promptField=editing?o.$('prompt'):cleaning?w.editor.$('instruction'):w.$('prompt');
  const prompt=promptField.value;if(this.$('prompt')!==this.root.ownerDocument.activeElement)this.$('prompt').value=prompt;
  this.root.classList.toggle('has-source',!!source);this.root.querySelector('.zpx-prompt').hidden=!source||removal&&w.editor.stage==='trim'&&!cancellable;this.$('prompt').hidden=removal&&['trim','mask'].includes(w.editor.stage);this.$('timeline').hidden=!source;
  this.$('import').hidden=editing||!source;this.$('import').disabled=busy||!w.state.clipTrimConfirmed||!!w.editor.candidate;this.$('import').title=!w.state.clipTrimConfirmed?'Confirm the clip range before importing an edited frame':w.editor.candidate?'Accept or dismiss the current imported frame first':'Import an externally edited image into frame '+w.playhead+' at the original source resolution';
  this.$('removal-flow').hidden=!source||!removal;this.$('clean-controls').hidden=!hasFrameControls;
  w.editor.$('clean').hidden=!cleaning||cancellable;
  this.$('side-toggle').textContent=removal&&w.editor.stage==='mask'?'Mask & settings':cleaning||hasFrameControls?'Frame & layers':'Layers & settings';
  w.editor.guideHelp.hidden=!removal;w.editor.$('instruction').closest('label').hidden=cleaning||p.propagation();
  this.$('prompt').setAttribute('aria-label',cleaning?'Cleanup instruction':'Describe your edit');this.$('prompt').placeholder=cleaning?promptField.placeholder:p.action==='replace'?'Describe what should replace the selected area (optional: attach a reference image)':'Describe what to paint, then paint it on the frame (optional: attach a reference image)';
  this.$('edit').hidden=!editing;
  this.$('prompt').disabled=busy;this.$('edit').disabled=busy||!source;
  this.$('run').disabled=editing?o.$('generate').disabled:w.$('generate').disabled;
  const request=o.rippleImage.request,item=o.items[o.selectedImage],ready=!!(editing&&request&&item&&item.ripple_guide===request.id);
  this.$('new-edit').hidden=editing||!p.propagation()||!selectedAnchor?.layers?.length;this.$('new-edit').disabled=busy;
  const draft=ready?p.syncFrameDraft(request,item):null;
  if(ready)this.$('run').disabled=busy||!!draft?.pending;this.$('retry').hidden=!ready;this.$('retry').disabled=busy||!!draft?.pending||o.$('generate').disabled;this.$('stop').hidden=!cancellable;this.$('stop').disabled=false;this.$('run').hidden=cancellable||removal&&w.editor.stage!=='render';
  this.$('run').textContent=busy?'Working…':ready?(draft?.error&&!draft.composed?'Retry layer setup':'Save frame edit'):editing?'Generate frame edit':w.$('generate').textContent;
  this.$('edit').textContent='Back to video';this.$('edit').title='Leave the frame editor without starting a video render';
  this.$('new-edit').textContent='Add another edit';this.$('new-edit').title='Create another image edit layer on the selected frame';
  const choices=editing?o.models.filter(m=>m.edit).map(m=>[m.id,m.provider?m.name+' · Browser sign-in':m.name]):p.propagation()?[['ltx','LTX 2.5'],['h3','MiniMax H3']]:[['remove','LTX 2.5 · Paintout']];
  if(!choices.length)choices.push([o.$('model').value||'loading','Loading models…']);const signature=JSON.stringify(choices);if(signature!==this.modelSignature){this.modelSignature=signature;this.$('model').replaceChildren(...choices.map(([value,label])=>{const option=this.root.ownerDocument.createElement('option');option.value=value;option.textContent=label;return option;}));}
  this.$('model').value=editing?o.$('model').value:p.propagation()?w.state.plateEngine:'remove';this.$('model-name').hidden=editing||p.propagation();this.$('model').hidden=!editing&&!p.propagation();this.$('model').disabled=busy||(editing&&!o.models.length)||(!editing&&!p.propagation());this.$('scale-label').hidden=!editing;
  if(editing&&this.editId!==request?.id){this.editId=request?.id;this.imageScale='auto';}
  this.$('scale').value=this.imageScale||'auto';
  this.syncVideoProcessing(busy);
  this.$('image-settings').hidden=!editing;
  this.methodLabel.hidden=editing||p.propagation();this.method.hidden=editing||p.propagation();this.method.value=w.state.mode;this.method.disabled=busy;w.$('resolution').hidden=editing||p.propagation();w.$('render-settings').hidden=editing;
  const showRefs=editing||p.propagation()&&!!source&&w.editor.stage!=='trim',activeRefs=editing?o.references.slice(1):(selectedAnchor?.image_references||[]);
  if(editing&&request?.anchor)request.anchor.image_references=activeRefs.map(ref=>({...ref}));
  this.$('references').hidden=!showRefs;this.$('prompt-reference').hidden=!showRefs;this.$('prompt-reference').disabled=busy;
  this.$('prompt-reference').textContent=activeRefs.length?`References (${activeRefs.length})`:'Add reference';
  this.$('reference-count').textContent=showRefs?`${activeRefs.length} reference${activeRefs.length===1?'':'s'}`:'';
  const referenceKey=showRefs?JSON.stringify([editing,activeRefs]):'';if(referenceKey!==this.referenceKey){this.referenceKey=referenceKey;this.$('reference-list').replaceChildren();if(showRefs)activeRefs.forEach((ref,index)=>{const row=this.root.ownerDocument.createElement('div'),image=this.root.ownerDocument.createElement('img'),badge=this.root.ownerDocument.createElement('small'),remove=this.root.ownerDocument.createElement('button');image.src=o.api.apiURL('/view?'+new URLSearchParams({filename:ref.filename,subfolder:ref.subfolder||'',type:'input'}));image.alt=ref.name||'Reference '+(index+1);badge.textContent=`Image ${index+2}`;remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Remove reference '+(index+1));remove.onclick=()=>{if(w.busy())return;if(editing){o.references.splice(index+1,1);if(request?.anchor)request.anchor.image_references=o.references.slice(1).map(r=>({...r}));o.save();o.render();}else if(selectedAnchor?.image_references){selectedAnchor.image_references.splice(index,1);w.save();w.render();}};row.append(image,badge,remove);this.$('reference-list').append(row);});}
  const quick=editing?o.imageModelSetup?.quick:p.propagation()?p.runner?.modelDownloads?.quick:w.modelDownloads?.quick;if(quick&&quick.parentElement!==this.$('setup'))this.$('setup').replaceChildren(quick);
  this.$('references').querySelector('button').disabled=busy;this.$('scale').disabled=busy;w.editor.tools.hidden=!source||editing||p.propagation()||w.state.mode==='full'||!['mask','clean'].includes(w.editor.stage);p.frameToolbar.hidden=true;
  this.$('layers').style.pointerEvents='';this.$('layers').setAttribute('aria-disabled','false');w.editor.timeline.addFrame.querySelector('span').textContent=removal?'Add clean frame':'Add keyframe';w.editor.timeline.addFrame.title=removal?'Add a clean-frame guide at the playhead':'Add an edited frame at the playhead';w.editor.timeline.cleanLabel.textContent=removal?'Clean frames':'Edited frames';
  if(p.propagation()){
    if(selectedAnchor)w.editor.renderLayers(selectedAnchor,editing&&!draft?.layers,busy||!!draft?.pending);
    w.editor.layersPanel.hidden=!editing||!selectedAnchor||!!draft?.layers;
  }
  const draftEditor=this.syncDraftLayers(draft,busy);
  const status=editing?o.$('message').textContent:w.$('message').textContent;
  const guidance=editing&&!busy?(ready?(draft?.error|| (draft?.pending?'Updating the layer preview…':'Adjust the layers, then choose Save frame edit.')):p.action==='replace'?'Select the area to replace (or paint a guide), optionally add a reference image, then generate an edited frame.':'Paint directly on the frame (or select an area), optionally add a reference image, then generate.'):'';
  this.$('status').textContent=status||guidance;this.$('status').hidden=!status&&!guidance;
  this.inlineEditor?.sync();this.modelPicker?.sync();this.syncImageTools();this.syncLayerDisclosures(draftEditor||w.editor);
  const repaired=!!w.editor.selected()?.layers?.length;
  this.root.classList.toggle('has-clean-frame',repaired);this.root.dataset.stage=w.editor.stage;
  const maskReady=removal&&w.editor.stage==='mask'&&!w.editor.$('continue').hidden&&!w.editor.$('continue').disabled;this.root.classList.toggle('is-mask-ready',maskReady);
  const help=w.editor.guideHelp;
  if(removal&&help&&!help.hidden){help.title=help.textContent;help.textContent=({trim:'Choose the part of the shot to process.',mask:maskReady?'Mask ready. Continue to create clean frames.':'Mark the object, then track it through the shot.',clean:repaired?'Review the repair, or paint another area.':'Paint the repair area and create a clean frame.',render:'Review your mask and clean frames, then render.'})[w.editor.stage]||help.textContent;}
  const file=w.resultMasterFile?.();this.$('export').hidden=!file;if(file)this.$('export').href=w.url('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'}));else this.$('export').removeAttribute('href');
 }
}

import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';
import {PlateWorkspace} from '../web/studio_plate.js';
import {writeFileSync} from 'node:fs';
import {ImageEditArea} from '../web/studio_image_area.js';
import {installPopoverDismissal} from '../web/studio_popovers.js';

const {document,window}=parseHTML('<html><head></head><body><main id="genj-studio" data-workspace="paintout"><div class="gs-workspace"></div></main></body></html>');
let styled=false;const frames=[];
window.requestAnimationFrame=callback=>frames.push(callback);
window.HTMLElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:styled?960:88,height:540,right:styled?960:88,bottom:540});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(value){this.toggleAttribute('checked',!!value);}});
window.HTMLElement.prototype.pause=()=>{};window.HTMLElement.prototype.load=()=>{};
window.HTMLCanvasElement.prototype.getContext=()=>new Proxy({},{get:()=>()=>{}});
const storage={getItem:()=>null,setItem(){},removeItem(){}};
Object.assign(globalThis,{document,window,innerWidth:1396,innerHeight:1046,localStorage:storage,ResizeObserver:class{observe(){}disconnect(){}}});
const owner={root:document.querySelector('main'),studio:{close(){}},app:{},storage,mode:'paintout',videoComposer:{syncWorkflow(){}},rippleImage:{request:null,importing:false},items:[],selectedImage:-1,references:[],models:[],
  api:{apiURL:path=>path,addEventListener(){},removeEventListener(){},fetchApi:async()=>({ok:true,json:async()=>({})})},
  fetch:async()=>({}),$(id){return document.querySelector('#zc-'+id)||{value:'',disabled:false};}};
const workspace=new PaintoutWorkspace(owner,{paintoutOnly:true});owner.paintout=workspace;workspace.modelInfo={};
const plate=new PlateWorkspace(owner);owner.plate=plate;plate.attach(workspace);

const surface=plate.surface,editor=workspace.editor;
const anchor={id:'anchor',frame:0,status:'accepted',file:'repair.png',layers:[{id:'one',file:'one.png',prompt:'First repair',method:'image'},{id:'two',file:'two.png',prompt:'Second repair',method:'image'},{id:'three',file:'three.png',prompt:'Third repair',method:'image'}]};
workspace.state.anchors=[anchor];workspace.selected=0;workspace.playhead=0;workspace.state.source='clip.mp4';workspace.state.frameCount=18;workspace.sourceInfo={path:'clip.mp4',width:512,height:320,fps:30,frames:18};editor.stage='clean';
editor.renderLayers(anchor,true,false);surface.syncLayerDisclosures();
workspace.result={preview_only:true,file:{filename:'preview.mp4',type:'output'}};surface.$('export').href='/stale-master.exr';surface.sync();assert.equal(surface.$('export').hidden,true,'Preview-only results never become downloads');assert.equal(surface.$('export').hasAttribute('href'),false,'A preview-only result clears a stale master href');
assert.equal(surface.resultExportsRow.hidden,true,'Preview-only results have no master export row');
const oldAction=plate.action,previewOnly=workspace.result;workspace.result={files:[{filename:'finished.mov',subfolder:'paintout/take',type:'output'}],config:{outputMode:'SDR video'},exports:[{role:'mask',file:{filename:'used_mask.mov',subfolder:'paintout/take',type:'output'}}]};
for(const action of ['paint','replace','remove']){plate.action=action;surface.sync();assert.equal(surface.resultExportsRow.querySelector('[data-result-export=mask]').download,'used_mask.mov',action+' exposes its returned processing mask');assert.equal(surface.resultExportsRow.previousElementSibling,surface.root.querySelector('.zpx-prompt'),'Save files stay grouped beside the main result action');}
plate.action=oldAction;workspace.result=previewOnly;surface.sync();
editor.stage='trim';workspace.state.clipTrimConfirmed=false;surface.sync();const trimAction=surface.$('trim');assert.equal(trimAction.parentElement===surface.trimControls,true,'Trim confirmation stays beside the timeline');assert.equal(trimAction.textContent,'Continue to masking');assert.equal(trimAction.closest('.zpx-source-menu'),null);assert.equal(trimAction.hidden,false);assert.ok(trimAction.classList.contains('gs-primary'));
let trimAccepted=0;const confirmClipTrim=editor.confirmClipTrim;editor.confirmClipTrim=async()=>{trimAccepted++;};await trimAction.onclick();assert.equal(trimAccepted,1,'Visible acceptance retains its real callback');editor.confirmClipTrim=confirmClipTrim;
editor.stage='mask';workspace.state.clipTrimConfirmed=true;surface.sync();assert.ok(trimAction.closest('.zpx-source-menu'),'After accepting the clip, Trim returns to source options');assert.equal(trimAction.textContent,'Trim clip');assert.equal(trimAction.classList.contains('gs-primary'),false);editor.stage='clean';surface.sync();
const sourceMenu=surface.sourceMenu;assert.deepEqual([...sourceMenu.querySelectorAll('button')].map(button=>button.dataset.plateSequence!==undefined?'sequence':'trim'),['sequence','trim']);assert.equal(sourceMenu.querySelector('[data-plate-reset]'),null,'Start over lives in the shared header');
assert.equal(surface.$('source').closest('.zpx-source-menu'),null,'The primary source button is always outside the secondary menu');assert.equal(surface.sourceControl.nextElementSibling,surface.$('spec'),'The source import is before the filename at the left');assert.equal(surface.$('source').textContent,'Replace video');
const originalImportFrame=editor.importFrame;let importOptions;editor.importFrame=async options=>{importOptions=options;};
for(const action of ['paint','remove','replace']){plate.action=action;editor.stage=action==='remove'?'mask':'clean';workspace.$('generate').disabled=true;surface.sync();assert.equal(surface.$('import').hidden,false);assert.equal(surface.$('import').disabled,false,'Manual import does not inherit AI-model readiness');assert.equal(surface.$('import').parentElement,surface.root.querySelector('.zpx-prompt'));assert.equal(surface.$('import').parentElement.hidden,false);surface.$('import').click();assert.deepEqual(importOptions,{atPlayhead:true});}
editor.importFrame=originalImportFrame;plate.action=oldAction;editor.stage='clean';surface.sync();
plate.action='replace';editor.stage='clean';const editedFile=anchor.file;anchor.file='';
surface.sync();
assert.equal(surface.$('run').textContent,'Edit keyframe','A draft frame offers a next step instead of a disabled render');
assert.equal(surface.$('run').disabled,false);
editor.candidate={review:{token:'manual-review',outside_pixels:7},anchor:anchor.id};
surface.sync();
assert.equal(editor.importReview.hidden,false);
assert.equal(editor.importReview.parentElement,surface.root.querySelector('.zpx-stage'),'Import review is outside the hidden propagation tools');
assert.equal(surface.$('run').textContent,'Use imported edit');
const acceptImported=editor.acceptImported;
let importedScope;editor.acceptImported=async scope=>{importedScope=scope;anchor.file=editedFile;editor.candidate=null;plate.syncControls();};
await surface.$('run').onclick();
assert.equal(importedScope,'include');
assert.equal(surface.$('run').textContent,'Generate video');
editor.acceptImported=acceptImported;
plate.action=oldAction;surface.sync();

const maskOptions=[...surface.root.querySelectorAll('.zp-editor-action-menu')].find(menu=>menu.querySelector('summary')?.textContent==='Mask options');assert.ok(maskOptions.matches('.zc-tool-popup'));assert.ok(maskOptions.querySelector(':scope > .zc-tool-panel'));
const disposePopovers=installPopoverDismissal(owner.root);let focusedMaskOptions=0;maskOptions.querySelector('summary').focus=()=>focusedMaskOptions++;maskOptions.open=true;const escapeMenu=new window.Event('keydown',{bubbles:true,cancelable:true});escapeMenu.key='Escape';maskOptions.querySelector('button').dispatchEvent(escapeMenu);assert.equal(maskOptions.open,false);assert.equal(focusedMaskOptions,1,'Escape returns focus to the original Mask options summary');disposePopovers();
const pickSource=workspace.pickSource;let pickerKind;workspace.pickSource=async kind=>{pickerKind=kind;};sourceMenu.open=true;surface.$('sequence').click();assert.equal(sourceMenu.open,false,'Choosing a source action closes its disclosure immediately');assert.equal(pickerKind,'sequence','Closing the disclosure preserves the existing picker handler');workspace.pickSource=pickSource;
const children=[...surface.$('view').parentElement.children];assert.ok(children.indexOf(surface.$('view'))<children.indexOf(surface.root.querySelector('.zpx-prompt')),'One prompt stays below preview');
let rows=[...surface.$('layers').querySelectorAll('li')];assert.equal(rows.length,3);
for(const row of rows){const disclosure=row.querySelector('.zpx-layer-adjustments');assert.equal(disclosure.open,false);assert.equal(disclosure.querySelectorAll('input[type=range]').length,4,'All four original adjusters remain in one disclosure');assert.ok(row.querySelector('.zp-layer-visibility svg'));assert.ok(row.querySelector('.zpx-layer-delete svg'));assert.equal(row.querySelector('.zp-layer-menu'),null);assert.equal(disclosure.querySelectorAll('.zpx-layer-order button').length,2);}
const moves=[];editor.movePaintLayer=async(id,delta)=>moves.push([id,delta]);
rows[2].querySelector('.zpx-layer-drag').ondragstart({dataTransfer:{setData(){}},preventDefault(){}});rows[0].ondrop({preventDefault(){}});assert.deepEqual(moves,[['one',2]],'Drag reaches real composition reorder controller');
rows[1].onkeydown({altKey:true,key:'ArrowUp',preventDefault(){}});assert.deepEqual(moves.at(-1),['two',1],'Keyboard reorder uses same controller');
let removed;editor.removePaintLayer=id=>removed=id;rows[1].querySelector('.zpx-layer-delete').click();assert.equal(removed,'two');
let adjusted;editor.adjustPaintLayer=(id,change)=>adjusted=[id,change];rows[1].querySelector('.zp-layer-visibility').click();assert.deepEqual(adjusted,['two',{enabled:false}]);
const disclosure=rows[1].querySelector('.zpx-layer-adjustments');disclosure.open=true;disclosure.ontoggle();editor.layerPanelKey=null;editor.renderLayers(anchor,true,false);surface.syncLayerDisclosures();assert.equal(surface.$('layers').querySelectorAll('.zpx-layer-adjustments')[1].open,true,'Disclosure choice survives controller repaint');
editor.stage='mask';workspace.state.mode='targeted';editor.$('continue').hidden=false;editor.$('continue').disabled=false;surface.sync();assert.equal(surface.root.classList.contains('is-mask-ready'),true);editor.$('continue').disabled=true;surface.sync();assert.equal(editor.$('continue').disabled,true,'Presentation never bypasses controller readiness');assert.equal(surface.root.classList.contains('is-mask-ready'),false);editor.stage='clean';surface.sync();
const timeline=editor.timeline,previousState={...editor.timeline.state},selectedMasks=[],trimmedMasks=[],selectMask=timeline.callbacks.onSegmentSelect,trimMask=timeline.callbacks.onMaskTrim;
timeline.callbacks.onSegmentSelect=id=>selectedMasks.push(id);timeline.callbacks.onMaskTrim=(...args)=>trimmedMasks.push(args);
timeline.update({stage:'mask',sourceFrames:18,startFrame:0,frameCount:18,maskSegments:[{id:'tracked',name:'Tracked',start:0,end:17,available_start:0,available_end:17,tracked:true},{id:'static',name:'Static',start:0,end:17,available_start:0,available_end:17,ready:true,tracked:false},{id:'imported',name:'Imported',start:0,end:17,available_start:0,available_end:17,ready:true,tracked:false}],selectedMask:'static'});
const maskRows=[...timeline.maskLanes.querySelectorAll('.zp-editor-mask-row')];assert.equal(maskRows.length,3);
for(const row of maskRows){row.querySelector('.zp-editor-mask-bar__select').click();assert.ok(row.getAttribute('aria-label'));assert.equal(row.querySelector('.zp-editor-mask-bar').style.left,'0%');assert.equal(row.querySelector('.zp-editor-mask-bar').style.width,'100%');}
assert.deepEqual(selectedMasks,['tracked','static','imported']);maskRows[1].querySelector('.zp-editor-mask-bar__handle').onkeydown({key:'ArrowRight',preventDefault(){},stopPropagation(){}});assert.deepEqual(trimmedMasks[0],['static',1,17]);
timeline.callbacks.onSegmentSelect=selectMask;timeline.callbacks.onMaskTrim=trimMask;timeline.update(previousState);
{
 const saved={sourceInfo:workspace.sourceInfo,source:workspace.state.source,mask:workspace.state.mask,anchors:workspace.state.anchors,count:workspace.state.frameCount,start:workspace.state.startFrame,action:plate.action,limit:workspace.state.processingMegapixelLimit,custom:workspace.state.processingLimitCustom,engine:workspace.state.plateEngine,result:workspace.result};
 workspace.result=null;workspace.sourceInfo={path:'Z:/portrait.mov',width:2160,height:3840,fps:25,frames:160};Object.assign(workspace.state,{source:'Z:/portrait.mov',mask:'Z:/mask.mov',anchors:[{id:'portrait',frame:0,file:'Z:/clean.exr',status:'accepted',enabled:true}],frameCount:160,startFrame:0,processingMegapixelLimit:0,processingLimitCustom:false,plateEngine:'ltx'});plate.action='remove';workspace.render();
 await new Promise(resolve=>setTimeout(resolve,0));
 const popup=workspace.$('resolution'),select=workspace.$('processing-limit'),slider=workspace.$('megapixels');assert.equal(select.value,'0');assert.equal(workspace.config().width,2176);popup.open=true;select.value='1';select.onchange();assert.deepEqual([workspace.config().width,workspace.config().height],[704,1280]);assert.match(workspace.$('size-help').textContent,/Saved output: 2160.*3840/);assert.equal(popup.open,true);
 select.value='custom';select.onchange();for(const value of [.65,.75,.85]){slider.value=value;slider.oninput();assert.equal(workspace.state.processingMegapixelLimit,value);assert.equal(popup.open,true,'Dragging the MP slider keeps the popout open');assert.equal(workspace.$('megapixels'),slider);assert.ok(workspace.config().width*workspace.config().height<=value*1e6);}
 for(const action of ['paint','replace']){plate.action=action;plate.sync();assert.equal(popup.hidden,true,'The dedicated slider replaces the old dimensions popout in Add and Replace');assert.ok(plate.config().width*plate.config().height<=.85e6);assert.equal(plate.config().frameCount,160);assert.equal(plate.config().sequenceFps,25);assert.equal(plate.config().plateAction,action);}
 workspace.sourceInfo=saved.sourceInfo;Object.assign(workspace.state,{source:saved.source,mask:saved.mask,anchors:saved.anchors,frameCount:saved.count,startFrame:saved.start,processingMegapixelLimit:saved.limit,processingLimitCustom:saved.custom,plateEngine:saved.engine});plate.action=saved.action;popup.open=false;workspace.render();workspace.result=saved.result;surface.sync();
}
{
 const saved={action:plate.action,result:workspace.result,file:anchor.file,layers:anchor.layers,fetch:workspace.fetch,pick:workspace.api.fetchApi,references:owner.references,imageArea:owner.imageArea,frameChanged:editor.frameChanged,ensureProject:editor.ensureProject,edit:plate.editFrame,busy:workspace.busy};
 workspace.result=null;workspace.busy=()=>false;editor.frameChanged=async()=>true;editor.ensureProject=async()=>{};plate.editFrame=async()=>{opened++;};
 let opened=0;const actions=editor.timeline;const picker=editor.importFrame;let picked;
 editor.importFrame=async options=>{picked=options;};
 for(const operation of ['paint','replace','remove']){
  plate.action=operation;
  actions.update({stage:'clean',sourceFrames:18,startFrame:0,frameCount:18,playhead:0,anchors:[anchor],selected:0,busy:false});
  await actions.cards.querySelector('.zp-editor-frame-card__select').onclick({detail:1,stopPropagation(){}});
  assert.equal(editor.framePreview,true,operation+' previews the accepted frame');
  assert.equal(editor.tool,'pan');assert.equal(opened,0);
  assert.deepEqual([...actions.frameActions.querySelectorAll('button')].map(button=>button.textContent.trim()),['Edit frame','Save source frame','Import edited frame']);
  await actions.callbacks.onImportFrame(0);assert.deepEqual(picked,{atPlayhead:true});
  actions.closeFrameActions();
 }
 editor.importFrame=picker;
 plate.action='replace';surface.sync();
 assert.equal(surface.$('edit').hidden,true,'The timeline popout owns frame entry from the video view');
 assert.equal(editor.layersPanel.hidden,true,'Layer controls live in the frame editor');
 plate.inline={};surface.sync();
 assert.equal(surface.$('edit').textContent,'Back to video');
 assert.ok(!editor.layersPanel.hidden&&editor.layersPanel.querySelector('[data-edit-plate-layer]'),'Saved layers can be adjusted or opened from Edit frame');
 plate.inline=null;surface.sync();
 anchor.layers[0].edit_area={enabled:true,source_key:'old'};anchor.layers[0].operation='replace';
 await plate.editSavedLayer(anchor.layers[0]);assert.equal(anchor.plateEditLayerId,'one');assert.deepEqual(anchor.edit_area,anchor.layers[0].edit_area);
 await plate.startNewFrameEdit();assert.equal(anchor.plateEditLayerId,null);assert.equal(anchor.edit_area,null);assert.equal(anchor.layers.length,3);
 // A whole-image second result gets its own stable mask, and changes only its target layer on regeneration.
 const requests=[];owner.imageArea={layerMask:async()=>null};owner.references=[{file:'base.png'}];
 workspace.api.fetchApi=async()=>({ok:true,json:async()=>({file:'new-layer.png',colour_space:'srgb_display'})});
 workspace.fetch=async(path,body)=>{requests.push([path,body]);return {file:'composed.exr',colour_space:'srgb_display',derived_mask:'inferred-mask'};};
 const facade=plate.imageWorkspace();const newFile=new File(['test'],'new.png');
 await facade.importAnchorFile(anchor,newFile,()=>{});
 assert.equal(requests.at(-1)[1].derive_mask_for,3);
 assert.equal(anchor.layers.length,4);
 assert.equal(anchor.layers[3].layer_mask,'inferred-mask');
 const id=anchor.plateEditLayerId;
 workspace.fetch=async(path,body)=>{requests.push([path,body]);return {file:'composed-2.exr',colour_space:'srgb_display',derived_mask:'inferred-mask'};};
 await facade.importAnchorFile(anchor,newFile,()=>{});
 assert.equal(anchor.layers.length,4);assert.equal(anchor.plateEditLayerId,id);
 const request={id:'replace-preview',anchor},item={ripple_guide:request.id,file:{filename:'generated.png'},prompt:'replace the car'};
 const oldRipple=owner.rippleImage,oldRender=owner.render,oldGallery=owner.renderGallery,oldInputs=owner.editInputs;
 Object.assign(owner,{items:[item],selectedImage:0,editInputs:{showSource:false},render:()=>surface.sync(),renderGallery:()=>surface.sync(),rippleImage:{request,importing:false,current:r=>r===request,check(){},resultFile:async()=>newFile}});
 const savedLayers=anchor.layers,oldFile=anchor.file;
 plate.inline={};surface.sync();assert.equal(surface.$('run').disabled,true);
 await plate.frameDraft.ready;
 const panel=surface.draftLayerPanel,blend=panel.querySelector('[aria-label="Blend edge of paint layer 4"]');
 assert.equal(surface.$('run').textContent,'Save frame edit');assert.equal(surface.$('run').disabled,false);
 assert.match(panel.querySelector('li strong').textContent,/Draft/);
 assert.equal(blend.disabled,false);assert.equal(blend.closest('details').open,true);
 assert.equal(anchor.file,oldFile);assert.equal(anchor.layers,savedLayers);
 blend.value='24';await blend.onchange();
 assert.equal(requests.at(-1)[1].layers[3].blend_pixels,24);
 assert.equal(anchor.layers[3].blend_pixels,0,'A draft slider must not modify the saved keyframe');
 plate.commitFrameLayers(anchor,await plate.readyFrameDraft(request,item));
 assert.equal(anchor.layers[3].blend_pixels,24,'Save commits the feathered layer');
 plate.inline=null;plate.frameDraft=null;
 Object.assign(owner,{items:[],selectedImage:-1,render:oldRender,renderGallery:oldGallery,editInputs:oldInputs,rippleImage:oldRipple});
 Object.assign(anchor,{file:saved.file,layers:saved.layers,plateEditLayerId:null,edit_area:null});
 Object.assign(workspace,{result:saved.result,fetch:saved.fetch,busy:saved.busy});
 workspace.api.fetchApi=saved.pick;Object.assign(owner,{references:saved.references,imageArea:saved.imageArea});
 Object.assign(editor,{frameChanged:saved.frameChanged,ensureProject:saved.ensureProject});Object.assign(plate,{action:saved.action,editFrame:saved.edit});
}
{
 const previous=plate.action,source=workspace.sourceInfo,engine=workspace.state.plateEngine,scale=workspace.state.plateScale,chosen=workspace.state.plateProcessingMegapixels,result=workspace.result;
 workspace.result=null;workspace.sourceInfo={...source,width:1920,height:1080};
 workspace.state.plateScale=.5;
 for(const operation of ['paint','replace']){
  plate.action=operation;workspace.state.plateEngine='ltx';workspace.state.plateProcessingMegapixels=undefined;
  surface.sync();
  const slider=surface.$('megapixels');
  assert.equal(surface.$('processing').hidden,false);
  assert.equal(surface.$('scale-label').hidden,true);
  assert.equal(workspace.$('resolution').hidden,true);
  assert.match(surface.$('processing-size').textContent,/^960 × 576$/,'The old 50% setting is retained before a slider change');
  for(const model of ['ltx','h3']){
   workspace.state.plateEngine=model;
   slider.value=slider.max;slider.oninput();
   const large=plate.config();
   assert.equal(large.width,3072);assert.equal(large.height%(model==='ltx'?64:32),0);
   assert.equal(surface.$('processing-size').textContent,large.width+' × '+large.height);
   slider.value=slider.min;slider.oninput();
   const small=plate.config();
   assert.ok(small.width<=640&&small.height<=384);
   assert.equal(small.frameCount,workspace.state.frameCount);
  }
  surface.$('processing-native').click();
  assert.equal(workspace.state.plateProcessingMegapixels,0);
  assert.equal(plate.config().width,1920);
 }
 plate.action='remove';surface.sync();
 assert.equal(surface.$('processing').hidden,true);
 assert.equal(workspace.$('resolution').hidden,false);
 workspace.sourceInfo=source;workspace.result=result;Object.assign(workspace.state,{plateEngine:engine,plateScale:scale,plateProcessingMegapixels:chosen});
 plate.action=previous;surface.sync();
}
if(process.env.PAINT_LAYOUT_FIXTURE){
 if(process.env.PAINT_LAYOUT_TOOLS==='1'){
  const inputs=document.createElement('div');inputs.className='zc-image-tools';document.querySelector('main').append(inputs);const source=document.createElement('div');inputs.after(source);
  const imageOwner={root:document.querySelector('main'),draft:{},editInputs:{source},references:[],api:{apiURL:value=>value}};const area=new ImageEditArea(imageOwner);surface.$('brushes').append(area.tools);surface.syncImageTools();inputs.hidden=true;source.hidden=true;
  const link=document.createElement('link');link.rel='stylesheet';link.href=new URL('../web/studio_image_area.css',import.meta.url).href;document.head.append(link);
 }
 const noMotion=document.createElement('style');noMotion.textContent='*,*::before,*::after{transition:none!important;animation:none!important}';document.head.append(noMotion);
 surface.root.classList.add('has-source','has-clean-frame');surface.root.dataset.stage='clean';workspace.page.style.visibility='';workspace.page.hidden=false;
 surface.$('removal-flow').hidden=false;surface.root.querySelector('.zpx-prompt').hidden=false;surface.$('timeline').hidden=false;surface.$('prompt').value='Remove the object and keep the rest unchanged.';
 editor.guideTitle.textContent='Review clean frame';editor.guideHelp.textContent='Review the repair, or paint another area.';editor.$('continue').hidden=true;editor.$('render-next').hidden=false;editor.$('render-next').disabled=false;
 surface.$('run').hidden=true;surface.$('edit').hidden=true;surface.$('new-edit').hidden=true;surface.$('retry').hidden=true;surface.$('stop').hidden=true;editor.$('clean').hidden=false;editor.$('clean').textContent='Try again';editor.$('clean').disabled=false;
 workspace.page.querySelector('[data-paintout-style-status]')?.remove();document.querySelector('.gs-workspace').remove();
 const top=document.createElement('div');top.className='gs-top';top.textContent='Zura Studio · Add, remove & replace';workspace.page.before(top);
 const session=document.createElement('div');session.className='zc-ae-session';session.textContent='After Effects session · 32-bit EXR · Work area';workspace.page.before(session);
 const colour=document.createElement('div');colour.style.cssText='height:48px;flex-shrink:0';colour.textContent='Input: HDR   Output: SDR   View: sRGB';workspace.page.before(colour);
 globalThis.getComputedStyle=()=>({getPropertyValue:name=>name==='--zp-card-row-step'?'56':name==='--zp-card-lane-base'?'76':''});
 editor.timelineHost.hidden=false;editor.nav.hidden=false;editor.timeline.update({stage:'clean',sourceFrames:18,startFrame:0,frameCount:18,fps:30,playhead:0,anchors:[anchor],trimEditable:true});
 if(process.env.PAINT_LAYOUT_STAGE==='mask'){editor.stage='mask';workspace.state.mode='targeted';workspace.state.maskRevision=1;workspace.state.maskProject='fixture';editor.document={mask_segments:[{id:'mask-one',name:'Tracked mask',start:0,end:17,available_start:0,available_end:17,tracked:true},{id:'mask-two',name:'Static mask',start:0,end:17,available_start:0,available_end:17,tracked:false,ready:true},{id:'mask-three',name:'Imported mask',start:0,end:17,available_start:0,available_end:17,tracked:false,ready:true}],mask_coverage:Array.from({length:18},(_,i)=>i)};editor.updateControls();surface.sync();workspace.page.dataset.editorStage='mask';editor.timeline.update({...editor.timeline.state,stage:'mask',maskSegments:editor.document.mask_segments,selectedMask:'mask-two'});if(process.env.PAINT_LAYOUT_GENERATING==='1')workspace.page.classList.add('is-generating');}
 document.body.insertAdjacentHTML('beforeend',`<script>addEventListener('load',()=>requestAnimationFrame(()=>{const q=s=>document.querySelector(s).getBoundingClientRect();const report={width:innerWidth,height:innerHeight,rail:q('.zpx-rail').toJSON(),maskScroll:(()=>{const list=document.querySelector('.zp-editor-mask-lanes'),last=list?.querySelector('.zp-editor-mask-row:last-child');if(!last)return null;const before=list.scrollTop;list.scrollTop=list.scrollHeight;const box=list.getBoundingClientRect(),row=last.getBoundingClientRect(),visible=row.top>=box.top&&row.bottom<=box.bottom;list.scrollTop=before;return {visible,scrollHeight:list.scrollHeight,clientHeight:list.clientHeight};})(),maskLanes:[...document.querySelectorAll('.zp-editor-mask-row')].map(e=>({id:e.dataset.segment,row:e.getBoundingClientRect().toJSON(),lane:e.querySelector('.zp-editor-mask-lane').getBoundingClientRect().toJSON(),bar:e.querySelector('.zp-editor-mask-bar').getBoundingClientRect().toJSON()})),inlineTools:[...document.querySelectorAll('.zia-icon-tools button,.zia-icon-tools input,.zia-icon-tools output')].map(e=>({rect:e.getBoundingClientRect().toJSON(),label:e.getAttribute('aria-label')||e.tagName})),cleanAppearance:(()=>{const root=document.querySelector('.zplate-surface'),button=document.querySelector('[data-editor=clean]'),probe=document.createElement('span');root.append(probe);probe.style.background='var(--gs-input)';const input=getComputedStyle(probe).backgroundColor;probe.style.background='var(--gs-accent)';const accent=getComputedStyle(probe).backgroundColor;probe.remove();const ready=getComputedStyle(button).backgroundColor;root.classList.remove('has-clean-frame');const fresh=getComputedStyle(button).backgroundColor;root.classList.add('has-clean-frame');const track=getComputedStyle(document.querySelector('[data-editor=track]')).backgroundColor;return {ready,fresh,input,accent,track};})(),continueAncestors:(()=>{let e=document.querySelector('[data-editor=continue]'),a=[];while(e){a.push({tag:e.tagName,cls:e.className,hidden:e.hidden,disabled:e.disabled,display:getComputedStyle(e).display,visibility:getComputedStyle(e).visibility,rect:e.getBoundingClientRect().toJSON()});e=e.parentElement;}return a;})(),parts:[...document.querySelectorAll('.zp-editor-timeline,.zp-editor-timeline__header,.zp-editor-timeline__lanes,.zp-editor-timeline__clean-lane')].map(e=>({cls:e.className,height:e.getBoundingClientRect().height,padding:getComputedStyle(e).padding,margin:getComputedStyle(e).margin})),page:q('.zplate-page').toJSON(),view:q('.zpx-view').toJSON(),timeline:q('[data-plate-timeline]').toJSON(),ruler:q('.zp-editor-timeline__ruler').toJSON(),readout:q('.zp-editor-timeline__readout').toJSON(),handles:[...document.querySelectorAll('.zp-editor-trim-handle')].map(e=>e.getBoundingClientRect().toJSON())};document.body.setAttribute('data-geometry',JSON.stringify(report));}));</script>`);
 writeFileSync(process.env.PAINT_LAYOUT_FIXTURE,document.toString());
}
workspace.close();console.log('Compact surface: source disclosure, prompt position, eye/bin, four adjusters, drag/keyboard real-controller routing and disclosure persistence pass.');

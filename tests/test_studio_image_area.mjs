import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {ImageEditArea,imageAreaSourceKey} from '../web/studio_image_area.js';

const {document,window}=parseHTML('<html><body><main id="studio"><div class="zc-image-tools"><button id="toggle"></button><button id="compare"></button></div><div class="zc-image-scroll"><div id="source"></div><div id="zc-gallery"></div><div id="zc-image-empty"></div></div><div id="zc-reference-list"><div class="zc-edit-main"><button>Main image</button><details class="zi-references"><summary>References</summary></details></div></div></main></body></html>');
globalThis.document=document;globalThis.window=window;
if(!globalThis.crypto?.randomUUID)globalThis.crypto={randomUUID:()=>String(Math.random())};
const root=document.querySelector('main'),main={filename:'original.png',subfolder:'zura_images/references',file:'zura_images/references/original.png',width:1920,height:1080};
const calls=[];let reply=null,area;
const owner={root,mode:'image',imageOperation:'edit',editMainMissing:false,references:[main],items:[],selectedImage:-1,draft:{},
  editInputs:{source:document.querySelector('#source'),toggle:document.querySelector('#toggle'),showSource:false},
  imageComparison:{button:document.querySelector('#compare'),host:document.createElement('div'),active:false},
  api:{apiURL:value=>value,fetchApi:async(url,options)=>{calls.push({url,options});return reply?reply():{ok:true,json:async()=>({name:'painted.png',subfolder:'zura_images/edit_areas'})};}},
  $(id){return root.querySelector('#zc-'+id);},save(){this.saved=area?.config();},render(){area?.sync();},message(value){this.messageText=value;}};
area=new ImageEditArea(owner);
let disposed=0;
const viewer=()=>({maskPresent:false,history:[1],root:document.createElement('div'),width:1920,height:1080,
  maskCanvas:{width:1920,height:1080,toBlob(callback){callback(new Blob(['mask'],{type:'image/png'}));}},
  measureMask(){return this.maskPresent;},setBrushSize(){},setTool(tool){this.tool=tool;},fit(){},undo(){this.history.pop();},clear(kind){if(kind!=='guide')this.maskPresent=false;if(kind!=='area')this.sketchPresent=false;area.changed({kind});},dispose(){disposed++;}});
area.loadViewer=async()=>{area.viewer=viewer();area.loading.hidden=true;area.refreshTools();};

assert.equal(imageAreaSourceKey(main),'zura_images/references/original.png');
assert.equal(imageAreaSourceKey({subfolder:'folder',filename:'plate.png'}),'folder/plate.png');
area.sync();assert.equal(area.button.hidden,false);assert.equal(area.config(),null,'Whole-image editing is the default');
{
  const home=area.tools.parentElement,rail=document.createElement('nav');root.append(rail);rail.append(area.tools);area.inline=true;
  assert.doesNotThrow(()=>area.sync(),'Video inline mode keeps using the relocated toolbar controller');
  area.paintPalette.hidden=true;area.colour.closest('label').hidden=true;
  area.setPaintAPlateMode(true);
  assert.equal(area.paintPalette.hidden,false,'Entering video paint immediately reveals the shared swatches');
  assert.equal(area.colour.closest('label').hidden,false,'The custom picker follows the swatches');
  area.sync();
  assert.equal(area.tools.querySelector('[data-area-tool=draw]').hidden,false,'Paint stays available on the Add rail');
  assert.equal(area.tools.querySelector('[data-area-tool=brush]').hidden,true,'Add paints directly without a separate area-selection tool');
  assert.equal(area.tools.querySelector('.zia-colour').hidden,false,'Add keeps the paint colour picker visible');
  area.setPaintAPlateMode(false);area.inline=false;home.append(area.tools);rail.remove();
}
assert.equal(area.button.textContent,'Paint area to edit');
assert.ok(area.button.querySelector('svg'),'Paint action has a brush icon');
assert.equal(area.button.getAttribute('aria-label'),'Paint area to edit');
assert.equal(area.areaAttachment.slot.parentElement,owner.$('reference-list').querySelector('.zc-edit-main'),'Paint entry sits beside the main image and references');
assert.ok(area.areaAttachment.slot.nextElementSibling.matches('.zi-references'),'Paint action sits immediately beside the main image, before optional references');
assert.ok(area.guideAttachment.slot.previousElementSibling.matches('.zi-references'),'Paint guidance is a separate image input, outside Paint Area');
assert.equal(area.button.disabled,false);
const entry=area.button;
owner.$('reference-list').innerHTML='<div class="zc-edit-main"><button>Main image</button><details class="zi-references"><summary>References</summary></details></div>';
assert.equal(entry.isConnected,false,'Rebuilding image inputs detaches the old entry');
area.sync();assert.equal(area.button,entry);assert.equal(area.areaAttachment.slot.parentElement,owner.$('reference-list').firstElementChild,'Input rebuild remounts the same live paint control');assert.ok(area.areaAttachment.slot.nextElementSibling.matches('.zi-references'));
assert.equal(root.querySelectorAll('.zia-open').length,1,'Rendering never duplicates the paint entry');
owner.$('reference-list').replaceChildren();area.sync();assert.equal(area.areaAttachment.slot.parentElement,root.querySelector('.zc-image-tools'),'A minimal or rebuilding view retains its header fallback');
owner.$('reference-list').innerHTML='<div class="zc-edit-main"><button>Main image</button><details class="zi-references"><summary>References</summary></details></div>';area.sync();assert.equal(area.areaAttachment.slot.parentElement,owner.$('reference-list').firstElementChild);
owner.editMainMissing=true;area.sync();assert.equal(entry.hidden,false,'Edit mode advertises painting before an image is added');assert.equal(entry.disabled,true);assert.equal(entry.title,'Add a main image first');
entry.click();assert.equal(area.state.enabled,false,'A missing main image cannot open an edit selection');
owner.editMainMissing=false;area.sync();assert.equal(entry.disabled,false);
owner.imageOperation='create';area.sync();assert.equal(entry.hidden,true,'Create image mode does not advertise edit-only painting');
owner.imageOperation='edit';area.sync();assert.equal(entry.hidden,false);
area.guideButton.click();assert.equal(area.editorMode,'guide');assert.equal(area.state.enabled,false,'Painting guidance never enables the edit-area mask');
assert.equal(area.host.querySelector('[data-area-tool=brush]').hidden,true,'The guidance workspace does not offer the area brush');
assert.equal(area.host.querySelector('[data-area-tool=draw]').hidden,false);area.finishEditor();
area.button.click();assert.equal(area.host.hidden,false);assert.equal(area.state.enabled,true);assert.equal(owner.editInputs.source.hidden,true);
await assert.rejects(()=>area.prepare(),/Paint an edit area or choose Whole image/);
assert.deepEqual(await area.flush(),area.config(),'Flushing an empty optional selection does not block navigation');

area.viewer.maskPresent=true;area.changed();clearTimeout(area.saveTimer);
assert.equal(owner.saved.mask,null,'A dirty selection never persists an older mask');
owner.submitting=true;
const first=await area.prepare();owner.submitting=false;
assert.equal(first.source_key,main.file);assert.equal(first.mask.file,'zura_images/edit_areas/painted.png');
assert.equal(calls.at(-1).url,'/upload/image');assert.equal(calls.at(-1).options.body.get('subfolder'),'zura_images/edit_areas');
first.mask.file='modified-in-caller';assert.equal(area.config().mask.file,'zura_images/edit_areas/painted.png','Prepared job owns an immutable snapshot');

area.setParameter('context',999,512);area.setParameter('feather',-4,128);
assert.equal(area.config().context,512);assert.equal(area.config().feather,0);
const saved=area.config();area.useWholeImage();assert.equal(area.config(),null);
area.restore(saved);area.sync();assert.equal(area.config().mask.file,saved.mask.file,'A handoff can restore the saved source-bound selection');
area.editing=true;area.finishEditor({render:false});assert.equal(area.editing,false);assert.equal(area.config().mask.file,saved.mask.file,'Finishing paint retains the source-bound mask');
owner.items=[{file:{filename:'result.png'}}];owner.selectedImage=0;owner.editInputs.showSource=false;owner.$('gallery').hidden=true;owner.$('image-empty').hidden=true;area.sync();
assert.equal(area.host.hidden,true);assert.equal(owner.$('gallery').hidden,false,'Closing the paint overlay reveals the generated result');assert.equal(owner.$('image-empty').hidden,true);
owner.imageOperation='create';assert.equal(area.config(),null,'Creation cannot consume an edit mask');owner.imageOperation='edit';area.sync();

// A late upload from a replaced main image must never attach to the new image.
area.button.click();area.viewer.maskPresent=true;area.changed();clearTimeout(area.saveTimer);
let release,started;const startedPromise=new Promise(resolve=>started=resolve);
reply=()=>{started();return new Promise(resolve=>release=resolve);};
const pending=area.flush();await startedPromise;
owner.references=[{...main,filename:'different.png',file:'zura_images/references/different.png'}];area.sync();
release({ok:true,json:async()=>({name:'late.png',subfolder:'zura_images/edit_areas'})});
await assert.rejects(pending,/changed while it was saving/);
assert.equal(area.state.source_key,owner.references[0].file);assert.equal(area.state.mask,null);assert.equal(area.config(),null);

// Closing retains the dirty canvas until the background upload has completed.
reply=()=>({ok:true,json:async()=>({name:'saved-on-close.png',subfolder:'zura_images/edit_areas'})});
area.button.click();area.viewer.maskPresent=true;area.changed();clearTimeout(area.saveTimer);
const before=disposed;area.close();await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(area.state.mask.filename,'saved-on-close.png');assert.ok(disposed>before);area.open();assert.equal(area.closed,false);
area.reset();clearTimeout(area.saveTimer);
area.inline=true;area.refreshTools();assert.equal(area.editing,false,'Loading an inline frame does not force painting');
const drawButton=area.tools.querySelector('[data-area-tool=draw]');assert.equal(drawButton.disabled,false,'The visible rail can explicitly open painting before a canvas exists');drawButton.click();assert.equal(area.editing,true);
area.finishEditor();area.tools.querySelector('[data-area-tool=brush]').click();assert.equal(area.viewer.tool,'brush','Reopening a cached canvas applies the explicitly chosen tool');
area.finishEditor();drawButton.click();assert.equal(area.viewer.tool,'draw');area.reset();
console.log('Image edit area: optional selection, upload ownership, handoff, stale-source protection and close flush pass.');

// Leaving paint mode retains a source-bound, pan-only preview, never on results.
owner.references=[main];owner.editMainMissing=false;owner.mode='image';owner.imageOperation='edit';owner.editInputs.showSource=true;
area.restore({enabled:true,source_key:main.file,mask:{filename:'mask.png',file:'mask.png'}});area.viewer=viewer();area.editing=true;area.viewer.maskPresent=true;
area.finishEditor();assert.equal(area.host.hidden,false);assert.equal(area.viewer.tool,'pan');
assert.equal(area.host.querySelector('.zia-toolbar').hidden,true);
owner.editInputs.showSource=false;area.sync();assert.equal(area.host.hidden,true,'A source mask must not overlay a generated result');
owner.editInputs.showSource=true;area.useWholeImage();assert.equal(area.host.hidden,true,'Whole image removes preview');
const {selectionPreviewPixels}=await import('../web/studio_image_area_preview.js');
const input=new Uint8ClampedArray(17*17*4);for(let y=2;y<15;y++)for(let x=2;x<15;x++)input[(y*17+x)*4]=255;
const maskBefore=input.slice(),preview=selectionPreviewPixels(input,17,17);
assert.equal(preview[(8*17+8)*4+3],200,'Interior produces about 35% visible fill at default .45 opacity');
assert.deepEqual([...preview.slice((2*17+8)*4,(2*17+8)*4+4)],[255,255,255,255],'High-contrast boundary follows the source mask');
assert.equal(preview[3],0);assert.deepEqual(input,maskBefore,'Display construction never mutates the inference mask');
input[(8*17+8)*4]=0;assert.equal(selectionPreviewPixels(input,17,17)[(8*17+7)*4+3],255,'Internal holes have a visible boundary');
const zoomed=selectionPreviewPixels(maskBefore,17,17,{scale:.25});assert.equal(zoomed[(6*17+8)*4+3],255,'Boundary expands in source pixels when zoomed out');
console.log('Image selection: retained source preview, result isolation and exact raster boundary pass.');


const {installShotSelectionPreview}=await import('../web/studio_image_area_preview.js');
let shotState={key:'source/frame35/mask1',mask:{file:'mask1'}},resolveShot,painted=[],baseDraws=0;
const shotViewer={width:1920,height:1080,transform:()=>({x:21,y:-8,scale:.5}),ctx:{save(){},restore(){},drawImage(...args){painted.push(args);}},draw(){baseDraws++;}};
installShotSelectionPreview(shotViewer,()=>shotState,()=>new Promise(resolve=>{resolveShot=resolve;}));
shotViewer.draw();await Promise.resolve();shotState=null;resolveShot('stale-mask');await new Promise(resolve=>setImmediate(resolve));
assert.equal(painted.length,0,'A late mask load cannot survive leaving its source/frame');
shotState={key:'source/frame35/mask2',mask:{file:'mask2'}};shotViewer.draw();await Promise.resolve();resolveShot('current-mask');await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(painted.at(-1),['current-mask',21,-8,960,540],'Shot ROI follows the native source transform at any zoom/pan');
shotState=null;painted=[];shotViewer.draw();assert.equal(painted.length,0,'Clear, whole image, result and unrelated frame remove shot ROI');
assert.ok(baseDraws>=4,'Native viewer drawing is preserved');
console.log('Back to shot: asynchronous source ownership, native zoom/pan and clear pass.');

// Reopening normal Image Edit restores a saved ROI without entering paint mode.
area.inline=false;owner.editInputs.showSource=true;owner.editInputs.toggle.hidden=false;
area.restore({enabled:true,source_key:main.file,mask:{filename:'saved-reopen.png',file:'saved-reopen.png'}});
area.sync();assert.equal(area.host.hidden,false);assert.equal(area.editing,false);
assert.ok(area.viewer,'Saved closed selection lazily recreates its display viewer');
assert.equal(owner.editInputs.toggle.hidden,false,'Readonly preview preserves the normal source/result toggle');
owner.editInputs.showSource=false;area.sync();assert.equal(area.host.hidden,true);
owner.editInputs.showSource=true;area.sync();assert.equal(area.host.hidden,false,'Returning to main image restores the saved ROI');
area.reset();area.sync();assert.equal(area.host.hidden,true,'Reset removes remembered ROI');
console.log('Normal Image Edit: saved closed ROI survives reopen and source/result toggles.');

// Saved coloured strokes and ROI stay separate from source/inference canvases.
let loadCount=0,failShot=true,requestedState;
const sourceSentinel={untouched:true},maskSentinel={file:'roi.png'},sketchSentinel={file:'colour.png'};
shotState={key:'source/frame35/roi/colour1',mask:maskSentinel,sketch:sketchSentinel};painted=[];
const colouredViewer={...shotViewer,draw(){}};
installShotSelectionPreview(colouredViewer,()=>shotState,async(mask,state)=>{
  loadCount++;requestedState=state;assert.equal(mask,maskSentinel);if(failShot)throw Error('Temporary mask read failure');
  return {selection:'roi-raster',sketch:'coloured-raster'};
});
colouredViewer.draw();await new Promise(resolve=>setImmediate(resolve));assert.equal(loadCount,1,'Failure does not trigger an automatic draw/load loop');
failShot=false;colouredViewer.draw();await new Promise(resolve=>setImmediate(resolve));assert.equal(loadCount,2,'A later external draw retries the same saved selection');
assert.equal(requestedState.sketch,sketchSentinel,'Loader receives the saved drawing belonging to this selection');
assert.deepEqual(painted.slice(-2),[['coloured-raster',21,-8,960,540],['roi-raster',21,-8,960,540]],'Colour and ROI share the exact source zoom/pan transform');
assert.deepEqual(maskSentinel,{file:'roi.png'});assert.deepEqual(sketchSentinel,{file:'colour.png'});assert.deepEqual(sourceSentinel,{untouched:true});
shotState=null;painted=[];colouredViewer.draw();assert.equal(painted.length,0,'Leaving the matching shot hides both colour and ROI');
console.log('Back to shot coloured drawing, read-only compositing and controlled retry pass.');

const {shotSelectionSourceVisible}=await import('../web/studio_image_area_preview.js');
assert.equal(shotSelectionSourceVisible({frame:35},false),true,'A source draft displays remembered drawing and ROI');
assert.equal(shotSelectionSourceVisible({frame:35,file:'accepted.png'},false),false,'Accepted generated preview remains clean');
assert.equal(shotSelectionSourceVisible({frame:35,file:'accepted.png'},true),true,'Show original restores the source drawing and ROI');
assert.equal(shotSelectionSourceVisible(null,true),false);

const {PaintoutMaskViewer}=await import('../web/paintout_studio/paintout_viewer.js');
const normalPaints=[],normalCtx={clearRect(){},save(){},restore(){},drawImage(asset){normalPaints.push(asset);}};
const displayCanvas={getContext:()=>({createImageData:()=>({data:new Uint8ClampedArray(4)}),putImageData(){}})};
const normalViewer={ctx:normalCtx,image:'source-raster',sketchPresent:true,sketchCanvas:'saved-coloured-strokes',width:1,height:1,maskVersion:1,opacity:.5,tool:'pan',positive:[],negative:[],cursor:null,overlay:'native-mask',buildOverlay(){},transform:()=>({x:0,y:0,scale:1}),maskCtx:{getImageData:()=>({data:new Uint8ClampedArray([255,255,255,255])})},draw:PaintoutMaskViewer.prototype.draw};
ImageEditArea.prototype.installSelectionPreview.call({owner:{root:{ownerDocument:{createElement:()=>displayCanvas}}},state:{enabled:true},isCurrent:()=>true},normalViewer);
assert.deepEqual(normalPaints.slice(0,2),['source-raster','saved-coloured-strokes'],'Closed normal Image Edit keeps the actual saved coloured drawing through native viewer draw');
assert.equal(normalPaints.at(-1),displayCanvas,'Exact ROI is a separate display layer');
assert.equal(normalViewer.opacity,.5,'Readonly compositing preserves user opacity');

// An unavailable display raster must not leak canvas alpha/smoothing into the next frame.
const throwingContext=()=>({globalAlpha:.37,imageSmoothingEnabled:true,stack:[],fail:false,
  save(){this.stack.push([this.globalAlpha,this.imageSmoothingEnabled]);},
  restore(){[this.globalAlpha,this.imageSmoothingEnabled]=this.stack.pop();},
  drawImage(){if(this.fail)throw Error('Unavailable display raster');}});
const selectionFailureCtx=throwingContext();selectionFailureCtx.fail=true;
const selectionFailureViewer={...normalViewer,ctx:selectionFailureCtx,draw(){}};
assert.throws(()=>ImageEditArea.prototype.installSelectionPreview.call({owner:{root:{ownerDocument:{createElement:()=>displayCanvas}}},state:{enabled:true},isCurrent:()=>true},selectionFailureViewer),/Unavailable display raster/);
assert.equal(selectionFailureCtx.globalAlpha,.37);assert.equal(selectionFailureCtx.imageSmoothingEnabled,true);assert.equal(selectionFailureCtx.stack.length,0);
assert.equal(selectionFailureViewer.opacity,.5,'A failed selection draw preserves the viewer opacity');
const shotFailureCtx=throwingContext(),shotFailureViewer={width:1,height:1,opacity:.45,ctx:shotFailureCtx,transform:()=>({x:0,y:0,scale:1}),draw(){}};
installShotSelectionPreview(shotFailureViewer,()=>({key:'throwing-display',mask:{file:'kept-mask'}}),async()=>({selection:'display-only-selection',sketch:'display-only-guide'}));
shotFailureViewer.draw();await new Promise(resolve=>setImmediate(resolve));shotFailureCtx.fail=true;
assert.throws(()=>shotFailureViewer.draw(),/Unavailable display raster/);
assert.equal(shotFailureCtx.globalAlpha,.37);assert.equal(shotFailureCtx.imageSmoothingEnabled,true);assert.equal(shotFailureCtx.stack.length,0);
console.log('Display overlay draw errors propagate after restoring canvas alpha and smoothing.');

// Exercise normal controller render ordering, including its real resultKey logic.
const {ImageEditInputs}=await import('../web/studio_image_edit_inputs.js');
const normalInputs=Object.create(ImageEditInputs.prototype);
normalInputs.owner=owner;normalInputs.heading=document.createElement('strong');normalInputs.addHome=document.createElement('div');normalInputs.addReferences=document.createElement('button');normalInputs.addLabel='Add';normalInputs.clear=document.createElement('button');normalInputs.toggle=document.createElement('button');normalInputs.source=owner.editInputs.source;normalInputs.source.innerHTML='<figure><img></figure>';normalInputs.sourceZoom={update(){}};
const heading=document.createElement('div');heading.className='zc-image-heading';heading.innerHTML='<h2></h2>';root.append(heading);
for(const id of ['reference-hint','generate']){const field=document.createElement('div');field.id='zc-'+id;root.append(field);}
owner.$('reference-list').replaceChildren();owner.imageComparison.render=()=>{};owner.imageArea=area;owner.editInputs=normalInputs;
owner.render=()=>{normalInputs.sync();area.sync();};owner.items=[{file:{filename:'earlier.png'}}];owner.selectedImage=0;
area.restore({enabled:true,source_key:main.file,mask:{filename:'kept.png',file:'kept.png'}});owner.render();
area.openEditor('draw');owner.items=[{file:{filename:'new-result.png'}}];owner.render();
assert.equal(normalInputs.showSource,true,'A changed result identity cannot silently switch away from the source while painting');
normalInputs.showSource=false;area.finishEditor();
assert.equal(normalInputs.showSource,true,'Done explicitly returns to the painted source');
assert.equal(area.host.hidden,false,'Real normal input sync and area sync preserve the closed ROI');
assert.equal(normalInputs.source.hidden,true,'The ordinary unpainted source cannot cover the saved ROI viewer');
assert.equal(owner.$('gallery').hidden,true,'The generated result cannot cover the saved ROI viewer');
normalInputs.toggle.onclick=()=>{normalInputs.showSource=!normalInputs.showSource;normalInputs.sync();};normalInputs.toggle.click();
assert.equal(area.host.hidden,true,'An explicit View result still presents a clean result');
normalInputs.toggle.click();assert.equal(area.host.hidden,false,'View main image restores the remembered ROI');
console.log('Real ImageEditInputs render ordering: result changes during painting, Done and normal toggles pass.');

// A completed image-layer edit becomes the selected result and the next edit
// input. The result should be visible, and returning to the main image must
// load that new composite instead of the old painted source raster.
const {StudioImageLayers}=await import('../web/studio_image_layers.js');
const composite={filename:'current-blue.png',subfolder:'zura_images/layers',type:'input',file:'zura_images/layers/current-blue.png'};
const compositeItem={file:{filename:'result-blue.png',type:'output'},image_layers:{schemaVersion:1,source:main,conditioningInput:composite,width:1920,height:1080,layers:[{id:'blue-layer'}]}};
owner.items=[compositeItem];owner.selectedImage=0;owner.references=[main];
area.restore({enabled:true,source_key:main.file,mask:{filename:'kept.png',file:'kept.png'}});
area.viewer={...viewer(),image:'old-red-raster',sourceKey:main.file,maskPresent:true};
const beforeCompositeDispose=disposed;
const imageLayers=Object.create(StudioImageLayers.prototype);imageLayers.owner=owner;
imageLayers.selectInput(compositeItem);
assert.equal(owner.references[0].file,composite.file,'The accepted composite is the next edit input');
assert.equal(area.state.source_key,composite.file,'The saved edit area is rebound to the current composite');
assert.equal(area.viewer,null,'The old red source raster is discarded when the main input changes');
assert.ok(disposed>beforeCompositeDispose,'The old viewer releases its canvas');
normalInputs.sync();area.sync();
assert.equal(normalInputs.showSource,false,'A selected composite keeps the generated result visible by default');
assert.equal(owner.$('gallery').hidden,false,'The completed result is not covered by the old source');
assert.equal(normalInputs.toggle.getAttribute('aria-label'),'View main image');
const loaded=[];const loadViewerBeforeComposite=area.loadViewer;
area.loadViewer=async(source,key)=>{loaded.push(source.file);area.viewer={...viewer(),image:'current-blue-raster',sourceKey:key,maskPresent:true};area.loading.hidden=true;area.refreshTools();};
normalInputs.toggle.click();
assert.equal(normalInputs.showSource,true);
assert.deepEqual(loaded,[composite.file],'View main image reloads the accepted composite raster');
assert.equal(area.viewer.image,'current-blue-raster');
area.button.click();assert.equal(area.editing,true,'Iterative painting starts on the current composite');
assert.equal(area.viewer.image,'current-blue-raster');
area.finishEditor();assert.equal(normalInputs.showSource,true,'Done returns to the composite that was just painted');
owner.references=[{...main,filename:'manually-uploaded.png',file:'zura_images/references/manually-uploaded.png'}];
normalInputs.sync();area.sync();
assert.equal(normalInputs.showSource,true,'A user-chosen new main image still defaults to its source view');
assert.equal(area.state.mask,null,'A manual source change clears the previous composite selection');
area.loadViewer=loadViewerBeforeComposite;
owner.references=[main];owner.items=[];owner.selectedImage=-1;area.reset();
console.log('Image edit completion shows the result, reloads the current composite for painting and keeps manual uploads source-first.');

// A guide can condition a whole-image edit without fabricating an ROI.
area.restore({enabled:false,source_key:main.file});
const originalCreate=document.createElement.bind(document),composited=[];
document.createElement=(tag,...args)=>tag==='canvas'?{
  width:0,height:0,getContext:()=>({drawImage(image){composited.push(image);}}),
  toBlob(callback){callback(new Blob(['composite'],{type:'image/png'}));},
}:originalCreate(tag,...args);
let guideUploads=0;reply=()=>({ok:true,json:async()=>({name:`guide-${++guideUploads}.png`,subfolder:'zura_images/edit_areas'})});
const guideViewer=viewer();guideViewer.width=1920;guideViewer.height=1080;guideViewer.image={pixels:'original source'};
guideViewer.sketchPresent=true;guideViewer.sketchCanvas={toBlob(callback){callback(new Blob(['coloured sketch'],{type:'image/png'}));}};
area.viewer=guideViewer;area.changed({kind:'guide'});clearTimeout(area.saveTimer);
const guideOnly=await area.prepare();document.createElement=originalCreate;
assert.equal(guideOnly.enabled,false,'Guidance alone leaves Paint Area off');
assert.equal(guideOnly.mask,null,'No binary selection is invented');
assert.equal(guideOnly.guide.file,'zura_images/edit_areas/guide-2.png');
assert.equal(guideUploads,2,'The sketch and source-composited guidance are stored separately');
assert.equal(composited[0],guideViewer.image,'The guidance composite uses the original source raster');
assert.equal(composited[1],guideViewer.sketchCanvas);
area.finishEditor({render:false});assert.equal(area.config().guide.file,guideOnly.guide.file);
area.restore(guideOnly);assert.equal((await area.prepare()).guide.file,guideOnly.guide.file,'A reopened guide-only edit retains its model input');
const mask={file:'retained-mask.png',filename:'retained-mask.png'};
area.restore({...guideOnly,enabled:true,mask});
area.sync();
assert.equal(area.areaAttachment.remove.hidden,false);
assert.equal(area.guideAttachment.remove.hidden,false);
area.guideAttachment.remove.click();
assert.equal(area.state.sketch,null);
assert.equal(area.config().guide,null);
assert.equal(area.config().mask.file,mask.file,'Deleting guidance preserves the edit area');
area.restore({...guideOnly,enabled:true,mask});
area.sync();
area.areaAttachment.remove.click();
assert.equal(area.config().mask,null);
assert.equal(area.config().guide.file,guideOnly.guide.file,'Deleting the edit area preserves guidance');
console.log('Guide-only painting: independent upload, original-pixel composite and restore pass.');

import {selectionPreviewPixels,installShotSelectionPreview,shotSelectionSourceVisible} from './studio_image_area_preview.js';
import {PlateSurface} from './studio_plate_surface.js';
import {aeFrameConfig} from './studio_ae_frame_contract.js';
import {workspaceStorage} from './studio_storage.js';
import {platePrompt,platePromptDrafts,savePlatePrompt} from './studio_plate_prompts.js';
import {rippleStudioProcessingSize,rippleStudioValidation} from './studio_ripple_recipes.js';
import {megapixelMaximum,resolutionSize,sourceMegapixelLimit,VIDEO_CANVAS_LIMITS} from './studio_resolution.js';
import {paintLayerRequest} from './paintout_studio/paintout_editor.js';

const KEY='zura-plate-action-v1';
const PROCESSING_MIN_MP=.2;
const PROCESSING_MAX_EDGE=3072;
const actions=[['paint','Add','Draw an addition and refine it with AI'],['remove','Remove','Mask the object, make clean frames, then render the removal'],['replace','Replace','Use edited frames to replace or change something']];
const copy=value=>JSON.parse(JSON.stringify(value));
const byFile=path=>String(path||'').replaceAll('\\','/');

/** Paintout owns the canvas, timeline, layers and project for every operation.
 * Ripple is only the Paint/Replace processing engine. Legacy adapters stay typed.
 */
export class PlateWorkspace{
  constructor(owner){this.owner=owner;this.storage=workspaceStorage(owner);this.action=this.storage.getItem(KEY)||'remove';if(!actions.some(([id])=>id===this.action))this.action='remove';this.switching=false;this.revision=0;}
  current(){return this.owner.paintout;}
  active(){return this.owner.mode==='paintout';}
  propagation(){return this.action!=='remove';}
  jobBusy(){const w=this.primary;return !!(w&&(w.job||w.submitting||w.picking||w.exporting||w.editor?.toolJob||w.editor?.maskStarting||w.editor?.submitting||w.editor?.importing||w.editor?.referenceUploading)||this.inline&&(this.owner.job||this.owner.pendingSubmission||this.owner.submitting||this.owner.uploading)||this.runner&&(this.runner.job||this.runner.pendingSubmission||this.runner.submitting));}
  // Explicit compatibility modes retain their own saved instruction. Merely
  // restoring one must not classify it as a new Remove/Add/Replace draft.
  legacyPromptMode(){const mode=this.primary?.state.mode;return ['inpaint','ripple'].includes(mode)?mode:null;}
  rememberPrompt(value,action=this.action){const w=this.primary;if(!w)return;const legacy=this.legacyPromptMode();if(legacy)w.prompts[legacy]=String(value);else savePlatePrompt(w.state,action,value);if(legacy||action==='remove'){w.cleanupPrompt=String(value);w.$('prompt').value=String(value);if(w.editor?.$?.('instruction'))w.editor.$('instruction').value=String(value);}}
  applyPrompt(){const w=this.primary;if(!w)return;const legacy=this.legacyPromptMode(),value=legacy?w.$('prompt').value:platePrompt(w.state,this.action);w.$('prompt').value=value;if(legacy||this.action==='remove'){w.cleanupPrompt=value;if(w.editor?.$?.('instruction'))w.editor.$('instruction').value=value;}this.promptDraft=platePromptDrafts(w.state);}
  async select(action=this.action){
    if(!actions.some(([id])=>id===action)||this.switching)return;
    const o=this.owner,w=o.paintout;if(w?.editor?.loadingProject)await w.editor.ensureProject();if(w?.busy())return;if(o.rippleImage?.request?.workspace?.platePrimary){await o.rippleImage.leave();if(o.rippleImage.request)return;}
    this.switching=true;
    try{
      if(w?.editor){await w.editor.flushManual();await w.editor.persist();}
      const previousAction=this.action;
      if(w&&this.promptDraft&&this.promptDraft===w.state.platePrompts)this.rememberPrompt(w.$('prompt').value,previousAction);
      this.action=action;this.storage.setItem(KEY,action);o.show('paintout');this.attach(o.paintout);this.action=action;
      const primary=o.paintout;primary.state.plateAction=action;
      this.paintAutoOpen=this.propagation();
      // Never change conditioning or discard anchors when choosing an operation.
      const enteringRemove=previousAction!=='remove'&&action==='remove',staleFull=enteringRemove&&primary.state.mode==='full';
      if(staleFull){const removalPrompt=primary.$('prompt').value;primary.setMode('targeted');primary.$('prompt').value=removalPrompt;}
      else if(primary.state.mode==='ripple'||primary.state.mode==='inpaint')primary.setMode('targeted');
      this.applyPrompt();
      if(!this.propagation()&&enteringRemove&&primary.state.source&&primary.state.clipTrimConfirmed&&(staleFull||!(primary.state.mask||primary.state.maskProject&&primary.state.maskRevision!=null)))await primary.editor.setStage('mask');
      if(this.propagation()&&primary.state.source&&primary.state.clipTrimConfirmed&&primary.editor.stage==='mask')await primary.editor.setStage('clean');
      if(this.propagation()){const runner=this.ensureRunner();runner.state.engine=primary.state.plateEngine;void runner.checkModels();}
      primary.save();primary.render();o.videoComposer?.syncWorkflow();
    }catch(error){o.paintout?.message(error.message);}
    finally{this.switching=false;this.sync();}
  }
  attach(w){
    if(!w||this.primary===w)return;this.primary=w;w.plate=this;
    if(w.state.plateAction&&actions.some(([id])=>id===w.state.plateAction))this.action=w.state.plateAction;
    w.state.plateEngine=['ltx','h3'].includes(w.state.plateEngine)?w.state.plateEngine:'ltx';w.state.plateScale=Number(w.state.plateScale)||1;
    const doc=w.page.ownerDocument;
    installShotSelectionPreview(w.editor.viewer,()=>{
      const e=w.editor,a=e.selected(),area=a?.edit_area;
      if(this.inline||!this.active()||!this.propagation()||e.stage!=='clean'||e.frameLoading||e.candidate||!shotSelectionSourceVisible(a,e.showOriginal)||a.frame!==w.playhead||a.frame!==e.viewer.frame||!area?.enabled||!area.mask?.filename)return null;
      return {key:JSON.stringify([w.state.source,a.id,a.frame,area.source_key,area.mask.file,area.mask.filename,area.mask.subfolder,area.sketch]),mask:area.mask,sketch:area.sketch};
    },async(mask,state)=>{
      const load=async ref=>{
        const image=new Image();await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;image.src=this.owner.api.apiURL('/view?'+new URLSearchParams({filename:ref.filename,subfolder:ref.subfolder||'',type:'input'}));});return image;
      };
      const [image,sketch]=await Promise.all([load(mask),state.sketch?.filename?load(state.sketch):null]);
      const canvas=doc.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
      const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(image,0,0);const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);
      pixels.data.set(selectionPreviewPixels(pixels.data,canvas.width,canvas.height));ctx.putImageData(pixels,0,0);return {selection:canvas,sketch};
    });
    this.strip=doc.createElement('nav');this.strip.className='zplate-actions';this.strip.setAttribute('aria-label','Edit operation');
    for(const [id,label,title]of actions){const b=doc.createElement('button');b.type='button';b.textContent=label;b.title=title;b.dataset.plateAction=id;b.onclick=()=>void this.select(id);this.strip.append(b);}
    w.page.querySelector('.zf-heading').after(this.strip);
    const viewer=w.page.querySelector('.zf-viewer');this.canvasShell=doc.createElement('div');this.canvasShell.className='zplate-canvas-shell';viewer.before(this.canvasShell);this.canvasShell.append(viewer);this.sidebar=doc.createElement('aside');this.sidebar.className='zplate-sidebar';this.sidebar.setAttribute('aria-label','Edits and layers');this.sidebar.append(w.editor.layersPanel,w.editor.tools);w.page.append(this.sidebar);this.canvasShell.after(w.$('message'));w.$('message').classList.add('zplate-feedback');
    this.frameToolbar=doc.createElement('div');this.frameToolbar.className='zplate-frame-toolbar';this.frameButton=doc.createElement('button');this.frameButton.type='button';this.frameButton.className='gs-primary';this.frameButton.onclick=()=>this.editFrame();this.newEditButton=doc.createElement('button');this.newEditButton.type='button';this.newEditButton.textContent='New edit';this.newEditButton.title='Start another edit while keeping the existing layers';this.newEditButton.onclick=()=>this.startNewFrameEdit();this.frameToolbar.append(this.frameButton,this.newEditButton);w.editor.viewerHost.prepend(this.frameToolbar);
    w.$('prompt').addEventListener('input',()=>{this.rememberPrompt(w.$('prompt').value);w.save();});
    this.trimButton=doc.createElement('button');this.trimButton.type='button';this.trimButton.textContent='Trim clip';this.trimButton.onclick=()=>w.editor.setStage('trim');w.page.querySelector('.zf-heading').append(this.trimButton);
    this.engine=doc.createElement('label');this.engine.className='zc-tool zplate-engine';this.engine.innerHTML='<span>Video model</span><select aria-label="Video processing model"><option value="ltx">LTX 2.5</option><option value="h3">MiniMax H3</option></select>';
    w.page.querySelector('.zf-model').parentElement.after(this.engine);
    this.engine.querySelector('select').value=w.state.plateEngine;
    this.engine.querySelector('select').onchange=()=>{if(w.busy())return;w.state.plateEngine=this.engine.querySelector('select').value;if(this.runner)this.runner.state.engine=w.state.plateEngine;this.revision++;w.save();this.runner?.checkModels();w.render();};
    const setup=w.openModelSetup.bind(w);w.openModelSetup=scope=>this.propagation()?this.ensureRunner().openModelSetup(w.state.plateEngine):setup(scope);
    const render=w.render.bind(w),generate=w.generate.bind(w),graph=w.graph.bind(w),cancel=w.cancel.bind(w),busy=w.busy.bind(w);
    this.nativeGenerate=generate;this.nativeGraph=graph;this.nativeBusy=busy;
    w.render=(...args)=>{const value=render(...args);this.syncControls();return value;};
    w.busy=()=>busy()||!!(this.inline&&(this.owner.job||this.owner.pendingSubmission||this.owner.submitting||this.owner.uploading))||!!(this.runner&&(this.runner.job||this.runner.pendingSubmission||this.runner.submitting));
    w.generate=()=>this.propagation()?this.generate():generate();w.graph=()=>this.propagation()?this.ensureRunner().graph():graph();w.cancel=()=>this.runner?.job||this.runner?.pendingSubmission?this.runner.onCancel():cancel();
    this.frameActions=w.page.querySelector('.zp-frame-actions');this.frameActionsHome=this.frameActions?.parentElement;
    const editor=w.editor,update=editor.updateControls.bind(editor),clean=editor.$('clean').onclick,confirm=editor.confirmClipTrim.bind(editor);
    this.nativeEditorUpdate=update;
    editor.updateControls=(...args)=>{const result=update(...args);this.syncControls();return result;};
    editor.$('clean').onclick=event=>this.propagation()?this.editFrame():clean(event);
    editor.confirmClipTrim=async()=>{if(editor.loadingProject)await editor.ensureProject();this.paintAutoOpen=this.propagation();await confirm();if(this.propagation()&&w.state.clipTrimConfirmed&&!w.busy()){if(editor.stage!=='clean')await editor.setStage('clean');this.syncControls();}};
    const setMode=w.setMode.bind(w);w.setMode=(...args)=>{const result=setMode(...args);this.applyPrompt();w.save();return result;};
    const reset=w.resetSource.bind(w);w.resetSource=async()=>{if(this.inline){await this.owner.rippleImage.leave();if(this.inline)return false;}const success=await reset();if(success!==false){delete w.state.platePrompts;this.applyPrompt();this.revision++;if(this.runner&&!this.runner.busy())this.runner.reset();w.save();}return success;};
    for(const key of ['onSeek','onCreate','onSelect','onRemove','onEditFrame','onExportFrame','onImportFrame']){
      const callback=editor.timeline.callbacks[key];
      editor.timeline.callbacks[key]=async(...args)=>{
        if(this.timelineSwitch||w.busy()||this.owner.rippleImage?.importing)return false;
        if(key==='onSelect')this.paintAutoOpen=false;
        this.timelineSwitch=true;
        try{if(this.inline){await this.owner.rippleImage.leave();if(this.inline)return false;}
          const loaded=await callback(...args);
          if(this.propagation()&&key==='onCreate'){
            // The frame must be visible before opening the inline Image editor.
            // createFrame already starts this load; do not race it
            // with a second request for the same 4K source frame.
            if(loaded===false)return;
            if(loaded!==true&&(await editor.frameChanged(true))===false)return;
            if(!w.busy())await this.editFrame();
          }
          return loaded;
        }catch(error){w.message(error.message);return false;}finally{this.timelineSwitch=false;}
      };
    }
    this.surface=new PlateSurface(this);const message=w.message.bind(w);w.message=value=>{message(value);this.surface.sync();};
    this.syncControls();
  }
  sync(){if(this.active()){this.attach(this.owner.paintout);this.syncControls();}}
  syncControls(){
    const w=this.primary;if(!w)return;const propagation=this.propagation(),e=w.editor,busy=w.busy();
    e.viewer?.draw();
    if(this.promptDraft!==platePromptDrafts(w.state))this.applyPrompt();
    if(this.lastPropagation===true&&!propagation)this.nativeEditorUpdate?.();this.lastPropagation=propagation;
    w.page.classList.add('zplate-page');w.page.dataset.plateAction=this.action;
    w.page.querySelector('h2').textContent='Add, remove & replace';w.$('new').textContent='Start over';
    for(const b of this.strip.querySelectorAll('button')){b.disabled=this.switching||busy;b.setAttribute('aria-pressed',String(b.dataset.plateAction===this.action));}
    if(this.frameActions){const host=!this.surface&&propagation?this.frameToolbar:this.frameActionsHome;if(host&&this.frameActions.parentElement!==host)host.append(this.frameActions);}
    this.frameToolbar.hidden=!(propagation&&e.stage==='clean');this.frameButton.textContent=this.action==='paint'?'Draw / edit frame':'Edit frame';this.frameButton.disabled=busy||!e.selected();this.newEditButton.disabled=busy||!e.selected();this.newEditButton.hidden=!e.selected()?.layers?.length;e.viewerToolbar.hidden=propagation;
    this.trimButton.disabled=busy||!w.state.source;this.trimButton.hidden=!w.state.source;
    this.engine.hidden=!propagation;this.engine.querySelector('select').disabled=busy;
    w.page.querySelector('.zf-model').parentElement.hidden=propagation;
    w.$('resolution').hidden=!!this.inline;
    e.nav.querySelector('[data-stage=mask]').hidden=propagation;
    e.nav.querySelector('[data-stage=clean]').textContent=propagation?'Edit frames':'Clean frames';
    e.timelineHost.hidden=!w.state.source;
    w.$('workflow-label').textContent='Add, remove & replace';
    w.$('empty').querySelector('h3').textContent='Add footage to begin';
    w.$('empty').querySelector('p').textContent=propagation?'Choose a frame on the timeline, then draw or edit it.':'Select what to remove, then add clean frames where needed.';
    w.$('empty').querySelector('.zps-start-mode').hidden=propagation;
    e.$('instruction').closest('label').hidden=propagation;
    if(w.modelDownloads?.quick&&propagation)w.modelDownloads.quick.hidden=true;
    if(this.runnerPanel){this.runnerPanel.hidden=!propagation||this.runner.availability?.ready!==false;this.runner.modelDownloads.quick.hidden=!propagation||this.runner.availability?.ready!==false;}
    e.$('clean').hidden=propagation;
    if(propagation){
      e.$('clean').textContent=this.action==='paint'?'Draw / edit frame':'Edit frame';e.$('clean').disabled=busy||!e.selected();
      e.objectReferenceTools.hidden=true;e.guideTitle.textContent=this.action==='paint'?'Add to your frame':'Edit your frame';
      e.$('tool-help').textContent=this.action==='paint'?'Paint an addition on the frame, then generate.':'Add an edited frame on the timeline. Area selection and drawing are optional.';
      e.maskSummary.hidden=true;e.maskReview.hidden=true;
      w.$('title').textContent=this.action==='paint'?'Add to your shot':'Replace or edit';
      w.$('prompt').placeholder='Describe the change and how it should move';
      const config=this.config(),delivery=this.owner.outputSettings?.delivery,error=rippleStudioValidation(delivery?.modelInputValidationConfig?.(w,config)||config);
      w.$('generate').disabled=busy||!!error;w.$('generate').textContent=busy?'Generating…':'Generate video';
      w.$('note').textContent=error||`${w.state.plateEngine==='h3'?'H3 uses timed edited frames':'LTX uses one selected edited frame'} · Original resolution, frame rate and audio retained`;
      w.$('note').hidden=false;w.$('note').classList.toggle('is-error',!!error);
      if(w.state.plateEngine==='h3')e.guideHelp.textContent='Add edited frames at the moments you want to change.';
    }
    if(this.runner?.job||this.runner?.pendingSubmission||this.runner?.submitting)this.progress(this.lastProgress||{title:'Starting video edit',detail:'Preparing'});
    this.surface?.sync();
    if(this.paintAutoOpen&&this.propagation()&&this.active()&&w.state.source&&w.state.clipTrimConfirmed&&!this.jobBusy()&&!this.inline&&!this.switching&&!this.paintAutoOpening&&typeof e.selected==='function'){
      this.paintAutoOpening=true;queueMicrotask(async()=>{try{if(!e.selected())await e.createFrame(w.playhead);if(this.propagation()&&this.active()&&!this.jobBusy()){this.paintAutoOpen=false;await this.editFrame();}}catch(error){this.paintAutoOpen=false;w.message(error.message);}finally{this.paintAutoOpening=false;}});
    }
  }
  async usePaintResult(request){
    if(this.paintAccepting||!this.propagation()||this.owner.rippleImage.request!==request)return;
    this.paintAccepting=true;this.paintGenerateRequested=false;
    try{await this.owner.rippleImage.useResult();if(!this.owner.rippleImage.request)this.primary.message('Frame edit saved. Review the frame, add another edit, or choose Generate video.');}
    catch(error){this.primary.message(error.message);}finally{this.paintAccepting=false;}
  }
  processingRange(){
    const source=this.primary.sourceInfo;
    const ratio=source?Math.max(source.width/source.height,source.height/source.width):16/9;
    const max=Math.min(megapixelMaximum(VIDEO_CANVAS_LIMITS),Math.floor(PROCESSING_MAX_EDGE**2/ratio/50000)*.05);
    return {min:PROCESSING_MIN_MP,max:Math.max(PROCESSING_MIN_MP,Number(max.toFixed(2)))};
  }
  processingSize(engine=this.primary.state.plateEngine||'ltx'){
    const {state,sourceInfo:source}=this.primary;
    if(!source)return {width:0,height:0};
    const step=engine==='h3'?32:64,chosen=state.plateProcessingMegapixels;
    if(Number.isFinite(chosen)&&chosen>0){
      const {min,max}=this.processingRange();
      const target=Math.max(min,Math.min(max,chosen));
      return resolutionSize(source.width/source.height,target,{
        step,min:64,max:PROCESSING_MAX_EDGE,maxPixels:VIDEO_CANVAS_LIMITS.maxPixels,
      });
    }
    if(chosen==null&&Number(state.processingMegapixelLimit)>0)return sourceMegapixelLimit(source.width,source.height,state.processingMegapixelLimit,{step});
    return rippleStudioProcessingSize(source.width,source.height,chosen===0?1:state.plateScale||1,engine);
  }
  config(){
    const w=this.primary;if(!w)return{};
    const engine=w.state.plateEngine||'ltx',size=this.processingSize(engine);
    const start=w.state.startFrame,end=start+w.state.frameCount,eligible=w.state.anchors.filter(a=>a.file&&a.enabled!==false&&a.frame>=start&&a.frame<end),selected=w.state.anchors[w.selected];
    const anchors=engine==='ltx'?[eligible.find(a=>a===selected)||eligible[0]].filter(Boolean):eligible;
    return aeFrameConfig({aeFrameBase:w.aeFrameBase,aeFrameMode:'ripple',state:{engine}},{engine,source:w.state.source,startFrame:start,frameCount:w.state.frameCount,sequenceFps:w.fps(),...size,resolutionMode:'plate',anchors:anchors.map(a=>({...a})),prompt:w.$('prompt').value,seed:Number(w.state.seed)||42,outputMode:'SDR video',sourceColour:w.state.sourceColour,detectedSourceColour:w.sourceInfo?.resolved_colour||'',plateAction:this.action,savePrefix:'ZURA STUDIO/plate'});
  }
  ensureRunner(){
    if(this.runner)return this.runner;
    const o=this.owner,w=this.primary,r=o.ensureRippleWorkspace('edit');this.runner=r;
    const nativeQuery=r.$.bind(r);this.runnerPanel=nativeQuery('model-downloads');r.$=key=>key==='model-downloads'?this.runnerPanel:nativeQuery(key);this.engine.after(this.runnerPanel);r.modelDownloads.mountQuick(w.page.querySelector('.zf-composer'));
    const render=r.render.bind(r),progress=r.setProgress.bind(r),clear=r.clearProgress.bind(r),message=r.message.bind(r),result=r.setResult.bind(r),config=r.config.bind(r);
    r.state.engine=w.state.plateEngine;
    r.render=(...args)=>{const value=render(...args);if(this.active())this.syncControls();return value;};
    r.config=()=>this.active()?this.config():config();
    r.setProgress=value=>{progress(value);if(this.active())this.progress(value);};
    r.clearProgress=()=>{clear();if(this.active()){this.lastProgress=null;w.$('progress').hidden=true;w.render();}};
    r.message=value=>{message(value);if(this.active())w.message(value);};
    r.setResult=value=>{result(value);if(this.active()){w.result=value;w.items.unshift(value);w.items=w.items.slice(0,12);w.save();w.preview('result');w.render();}};
    if(r.job||r.pendingSubmission)r.onResume?.();
    return r;
  }
  progress(value){
    this.lastProgress=value;const w=this.primary;w.$('progress').hidden=false;w.$('progress-title').textContent=value.title||'Processing';w.$('progress-detail').textContent=value.detail||'';
    if(Number.isFinite(value.value))w.$('bar').value=value.value;else w.$('bar').removeAttribute('value');w.$('cancel').disabled=false;
  }
  async generate(){
    const w=this.primary;if(w.busy())return;let config=this.config();const delivery=this.owner.outputSettings?.delivery,error=rippleStudioValidation(delivery?.modelInputValidationConfig?.(w,config)||config);if(error){w.message(error);return;}
    const r=this.ensureRunner();r.source=r.sourceInfo=w.sourceInfo;r.aeFrameBase=w.aeFrameBase;r.aeFrameMode='ripple';Object.assign(r.state,{engine:config.engine,sourcePath:w.state.source,sourceName:w.sourceInfo.name||'',startFrame:config.startFrame,frameCount:config.frameCount,sourceColour:config.sourceColour,anchors:w.state.anchors,prompt:config.prompt});
    try{config=await delivery?.prepareInferenceView?.(r,'paintout',config)||config;const invalid=rippleStudioValidation(config);if(invalid)throw Error(invalid);await r.onGenerate(config);if(r.job||r.pendingSubmission)w.preview('source');}catch(error){w.message(error.message);}finally{w.render();}
  }
  imageWorkspace(){
    if(this.imageFacade)return this.imageFacade;
    const plate=this,w=this.primary;
    this.imageFacade={intent:'plate',platePrimary:w,owner:this.owner,api:w.api,app:w.app,root:w.page,
      get source(){return w.sourceInfo;},get revision(){return plate.revision;},get state(){return {...w.state,engine:w.state.plateEngine};},
      get exporting(){return w.exporting;},set exporting(value){w.exporting=value;},
      busy:()=>w.busy(),anchors:()=>w.state.anchors,selected:()=>w.state.anchors[w.selected],save:()=>{plate.rememberPrompt(w.$('prompt').value);w.save();},render:()=>w.render(),message:value=>w.message(value),$:name=>w.$(name),
      prepareAnchor:async anchor=>{
        await w.editor.ensureProject();const layers=w.editor.ensureLayers(anchor),index=layers.findIndex(layer=>layer.id===anchor.plateEditLayerId),before=index>=0?layers.slice(0,index):layers;
        if(before.length){const base=await w.fetch('/zura/paintout/editor/compose-layers',{project:w.editor.project,source:w.state.source,frame:anchor.frame,colour_space:w.state.sourceColour,expected_revision:w.editor.revision,layers:before.map(paintLayerRequest)});return w.fetch('/zura/paintout/export-frame',{file:base.file,frame:0,colour_space:base.colour_space});}
        return w.fetch('/zura/paintout/export-frame',{project:w.editor.project,file:w.state.source,frame:anchor.frame,colour_space:w.state.sourceColour});
      },
      importAnchorFile:async(anchor,file,check)=>{
        const draft=await this.prepareFrameLayers(anchor,file,check,this.owner.items?.[this.owner.selectedImage]);
        return this.commitFrameLayers(anchor,draft);
      }};
    return this.imageFacade;
  }
  async prepareFrameLayers(anchor,file,check,imageItem){
    const w=this.primary,plate=this,retainedContext=imageItem?.retain_layer_context===true;
    const imageFeather=retainedContext&&imageItem.edit_area?.enabled?Number(imageItem.edit_area.feather??16):0;
    await w.editor.ensureProject();check();const body=new FormData();body.append('project',w.editor.project);body.append('source',w.state.source);body.append('frame',String(anchor.frame));body.append('colour_space','srgb_display');body.append('file',file,file.name);
    const response=await w.api.fetchApi('/zura/paintout/editor/import-frame',{method:'POST',body});const result=await response.json();if(!response.ok)throw Error(result.error||'Could not import the edited frame.');check();
    const mask=await plate.owner.imageArea.layerMask(imageItem?.edit_area||null);check();
    // Regeneration updates the current edit. New edit creates another layer.
    // Keep earlier attempts in frame history, and only commit after recomposition.
    const previous=w.editor.ensureLayers(anchor),layers=copy(previous),index=layers.findIndex(layer=>layer.id===anchor.plateEditLayerId);
    const target=index>=0?index:layers.length;
    const derive=!mask&&target>0;
    const layer={...(index>=0?layers[index]:{}),...result,id:index>=0?layers[index].id:crypto.randomUUID(),method:'image',operation:plate.action,edit_area:imageItem?.edit_area||null,image_references:plate.owner.references.slice(1).map(ref=>({...ref})),retain_layer_context:retainedContext,blend_pixels:index>=0?layers[index].blend_pixels??imageFeather:imageFeather,prompt:imageItem?.prompt??plate.owner.$('prompt').value,layer_mask:mask||(derive?null:w.editor.fullFrameMask()),enabled:index>=0?layers[index].enabled!==false:true,opacity:index>=0?layers[index].opacity??1:1};
    if(index>=0)layers[index]=layer;else layers.push(layer);
    const composed=await this.composeFrameLayers(anchor,layers,derive?target:null);check();
    if(derive){
      if(!composed.derived_mask)throw Error('Restart ComfyUI to save this edit as an independent layer.');
      layer.layer_mask=composed.derived_mask;
    }
    if(anchor.layers!==previous)throw Error('The layer stack changed while the edit was being prepared. Choose its frame again.');
    return {prior:previous,layers,layerId:layer.id,composed};
  }
  async composeFrameLayers(anchor,layers,derive=null){
    const w=this.primary,editor=w.editor;
    while(editor.saving)await new Promise(resolve=>setTimeout(resolve,20));
    return w.fetch('/zura/paintout/editor/compose-layers',{project:editor.project,source:w.state.source,frame:anchor.frame,colour_space:w.state.sourceColour,expected_revision:editor.revision,layers:layers.map(paintLayerRequest),...(derive!==null?{derive_mask_for:derive}:{})});
  }
  commitFrameLayers(anchor,draft){
    const w=this.primary,{layers,layerId,composed,prior}=draft;
    if(anchor.layers!==prior)throw Error('The layer stack changed. Reopen the frame before saving.');
    w.editor.saveFrameVersion(anchor);
    anchor.layers=layers;anchor.plateEditLayerId=layerId;anchor.edit_area=layers.find(layer=>layer.id===layerId)?.edit_area||null;
    Object.assign(anchor,{file:composed.file,preview_file:composed.png_file,preview_colour_space:composed.preview_colour_space,colour_space:composed.colour_space,status:'accepted'});
    w.editor.saveFrameVersion(anchor);w.save();return anchor;
  }
  frameDraftCurrent(draft){
    const o=this.owner;
    return this.frameDraft===draft&&o.rippleImage.request===draft.request&&o.items[o.selectedImage]===draft.item&&o.rippleImage.current(draft.request);
  }
  syncFrameDraft(request,item){
    if(!request||!item||item.ripple_guide!==request.id)return null;
    if(this.frameDraft?.request===request&&this.frameDraft.item===item)return this.frameDraft;
    const draft=this.frameDraft={request,item,pending:true};
    const check=()=>{this.owner.rippleImage.check(request);if(!this.frameDraftCurrent(draft))throw Error('The selected edit changed.');};
    draft.ready=(async()=>{
      try{
        const file=await this.owner.rippleImage.resultFile(request,item);check();
        const result=await this.prepareFrameLayers(request.anchor,file,check,item);check();
        Object.assign(draft,result);
      }catch(error){if(this.frameDraftCurrent(draft))draft.error=error.message;}
      finally{draft.pending=false;if(this.frameDraftCurrent(draft))this.updateDraftFramePreview();}
      return draft;
    })();
    return draft;
  }
  async readyFrameDraft(request,item){
    const draft=this.syncFrameDraft(request,item);
    if(draft)await draft.ready;
    if(!draft||!this.frameDraftCurrent(draft)||!draft.composed)throw Error(draft?.error||'Review the generated frame before saving.');
    return draft;
  }
  updateDraftFramePreview(){
    if(this.owner.updateDraftFramePreview)this.owner.updateDraftFramePreview();
    else this.owner.renderGallery();
  }
  draftPreview(item){
    const draft=this.frameDraft;
    if(!draft?.composed?.png_file||draft.item!==item||!this.frameDraftCurrent(draft))return item;
    const ref=path=>({filename:byFile(path).split('/').at(-1),subfolder:'paintout/clean_frames',type:'output'});
    const preview=ref(draft.composed.png_file);
    return {...item,file:preview,preview,master:ref(draft.composed.file)};
  }
  async updateFrameDraft(draft,layers){
    if(!this.frameDraftCurrent(draft)||draft.pending||this.jobBusy())return;
    draft.pending=true;draft.error='';this.owner.render();
    try{
      const result=await this.composeFrameLayers(draft.request.anchor,layers);
      if(!this.frameDraftCurrent(draft))return;
      if(draft.request.anchor.layers!==draft.prior)throw Error('The saved layers changed. Reopen the frame to adjust them.');
      draft.layers=layers;draft.composed=result;
      this.owner.editInputs.showSource=false;this.owner.imageArea.editing=false;if(this.owner.imageComparison)this.owner.imageComparison.active=false;
    }catch(error){if(this.frameDraftCurrent(draft))draft.error=error.message;}
    finally{draft.pending=false;if(this.frameDraftCurrent(draft)){this.updateDraftFramePreview();this.owner.render();}}
  }
  syncInlineImage(request){
    const o=this.owner,w=this.primary;
    if(o.mode!=='image'||!request?.workspace?.platePrimary){this.exitInlineImage();return;}
    if(!this.inline){this.inline=this.surface.inlineEditor.mount();o.imageArea.inline=true;w.page.classList.add('is-editing-image');w.page.querySelector('.zf-composer').hidden=true;}
    w.page.hidden=false;o.root.querySelector('.zc-image-page').hidden=true;o.root.dataset.workspace='paintout';o.videoComposer.task.hidden=false;o.imageTask.hidden=true;
    for(const b of o.root.querySelectorAll('.zc-nav [data-space]'))b.setAttribute('aria-current',b.dataset.space==='video'?'page':'false');
    o.imageArea.refreshTools();o.videoComposer.syncWorkflow();this.surface?.sync();
  }
  exitInlineImage(){
    if(!this.inline)return;this.frameDraft=null;this.paintGenerateRequested=false;this.surface.inlineEditor.restore();this.inline=null;
    this.owner.root.dataset.workspace=this.owner.mode;
  }
  async backToShot(timeout=3000){
    if(this.backPromise)return this.backPromise;
    const o=this.owner;if(o.rippleImage.imageBusy()||o.rippleImage.importing)return;
    this.backPromise=(async()=>{let timer;try{
      await Promise.race([o.rippleImage.leave(),new Promise(resolve=>{timer=setTimeout(resolve,timeout);})]);
    }catch(error){this.primary.message(error.message);}finally{
      clearTimeout(timer);if(this.inline){o.rippleImage.clear();this.exitInlineImage();o.show('paintout');this.primary.render();}
      this.backPromise=null;
    }})();return this.backPromise;
  }
  async refreshInlineSource(anchor=this.primary?.editor?.selected()){
    const o=this.owner,req=o.rippleImage?.request;
    if(!this.inline||!req||req.anchor!==anchor||o.rippleImage.imageBusy()||o.rippleImage.importing)return;
    try{
      const exported=await this.imageWorkspace().prepareAnchor(anchor);
      const response=await o.api.fetchApi(exported.url);if(!response.ok)return;
      const blob=await response.blob(),form=new FormData();form.append('image',blob,`ripple_frame_${anchor.frame}.png`);form.append('subfolder','zura_images/ripple');form.append('type','input');
      const upload=await o.api.fetchApi('/upload/image',{method:'POST',body:form}),image=await upload.json();if(!upload.ok||!image.name)return;
      const file=(image.subfolder?image.subfolder+'/':'')+image.name;
      o.references=[{file,filename:image.name,subfolder:image.subfolder||'',name:`Source frame ${anchor.frame}`,width:req.width,height:req.height},...o.references.slice(1)];
      if(o.imageArea){o.imageArea.state.source_key=file;o.imageArea.disposeViewer();o.imageArea.sync();}
      o.save();o.render();
    }catch{}
  }
  async startNewFrameEdit(){
    const w=this.primary,anchor=w?.editor?.selected();
    if(!anchor||this.jobBusy())return;
    anchor.plateEditLayerId=null;
    anchor.edit_area=null;
    w.save();
    return this.editFrame();
  }
  async editSavedLayer(layer){
    const w=this.primary,anchor=w?.editor?.selected();
    if(!anchor||!this.propagation()||this.jobBusy()||!anchor.layers?.includes(layer)||layer.method!=='image')return;
    if(this.inline){await this.backToShot();if(this.inline||w.editor.selected()!==anchor)return;}
    if(layer.operation&&layer.operation!==this.action)await this.select(layer.operation);
    if(w.editor.selected()!==anchor||!this.propagation())return;
    const previousId=anchor.plateEditLayerId;
    anchor.edit_area=Object.hasOwn(layer,'edit_area')?layer.edit_area:previousId===layer.id?anchor.edit_area:null;
    anchor.plateEditLayerId=layer.id;
    if(layer.image_references)anchor.image_references=layer.image_references.map(ref=>({...ref}));
    if(layer.prompt!=null){w.$('prompt').value=layer.prompt;this.rememberPrompt(layer.prompt);}
    w.save();
    return this.editFrame();
  }
  async editFrame(){
    const w=this.primary;if(w?.editor?.loadingProject)await w.editor.ensureProject();
    const anchor=w?.editor?.selected();if(!anchor||this.jobBusy())return;
    if(['acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3'].includes(w.state.sourceColour)||['acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3'].includes(w.sourceInfo?.resolved_colour)){w.message('Paint and Replace currently use SDR image guides. Use Remove for the native HDR Paintout workflow. Your original float source is retained.');return;}
    if(w.playhead!==anchor.frame){w.playhead=anchor.frame;w.updatePlayhead?.();}
    if(w.editor.stage!=='clean')await w.editor.setStage('clean');
    const previous=anchor.layers?.find(layer=>layer.id===anchor.plateEditLayerId);
    if(previous?.operation&&previous.operation!==this.action){
      anchor.plateEditLayerId=null;anchor.edit_area=null;w.save();
    }
    await this.owner.rippleImage.edit(this.imageWorkspace(),anchor);
    if(this.owner.rippleImage.request?.anchor===anchor){const area=this.owner.imageArea;area.sync();area.openEditor(this.action==='paint'?'draw':'brush');if(area.load)await area.load;this.surface.inlineEditor.sync();}
  }
}

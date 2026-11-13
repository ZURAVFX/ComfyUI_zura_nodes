import {PlateSurface} from './studio_plate_surface.js';
import {aeFrameConfig} from './studio_ae_frame_contract.js';
import {workspaceStorage} from './studio_storage.js';
import {platePrompt,platePromptDrafts,savePlatePrompt} from './studio_plate_prompts.js';
import {rippleStudioProcessingSize,rippleStudioValidation} from './studio_ripple_recipes.js';

const KEY='zura-plate-action-v1';
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
  // Explicit compatibility modes retain their own saved instruction. Merely
  // restoring one must not classify it as a new Remove/Add/Replace draft.
  legacyPromptMode(){const mode=this.primary?.state.mode;return ['inpaint','ripple'].includes(mode)?mode:null;}
  rememberPrompt(value,action=this.action){const w=this.primary;if(!w)return;const legacy=this.legacyPromptMode();if(legacy)w.prompts[legacy]=String(value);else savePlatePrompt(w.state,action,value);if(legacy||action==='remove'){w.cleanupPrompt=String(value);w.$('prompt').value=String(value);if(w.editor?.$?.('instruction'))w.editor.$('instruction').value=String(value);}}
  applyPrompt(){const w=this.primary;if(!w)return;const legacy=this.legacyPromptMode(),value=legacy?w.$('prompt').value:platePrompt(w.state,this.action);w.$('prompt').value=value;if(legacy||this.action==='remove'){w.cleanupPrompt=value;if(w.editor?.$?.('instruction'))w.editor.$('instruction').value=value;}this.promptDraft=platePromptDrafts(w.state);}
  async select(action=this.action){
    if(!actions.some(([id])=>id===action)||this.switching)return;
    const o=this.owner,w=o.paintout;if(w?.busy())return;if(o.rippleImage?.request?.workspace?.platePrimary){await o.rippleImage.leave();if(o.rippleImage.request)return;}
    this.switching=true;
    try{
      if(w?.editor){await w.editor.flushManual();await w.editor.persist();}
      const previousAction=this.action;
      if(w&&this.promptDraft&&this.promptDraft===w.state.platePrompts)this.rememberPrompt(w.$('prompt').value,previousAction);
      this.action=action;this.storage.setItem(KEY,action);o.show('paintout');this.attach(o.paintout);this.action=action;
      const primary=o.paintout;primary.state.plateAction=action;
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
    this.strip=doc.createElement('nav');this.strip.className='zplate-actions';this.strip.setAttribute('aria-label','Edit operation');
    for(const [id,label,title]of actions){const b=doc.createElement('button');b.type='button';b.textContent=label;b.title=title;b.dataset.plateAction=id;b.onclick=()=>void this.select(id);this.strip.append(b);}
    w.page.querySelector('.zf-heading').after(this.strip);
    const viewer=w.page.querySelector('.zf-viewer');this.canvasShell=doc.createElement('div');this.canvasShell.className='zplate-canvas-shell';viewer.before(this.canvasShell);this.canvasShell.append(viewer);this.sidebar=doc.createElement('aside');this.sidebar.className='zplate-sidebar';this.sidebar.setAttribute('aria-label','Edits and layers');this.sidebar.append(w.editor.layersPanel,w.editor.tools);w.page.append(this.sidebar);this.canvasShell.after(w.$('message'));w.$('message').classList.add('zplate-feedback');
    this.frameToolbar=doc.createElement('div');this.frameToolbar.className='zplate-frame-toolbar';this.frameButton=doc.createElement('button');this.frameButton.type='button';this.frameButton.className='gs-primary';this.frameButton.onclick=()=>this.editFrame();this.newEditButton=doc.createElement('button');this.newEditButton.type='button';this.newEditButton.textContent='New edit';this.newEditButton.title='Start another edit while keeping the existing layers';this.newEditButton.onclick=()=>{const anchor=w.editor.selected();if(!anchor||w.busy())return;anchor.plateEditLayerId=null;anchor.edit_area=null;w.editor.newPaintArea();w.save();void this.editFrame();};this.frameToolbar.append(this.frameButton,this.newEditButton);w.editor.viewerHost.prepend(this.frameToolbar);
    w.$('prompt').addEventListener('input',()=>{this.rememberPrompt(w.$('prompt').value);w.save();});
    this.trimButton=doc.createElement('button');this.trimButton.type='button';this.trimButton.textContent='Trim clip';this.trimButton.onclick=()=>w.editor.setStage('trim');w.page.querySelector('.zf-heading').append(this.trimButton);
    this.engine=doc.createElement('label');this.engine.className='zc-tool zplate-engine';this.engine.innerHTML='<span>Video model</span><select aria-label="Video processing model"><option value="ltx">LTX 2.5</option><option value="h3">MiniMax H3</option></select>';
    this.scale=doc.createElement('label');this.scale.className='zc-tool zplate-scale';this.scale.innerHTML='<span>Process</span><select aria-label="Video processing scale"><option value="1">Full size</option><option value="0.75">75%</option><option value="0.5">50%</option><option value="0.25">25%</option></select>';
    w.page.querySelector('.zf-model').parentElement.after(this.engine,this.scale);
    this.engine.querySelector('select').value=w.state.plateEngine;this.scale.querySelector('select').value=String(w.state.plateScale);
    this.engine.querySelector('select').onchange=()=>{if(w.busy())return;w.state.plateEngine=this.engine.querySelector('select').value;if(this.runner)this.runner.state.engine=w.state.plateEngine;this.revision++;w.save();this.runner?.checkModels();w.render();};
    this.scale.querySelector('select').onchange=()=>{if(w.busy())return;w.state.plateScale=Number(this.scale.querySelector('select').value);w.save();w.render();};
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
    editor.confirmClipTrim=async()=>{await confirm();if(this.propagation()&&w.state.clipTrimConfirmed&&!w.busy())await editor.setStage('clean');};
    const setMode=w.setMode.bind(w);w.setMode=(...args)=>{const result=setMode(...args);this.applyPrompt();w.save();return result;};
    const reset=w.resetSource.bind(w);w.resetSource=async()=>{if(this.inline){await this.owner.rippleImage.leave();if(this.inline)return false;}const success=await reset();if(success!==false){delete w.state.platePrompts;this.applyPrompt();this.revision++;if(this.runner&&!this.runner.busy())this.runner.reset();w.save();}return success;};
    for(const key of ['onSeek','onCreate','onSelect','onRemove']){
      const callback=editor.timeline.callbacks[key];
      editor.timeline.callbacks[key]=async(...args)=>{
        if(this.timelineSwitch||w.busy()||this.owner.rippleImage?.importing)return;
        this.timelineSwitch=true;
        try{if(this.inline){await this.owner.rippleImage.leave();if(this.inline)return;}
          await callback(...args);
          if(this.propagation()&&['onCreate','onSelect'].includes(key)){await editor.frameChanged(true);if(!w.busy())await this.editFrame();}
        }catch(error){w.message(error.message);}finally{this.timelineSwitch=false;}
      };
    }
    this.surface=new PlateSurface(this);const message=w.message.bind(w);w.message=value=>{message(value);this.surface.sync();};
    this.syncControls();
  }
  sync(){if(this.active()){this.attach(this.owner.paintout);this.syncControls();}}
  syncControls(){
    const w=this.primary;if(!w)return;const propagation=this.propagation(),e=w.editor,busy=w.busy();
    if(this.promptDraft!==platePromptDrafts(w.state))this.applyPrompt();
    if(this.lastPropagation===true&&!propagation)this.nativeEditorUpdate?.();this.lastPropagation=propagation;
    w.page.classList.add('zplate-page');w.page.dataset.plateAction=this.action;
    w.page.querySelector('h2').textContent='Add, remove & replace';w.$('new').textContent='Start over';
    for(const b of this.strip.querySelectorAll('button')){b.disabled=this.switching||busy;b.setAttribute('aria-pressed',String(b.dataset.plateAction===this.action));}
    if(this.frameActions){const host=propagation?this.frameToolbar:this.frameActionsHome;if(this.frameActions.parentElement!==host)host.append(this.frameActions);}
    this.frameToolbar.hidden=!(propagation&&e.stage==='clean');this.frameButton.textContent=this.action==='paint'?'Draw / edit frame':'Edit frame';this.frameButton.disabled=busy||!e.selected();this.newEditButton.disabled=busy||!e.selected();this.newEditButton.hidden=!e.selected()?.layers?.length;e.viewerToolbar.hidden=propagation;
    this.trimButton.disabled=busy||!w.state.source;this.trimButton.hidden=!w.state.source;
    this.engine.hidden=this.scale.hidden=!propagation;this.engine.querySelector('select').disabled=this.scale.querySelector('select').disabled=busy;
    w.page.querySelector('.zf-model').parentElement.hidden=propagation;
    w.$('resolution').hidden=propagation;
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
      e.$('tool-help').textContent='Add an edited frame on the timeline. Area selection and drawing are optional.';
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
  }
  config(){
    const w=this.primary,s=w?.sourceInfo;if(!w)return{};
    const engine=w.state.plateEngine||'ltx',size=s?rippleStudioProcessingSize(s.width,s.height,w.state.plateScale||1,engine):{width:0,height:0};
    const start=w.state.startFrame,end=start+w.state.frameCount,eligible=w.state.anchors.filter(a=>a.file&&a.enabled!==false&&a.frame>=start&&a.frame<end),selected=w.state.anchors[w.selected];
    const anchors=engine==='ltx'?[eligible.find(a=>a===selected)||eligible[0]].filter(Boolean):eligible;
    return aeFrameConfig({aeFrameBase:w.aeFrameBase,aeFrameMode:'ripple',state:{engine}},{engine,source:w.state.source,startFrame:start,frameCount:w.state.frameCount,sequenceFps:w.fps(),...size,resolutionMode:'plate',anchors:anchors.map(a=>({...a})),prompt:w.$('prompt').value,seed:Number(w.state.seed)||42,outputMode:'SDR video',sourceColour:w.state.sourceColour,detectedSourceColour:s?.resolved_colour||'',savePrefix:'ZURA STUDIO/plate'});
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
        if(before.length){const base=await w.fetch('/zura/paintout/editor/compose-layers',{project:w.editor.project,source:w.state.source,frame:anchor.frame,colour_space:w.state.sourceColour,expected_revision:w.editor.revision,layers:before.map(layer=>({file:layer.file,colour_space:layer.colour_space,mask:layer.layer_mask,expand_pixels:layer.expand_pixels||0,blend_pixels:layer.blend_pixels||0,brightness_ev:layer.brightness_ev||0,enabled:layer.enabled!==false,opacity:layer.opacity??1}))});return w.fetch('/zura/paintout/export-frame',{file:base.file,frame:0,colour_space:base.colour_space});}
        return w.fetch('/zura/paintout/export-frame',{project:w.editor.project,file:w.state.source,frame:anchor.frame,colour_space:w.state.sourceColour});
      },
      async importAnchorFile(anchor,file,check){
        const imageItem=plate.owner.items?.[plate.owner.selectedImage],retainedContext=imageItem?.retain_layer_context===true;
        const imageFeather=retainedContext&&imageItem.edit_area?.enabled?Number(imageItem.edit_area.feather??16):0;
        await w.editor.ensureProject();const body=new FormData();body.append('project',w.editor.project);body.append('source',w.state.source);body.append('frame',String(anchor.frame));body.append('colour_space','srgb_display');body.append('file',file,file.name);
        const response=await w.api.fetchApi('/zura/paintout/editor/import-frame',{method:'POST',body});const result=await response.json();if(!response.ok)throw Error(result.error||'Could not import the edited frame.');check();
        const mask=await plate.owner.imageArea.layerMask(imageItem?.edit_area||null);check();
        // Regeneration updates the current edit. New edit creates another layer.
        // Keep earlier attempts in frame history, and only commit after recomposition.
        const previous=w.editor.ensureLayers(anchor),layers=copy(previous),index=layers.findIndex(layer=>layer.id===anchor.plateEditLayerId);
        const layer={...(index>=0?layers[index]:{}),...result,id:index>=0?layers[index].id:crypto.randomUUID(),method:'image',retain_layer_context:retainedContext,blend_pixels:index>=0?layers[index].blend_pixels??imageFeather:imageFeather,prompt:plate.owner.$('prompt').value,layer_mask:mask||w.editor.fullFrameMask(),enabled:index>=0?layers[index].enabled!==false:true,opacity:index>=0?layers[index].opacity??1:1};
        if(index>=0)layers[index]=layer;else layers.push(layer);
        const composed=await w.fetch('/zura/paintout/editor/compose-layers',{project:w.editor.project,source:w.state.source,frame:anchor.frame,colour_space:w.state.sourceColour,expected_revision:w.editor.revision,layers:layers.map(layer=>({file:layer.file,colour_space:layer.colour_space,mask:layer.layer_mask,expand_pixels:layer.expand_pixels||0,blend_pixels:layer.blend_pixels||0,brightness_ev:layer.brightness_ev||0,enabled:layer.enabled!==false,opacity:layer.opacity??1}))});check();
        if(anchor.layers!==previous)throw Error('The layer stack changed while the edit was being prepared. Choose its frame again.');
        w.editor.saveFrameVersion(anchor);anchor.layers=layers;anchor.plateEditLayerId=layer.id;
        Object.assign(anchor,{file:composed.file,preview_file:composed.png_file,preview_colour_space:composed.preview_colour_space,colour_space:composed.colour_space,status:'accepted'});
        w.editor.saveFrameVersion(anchor);w.save();return anchor;
      }};
    return this.imageFacade;
  }
  syncInlineImage(request){
    const o=this.owner,w=this.primary;
    if(o.mode!=='image'||!request?.workspace?.platePrimary){this.exitInlineImage();return;}
    if(!this.inline){
      const doc=w.page.ownerDocument,host=doc.createElement('div');host.className='zplate-inline-image';w.page.querySelector('.zf-viewer').append(host);
      this.inline={host,moved:[]};o.imageArea.inline=true;
      const move=(node,target)=>{if(!node)return;const marker=doc.createComment('plate-image-home');node.before(marker);this.inline.moved.push({node,marker});target.append(node);};
      if(!this.surface)move(o.rippleImage.banner,host);if(o.imageComparison?.button)move(o.imageComparison.button,this.surface?.root.querySelector('.zpx-header')||o.rippleImage.banner);move(o.editInputs.source,host);move(o.$('gallery'),host);move(o.imageComparison?.host,host);move(o.imageArea.host,host);move(o.imageArea.tools,this.surface?.$('brushes')||this.strip);
      this.inline.composer=o.root.querySelector('.zc-image-composer');if(!this.surface){move(this.inline.composer,w.page);this.inline.composer.classList.add('zplate-inline-composer');}else{move(o.$('progress'),this.surface.root.querySelector('.zpx-stage'));move(o.browserConnection?.host,this.surface.$('account'));move(o.root.querySelector('.zc-image-settings'),this.surface.$('image-settings-body'));}
      w.page.classList.add('is-editing-image');w.page.querySelector('.zf-composer').hidden=true;
    }
    w.page.hidden=false;o.root.querySelector('.zc-image-page').hidden=true;o.root.dataset.workspace='paintout';o.videoComposer.task.hidden=false;o.imageTask.hidden=true;
    for(const b of o.root.querySelectorAll('.zc-nav [data-space]'))b.setAttribute('aria-current',b.dataset.space==='video'?'page':'false');
    o.imageArea.refreshTools();o.videoComposer.syncWorkflow();this.surface?.sync();
  }
  exitInlineImage(){
    if(!this.inline)return;this.owner.imageArea.inline=false;const {host,moved,composer}=this.inline;this.inline=null;
    for(const {node,marker}of moved)if(marker.parentNode)marker.replaceWith(node);
    composer.classList.remove('zplate-inline-composer');host.remove();this.primary.page.classList.remove('is-editing-image');this.primary.page.querySelector('.zf-composer').hidden=false;
    this.owner.root.dataset.workspace=this.owner.mode;
  }
  async editFrame(){
    const w=this.primary,anchor=w.editor.selected();if(!anchor||w.busy())return;
    if(['acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3'].includes(w.state.sourceColour)||['acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3'].includes(w.sourceInfo?.resolved_colour)){w.message('Paint and Replace currently use SDR image guides. Use Remove for the native HDR Paintout workflow. Your original float source is retained.');return;}
    await this.owner.rippleImage.edit(this.imageWorkspace(),anchor);
  }
}

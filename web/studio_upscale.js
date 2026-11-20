import {openStudioGraph,studioGraphReceipt} from './studio_graph_view.js';
import {workspaceStorage} from './studio_storage.js';
import {ClipTrimmer} from './studio_trim.js';
import {ShotComparison} from './studio_compare.js';
import {StudioModelDownloads} from './studio_model_download.js';
import {playbackFile} from './studio_delivery_formats.js';
import {captureResultExports,installResultExportStyles} from './studio_result_exports.js';
import {submitOwnedGraph,recoverOwnedSubmission,cancelOwnedJob} from './studio_owned_jobs.js';
import {durationLabel,installOwnedNodeProgress} from './studio_progress.js';
import {buildUpscaleGraph,DEFAULT_UPSCALE_MODEL,RTX_UPSCALE,UPSCALE_MODELS,rtxCapabilities,rtxSize,upscaleAvailability,upscaleFrameConfig,addUpscaleFramePreviews} from './studio_upscale_recipes.js';

import {EXTEND_DEFAULT,EXTEND_MODELS,EXTEND_SETTINGS,buildExtendGraph,extendAvailability,extendPlan} from './studio_extend_recipes.js';

const KEY='zura-upscale-workspace-v1';
const HDR_REFINE='ltx25_hdr_refine_x2';
const RTX_QUALITY={HIGHBITRATE_ULTRA:'Clean footage',ULTRA:'Ultra',HIGH:'High',MEDIUM:'Medium',LOW:'Low',BICUBIC:'Bicubic'};
const HDR=new Set(['acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3']);

const outputFile=(output,extension)=>Object.values(output||{}).flat().find(
  file=>file?.type==='output'&&typeof file.filename==='string'&&extension.test(file.filename));
function completedVideo(entry,config){
  if(entry?.status?.status_str!=='success')return null;
  const outputs=entry.outputs||{};
  const master=outputFile(outputs.zura_hdr_save_video||outputs.save,/\.mov$/i);
  if(!master)return null;
  const preview=outputFile(outputs.zura_hdr_save_preview,/\.mp4$/i);
  const archive=outputFile(outputs.zura_hdr_archive,/\.zip$/i);
  const exports=captureResultExports(archive?{zura_exports:[{role:'exr',file:archive}]}:outputs.save);
  return {file:preview?{...master,preview}:master,config,exports,tail:outputFile(outputs.save_tail,/\.mov$/i)};
}

export class UpscaleWorkspace{
  constructor(owner,extending=false){
    this.extending=extending;
    this.mode=extending?'extend_length':'upscale';
    this.key=extending?'zura-extend-length-v1':KEY;
    this.title=extending?'Extend length':'Upscale video';
    this.models=extending?EXTEND_MODELS:UPSCALE_MODELS;
    this.owner=owner;
    this.independentAsset=true;
    this.api=owner.api;
    this.storage=workspaceStorage(owner);
    let saved={};
    try{saved=JSON.parse(this.storage.getItem(this.key))||{};}catch{}
    this.source=saved.source||null;
    this.range=saved.range||null;
    this.detail=saved.detail??1;
    this.prompt=typeof saved.prompt==='string'?saved.prompt:'';
    this.negativePrompt=typeof saved.negativePrompt==='string'?saved.negativePrompt:'';
    this.refineScale=saved.refineScale===2?2:1;
    this.rtxScale=[1,1.5,2,3,4].includes(saved.rtxScale)?saved.rtxScale:2;
    this.rtxQuality=typeof saved.rtxQuality==='string'?saved.rtxQuality:'';
    this.rtxStrength=Number.isFinite(saved.rtxStrength)?saved.rtxStrength:1;
    this.refineOutput=saved.refineOutput==='sdr'?'sdr':'hdr';
    this.model=Object.hasOwn(this.models,saved.model)?saved.model:extending?EXTEND_DEFAULT:DEFAULT_UPSCALE_MODEL;
    this.extension=extending?{...EXTEND_SETTINGS,...saved.extension}:null;
    this.result=saved.result||null;
    this.job=saved.job||null;
    this.pendingSubmission=saved.pendingSubmission||null;
    if(this.job?.cancelPending)this.job.cancelRetryAvailable=true;
    this.disposed=false;
    const doc=owner.root.ownerDocument;
    if(!doc.getElementById('zura-alpha-styles')){
      const style=doc.createElement('link');
      style.id='zura-alpha-styles';
      style.rel='stylesheet';
      style.href=new URL('./studio_alpha.css',import.meta.url).href;
      doc.head.append(style);
    }
    const sheet=doc.createElement('link');
    sheet.rel='stylesheet';
    sheet.href=new URL('./studio_upscale.css',import.meta.url).href;
    doc.head.append(sheet);
    this.style=sheet;
    this.page=doc.createElement('section');
    this.page.className='zalpha-page zup-page'+(extending?' zup-extend':'');
    this.page.hidden=true;
    this.page.innerHTML=`<header class="zalpha-heading"><h2 data-heading>${this.title}</h2><div class="zup-view-actions" aria-label="Preview tools"><button type="button" data-view hidden>View source</button><button type="button" data-compare hidden>Compare video</button><button type="button" data-result-fullscreen hidden>Fullscreen</button><a class="gs-primary zup-download" data-download download hidden>Download MOV</a>${extending?'<button type="button" data-tail-view hidden>View extension only</button>':''}</div></header>
      <div class="zalpha-viewer" data-viewer><video data-video controls playsinline preload="metadata" hidden></video><div class="gs-comparison" data-wipe-host hidden></div><div class="zalpha-empty" data-empty><strong>${extending?'Continue a video beyond its last frame':'Upscale or refine a video'}</strong><button type="button" class="gs-primary" data-add>Add video</button></div></div>
      <section class="zalpha-progress" data-progress hidden role="status"><div><strong data-progress-title>Preparing</strong><button type="button" data-cancel>Cancel run</button></div><progress data-bar max="100" aria-label="Current processing stage progress"></progress><span data-progress-detail></span></section>
      <div class="zalpha-composer zc-prompt-card zc-shared-composer">
        <div class="zalpha-attachments"><button type="button" class="zc-attachment" data-source hidden>Replace video</button><input type="file" data-file accept=".mp4,.mov,.mkv,.webm,video/*" hidden><span data-source-meta></span></div>
        <details data-trim class="zalpha-trim" hidden><summary><span>Trim clip</span><span data-range></span></summary><div data-trimmer></div><div class="zalpha-trim-fields"><label>In frame <input type="number" min="1" step="1" data-in></label><label>Out frame <input type="number" min="1" step="1" data-out></label><button type="button" data-full>Use full clip</button></div></details>
        <label data-prompt-control class="zup-prompt" hidden><span>${extending?'Extension prompt':'Refinement prompt'} <small>Optional</small></span><textarea data-prompt class="zc-shared-prompt" aria-label="${extending?'Extension prompt':'Refinement prompt'}" placeholder="Describe how the refinement should look" maxlength="1000"></textarea></label>
        ${extending?'<div class="zup-extension-controls"><label>Add seconds <input type="number" data-seconds min="0.25" max="10" step="0.25"></label><label>Ending context (s) <input type="number" data-context min="0.25" max="4.25" step="0.25"></label><label>Processing (MP) <input type="number" data-megapixels min="0.16" max="1.05" step="0.01"></label><details class="zc-tool-popup zup-extend-settings"><summary>Settings</summary><div><label>Steps <input type="number" data-steps min="4" max="50"></label><label>Seed <input type="number" data-seed min="0" max="9007199254740991"></label><label data-turbo-control>Turbo strength <input type="number" data-turbo-strength min="0" max="1" step="0.05"></label><label><input type="checkbox" data-audio> Generate audio for the extension</label></div></details></div>':''}
        <details class="zup-negative" data-negative-control hidden><summary>Avoid… <span data-negative-status hidden>Added</span></summary><textarea data-negative class="zc-shared-prompt" aria-label="Negative prompt" placeholder="Describe changes to avoid, such as halos, smearing or altered lettering" maxlength="1000"></textarea></details>
        <div class="zc-prompt-bottom"><div class="zc-prompt-tools"><label class="zup-model">Model <select data-model aria-label="Video model"></select></label><span class="zc-tool" data-resolution>2×</span><label data-rtx-scale-control hidden>Scale <select data-rtx-scale aria-label="RTX upscale factor"><option value="1">1×</option><option value="1.5">1.5×</option><option value="2">2×</option><option value="3">3×</option><option value="4">4×</option></select></label><label data-rtx-quality-control hidden>Quality <select data-rtx-quality aria-label="RTX quality"></select></label><label class="zup-detail" data-rtx-strength-control hidden>Strength <input data-rtx-strength type="range" min="0" max="1" step="0.05" aria-label="RTX effect strength"><output data-rtx-strength-value></output></label><label data-refine-scale-control hidden>Size <select data-refine-scale aria-label="Refine output size"><option value="1">Original size</option><option value="2">2×</option></select></label><label class="zup-detail" data-detail-control title="0% uses the bicubic base. 100% keeps all detail added by the Flash decoder.">Flash detail <input data-detail type="range" min="0" max="1" step="0.05" aria-label="Detail enhancement"><output data-detail-value></output></label><details class="zc-tool-popup gs-model-help" data-models hidden></details><label class="zc-output-choice">Output:<select data-refine-output aria-label="Output range"><option value="sdr">SDR</option><option value="hdr">HDR</option></select></label></div><div class="zalpha-actions"><button type="button" data-frame-preview hidden title="Preview the current frame with the selected model">Preview frame</button><button type="button" class="gs-primary" data-generate>Upscale video</button></div></div>
        <p class="zalpha-status" data-range-hint hidden></p>
        <p class="zalpha-status" data-detail-hint hidden>Blends detail from the Flash decoder. 0% keeps the bicubic upscale, 100% keeps all model detail.</p>
        <p class="zalpha-status" data-status role="status"></p>
        <div class="zalpha-exports zc-result-exports" data-exports hidden><a data-preview-download download hidden>Save MP4 preview</a><a data-exr-download download hidden>Save EXR frames</a>${extending?'<a data-tail-download download hidden>Save extension only</a>':''}</div>
      </div>`;
    owner.root.append(this.page);
    this.video=this.$('video');
    installResultExportStyles(doc);
    this.comparison=new ShotComparison(this.$('wipe-host'));
    this.comparison.onClose=()=>{
      const frame=this.view==='frame'?this.frameReview?.frame:null;
      this.preview(frame==null?'result':'source');
      if(frame!=null)this.video.currentTime=frame/this.source.fps;
    };
    this.modelDownloads=new StudioModelDownloads(this.$('models'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.checkModels());
    this.modelDownloads.inlineSetup=true;
    this.modelDownloads.mountQuick(this.page.querySelector('.zalpha-composer'));
    this.trimmer=new ClipTrimmer(this.$('trimmer'),{
      onSeek:time=>{if(this.view!=='source')this.preview('source');this.video.currentTime=time;},
      onCommit:range=>{
        const fps=this.source.fps;
        const first=Math.min(this.source.frames,Math.round(range.start*fps)+1);
        const last=Math.min(this.source.frames,Math.round((range.start+range.duration)*fps));
        this.setFrames(first,Math.max(first,last));
      },
    });
    this.$('add').onclick=this.$('source').onclick=()=>this.$('file').click();
    this.$('file').onchange=event=>{
      const file=event.target.files?.[0];
      event.target.value='';
      if(file)void this.upload(file);
    };
    this.$('in').onchange=this.$('out').onchange=()=>this.setFrames(Number(this.$('in').value),Number(this.$('out').value));
    this.$('full').onclick=()=>{this.range=null;this.save();this.render();};
    const select=this.$('model');
    for(const [id,model] of Object.entries(this.models)){
      const option=doc.createElement('option');
      option.value=id;
      option.textContent=model.label;
      select.append(option);
    }
    select.value=this.model;
    select.onchange=()=>{
      if(this.busy()||!Object.hasOwn(this.models,select.value))return;
      this.model=select.value;
      if(this.extension)this.$('steps').value=this.extension.steps=this.models[this.model].steps;
      this.message('');
      this.updateAvailability();
      this.save();
      this.render();
      void this.checkModels();
    };
    if(extending){
      this.$('prompt').placeholder='Describe what should happen after the last frame';
      for(const [field,key] of Object.entries({seconds:'seconds',context:'context',megapixels:'megapixels',steps:'steps',seed:'seed','turbo-strength':'turboStrength'})){
        const control=this.$(field);
        control.value=String(this.extension[key]);
        control.onchange=()=>{
          if(control.value===''||!control.checkValidity()){control.value=String(this.extension[key]);return;}
          this.extension[key]=Number(control.value);
          this.save();
          this.render();
        };
      }
      this.$('audio').checked=this.extension.audio;
      this.$('audio').onchange=()=>{this.extension.audio=this.$('audio').checked;this.save();};
      this.$('tail-view').onclick=()=>this.preview(this.view==='tail'?'result':'tail');
    }
    this.$('prompt').value=this.prompt;
    this.$('prompt').oninput=()=>{this.prompt=this.$('prompt').value;this.save();};
    this.$('negative').value=this.negativePrompt;
    this.$('negative').oninput=()=>{this.negativePrompt=this.$('negative').value;this.$('negative-status').hidden=!this.negativePrompt.trim();this.save();};
    this.$('rtx-scale').value=String(this.rtxScale);
    this.$('rtx-scale').onchange=()=>{this.rtxScale=Number(this.$('rtx-scale').value);this.save();this.render();};
    this.$('rtx-quality').onchange=()=>{this.rtxQuality=this.$('rtx-quality').value;this.save();};
    this.$('rtx-strength').value=String(this.rtxStrength);
    this.$('rtx-strength').oninput=()=>{
      this.rtxStrength=Number(this.$('rtx-strength').value);
      this.$('rtx-strength-value').textContent=Math.round(this.rtxStrength*100)+'%';
    };
    this.$('rtx-strength').onchange=()=>this.save();
    this.$('refine-scale').value=String(this.refineScale);
    this.$('refine-output').value=this.refineOutput;
    this.$('refine-scale').onchange=()=>{this.refineScale=Number(this.$('refine-scale').value);this.save();this.render();};
    this.$('refine-output').onchange=()=>{
      if(this.model!==HDR_REFINE||this.busy())return;
      this.refineOutput=this.$('refine-output').value;
      this.save();
      this.render();
    };
    this.$('detail').value=String(this.detail);
    this.$('detail').oninput=()=>{
      this.detail=Number(this.$('detail').value);
      this.$('detail-value').textContent=Math.round(this.detail*100)+'%';
    };
    this.$('detail').onchange=()=>this.save();
    this.$('view').onclick=()=>this.preview(this.view==='source'?'result':'source');
    this.$('compare').onclick=()=>{
      this.view='result';
      this.render();
      this.video.pause();
      this.video.hidden=true;
      this.comparison.show(this.sourceURL(),this.fileURL(playbackFile(this.result.file)),this.result.config.start,{resultLabel:'Final result'});
      this.$('result-fullscreen').hidden=true;
    };
    this.$('result-fullscreen').onclick=async()=>{
      const target=this.view==='frame'?this.$('wipe-host'):this.video;
      try{await target.requestFullscreen();}
      catch{this.message('Fullscreen is unavailable.');}
    };
    this.$('generate').onclick=()=>this.generate();
    this.$('frame-preview').onclick=()=>this.generate(true);
    this.$('cancel').onclick=()=>this.cancel();
    this.video.ontimeupdate=()=>{if(this.view==='source')this.trimmer.setPlayhead(this.video.currentTime);};
    this.video.onerror=()=>void this.recoverSourcePreview();
    this.video.addEventListener('loadeddata',()=>{
      if(this.$('status').textContent==='Preparing a browser preview…')this.message('');
    });
    this.nodeProgress=installOwnedNodeProgress(this.api,()=>this.job,(job,now)=>this.renderRunning(job,now));
    this.view=this.result?'result':'source';
    this.render();
  }

  $(name){return this.page.querySelector(`[data-${name}]`);}
  fetch(path,body){return this.owner.fetch(path,body);}
  fileURL(file){return this.api.apiURL('/view?'+new URLSearchParams({filename:file.filename,subfolder:(file.subfolder||'').replaceAll('\\','/'),type:file.type}));}
  sourceURL(){
    if(!this.source)return '';
    if(this.playbackURL)return this.playbackURL;
    const parts=this.source.file.split('/');
    return this.fileURL({filename:parts.pop(),subfolder:parts.join('/'),type:'input'});
  }
  setPlayback(info){
    const preferred=info.playback_url||info.media_url;
    this.playbackURL=preferred?this.api.apiURL(preferred):null;
    this.fallbackPlaybackURL=info.media_url&&this.api.apiURL(info.media_url+'&preview=1');
  }
  async recoverSourcePreview(){
    const source=this.source;
    if(this.view==='source'&&source){
      if(!this.playbackURL)await this.refreshSourcePreview();
      if(this.disposed||source!==this.source||this.view!=='source')return;
      if(this.fallbackPlaybackURL&&this.playbackURL!==this.fallbackPlaybackURL){
        this.playbackURL=this.fallbackPlaybackURL;
        this.message('Preparing a browser preview…');
        this.preview('source');
        return;
      }
    }
    this.message('This preview could not play in the browser.');
  }
  async refreshSourcePreview(){
    const source=this.source;
    if(!source?.id||this.playbackURL||this.refreshingPreview)return;
    this.refreshingPreview=true;
    try{
      const info=await this.fetch('/zura/studio/assets/'+encodeURIComponent(source.id)+'/ripple',{});
      if(this.disposed||this.source!==source)return;
      this.source.hdr=HDR.has(info.resolved_colour);
      this.save();
      if(info.playback_url||info.media_url){
        this.setPlayback(info);
        if(this.view==='source')this.preview('source');
      }
    }catch(error){if(!this.disposed&&this.source===source)this.message(error.message);}
    finally{this.refreshingPreview=false;}
  }
  setFrames(first,last){
    if(!this.source||this.busy())return;
    if(!Number.isInteger(first)||!Number.isInteger(last)||first<1||last<first||last>this.source.frames){
      this.message('Choose a frame range within the source clip. Out frame is inclusive.');
      this.render();
      return;
    }
    const fps=this.source.fps;
    this.range=first===1&&last===this.source.frames?null:{start:(first-1)/fps,duration:(last-first+1)/fps};
    this.message('');
    this.save();
    this.preview('source');
    this.video.currentTime=(first-1)/fps;
  }
  busy(){return !!(this.uploadController||this.submitting||this.job||this.pendingSubmission);}
  refining(){return ['ltx25_tiled_x2',HDR_REFINE].includes(this.model);}
  config(){const {id,width,height,frames,fps}=this.source||{};return {...this.extension,sourceId:id,fps,file:this.source?.file,start:this.range?.start||0,duration:this.range?.duration||0,detail:this.detail,model:this.model,width,height,rtxScale:this.rtxScale,rtxQuality:this.rtxQuality,rtxStrength:this.rtxStrength,prompt:this.prompt,negativePrompt:this.negativePrompt,refineScale:this.refineScale,refineOutput:this.refineOutput,frames:this.range?Math.round(this.range.duration*fps):frames};}
  save(){
    try{
      const {source,range,detail,model,result,job,pendingSubmission,prompt,negativePrompt,refineScale,refineOutput,rtxScale,rtxQuality,rtxStrength}=this;
      this.storage.setItem(this.key,JSON.stringify({extension:this.extension,source,range,detail,model,result,job,pendingSubmission,prompt,negativePrompt,refineScale,refineOutput,rtxScale,rtxQuality,rtxStrength}));
      return true;
    }catch{return false;}
  }
  message(text){this.$('status').textContent=text||'';}
  setProgress(title,detail,value=null){
    this.$('progress').hidden=false;
    this.$('progress-title').textContent=title;
    this.$('progress-detail').textContent=detail;
    if(value===null)this.$('bar').removeAttribute('value');
    else this.$('bar').value=value;
  }
  preview(view){
    this.comparison.hide();
    if(view==='frame'&&this.frameReview){
      const {source,result,model}=this.frameReview;
      this.view='frame';
      this.video.pause();
      this.video.hidden=this.$('empty').hidden=true;
      this.comparison.show(this.fileURL(source),this.fileURL(result),0,
        {kind:'image',sourceKind:'image',resultLabel:this.models[model]?.label||'Processed frame'});
      this.render();
      return;
    }
    this.view=view==='tail'&&this.result?.tail?'tail':view==='result'&&this.result?'result':'source';
    const file=this.view==='tail'?this.result.tail:this.view==='result'?this.result.file:null;
    const url=file?this.fileURL(playbackFile(file)):this.sourceURL();
    this.video.hidden=!url;
    this.$('empty').hidden=!!url;
    if(url&&this.video.getAttribute('src')!==url){
      this.video.pause();
      this.video.setAttribute('src',url);
      this.video.load();
    }
    if(!url){this.video.pause();this.video.removeAttribute('src');}
    this.render();
  }
  render(){
    const busy=this.busy(),source=this.source;
    const needsSetup=this.availability?.ready===false;
    this.$('add').disabled=this.$('source').disabled=this.$('detail').disabled=this.$('full').disabled=this.$('model').disabled=busy;
    this.$('source').hidden=!source;
    this.$('source-meta').textContent=source?`${source.name} · ${source.width} × ${source.height} · ${Number(source.fps.toFixed(3))} fps`:'';

    const refine=this.refining(),rtx=this.model===RTX_UPSCALE;
    const scale=refine?this.refineScale:this.models[this.model].scale||2;
    const plan=this.extending&&source?extendPlan(this.config()):null;
    const size=source&&(rtx?rtxSize(source.width,source.height,this.rtxScale):{width:source.width*scale,height:source.height*scale});
    this.$('resolution').textContent=plan?plan.width+' × '+plan.height+' processing':size?size.width+' × '+size.height:'';
    const rtxOutOfRange=rtx&&size&&Object.values(size).some(n=>n<64||n>8192);
    this.$('rtx-scale-control').hidden=this.$('rtx-quality-control').hidden=!rtx;
    this.$('rtx-scale').disabled=this.$('rtx-quality').disabled=this.$('rtx-strength').disabled=busy;
    if(rtx){
      const caps=rtxCapabilities(this.modelInfo);
      const quality=this.$('rtx-quality'),keys=caps.quality.join(',');
      if(quality.dataset.options!==keys){
        quality.dataset.options=keys;
        quality.replaceChildren(...caps.quality.map(id=>{
          const option=this.page.ownerDocument.createElement('option');
          option.value=id;
          option.textContent=RTX_QUALITY[id];
          return option;
        }));
      }
      quality.value=caps.quality.includes(this.rtxQuality)?this.rtxQuality:caps.quality[0];
      this.$('rtx-strength-control').hidden=!caps.strength;
      this.$('rtx-strength-value').textContent=Math.round(this.rtxStrength*100)+'%';
    }else this.$('rtx-strength-control').hidden=true;
    const textGuidance=this.models[this.model].textGuidance;
    this.$('prompt-control').hidden=!textGuidance&&!this.extending;
    this.$('negative-control').hidden=!textGuidance;
    this.$('refine-scale-control').hidden=!refine;
    this.$('negative-status').hidden=!this.negativePrompt.trim();
    if(this.extending){
      for(const field of ['seconds','context','megapixels','steps','seed','turbo-strength','audio'])this.$(field).disabled=busy;
      this.$('turbo-control').hidden=this.model!==EXTEND_DEFAULT;
    }
    const output=this.$('refine-output'),canChooseOutput=this.model===HDR_REFINE;
    output.value=canChooseOutput?this.refineOutput:'sdr';
    output.disabled=busy||!canChooseOutput;
    output.title=canChooseOutput?'Choose the final video range':'This workflow exports SDR';
    this.$('negative').disabled=this.$('refine-scale').disabled=busy;
    const relay=this.model.startsWith('relayvsr_');
    this.$('detail-hint').hidden=!relay;
    this.$('prompt').disabled=busy;
    this.$('detail-control').hidden=!relay;
    this.$('detail-value').textContent=Math.round(this.detail*100)+'%';
    this.$('range').textContent=this.range?`${this.range.duration.toFixed(2)}s selected`:'Full clip';
    this.$('trim').hidden=!source;
    if(source){
      this.$('in').max=this.$('out').max=String(source.frames);
      this.$('in').value=String(this.range?Math.round(this.range.start*source.fps)+1:1);
      this.$('out').value=String(this.range?Math.round((this.range.start+this.range.duration)*source.fps):source.frames);
    }
    this.$('in').disabled=this.$('out').disabled=busy;
    this.trimmer.update(source&&{...source,url:this.sourceURL()},this.range?{...this.range,length_mode:'custom',workflow_mode:'relight'}:{length_mode:'original',workflow_mode:'relight'},{disabled:busy});
    const wrongSource=source?.hdr!==undefined&&source.hdr!==(this.model===HDR_REFINE);
    const hint=wrongSource?(this.extending?'Add an SDR video to extend.':source.hdr?'Choose LTX Refine (HDR) for this source.':'LTX Refine (HDR) needs an HDR source video.'):rtxOutOfRange?'Choose an RTX scale that gives dimensions between 64 and 8192 pixels.':'';
    this.$('range-hint').hidden=!hint;
    this.$('range-hint').textContent=hint;
    this.$('generate').disabled=busy||(!needsSetup&&(!source||wrongSource||rtxOutOfRange));
    this.$('frame-preview').hidden=this.extending;
    this.$('frame-preview').disabled=busy||!source||!!wrongSource||!!rtxOutOfRange;
    this.$('generate').textContent=busy?'Working…':needsSetup?'Set up '+this.models[this.model].label:this.extending?'Extend video':refine?'Refine video':'Upscale video';
    this.$('view').hidden=!source||!this.result;
    this.$('compare').hidden=this.extending||this.$('view').hidden;
    this.$('heading').textContent=this.view==='frame'?'Frame preview':this.view==='source'||!this.result?this.title:'Final result';
    this.$('result-fullscreen').hidden=this.view==='frame'?!this.$('wipe-host').requestFullscreen:
      !this.result||!this.video.requestFullscreen;
    if(this.extending){
      this.$('tail-view').hidden=!this.result?.tail;
      this.$('tail-view').textContent=this.view==='tail'?'View full result':'View extension only';
      this.$('tail-download').hidden=!this.result?.tail;
      if(this.result?.tail)this.$('tail-download').href=this.fileURL(this.result.tail);
      if(source&&!this.result&&!busy&&!wrongSource){
        const context=plan.contextFrames/24;
        this.$('range-hint').textContent='The extension begins after the Out frame. H3 uses '+context.toFixed(2)+'s of ending context.';
        this.$('range-hint').hidden=false;
      }
    }
    this.$('view').textContent=this.view==='source'?'View result':'View source';
    this.$('download').hidden=!this.result;
    this.$('exports').hidden=true;
    if(this.result){
      this.$('download').href=this.fileURL(this.result.file);
      this.$('download').download=this.result.file.filename;
      this.$('preview-download').hidden=!this.result.file.preview;
      if(this.result.file.preview)this.$('preview-download').href=this.fileURL(this.result.file.preview);
      const archive=this.result.exports?.find(item=>item.role==='exr')?.file;
      this.$('exr-download').hidden=!archive;
      if(archive)this.$('exr-download').href=this.fileURL(archive);
      this.$('exports').hidden=!this.result.file.preview&&!archive&&!this.result.tail;
    }
    this.$('cancel').disabled=!!this.job?.cancelPending&&!this.job.cancelRetryAvailable;
    if(!busy)this.$('progress').hidden=true;
    this.owner.workflowProgress?.schedule();
  }

  async upload(file){
    if(this.busy()||this.disposed)return;
    if(!/\.(mp4|mov|mkv|webm)$/i.test(file.name)){this.message('Choose an MP4, MOV, MKV or WebM video.');return;}
    if(file.size>2*1024**3){this.message('Use a source video smaller than 2 GB.');return;}
    const controller=new AbortController();
    this.uploadController=controller;
    this.message('');
    this.setProgress('Loading source','Uploading video to ComfyUI');
    this.render();
    try{
      const body=new FormData();
      body.append('file',file,file.name);
      const response=await this.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body,signal:controller.signal,timeoutMs:null});
      const asset=await response.json();
      if(!response.ok||!asset.id||!asset.file)throw Error(asset.error||'Could not upload this video.');
      const info=await this.fetch('/zura/studio/assets/'+encodeURIComponent(asset.id)+'/ripple',{});
      if(this.disposed||controller.signal.aborted)return;
      const hdr=HDR.has(info.resolved_colour);
      const fps=Number(info.fps),duration=Number(asset.duration);
      if(![fps,duration,info.width,info.height].every(value=>Number.isFinite(value)&&value>0)||!Number.isInteger(info.frames)||info.frames<1)throw Error('Could not read this clip’s dimensions or timing.');
      this.source={id:asset.id,file:asset.file,name:asset.name||file.name,width:info.width,
        height:info.height,frames:info.frames,fps,duration,hdr};
      this.setPlayback(info);
      if(!this.extending&&(hdr&&this.model!==HDR_REFINE||!hdr&&this.model===HDR_REFINE)){
        this.model=hdr?HDR_REFINE:DEFAULT_UPSCALE_MODEL;
        this.$('model').value=this.model;
        this.updateAvailability();
      }
      this.range=null;
      this.result=this.frameReview=null;
      if(this.extending)this.$('trim').open=true;
      this.save();
      this.preview('source');
    }catch(error){if(!this.disposed)this.message(controller.signal.aborted?'Upload cancelled.':error.message);}
    finally{this.uploadController=null;if(!this.disposed)this.render();}
  }

  updateAvailability(){
    this.availability=this.modelInfo?(this.extending?extendAvailability:upscaleAvailability)(this.modelInfo,this.model):null;
    this.modelDownloads.setMissingContext(this.model,this.availability?.missing,this.models[this.model].label);
  }
  async checkModels(){
    try{
      this.modelInfo=await this.fetch('/object_info');
      if(this.disposed)return null;
      this.updateAvailability();
      this.render();
      return this.availability;
    }catch(error){
      if(!this.disposed)this.message('Could not check model setup. '+error.message);
      return null;
    }
  }

  async prepareGraph(config){
    if(this.extending){
      if(this.source?.hdr)throw Error('Add an SDR video to extend.');
      return buildExtendGraph(config,this.modelInfo);
    }
    if(config.model!==HDR_REFINE)return buildUpscaleGraph(config,this.modelInfo);
    const reply=await this.fetch('/zura/studio/hdr/native-graph',{
      source_kind:'upload',source_id:config.sourceId,refine:true,upscale_2x:config.refineScale===2,
      prompt:config.prompt,negative_prompt:config.negativePrompt,sdr_delivery:!config.framePreview&&config.refineOutput==='sdr',
      start_frame:Math.round(config.start*config.fps),frame_count:config.frames,
      output:config.framePreview?'hlg_video':'hlg_and_exr',exr_storage:this.owner.outputSettings?.exrStorage('acescg_exr')||'half',
    });
    if(!reply?.graph||reply.details?.width!==config.width*config.refineScale||reply.details?.height!==config.height*config.refineScale||
       reply.details?.frames!==config.frames)throw Error('Could not verify the HDR refine selection.');
    if(config.framePreview){
      const graph=Object.fromEntries(Object.entries(reply.graph).filter(([id])=>!id.startsWith('zura_hdr_')));
      return addUpscaleFramePreviews(graph,config.framePreview,['source',0],['trim_raster',0],true);
    }
    return reply.graph;
  }
  async generate(previewFrame=false){
    if(this.busy()||previewFrame&&this.extending)return;
    if(this.availability?.ready===false){await this.modelDownloads.checkSetup();return;}
    if(!this.source)return;
    let config=this.config();
    if(previewFrame){
      const comparingVideo=this.view==='result'&&!this.$('wipe-host').hidden;
      const playhead=comparingVideo?this.comparison.result.currentTime:this.video.currentTime;
      const time=this.view==='frame'?this.frameReview.frame/config.fps:
        (Number(playhead)||0)+(this.view==='result'?(this.result?.config?.start||0):0);
      config=upscaleFrameConfig(config,this.source.frames,time);
    }
    this.submitting=true;
    this.$('trim').open=false;
    this.message('');
    const label=this.models[this.model].label;
    this.setProgress('Checking setup',`Preparing ${label}`);
    this.render();
    try{
      const availability=await this.checkModels();
      if(this.disposed)return;
      if(!availability?.ready)throw Error(`Check ${label} setup before processing.`);
      const graph=await this.prepareGraph(config);
      if(!this.disposed)await submitOwnedGraph(this,graph,config,'auto',{['zura_'+this.mode+(previewFrame?'_frame':'')]:true});
    }catch(error){if(!this.disposed)this.message(error.message);}
    finally{this.submitting=false;if(!this.disposed)this.render();}
  }
  startPolling(){
    if(this.timer||this.disposed)return;
    this.timer=setInterval(()=>void this.poll(),1500);
    void this.poll();
  }
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  processingTitle(){return this.extending?'Extending video':'Processing video';}
  renderRunning(job,now=Date.now()){
    if(!job.runningSince){
      job.runningSince=now;
      this.save();
    }
    const {node,measurement}=this.nodeProgress?.read(job)||{};
    const title=job.stages?.[node]||job.currentStage||(job.config?.framePreview?'Processing preview frame':this.processingTitle());
    const detail=[durationLabel((now-job.runningSince)/1000)+' elapsed'];
    if(!measurement){
      this.setProgress(title,detail.join(' · '));
      return;
    }
    const {value,max,remaining}=measurement;
    const percent=Math.floor(100*value/max);
    const sampling=/^(sample|hdr_sample)/.test(node);
    detail.unshift(sampling?'Step '+value+' of '+max:percent+'% of this stage');
    if(value===max)detail.push('Finishing this stage…');
    else if(remaining>0)detail.push('About '+durationLabel(remaining)+' left in this stage');
    else detail.push('Estimating time…');
    this.setProgress(title,detail.join(' · '),percent);
  }
  finishTracking(message){
    this.job=this.pendingSubmission=null;
    this.stopPolling();
    this.save();
    this.message(message);
    this.render();
  }
  async poll(){
    if(this.polling||this.disposed)return;
    if(this.pendingSubmission&&!this.job){
      await recoverOwnedSubmission(this,{onMissing:request=>{
        if(this.submitting)return;
        if(request.cancelRequested){
          this.finishTracking('ComfyUI could not find this run. You can try again.');
        }else{
          this.setProgress('Run not found','Choose Cancel run to clear this attempt and try again.');
        }
      }});
      if(!this.job)return;
    }
    const job=this.job;
    if(!job||this.disposed)return;
    if(job.cancelRequested){
      delete job.cancelRequested;
      await cancelOwnedJob(this);
      return;
    }
    this.polling=true;
    try{
      const path='/history/'+encodeURIComponent(job.id);
      const current=()=>!this.disposed&&this.job===job;
      const terminal=entry=>entry?.status?.completed||['error','success','cancelled','interrupted'].includes(entry?.status?.status_str);
      let entry=(await this.fetch(path))[job.id];
      if(!current())return;
      if(!terminal(entry)){
        const queue=await this.fetch('/queue');
        if(!current())return;
        if(!Array.isArray(queue?.queue_running)||!Array.isArray(queue?.queue_pending))throw Error('ComfyUI queue is unavailable.');
        const owns=row=>row[1]===job.id;
        const running=queue.queue_running.some(owns);
        const position=queue.queue_pending.findIndex(owns)+1;
        if(running||position){
          if(job.cancelPending)this.setProgress('Cancelling…','Waiting for ComfyUI to stop this run.');
          else if(running)this.renderRunning(job);
          else this.setProgress('Queued','Position '+position+' · '+durationLabel((Date.now()-job.started)/1000)+' waiting');
          if(this.reconnecting){this.reconnecting=false;this.message('');}
          return;
        }
        // The run can finish between checking history and checking the queue.
        entry=(await this.fetch(path))[job.id];
        if(!current())return;
        if(!terminal(entry)){
          this.finishTracking(job.cancelPending?'Run left the queue after cancellation.':'This run is no longer in the ComfyUI queue. Check the output folder or try again.');
          return;
        }
      }
      const failure=entry.status.messages?.find(([type])=>type==='execution_error')?.[1];
      const interrupted=['cancelled','interrupted'].includes(entry.status.status_str)||
        entry.status.messages?.some(([type])=>type==='execution_interrupted');
      const sample=job.config.framePreview;
      const result=!sample&&!failure&&!interrupted&&completedVideo(entry,job.config);
      this.job=null;
      this.stopPolling();
      if(result)this.showCompletedResult(result);
      else if(sample&&entry.status.status_str==='success'&&!failure&&!interrupted){
        const frameFile=id=>entry.outputs?.['frame_'+id+'_preview']?.images?.find(
          file=>file?.type==='temp'&&/\.png$/i.test(file.filename));
        const source=frameFile('original'),processed=frameFile('result');
        this.save();
        if(source&&processed){
          this.frameReview={frame:sample.frame,model:job.config.model,source,result:processed};
          this.message('');
          this.preview('frame');
        }else{this.message('The run ended without a frame preview.');this.render();}
      }else{
        this.message(interrupted?'Run cancelled.':failure?.exception_message||'The run ended without a finished video.');
        this.save();
        this.render();
      }
    }catch(error){
      if(!this.disposed&&this.job===job){
        this.reconnecting=true;
        this.setProgress('Reconnecting','Waiting for ComfyUI to respond.');
        this.message(error.message);
      }
    }
    finally{this.polling=false;}
  }
  showCompletedResult(result){
    this.result=result;
    this.save();
    this.message('');
    this.preview('result');
  }
  async restoreCompletedResult(){
    if(!this.source||this.busy()||this.result||this.restoringResult)return;
    const receipt=studioGraphReceipt(this,this.mode),source=this.source;
    if(!receipt?.id)return;
    this.restoringResult=true;
    try{
      const entry=(await this.fetch('/history/'+encodeURIComponent(receipt.id)))[receipt.id];
      if(this.disposed||this.source!==source||this.busy()||this.result||entry?.prompt?.[1]!==receipt.id||
         !entry.prompt[3]?.['zura_'+this.mode])return;
      const graph=entry.prompt[2];
      const start=graph?.trim?.inputs?.start_time??(Number(graph?.source?.inputs?.start_frame)||0)/source.fps;
      const result=completedVideo(entry,{start});
      if(result)this.showCompletedResult(result);
    }catch{/* The regular workspace remains available while history is offline. */}
    finally{this.restoringResult=false;}
  }
  async cancel(){
    if(this.uploadController){this.uploadController.abort();return;}
    if(this.pendingSubmission&&!this.job){
      this.pendingSubmission.cancelRequested=true;
      this.save();
      this.setProgress('Cancelling','Checking whether the run started');
      await this.poll();
      return;
    }
    if(this.job)await cancelOwnedJob(this);
  }
  async graph(){
    const availability=await this.checkModels();
    const label=this.models[this.model].label;
    if(!availability?.ready)throw Error(`Complete ${label} setup before opening the graph.`);
    const graph=await this.prepareGraph(this.config());
    await openStudioGraph(this.owner.studio,graph,this.title+" · "+label,this.mode);
  }
  onCancel(){return this.cancel();}
  open(){
    this.modelDownloads.resume();
    this.preview(this.view);
    void this.refreshSourcePreview();
    void this.restoreCompletedResult();
    void this.checkModels();
    if(this.job||this.pendingSubmission){
      this.setProgress('Reconnecting','Checking the ComfyUI queue');
      this.startPolling();
    }
  }
  reset(){
    if(this.busy())return false;
    this.source=this.result=this.frameReview=this.range=this.playbackURL=this.fallbackPlaybackURL=null;
    this.prompt=this.$('prompt').value=this.negativePrompt=this.$('negative').value='';
    this.$('negative-control').open=false;
    this.save();
    this.message('');
    this.preview('source');
    return true;
  }
  close(){
    this.disposed=true;
    this.uploadController?.abort();
    this.stopPolling();
    this.modelDownloads.dispose();
    this.nodeProgress.dispose();
    this.trimmer.close();
    this.comparison.hide();
    this.video.pause();
    this.style.remove();
  }
}

export class ExtendLengthWorkspace extends UpscaleWorkspace{
  constructor(owner){super(owner,true);}
}

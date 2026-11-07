import {ClipTrimmer} from './studio_trim.js';
import {StudioModelDownloads} from './studio_model_download.js';
import {rippleStudioProcessingSize, rippleStudioValidation} from './studio_ripple_recipes.js';
import {RippleTimeline} from './studio_ripple_timeline.js';

const STATE_KEY='zura-ripple-workspace-v1';
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
const frameNumber=value=>Number.isFinite(Number(value))?Math.round(Number(value)):0;
const formatRate=rate=>Number(Number(rate||0).toFixed(3)).toString();
const nextId=()=>globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(36).slice(2)}`;
const initial=()=>({engine:'h3',scale:1,startFrame:0,frameCount:0,playhead:0,prompt:'',sourceColour:'auto',anchors:[],project:null});
function readState(){try{const saved=JSON.parse(localStorage.getItem(STATE_KEY));return saved&&typeof saved==='object'?saved:{};}catch{return {};}}

/** Merge earlier per-model keyframes without losing different edits on one frame. */
function sharedAnchors(saved,engine){
  if(Array.isArray(saved))return saved;
  const groups=saved&&typeof saved==='object'?saved:{},other=engine==='ltx'?'h3':'ltx';
  const result=[],ids=new Set();
  for(const name of [engine,other])for(const value of Array.isArray(groups[name])?groups[name]:[]){
    if(!value||typeof value!=='object')continue;
    const same=result.find(a=>JSON.stringify(a)===JSON.stringify(value));
    if(same)continue;
    const anchor={...value};if(!anchor.id||ids.has(String(anchor.id)))anchor.id=nextId();
    ids.add(String(anchor.id));result.push(anchor);
  }
  // Old model lists could each contain a different edit for the same frame.
  // Keep both cards and use one at a time; selecting the other switches it on.
  for(const anchor of result){
    const variants=result.filter(other=>Number(other.frame)===Number(anchor.frame));
    if(variants.length>1){anchor.legacyVariant=true;anchor.enabled=variants.find(a=>a.enabled!==false)===anchor;}
  }
  return result.sort((a,b)=>Number(a.frame)-Number(b.frame));
}

/** Dedicated timeline for edited frames. Inference stays in the supplied native graph. */
export class RippleWorkspace {
  constructor(owner){
    this.owner=owner;this.api=owner.api;this.root=owner.root;this.app=owner.app;this.closed=true;
    const saved=readState();this.state={...initial(),...saved};
    if(!['h3','ltx'].includes(this.state.engine))this.state.engine='h3';
    if(![1,.75,.5,.25].includes(Number(this.state.scale)))this.state.scale=1;
    this.state.anchors=sharedAnchors(saved.anchors,this.state.engine);
    this.source=null;this.sourceInfo=null;this.selectedId=saved.selectedId||null;this.job=saved.job||null;this.pendingSubmission=saved.pendingSubmission||null;this.result=saved.result||null;
    this.revision=0;this.submitting=false;this.importing=false;this.exporting=false;this.picking=false;this.modelInfo=null;this.availability=null;
    const doc=this.root.ownerDocument;
    if(!doc.getElementById('zura-ripple-styles')){const style=doc.createElement('link');style.id='zura-ripple-styles';style.rel='stylesheet';style.href=new URL('./studio_ripple.css',import.meta.url).href;doc.head.append(style);}
    this.page=doc.createElement('section');this.page.className='zru-page';this.page.hidden=true;
    this.page.innerHTML=`<header class="zru-heading"><div><h2>Ripple edit</h2></div><button type="button" data-view-result hidden>View result</button></header>
      <div class="zru-viewer" aria-label="Video preview"><video data-video controls playsinline preload="metadata" hidden></video><div data-frame-preview role="img" aria-label="Selected source frame" hidden></div><div data-empty class="zru-empty"><strong>Edit a video with Ripple</strong><span>Add a clip, then place edited frames along its timeline.</span></div></div>
      <div data-timeline class="zru-timeline" hidden><div data-visual-timeline></div>
          <div class="zru-time-row"><label for="zru-frame">Frame</label><input id="zru-frame" data-frame type="text" inputmode="numeric" aria-label="Current source frame"/><span data-frame-total></span><details class="zc-tool-popup zru-trim"><summary>Trim clip <span data-trim-label></span></summary><div class="zc-tool-panel"><div data-trimmer></div><button type="button" data-full-clip>Use full clip</button></div></details></div>
          <div data-anchor-editor class="zru-anchor-editor" hidden><div class="zru-anchor-name"><strong data-anchor-label></strong><span data-anchor-status></span></div><div class="zru-anchor-actions"><button type="button" data-edit>Edit image</button><button type="button" data-export>Save frame</button><button type="button" data-import>Import edit</button><button type="button" data-compare hidden>View edit</button><input data-import-file type="file" accept="image/png,image/tiff,.tif,.tiff,.exr" hidden/></div></div>
        </div>
      <div data-progress class="zru-progress" role="status" aria-live="polite" hidden><div><strong data-progress-title>Preparing</strong><button type="button" data-cancel>Cancel run</button></div><progress data-bar max="100" aria-label="Ripple generation progress"></progress><span data-progress-detail></span></div>
      <div class="zru-composer zc-prompt-card"><div class="zru-attachments"><button type="button" class="zc-attachment" data-source>Add video</button><input data-source-file type="file" accept="video/*,.mov,.mkv,.mxf,.avi" hidden/><span data-source-meta></span><button type="button" class="zru-clear-source" data-clear-source aria-label="Remove source video" title="Remove source video" hidden>×</button></div>
        <label class="zru-prompt-label" for="zru-prompt">Describe your edit</label><textarea id="zru-prompt" data-prompt rows="2" maxlength="12000" placeholder="Describe the change to carry through the video"></textarea>
        <div class="zc-prompt-bottom"><div class="zru-tools zc-prompt-tools"><label class="zc-tool zru-model"><span class="zru-model-icon" aria-hidden="true">◇</span><span class="zc-sr-only">Ripple model</span><select data-engine aria-label="Ripple model"><option value="h3">H3 · Ripple</option><option value="ltx">LTX 2.5 · Ripple</option></select></label><label class="zc-tool zru-size"><span class="zc-sr-only">Processing resolution</span><select data-scale aria-label="Processing resolution"><option value="1">Full resolution</option><option value="0.75">75% resolution</option><option value="0.5">50% resolution</option><option value="0.25">25% resolution</option></select></label><span data-processing-size class="zru-size-label"></span><details data-model-downloads class="zc-tool-popup gs-model-help" hidden></details></div><div class="zru-actions"><a data-download download hidden>Save video</a><button type="button" class="gs-primary" data-generate>Generate video</button></div></div>
        <p data-status class="zru-status" role="status" aria-live="polite">Ripple edits the whole frame. Surrounding details may also change.</p>
      </div>`;
    this.root.append(this.page);this.video=this.$('video');this.framePreview=this.$('frame-preview');
    const colour=doc.createElement('label');colour.className='zru-source-colour';colour.hidden=true;colour.innerHTML='<span>Untagged SDR</span><select data-source-colour aria-label="Source colour for untagged video"><option value="rec709_oetf">Assume Rec.709</option><option value="srgb_display">sRGB</option><option value="rec709_gamma24">Rec.709 · gamma 2.4</option></select>';this.$('source-meta').after(colour);this.sourceColourControl=colour;
    this.$('source-colour').onchange=()=>{if(this.busy())return;this.owner.rippleImage?.invalidate(this);this.state.sourceColour=this.$('source-colour').value;++this.revision;this.save();this.render();};
    this.$('prompt').value=this.state.prompt||'';this.$('engine').value=this.state.engine;this.$('scale').value=String(this.state.scale);
    this.modelDownloads=new StudioModelDownloads(this.$('model-downloads'),(path,body)=>this.fetch('/zura/studio'+path,body),()=>this.checkModels());this.modelDownloads.mountQuick(this.page.querySelector('.zru-composer'));
    this.$('source').onclick=()=>this.$('source-file').click();this.$('source-file').onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)void this.uploadSource(file);};this.$('clear-source').onclick=()=>this.reset();
    this.$('engine').onchange=()=>{if(this.busy())return;this.owner.rippleImage?.invalidate(this);if(this.viewingEdit)this.viewAnchor(false);this.state.engine=this.$('engine').value;this.save();this.checkModels();this.render();};
    this.$('scale').onchange=()=>{if(this.busy())return;this.state.scale=Number(this.$('scale').value);this.save();this.render();};
    this.$('prompt').oninput=()=>{this.state.prompt=this.$('prompt').value;this.save();};
    this.$('frame').onfocus=e=>e.target.select();this.$('frame').onchange=e=>{const raw=e.target.value.trim(),n=Number(raw);if(!raw||!Number.isInteger(n)){this.message('Enter a whole frame number.');this.render();return;}this.seek(n);};
    this.$('frame').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();const n=Number(e.target.value.trim());if(Number.isInteger(n))this.addAnchor(n);else this.message('Enter a whole frame number.');}};
    this.$('edit').onclick=()=>{const anchor=this.selected();if(!anchor)return;if(typeof this.owner.editRippleFrame!=='function'){this.message('The image editor is not available.');return;}void Promise.resolve(this.owner.editRippleFrame(this,anchor)).catch(error=>this.message(error.message));};
    this.$('export').onclick=()=>void this.exportAnchor();this.$('import').onclick=()=>this.$('import-file').click();
    this.$('import-file').onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)void this.importAnchorFile(this.selected(),file).catch(()=>{});};
    this.$('compare').onclick=()=>this.viewAnchor(!this.viewingEdit);
    this.$('generate').onclick=()=>void this.generate();this.$('cancel').onclick=()=>void this.cancel();
    this.$('view-result').onclick=()=>{if(!this.result?.file)return;if(this.video.dataset.kind==='result')this.viewAnchor(false);else{this.viewingEdit=false;this.showResult(this.result);this.render();}};
    this.video.addEventListener('error',()=>{if(this.source&&this.video.dataset.kind==='source'){this.video.hidden=true;this.framePreview.hidden=false;this.showFramePreview();this.message('Playback is unavailable for this format. The selected frame remains available for editing.');}});
    this.video.addEventListener('loadedmetadata',()=>this.applySourceSeek());
    this.video.addEventListener('timeupdate',()=>this.syncSourcePlayhead());
    for(const event of ['seeked','pause'])this.video.addEventListener(event,()=>this.syncSourcePlayhead(true));
    this.trimmer=new ClipTrimmer(this.$('trimmer'),{onSeek:seconds=>this.seek(Math.floor(seconds*this.fps())),onCommit:range=>this.setTrim(range)});
    this.timeline=new RippleTimeline(this.$('visual-timeline'),this);
    this.$('full-clip').onclick=()=>this.fullClip();
    this.render();
  }
  $(name){return this.page.querySelector(`[data-${name}]`);}
  fetch(path,body){return this.owner.fetch(path,body);}
  url(path){return this.api.apiURL(path);}
  fps(){const rate=Number(this.source?.fps);return Number.isFinite(rate)&&rate>0?rate:24;}
  colourSpace(){return this.state.sourceColour&&this.state.sourceColour!=='auto'?this.state.sourceColour:this.source?.resolved_colour||'rec709_oetf';}
  thumbnail(file,frame=0,space=this.colourSpace(),size=240){return this.url('/zura/paintout/frame-preview?'+new URLSearchParams({file,frame,space,size}));}
  busy(){return !!(this.job||this.pendingSubmission||this.submitting||this.importing||this.exporting||this.picking);}
  anchors(){return this.state.anchors;}
  selected(){return this.anchors().find(anchor=>String(anchor.id)===String(this.selectedId))||null;}
  message(text){this.$('status').textContent=text||'Ripple edits the whole frame. Surrounding details may also change.';}
  save(){try{localStorage.setItem(STATE_KEY,JSON.stringify({...this.state,selectedId:this.selectedId,job:this.job,pendingSubmission:this.pendingSubmission,result:this.result,sourcePath:this.source?.path||this.state.sourcePath||''}));return true;}catch{return false;}}
  async uploadSource(file){
    if(this.busy())return;const revision=++this.revision;this.picking=true;this.uploadController=new AbortController();this.setProgress({title:'Loading video',detail:'Preparing your source footage'});this.render();this.message('');
    try{const body=new FormData();body.append('file',file,file.name);const response=await this.api.fetchApi('/zura/studio/upload?kind=video',{method:'POST',body,signal:this.uploadController.signal,timeoutMs:null});const asset=await response.json();if(!response.ok)throw Error(asset.error||'Could not upload this video.');if(!asset.id)throw Error('The uploaded video could not be identified.');if(revision!==this.revision)return;const info=await this.fetch('/zura/studio/assets/'+encodeURIComponent(asset.id)+'/ripple',{});if(revision!==this.revision)return;this.setSource({...info,name:asset.name||file.name||info.name});}
    catch(error){if(revision===this.revision)this.message(error.message||'Could not open this video.');}
    finally{if(revision===this.revision){this.picking=false;this.uploadController=null;this.clearProgress();this.render();}}
  }
  async pickSource(){
    if(this.busy())return;const revision=++this.revision;this.picking=true;this.render();
    try{const response=await this.fetch('/zura/paintout/pick',{kind:'footage'});if(revision!==this.revision||!response.paths?.length)return;const info=await this.fetch('/zura/paintout/info?'+new URLSearchParams({file:response.paths[0]}));if(revision!==this.revision)return;this.setSource(info);}
    catch(error){if(revision===this.revision)this.message(error.message||'Could not open this video.');}
    finally{if(revision===this.revision){this.picking=false;this.render();}}
  }
  setSource(info){
    if(!info?.path||info.kind!=='video'||!Number.isInteger(info.frames)||info.frames<1||!(info.width>0&&info.height>0))throw Error('Choose a supported video clip.');
    this.owner.rippleImage?.invalidate(this);
    ++this.revision;this.source=this.sourceInfo=info;this.state={...initial(),engine:this.state.engine,scale:this.state.scale,prompt:this.state.prompt,sourcePath:info.path,sourceName:info.name||'',frameCount:info.frames};
    this.state.sourceColour=info.resolved_colour||'rec709_oetf';this.selectedId=null;this.result=null;this.job=null;this.pendingSubmission=null;this.picking=false;this.projectPromise=null;this.viewingEdit=false;this.uploadController=null;this.clearProgress();
    this.video.dataset.kind='source';this.video.src=this.url(info.media_url||info.thumbnail_url);this.video.hidden=false;this.framePreview.hidden=true;this.video.load();this.$('empty').hidden=true;this.seek(0);this.message(['hlg_rec2020','pq_rec2020','pq_display_p3','acescg','acescct','linear_rec709'].includes(info.resolved_colour)?'Ripple currently supports SDR footage.':'');this.save();this.render();
  }
  setSourceAsset(info){this.setSource(info);}
  async restoreSource(){
    const path=this.state.sourcePath;if(!path||this.source?.path===path)return;const revision=++this.revision;
    try{const info=await this.fetch('/zura/paintout/info?'+new URLSearchParams({file:path}));if(revision!==this.revision||this.state.sourcePath!==path)return;this.source=this.sourceInfo=info;this.state.frameCount=clamp(frameNumber(this.state.frameCount)||info.frames,1,info.frames);this.state.startFrame=clamp(frameNumber(this.state.startFrame),0,info.frames-this.state.frameCount);this.state.playhead=clamp(frameNumber(this.state.playhead),0,info.frames-1);this.video.dataset.kind='source';this.video.src=this.url(info.media_url||info.thumbnail_url);this.video.hidden=false;this.framePreview.hidden=true;this.$('empty').hidden=true;this.video.load();this.seek(this.state.playhead);if(this.result?.file&&(!this.result.config?.source||this.result.config.source===path)&&!this.job&&!this.pendingSubmission)this.showResult(this.result);this.render();}
    catch(error){if(revision===this.revision)this.message('Choose the source video again to restore its preview.');}
  }
  showFramePreview(file=this.source?.path,frame=this.state.playhead,space=this.colourSpace()){if(!file)return;const url=this.url('/zura/paintout/frame-preview?'+new URLSearchParams({file,frame,space,size:1280}));this.framePreview.style.backgroundImage=`url(${JSON.stringify(url)})`;}
  viewAnchor(showEdit){const anchor=this.selected();if(showEdit&&anchor?.file){this.showFramePreview(anchor.file,0,anchor.colour_space||'srgb_display');this.viewingEdit=true;this.video.pause();this.video.hidden=true;this.framePreview.hidden=false;}else{this.viewingEdit=false;this.framePreview.hidden=true;if(this.source){this.video.dataset.kind='source';this.video.src=this.url(this.source.media_url||this.source.thumbnail_url);this.video.hidden=false;this.video.load();this.pendingSourceFrame=this.state.playhead;this.applySourceSeek();}}this.render();}
  applySourceSeek(){
    if(!this.source||this.video.dataset.kind!=='source'||this.pendingSourceFrame==null||this.video.readyState<1)return;
    // Seek inside the frame, avoiding a timestamp rounded just before its boundary.
    try{this.video.currentTime=(this.pendingSourceFrame+.5)/this.fps();this.pendingSourceFrame=null;}catch{/* Retry when source metadata arrives. */}
  }
  syncSourcePlayhead(persist=false,allowSeeking=false){
    if(!this.source||this.video.dataset.kind!=='source'||this.viewingEdit||this.video.hidden||this.video.readyState<1||this.pendingSourceFrame!=null||this.video.seeking&&!allowSeeking||!Number.isFinite(this.video.currentTime))return;
    const frame=clamp(Math.floor(this.video.currentTime*this.fps()+1e-6),0,this.source.frames-1);
    this.state.playhead=frame;
    if(this.selected()&&this.selected().frame!==frame){this.selectedId=null;this.render();}else this.updatePlayhead();
    if(persist)this.save();
  }
  seek(frame){if(!this.source)return;this.state.playhead=clamp(frameNumber(frame),0,this.source.frames-1);const selectionChanged=!!this.selected()&&this.selected().frame!==this.state.playhead;if(selectionChanged)this.selectedId=null;if(this.viewingEdit||this.video.dataset.kind==='result')this.viewAnchor(false);if(this.video.dataset.kind==='source'){this.pendingSourceFrame=this.state.playhead;this.applySourceSeek();}if(!this.framePreview.hidden)this.showFramePreview();if(selectionChanged)this.render();else this.updatePlayhead();this.save();}
  updatePlayhead(){this.timeline?.setPlayhead(this.state.playhead);this.$('frame').value=String(this.state.playhead);this.trimmer?.setPlayhead(this.state.playhead/this.fps());}
  addAtPlayhead(){if(this.busy())return;this.syncSourcePlayhead(true,true);this.addAnchor(this.state.playhead);}
  addAnchor(frame){
    if(!this.source||this.busy())return;frame=clamp(frameNumber(frame),0,this.source.frames-1);
    if(this.state.engine==='ltx'&&frame!==this.state.startFrame){this.message(`LTX can only use frame ${this.state.startFrame}, the clip's first frame. Use H3 for keyframes elsewhere, or change the trim start.`);return;}
    const outside=frame<this.state.startFrame||frame>=this.state.startFrame+this.state.frameCount;
    let anchor=this.anchors().find(a=>a.frame===frame&&a.enabled!==false)||this.anchors().find(a=>a.frame===frame);if(!anchor){if(!outside&&this.state.engine==='h3'&&this.anchors().filter(a=>a.enabled!==false&&a.frame>=this.state.startFrame&&a.frame<this.state.startFrame+this.state.frameCount).length>=16){this.message('H3 Ripple supports up to 16 keyframes in a clip.');return;}anchor={id:nextId(),frame,file:'',colour_space:'srgb_display',enabled:true};this.anchors().push(anchor);this.anchors().sort((a,b)=>a.frame-b.frame);}
    this.selectAnchor(anchor.id);if(outside)this.message(`Keyframe ${frame} added outside the trim. Extend the In/Out range to include it in the video.`);
  }
  selectAnchor(id){if(this.busy())return;const anchor=this.anchors().find(a=>String(a.id)===String(id));if(!anchor)return;this.video.pause();if(anchor.legacyVariant){for(const variant of this.anchors())if(variant.legacyVariant&&Number(variant.frame)===Number(anchor.frame))variant.enabled=variant===anchor;}this.selectedId=anchor.id;if(this.viewingEdit)this.viewAnchor(false);this.seek(anchor.frame);this.message('');this.save();this.render();}
  removeAnchor(){if(this.busy())return;const anchor=this.selected();if(!anchor)return;if(this.viewingEdit)this.viewAnchor(false);this.state.anchors=this.anchors().filter(a=>a!==anchor);if(anchor.legacyVariant&&anchor.enabled!==false){const other=this.anchors().find(a=>a.legacyVariant&&Number(a.frame)===Number(anchor.frame));if(other)other.enabled=true;}this.selectedId=null;this.save();this.render();}
  setTrim(range){if(!this.source||this.busy())return;const fps=this.fps(),total=this.source.frames,start=clamp(Math.round(range.start*fps),0,total-1),end=clamp(Math.round((range.start+range.duration)*fps),start+1,total);this.state.startFrame=start;this.state.frameCount=end-start;this.seek(start);this.save();this.render();}
  fullClip(){if(!this.source||this.busy())return;this.state.startFrame=0;this.state.frameCount=this.source.frames;this.seek(0);this.save();this.render();}
  async prepareAnchor(anchor){
    if(!this.source||!anchor||!this.anchors().includes(anchor))throw Error('Choose a keyframe first.');
    const revision=this.revision,source=this.source.path,frame=anchor.frame,result=await this.fetch('/zura/paintout/export-frame',{file:source,frame,colour_space:this.colourSpace()});
    if(revision!==this.revision||this.source?.path!==source||!this.anchors().includes(anchor)||anchor.frame!==frame)throw Error('The source or keyframe changed. Select the frame again.');return result;
  }
  async exportAnchor(){
    if(this.busy())return;const anchor=this.selected();if(!anchor)return;this.exporting=true;this.render();
    try{const file=await this.prepareAnchor(anchor),link=this.page.ownerDocument.createElement('a');link.href=this.url(file.url);link.download=file.download_name||`frame_${anchor.frame}.png`;link.click();this.message(`Frame ${anchor.frame} saved. Import your edited image into this keyframe.`);}
    catch(error){this.message(error.message||'Could not save this frame.');}finally{this.exporting=false;this.render();}
  }
  async ensureProject(){
    if(!this.source)throw Error('Add footage first.');if(this.state.project)return this.state.project;
    if(this.projectPromise)return this.projectPromise;
    const revision=this.revision,source=this.source.path;
    this.projectPromise=(async()=>{const document=await this.fetch('/zura/paintout/editor/project',{data:{draft:{source}}});if(revision!==this.revision||this.source?.path!==source)throw Error('The source changed. Select the frame again.');this.state.project=document.id;this.save();return document.id;})();
    try{return await this.projectPromise;}finally{if(revision===this.revision)this.projectPromise=null;}
  }
  async importAnchorFile(anchor,file,check=()=>{}){
    if(!anchor||!file||!this.source||this.importing)throw Error('Choose a keyframe and edited image first.');
    const revision=this.revision,source=this.source.path,frame=anchor.frame,engine=this.state.engine;this.importing=true;this.render();
    try{const project=await this.ensureProject(),body=new FormData();body.append('project',project);body.append('source',source);body.append('frame',String(frame));body.append('colour_space','srgb_display');body.append('file',file,file.name||`frame_${frame}.png`);
      const response=await this.api.fetchApi('/zura/paintout/editor/import-frame',{method:'POST',body});const result=await response.json();if(!response.ok)throw Error(result.error||'Could not import this edited image.');
      if(revision!==this.revision||this.source?.path!==source||this.state.engine!==engine||!this.anchors().includes(anchor)||anchor.frame!==frame)throw Error('The source or keyframe changed. Import the image again.');
      if(Number(result.frame)!==frame||!result.file)throw Error('The imported image does not match this keyframe.');
      check();Object.assign(anchor,{file:result.file,colour_space:result.colour_space||'srgb_display',enabled:true});this.selectedId=anchor.id;this.save();this.message(`Edit ready for frame ${frame}.`);return anchor;
    }catch(error){this.message(error.message||'Could not import this edited image.');throw error;}finally{this.importing=false;this.render();}
  }
  config(){
    const source=this.source,size=source?rippleStudioProcessingSize(source.width,source.height,Number(this.state.scale),this.state.engine):{width:0,height:0};
    const start=this.state.startFrame,end=start+this.state.frameCount;
    const anchors=this.anchors().filter(a=>a.enabled!==false&&a.frame>=start&&a.frame<end&&(this.state.engine!=='ltx'||a.frame===start)).map(a=>({...a}));
    return {engine:this.state.engine,source:source?.path||'',startFrame:start,frameCount:this.state.frameCount,sequenceFps:this.fps(),width:size.width,height:size.height,resolutionMode:'plate',anchors,prompt:this.$('prompt').value,seed:42,outputMode:'SDR video',sourceColour:this.colourSpace(),detectedSourceColour:source?.resolved_colour||''};
  }
  async generate(){
    if(this.busy())return;const config=this.config(),error=rippleStudioValidation(config);if(error){this.message(error);return;}
    if(typeof this.onGenerate!=='function'){this.message('Ripple is still connecting to ComfyUI. Try again shortly.');return;}
    try{await this.onGenerate(config);}catch(error){this.message(error.message||'Could not start the Ripple run.');this.render();}
  }
  async cancel(){if(this.picking&&this.uploadController){this.uploadController.abort();this.uploadController=null;this.picking=false;++this.revision;this.clearProgress();this.message('Video upload cancelled.');this.render();return;}if((this.job||this.pendingSubmission)&&typeof this.onCancel==='function')await this.onCancel(this.job);}
  setProgress({title='Generating video',detail='',value=null}={}){this.$('progress').hidden=false;this.$('progress-title').textContent=title;this.$('progress-detail').textContent=detail;if(Number.isFinite(value))this.$('bar').value=clamp(value,0,100);else this.$('bar').removeAttribute('value');}
  clearProgress(){this.$('progress').hidden=true;this.$('bar').removeAttribute('value');}
  setResult(result){
    this.result=result;this.job=null;this.clearProgress();const file=result?.file;if(!file){this.message('The run completed without a playable video. Check the output folder.');this.render();return;}
    this.showResult(result);this.message('Your finished video is ready.');this.save();this.render();
  }
  showResult(result){const output=file=>this.url('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'}));this.video.dataset.kind='result';this.video.src=result.preview_url?this.url(result.preview_url):output(result.file);this.video.hidden=false;this.framePreview.hidden=true;this.$('empty').hidden=true;this.video.load();this.$('download').href=result.download_url?this.url(result.download_url):output(result.master||result.file);this.$('download').hidden=false;}
  async checkModels(){if(typeof this.onCheckModels==='function')try{await this.onCheckModels(this.state.engine);}catch(error){this.message(error.message||'Could not check Ripple models.');}}
  setAvailability(availability){this.availability=availability;const missing=availability?.missing||[];this.$('model-downloads').hidden=availability?.ready!==false;this.modelDownloads.setMissingContext(this.state.engine==='h3'?'h3_ripple':'ltx_ripple',missing);this.render();}
  openModelSetup(engine,availability=this.availability){this.setAvailability(availability);this.$('model-downloads').hidden=false;this.$('model-downloads').open=true;this.modelDownloads.load();}
  render(){
    const has=!!this.source,busy=this.busy(),anchor=this.selected(),frames=this.source?.frames||0,start=this.state.startFrame,end=start+this.state.frameCount;
    this.$('timeline').hidden=!has;this.$('empty').hidden=has||!!this.result;this.$('source').textContent=has?'Replace video':'Add video';this.$('clear-source').hidden=!has;
    this.$('source-meta').textContent=has?`${this.state.sourceName||this.source.name||this.source.path.split(/[\\/]/).pop()} · ${this.source.width} × ${this.source.height} · ${formatRate(this.fps())} fps`:'';
    if(this.sourceColourControl){this.sourceColourControl.hidden=!has||!!this.source.resolved_colour;this.$('source-colour').value=this.state.sourceColour==='auto'?'rec709_oetf':this.state.sourceColour;this.$('source-colour').disabled=busy;}
    this.$('frame-total').textContent=has?`of ${frames-1}`:'';this.updatePlayhead();
    this.$('trim-label').textContent=has?`${(this.state.frameCount/this.fps()).toFixed(2).replace(/\.?0+$/,'')}s`:'';
    this.$('anchor-editor').hidden=!anchor;this.$('anchor-label').textContent=anchor?`Frame ${anchor.frame}`:'';this.$('anchor-status').textContent=anchor?(this.state.engine==='ltx'&&anchor.frame!==start?`Saved for H3 · LTX uses frame ${start}`:anchor.frame<start||anchor.frame>=end?'Outside trim · extend In/Out to use':anchor.file?'Edited image ready':'Add an edited image'):'';this.$('compare').hidden=!anchor?.file;this.$('compare').textContent=this.viewingEdit?'View original':'View edit';
    this.timeline.update({startFrame:start,frameCount:this.state.frameCount||1,totalFrames:frames||1,fps:this.fps(),playhead:this.state.playhead,anchors:this.anchors().map(a=>({...a,status:a.file?'accepted':'draft'})),selected:this.anchors().indexOf(anchor),stage:'clean',busy,thumbnail:a=>a.file?this.thumbnail(a.file,0,a.colour_space||'srgb_display'):this.thumbnail(this.source?.path,a.frame)});
    for(const name of ['source','clear-source','engine','scale','frame','scrub','add-on-track','edit','export','import','compare','full-clip'])this.$(name).disabled=busy||(!has&&!['source','engine','scale'].includes(name));
    this.$('generate').disabled=busy||!has;this.$('cancel').disabled=!this.job&&!this.pendingSubmission&&!this.uploadController;this.$('download').hidden=!this.result?.file;this.$('view-result').hidden=!this.result?.file;this.$('view-result').textContent=this.video.dataset.kind==='result'?'View source':'View result';
    if(has){const size=rippleStudioProcessingSize(this.source.width,this.source.height,Number(this.state.scale),this.state.engine);this.$('processing-size').textContent=`${size.width} × ${size.height} processing · ${this.source.width} × ${this.source.height} output`;this.trimmer.update({url:this.url(this.source.media_url||''),duration:frames/this.fps(),fps:this.fps()},{workflow_mode:'relight',length_mode:'custom',start:start/this.fps(),duration:this.state.frameCount/this.fps()},{disabled:busy});this.trimmer.setPlayhead(this.state.playhead/this.fps());}else{this.$('processing-size').textContent='';this.trimmer.update(null,{});}
  }
  reset(){if(this.busy())return false;this.owner.rippleImage?.invalidate(this);++this.revision;this.trimmer.close();this.video.pause();this.video.removeAttribute('src');this.video.load();this.video.hidden=true;this.framePreview.hidden=true;this.framePreview.style.backgroundImage='';this.source=this.sourceInfo=null;this.state=initial();this.selectedId=null;this.result=null;this.job=null;this.pendingSubmission=null;this.projectPromise=null;this.viewingEdit=false;this.$('prompt').value='';this.$('engine').value='h3';this.$('scale').value='1';this.$('download').hidden=true;this.clearProgress();this.message('');this.save();this.render();return true;}
  open(){this.closed=false;this.page.hidden=false;void this.restoreSource();void this.checkModels();if(this.job||this.pendingSubmission)void this.onResume?.();this.render();}
  graph(){if(typeof this.onGraph==='function')return this.onGraph(this.config());this.message('The editable graph is not available until the Ripple setup is ready.');}
  close(){this.closed=true;this.page.hidden=true;this.video.pause();this.trimmer.close();}
  dispose(){++this.revision;this.close();this.timeline.dispose();this.rippleJobs?.dispose();this.modelDownloads.dispose();this.page.remove();}
}

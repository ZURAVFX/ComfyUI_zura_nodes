import {maskIcons} from './paintout_icons.js';
import {PaintoutTimeline} from './paintout_timeline.js';
import {PaintoutMaskViewer} from './paintout_viewer.js';
import {buildFrameEditGraph,frameEditAvailability} from './paintout_frame_recipes.js';

const endpoint='/zura/paintout/editor';
const el=(tag,text)=>{const node=document.createElement(tag);if(text)node.textContent=text;return node;};
const number=(value,min,max)=>Math.max(min,Math.min(max,Math.round(Number(value)||0)));

export function paintoutDraft(saved={}){
  const draft={mode:'targeted',source:'',mask:'',anchors:[],startFrame:0,frameCount:81,sequenceFps:25,sourceColour:'srgb_display',processingSpace:'SDR (sRGB)',width:1152,height:640,resolutionMode:'default',megapixels:.75,outputMode:'SDR video',seed:42,maskSubject:'',maskGrow:0,maskFeather:0,editorStage:'mask',...saved};
  draft.maskFeather=0; // Repair masks stay hard, including drafts saved by earlier builds.
  draft.anchors=Array.isArray(draft.anchors)?draft.anchors:[];
  return draft;
}

export function maskGraph(config,info={}){
  const {project,revision,source,frame,startFrame,frameCount,colourSpace,operation,direction,selection,text}=config;
  const graph={};
  const inputs={source,project,frame,start_frame:startFrame,frame_count:frameCount,colour_space:colourSpace,
    operation,direction,positive_coords:JSON.stringify(selection.positive||[]),negative_coords:JSON.stringify(selection.negative||[]),
    text:text||'',paint_mask:selection.hasMask?selection.mask:'',expected_revision:revision};
  if(operation!=='absent'&&(!selection.hasMask||frameCount>1)){
    const field=info.CheckpointLoaderSimple?.input?.required?.ckpt_name;
    const files=Array.isArray(field?.[0])?field[0]:field?.[1]?.options||[];
    const file=files.find(f=>/sam3\.1_multiplex_fp16\.safetensors$/i.test(f))||files.find(f=>/sam3.*\.safetensors$/i.test(f));
    if(!file||!info.SAM3_Detect||!info.SAM3_VideoTrack)throw Error('Install the native SAM3 checkpoint to use text and point selection. You can still paint a mask manually.');
    graph.mask_model={class_type:'CheckpointLoaderSimple',inputs:{ckpt_name:file},_meta:{title:'Loading subject selection'}};
    inputs.model=['mask_model',0];
    if(text&&!selection.positive?.length&&!selection.hasMask){
      graph.mask_text={class_type:'CLIPTextEncode',inputs:{clip:['mask_model',1],text},_meta:{title:'Finding the selected subject'}};
      inputs.conditioning=['mask_text',0];
    }
  }
  graph.mask_pass={class_type:'ZuraPaintoutMaskPass',inputs,_meta:{title:operation==='absent'?'Marking the subject absent':'Preparing the removal mask'}};
  return graph;
}

export class PaintoutEditor{
  constructor(workspace){
    this.w=workspace;this.stage='mask';this.active=false;this.project=null;this.revision=-1;this.document=null;
    this.sequence=0;this.saveSequence=0;this.previewSequence=0;this.closed=false;this.toolJob=workspace.state.editorJob||null;this.selectionDirty=false;this.candidate=null;
    const link=document.createElement('link');link.rel='stylesheet';link.href=new URL('./paintout_editor.css',import.meta.url).href;workspace.page.append(link);
    this.nav=el('nav');this.nav.className='zp-editor-stages';this.nav.setAttribute('aria-label','Paintout process');
    for(const [key,title] of [['mask','Mask'],['clean','Clean frames'],['render','Render']]){
      const b=el('button',title);b.type='button';b.onclick=()=>this.setStage(key);b.dataset.stage=key;this.nav.append(b);
    }
    this.guide=el('span');this.guide.className='zp-editor-guide';this.nav.append(this.guide);
    workspace.page.querySelector('.zf-heading').after(this.nav);
    this.projects=el('details');this.projects.className='zp-editor-projects';this.projects.innerHTML='<summary>Projects</summary><div role="group" aria-label="Saved Paintout projects"></div>';workspace.page.querySelector('.zf-heading').append(this.projects);
    this.projects.ontoggle=async()=>{if(!this.projects.open)return;if(workspace.busy()){this.projects.open=false;return;}const list=this.projects.querySelector('div');list.textContent='Loading projects…';try{const projects=await workspace.fetch(endpoint+'/projects');list.replaceChildren();for(const project of projects){const button=el('button',project.name+(project.frames?` · ${project.frames} frames`:''));button.type='button';button.title=project.source+' · '+new Date(project.updated*1000).toLocaleString();button.onclick=()=>this.openProject(project.id);list.append(button);}if(!projects.length)list.textContent='Add footage to start your first project.';}catch(e){list.textContent=e.message;}};
    this.viewerHost=el('div');this.viewerHost.className='zp-editor-viewer-host';this.viewerHost.hidden=true;
    workspace.page.querySelector('.zf-viewer').append(this.viewerHost);
    this.viewer=new PaintoutMaskViewer(this.viewerHost,{onCommit:()=>{if(this.stage==='mask')this.flushManual().catch(e=>this.status(e.message));else this.saveCleanMask();},onChange:change=>{if(this.stage==='mask'&&change.kind==='paint'){const segment=this.maskSegment();if(segment&&segment.frame===this.viewer.frame){segment.pendingMask=this.viewer.getSelection().mask;segment.ready=false;this.w.save();}else{this.manualDirty=true;this.manualVersion=(this.manualVersion||0)+1;}}this.previewSequence++;this.selectionDirty=true;this.candidate=null;this.viewer.setOpacity(Number(this.$('opacity').value)/100);this.updateControls();}});
    this.timelineHost=el('div');this.timelineHost.className='zp-editor-timeline-host';workspace.page.querySelector('.zf-viewer').after(this.timelineHost);
    this.timeline=new PaintoutTimeline(this.timelineHost,{onTrim:(start,end,commit)=>{workspace.state.startFrame=start;workspace.state.frameCount=end-start+1;workspace.$('start').value=start;workspace.$('count').value=end-start+1;if(!this.customRange){this.$('range-start').value=start;this.$('range-end').value=end;}if(commit)workspace.save();workspace.render();},onSeek:f=>workspace.seek(f),onCreate:f=>this.createFrame(f),onSelect:i=>this.selectFrame(i),onRemove:i=>this.removeFrame(i),onMaskSelect:async f=>{if(workspace.busy())return;await this.setStage('mask');workspace.seek(f);}});
    this.tools=el('section');this.tools.className='zp-editor-tools';this.tools.setAttribute('aria-label','Paintout editing tools');this.timelineHost.after(this.tools);
    this.tools.innerHTML=`<div class="zp-editor-mask-intro"><strong>1. Select what to remove</strong><span>Click the subject, describe it, or paint the mask yourself. Red is the area to remove.</span><button type="button" data-editor="import-mask">Import mask video</button><span>Custom mask: white removes · black keeps. Match the plate’s size, frame rate and length.</span></div>
      <div class="zp-editor-tool-row"><div class="zp-editor-tool-group" role="group" aria-label="Mask tools"><button type="button" data-tool="include" title="Click on the subject to include it">${maskIcons['circle-plus']}<span>Select subject</span></button><button type="button" data-tool="exclude" title="Click on unwanted areas to exclude them">${maskIcons['circle-minus']}<span>Exclude area</span></button><button type="button" data-tool="brush" title="Draw the removal mask manually">${maskIcons.paintbrush}<span>Paint mask</span></button><button type="button" data-tool="protect" title="Erase from the removal mask">${maskIcons.eraser}<span>Erase mask</span></button><button type="button" data-tool="pan" title="Drag to move the view. Scroll to zoom.">${maskIcons.hand}<span>Pan</span></button></div><button type="button" data-editor="undo">${maskIcons['undo-2']}<span>Undo</span></button><button type="button" data-editor="clear">Clear selection</button></div>
      <div class="zp-editor-tool-row"><label class="zp-editor-description">Or describe the subject<input data-editor="subject" placeholder="e.g. the person in the red coat" /></label><button type="button" data-editor="selection">Preview mask on this frame</button></div>
      <p class="zp-editor-tool-help" data-editor="tool-help"></p>
      <div class="zp-editor-tool-row"><label data-editor="brush-control">Brush size <output data-editor="brush-value">32 px</output><input data-editor="brush" type="range" min="1" max="200" value="32" /></label><label title="Expand the hard removal boundary in original plate pixels">Expand mask <output data-editor="grow-value">0 px</output><input data-editor="grow" type="range" min="0" max="100" value="0" /></label><label title="Only changes how the red overlay is displayed, not the mask">Red overlay<input data-editor="opacity" type="range" min="0" max="100" value="45" /></label></div>
      <div class="zp-editor-mask-actions"><div class="zp-editor-track-guide"><strong>2. Track and build your mask</strong><span data-editor="track-help">Preview your selection, then track. If tracking loses the subject, start a new segment where it is visible again.</span></div>
        <div class="zp-editor-segment-actions" role="group" aria-label="Add or repair tracking"><button type="button" data-editor="repair-segment">Repair tracking from here</button><button type="button" data-editor="add-segment">Add another mask</button></div>
        <div class="zp-editor-segment-draft" data-editor="segment-draft" hidden><strong data-editor="segment-label"></strong><span data-editor="segment-help"></span><button type="button" data-editor="segment-seed">Go to selection frame</button><button type="button" data-editor="segment-cancel">Close segment editor</button></div>
        <div class="zp-editor-track-range"><label>From frame<input data-editor="range-start" type="number" min="0" step="1" /></label><button type="button" data-editor="range-in" title="Set the segment start to the playhead">Set In here</button><label>To frame<input data-editor="range-end" type="number" min="0" step="1" /></label><button type="button" data-editor="range-out" title="Set the segment end to the playhead">Set Out here</button><label>Direction<select data-editor="direction"><option value="both">Both ways from selection</option><option value="forward">Forward from selection</option><option value="backward">Backward from selection</option></select></label><label>Combine with saved mask<select data-editor="operation"><option value="replace">Replace this range</option><option value="add">Add to existing masks</option><option value="protect">Protect this region</option></select></label></div>
        <button type="button" class="zp-editor-primary" data-editor="track">Track mask through shot</button><button type="button" data-editor="continue">Next: clean frames</button>
        <details class="zp-editor-segments"><summary data-editor="segments-label">Tracking segments</summary><ol data-editor="segments"></ol></details>
        <details><summary>Absence / mask history</summary><div class="zp-editor-tool-row"><button type="button" data-editor="absent">Subject absent in section</button><button type="button" data-editor="previous-mask">Previous mask pass</button><button type="button" data-editor="next-mask">Next mask pass</button></div></details></div>
      <div class="zp-editor-clean-actions" hidden><strong data-editor="frame-label">Add a clean frame on the timeline</strong><label class="zp-editor-description">Cleanup instruction<input data-editor="instruction" value="Remove the selected object and reconstruct the background." /></label><button type="button" class="zp-editor-primary" data-editor="clean">Clean with FLUX 3</button><button type="button" data-editor="download">Download original</button><button type="button" data-editor="reference" hidden>Download frame reference</button><button type="button" data-editor="import">Import edited frame</button><label data-editor="version-control" hidden>Saved version<select data-editor="version" aria-label="Saved clean-frame version"></select></label><button type="button" data-editor="accept" hidden>Use clean frame</button><button type="button" data-editor="reject" hidden>Discard result (X)</button></div>
      <p data-editor="status" role="status" aria-live="polite"></p><div data-editor="job" hidden><progress aria-label="Frame editing progress"></progress><span data-editor="job-label">Queued</span><button type="button" data-editor="cancel">Cancel this run</button></div>`;
    this.subjectChoices=el('section');this.subjectChoices.className='zp-editor-subject-choices';this.subjectChoices.hidden=true;this.subjectChoices.setAttribute('aria-label','Choose the subject to remove');this.tools.querySelector('.zp-editor-mask-intro').after(this.subjectChoices);
    this.$('import-mask').onclick=()=>workspace.pickMask();
    this.maskSummary=el('div');this.maskSummary.className='zp-editor-mask-summary';this.maskSummary.innerHTML='<span></span><button type="button">Review mask</button>';this.maskSummary.querySelector('button').onclick=()=>this.setStage('mask');workspace.$('mask-control')?.after(this.maskSummary);
    this.$('subject').value=workspace.state.maskSubject||'';
    workspace.state.maskFeather=0;this.$('grow').value=workspace.state.maskGrow??0;this.$('grow').oninput=()=>this.morph(false);this.$('grow').onchange=()=>this.morph(true);
    for(const b of this.tools.querySelectorAll('[data-tool]'))b.onclick=()=>{this.viewer.setTool(b.dataset.tool);this.tool=b.dataset.tool;this.updateControls();};
    this.tool='include';this.viewer.setTool(this.tool);this.$('brush').oninput=()=>{this.viewer.setBrushSize(Number(this.$('brush').value));this.$('brush-value').textContent=this.$('brush').value+' px';};this.viewer.setBrushSize(32);
    this.$('opacity').oninput=()=>this.viewer.setOpacity(Number(this.$('opacity').value)/100);
    this.$('undo').onclick=()=>{this.viewer.undo();if(this.stage==='clean')this.saveCleanMask();if(this.stage==='mask'&&this.manualDirty)this.flushManual().catch(e=>this.status(e.message));};this.$('clear').onclick=()=>{this.viewer.clear();if(this.stage==='clean')this.saveCleanMask();if(this.stage==='mask'&&this.maskSegment()){const segment=this.maskSegment();segment.pendingMask=this.viewer.getSelection().mask;segment.ready=false;this.w.save();}else if(this.stage==='mask'){this.manualDirty=true;this.manualVersion=(this.manualVersion||0)+1;this.flushManual().catch(e=>this.status(e.message));}this.selectionDirty=true;this.candidate=null;this.updateControls();};
    this.$('subject').oninput=()=>{workspace.state.maskSubject=this.$('subject').value;this.subjectChanged=true;this.viewer.setSelection({});this.status('Preview the new subject selection before tracking. The overlay still shows your saved mask.');workspace.save();};
    this.$('continue').onclick=()=>this.setStage('clean');this.$('selection').onclick=()=>this.manualDirty?this.flushManual().catch(e=>this.status(e.message)):this.runMask(true);this.$('track').onclick=()=>this.runMask(false);this.$('absent').onclick=()=>this.runMask(false,'absent');
    for(const field of ['range-start','range-end','direction','operation'])this.$(field).onchange=()=>{this.customRange=true;this.saveSegmentRange();this.updateControls();};
    this.$('repair-segment').onclick=()=>this.beginMaskSegment('replace').catch(error=>this.status(error.message));
    this.$('add-segment').onclick=()=>this.beginMaskSegment('add').catch(error=>this.status(error.message));
    this.$('segment-cancel').onclick=()=>this.finishMaskSegment().catch(error=>this.status(error.message));
    this.$('segment-seed').onclick=()=>{const segment=this.maskSegment();if(segment)this.w.seek(segment.frame);};
    for(const [key,field]of [['range-in','range-start'],['range-out','range-end']])this.$(key).onclick=()=>{this.$(field).value=this.w.playhead;this.customRange=true;this.saveSegmentRange();this.updateControls();};
    this.$('previous-mask').onclick=()=>this.selectMask(-1);this.$('next-mask').onclick=()=>this.selectMask(1);
    this.maskReview=el('div');this.maskReview.className='zp-editor-mask-review';this.maskReview.hidden=true;this.maskReview.innerHTML='<span data-editor="review-count"></span><button type="button" data-editor="review-next">Review next change</button><small data-editor="review-reason"></small>';this.tools.querySelector('.zp-editor-mask-actions').append(this.maskReview);this.$('review-next').onclick=()=>this.nextMaskReview().catch(error=>this.status(error.message));
    this.$('instruction').oninput=()=>{const anchor=this.selected();if(anchor){anchor.editPrompt=this.$('instruction').value;this.w.save();}};this.$('clean').onclick=()=>this.cleanFrame();this.$('accept').onclick=()=>this.acceptFrame();this.$('reject').onclick=()=>this.discardFrame();
    this.$('version').onchange=()=>this.selectVersion(this.$('version').value);
    this.$('reference').onclick=()=>{const a=this.selected();if(!a?.exportReference)return;const blob=new Blob([JSON.stringify(a.exportReference,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=el('a');link.href=url;link.download=`${this.project}_frame_${String(a.frame).padStart(6,'0')}.reference.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};this.$('download').onclick=()=>this.downloadFrame();this.$('import').onclick=()=>this.importFrame();this.$('cancel').onclick=()=>this.cancel();
    this.importReview=el('section');this.importReview.className='zp-editor-import-review';this.importReview.hidden=true;
    this.importReview.innerHTML='<strong>Review imported edit</strong><p data-editor="import-differences"></p><div><button type="button" data-editor="import-current">Keep current repair area</button><button type="button" class="zp-editor-primary" data-editor="import-include">Include highlighted edits</button></div><small>This changes this clean guide only. Your video removal mask stays as set in Mask.</small>';
    this.tools.append(this.importReview);this.$('import-current').onclick=()=>this.acceptImported('current');this.$('import-include').onclick=()=>this.acceptImported('include');
    const compare=el('button','Show original');compare.type='button';compare.dataset.editor='compare';this.tools.querySelector('.zp-editor-clean-actions').append(compare);
    compare.onclick=()=>this.compareFrame();
    this.discardShortcut=event=>{if(event.key.toLowerCase()!=='x'||event.ctrlKey||event.metaKey||event.altKey||event.repeat||event.target.closest?.('input,textarea,select,[contenteditable=true]'))return;if(!workspace.page.isConnected||workspace.page.closest('[hidden]')||this.stage!=='clean'||!this.candidate||workspace.busy())return;event.preventDefault();this.discardFrame();};
    document.addEventListener('keydown',this.discardShortcut);

    this.viewerHost.ondragover=e=>{e.preventDefault();};this.viewerHost.ondrop=e=>{e.preventDefault();const file=e.dataTransfer?.files?.[0];if(file)this.importDropped(file);};
    workspace.api.addEventListener?.('executing',event=>{const detail=event.detail;if(detail?.prompt_id!==this.toolJob?.id||!detail.node)return;this.$('job-label').textContent=this.toolJob.stages[detail.node]||'Processing';this.$('job').querySelector('progress').removeAttribute('value');});
    workspace.api.addEventListener?.('progress',event=>{const detail=event.detail;if(detail?.prompt_id!==this.toolJob?.id||!Number.isFinite(detail.value)||!Number.isFinite(detail.max)||detail.max<=0)return;const bar=this.$('job').querySelector('progress');bar.max=detail.max;bar.value=detail.value;this.$('job-label').textContent=`${this.toolJob.stages[detail.node]||'Processing'} · ${detail.value} of ${detail.max}`;});
    this.morph(false);this.update();
  }
  $(key){return this.tools.querySelector(`[data-editor="${key}"]`);}
  status(message){this.$('status').textContent=message||'';}
  busy(){return !!(this.frameLoading||this.toolJob||this.submitting||this.loadingProject||this.openingProject||this.importing);}
  selected(){return this.w.state.anchors[this.w.selected];}
  maskSegment(){const segment=this.w.state.maskSegmentDraft;return segment?.source===this.w.state.source?segment:null;}
  saveSegmentRange(){const segment=this.maskSegment();if(segment){segment.start=Number(this.$('range-start').value);segment.end=Number(this.$('range-end').value);segment.direction=this.$('direction').value;segment.operation=this.$('operation').value;this.w.save();}}
  async beginMaskSegment(operation){
    if(this.w.busy()||!this.w.state.source)return;
    await this.flushManual();await this.setStage('mask');await this.ensureProject();
    const w=this.w,frame=w.playhead,trimEnd=w.state.startFrame+w.state.frameCount-1;
    let end=trimEnd;
    if(operation==='replace')for(const pass of this.document?.mask_history||[]){if(pass.revision>this.w.state.maskRevision)continue;const seed=pass.metadata?.frame;if(Number.isInteger(seed)&&seed>frame)end=Math.min(end,seed-1);}
    w.state.maskSegmentDraft={source:w.state.source,frame,start:frame,end,operation,direction:'forward',ready:false};
    this.customRange=true;this.$('range-start').value=frame;this.$('range-end').value=end;this.$('operation').value=operation;this.$('direction').value='forward';
    this.maskChoices=null;this.subjectChoices.hidden=true;this.previewSequence++;this.subjectChanged=false;this.selectionDirty=true;this.viewer.setSelection({});await this.viewer.setMask(null);this.viewer.setOpacity(Number(this.$('opacity').value)/100);this.tool='include';this.viewer.setTool('include');
    this.status(operation==='add'?'Select or paint the additional subject, then preview this segment. Existing masks are kept.':'Select or paint the subject again, then preview. Only the chosen range will be replaced; earlier frames are kept.');this.updateControls();w.save();
  }
  async finishMaskSegment(){
    if(this.w.busy())return;
    this.w.state.maskSegmentDraft=null;this.maskChoices=null;this.subjectChoices.hidden=true;this.selectionDirty=false;this.subjectChanged=false;this.customRange=false;this.previewSequence++;
    this.$('operation').value='replace';this.$('direction').value='both';this.$('range-start').value=this.w.state.startFrame;this.$('range-end').value=this.w.state.startFrame+this.w.state.frameCount-1;
    this.frameKey=null;await this.frameChanged(true);this.w.save();this.updateControls();this.status('Showing the saved shot mask. Accepted segment previews and tracking are kept.');
  }
  async acceptSegmentSeed(mask={}){
    const segment=this.maskSegment();if(!segment)return;
    const seed=this.document?.mask_seed;
    const url=mask.seed_frame===segment.frame?mask.seed_url:seed?.frame===segment.frame&&seed.mask_revision===this.w.state.maskRevision?seed.url:null;
    if(!url)throw Error('This server needs the updated Paintout backend to keep additional mask seeds separate. Restart ComfyUI with the new package.');
    await this.viewer.setMask(this.w.url(url));
    segment.seedMask=this.viewer.getSelection().mask;segment.pendingMask=null;segment.ready=true;segment.maskRevision=this.w.state.maskRevision;this.selectionDirty=false;this.w.save();
  }
  updateMaskSegments(){
    const passes=(this.document?.mask_history||[]).filter(pass=>pass.revision<=this.w.state.maskRevision&&pass.end_frame>pass.start_frame);
    this.$('segments-label').textContent=`Tracking segments (${passes.length})`;
    const list=this.$('segments');list.replaceChildren();
    if(!passes.length){list.append(el('li','No tracked segments yet. Select a subject and track, or add another mask.'));return;}
    for(const pass of passes){const row=el('li'),button=el('button',`Frames ${pass.start_frame}–${pass.end_frame} · ${pass.operation==='add'?'Added mask':pass.operation==='absent'?'Subject absent':pass.operation==='protect'?'Protected region':'Tracked repair'}`);button.type='button';button.disabled=this.w.busy();button.onclick=()=>this.w.seek(pass.metadata?.frame??pass.start_frame);row.append(button);list.append(row);}
  }
  maskReviewRanges(){
    const state=this.w.state,document=this.document;
    if(!document||document.id!==state.maskProject||document.mask_revision!==state.maskRevision)return [];
    const start=state.startFrame,end=start+state.frameCount-1,seen=new Set();
    return (document.mask_review_ranges||[]).filter(range=>Number.isInteger(range.start_frame)&&Number.isInteger(range.end_frame)&&range.end_frame>=range.start_frame).map(range=>({...range,start_frame:Math.max(start,range.start_frame),end_frame:Math.min(end,range.end_frame),status:'needs_review'})).filter(range=>{const key=[range.start_frame,range.end_frame,range.reason].join('|');if(range.start_frame>range.end_frame||seen.has(key))return false;seen.add(key);return true;}).sort((a,b)=>a.start_frame-b.start_frame||a.end_frame-b.end_frame);
  }
  async nextMaskReview(){
    const w=this.w;if(this.stage!=='mask'||w.busy()||this.manualSaving)return;
    await this.flushManual();const ranges=this.maskReviewRanges();if(!ranges.length)return;
    const next=ranges.find(range=>range.start_frame>w.playhead)||ranges[0];
    w.playhead=next.start_frame;w.updatePlayhead();await this.frameChanged(true);this.updateControls();
    this.status(`${next.label||'Mask changed'} at source frame ${next.start_frame}. Advisory only: inspect the mask and paint or erase if needed.`);
  }

  frameVersions(anchor=this.selected()){
    if(!anchor)return [];
    const versions=(anchor.versions||[]).filter((v,i,list)=>v.file&&list.findIndex(other=>other.file===v.file)===i).map(v=>({...v}));
    if(anchor.file&&!versions.some(v=>v.file===anchor.file))versions.push({file:anchor.file,preview_file:anchor.preview_file,colour_space:anchor.colour_space});
    return versions;
  }
  async selectVersion(file){
    if(this.w.busy()||this.candidate||this.stage!=='clean')return;
    const anchor=this.selected(),versions=this.frameVersions(anchor),version=versions.find(v=>v.file===file);
    if(!anchor||anchor.frame!==this.w.playhead||!version||anchor.file===file)return;
    anchor.versions=versions;
    Object.assign(anchor,{file:version.file,preview_file:version.preview_file||version.png_file||'',colour_space:version.colour_space||anchor.colour_space,status:'accepted'});
    this.showOriginal=false;this.frameKey=null;this.w.syncAnchorControls?.(this.w.selected);this.w.changed();
    await this.frameChanged(true);this.status('Using saved version '+(versions.indexOf(version)+1)+' for source frame '+anchor.frame+'. Other versions are kept.');
  }
  showMaskChoices(result){
    this.maskChoices={...result,source:this.w.state.source};this.subjectChoices.replaceChildren(el('strong','Several subjects matched. Choose the one to remove.'));
    const list=el('div');list.className='zp-editor-subject-choices__list';
    for(const choice of result.choices){const button=el('button');button.type='button';button.setAttribute('aria-label','Choose subject '+(choice.index+1));const preview=el('span');preview.className='zp-editor-subject-choices__preview';const plate=el('img');plate.alt='';plate.src=this.w.thumbnail(this.w.state.source,result.frame,this.w.state.sourceColour,320);preview.append(plate);const overlay=el('span');overlay.style.maskImage=`url("${this.w.url(choice.url)}")`;preview.append(overlay);button.append(preview,el('span','Subject '+(choice.index+1)));button.onclick=()=>this.chooseMaskSubject(choice.index);list.append(button);}
    const cancel=el('button','Cancel selection');cancel.type='button';cancel.onclick=()=>{this.maskChoices=null;this.subjectChoices.hidden=true;this.updateControls();this.status('Selection cancelled. Your saved mask is unchanged.');};list.append(cancel);this.subjectChoices.append(list);this.updateControls();
  }
  async chooseMaskSubject(index){
    const selection=this.maskChoices,w=this.w;
    if(w.busy()||!selection)return;
    if(this.saving){this.status('Project is saving. Choose the subject again in a moment.');return;}
    if(selection.source!==w.state.source||selection.project!==this.project||selection.frame!==w.playhead){this.status('Return to the detected source frame or preview the selection again.');return;}
    this.submitting=true;clearTimeout(this.saveTimer);w.render();
    try{const document=await w.fetch(endpoint+'/select-mask-candidate',{project:this.project,token:selection.token,index,source:w.state.source,frame:w.playhead,expected_revision:this.revision});
      this.document=document;this.revision=document.revision;w.state.maskProject=document.id;w.state.maskRevision=document.mask_revision;w.state.maskCoverage=document.mask_coverage;this.maskChoices=null;this.subjectChoices.hidden=true;this.subjectChanged=false;this.selectionDirty=false;this.viewer.setSelection({});await this.acceptSegmentSeed();this.frameKey=null;this.status('Subject selected on this frame. Check the red mask, then track it through the shot.');
    }catch(error){this.status(error.message);}finally{this.submitting=false;w.render();await this.frameChanged(true);w.save();}
  }
  projectData(){return {draft:JSON.parse(JSON.stringify({...this.w.state,editorStage:this.stage,editorPlayhead:this.w.playhead,editorSelected:this.w.selected})),prompts:{...this.w.prompts},renderJob:this.w.job||null,result:this.w.result?.config?.source===this.w.state.source?this.w.result:null};}
  hydrateControls(){
    const w=this.w;
    for(const [field,key]of Object.entries({start:'startFrame',count:'frameCount',fps:'sequenceFps',colour:'sourceColour',processing:'processingSpace',width:'width',height:'height',output:'outputMode',seed:'seed'})){const input=w.$(field);if(input)input.value=w.state[key];}
    if(w.$('prompt'))w.$('prompt').value=w.prompts[w.state.mode]||'';
    this.$('subject').value=w.state.maskSubject||'';this.$('grow').value=w.state.maskGrow??0;w.state.maskFeather=0;
    this.$('instruction').value=this.selected()?.editPrompt||'Remove the selected object and reconstruct the background.';this.$('range-start').value=w.state.startFrame;this.$('range-end').value=w.state.startFrame+w.state.frameCount-1;
    const segment=this.maskSegment();if(segment){this.customRange=true;this.$('range-start').value=segment.start;this.$('range-end').value=segment.end;this.$('operation').value=segment.operation;this.$('direction').value=segment.direction;}
    w.syncAnchorControls?.(w.selected);w.updatePlayhead();
  }
  async openProject(id){
    if(this.w.busy()||this.saving)return;
    try{
      await this.flushManual();if(this.w.state.source)await this.persist();this.openingProject=true;this.w.render();
      const doc=await this.w.fetch(endpoint+'/project',{id}),draft=doc.data?.draft;
      if(!draft?.source)throw Error('This project has no footage.');
      const [sourceInfo,maskInfo]=await Promise.all([this.w.info(draft.source),draft.mask?this.w.info(draft.mask):null]),w=this.w;
      w.state=paintoutDraft({...draft,editorProject:doc.id,maskProject:doc.mask_revision==null?null:doc.id,maskRevision:doc.mask_revision,maskCoverage:doc.mask_coverage});
      w.sourceInfo=sourceInfo;w.maskInfo=maskInfo;w.prompts={...doc.data.prompts};w.job=doc.data.renderJob?.config?.source===draft.source?doc.data.renderJob:null;w.result=doc.data.result?.config?.source===draft.source?doc.data.result:null;
      w.selected=Number.isInteger(draft.editorSelected)&&w.state.anchors[draft.editorSelected]?draft.editorSelected:-1;w.playhead=number(draft.editorPlayhead??draft.startFrame??0,0,sourceInfo.frames-1);
      this.source=draft.source;this.projectSource=draft.source;this.project=doc.id;this.document=doc;this.revision=doc.revision;this.frameKey=null;this.subjectChanged=false;this.customRange=false;this.selectionDirty=false;this.showOriginal=false;
      this.projects.open=false;this.toolJob=w.state.editorJob?.source===draft.source?w.state.editorJob:null;
      this.stage=w.state.mode==='full'||w.result?'render':['mask','clean','render'].includes(draft.editorStage)?draft.editorStage:'mask';this.active=this.stage!=='render';this.candidate=this.stage==='clean'?this.selected()?.candidate||null:null;
      this.hydrateControls();w.view=this.stage==='clean'?'anchor':'mask';w.renderAnchors();w.render();if(this.active)await this.frameChanged(true);else w.preview(w.result?'result':'source');if(this.toolJob)this.startPolling();if(w.job)w.startPolling();w.save();
    }catch(e){this.status(e.message);}finally{this.openingProject=false;this.w.render();}
  }
  async ensureProject(){
    if(this.loadingProject)return this.projectPromise;
    const source=this.w.state.source;if(!source)throw Error('Add footage first.');
    if(this.project&&this.projectSource===source)return;
    this.loadingProject=true;
    this.projectPromise=(async()=>{
      const id=this.w.state.editorProject;
      const doc=await this.w.fetch(endpoint+'/project',id?{id}:{data:this.projectData()});
      if(this.w.state.source!==source)return;
      const saved=doc.data?.draft,local=this.w.state;
      // Disk can recover a newer saved draft, while newer browser edits remain authoritative.
      if(saved?.source===source&&((Number(saved.editorUpdatedAt)||0)>(Number(local.editorUpdatedAt)||0)||(!local.editorUpdatedAt&&!local.anchors.length&&saved.anchors?.length))){
        Object.assign(local,saved);local.maskFeather=0;local.anchors=Array.isArray(local.anchors)?local.anchors:[];
        this.w.prompts={...doc.data?.prompts};
        this.w.selected=Number.isInteger(local.editorSelected)&&local.anchors[local.editorSelected]?local.editorSelected:-1;
        this.w.playhead=number(local.editorPlayhead??local.startFrame??0,0,(this.w.sourceInfo?.frames||1)-1);
        this.w.job=doc.data?.renderJob?.config?.source===source?doc.data.renderJob:null;
        this.w.result=doc.data?.result?.config?.source===source?doc.data.result:null;
        this.hydrateControls();this.w.renderAnchors?.();
      }
      this.project=doc.id;this.projectSource=source;this.revision=doc.revision;this.document=doc;const segment=this.maskSegment();if(segment){this.customRange=true;this.$('range-start').value=segment.start;this.$('range-end').value=segment.end;this.$('operation').value=segment.operation;this.$('direction').value=segment.direction;}
      this.w.state.editorProject=doc.id;
      if(doc.mask_revision!=null){this.w.state.maskProject=doc.id;this.w.state.maskRevision=doc.mask_revision;this.w.state.maskCoverage=doc.mask_coverage;}
    })();
    try{await this.projectPromise;}finally{this.loadingProject=false;}
  }
  saveSoon(){
    if(this.closed||!this.w.state.source)return;this.w.state.editorUpdatedAt=Date.now();this.w.state.editorSelected=this.w.selected;clearTimeout(this.saveTimer);
    this.saveTimer=setTimeout(()=>this.persist().catch(e=>this.status('Project was not saved: '+e.message)),500);
  }
  async persist(){
    if(!this.w.state.source||this.w.picking||this.toolJob||this.submitting||this.loadingProject||this.openingProject||this.importing||this.manualDirty||this.manualSaving)return;await this.ensureProject();
    if(this.saving){this.saveAgain=true;return;}this.saving=true;
    const project=this.project,source=this.projectSource;
    try{const doc=await this.w.fetch(endpoint+'/project',{id:project,data:this.projectData(),expected_revision:this.revision});if(this.project===project&&this.projectSource===source){this.document=doc;this.revision=doc.revision;}}
    finally{this.saving=false;if(this.saveAgain){this.saveAgain=false;this.saveSoon();}}
  }
  async loadDocument(){const doc=await this.w.fetch(endpoint+'/project',{id:this.project});this.document=doc;this.revision=doc.revision;this.w.state.maskCoverage=doc.mask_coverage;return doc;}
  async setStage(stage){
    if(this.w.busy()||!['mask','clean','render'].includes(stage))return;try{await this.flushManual();}catch(e){this.status(e.message);return;}this.closed=false;this.stage=stage;this.w.state.editorStage=stage;if(stage==='clean')this.$('instruction').value=this.selected()?.editPrompt||'Remove the selected object and reconstruct the background.';this.active=stage!=='render'&&!!this.w.state.source;this.candidate=stage==='clean'?this.selected()?.candidate||null:null;
    if(stage==='clean'&&!this.selected()&&this.w.state.source)this.createFrame(this.w.playhead);
    if(this.active){this.w.view=stage==='clean'?'anchor':'mask';this.w.comparison?.hide();if(this.w.$('comparison'))this.w.$('comparison').hidden=true;this.w.$('video').pause();this.w.$('video').hidden=true;this.w.$('image-slot').hidden=true;await this.frameChanged(true);}
    else this.w.preview(this.w.result?'result':'source');
    this.update();this.w.save();
  }
  async frameChanged(force=false){
    if(!this.active||!this.w.sourceInfo)return;const w=this.w;
    const accepted=this.stage==='clean'&&this.selected()?.frame===w.playhead?this.selected():null;
    const key=[w.state.source,w.playhead,w.state.maskRevision,w.state.mask,w.state.sourceColour,this.candidate?.file,accepted?.file,this.stage].join('|');
    if(!force&&key===this.frameKey&&!this.manualDirty&&!this.manualSaving)return;const seq=++this.sequence;this.frameLoading=true;this.updateControls();
    try{await this.flushManual();if(seq!==this.sequence)return;this.frameKey=key;
      const candidate=accepted?this.candidate:null,info=w.sourceInfo,url=candidate?.file?w.thumbnail(candidate.png_file||candidate.file,0,candidate.colour_space,1280):accepted?.file?w.thumbnail(accepted.preview_file||accepted.file,0,accepted.colour_space,1280):w.thumbnail(w.state.source,w.playhead,w.state.sourceColour,1280);
      this.showOriginal=false;
      await this.viewer.setFrame(url,info.width,info.height,w.playhead);if(seq!==this.sequence)return;
      this.selectionDirty=false;
      if(candidate?.review){await this.viewer.setMask(w.url(candidate.review.difference_url));}
      else if(this.stage==='clean'&&accepted?.editMask){await this.viewer.setMask(accepted.editMask);}
      else if(this.stage==='mask'&&this.maskSegment()?.frame===w.playhead){const segment=this.maskSegment();await this.viewer.setMask(segment.pendingMask||segment.seedMask||null);}
      else if(w.state.maskProject&&w.state.maskRevision!=null){await this.viewer.setMask(w.url(endpoint+'/mask-preview?'+new URLSearchParams({project:w.state.maskProject,revision:w.state.maskRevision,frame:w.playhead,grow:0,feather:0})));}
      else if(w.state.mask){await this.viewer.setMask(w.thumbnail(w.state.mask,w.playhead,'srgb_display',1280));}
      else await this.viewer.setMask(null);
      if(seq!==this.sequence)return;this.selectionDirty=!!(this.stage==='mask'&&this.maskSegment()?.frame===w.playhead&&this.maskSegment().pendingMask);this.$('grow').value=this.stage==='clean'?(accepted?.editGrow??w.state.maskGrow??0):(w.state.maskGrow??0);this.$('grow-value').textContent=this.$('grow').value+' px';this.viewer.setGrow(candidate?.review?0:Number(this.$('grow').value),0);this.viewer.setOpacity(candidate&&!candidate.review?0:Number(this.$('opacity').value)/100);this.updateControls();this.authoritativePreview().catch(e=>{if(seq===this.sequence)this.status(e.message);});
    }catch(e){if(seq===this.sequence){this.frameKey=null;if(this.manualDirty){w.playhead=this.viewer.frame;w.updatePlayhead();}this.status(e.message);}}finally{if(seq===this.sequence){this.frameLoading=false;this.w.render();}}
  }
  update(){
    const w=this.w,has=!!w.state.source;
    w.page.classList.toggle('zp-editor-open',has&&w.state.mode!=='full');w.page.dataset.editorStage=this.stage;
    this.guide.textContent=this.stage==='mask'?'Select → preview → track → review.':this.stage==='clean'?'Click the timeline to add clean frames that guide the repair.':'Review your shot settings and generate the paintout.';
    this.timelineHost.hidden=!has||w.state.mode==='full';this.tools.hidden=!has||this.stage==='render'||w.state.mode==='full';this.nav.hidden=!has||w.state.mode==='full';
    this.viewerHost.hidden=!this.active||!has||w.state.mode==='full';
    if(this.active&&has&&w.state.mode!=='full'){w.$('video').hidden=true;w.$('image-slot').hidden=true;}
    w.$('anchors-section').hidden=true;
    for(const b of this.nav.querySelectorAll('button')){b.setAttribute('aria-current',b.dataset.stage===this.stage?'step':'false');b.disabled=this.busy();}
    this.timeline.update({sourceFrames:w.sourceInfo?.frames,startFrame:w.state.startFrame,frameCount:w.state.frameCount,fps:w.fps(),playhead:w.playhead,
      anchors:w.state.anchors,selected:w.selected,busy:w.busy(),thumbnail:a=>a.file?w.thumbnail(a.preview_file||a.file,0,a.colour_space):w.thumbnail(w.state.source,a.frame,w.state.sourceColour),maskRanges:[...(this.document?.mask_history||[]).filter(pass=>pass.revision<=w.state.maskRevision).map(pass=>({...pass,status:'tracked'})),...this.maskReviewRanges()]});
    if(has&&this.source!==w.state.source){this.source=w.state.source;this.frameKey=null;this.project=null;this.projectSource=null;this.revision=-1;
      this.customRange=false;this.$('range-start').value=w.state.startFrame;this.$('range-end').value=w.state.startFrame+w.state.frameCount-1;
      this.ensureProject().then(()=>{if(this.projectSource===w.state.source){if(w.state.mode!=='full'){this.stage=w.result?'render':w.state.editorStage||'mask';this.active=this.stage!=='render';this.candidate=this.stage==='clean'?this.selected()?.candidate||null:null;if(this.active){w.view=this.stage==='clean'?'anchor':'mask';this.frameChanged(true);}else w.preview(w.result?'result':'source');}this.update();}}).catch(e=>this.status(e.message));}
    this.updateControls();
  }
  updateControls(){
    const clean=this.stage==='clean',busy=this.w.busy();
    if(clean&&['include','exclude'].includes(this.tool)){this.tool='brush';this.viewer.setTool('brush');}
    const hasRemovalMask=!!(this.w.state.maskProject&&this.w.state.maskRevision!=null||this.w.state.mask),coverage=this.w.state.maskCoverage;
    const covered=Array.isArray(coverage)?new Set(coverage):null,needed=this.w.state.frameCount;
    const count=covered?Array.from({length:needed},(_,i)=>this.w.state.startFrame+i).filter(f=>covered.has(f)).length:needed;
    this.subjectChoices.hidden=clean||this.stage==='render'||!this.maskChoices||this.maskChoices.source!==this.w.state.source||this.maskChoices.frame!==this.w.playhead;
    for(const button of this.subjectChoices.querySelectorAll('button'))button.disabled=busy;
    this.maskSummary.hidden=this.stage!=='render'||this.w.state.mode==='full';
    this.maskSummary.querySelector('span').textContent=!hasRemovalMask?'Set up your removal mask in step 1 before rendering.':count<needed?`Mask from step 1 covers ${count} of ${needed} frames. Finish tracking before rendering.`:'Removal mask from step 1 is ready and will be used automatically.';
    this.maskSummary.querySelector('button').disabled=busy;
    this.viewerHost.inert=busy||!!this.candidate;this.viewerHost.setAttribute('aria-busy',String(busy));if(busy)this.viewer.drag=null;
    for(const input of this.tools.querySelectorAll('input,select'))input.disabled=busy;
    for(const b of this.tools.querySelectorAll('button'))b.disabled=busy;
    this.tools.querySelector('.zp-editor-mask-actions').hidden=clean;this.tools.querySelector('.zp-editor-clean-actions').hidden=!clean;
    this.$('subject').closest('.zp-editor-tool-row').hidden=clean;
    this.tools.querySelector('.zp-editor-mask-intro').hidden=clean;
    this.$('brush-control').hidden=!['brush','protect'].includes(this.tool);
    const help={include:'Click inside the subject to add + points. Then preview the mask. Click a point again to remove it.',exclude:'Click outside the subject to add − points where the mask spills. Preview again to refine it.',brush:'Paint manually: drag over the area to remove. Changes save to this frame automatically. Scrub to any other frame to fix it too.',protect:'Erase manually: drag over red areas to keep them. Changes save to this frame automatically. Undo restores the last stroke.',pan:'Drag to pan. Scroll to zoom. Press 0 to fit the whole frame.'};
    this.$('tool-help').textContent=clean&&['brush','protect'].includes(this.tool)?(this.tool==='brush'?'Paint everything FLUX should remove, including shadows or small details. Only this clean frame’s mask changes.':'Erase any area FLUX must keep. Only this clean frame’s mask changes.'):help[this.tool];
    const selection=this.viewer.getSelection(false),hasSelection=selection.hasMask||selection.positive.length>0||!!this.$('subject').value.trim();
    this.$('selection').disabled=busy||(!hasSelection&&!this.manualDirty);
    this.$('selection').textContent=this.tool==='brush'||this.tool==='protect'?'Save mask on this frame':'Preview mask on this frame';
    this.$('track').disabled=busy||!selection.hasMask||this.subjectChanged||this.selectionDirty||!!this.manualSaving;
    const segment=this.maskSegment(),atSeed=segment?.frame===this.w.playhead;
    this.$('segment-draft').hidden=!segment;
    this.$('segment-label').textContent=segment?`${segment.operation==='add'?'Additional mask':'Repair segment'} · selection frame ${segment.frame}`:'';
    this.$('segment-help').textContent=segment?(segment.ready?'This segment has its own seed. Tracking changes only the range below.':'Select the subject again or paint a new mask, then preview. Your saved shot mask is kept.') :'';
    this.$('segment-seed').hidden=!segment||atSeed;
    this.$('track').textContent=segment?'Track this segment':this.customRange?'Track mask through section':'Track mask through shot';
    if(segment)this.$('track').disabled=busy||!atSeed||!segment.ready||this.selectionDirty||this.subjectChanged;
    this.updateMaskSegments();
    this.$('track-help').textContent=this.selectionDirty||this.subjectChanged?'Your selection changed. Preview or save this frame before tracking.':selection.hasMask?'Check the red mask, then track it. Scrub the timeline afterwards and fix any missed sections.':'Start by selecting or painting the subject above, then preview the mask.';
    if(this.maskChoices&&!this.subjectChoices.hidden){this.$('track').disabled=true;this.$('track-help').textContent='Choose a subject from the previews above before tracking.';}
    this.$('continue').disabled=busy||!(this.w.state.mask||this.w.state.maskRevision!=null);

    for(const b of this.tools.querySelectorAll('[data-tool=include],[data-tool=exclude]'))b.hidden=clean;
    for(const b of this.tools.querySelectorAll('[data-tool]'))b.setAttribute('aria-pressed',String(b.dataset.tool===this.tool));
    const a=this.selected();this.$('frame-label').textContent=a?`Clean frame ${a.frame} · ${a.frame<this.w.state.startFrame||a.frame>=this.w.state.startFrame+this.w.state.frameCount?'Outside trim. Extend the range to use this guide.':({needs_review:'Review result',needs_edit:'Ready to clean',accepted:'Accepted'})[a.status]||'Accepted'}`:'Add a clean frame on the timeline';
    const versions=this.frameVersions(a),versionSelect=this.$('version');this.$('version-control').hidden=!clean||versions.length<2;
    versionSelect.replaceChildren(...versions.map((version,index)=>{const option=el('option',`Version ${index+1} · ${version.method==='flux3'?'FLUX':version.method==='manual'?'Imported':'Saved'}`);option.value=version.file;return option;}));versionSelect.value=a?.file||'';versionSelect.disabled=busy||!!this.candidate||a?.frame!==this.w.playhead;versionSelect.title=this.candidate?'Use or discard the current result before choosing a saved version.':'Choose the clean image used to guide this frame.';
    const onFrame=a?.frame===this.w.playhead;this.$('reference').hidden=!clean||!onFrame||!a?.exportReference;
    this.$('compare').hidden=!clean||!onFrame||!(a?.file||this.candidate);this.$('compare').textContent=this.showOriginal?'Show clean frame':'Show original';
    this.$('reject').hidden=!this.candidate;this.$('accept').hidden=!this.candidate||!!this.candidate.review;
    if(clean&&this.candidate)this.$('grow').disabled=true;
    const review=this.candidate?.review;this.importReview.hidden=!clean||!onFrame||!review;this.$('import-differences').textContent=review?`${review.outside_pixels.toLocaleString()} changed pixels lie outside your repair area. Red highlights those changes. Keep the current bounds or include the intended edits.`:'';
    this.$('import-current').disabled=this.$('import-include').disabled=busy||!onFrame;
    if(review){for(const input of this.tools.querySelectorAll('input,select'))if(input!==this.$('opacity'))input.disabled=true;for(const b of this.tools.querySelectorAll('[data-tool],[data-editor=undo],[data-editor=clear]'))b.disabled=true;}
    this.$('clean').disabled=busy||!onFrame||!!this.candidate;this.$('download').disabled=busy||!onFrame;this.$('import').disabled=busy||!onFrame||!!this.candidate;this.$('accept').disabled=busy||!onFrame;
    this.$('job').hidden=!this.toolJob;this.$('cancel').disabled=!this.toolJob;
    this.$('previous-mask').disabled=busy||!this.document?.mask_history?.length;this.$('next-mask').disabled=busy||!this.document?.mask_history?.length;
    const reviewRanges=this.maskReviewRanges(),atFrame=reviewRanges.find(range=>this.w.playhead>=range.start_frame&&this.w.playhead<=range.end_frame);
    this.maskReview.hidden=this.stage!=='mask'||!reviewRanges.length;
    this.$('review-count').textContent=`${reviewRanges.length} mask ${reviewRanges.length===1?'change':'changes'} to check`;
    this.$('review-reason').textContent=atFrame?`${atFrame.label||'Mask changed'}. Advisory only: inspect and correct if needed.`:'Amber timeline marks flag abrupt mask changes. Advisory only; no masks have been altered.';
    this.$('review-next').disabled=busy||!!this.manualSaving||!reviewRanges.length;

  }
  morph(authoritative){
    const grow=Number(this.$('grow').value),feather=0;
    this.$('grow-value').textContent=grow+' px';
    this.previewSequence++;if(this.stage==='clean'&&this.selected()){this.selected().editGrow=grow;if(!this.candidate)this.viewer.setOpacity(Number(this.$('opacity').value)/100);}else this.w.state.maskGrow=grow;this.w.state.maskFeather=0;this.viewer.setGrow(grow,0);
    if(authoritative){this.w.save();this.authoritativePreview().catch(e=>this.status(e.message));}
  }
  async authoritativePreview(){
    if(!this.w.sourceInfo||!this.active||this.candidate?.review)return;
    const frame=this.w.playhead,seq=this.sequence,preview=++this.previewSequence;
    const state=this.w.state;let response;
    if(this.stage!=='clean'&&!this.maskSegment()&&!this.selectionDirty&&state.maskProject&&state.maskRevision!=null){
      const params=new URLSearchParams({project:state.maskProject,revision:state.maskRevision,frame,grow:state.maskGrow,feather:state.maskFeather});
      response=await this.w.api.fetchApi(endpoint+'/mask-preview?'+params);
    }else{
      const selection=this.viewer.getSelection();if(!selection.hasMask)return;
      response=await this.w.api.fetchApi(endpoint+'/effective-mask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mask:selection.mask,width:this.w.sourceInfo.width,height:this.w.sourceInfo.height,grow:this.stage==='clean'?(this.selected()?.editGrow??0):state.maskGrow,feather:0,project:state.maskProject,revision:state.maskRevision,source:state.source,frame})});
    }
    if(!response.ok)throw Error('Could not update the full-resolution repair boundary.');
    const blob=await response.blob();if(seq!==this.sequence||frame!==this.w.playhead||preview!==this.previewSequence)return;
    const url=URL.createObjectURL(blob);try{await this.viewer.setEffectiveMask(url);}finally{URL.revokeObjectURL(url);}
    if(preview===this.previewSequence)this.status(this.stage==='clean'?'Red is the exact FLUX edit area. Paint to include shadows; erase to preserve detail.':'Red marks the hard removal boundary.');
  }
  createFrame(frame){
    if(this.manualDirty||this.manualSaving){this.flushManual().then(()=>this.createFrame(frame)).catch(e=>this.status(e.message));return;}
    if(this.w.busy()||!this.w.state.source)return;frame=number(frame,0,(this.w.sourceInfo?.frames||1)-1);const start=Math.min(frame,this.w.state.startFrame),end=Math.max(frame,this.w.state.startFrame+this.w.state.frameCount-1);if(end-start>=993){this.status('Trim a shorter range around this frame before adding its clean guide.');return;}this.w.state.startFrame=start;this.w.state.frameCount=end-start+1;if(this.w.$('start'))this.w.$('start').value=start;if(this.w.$('count'))this.w.$('count').value=end-start+1;
    const old=this.w.state.anchors.findIndex(a=>a.frame===frame);if(old>=0){this.selectFrame(old);return;}
    this.w.state.anchors.push({id:crypto.randomUUID(),frame,file:'',strength:.75,enabled:true,status:'draft',colour_space:this.w.state.sourceColour,versions:[]});
    this.selectFrame(this.w.state.anchors.length-1);this.w.save();
  }
  selectFrame(index){if(this.manualDirty||this.manualSaving){this.flushManual().then(()=>this.selectFrame(index)).catch(e=>this.status(e.message));return;}if(this.w.busy())return;const a=this.w.state.anchors[index];if(!a)return;this.w.selected=index;this.w.syncAnchorControls?.(index);this.w.playhead=a.frame;this.stage='clean';this.$('instruction').value=a.editPrompt||'Remove the selected object and reconstruct the background.';this.w.state.editorStage='clean';this.w.view='anchor';this.active=true;this.candidate=a.candidate||null;this.tool='brush';this.viewer.setTool('brush');this.w.comparison?.hide();if(this.w.$('comparison'))this.w.$('comparison').hidden=true;this.w.updatePlayhead();this.frameChanged(true);this.update();this.w.save();}
  async compareFrame(){try{this.showOriginal=!this.showOriginal;const a=this.selected(),url=this.showOriginal?this.w.thumbnail(this.w.state.source,this.w.playhead,this.w.state.sourceColour,1280):this.candidate?.file?this.w.thumbnail(this.candidate.png_file||this.candidate.file,0,this.candidate.colour_space,1280):this.w.thumbnail(a.preview_file||a.file,0,a.colour_space,1280);await this.viewer.setDisplayImage(url);this.viewer.setOpacity(0);this.updateControls();}catch(e){this.status(e.message);}}
  removeFrame(index){if(this.w.busy())return;this.w.state.anchors.splice(index,1);this.w.selected=-1;this.candidate=null;this.w.changed();}
  async downloadFrame(){
    try{const a=this.selected();if(!a)return;await this.ensureProject();const result=await this.w.fetch('/zura/paintout/export-frame',{project:this.project,file:this.w.state.source,frame:a.frame,colour_space:this.w.state.sourceColour});if(result.reference){a.exportReference=result.reference;this.w.save();this.updateControls();}const link=el('a');link.href=this.w.url(result.url);link.download=result.download_name||`paint_${a.frame}.`+(result.path.endsWith('.exr')?'exr':'png');link.click();this.status('Original frame exported. Import the edited image into this same frame card.');}
    catch(e){this.status(e.message);}
  }
  async reviewImportedFrame(result,anchor,selection=this.viewer.getSelection()){
    const w=this.w;
    if(anchor!==this.selected()||anchor.frame!==w.playhead)throw Error('Select the matching clean-frame card and import again.');
    this.importing=true;this.updateControls();
    try{await this.ensureProject();const review=await w.fetch(endpoint+'/review-import',{project:this.project,source:w.state.source,frame:anchor.frame,file:result.file,source_colour_space:w.state.sourceColour,colour_space:result.colour_space,mask:selection.mask,grow:anchor.editGrow??w.state.maskGrow??0,mask_revision:w.state.maskRevision??null});
      if(anchor!==this.selected()||anchor.frame!==w.playhead)throw Error('The selected frame changed. Import into the intended frame again.');
      this.candidate={...result,method:'manual',review,anchor:anchor.id||anchor.frame};anchor.candidate=this.candidate;if(!anchor.file)anchor.status='needs_review';this.frameKey=null;w.save();this.status('Review the red changes outside your repair, then choose which area to keep.');
    }finally{this.importing=false;w.render();if(this.active)await this.frameChanged(true);}
  }
  async acceptImported(scope){
    const w=this.w,anchor=this.selected(),candidate=this.candidate;
    if(w.busy()||!candidate?.review||!anchor||anchor.frame!==w.playhead||String(anchor.id||anchor.frame)!==String(candidate.anchor))return;
    this.importing=true;this.updateControls();
    try{while(this.saving)await new Promise(resolve=>setTimeout(resolve,10));await this.loadDocument();
      const result=await w.fetch(endpoint+'/accept-import-review',{project:this.project,source:w.state.source,frame:anchor.frame,token:candidate.review.token,scope,expected_revision:this.revision});
      anchor.versions=this.frameVersions(anchor);anchor.versions.push({...result,method:'manual'});Object.assign(anchor,{file:result.file,preview_file:result.preview_file||'',colour_space:result.colour_space,status:'accepted',editMask:result.mask,editGrow:0});delete anchor.candidate;this.candidate=null;this.frameKey=null;w.syncAnchorControls?.(w.selected);w.save();this.status(scope==='include'?'Imported edits included in this guide. The video mask is unchanged.':'Imported frame accepted. Pixels outside the repair remain identical to the source.');
    }catch(error){this.status(error.message);}finally{this.importing=false;w.render();if(this.active)await this.frameChanged(true);}
  }
  async importFrame(){
    if(this.w.busy()||this.candidate)return;const index=this.w.selected,anchor=this.selected();if(index<0||anchor?.frame!==this.w.playhead)return;
    const selection=this.viewer.getSelection();try{const result=await this.w.pickAnchors(index);if(result?.file)await this.reviewImportedFrame(result,anchor,selection);}catch(error){this.status(error.message);}
  }
  async importDropped(file){
    if(this.w.busy()||this.candidate)return;
    const anchor=this.selected(),source=this.w.state.source;
    if(!anchor||anchor.frame!==this.w.playhead){this.status('Select the matching clean-frame card before dropping an edited image.');return;}
    try{
      if(!/\.(png|exr|tiff?)$/i.test(file.name))throw Error('Choose an edited PNG, TIFF or EXR frame.');
      if(file.size>100*1024*1024)throw Error('The edited frame exceeds 100 MB.');
      await this.ensureProject();this.importing=true;this.updateControls();this.status('Checking edited frame dimensions…');
      const body=new FormData();body.append('project',this.project);body.append('source',source);body.append('frame',String(anchor.frame));body.append('colour_space',anchor.colour_space||this.w.state.sourceColour);body.append('file',file,file.name);
      const response=await this.w.api.fetchApi(endpoint+'/import-frame',{method:'POST',body});
      const result=await response.json();if(!response.ok)throw Error(result.error||'The edited frame could not be imported.');
      if(this.w.state.source!==source||!this.w.state.anchors.includes(anchor))throw Error('The shot changed before import completed. Select the intended frame and import again.');
      if(result.frame!==anchor.frame)throw Error('The imported image did not match the selected source frame.');
      await this.reviewImportedFrame(result,anchor);
    }catch(e){this.status(e.message);}finally{this.importing=false;this.w.render();if(this.active)await this.frameChanged(true);}
  }
  async flushManual(){
    if(this.manualSaving){await this.manualSaving;if(this.manualDirty)return this.flushManual();return;}
    if(!this.manualDirty||this.stage!=='mask')return;
    this.manualSaving=(async()=>{
      await this.ensureProject();
      // Project saves and mask commits share the same optimistic revision.
      while(this.saving)await new Promise(resolve=>setTimeout(resolve,20));
      while(this.manualDirty){
        const version=this.manualVersion,frame=this.viewer.frame,selection=this.viewer.getSelection(),project=this.project;
        this.status('Saving mask correction on frame '+frame+'…');
        const doc=await this.w.fetch(endpoint+'/paint-mask',{project,source:this.w.state.source,frame,mask:selection.mask,expected_revision:this.revision,expected_mask_revision:this.w.state.maskRevision??null});
        if(this.project!==project)throw Error('The shot changed before the mask correction could be saved.');
        this.document=doc;this.revision=doc.revision;this.w.state.maskProject=doc.id;this.w.state.maskRevision=doc.mask_revision;this.w.state.maskCoverage=doc.mask_coverage;
        if(version===this.manualVersion){this.manualDirty=false;this.selectionDirty=false;this.subjectChanged=false;this.viewer.setSelection({});}
        this.status('Frame '+frame+' correction saved. Scrub to fix another frame, or track this correction through a section.');
      }
    })();
    try{await this.manualSaving;}catch(e){throw Error('Mask correction was not saved. Stay on this frame and retry. '+e.message);}
    finally{this.manualSaving=null;this.updateControls();}
    this.w.save();this.update();
  }
  async runMask(single,operation){
    if(this.w.busy())return;
    try{if(!single&&!operation&&(this.selectionDirty||this.subjectChanged||!this.viewer.getSelection().hasMask))throw Error('Preview or save the mask on this frame before tracking.');await this.ensureProject();await this.persist();let selection=this.viewer.getSelection();
      const segment=this.maskSegment();
      if(segment&&this.w.playhead!==segment.frame)throw Error('Return to the segment selection frame before previewing or tracking.');
      if(segment&&!single&&!operation){if(!segment.ready||this.selectionDirty||this.subjectChanged)throw Error('Preview the new segment selection before tracking.');selection={positive:[],negative:[],hasMask:true,mask:segment.seedMask};}
      const hasMask=selection.hasMask&&!this.subjectChanged&&!selection.positive.length&&!selection.negative.length;
      let start=single?this.w.playhead:number(this.$('range-start').value,this.w.state.startFrame,this.w.state.startFrame+this.w.state.frameCount-1);
      let end=single?start:number(this.$('range-end').value,start,this.w.state.startFrame+this.w.state.frameCount-1);
      if(!single&&!segment&&!this.customRange&&!operation&&this.$('operation').value==='replace'){
        start=this.w.state.startFrame;end=start+this.w.state.frameCount-1;
        const seeds=(this.document?.mask_history||[]).filter(pass=>pass.revision<=this.w.state.maskRevision&&['replace','add'].includes(pass.operation)).map(pass=>pass.metadata?.frame).filter(Number.isInteger);
        for(const seed of seeds){if(seed<this.w.playhead)start=Math.max(start,seed+1);if(seed>this.w.playhead)end=Math.min(end,seed-1);}
        this.$('range-start').value=start;this.$('range-end').value=end;
      }
      if(this.w.playhead<start||this.w.playhead>end)throw Error('Move the playhead inside the section to track.');
      const graph=maskGraph({source:this.w.state.source,project:this.project,revision:this.revision,frame:this.w.playhead,startFrame:start,frameCount:end-start+1,
        colourSpace:this.w.state.sourceColour,operation:operation||this.$('operation').value,direction:this.$('direction').value,selection:{...selection,hasMask},text:this.$('subject').value},this.w.modelInfo);
      await this.queue(graph,'mask');if(this.toolJob){this.toolJob.maskSingle=single;this.toolJob.maskSegment=!!segment;this.w.save();}
    }catch(e){this.status(e.message);}
  }
  saveCleanMask(){
    const anchor=this.selected();if(this.stage!=='clean'||!anchor||anchor.frame!==this.viewer.frame||this.candidate)return;
    anchor.editMask=this.viewer.getSelection().mask;anchor.editGrow=Number(this.$('grow').value);this.w.save();this.authoritativePreview().catch(e=>this.status(e.message));
  }
  async cleanFrame(){
    if(this.w.busy()||this.candidate)return;
    try{const a=this.selected();if(!a||a.frame!==this.w.playhead)throw Error('Select the clean-frame card at the frame you want to edit.');const selection=this.viewer.getSelection();
      const availability=frameEditAvailability(this.w.modelInfo);if(!availability.ready)throw Error('Frame cleaning needs: '+availability.missing.join(', '));
      const graph=buildFrameEditGraph({source:this.w.state.source,frame:a.frame,colour_space:this.w.state.sourceColour,mask:selection.mask,
        grow:a.editGrow??this.w.state.maskGrow,feather:0,project:this.w.state.maskProject,mask_revision:this.w.state.maskRevision,context:128,max_side:1024,seed:a.editSeed??this.w.state.seed,prompt:this.$('instruction').value},this.w.modelInfo);
      await this.queue(graph,'frame',a.id||a.frame);
    }catch(e){this.status(e.message);}
  }
  async queue(graph,kind,anchor){
    this.submitting=true;this.status('Submitting '+(kind==='mask'?'mask pass':'frame cleanup')+'…');this.w.render();
    try{const response=await this.w.fetch('/prompt',{prompt:graph,client_id:this.w.api.clientId,extra_data:{zura_paintout_editor:true}});
      if(!response.prompt_id)throw Error('ComfyUI did not confirm the run. Check the queue before retrying.');
      this.toolJob={id:response.prompt_id,kind,anchor,source:this.w.state.source,frame:this.w.playhead,stages:Object.fromEntries(Object.entries(graph).map(([id,n])=>[id,n._meta?.title||n.class_type]))};
      this.w.state.editorJob=this.toolJob;this.w.save();this.startPolling();
    }finally{this.submitting=false;this.w.render();}
  }
  startPolling(){if(this.timer)return;this.timer=setInterval(()=>this.poll(),1200);this.poll();}
  async poll(){
    if(!this.toolJob||this.polling)return;this.polling=true;const job=this.toolJob;
    try{const history=await this.w.fetch('/history/'+encodeURIComponent(job.id));if(this.toolJob!==job)return;const entry=history[job.id];
      if(!entry){
        const queue=await this.w.fetch('/queue');if(this.toolJob!==job)return;
        const present=[...(queue.queue_running||[]),...(queue.queue_pending||[])].some(item=>item[1]===job.id);
        this.missingPolls=present?0:(this.missingPolls||0)+1;
        if(this.missingPolls<2){this.$('job-label').textContent='Queued or processing in ComfyUI';return;}
        this.toolJob=null;this.w.state.editorJob=null;clearInterval(this.timer);this.timer=null;this.missingPolls=0;this.w.save();this.w.render();this.status('This run is no longer in the ComfyUI queue. Your accepted frames and masks are saved.');return;
      }
      this.missingPolls=0;
      if(!entry.status?.completed&&entry.status?.status_str!=='error')return;
      this.toolJob=null;this.w.state.editorJob=null;clearInterval(this.timer);this.timer=null;
      const outputs=Object.values(entry.outputs||{}),mask=outputs.flatMap(o=>o.zura_mask||[])[0],frame=outputs.flatMap(o=>o.zura_frame||[])[0],choices=outputs.flatMap(o=>o.zura_mask_choices||[])[0];
      if(choices&&job.source===this.w.state.source){this.showMaskChoices(choices);this.status('Several subjects matched. Choose a preview above; your saved mask is unchanged.');}
      else if(mask){this.w.state.maskProject=mask.project;this.w.state.maskRevision=mask.revision;await this.loadDocument();if(job.maskSingle)await this.acceptSegmentSeed(mask);else if(job.maskSegment){this.w.state.maskSegmentDraft=null;this.customRange=false;this.$('direction').value='both';this.$('operation').value='replace';this.$('range-start').value=this.w.state.startFrame;this.$('range-end').value=this.w.state.startFrame+this.w.state.frameCount-1;}this.subjectChanged=false;this.selectionDirty=false;this.frameKey=null;await this.frameChanged(true);this.status(job.maskSingle?'Selection saved. Check the red area, choose the range and track.':'Segment saved. Scrub to check it. If the subject is lost, use Repair tracking from here; use Add another mask for extra coverage.');}
      else if(frame&&job.source===this.w.state.source){
        const anchor=this.w.state.anchors.find(a=>String(a.id||a.frame)===String(job.anchor));
        if(anchor){anchor.candidate={...frame,anchor:job.anchor};if(!anchor.file)anchor.status='needs_review';this.candidate=anchor.candidate;await this.viewer.setFrame(this.w.thumbnail(frame.png_file||frame.file,0,frame.colour_space,1280),frame.width,frame.height,frame.frame);this.viewer.setOpacity(0);this.status('Review the cleaned frame, then choose Use clean frame or keep the previous version.');}
        else this.status('The frame finished, but its guide card was removed. The result is available in ComfyUI history.');
      }
      else{const failure=entry.status?.messages?.find(m=>m[0]==='execution_error')?.[1];this.status(failure?.exception_message||'Run stopped without a saved result. Your accepted frames and masks are unchanged.');}
      this.w.save();this.w.render();
    }catch(e){this.status('Reconnecting to your run: '+e.message);}finally{this.polling=false;}
  }
  discardFrame(){
    if(this.w.busy()||!this.candidate)return;
    const anchor=this.selected();if(anchor){delete anchor.candidate;if(!this.candidate.review)anchor.editSeed=((anchor.editSeed??Number(this.w.state.seed)) + 1)%2147483647;if(!anchor.file)anchor.status='draft';}
    this.candidate=null;this.frameKey=null;this.w.save();this.frameChanged(true);this.updateControls();this.status('Result discarded. Your mask and saved clean versions are kept.');
  }
  acceptFrame(){const result=this.candidate,a=this.selected();if(!result||result.review||!a||a.frame!==this.w.playhead||String(a.id||a.frame)!==String(result.anchor))return;a.versions||=[];if(a.file&&!a.versions.some(v=>v.file===a.file))a.versions.push({file:a.file,preview_file:a.preview_file,colour_space:a.colour_space});a.versions.push({...result,method:'flux3'});Object.assign(a,{file:result.file,preview_file:result.png_file,colour_space:result.colour_space,status:'accepted'});delete a.candidate;this.candidate=null;this.w.syncAnchorControls?.(this.w.selected);this.w.changed();this.frameChanged(true);this.status('Clean frame '+a.frame+' will guide the next paintout.');}
  async selectMask(delta){if(this.w.busy()||!this.project)return;try{const doc=await this.loadDocument(),list=doc.mask_history||[],index=list.findIndex(m=>m.revision===doc.mask_revision),next=list[index+delta];if(!next)return;const updated=await this.w.fetch(endpoint+'/mask-select',{project:this.project,mask_revision:next.revision,expected_revision:this.revision});this.document=updated;this.revision=updated.revision;this.w.state.maskRevision=updated.mask_revision;this.w.state.maskCoverage=updated.mask_coverage;await this.frameChanged(true);this.w.changed();}catch(e){this.status(e.message);}}
  async cancel(){if(!this.toolJob)return;try{const id=this.toolJob.id;await this.w.fetch('/queue',{delete:[id]});await this.w.fetch('/interrupt',{prompt_id:id});this.status('Cancellation requested for this run.');}catch(e){this.status(e.message);}}
  close(){this.closed=true;this.previewSequence++;clearTimeout(this.saveTimer);clearInterval(this.timer);this.timer=null;this.flushManual().then(()=>this.persist()).catch(e=>this.status(e.message));}
}

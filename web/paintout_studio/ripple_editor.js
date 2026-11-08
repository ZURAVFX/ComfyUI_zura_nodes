// A deliberately first-frame-only presentation of Paintout's proven mask editor.
export const isRipple=editor=>editor.w.state.mode==='ripple';
export function syncRippleWorkspace(w){
  const active=w.ripple;w.page.classList.toggle('is-ripple',active);w.page.querySelector('.zf-heading h2').textContent=active?'Replace an object':'Paintout';
  w.$('empty').querySelector('h3').textContent=active?'Replace an object':'Start your paintout';
  w.$('empty').querySelector('p').textContent=active?'Trim your clip, edit its first frame, then let Ripple carry the replacement through the shot.':'Choose a workflow and add footage.';
  w.$('new').textContent=active?'Start over':'New paintout';
  w.page.querySelector('.zf-model').innerHTML=active?'LTX 2.5 · Ripple':'LTX 2.5';
  if(!active){w.$('prompt').placeholder='Describe your video';w.$('prompt').setAttribute('aria-label','Video prompt');return;}
  w.$('workflow-label').textContent='Object replacement · first frame';w.$('title').textContent='Replace an object with Ripple';
  w.$('prompt').placeholder='Optional: describe the replacement and what should stay unchanged…';
  w.$('prompt').setAttribute('aria-label','Video direction for the first-frame object replacement');
  w.$('anchor-help').textContent=`Replacement is guided by the first selected source frame (${w.state.startFrame}). Trim again to start at a different frame.`;
  w.$('generate').textContent=w.busy()?'Generating…':w.validationError?'Finish first-frame setup':'Generate replacement';
  if(w.result)w.$('result-status').textContent=`Ready · ${w.result.config.frameCount} frames · Your object replacement is ready to play`;
  w.$('note').textContent=w.validationError||(!w.availability?.ready?w.$('setup').textContent:'The mask controls the first-frame image edit. Ripple propagates the whole image, so nearby details may also change.');
  w.$('note').hidden=false;
}

export function syncRippleEditor(e){
  if(!isRipple(e)){if(e.rippleMaskToggle)e.rippleMaskToggle.hidden=true;e.w.page.classList.remove('ripple-adjust-mask');for(const button of e.viewerToolbar.querySelectorAll('[data-tool=brush],[data-tool=protect],[data-editor=undo],[data-editor-menu=mask]'))button.hidden=false;e.nav.setAttribute('aria-label','Paintout stages');for(const b of e.nav.querySelectorAll('[data-stage]'))b.textContent=({trim:'Trim clip',mask:'Mask',clean:e.w.state.mode==='inpaint'?'Reference frame':'Clean frames',render:'Render'})[b.dataset.stage];e.$('instruction').closest('label').firstChild.textContent='Instruction';return;}
  const w=e.w,busy=w.busy(),clean=e.stage==='clean',frame=w.state.startFrame;
  e.nav.setAttribute('aria-label','First-frame object replacement');
  const labels={trim:'Trim clip',mask:'Select object',clean:'Replacement frame',render:'Generate'};
  for(const b of e.nav.querySelectorAll('[data-stage]'))b.textContent=labels[b.dataset.stage];
  e.timelineHost.hidden=e.stage!=='trim'||!w.state.source;
  e.projects.hidden=true;
  e.maskSummary.hidden=true;e.maskReview.hidden=true;
  e.$('track').hidden=true;e.$('import-mask').hidden=true;
  e.$('continue').disabled=busy||!e.viewer.getSelection(false).hasMask||!!e.manualSaving||e.selectionDirty||e.autoPreviewPending;
  e.$('continue').querySelector('span').textContent='Next: replacement frame';
  e.$('render-next').querySelector('span').textContent='Use this first frame';
  if(!e.rippleReviewClick){e.rippleReviewClick=e.$('render-next').onclick;e.$('render-next').onclick=async event=>{if(!isRipple(e))return e.rippleReviewClick(event);const anchor=e.selected();if(!anchor?.file||anchor.frame!==w.state.startFrame||anchor.status!=='accepted'||anchor.enabled===false||e.candidate||w.busy())return;anchor.rippleReviewedFile=anchor.file;w.save();await e.setStage('render');};}
  e.$('render-next').disabled=busy||!!e.candidate||!w.state.anchors.some(a=>a.frame===frame&&a.file&&a.status==='accepted'&&a.enabled!==false);
  if(!e.rippleMaskToggle){const button=document.createElement('button');button.type='button';button.textContent='Adjust mask';button.onclick=()=>{e.rippleAdjustMask=!e.rippleAdjustMask;e.tool=e.rippleAdjustMask?'brush':'pan';e.viewer.setTool(e.tool);e.updateControls();};e.viewerToolbar.append(button);e.rippleMaskToggle=button;}
  e.rippleMaskToggle.hidden=!clean;e.rippleMaskToggle.disabled=busy;e.rippleMaskToggle.setAttribute('aria-pressed',String(!!e.rippleAdjustMask));
  w.page.classList.toggle('ripple-adjust-mask',clean&&!!e.rippleAdjustMask);
  for(const button of e.viewerToolbar.querySelectorAll('[data-tool=brush],[data-tool=protect],[data-editor=undo],[data-editor-menu=mask]'))button.hidden=clean&&!e.rippleAdjustMask;
  e.objectReferenceTools.hidden=!clean;e.$('instruction').closest('label').firstChild.textContent='Replacement instruction';
  e.$('instruction').placeholder='e.g. Replace the microphone with the gold microphone in my reference';
  e.$('clean').textContent=e.selected()?.cleanAttempt?'Try again':e.selected()?.file?'Add replacement edit':'Create replacement frame';
  e.$('compare').textContent=e.showOriginal?'Show replacement':'Show original';
  e.$('frame-label').textContent=`First selected frame · ${frame}`;
  e.$('tool-help').textContent='Select or paint the object to replace. Include the space needed by the replacement. Erase any area that must stay unchanged in this first image.';
  e.$('selection-cue').textContent=e.autoPreviewPending?'Updating your first-frame mask…':'This mask guides the image edit only. No tracking is needed.';
  e.guideHelp.hidden=false;
  if(!e.toolJob&&!w.job&&!busy){
    const copy={trim:['Choose where the replacement starts','Drag the trim handles. The first selected frame becomes the only editable guide frame.'],mask:[`Select the object on frame ${frame}`,'Click to select, or paint a mask. Expand it if the replacement needs more room.'],clean:[`Create the replacement on frame ${frame}`,'Your object mask is already applied. Add a reference and describe the replacement, or use a finished first frame.'],render:['Review and generate','Ripple carries your first-frame edit through this trimmed clip. The original audio and frame rate are retained.']};
    [e.guideTitle.textContent,e.guideHelp.textContent]=copy[e.stage];
  }
  if(!e.rippleImport){
    const button=document.createElement('button');button.type='button';button.className='ripple-import';button.textContent='Use a finished first frame';
    button.onclick=async()=>{await e.setStage('clean');await e.importFrame();};e.guideActions.append(button);e.rippleImport=button;
  }
  e.rippleImport.hidden=e.stage!=='mask';e.rippleImport.disabled=busy;
}

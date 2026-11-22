/** The same two-step relight flow for the native LTX and H3 renderers. */
export class RelightSimpleSurface {
  constructor(workspace){
    this.w=workspace;const w=workspace,doc=w.page.ownerDocument;
    w.page.classList.add('zru-relight-simple');
    if(!doc.getElementById('zura-relight-simple-styles')){const css=doc.createElement('link');css.id='zura-relight-simple-styles';css.rel='stylesheet';css.href=new URL('./studio_relight_simple.css',import.meta.url).href;doc.head.append(css);}
    const viewer=w.page.querySelector('.zru-viewer');
    this.frames=doc.createElement('div');this.frames.className='zru-relight-frames';viewer.before(this.frames);
    const source=doc.createElement('section');source.className='zru-relight-source';const title=doc.createElement('h3');title.textContent='Original video';source.append(title,viewer);
    this.card=doc.createElement('section');this.card.className='zru-lighting-card';
    this.card.innerHTML='<h3>1. Create a lighting frame</h3><div class="zru-lighting-preview"><p>Set the lighting on one frame, then apply it throughout the video.</p></div><div class="zru-lighting-actions"><button type="button" data-lighting-edit>Create lighting frame</button><button type="button" data-lighting-upload>Upload lighting image</button></div><p class="zru-lighting-state" role="status"></p>';
    this.frames.append(source,this.card);
    const timeline=w.$('timeline');this.advanced=doc.createElement('details');this.advanced.className='zru-relight-advanced';
    const summary=doc.createElement('summary');summary.textContent='Advanced · clip range and extra lighting frames';this.advanced.append(summary);timeline.before(this.advanced);this.advanced.append(timeline);
    this.advanced.open=w.state.relightAdvanced===true;
    this.advanced.ontoggle=()=>{if(w.state.relightAdvanced===this.advanced.open)return;w.state.relightAdvanced=this.advanced.open;w.save();w.render();};
    this.card.querySelector('[data-lighting-edit]').onclick=()=>this.edit();
    this.card.querySelector('[data-lighting-upload]').onclick=()=>{if(w.busy()||!w.source)return;this.anchor();w.$('import-file').click();};
    w.page.querySelector('.zru-empty span').textContent='Add a video, create a lighting frame, then relight the video.';
    w.$('engine').setAttribute('aria-label','Relight model');
    w.$('generate').setAttribute('aria-label','Relight video');
    const resolution=doc.createElement('label');
    resolution.className='zru-return-source';
    this.returnSource=doc.createElement('input');
    this.returnSource.type='checkbox';
    this.returnSource.onchange=()=>{w.state.returnSourceResolution=this.returnSource.checked;w.save();w.render();};
    resolution.append(this.returnSource,'Return at source resolution');
    w.$('scale').closest('label').after(resolution);
    const option=doc.createElement('option');
    option.value='custom';option.textContent='Custom megapixels';
    w.$('scale').append(option);
    w.$('scale').value=String(w.state.scale);
    this.megapixels=doc.createElement('label');
    this.megapixels.className='zru-relight-megapixels';
    this.megapixels.innerHTML='<span>Megapixels</span><input type="range" min="0.25" max="8.35" step="0.05"><output></output>';
    this.megapixelInput=this.megapixels.querySelector('input');
    this.megapixelInput.oninput=()=>{w.state.megapixels=Number(this.megapixelInput.value);w.save();w.render();};
    resolution.before(this.megapixels);
  }
  anchor(){
    const w=this.w,existing=w.ltxReference();
    if(existing&&existing.frame>=w.state.startFrame&&existing.frame<w.state.startFrame+w.state.frameCount){w.selectedId=existing.id;return existing;}
    w.addAnchor(w.state.startFrame);const anchor=w.selected();if(anchor)w.state.ltxReferenceId=anchor.id;return anchor;
  }
  async edit(){
    const w=this.w;if(w.busy()||!w.source)return;
    const anchor=this.anchor();if(!anchor)return;
    w.state.playhead=anchor.frame;w.updatePlayhead();
    await w.owner.rippleImage.edit(w,anchor);
  }
  sync(){
    const w=this.w,has=!!w.source,busy=w.busy(),anchor=w.ltxReference(),ready=!!anchor?.file;
    this.returnSource.checked=w.state.returnSourceResolution!==false;
    this.returnSource.disabled=busy||!has;
    this.megapixels.hidden=w.state.scale!=='custom';
    this.megapixelInput.disabled=busy||!has;
    this.megapixelInput.value=w.state.megapixels||.9;
    this.megapixels.querySelector('output').textContent=`${Number(this.megapixelInput.value).toFixed(2)} MP`;
    this.frames.classList.toggle('has-source',has);this.advanced.hidden=!has;
    let image=this.card.querySelector('img');const empty=this.card.querySelector('.zru-lighting-preview p');empty.hidden=ready;
    if(ready){const url=w.thumbnail(anchor.file,0,anchor.colour_space||'srgb_display',640);if(!image){image=this.card.ownerDocument.createElement('img');image.alt='Lighting reference';image.src=url;this.card.querySelector('.zru-lighting-preview').prepend(image);}else if(image.getAttribute('src')!==url)image.src=url;}
    else image?.remove();
    const edit=this.card.querySelector('[data-lighting-edit]');edit.textContent=ready?'Edit lighting frame':'Create lighting frame';edit.disabled=!has||busy;
    this.card.querySelector('[data-lighting-upload]').disabled=!has||busy;
    this.card.querySelector('.zru-lighting-state').textContent=ready?(anchor.fitted?'Lighting image centre-cropped to match the source.':'Lighting frame ready. Next: Relight video.'):has?'Describe the lighting below, then create or upload a lighting frame.':'Add a video to begin.';
    this.card.querySelector('h3').textContent=ready?'1. Review the lighting frame':'1. Create a lighting frame';
    w.$('generate').textContent=busy?'Relighting…':'2. Relight video';
  }
}

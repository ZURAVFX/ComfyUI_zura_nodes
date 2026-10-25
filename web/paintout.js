import { app } from '/scripts/app.js';
import { api } from '/scripts/api.js';

if (!globalThis.__zuraPaintoutMediaBrowserLoaded) {
globalThis.__zuraPaintoutMediaBrowserLoaded = true;
const css=`.zp-panel{box-sizing:border-box;height:100%;overflow:auto;padding:12px;background:#202329;color:#e9edf1;font:13px system-ui}.zp-panel button{padding:7px 11px;border:1px solid #526477;background:#303e4d;color:#f0f4f8;border-radius:5px;cursor:pointer}.zp-panel button:disabled{opacity:.5}.zp-panel input,.zp-panel select{box-sizing:border-box;background:#15191e;color:#edf1f5;border:1px solid #56616e;border-radius:4px;padding:5px;min-width:0}.zp-help{color:#acbac7;font-size:12px;line-height:1.5;margin:0 0 10px}.zp-card{display:grid;grid-template-columns:120px 1fr;gap:12px;padding:10px;margin:8px 0;background:#292f37;border:1px solid #414d5b;border-radius:7px}.zp-card img{width:120px;height:82px;object-fit:contain;background:#121519;border-radius:4px}.zp-fields{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.zp-fields label{display:flex;align-items:center;gap:5px}.zp-name{overflow-wrap:anywhere;font-weight:600}.zp-line{padding:9px 0;border-bottom:1px solid #3a424b}.zp-toolbar{display:flex;flex-wrap:wrap;gap:8px}.zp-error{color:#ffb8ab;white-space:pre-wrap;margin:8px 0}.zp-panel video{width:100%;max-height:380px;background:#111}`;
const style=document.createElement('style');style.textContent=css;document.head.append(style);
const widget=(n,k)=>n.widgets?.find(w=>w.name===k);
function hide(w){if(!w)return;w.type='converted-widget';w.computeSize=()=>[0,-4];if(w.inputEl)w.inputEl.style.display='none';}
function el(tag,text,cls){const e=document.createElement(tag);if(text)e.textContent=text;if(cls)e.className=cls;return e;}
function button(text,fn){const b=el('button',text);b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();}finally{b.disabled=false;}};return b;}
const name=p=>String(p||'No file selected').split(/[\\/]/).pop();
function thumb(file,space='acescg'){const img=el('img');img.alt='Painted frame preview';if(file)img.src=api.apiURL('/zura/paintout/thumbnail?'+new URLSearchParams({file,space}));img.onerror=()=>{img.alt='Preview unavailable: check file and colour space';};return img;}
async function pick(kind){const r=await api.fetchApi('/zura/paintout/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind})});if([404,405].includes(r.status))throw Error('The file browser has not loaded in ComfyUI yet. Restart ComfyUI, then refresh this page.');const text=await r.text();let d;try{d=JSON.parse(text);}catch{throw Error('ComfyUI could not open the file browser. Restart ComfyUI and refresh this page.');}if(!r.ok)throw Error(d.error||'Could not browse files');return d.paths;}
function panel(node,key,height){const box=el('div','', 'zp-panel');node.addDOMWidget(key,'zura_panel',box,{serialize:false,hideOnZoom:false,getMinHeight:()=>height});return box;}
function redrawOnConfigure(node,draw){const old=node.onConfigure;node.onConfigure=function(){const r=old?.apply(this,arguments);draw();return r;};let stamp;const bg=node.onDrawBackground;node.onDrawBackground=function(){const current=JSON.stringify(node.widgets.filter(w=>w.type==='converted-widget').map(w=>w.value));if(current!==stamp){stamp=current;draw();}return bg?.apply(this,arguments);};}

app.registerExtension({
 name:'Zura.Paintout.MediaBrowser',
 async beforeRegisterNodeDef(nodeType,nodeData){
  if(!['ZuraPaintoutCrop','ZuraPaintoutFromAnchors','ZuraPaintoutFullFrame','ZuraPaintoutExportFrames','ZuraPaintoutAnchors','ZuraPaintoutAnchorFiles','ZuraPaintoutUncrop'].includes(nodeData.name))return;
  const created=nodeType.prototype.onNodeCreated;
  nodeType.prototype.onNodeCreated=function(){
   const result=created?.apply(this,arguments), node=this;
   const labels={framing_mode:'Framing',render_width:'Render width',render_height:'Render height',colour_space:'Source colour space',processing_mode:'Process as',start_frame:'Start frame',frame_count:'Frames to process',sequence_fps:'EXR frame rate',context_pixels:'Crop context (pixels)',max_crop_side:'Crop size limit',repair_grow:'Cover object edges (pixels)',feather_pixels:'Blend softness (pixels)',output_name:'Save folder / take name',precision:'EXR precision',match_context:'Match surrounding colour',export_format:'Save as',motion_preview:'Make motion preview'};
   for(const w of node.widgets||[])if(labels[w.name])w.label=labels[w.name];
   if(nodeData.name==='ZuraPaintoutFullFrame')for(const key of ['context_pixels','max_crop_side','repair_grow','feather_pixels','framing_mode'])hide(widget(node,key));
   if(['ZuraPaintoutCrop','ZuraPaintoutFromAnchors','ZuraPaintoutFullFrame','ZuraPaintoutExportFrames'].includes(nodeData.name)){
    const fields=['plate_path',...(nodeData.name==='ZuraPaintoutCrop'?['mask_path']:[])];
    fields.forEach(k=>hide(widget(node,k)));
    const fpsWidget=widget(node,'sequence_fps');hide(fpsWidget);
    const videoPath=p=>/\.(mov|mp4|mxf|mkv|avi|webm|m4v)$/i.test(String(p||''));
    const inferMode=p=>p&&!videoPath(p)?'sequence':'video';
    const box=panel(node,'footage_browser',nodeData.name==='ZuraPaintoutCrop'?370:250);
    const draw=()=>{
     box.replaceChildren();box.append(el('p','Choose a video or an image sequence below. Set the source colour space to match your footage.','zp-help'));
     node.properties ||= {};node.properties.zuraInputModes ||= {};
     for(const key of fields){
      const line=el('div','','zp-line'),w=widget(node,key),isPlate=key==='plate_path';
      const modes=node.properties.zuraInputModes;
      const mode=modes[key]||inferMode(w.value);
      line.append(el('div',isPlate?'Original footage':'Removal mask','zp-name'));
      const options=el('div','','zp-fields'),typeLabel=el('label','Load as '),select=el('select');
      select.setAttribute('aria-label',isPlate?'Footage input type':'Mask input type');
      for(const [value,title] of [['video','Video file'],['sequence','Image sequence (EXR / TIFF / PNG)']]){const option=el('option',title);option.value=value;select.append(option);}
      select.value=mode;select.onchange=()=>{modes[key]=select.value;if(w.value&&inferMode(w.value)!==select.value)w.value='';node.graph?.setDirtyCanvas(true,true);draw();};
      typeLabel.append(select);options.append(typeLabel);line.append(options);
      const selected=el('div',w.value?name(w.value):(mode==='sequence'?'No sequence folder selected':'No video selected'),'zp-help');selected.title=w.value||'';line.append(selected);
      const error=el('div','','zp-error');
      const choose=async()=>{try{error.textContent='';const paths=await pick(mode==='sequence'?'sequence':isPlate?'footage':'mask');if(paths.length){if(mode==='video'&&!videoPath(paths[0]))throw Error('Choose a video file. For EXR, TIFF or PNG frames, switch Load as to Image sequence.');w.value=paths[0];modes[key]=mode;node.graph?.setDirtyCanvas(true,true);draw();}}catch(e){error.textContent=e.message;}};
      const toolbar=el('div','','zp-toolbar');toolbar.append(button(mode==='sequence'?'Choose sequence folder':'Choose video file',choose));line.append(toolbar);
      if(mode==='sequence'){
       line.append(el('p','Select the folder containing one image sequence. Frames are loaded in numeric filename order.','zp-help'));
       if(isPlate&&fpsWidget){
        const row=el('div','','zp-fields'),label=el('label','Sequence frame rate (fps) '),input=el('input');input.type='number';input.min='1';input.max='120';input.step='0.01';input.value=fpsWidget.value;input.style.width='95px';input.setAttribute('aria-label','Sequence frame rate (fps)');
        input.onchange=()=>{const value=Number(input.value);if(!Number.isFinite(value)||value<1||value>120){input.value=fpsWidget.value;error.textContent='Enter a sequence frame rate from 1 to 120 fps.';return;}fpsWidget.value=value;error.textContent='';node.graph?.setDirtyCanvas(true,true);};
        label.append(input);row.append(label);line.append(row,el('p','Images do not store playback speed. Enter the frame rate of the original shot.','zp-help'));
       }else if(!isPlate)line.append(el('p','One mask image per source frame. Uses the original footage timing.','zp-help'));
      }else if(isPlate)line.append(el('p','Frame rate is read automatically from the video.','zp-help'));
      if(!isPlate)line.append(el('p','White = remove. Black = keep. Match the source size and frame order.','zp-help'));
      line.append(error);box.append(line);
     }
    };redrawOnConfigure(node,draw);node.size=[510,nodeData.name==='ZuraPaintoutCrop'?750:510];draw();
   }
   if(['ZuraPaintoutAnchors','ZuraPaintoutAnchorFiles'].includes(nodeData.name)){
    const data=widget(node,'anchors');hide(data);const box=panel(node,'painted_anchor_cards',340);
    const rows=()=>{try{const a=JSON.parse(data.value);return Array.isArray(a)?a:[];}catch{return[];}};
    const commit=a=>{data.value=JSON.stringify(a,null,2);node.graph?.setDirtyCanvas(true,true);};
    const draw=()=>{box.replaceChildren();box.append(el('p','Paint full-size frames, then add them here. Use the original footage frame numbers, starting at 0. Use -1 for the last selected frame. Thumbnails are display previews.','zp-help'));const error=el('div','','zp-error');
     const toolbar=el('div','','zp-toolbar');toolbar.append(button('+ Browse painted frames',async()=>{try{const files=await pick('anchor'),a=rows();for(const file of files){const inferred=name(file).match(/(\d+)(?=\.[^.]+$)/);a.push({frame:inferred?Number(inferred[1]):0,file,strength:.75,enabled:true,colour_space:/\.(png)$/i.test(file)?'srgb_display':'acescg'});}commit(a);draw();}catch(e){error.textContent=e.message;}}));
     const manifest=el('input');manifest.type='file';manifest.accept='.json';manifest.hidden=true;manifest.onchange=async()=>{try{const a=JSON.parse(await manifest.files[0].text());if(!Array.isArray(a))throw Error('Expected an anchor list');commit(a);draw();}catch(e){error.textContent=e.message;}manifest.value='';};toolbar.append(button('Import anchor list',()=>manifest.click()),manifest);box.append(toolbar,error);
     const a=rows();if(!a.length)box.append(el('p','No painted frames yet. Add one or more files above.','zp-help'));
     a.forEach((row,index)=>{const card=el('div','','zp-card'),info=el('div');card.append(thumb(row.file,row.colour_space||'acescg'));info.append(el('div',name(row.file),'zp-name'));const controls=el('div','','zp-fields');
      for(const [key,title,type] of [['enabled','Use','checkbox'],['frame','Frame','number'],['strength','Strength','number']]){const label=el('label',title),input=el('input');input.type=type;if(type==='checkbox')input.checked=row.enabled!==false;else input.value=row[key]??.75;if(key==='frame'){input.step='1';input.min='-1';input.style.width='75px';}if(key==='strength'){input.min='.05';input.max='1';input.step='.05';input.style.width='72px';}input.onchange=()=>{a[index][key]=type==='checkbox'?input.checked:Number(input.value);commit(a);};label.append(input);controls.append(label);}info.append(controls);
      const colour=el('select');for(const [value,title] of [['acescg','ACEScg EXR'],['acescct','ACEScct EXR'],['linear_rec709','Linear Rec.709 EXR'],['srgb_display','sRGB image'],['hlg_rec2020','HLG TIFF'],['rec709_gamma24','Rec.709 gamma 2.4']]){const o=el('option',title);o.value=value;colour.append(o);}colour.value=row.colour_space||'acescg';colour.onchange=()=>{a[index].colour_space=colour.value;commit(a);draw();};info.append(colour);
      const actions=el('div','','zp-toolbar');actions.style.marginTop='8px';actions.append(button('Replace',async()=>{try{const files=await pick('anchor');if(files.length){a[index].file=files[0];commit(a);draw();}}catch(e){error.textContent=e.message;}}),button('Remove',()=>{a.splice(index,1);commit(a);draw();}));info.append(actions);card.append(info);box.append(card);});
    };redrawOnConfigure(node,draw);node.size=[590,570];draw();
   }
   if(nodeData.name==='ZuraPaintoutUncrop'){
    const box=panel(node,'motion_preview',230);box.append(el('p','After rendering, play the SDR motion preview here. Export SDR video, HLG video or EXR masters with the format control.','zp-help'));
    const old=node.onExecuted;node.onExecuted=function(data){old?.apply(this,arguments);box.replaceChildren();for(const file of (data.images||[]).filter(f=>/\.mp4$/i.test(f.filename))){box.append(el('div',file.filename,'zp-help'));const video=el('video');video.controls=true;video.loop=true;video.muted=true;video.preload='metadata';video.src=api.apiURL('/view?'+new URLSearchParams(file));box.append(video);}if(data.text)box.append(el('div',data.text.join('\n'),'zp-help'));};node.size=[530,560];
   }
   return result;
  };
 }
});


}

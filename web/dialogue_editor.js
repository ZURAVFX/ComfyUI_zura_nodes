import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const media = source => api.apiURL('/zura/dialogue/media?source='+encodeURIComponent(source));
const widget = (node,name) => node?.widgets?.find(w=>w.name===name);
const read = (node,name) => widget(node,name)?.value;
const write = (node,name,value) => { const w=widget(node,name);if(w){w.value=value;w.callback?.(value);}node.graph?.setDirtyCanvas(true,true);if(node.comfyClass==='ZuraDialogueSource'&&['word_start','word_end','context_start','context_end'].includes(name))syncSourceTiming(node); };
const el = (tag,attrs={},text='') => {const e=document.createElement(tag);Object.assign(e,attrs);e.textContent=text;return e;};

function connectedSource(node){
  const seen=new Set();
  while(node&&!seen.has(node)){
    if(node.comfyClass==='ZuraDialogueSource')return node;
    seen.add(node);const input=node.inputs?.find(i=>i.name==='edit'||i.type==='ZURA_DIALOGUE_EDIT'),links=node.graph?.links;
    const link=typeof links?.get==='function'?links.get(input?.link):links?.[input?.link];
    node=link?node.graph?.getNodeById?.(link.origin_id):null;
  }
  return null;
}
const timingMode=node=>read(node,'timing_mode')||node.properties?.zuraDialogueTimingMode||'source';
function contextWindow(fps,frames,start,end,contextStart,contextEnd){
  let first=Math.floor(contextStart*fps),last=Math.min(frames,Math.ceil(contextEnd*fps));
  const a=Math.floor(start*fps),b=Math.min(frames,Math.ceil(end*fps));
  if(b-a>241)throw new Error(`Selected words exceed ${(241/fps).toFixed(2)}s. Split them into shorter takes.`);
  if(last-first>241){const margin=Math.min(Math.floor(.75*fps+.5),Math.floor((241-(b-a))/2));first=Math.max(first,a-margin);last=Math.min(last,b+margin);}
  return [first,last];
}
function sourceRange(node){
  const source=connectedSource(node);if(!source)return null;
  const fps=source.properties?.zuraDialogueInfo?.fps;
  const context=Number(read(source,'context_start'))||0;
  let offset=fps?Math.floor(context*fps)/fps:context;
  if(fps&&source.properties.zuraDialogueInfo.frames){
    try{offset=contextWindow(fps,source.properties.zuraDialogueInfo.frames,Number(read(source,'word_start')),Number(read(source,'word_end')),context,Number(read(source,'context_end')))[0]/fps;}catch{return null;}
  }
  return [Number(read(source,'word_start'))-offset,Number(read(source,'word_end'))-offset];
}
function syncSourceTiming(source){
  for(const node of source.graph?._nodes||[]){
    if(node.comfyClass!=='ZuraDialogueFinish'||timingMode(node)!=='source'||connectedSource(node)!==source)continue;
    const range=sourceRange(node);if(range){write(node,'generated_word_start',range[0]);write(node,'generated_word_end',range[1]);}
  }
}

export function waveform(canvas,peaks,duration,getRange,setRange,seek,getPlayhead=()=>0,commit=()=>{}){
  const ctx=canvas.getContext('2d');let active=null;
  const draw=()=>{
    const [start,end]=getRange(),w=canvas.width,h=canvas.height,top=25,bottom=h-24,mid=(top+bottom)/2;
    ctx.fillStyle='#101721';ctx.fillRect(0,0,w,h);ctx.fillStyle='#244d45';ctx.fillRect(start/duration*w,top,(end-start)/duration*w,bottom-top);
    const max=Math.max(.02,...peaks);ctx.strokeStyle='#b9c9d8';ctx.beginPath();
    peaks.forEach((v,i)=>{const x=i/peaks.length*w,amplitude=v/max*(bottom-top)*.42;ctx.moveTo(x,mid-amplitude);ctx.lineTo(x,mid+amplitude);});ctx.stroke();
    ctx.font='16px system-ui';ctx.fillStyle='#b9c9d8';ctx.textAlign='center';
    const tick=duration>10?Math.ceil(duration/8):.5;
    for(let t=0;t<=duration;t+=tick){const x=t/duration*w;ctx.fillRect(x,bottom,1,6);ctx.fillText(t.toFixed(1)+'s',Math.max(22,Math.min(w-22,x)),h-3);}
    for(const [time,label] of [[start,'IN'],[end,'OUT']]){const x=time/duration*w;ctx.fillStyle='#8de6c9';ctx.fillRect(x-2,22,4,bottom-22);ctx.fillRect(x-15,1,30,22);ctx.fillStyle='#10251e';ctx.font='bold 13px system-ui';ctx.fillText(label,x,17);}
    const x=getPlayhead()/duration*w;ctx.fillStyle='#ffd089';ctx.fillRect(x-1,25,2,bottom-25);
  };
  const time=e=>Math.max(0,Math.min(duration,(e.clientX-canvas.getBoundingClientRect().left)/canvas.getBoundingClientRect().width*duration));
  function hit(e){const t=time(e),[a,b]=getRange(),radius=14/canvas.getBoundingClientRect().width*duration;return Math.min(Math.abs(t-a),Math.abs(t-b))<=radius?(Math.abs(t-a)<Math.abs(t-b)?0:1):null;}
  canvas.onpointerdown=e=>{e.preventDefault();e.stopPropagation();active=hit(e);canvas.setPointerCapture(e.pointerId);if(active===null){seek(time(e));draw();}else canvas.style.cursor='grabbing';};
  canvas.onpointermove=e=>{e.stopPropagation();if(active===null){canvas.style.cursor=hit(e)===null?'crosshair':'ew-resize';return;}const range=[...getRange()],t=time(e);range[active]=active?Math.max(range[0]+.001,t):Math.min(range[1]-.001,t);setRange(range);seek(t);draw();};
  canvas.onpointerup=canvas.onpointercancel=e=>{e.stopPropagation();if(active!==null)commit();active=null;canvas.style.cursor='crosshair';if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);};
  draw();return draw;
}
export function embeddedWidget(node,name,type,root,height,minWidth){
  const dom=node.addDOMWidget(name,type,root,{serialize:false,getMinHeight:()=>height,getMaxHeight:()=>height,getValue:()=>'',setValue:()=>{},hideOnZoom:false});
  // The properties-panel canvas renderer writes widget.width using its narrower
  // panel. Keep this DOM widget tied to its own node instead of that shared cache.
  Object.defineProperty(dom,'width',{configurable:true,get:()=>node.size[0],set:()=>{}});
  dom.computeLayoutSize=()=>({minHeight:height,maxHeight:height,minWidth});return dom;
}

async function picker(node,generated=false,host=null){
  const source=generated?node._dialoguePreview?.generated_video:read(node,'source');
  if(!source)throw new Error(generated?'Run the workflow once to preview the generated words.':'Choose a local video first.');
  const response=await api.fetchApi('/zura/dialogue/info',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source})});
  const info=await response.json();if(!response.ok)throw new Error(info.error);
  if(!generated){node.properties.zuraDialogueInfo={fps:info.fps,frames:info.frames};syncSourceTiming(node);}
  const shade=el('div',{className:host?'zura-dialogue-inline':'zura-dialogue-shade'}),panel=el('section',{className:'zura-dialogue-panel'});shade.append(panel);
  const style=el('style');style.textContent=`
    .zura-dialogue-shade{position:fixed;inset:0;z-index:100000;background:#05080dd9;display:grid;place-items:center;font:14px system-ui;color:#e3eaf2}
    .zura-dialogue-panel{width:min(1100px,96vw);max-height:94vh;overflow:auto;background:#18212d;border:1px solid #3b4b5d;border-radius:16px;padding:24px;box-shadow:0 20px 90px #0009}
    .zura-dialogue-panel h2{margin:0 0 8px;font-size:22px}.zura-dialogue-panel p{color:#a8b8c9;margin:8px 0 18px}
    .zura-dialogue-row{display:flex;gap:20px;align-items:start}.zura-dialogue-picture{position:relative;flex:1;min-width:0;background:#080d13;border-radius:8px;overflow:hidden}
    .zura-dialogue-picture video{display:block;width:100%;height:auto}.zura-dialogue-picture canvas{position:absolute;inset:0;width:100%;height:100%;touch-action:none}
    .zura-dialogue-tools{width:240px;display:grid;gap:10px}.zura-dialogue-panel button,.zura-dialogue-panel input{font:inherit;color:inherit;background:#263345;border:1px solid #506278;border-radius:6px;padding:8px}
    .zura-dialogue-panel button{cursor:pointer}.zura-dialogue-panel button[aria-pressed=true]{border-color:#65e4c0;background:#21453e}.zura-dialogue-panel .primary{background:#60ddba;color:#10241f;border:0;font-weight:650}
    .zura-dialogue-panel label{display:grid;gap:5px;font-size:12px;color:#b7c6d8}.zura-dialogue-panel input[type=number]{width:100%;box-sizing:border-box}
    .zura-dialogue-wave{width:100%;height:100px;border:1px solid #46566b;border-radius:8px;touch-action:none;margin:12px 0}
    .zura-dialogue-times{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.zura-dialogue-actions{display:flex;gap:12px;justify-content:flex-end;margin-top:18px}
    .zura-dialogue-status{color:#65e4c0;font-size:12px;min-height:18px}.zura-dialogue-panel input[type=range]{padding:0;width:100%}
    @media(max-width:750px){.zura-dialogue-row{display:block}.zura-dialogue-tools{width:auto;grid-template-columns:1fr 1fr;margin-top:12px}.zura-dialogue-times{grid-template-columns:1fr 1fr}}
    .zura-dialogue-inline{font:13px system-ui;color:#e3eaf2;width:100%;height:100%;overflow:auto;background:#18212d;border-radius:10px;box-sizing:border-box}
    .zura-dialogue-inline .zura-dialogue-panel{width:auto;max-height:none;padding:14px;border:0;border-radius:10px;box-shadow:none;overflow:visible}
    .zura-dialogue-inline .zura-dialogue-panel h2{font-size:18px}.zura-dialogue-inline .zura-dialogue-panel p{font-size:12px;margin-bottom:12px}
    .zura-dialogue-inline .zura-dialogue-row{display:flex;gap:12px}.zura-dialogue-inline .zura-dialogue-picture{flex:1;max-width:none!important}
    .zura-dialogue-inline .zura-dialogue-tools{width:160px;display:grid;grid-template-columns:1fr;gap:7px}
    .zura-dialogue-inline .zura-dialogue-panel button,.zura-dialogue-inline .zura-dialogue-panel input{padding:6px;font-size:12px}
    .zura-dialogue-inline .zura-dialogue-times{grid-template-columns:1fr 1fr;gap:8px}.zura-dialogue-inline .zura-dialogue-wave{height:78px;margin:10px 0}
    .zura-dialogue-inline .zura-dialogue-actions{margin-top:10px}.zura-dialogue-inline .zura-dialogue-status{color:#9eecd7}
  `;shade.append(style);
  panel.append(el('h2',{},generated?'Select replacement words':'Select words and face'));
  panel.append(el('p',{},generated?'Mark only the replacement words. These times refer to the last generated face clip.':'Draw the face crop, place the mouth, then drag IN and OUT to isolate the words.'));
  let timing;
  if(generated){
    const label=el('label',{},'Replacement timing');timing=el('select',{ariaLabel:'Replacement timing'});
    timing.append(el('option',{value:'source'},'Match original timing (no retiming)'),el('option',{value:'manual'},'Choose replacement IN/OUT (no retiming)'));
    timing.value=timingMode(node);label.append(timing);panel.append(label);
    timing.onchange=()=>{node.properties.zuraDialogueTimingMode=timing.value;write(node,'timing_mode',timing.value);if(timing.value==='source'){const r=sourceRange(node);if(r){range=r;redraw();commit();}}};
  }
  const row=el('div',{className:'zura-dialogue-row'}),picture=el('div',{className:'zura-dialogue-picture'}),video=el('video',{src:media(source),controls:false,playsInline:true,preload:'auto'}),overlay=el('canvas',{width:info.width,height:info.height,'ariaLabel':'Face crop and mouth selection'}),tools=el('div',{className:'zura-dialogue-tools'});
  picture.style.maxWidth=`calc(52vh * ${info.width/info.height})`;
  panel.append(row);row.append(picture,tools);picture.append(video,overlay);
  let selection={};try{selection=JSON.parse(read(node,'selection')||'{}');}catch{}
  let box=selection.box||[0,0,info.width,info.height],mouth=selection.mouth||[info.width/2,info.height*.66,info.width*.08,info.height*.06],frame=selection.frame||0;
  let mode='crop',drag=null;const ctx=overlay.getContext('2d');
  const paint=()=>{ctx.clearRect(0,0,overlay.width,overlay.height);if(generated)return;ctx.lineWidth=Math.max(2,info.width/350);ctx.strokeStyle='#65e4c0';ctx.strokeRect(...box);ctx.strokeStyle='#ffcb75';ctx.beginPath();ctx.ellipse(...mouth,0,0,Math.PI*2);ctx.stroke();ctx.fillStyle='#65e4c0';ctx.font=`${Math.max(16,info.width/45)}px system-ui`;ctx.fillText('FACE CROP',box[0]+8,box[1]+24);};
  const cropButton=el('button',{},'Draw face crop'),mouthButton=el('button',{},'Place mouth centre');
  function setMode(value){mode=value;cropButton.setAttribute('aria-pressed',value==='crop');mouthButton.setAttribute('aria-pressed',value==='mouth');if(value==='mouth')video.currentTime=frame;}
  if(!generated){tools.append(cropButton,mouthButton);cropButton.onclick=()=>setMode('crop');mouthButton.onclick=()=>setMode('mouth');setMode('crop');}
  const number=(label,value,callback,step=.001)=>{const wrap=el('label',{},label),input=el('input',{type:'number',value,min:'0',step:String(step)});wrap.append(input);input.oninput=()=>{if(input.value==='')return;const n=Number(input.value);if(Number.isFinite(n))callback(n);};return {wrap,input};};
  const radiusX=number('Mouth radius X (source pixels)',mouth[2],v=>{mouth[2]=Math.max(1,v);paint();commit();},1),radiusY=number('Mouth radius Y (source pixels)',mouth[3],v=>{mouth[3]=Math.max(1,v);paint();commit();},1);
  if(!generated)tools.append(radiusX.wrap,radiusY.wrap);
  const play=el('button',{type:'button',ariaLabel:'Play preview',title:'Play preview'}),playWord=el('button',{type:'button'},'Play selection'),status=el('div',{className:'zura-dialogue-status'});
  const transport=el('div');transport.style.cssText='display:flex;align-items:center;gap:10px;margin-top:10px';play.style.cssText='width:40px;height:36px;display:grid;place-items:center;flex-shrink:0';transport.append(play,playWord,status);panel.append(transport);
  const playIcon='<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4v16l14-8z"/></svg>',pauseIcon='<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 4h5v16H6zM15 4h5v16h-5z"/></svg>';
  let animation=null;
  const playback=()=>{play.innerHTML=video.paused?playIcon:pauseIcon;play.setAttribute('aria-label',video.paused?'Play preview':'Pause preview');play.title=video.paused?'Play preview':'Pause preview';if(!video.paused){if(stopAt!==null&&video.currentTime>=stopAt){const end=stopAt;stopAt=null;video.pause();video.currentTime=end;return;}redrawWave();animation=requestAnimationFrame(playback);}};
  const startPlayback=async()=>{try{if(video.ended)video.currentTime=0;await video.play();}catch(error){if(error.name!=='AbortError')status.textContent='Preview could not play: '+error.message;}};
  play.innerHTML=playIcon;play.onclick=e=>{e.stopPropagation();stopAt=null;video.paused?startPlayback():video.pause();};
  video.onplay=()=>{cancelAnimationFrame(animation);playback();};video.onpause=video.onended=()=>{cancelAnimationFrame(animation);playback();};
  const startName=generated?'generated_word_start':'word_start',endName=generated?'generated_word_end':'word_end';
  let range=generated&&timingMode(node)==='source'?(sourceRange(node)||node._dialoguePreview.generated_range):null;
  range=range||[Number(read(node,startName)),Number(read(node,endName))];range=[Math.max(0,Math.min(info.duration-.001,range[0])),Math.min(info.duration,range[1])];range[1]=Math.max(range[0]+.001,range[1]);
  const wave=el('canvas',{className:'zura-dialogue-wave',width:1400,height:126,ariaLabel:generated?'Generated speech timeline, drag IN and OUT handles':'Source speech timeline, drag IN and OUT handles'});panel.append(wave);
  const times=el('div',{className:'zura-dialogue-times'});panel.append(times);
  const start=number('Selection IN (seconds)',range[0],v=>{range[0]=Math.max(0,Math.min(range[1]-.001,v));redraw();commit();}),end=number('Selection OUT (seconds)',range[1],v=>{range[1]=Math.min(info.duration,Math.max(range[0]+.001,v));redraw();commit();});times.append(start.wrap,end.wrap);
  let contextA,contextB,contextNote;
  if(!generated){contextA=number('Context IN (seconds)',read(node,'context_start'),commit);contextB=number('Context OUT (seconds)',Math.min(info.duration,read(node,'context_end')),commit);const details=el('details'),summary=el('summary',{},'Context range');summary.style.cssText='cursor:pointer;padding:10px 0';const contextTimes=el('div',{className:'zura-dialogue-times'});contextTimes.append(contextA.wrap,contextB.wrap);details.append(summary,contextTimes);panel.append(details);}
  if(!generated){contextNote=el('p');contextNote.style.cssText='color:#bacbdb;font:13px/1.5 system-ui';panel.append(contextNote);updateContextNote();}
  function updateContextNote(){if(!contextNote)return;try{const [a,b]=contextWindow(info.fps,info.frames,range[0],range[1],Number(contextA.input.value),Number(contextB.input.value));const count=Math.ceil((b-a-1)/8)*8+1;contextNote.textContent=`Processing ${ (a/info.fps).toFixed(3)}–${(b/info.fps).toFixed(3)} s · ${count} padded frames. Long context is bounded automatically; selected words keep their original timing.`;}catch(error){contextNote.textContent=error.message;}}
  const redrawWave=waveform(wave,generated?node._dialoguePreview.peaks:info.peaks,generated?node._dialoguePreview.duration:info.duration,()=>range,r=>{range=r;redraw();},t=>{video.pause();video.currentTime=t;},()=>video.currentTime,commit);
  function redraw(){start.input.value=range[0].toFixed(3);end.input.value=range[1].toFixed(3);redrawWave();}
  function commit(){updateContextNote();save.onclick();}
  let stopAt=null;playWord.onclick=()=>{video.currentTime=range[0];stopAt=range[1];startPlayback();};
  const scrub=el('input',{type:'range',min:0,max:info.duration,step:.001,value:frame,ariaLabel:'Video preview position'});panel.append(scrub);
  scrub.oninput=()=>{video.currentTime=Number(scrub.value);stopAt=null;};
  video.ontimeupdate=()=>{scrub.value=video.currentTime;redrawWave();status.textContent=`${video.currentTime.toFixed(3)} s · ${info.width} × ${info.height}`;if(stopAt!==null&&video.currentTime>=stopAt){video.pause();stopAt=null;}};
  video.onloadedmetadata=()=>{video.currentTime=Math.min(frame,info.duration);paint();};
  const point=e=>{const r=overlay.getBoundingClientRect();return [Math.round(Math.max(0,Math.min(info.width,(e.clientX-r.left)/r.width*info.width))),Math.round(Math.max(0,Math.min(info.height,(e.clientY-r.top)/r.height*info.height)))];};
  if(!generated){overlay.onpointerdown=e=>{video.pause();overlay.setPointerCapture(e.pointerId);const p=point(e);if(mode==='mouth'){mouth[0]=p[0];mouth[1]=p[1];}else{drag=p;frame=video.currentTime;}paint();};
    overlay.onpointermove=e=>{if(!drag)return;const p=point(e);box=[Math.min(drag[0],p[0]),Math.min(drag[1],p[1]),Math.max(1,Math.abs(p[0]-drag[0])),Math.max(1,Math.abs(p[1]-drag[1]))];paint();};
    overlay.onpointerup=()=>{if(drag){mouth=[box[0]+box[2]*.5,box[1]+box[3]*.65,Math.max(3,box[2]*.1),Math.max(3,box[3]*.08)];radiusX.input.value=mouth[2].toFixed(0);radiusY.input.value=mouth[3].toFixed(0);}drag=null;paint();commit();};}
  else overlay.style.pointerEvents='none';
  const actions=el('div',{className:'zura-dialogue-actions'}),cancel=el('button',{},'Cancel'),save=el('button',{className:'primary'},host?'Apply selection':'Use selection');if(!host){actions.append(cancel,save);panel.append(actions);}
  const close=()=>{cancelAnimationFrame(animation);video.pause();video.removeAttribute('src');video.load();shade.remove();};cancel.onclick=close;
  if(!host)shade.onclick=e=>{if(e.target===shade)close();};
  save.onclick=()=>{
    if(!generated&&!(Number(contextA.input.value)<=range[0]&&range[1]<=Number(contextB.input.value)&&Number(contextB.input.value)<=info.duration+.001)){status.textContent='Keep the selected words inside context, and context inside the clip.';return;}
    if(generated){
      const original=sourceRange(node),fps=connectedSource(node)?.properties?.zuraDialogueInfo?.fps||30;
      const follows=original&&range.every((v,i)=>Math.abs(v-original[i])<.001);
      const mode=follows?'source':'manual';
      if(original&&Math.abs((range[1]-range[0])-(original[1]-original[0]))>1/fps+1e-6){status.textContent='Keep replacement and original selections the same length. No retiming is applied.';return;}
      node.properties.zuraDialogueTimingMode=mode;write(node,'timing_mode',mode);timing.value=mode;
    }
    write(node,startName,range[0]);write(node,endName,range[1]);
    if(!generated){write(node,'context_start',Number(contextA.input.value));write(node,'context_end',Number(contextB.input.value));write(node,'selection',JSON.stringify({box,mouth,frame,identity:info.identity}));}
    if(host){status.textContent='Selection saved';}else close();
  };
  if(host){host.replaceChildren(shade);host._dialogueDispose=close;}else document.body.append(shade);paint();redraw();
}

const showError=error=>app.extensionManager.toast.add({severity:'error',summary:'Dialogue editor',detail:error.message,life:7000});

function hide(node,names){for(const name of names){const w=widget(node,name);if(w){w.type='hidden';w.hidden=true;w.computeSize=()=>[0,-4];w.computeLayoutSize=()=>({minHeight:0,maxHeight:0,minWidth:0});}}}
async function uploadVideo(node){
  const input=el('input',{type:'file',accept:'video/*'});
  input.onchange=async()=>{try{
    if(!input.files?.[0])return;
    const body=new FormData();body.append('image',input.files[0]);body.append('type','input');
    const response=await api.fetchApi('/upload/image',{method:'POST',body});if(!response.ok)throw new Error('Video upload failed.');
    const data=await response.json();write(node,'source',(data.subfolder?data.subfolder+'/':'')+data.name);
    const responseInfo=await api.fetchApi('/zura/dialogue/info',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:read(node,'source')})});
    const info=await responseInfo.json();if(!responseInfo.ok)throw new Error(info.error);
    write(node,'context_start',0);write(node,'context_end',info.duration);write(node,'word_start',0);write(node,'word_end',Math.min(.5,info.duration));
    await node._dialogueRefresh?.();
  }catch(error){showError(error);}};
  input.click();
}
function mountNodeEditor(node){
  const source=node.comfyClass==='ZuraDialogueSource';
  if(source&&/Select Word and Face/i.test(node.title))node.title='Zura · Select Words and Face';
  const root=el('div');node._dialogueRoot=root;root.style.cssText='width:100%;height:100%;overflow:hidden;box-sizing:border-box;';
  for(const event of ['pointerdown','pointerup','click','dblclick','keydown','wheel'])root.addEventListener(event,e=>e.stopPropagation());
  embeddedWidget(node,'dialogue_editor','zuraDialogueEditor',root,source?660:560,440);
  let revision=0;
  node._dialogueRefresh=async(generated=false)=>{
    const mine=++revision;root._dialogueDispose?.();root.replaceChildren();
    const top=el('div');top.style.cssText='display:flex;gap:8px;padding:8px;background:#18212d;border-bottom:1px solid #46566b';
    const button=(text,callback)=>{const b=el('button',{},text);b.style.cssText='font:13px system-ui;padding:7px 12px;background:#28483f;color:#f3fff9;border:1px solid #639b8c;border-radius:6px;cursor:pointer';b.onclick=callback;top.append(b);};
    if(source)button('Choose video',()=>uploadVideo(node));
    else {button('Finished video',()=>node._dialogueRefresh(false));button('Replacement words',()=>node._dialogueRefresh(true));}
    const body=el('div');body.style.cssText='height:calc(100% - 48px);overflow:auto';root.append(top,body);
    if(source||generated){
      if(!source&&!node._dialoguePreview){body.append(el('p',{},'Run once to select the generated replacement words.'));return;}
      try{await picker(node,generated,body);if(mine!==revision)body._dialogueDispose?.();}
      catch(error){if(mine===revision){const message=el('p',{},error.message);message.style.cssText='padding:16px;color:#e3eaf2;font:14px system-ui';body.replaceChildren(message);}}
    }else{
      body.style.background='#18212d';const preview=node._dialoguePreview;
      if(!preview){const p=el('p',{},'The finished video appears here after Run. Only the selected words and mouth region are replaced.');p.style.cssText='padding:16px;color:#cad8e7;font:14px system-ui;line-height:1.6';body.append(p);return;}
      const video=el('video',{src:media(preview.file),controls:true,playsInline:true,preload:'metadata'});video.style.cssText='display:block;width:100%;max-height:450px;background:#080d13;object-fit:contain';
      const caption=el('p',{},preview.retimed===false?'Original timing preserved. Use Replacement words to move the replacement selection, then Run again. No video or audio retiming is applied.':'This preview predates the timing safeguard. Run again with Match original timing.');caption.style.cssText='padding:0 14px;color:#cad8e7;font:13px system-ui;line-height:1.5';body.append(video,caption);
      const download=el('a',{href:media(preview.file),download:preview.file.split('/').pop().replace(' [output]','')},'Download finished video');download.style.cssText='display:inline-block;margin:0 14px 16px;color:#9eecd7';body.append(download);
      body._dialogueDispose=()=>{video.pause();video.removeAttribute('src');video.load();};
    }
    root._dialogueDispose=()=>body._dialogueDispose?.();
  };
  const configured=node.onConfigure;node.onConfigure=function(data){configured?.call(this,data);if(source&&/Select Word and Face/i.test(node.title))node.title='Zura · Select Words and Face';if(!source&&['source','manual'].includes(node.properties?.zuraDialogueTimingMode))write(node,'timing_mode',node.properties.zuraDialogueTimingMode);node._dialoguePreview=data.properties?.zuraDialoguePreview;node.setSize([Math.max(480,node.size[0]),Math.max(source?920:760,node.size[1])]);queueMicrotask(()=>{const original=source?node:connectedSource(node);if(original)syncSourceTiming(original);node._dialogueRefresh();});};
  const removed=node.onRemoved;node.onRemoved=function(...args){revision++;root._dialogueDispose?.();removed?.apply(this,args);};
  if(source){
    const file=widget(node,'source'),previous=file.callback;file.callback=function(v){previous?.call(this,v);write(node,'selection','{}');node._dialogueRefresh();};
    hide(node,['selection','word_start','word_end','context_start','context_end','render_size','stabilize_crop']);
    const executed=node.onExecuted;node.onExecuted=function(message){executed?.call(this,message);const info=message.zura_dialogue_source?.[0];if(info){node.properties.zuraDialogueInfo={fps:info.fps,frames:info.frames};node.properties.zuraDialoguePrepared=info;syncSourceTiming(node);}};
  }else{
    hide(node,['generated_word_start','generated_word_end','timing_mode']);
    const executed=node.onExecuted;node.onExecuted=function(message){executed?.call(this,message);if(message.zura_dialogue?.[0]){node._dialoguePreview=message.zura_dialogue[0];node.properties.zuraDialoguePreview=node._dialoguePreview;node._dialogueRefresh();}};
  }
  node.setSize([480,source?920:760]);queueMicrotask(()=>node._dialogueRefresh());
}
function decorateRender(node){
  if(node._dialogueRenderUI||!node.subgraph?.name?.startsWith('LTX Dub-It'))return;
  const prompt=widget(node,'text'),seed=widget(node,'noise_seed');if(!prompt||!seed)return;node._dialogueRenderUI=true;
  const parsed=String(prompt.value).match(/^(.*saying:\s*")([^"]*)(".*)$/s);
  const previous=node.properties.zuraDialogueDirection;
  const state={sentence:parsed?parsed[2]:(previous?.sentence??previous?.context?.replaceAll('{words}',previous.words||'')??''),prefix:parsed?parsed[1]:(previous?.prefix||'A person speaks naturally in the voice and accent of the reference audio, saying: "'),suffix:parsed?parsed[3]:(previous?.suffix||'"')};
  node.properties.zuraDialogueDirection=state;
  for(const w of node.widgets||[]){w.hidden=true;w.computeSize=()=>[0,-4];w.computeLayoutSize=()=>({minHeight:0,maxHeight:0,minWidth:0});if(w.element)w.element.style.display='none';}
  const root=el('div');root.style.cssText='padding:16px;box-sizing:border-box;width:100%;height:100%;background:#18212d;color:#e3eaf2;border-radius:10px;font:13px system-ui;overflow:auto';
  const apply=()=>{prompt.value=state.prefix+state.sentence.trim()+state.suffix;prompt.callback?.(prompt.value);node.graph?.setDirtyCanvas(true,true);};
  const label=el('label',{},'Replacement phrase');label.style.cssText='display:grid;gap:8px;font-weight:600';
  const text=el('textarea',{value:state.sentence,ariaLabel:'Replacement phrase',placeholder:'Type the full phrase as it should be spoken.',rows:4});text.style.cssText='box-sizing:border-box;width:100%;min-height:120px;resize:vertical;font:17px/1.5 system-ui;padding:12px;background:#101721;color:#f0f5fa;border:1px solid #83bda9;border-radius:7px';
  text.oninput=()=>{state.sentence=text.value;apply();};label.append(text);root.append(label);
  const help=el('p',{},'Type the full phrase, including the replacement words. This gives the model delivery context. Only the words selected on the timelines and their mouth movement are inserted.');help.style.cssText='font-weight:400;line-height:1.6;color:#bacbdb';root.append(help);
  const seedLabel=el('label',{},'Seed');seedLabel.style.cssText='display:grid;gap:8px;margin-top:14px';const input=el('input',{type:'number',min:0,step:1,value:seed.value,ariaLabel:'Dialogue seed'});input.style.cssText='font:14px system-ui;background:#101721;color:#f0f5fa;border:1px solid #61768c;border-radius:6px;padding:8px;width:100%;box-sizing:border-box';
  input.onchange=()=>{if(Number.isSafeInteger(Number(input.value))){seed.value=Number(input.value);seed.callback?.(seed.value);node.graph?.setDirtyCanvas(true,true);}};seedLabel.append(input);root.append(seedLabel);
  const sizeWidget=()=>widget((app.rootGraph||app.graph)._nodes.find(n=>n.comfyClass==='ZuraDialogueSource'),'render_size');
  const qualityLabel=el('label',{},'Face detail');qualityLabel.style.cssText='display:grid;gap:8px;margin-top:14px';
  const quality=el('select',{ariaLabel:'Face detail'});quality.style.cssText=input.style.cssText;
  for(const [value,title] of [[384,'Preview · up to 768 px'],[512,'Quality · up to 1024 px'],[640,'High detail · up to 1280 px'],[768,'Maximum detail · up to 1536 px']])quality.append(el('option',{value},title));
  quality.value=String(sizeWidget()?.value||512);
  quality.onchange=()=>{const w=sizeWidget();if(w){w.value=Number(quality.value);w.callback?.(w.value);node.graph?.setDirtyCanvas(true,true);}};
  qualityLabel.append(quality);root.append(qualityLabel);
  const cropLabel=el('label',{},'Face reference');cropLabel.style.cssText=qualityLabel.style.cssText;
  const crop=el('select',{ariaLabel:'Face reference'});crop.style.cssText=input.style.cssText;
  crop.append(el('option',{value:'tracked'},'Follow face'),el('option',{value:'fixed'},'Fixed crop'));
  const cropWidget=()=>widget((app.rootGraph||app.graph)._nodes.find(n=>n.comfyClass==='ZuraDialogueSource'),'stabilize_crop');
  crop.value=cropWidget()?.value?'tracked':'fixed';
  crop.onchange=()=>{const w=cropWidget();if(w){w.value=crop.value==='tracked';w.callback?.(w.value);node.graph?.setDirtyCanvas(true,true);}};
  cropLabel.append(crop);root.append(cropLabel);
  requestAnimationFrame(()=>{quality.value=String(sizeWidget()?.value||512);crop.value=cropWidget()?.value?'tracked':'fixed';});
  const note=el('p',{},'The face fits the selected longest edge automatically, with padding to preserve its proportions. LTX uses 8 base steps + 3 refinement steps, then downsamples into the original. Long context ranges are bounded around your selected words. Larger detail uses more memory. The finished video keeps its original size and timing.');note.style.cssText='line-height:1.6;color:#bacbdb';root.append(note);
  for(const event of ['pointerdown','pointerup','click','dblclick','keydown','wheel'])root.addEventListener(event,e=>e.stopPropagation());
  embeddedWidget(node,'dialogue_direction','zuraDialogueDirection',root,640,300);
  node.setSize([Math.max(340,node.size[0]),Math.max(960,node.size[1])]);
}
app.registerExtension({name:'Zura.DialogueEditor',nodeCreated(node){
  if(['ZuraDialogueSource','ZuraDialogueFinish'].includes(node.comfyClass))mountNodeEditor(node);
  else {const before=node.onConfigure;node.onConfigure=function(data){before?.call(this,data);decorateRender(node);};queueMicrotask(()=>decorateRender(node));}
}});

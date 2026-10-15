import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { transcriptWords, wordsInRange, phraseEditor, wordSelector, transcriptStyle } from './dialogue_transcript.js';

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
function defaultMouth(box){const[x,y,w,h]=box;return [x+w*.5,y+h*.65,Math.max(4,w*.13),Math.max(4,h*.11)];}
function mouthSizeValid(mouth,box){return mouth[2]>=Math.max(2,box[2]*.04)&&mouth[3]>=Math.max(2,box[3]*.04);}
function syncTranscript(source,words=source.properties?.zuraDialogueTranscript?.words,info=source.properties?.zuraDialogueInfo){
  if(!words?.length||!info?.fps)return;
  const cached=source.properties.zuraDialogueTranscript;if(cached&&cached.source!==read(source,'source'))return;
  let bounds;try{bounds=contextWindow(info.fps,info.frames,Number(read(source,'word_start')),Number(read(source,'word_end')),Number(read(source,'context_start')),Number(read(source,'context_end'))).map(v=>v/info.fps);}catch{return;}
  const phrase=wordsInRange(words,bounds),data={key:JSON.stringify([read(source,'source'),cached?.identity||info.identity,...bounds]),text:phrase.map(w=>w.text).join(' '),words:phrase,range:[Number(read(source,'word_start')),Number(read(source,'word_end'))]};
  for(const target of source.graph?._nodes||[])if(target._dialoguePhraseUI&&connectedSource(target)===source)target._dialoguePhraseUI.update(data);
}
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

function mouthSelectionConfirmed(selection,box){
  if(selection.mouth_confirmed===false||!selection.mouth)return false;
  const [x,y,w,h]=box,guess=[x+w*.5,y+h*.65,Math.max(3,w*.1),Math.max(3,h*.08)];
  return selection.mouth_confirmed===true||!selection.mouth.every((v,i)=>Math.abs(v-guess[i])<=.01);
}
function shiftReplacement(range,edge,value,duration,length){
  const start=Math.max(0,Math.min(duration-length,edge?value-length:value));
  return [start,start+length];
}
export function waveform(canvas,peaks,duration,getRange,setRange,seek,getPlayhead=()=>0,commit=()=>{},getLockedDuration=()=>null){
  const ctx=canvas.getContext('2d');let active=null;
  const draw=()=>{
    const [start,end]=getRange(),w=canvas.width,h=canvas.height,top=25,bottom=h-24,mid=(top+bottom)/2;
    const reference=canvas.dataset?.selectionMode==='reference';
    ctx.fillStyle='#101721';ctx.fillRect(0,0,w,h);ctx.fillStyle=reference?'#594727':'#244d45';ctx.fillRect(start/duration*w,top,(end-start)/duration*w,bottom-top);
    const max=Math.max(.02,...peaks);ctx.strokeStyle='#b9c9d8';ctx.beginPath();
    peaks.forEach((v,i)=>{const x=i/peaks.length*w,amplitude=v/max*(bottom-top)*.42;ctx.moveTo(x,mid-amplitude);ctx.lineTo(x,mid+amplitude);});ctx.stroke();
    ctx.font='16px system-ui';ctx.fillStyle='#b9c9d8';ctx.textAlign='center';
    const tick=duration>10?Math.ceil(duration/8):.5;
    for(let t=0;t<=duration;t+=tick){const x=t/duration*w;ctx.fillRect(x,bottom,1,6);ctx.fillText(t.toFixed(1)+'s',Math.max(22,Math.min(w-22,x)),h-3);}
    for(const [time,label] of [[start,'IN'],[end,'OUT']]){const x=time/duration*w;ctx.fillStyle=reference?'#ffd18a':'#8de6c9';ctx.fillRect(x-2,22,4,bottom-22);const labelX=Math.max(15,Math.min(w-15,x));ctx.fillRect(labelX-15,1,30,22);ctx.fillStyle='#10251e';ctx.font='bold 13px system-ui';ctx.fillText(label,labelX,17);}
    const x=getPlayhead()/duration*w;ctx.fillStyle='#ffd089';ctx.fillRect(x-1,25,2,bottom-25);
  };
  const time=e=>Math.max(0,Math.min(duration,(e.clientX-canvas.getBoundingClientRect().left)/canvas.getBoundingClientRect().width*duration));
  function hit(e){const t=time(e),[a,b]=getRange(),radius=14/canvas.getBoundingClientRect().width*duration;return Math.min(Math.abs(t-a),Math.abs(t-b))<=radius?(Math.abs(t-a)<Math.abs(t-b)?0:1):null;}
  canvas.onpointerdown=e=>{e.preventDefault();e.stopPropagation();active=hit(e);canvas.setPointerCapture(e.pointerId);if(active===null){seek(time(e));draw();}else canvas.style.cursor='grabbing';};
  canvas.onpointermove=e=>{e.stopPropagation();if(active===null){canvas.style.cursor=hit(e)===null?'crosshair':'ew-resize';return;}const range=[...getRange()],t=time(e);const length=getLockedDuration();if(length!==null){setRange(shiftReplacement(range,active,t,duration,length));}else{range[active]=active?Math.max(range[0]+.001,t):Math.min(range[1]-.001,t);setRange(range);}seek(t);draw();};
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
  if(!source)throw new Error(generated?'Run once to preview the replacement take.':'Choose a video to begin.');
  const response=await api.fetchApi('/zura/dialogue/info',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source})});
  const info=await response.json();if(!response.ok)throw Error(info.error);
  if(!generated){node.properties.zuraDialogueInfo={fps:info.fps,frames:info.frames};syncSourceTiming(node);}
  let alive=true,animation=null,stopAt=null,wordUI=null,words=[];
  const shade=el('div',{className:host?'zura-dialogue-inline':'zura-dialogue-shade'}),panel=el('section',{className:'zura-dialogue-panel zura-transcript'});
  shade.append(transcriptStyle(),panel);
  const style=el('style');style.textContent=`
    .zura-dialogue-inline{width:100%;height:100%;overflow:auto;box-sizing:border-box;background:#18212d;color:#e5edf5;font:13px system-ui}
    .zura-dialogue-shade{position:fixed;inset:0;z-index:100000;background:#05080dd9;display:grid;place-items:center}
    .zura-dialogue-panel{padding:14px;box-sizing:border-box;width:100%;overflow:auto}.zura-dialogue-shade .zura-dialogue-panel{background:#18212d;max-width:1000px;max-height:94vh;border-radius:10px}
    .zura-dialogue-panel h2{font-size:18px;margin:0 0 7px}.zura-dialogue-panel h3{margin-top:18px}
    .zura-dialogue-picture{position:relative;background:#080d13;min-width:0;flex:1;border-radius:6px;overflow:hidden;line-height:0;max-width:100%}
    .zura-dialogue-picture video{display:block;width:100%;max-height:290px;object-fit:contain}
    .zura-dialogue-picture canvas{position:absolute;touch-action:none}
    .zura-dialogue-row{display:flex;gap:10px;align-items:start}.zura-dialogue-tools{width:135px;flex-shrink:0;display:grid;gap:8px}
    .zura-dialogue-tools button{font-size:12px}.zura-dialogue-tools button[aria-pressed=true]{background:#28584d;border-color:#9de8cf}
    .zura-dialogue-panel .zura-mouth-note{font-size:11px;line-height:1.5;margin:0}
    .zura-dialogue-panel input{font:13px system-ui;color:#edf4fa;background:#101923;border:1px solid #52677b;border-radius:5px;box-sizing:border-box;padding:7px;min-width:0;width:100%;font-variant-numeric:tabular-nums}
    .zura-dialogue-panel input:focus-visible{outline:2px solid #a4f0d6;outline-offset:2px}
    .zura-dialogue-times{display:grid;grid-template-columns:1fr 1fr;gap:10px}.zura-dialogue-times label{font-size:12px;font-weight:400}
    .zura-dialogue-wave{display:block;width:100%;height:73px;border:1px solid #52677b;border-radius:5px;margin:8px 0;touch-action:none}
    .zura-dialogue-panel .zura-reference-wave{border-color:#ac8c51}
    .zura-dialogue-transport{display:flex;align-items:center;gap:8px;margin:10px 0;flex-wrap:wrap}.zura-dialogue-transport button{min-height:34px}
    .zura-dialogue-panel .zura-range-summary{font-variant-numeric:tabular-nums;color:#d4e2ed;margin:4px 0;font-size:12px}
    .zura-dialogue-panel [hidden]{display:none!important}.zura-dialogue-panel details{margin-top:12px}.zura-dialogue-panel summary{cursor:pointer;color:#bfd1df}
    .zura-dialogue-panel .zura-error{color:#ffc1b8}.zura-dialogue-panel [role=status]{overflow-wrap:anywhere}
  `;shade.append(style);
  panel.append(el('h2',{},generated?'Align replacement words':'Choose the clip and words'));
  panel.append(el('p',{},generated?'Move the selection to the words you want to insert. Its duration stays matched to the original.':'Trim the reference clip, select the words to replace, then edit the recognised phrase in the next node.'));
  const editorTabs=el('div',{className:'zura-dialogue-transport'}),referenceTab=el('button',{type:'button'},'Clip and face'),wordsTab=el('button',{type:'button'},'Select words'),referencePanel=el('section'),wordPanel=el('section');
  if(!generated){editorTabs.append(referenceTab,wordsTab);panel.append(editorTabs);}
  let range=generated&&timingMode(node)==='source'?(sourceRange(node)||node._dialoguePreview.generated_range):null;
  range=range||[Number(read(node,generated?'generated_word_start':'word_start')),Number(read(node,generated?'generated_word_end':'word_end'))];
  range=[Math.max(0,Math.min(info.duration-.001,range[0])),Math.min(info.duration,range[1])];range[1]=Math.max(range[0]+.001,range[1]);
  let reference=[Number(read(node,'context_start'))||0,Math.min(info.duration,Number(read(node,'context_end'))||info.duration)];
  if(!generated){try{reference=contextWindow(info.fps,info.frames,...range,...reference).map(v=>Math.min(info.duration,v/info.fps));}catch{}}
  let selection={};try{selection=JSON.parse(read(node,'selection')||'{}');}catch{}
  let box=selection.box||[0,0,info.width,info.height],mouth=selection.mouth||defaultMouth(box),frame=Number(selection.frame)||0;
  let mouthConfirmed=mouthSelectionConfirmed(selection,box)&&mouthSizeValid(mouth,box),mode='crop',drag=null,placingMouth=false,snapshot=null;
  const video=el('video',{src:media(source),controls:false,playsInline:true,preload:'auto'}),picture=el('div',{className:'zura-dialogue-picture'}),overlay=el('canvas',{width:info.width,height:info.height,ariaLabel:'Draw face crop or mouth area'}),tools=el('div',{className:'zura-dialogue-tools'}),row=el('div',{className:'zura-dialogue-row'});
  picture.append(video,overlay);row.append(picture);if(!generated)row.append(tools);panel.append(row);
  // Overlay the actual rendered picture, including portrait/letterboxed previews.
  function sizeOverlay(){const r=video.getBoundingClientRect(),ratio=info.width/info.height,w=Math.min(r.width,r.height*ratio),h=w/ratio;overlay.style.cssText=`left:${(r.width-w)/2}px;top:${(r.height-h)/2}px;width:${w}px;height:${h}px`;}
  const resizeObserver=new ResizeObserver(sizeOverlay);resizeObserver.observe(video);
  const status=el('p',{className:'zura-transcript-status',role:'status'}),mouthNote=el('p',{className:'zura-mouth-note'}),ctx=overlay.getContext('2d');
  const cropButton=el('button',{type:'button'},'Draw face crop'),mouthButton=el('button',{type:'button'},'Draw mouth area'),resetMouth=el('button',{type:'button'},'Reset mouth size');
  function anchorValid(){if(generated)return true;try{const[a,b]=contextWindow(info.fps,info.frames,...range,...reference);return frame*info.fps>=a-.5&&frame*info.fps<b;}catch{return false;}}
  function updateMouthNote(){const valid=mouthConfirmed&&mouthSizeValid(mouth,box)&&anchorValid();mouthNote.textContent=!anchorValid()?'Reference frame is outside this clip. Pause inside it and draw the mouth again.':!mouthSizeValid(mouth,box)?'Mouth area is too small. Reset its size, then place it over both lips.':valid?'Amber oval: replaced mouth area. Include both lips and open-mouth movement.':'Pause on a clear face. Click the lips or drag around the whole mouth.';mouthNote.style.color=valid?'#ffe1a4':'#ffc1b8';}
  function setMode(value){mode=value;cropButton.setAttribute('aria-pressed',value==='crop');mouthButton.setAttribute('aria-pressed',value==='mouth');}
  function paint(){sizeOverlay();ctx.clearRect(0,0,overlay.width,overlay.height);if(generated)return;ctx.lineWidth=Math.max(2,info.width/350);ctx.strokeStyle='#91e7cb';ctx.strokeRect(...box);ctx.strokeStyle=mouthConfirmed&&anchorValid()?'#ffcb75':'#ff9c90';ctx.fillStyle='#ffcb7528';ctx.beginPath();ctx.ellipse(...mouth,0,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.beginPath();ctx.moveTo(mouth[0]-5,mouth[1]);ctx.lineTo(mouth[0]+5,mouth[1]);ctx.moveTo(mouth[0],mouth[1]-5);ctx.lineTo(mouth[0],mouth[1]+5);ctx.stroke();}
  const number=(title,value,changed)=>{const wrap=el('label',{},title),input=el('input',{type:'number',value,min:0,max:info.duration,step:.001,ariaLabel:title});input.onchange=input.oninput=()=>{if(input.value!==''&&Number.isFinite(Number(input.value)))changed(Number(input.value));};wrap.append(input);return {wrap,input};};
  if(!generated){
    tools.append(cropButton,mouthButton,resetMouth,mouthNote);cropButton.onclick=()=>setMode('crop');mouthButton.onclick=()=>{setMode('mouth');if(anchorValid())video.currentTime=frame;};
    resetMouth.onclick=()=>{const defaults=defaultMouth(box);mouth=[mouth[0],mouth[1],defaults[2],defaults[3]];mouthConfirmed=false;setMode('mouth');paint();updateMouthNote();commit();};setMode('crop');updateMouthNote();
  }else overlay.style.pointerEvents='none';
  const transport=el('div',{className:'zura-dialogue-transport'}),play=el('button',{type:'button',ariaLabel:'Play preview',title:'Play preview'}),playSelected=el('button',{type:'button'},'Play selected words');
  const playIcon='<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4v16l14-8z"/></svg>',pauseIcon='<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 4h5v16H6zM15 4h5v16h-5z"/></svg>';
  play.innerHTML=playIcon;play.style.cssText='width:40px;display:grid;place-items:center';transport.append(play,playSelected);
  if(!generated){const playReference=el('button',{type:'button'},'Play reference clip');playReference.onclick=()=>playRange(reference);transport.append(playReference);}panel.append(transport);
  const scrub=el('input',{type:'range',min:0,max:info.duration,step:.001,value:Math.min(Math.max(frame,reference[0]),reference[1]||info.duration),ariaLabel:'Video preview position'});scrub.oninput=()=>{video.pause();video.currentTime=Number(scrub.value);stopAt=null;};panel.append(scrub);
  const timeLabel=el('p',{className:'zura-range-summary'});panel.append(timeLabel);
  let refWave,refA,refB,drawReference=()=>{};
  if(!generated){
    referencePanel.append(el('h3',{},'Reference clip'),el('p',{},'Drag amber IN/OUT handles. This footage supplies the voice and video context.'));
    refWave=el('canvas',{width:1400,height:126,className:'zura-dialogue-wave zura-reference-wave',ariaLabel:'Reference clip timeline, drag IN and OUT'});refWave.dataset.selectionMode='reference';referencePanel.append(refWave);
    const times=el('div',{className:'zura-dialogue-times'});
    refA=number('Reference IN',reference[0],v=>changeReference([Math.max(0,Math.min(reference[1]-.001,v)),reference[1]]));
    refB=number('Reference OUT',reference[1],v=>changeReference([reference[0],Math.max(reference[0]+.001,Math.min(info.duration,v))]));times.append(refA.wrap,refB.wrap);referencePanel.append(times);
    drawReference=waveform(refWave,info.peaks,info.duration,()=>reference,changeReference,seek,()=>video.currentTime,commit);
  }else{
    const timing=el('select',{ariaLabel:'Replacement timing'});timing.append(el('option',{value:'source'},'Use original timestamps'),el('option',{value:'manual'},'Move replacement selection'));timing.value=timingMode(node);timing.onchange=()=>{write(node,'timing_mode',timing.value);node.properties.zuraDialogueTimingMode=timing.value;if(timing.value==='source'){range=sourceRange(node)||range;redraw();commit();}};panel.append(timing);
  }
  wordPanel.append(el('h3',{},generated?'Replacement words':'Words to replace'),el('p',{},generated?'Drag either handle to move the replacement without changing its duration.':'Select words below or drag the green handles. Only this interval is replaced.'));
  const wave=el('canvas',{className:'zura-dialogue-wave',width:1400,height:126,ariaLabel:generated?'Replacement words timeline, move selection':'Words to replace timeline, drag IN and OUT'});wordPanel.append(wave);
  const times=el('div',{className:'zura-dialogue-times'}),a=number('Words IN',range[0],v=>setWords([Math.max(0,Math.min(range[1]-.001,v)),range[1]])),b=number('Words OUT',range[1],v=>setWords([range[0],Math.max(range[0]+.001,Math.min(info.duration,v))]));times.append(a.wrap,b.wrap);wordPanel.append(times);
  const replacementLength=()=>generated?(sourceRange(node)?.reduce((x,y)=>y-x)??range[1]-range[0]):null;
  if(generated){a.input.onchange=()=>{range=shiftReplacement(range,0,Number(a.input.value),info.duration,replacementLength());redraw();commit();};b.input.onchange=()=>{range=shiftReplacement(range,1,Number(b.input.value),info.duration,replacementLength());redraw();commit();};}
  let drawWords=()=>{};
  function rebuildWordWave(){const offset=generated?0:reference[0],duration=generated?info.duration:reference[1]-reference[0],peaks=generated?node._dialoguePreview.peaks:info.peaks.slice(Math.floor(offset/info.duration*info.peaks.length),Math.ceil((offset+duration)/info.duration*info.peaks.length));drawWords=waveform(wave,peaks,duration,()=>range.map(t=>t-offset),r=>{range=r.map(t=>t+offset);redraw();},t=>seek(t+offset),()=>video.currentTime-offset,commit,replacementLength);}
  const transcriptHost=el('div'),transcriptStatus=el('p',{className:'zura-transcript-status',role:'status'},'Recognising words locally with Parakeet…'),retry=el('button',{type:'button'},'Retry Parakeet');retry.hidden=true;wordPanel.append(transcriptStatus,transcriptHost,retry);panel.append(referencePanel,wordPanel,status);
  const contextNote=el('p',{className:'zura-range-summary'});if(!generated)panel.append(contextNote);
  function seek(time){video.pause();video.currentTime=time;}
  function changeReference(next){const max=240/info.fps;if(next[1]-next[0]>max){next=next[0]!==reference[0]?[Math.max(0,next[1]-max),next[1]]:[next[0],Math.min(info.duration,next[0]+max)];}reference=[Math.max(0,next[0]),Math.min(info.duration,next[1])];range=[Math.max(reference[0],range[0]),Math.min(reference[1],range[1])];if(range[1]<=range[0])range=[reference[0],Math.min(reference[1],reference[0]+.5)];rebuildWordWave();redraw();commit();}
  function setWords(next){range=[Math.max(0,next[0]),Math.min(info.duration,next[1])];if(!generated&&(range[0]<reference[0]||range[1]>reference[1])){reference=[Math.max(0,range[0]-.5),Math.min(info.duration,range[1]+.5)];rebuildWordWave();}redraw();commit();}
  function redraw(){a.input.value=range[0].toFixed(3);b.input.value=range[1].toFixed(3);if(refA){refA.input.value=reference[0].toFixed(3);refB.input.value=reference[1].toFixed(3);}drawWords();drawReference();wordUI?.update(video.currentTime);updateMouthNote();paint();}
  function commit(){
    if(!alive)return;
    if(!generated){
      try{const window=contextWindow(info.fps,info.frames,...range,...reference).map(v=>Math.min(info.duration,v/info.fps));contextNote.classList.remove('zura-error');contextNote.textContent=`Effective reference: ${window[0].toFixed(3)}–${window[1].toFixed(3)} s · ${Math.ceil(((window[1]-window[0])*info.fps-1)/8)*8+1} padded frames. Source timing is preserved.`;}
      catch(error){contextNote.textContent=error.message;contextNote.classList.add('zura-error');status.textContent=error.message;return;}
      write(node,'word_start',range[0]);write(node,'word_end',range[1]);write(node,'context_start',reference[0]);write(node,'context_end',reference[1]);
      write(node,'selection',JSON.stringify({box,mouth,frame,identity:info.identity,mouth_confirmed:mouthConfirmed&&mouthSizeValid(mouth,box)&&anchorValid()}));
      syncTranscript(node,words,info);
      status.textContent=mouthConfirmed&&anchorValid()?'Selection saved. Edit the phrase in the next node.':'Place the mouth on the lips inside the reference clip before Run.';
    }else{
      const original=sourceRange(node),follows=original&&range.every((v,i)=>Math.abs(v-original[i])<.001);write(node,'timing_mode',follows?'source':'manual');node.properties.zuraDialogueTimingMode=follows?'source':'manual';write(node,'generated_word_start',range[0]);write(node,'generated_word_end',range[1]);status.textContent='Selection saved. Run again to apply this blend; the unchanged take is reused.';
    }
  }
  const point=e=>{const r=overlay.getBoundingClientRect();return [Math.round(Math.max(0,Math.min(info.width,(e.clientX-r.left)/r.width*info.width))),Math.round(Math.max(0,Math.min(info.height,(e.clientY-r.top)/r.height*info.height)))];};
  if(!generated){
    overlay.onpointerdown=e=>{e.preventDefault();video.pause();overlay.setPointerCapture(e.pointerId);snapshot={box:[...box],mouth:[...mouth],frame,confirmed:mouthConfirmed};drag=point(e);placingMouth=mode==='mouth';frame=video.currentTime;if(placingMouth){if(!mouthSizeValid(mouth,box))mouth=defaultMouth(box);mouth[0]=drag[0];mouth[1]=drag[1];mouthConfirmed=true;}paint();};
    overlay.onpointermove=e=>{if(!drag)return;const p=point(e);if(placingMouth){if(Math.hypot(p[0]-drag[0],p[1]-drag[1])>8){mouth=[(p[0]+drag[0])/2,(p[1]+drag[1])/2,Math.max(1,Math.abs(p[0]-drag[0])/2),Math.max(1,Math.abs(p[1]-drag[1])/2)];}}else box=[Math.min(drag[0],p[0]),Math.min(drag[1],p[1]),Math.max(1,Math.abs(p[0]-drag[0])),Math.max(1,Math.abs(p[1]-drag[1]))];paint();};
    overlay.onpointerup=e=>{if(!drag)return;
      if(!placingMouth&&(box[2]<32||box[3]<32)){box=snapshot.box;mouth=snapshot.mouth;frame=snapshot.frame;mouthConfirmed=snapshot.confirmed;status.textContent='Drag a crop around the whole face. A click keeps the previous crop.';}
      else if(!placingMouth){const[x,y,w,h]=box;mouthConfirmed=snapshot.confirmed&&Math.abs(frame-snapshot.frame)<=.5/info.fps&&x<=mouth[0]&&mouth[0]<=x+w&&y<=mouth[1]&&mouth[1]<=y+h&&mouthSizeValid(mouth,box);if(!mouthConfirmed)mouth=defaultMouth(box);setMode('mouth');}
      if(placingMouth&&!mouthSizeValid(mouth,box)){mouthConfirmed=false;status.textContent='Mouth area is too small. Draw around both lips or reset its size.';}
      drag=null;placingMouth=false;if(overlay.hasPointerCapture(e.pointerId))overlay.releasePointerCapture(e.pointerId);redraw();commit();};
    overlay.onpointercancel=()=>{if(snapshot){box=snapshot.box;mouth=snapshot.mouth;frame=snapshot.frame;mouthConfirmed=snapshot.confirmed;}drag=null;placingMouth=false;redraw();};
  }
  async function startPlayback(){try{await video.play();}catch(error){if(error.name!=='AbortError')status.textContent='Preview could not play: '+error.message;}}
  function playRange(bounds){video.currentTime=bounds[0];stopAt=bounds[1];startPlayback();}
  function playback(){play.innerHTML=video.paused?playIcon:pauseIcon;play.setAttribute('aria-label',video.paused?'Play preview':'Pause preview');if(!video.paused){drawWords();drawReference();wordUI?.update(video.currentTime);if(stopAt!==null&&video.currentTime>=stopAt){const end=stopAt;stopAt=null;video.pause();video.currentTime=end;return;}animation=requestAnimationFrame(playback);}}
  play.onclick=()=>{stopAt=null;video.paused?startPlayback():video.pause();};playSelected.onclick=()=>playRange(range);video.onplay=()=>{cancelAnimationFrame(animation);playback();};video.onpause=video.onended=()=>{cancelAnimationFrame(animation);playback();};
  video.ontimeupdate=()=>{scrub.value=video.currentTime;timeLabel.textContent=`${video.currentTime.toFixed(3)} s / ${info.duration.toFixed(3)} s`;drawWords();drawReference();wordUI?.update(video.currentTime);if(stopAt!==null&&video.currentTime>=stopAt){stopAt=null;video.pause();}};
  video.onloadedmetadata=()=>{video.currentTime=Math.min(Math.max(frame,generated?0:reference[0]),generated?info.duration:reference[1]-.001);paint();};
  async function recognise(){retry.hidden=true;transcriptStatus.classList.remove('zura-transcript-error');transcriptStatus.textContent='Recognising words locally with Parakeet…';try{const result=await transcriptWords(api.fetchApi.bind(api),source,info.identity);if(!alive||(!generated&&read(node,'source')!==source))return;words=result;
      if(generated){wordUI=wordSelector(words,()=>range,r=>{const duration=replacementLength();range=shiftReplacement(range,0,r[0],info.duration,duration);redraw();commit();},seek);}
      else{node.properties.zuraDialogueTranscript={source,identity:info.identity,words};wordUI=wordSelector(words,()=>range,setWords,seek);syncTranscript(node,words,info);}
      transcriptHost.replaceChildren(wordUI.element);transcriptStatus.textContent='Parakeet transcript ready. You can edit recognition mistakes in the phrase box.';
    }catch(error){if(alive){transcriptStatus.textContent=error.message;transcriptStatus.classList.add('zura-transcript-error');retry.hidden=false;}}}
  retry.onclick=recognise;
  function editorTab(value){if(generated)return;node.properties.zuraDialogueEditorTab=value;referencePanel.hidden=value!=='reference';wordPanel.hidden=value!=='words';tools.hidden=value==='words';overlay.style.pointerEvents=value==='words'?'none':'';referenceTab.setAttribute('aria-pressed',value==='reference');wordsTab.setAttribute('aria-pressed',value==='words');requestAnimationFrame(paint);}
  referenceTab.onclick=()=>editorTab('reference');wordsTab.onclick=()=>editorTab('words');editorTab(node.properties.zuraDialogueEditorTab||'reference');
  const close=()=>{alive=false;cancelAnimationFrame(animation);resizeObserver.disconnect();video.pause();video.removeAttribute('src');video.load();shade.remove();};
  if(host){host.replaceChildren(shade);host._dialogueDispose=close;}else{const done=el('button',{type:'button'},'Done');done.onclick=()=>{commit();close();};panel.append(done);document.body.append(shade);}
  rebuildWordWave();redraw();recognise();
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
  embeddedWidget(node,'dialogue_editor','zuraDialogueEditor',root,source?900:650,440);
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
      const caption=el('p',{},preview.retimed===false?'Preview the speech and lips. If the generated delivery starts earlier or later, open Replacement words and drag either handle to move the selection, then Run again. Both handles move together; duration stays unchanged.':'This preview predates the timing safeguard. Check the replacement selection and Run again.');caption.style.cssText='padding:0 14px;color:#cad8e7;font:13px system-ui;line-height:1.5';body.append(video,caption);
      const download=el('a',{href:media(preview.file),download:preview.file.split('/').pop().replace(' [output]','')},'Download finished video');download.style.cssText='display:inline-block;margin:0 14px 16px;color:#9eecd7';body.append(download);
      body._dialogueDispose=()=>{video.pause();video.removeAttribute('src');video.load();};
    }
    root._dialogueDispose=()=>body._dialogueDispose?.();
  };
  const configured=node.onConfigure;node.onConfigure=function(data){configured?.call(this,data);if(source&&/Select Word and Face/i.test(node.title))node.title='Zura · Select Words and Face';if(!source&&['source','manual'].includes(node.properties?.zuraDialogueTimingMode))write(node,'timing_mode',node.properties.zuraDialogueTimingMode);node._dialoguePreview=data.properties?.zuraDialoguePreview;node.setSize([Math.max(480,node.size[0]),Math.max(source?1120:860,node.size[1])]);queueMicrotask(()=>{const original=source?node:connectedSource(node);if(original)syncSourceTiming(original);node._dialogueRefresh();});};
  const removed=node.onRemoved;node.onRemoved=function(...args){revision++;root._dialogueDispose?.();removed?.apply(this,args);};
  if(source){
    const file=widget(node,'source'),previous=file.callback;file.callback=function(v){previous?.call(this,v);write(node,'selection','{}');delete node.properties.zuraDialogueTranscript;node._dialogueRefresh();};
    hide(node,['selection','word_start','word_end','context_start','context_end','render_size','stabilize_crop']);
    const executed=node.onExecuted;node.onExecuted=function(message){executed?.call(this,message);const info=message.zura_dialogue_source?.[0];if(info){node.properties.zuraDialogueInfo={fps:info.fps,frames:info.frames};node.properties.zuraDialoguePrepared=info;syncSourceTiming(node);}};
  }else{
    hide(node,['generated_word_start','generated_word_end','timing_mode']);
    const executed=node.onExecuted;node.onExecuted=function(message){executed?.call(this,message);if(message.zura_dialogue?.[0]){node._dialoguePreview=message.zura_dialogue[0];node.properties.zuraDialoguePreview=node._dialoguePreview;node._dialogueRefresh();}};
  }
  node.setSize([480,source?1120:860]);queueMicrotask(()=>node._dialogueRefresh());
}
function decorateRender(node){
  if(node._dialogueRenderUI||!node.subgraph?.name?.startsWith('LTX Dub-It'))return;
  const prompt=widget(node,'text'),seed=widget(node,'noise_seed');if(!prompt||!seed)return;node._dialogueRenderUI=true;
  const parsed=String(prompt.value).match(/^(.*saying:\s*")([^"]*)(".*)$/s);
  const previous=node.properties.zuraDialogueDirection;
  const state={...previous,edited:previous?.edited??Boolean(previous?.sentence&&previous.sentence!=='Type the complete replacement phrase here.'),sentence:parsed?parsed[2]:(previous?.sentence??previous?.context?.replaceAll('{words}',previous.words||'')??''),prefix:parsed?parsed[1]:(previous?.prefix||'A person speaks naturally in the voice and accent of the reference audio, saying: "'),suffix:parsed?parsed[3]:(previous?.suffix||'"')};
  node.properties.zuraDialogueDirection=state;
  for(const w of node.widgets||[]){w.hidden=true;w.computeSize=()=>[0,-4];w.computeLayoutSize=()=>({minHeight:0,maxHeight:0,minWidth:0});if(w.element)w.element.style.display='none';}
  const root=el('div');root.style.cssText='padding:16px;box-sizing:border-box;width:100%;height:100%;background:#18212d;color:#e3eaf2;border-radius:10px;font:13px system-ui;overflow:auto';
  const apply=()=>{prompt.value=state.prefix+state.sentence.trim()+state.suffix;prompt.callback?.(prompt.value);node.graph?.setDirtyCanvas(true,true);};
  root.append(transcriptStyle(),el('h2',{},'Edit spoken words'));
  const phraseUI=phraseEditor(state,apply);node._dialoguePhraseUI=phraseUI;root.append(phraseUI.element);
  const initialise=()=>{const source=connectedSource(node);if(source)syncTranscript(source);};queueMicrotask(initialise);
  const seedLabel=el('label',{},'Seed');seedLabel.style.cssText='display:grid;gap:8px;margin-top:14px';const input=el('input',{type:'number',min:0,step:1,value:seed.value,ariaLabel:'Dialogue seed'});input.style.cssText='font:14px system-ui;background:#101721;color:#f0f5fa;border:1px solid #61768c;border-radius:6px;padding:8px;width:100%;box-sizing:border-box';
  input.onchange=()=>{if(Number.isSafeInteger(Number(input.value))){seed.value=Number(input.value);seed.callback?.(seed.value);node.graph?.setDirtyCanvas(true,true);}};seedLabel.append(input);root.append(seedLabel);
  const sizeWidget=()=>widget(connectedSource(node),'render_size');
  const qualityLabel=el('label',{},'Face detail');qualityLabel.style.cssText='display:grid;gap:8px;margin-top:14px';
  const quality=el('select',{ariaLabel:'Face detail'});quality.style.cssText=input.style.cssText;
  for(const [value,title] of [[384,'Preview · up to 768 px'],[512,'Quality · up to 1024 px'],[640,'High detail · up to 1280 px'],[768,'Maximum detail · up to 1536 px']])quality.append(el('option',{value},title));
  quality.value=String(sizeWidget()?.value||512);
  quality.onchange=()=>{const w=sizeWidget();if(w){w.value=Number(quality.value);w.callback?.(w.value);node.graph?.setDirtyCanvas(true,true);}};
  qualityLabel.append(quality);root.append(qualityLabel);
  const cropLabel=el('label',{},'Face reference');cropLabel.style.cssText=qualityLabel.style.cssText;
  const crop=el('select',{ariaLabel:'Face reference'});crop.style.cssText=input.style.cssText;
  crop.append(el('option',{value:'tracked'},'Follow face'),el('option',{value:'fixed'},'Fixed crop'));
  const cropWidget=()=>widget(connectedSource(node),'stabilize_crop');
  crop.value=cropWidget()?.value?'tracked':'fixed';
  crop.onchange=()=>{const w=cropWidget();if(w){w.value=crop.value==='tracked';w.callback?.(w.value);node.graph?.setDirtyCanvas(true,true);}};
  cropLabel.append(crop);root.append(cropLabel);
  requestAnimationFrame(()=>{quality.value=String(sizeWidget()?.value||512);crop.value=cropWidget()?.value?'tracked':'fixed';});
  const note=el('p',{},'The face fits the selected longest edge automatically, with padding to preserve its proportions. LTX uses 8 base steps + 3 refinement steps, then downsamples into the original. Long context ranges are bounded around your selected words. Larger detail uses more memory. The finished video keeps its original size and timing. This LTX 2.5 INT8 + Dub-It 2.3 combination is experimental: voice identity and dialogue timing can vary between takes.');note.style.cssText='line-height:1.6;color:#bacbdb';root.append(note);
  for(const event of ['pointerdown','pointerup','click','dblclick','keydown','wheel'])root.addEventListener(event,e=>e.stopPropagation());
  embeddedWidget(node,'dialogue_direction','zuraDialogueDirection',root,740,300);
  node.setSize([Math.max(340,node.size[0]),Math.max(1060,node.size[1])]);
}
app.registerExtension({name:'Zura.DialogueEditor',nodeCreated(node){
  if(['ZuraDialogueSource','ZuraDialogueFinish'].includes(node.comfyClass))mountNodeEditor(node);
  else {const before=node.onConfigure;node.onConfigure=function(data){before?.call(this,data);decorateRender(node);};queueMicrotask(()=>decorateRender(node));}
}});

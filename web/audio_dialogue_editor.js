import {app} from '../../scripts/app.js';
import {api} from '../../scripts/api.js';
import {waveform,embeddedWidget} from './dialogue_editor.js';

const field=(n,k)=>n.widgets?.find(w=>w.name===k);
const get=(n,k)=>field(n,k)?.value;
const set=(n,k,v)=>{const w=field(n,k);if(w){w.value=v;w.callback?.(v);}n.graph?.setDirtyCanvas(true,true);};
const el=(tag,props={},text='')=>{const e=document.createElement(tag);Object.assign(e,props);e.textContent=text;return e;};
const media=p=>api.apiURL('/zura/audio-dialogue/media?source='+encodeURIComponent(p));
const post=async(route,data)=>{const r=await api.fetchApi('/zura/audio-dialogue/'+route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error);return v;};
const playIcon='<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4v16l14-8z"/></svg>';
const pauseIcon='<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 4h5v16H6zM15 4h5v16h-5z"/></svg>';

async function upload(n,key,refresh){
 const input=el('input',{type:'file',accept:'audio/*'});
 input.onchange=async()=>{if(!input.files?.length)return;try{const body=new FormData();body.append('image',input.files[0]);body.append('type','input');const r=await api.fetchApi('/upload/image',{method:'POST',body});if(!r.ok)throw Error('Audio upload failed');const file=await r.json();const path=(file.subfolder?file.subfolder+'/':'')+file.name;
  const info=await post('info',{source:path});set(n,key,path);
  if(key==='source'){set(n,'word_start',0);set(n,'word_end',Math.min(.5,info.duration));set(n,'reference_start',0);set(n,'reference_end',0);set(n,'source_transcript','');n.properties.zuraAudioWords=[];}
  else {set(n,'extra_transcript','');n._audioRefOpen=true;}refresh();
 }catch(e){app.extensionManager.toast.add({severity:'error',summary:'Audio editor',detail:e.message,life:7000});}};input.click();
}

function hide(n){for(const w of n.widgets||[]){w.type='hidden';w.hidden=true;w.computeSize=()=>[0,-4];w.computeLayoutSize=()=>({minHeight:0,maxHeight:0,minWidth:0});}}
function label(text,input){const l=el('label',{},text);l.append(input);return l;}
function number(n,key,text,refresh){const options=key==='seed'?{min:0,max:4294967295,step:1}:key==='pace'?{min:.5,max:2,step:.05}:key==='fade_ms'?{min:0,max:100,step:1}:{min:0,step:.001};const input=el('input',{type:'number',...options,value:get(n,key),ariaLabel:text});input.oninput=()=>{if(input.value!==''&&input.validity.valid&&Number.isFinite(Number(input.value))){set(n,key,Number(input.value));refresh?.();}};return label(text,input);}
function text(n,key,title,placeholder){const input=el('textarea',{value:get(n,key)||'',rows:3,placeholder,ariaLabel:title});input.oninput=()=>set(n,key,input.value);return label(title,input);}
function choice(n,key,title,onchange){const select=el('select',{ariaLabel:title});for(const value of field(n,key)?.options?.values||[]){select.append(el('option',{value},value));}select.value=get(n,key);select.onchange=()=>{set(n,key,select.value);onchange?.(select.value);};return label(title,select);}

function timeline(panel,info,n,source,status,words=[]){
 const aKey=source?'word_start':'generated_start',bKey=source?'word_end':'generated_end';
 let range=[Number(get(n,aKey)),Number(get(n,bKey))];
 range=[Math.max(0,Math.min(info.duration-.001,range[0])),Math.max(.001,Math.min(info.duration,range[1]))];if(range[1]<=range[0])range[1]=Math.min(info.duration,range[0]+.001);
 const audio=el('audio',{src:media(info.file),preload:'metadata'});panel.append(audio);
 let stopAt=null,animation=null;
 const row=el('div',{className:'zura-audio-row'}),play=el('button',{type:'button',ariaLabel:'Play audio',title:'Play audio'}),selected=el('button',{type:'button'},'Play selection');play.innerHTML=playIcon;row.append(play,selected);panel.append(row);
 const wave=el('canvas',{width:1600,height:150,ariaLabel:source?'Source waveform, drag IN and OUT':'Replacement waveform, drag IN and OUT'});panel.append(wave);
 const times=el('div',{className:'zura-audio-row'}),a=el('input',{type:'number',min:0,max:info.duration,step:.001,value:range[0],ariaLabel:'Selection IN'}),b=el('input',{type:'number',min:0,max:info.duration,step:.001,value:range[1],ariaLabel:'Selection OUT'});times.append(label('IN Â· seconds',a),label('OUT Â· seconds',b));panel.append(times);
 function commit(){set(n,aKey,range[0]);set(n,bKey,range[1]);if(!source){set(n,'selection_mode','Manual IN/OUT');const selector=panel.querySelector('select[aria-label="Replacement selection"]');if(selector)selector.value='Manual IN/OUT';}for(const w of wordButtons)w.button.setAttribute('aria-pressed',w.word.end>range[0]&&w.word.start<range[1]);}
 function redraw(){a.value=range[0].toFixed(3);b.value=range[1].toFixed(3);draw();}
 const draw=waveform(wave,info.peaks,info.duration,()=>range,r=>{range=r;redraw();},t=>{audio.pause();audio.currentTime=t;},()=>audio.currentTime,commit);
 a.oninput=()=>{if(a.value==='')return;range[0]=Math.max(0,Math.min(range[1]-.001,Number(a.value)));redraw();commit();};
 b.oninput=()=>{if(b.value==='')return;range[1]=Math.min(info.duration,Math.max(range[0]+.001,Number(b.value)));redraw();commit();};
 const wordButtons=[];
 if(words.length){const list=el('div',{className:'zura-audio-words'});panel.append(el('p',{},'Select words. Shift-click to extend the selection.'),list);for(const word of words){const button=el('button',{type:'button',title:`${word.start.toFixed(3)}â€“${word.end.toFixed(3)} s`},word.text);button.onclick=e=>{range=e.shiftKey?[Math.min(range[0],word.start),Math.max(range[1],word.end)]:[word.start,word.end];range[1]=Math.min(info.duration,range[1]);redraw();commit();audio.pause();audio.currentTime=range[0];};wordButtons.push({word,button});list.append(button);}}
 function paint(){play.innerHTML=audio.paused?playIcon:pauseIcon;play.ariaLabel=audio.paused?'Play audio':'Pause audio';draw();if(!audio.paused){if(stopAt!==null&&audio.currentTime>=stopAt){const end=stopAt;audio.pause();audio.currentTime=end;stopAt=null;draw();return;}animation=requestAnimationFrame(paint);}}
 const start=()=>audio.play().catch(e=>{status.textContent=e.message;});
 play.onclick=()=>{stopAt=null;if(audio.paused){if(audio.ended)audio.currentTime=0;start();}else audio.pause();};
 selected.onclick=()=>{audio.currentTime=range[0];stopAt=range[1];start();};
 audio.onplay=()=>{cancelAnimationFrame(animation);paint();};audio.onpause=audio.onended=()=>{cancelAnimationFrame(animation);paint();};audio.ontimeupdate=()=>{draw();if(stopAt!==null&&audio.currentTime>=stopAt){const end=stopAt;stopAt=null;audio.pause();audio.currentTime=end;draw();}};
 return ()=>{cancelAnimationFrame(animation);audio.pause();audio.removeAttribute('src');audio.load();};
}

function mount(n){
 const source=n.comfyClass==='ZuraAudioDialogueSource';hide(n);
 const root=el('section',{className:'zura-audio-editor'});n._audioRoot=root;
 const style=el('style');style.textContent=`.zura-audio-editor{font:13px system-ui;color:#e7eff6;background:#18212d;border-radius:10px;padding:14px;box-sizing:border-box;overflow:auto;width:100%;height:100%}.zura-audio-editor h3{margin:0 0 10px;font-size:19px}.zura-audio-editor p{color:#aec0d0;line-height:1.5}.zura-audio-editor .zura-audio-download,.zura-audio-editor button,.zura-audio-editor input,.zura-audio-editor textarea,.zura-audio-editor select{font:inherit;color:inherit;background:#263547;border:1px solid #52677c;border-radius:6px;padding:8px;box-sizing:border-box}.zura-audio-editor .zura-audio-download{display:inline-flex;align-items:center;gap:8px;text-decoration:none;background:#254f45;border-color:#8de6c9;font-weight:600}.zura-audio-editor button{cursor:pointer}.zura-audio-editor button[aria-pressed=true]{background:#254f45;border-color:#8de6c9}.zura-audio-editor label{display:grid;gap:6px;color:#bccddd;font-size:12px;flex:1;min-width:0;margin:10px 0}.zura-audio-editor textarea{width:100%;resize:vertical;min-height:80px}.zura-audio-editor input{width:100%}.zura-audio-editor canvas{width:100%;height:100px;border:1px solid #52677c;border-radius:7px;margin:12px 0;touch-action:none}.zura-audio-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.zura-audio-words{display:flex;gap:6px;flex-wrap:wrap}.zura-audio-words button{padding:5px 8px}.zura-audio-editor summary{cursor:pointer;padding:10px 0;color:#8de6c9}.zura-audio-status{line-height:1.5;margin:12px 0;color:#9ce8d0;overflow-wrap:anywhere}`;
 for(const event of ['pointerdown','pointerup','click','dblclick','keydown','wheel'])root.addEventListener(event,e=>e.stopPropagation());
 embeddedWidget(n,'audio_dialogue_editor','zuraAudioDialogueEditor',root,source?830:700,450);n.setSize([Math.max(n.size[0],550),source?970:900]);
 let dispose=()=>{},revision=0;
 n._audioRefresh=async(tab='take')=>{const mine=++revision;dispose();root.replaceChildren(style);root.append(el('h3',{},source?'Select words':'Blend replacement words'));
  const status=el('div',{className:'zura-audio-status'});let info;
  try{
   if(source){const row=el('div',{className:'zura-audio-row'}),choose=el('button',{},'Choose audio'),transcribe=el('button',{},'Transcribe with Parakeet');row.append(choose,transcribe);root.append(row);choose.onclick=()=>upload(n,'source',()=>n._audioRefresh());
    transcribe.onclick=async()=>{transcribe.disabled=true;status.textContent='Transcribing locallyâ€¦';try{const v=await post('transcribe',{source:get(n,'source')});n.properties.zuraAudioWords=v.words;set(n,'source_transcript',v.words.map(w=>w.text).join(' '));await n._audioRefresh();}catch(e){status.textContent=e.message;}finally{transcribe.disabled=false;}};
    if(get(n,'source')){info=await post('info',{source:get(n,'source')});info.file=get(n,'source');if(mine!==revision)return;root.append(el('p',{},`${get(n,'source')} Â· ${(info.sample_rate/1000).toFixed(1)} kHz Â· ${info.channels} channel${info.channels===1?'':'s'}`));dispose=timeline(root,info,n,true,status,n.properties.zuraAudioWords||[]);}
    else root.append(el('p',{},'Choose your original audio. Drag the waveform handles or select transcript words.'));
    root.append(text(n,'source_transcript','Original full phrase','The original words, before the edit. Parakeet can fill this in.'));
    const details=el('details',{open:Boolean(n._audioRefOpen)}),summary=el('summary',{},'Speaker reference Â· optional extra recording');details.ontoggle=()=>{n._audioRefOpen=details.open;};details.append(summary,el('p',{},'Use 8â€“20 seconds of clean speech from the same actor where possible. LongCat needs the exact words alongside the recording. Keep the total reference under 25 seconds.'));
    const more=el('button',{},get(n,'extra_reference')?'Change additional reference':'Add speaker reference'),clear=el('button',{},'Remove extra reference'),r=el('div',{className:'zura-audio-row'});r.append(more,clear);details.append(r);more.onclick=()=>upload(n,'extra_reference',()=>n._audioRefresh());clear.onclick=()=>{set(n,'extra_reference','');set(n,'extra_transcript','');n._audioRefresh();};
    if(get(n,'extra_reference')){const audio=el('audio',{src:media(get(n,'extra_reference')),controls:true,preload:'metadata'});audio.style.width='100%';const transcribe=el('button',{},'Transcribe extra reference');transcribe.onclick=async()=>{transcribe.disabled=true;status.textContent='Transcribing extra reference locallyâ€¦';try{const result=await post('transcribe',{source:get(n,'extra_reference')});set(n,'extra_transcript',result.words.map(w=>w.text).join(' '));n._audioRefOpen=true;await n._audioRefresh();}catch(e){status.textContent=e.message;}finally{transcribe.disabled=false;}};const duration=el('p',{},get(n,'extra_reference'));audio.onloadedmetadata=()=>{if(Number.isFinite(audio.duration))duration.textContent=`${get(n,'extra_reference')} Â· ${audio.duration.toFixed(1)} seconds`;};details.append(duration,audio,transcribe,text(n,'extra_transcript','Exact words in the additional reference','Transcript of the extra recording.'));const before=dispose;dispose=()=>{before();audio.pause();};}
    const sourceControls=el('div'),trim=el('details',{open:Number(get(n,'reference_start'))>0||Number(get(n,'reference_end'))>0});
    sourceControls.append(el('p',{},'The original audio is included as a voice reference. You can optionally trim it below.'));
    trim.append(el('summary',{},'Trim original voice reference'),el('p',{},'OUT = 0 includes the rest of the source. If you trim it, enter only the words spoken inside that range.'));
    const times=el('div',{className:'zura-audio-row'});times.append(number(n,'reference_start','Reference IN'),number(n,'reference_end','Reference OUT (0 = end)'));trim.append(times,text(n,'source_reference_transcript','Exact words in the trimmed source','Only needed when you trim the original reference.'));sourceControls.append(trim);
    const updateReferenceMode=()=>{sourceControls.hidden=get(n,'reference_mode')==='Extra reference only';};
    details.append(choice(n,'reference_mode','Reference to use',updateReferenceMode),sourceControls);updateReferenceMode();root.append(details);
   }else{
    const preview=n._audioPreview||n.properties.zuraAudioPreview;const row=el('div',{className:'zura-audio-row'}),take=el('button',{},'Replacement take'),final=el('button',{},'Finished audio');take.setAttribute('aria-pressed',tab==='take');final.setAttribute('aria-pressed',tab==='final');row.append(take,final);root.append(row);take.onclick=()=>n._audioRefresh('take');final.onclick=()=>n._audioRefresh('final');
    if(preview){status.textContent=preview.status+(preview.notice?' Â· '+preview.notice:'');
     if(preview.status==='Blended'&&preview.file){const name=String(get(n,'project')||'Dialogue_Edit').replace(/[^a-zA-Z0-9_-]+/g,'_')+'.wav',download=el('a',{className:'zura-audio-download',href:media(preview.file),download:name,ariaLabel:'Download finished WAV',title:'Download the blended audio as a WAV file'},'Download WAV');root.append(download);}

     if(tab==='take'){info={file:preview.take,duration:preview.take_duration,peaks:preview.take_peaks};dispose=timeline(root,info,n,false,status,preview.words||[]);root.append(el('p',{},'Adjust the selected words, then Run again. LongCat reuses this take.'));
      const transcribe=el('button',{},'Transcribe take with Parakeet');root.append(transcribe);transcribe.onclick=async()=>{transcribe.disabled=true;try{preview.words=(await post('transcribe',{source:preview.take})).words;await n._audioRefresh();}catch(e){status.textContent=e.message;}finally{transcribe.disabled=false;}};
     }else{const audio=el('audio',{src:media(preview.file),controls:true,preload:'metadata'});audio.style.width='100%';root.append(audio,el('p',{},(preview.status==='Blended'?'Finished WAV Â· ':'Preview only Â· ')+preview.file));dispose=()=>audio.pause();}
    }else root.append(el('p',{},'Run once to generate the full phrase. The changed words can be selected automatically with Parakeet, or manually on the waveform.'));
    root.append(choice(n,'selection_mode','Replacement selection'),choice(n,'timing','Timing'),number(n,'fade_ms','Blend at each edge Â· milliseconds'),text(n,'project','Output label','Dialogue_Edit'));
    root.append(el('p',{},'Natural duration keeps the take untouched and moves the following audio. Keep timing allows at most 15% pitch-preserving adjustment. Only the selected section is replaced.'));
   }
  }catch(e){status.textContent=e.message;}root.append(status);
 };
 const configured=n.onConfigure;n.onConfigure=function(data){configured?.call(this,data);queueMicrotask(()=>{const p=n.properties.zuraAudioPreview;if(!source&&get(n,'selection_mode')==='Auto changed words'&&p?.selection){set(n,'generated_start',p.selection[0]);set(n,'generated_end',p.selection[1]);}n._audioRefresh();});};
 const executed=n.onExecuted;n.onExecuted=function(message){executed?.call(this,message);const p=message?.zura_audio_dialogue?.[0];if(p){n._audioPreview=p;n.properties.zuraAudioPreview=p;if(get(n,'selection_mode')==='Auto changed words'&&p.selection){set(n,'generated_start',p.selection[0]);set(n,'generated_end',p.selection[1]);}n._audioRefresh();}};
 const removed=n.onRemoved;n.onRemoved=function(){dispose();removed?.call(this);};queueMicrotask(()=>n._audioRefresh());
}

function direction(n){
 if(n._zuraAudioDirection||!n.subgraph?.nodes?.some(x=>x.comfyClass==='ZuraLongCatDialogueVoice'))return;
 n._zuraAudioDirection=true;
 for(const w of n.widgets||[]){w.hidden=true;w.computeSize=()=>[0,-4];w.computeLayoutSize=()=>({minHeight:0,maxHeight:0,minWidth:0});if(w.element)w.element.style.display='none';}
 const root=el('section',{className:'zura-audio-editor'});root.style.cssText='font:13px system-ui;color:#e7eff6;background:#172a26;border-radius:10px;padding:16px;box-sizing:border-box;overflow:auto;width:100%;height:100%';
 root.append(el('h3',{},'Full replacement phrase'),el('p',{},'Type the complete sentence as you want it spoken. LongCat uses the whole phrase for delivery; the final node blends only the selected words.'));
 const phrase=text(n,'script','Phrase to generate','Type the complete replacement phrase.');phrase.querySelector('textarea').rows=5;root.append(phrase);
 const row=el('div',{className:'zura-audio-row'});row.append(number(n,'pace','Speaking pace Â· 1 = normal'),number(n,'seed','Take seed'));root.append(row);
 const takeStatus=el('p',{role:'status'},'Keep this take if you like its delivery.');
 const newTake=el('button',{},'Change seed');newTake.title='Changes the seed. Press Run to generate another performance.';newTake.onclick=()=>{set(n,'seed',(Number(get(n,'seed'))+1)%4294967296);root.querySelector('input[aria-label="Take seed"]').value=get(n,'seed');takeStatus.textContent='Seed changed. Press Run to generate another take.';};root.append(newTake,takeStatus);
 root.append(el('p',{},'Press Run after changing the take. Moving waveform handles reuses the current performance.'),text(n,'project','Take label','Dialogue_Take'));
 for(const e of root.querySelectorAll('textarea,input,button'))e.style.cssText+=';font:inherit;color:inherit;background:#263f39;border:1px solid #56786c;border-radius:6px;padding:8px;box-sizing:border-box;max-width:100%';
 for(const l of root.querySelectorAll('label'))l.style.cssText='display:grid;gap:6px;margin:12px 0;flex:1;min-width:0';
 for(const event of ['pointerdown','pointerup','click','dblclick','keydown','wheel'])root.addEventListener(event,e=>e.stopPropagation());
 embeddedWidget(n,'audio_direction','zuraAudioDirection',root,600,340);n.setSize([Math.max(420,n.size[0]),Math.max(780,n.size[1])]);
}

app.registerExtension({name:'Zura.AudioDialogueEditor',nodeCreated(n){if(['ZuraAudioDialogueSource','ZuraAudioDialogueFinish'].includes(n.comfyClass))mount(n);else{const previous=n.onConfigure;n.onConfigure=function(data){previous?.call(this,data);queueMicrotask(()=>direction(n));};queueMicrotask(()=>direction(n));}}});

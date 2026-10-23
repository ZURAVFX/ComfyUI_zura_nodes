import {buildFrameVideoGraph,frameVideoAvailability,FRAME_LENGTHS,FRAME_SIZE_PRESETS} from './frame_video_recipes.js';
import {composerIcons as icons,VIDEO_WORKFLOWS} from './studio_composer.js';
import {tidyArtistGraph} from './artist_graph.js';
const KEY='zura-first-last-v1';
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const view=(api,file,type='output')=>api.apiURL('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type}));
export class FrameVideoWorkspace{
  constructor(owner){
    this.owner=owner;this.api=owner.api;this.app=owner.app;this.studio=owner.studio;
    let saved={};try{saved=JSON.parse(localStorage.getItem(KEY))||{};}catch{}
    this.assets=saved.assets||{};this.job=saved.job||null;this.items=Array.isArray(saved.items)?saved.items.slice(0,12):[];
    this.page=document.createElement('section');this.page.className='zf-page';
    this.page.innerHTML=`
      <div class="zf-heading">
        <button type="button" id="zf-back"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m10 5-7 7 7 7M3 12h18"/></svg>Back to video</button>
        <h2 class="zc-sr-only">Frame to video</h2>
        <label class="zc-task-control"><span class="zc-sr-only">Video workflow</span><select id="zf-task" aria-label="Video workflow">${VIDEO_WORKFLOWS.map(([id,label])=>`<option value="${id}" ${id==='frames'?'selected':''}>${label}</option>`).join('')}</select></label>
        <details id="zf-history"><summary>History</summary><div id="zf-takes"></div></details><button type="button" id="zf-clear">Clear history</button>
      </div>
      <div class="zf-viewer">
        <div id="zf-empty"><h3>Bring your image to life.</h3><p>Add a first frame and describe the movement. Add a last frame if you want to guide the ending.</p></div>
        <div id="zf-image-slot" hidden></div><video id="zf-result" controls playsinline hidden></video>
        <div id="zf-progress" hidden><strong id="zf-progress-title">Queued</strong><button id="zf-cancel" type="button">Cancel run</button><progress id="zf-bar" max="100" aria-label="Video generation progress"></progress><span id="zf-progress-detail"></span></div>
        <p id="zf-message" role="status" hidden></p>
      </div>
      <form class="zf-composer zc-prompt-card">
        <strong>Generate video</strong>
        <div class="zc-composer-attachments">
          ${['first','last'].map(id=>`<button type="button" class="zc-attachment" data-frame="${id}">${icons.image}<span>${id==='first'?'First frame':'Last frame · optional'}</span></button><input id="zf-${id}" type="file" accept="image/png,image/jpeg,image/webp" hidden/>`).join('')}
          <button type="button" id="zf-remove-last" class="zc-tool" aria-label="Remove last frame" hidden>Remove last</button>
          <button type="button" id="zf-swap" class="zc-tool" aria-label="Swap first and last frames" hidden>Swap</button>
          <button type="button" id="zf-audio-file-button" class="zc-attachment" hidden>${icons.audio}<span>Add audio reference</span></button><input id="zf-audio-file" type="file" accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg" hidden/>
        </div>
        <label for="zf-prompt" class="zc-sr-only">Describe your video</label><textarea id="zf-prompt" placeholder="Describe the movement, camera and action…" maxlength="12000" required></textarea>
        <div class="zc-prompt-bottom"><div class="zc-prompt-tools">
          <span class="zc-tool">${icons.model}MiniMax H3</span>
          <details class="zc-tool-popup"><summary aria-label="Output resolution">${icons.size}<span id="zf-size-label">1344 × 768</span>${icons.chevron}</summary>
            <div class="zc-tool-panel"><strong>Output resolution</strong>
              <label class="zf-presets" for="zf-size-preset">Size preset<select id="zf-size-preset">${FRAME_SIZE_PRESETS.map(p=>`<option value="${p.id}">${p.label}</option>`).join('')}<option value="custom">Custom dimensions</option></select></label>
              <div class="zf-dimensions" id="zf-custom-size"><label>Width (px)<input id="zf-width" type="number" min="256" max="1536" step="32" value="1344"/></label><label>Height (px)<input id="zf-height" type="number" min="256" max="1536" step="32" value="768"/></label></div>
              <p>Up to 1.03 MP. Custom dimensions use multiples of 32. Match your image shape to avoid stretching or cropping.</p>
            </div>
          </details>
          <label class="zc-tool zc-model-control">${icons.clock}<span class="zc-sr-only">Clip length</span><select id="zf-length" aria-label="Clip length">${FRAME_LENGTHS.map(n=>`<option value="${n}" ${n===73?'selected':''}>${(n/24).toFixed(2)}s</option>`).join('')}</select>${icons.chevron}</label>
          <label class="zc-tool zf-audio-switch"><input type="checkbox" id="zf-audio-enabled" role="switch"/>Audio reference</label>
          <details class="zc-tool-popup"><summary aria-label="Advanced generation settings">${icons.settings}</summary><div class="zc-tool-panel"><label>Sampling steps<input type="number" id="zf-steps" min="4" max="40" value="8"/></label><p>8-step Turbo, strength 1.0 · Comfy Kitchen · res_multistep / simple.</p><label>Seed<input id="zf-seed" type="number" min="0" max="9007199254740991" value="42"/></label><label class="zf-check"><input type="checkbox" id="zf-random" checked/>New variation</label><div id="zf-setup"></div><button id="zf-refresh" type="button">Refresh installed models</button></div></details>
        </div><div class="zc-prompt-submit"><button id="zf-generate" class="gs-primary" type="submit" aria-describedby="zf-note" disabled>Generate video</button></div></div>
        <p id="zf-note" aria-live="polite">Add a first frame to begin. The last frame is optional.</p>
      </form>`;
    owner.root.append(this.page);
    const draft=saved.draft||{};for(const id of ['prompt','width','height','length','steps','seed'])if(draft[id]!==undefined)this.$(id).value=draft[id];
    this.$('size-preset').value=draft.sizePreset==='custom'?'custom':FRAME_SIZE_PRESETS.find(p=>p.width===Number(this.$('width').value)&&p.height===Number(this.$('height').value))?.id||'custom';
    this.$('audio-enabled').checked=draft.audioEnabled===true;this.$('random').checked=draft.random!==false;
    this.$('back').onclick=()=>owner.show('video');this.$('refresh').onclick=()=>this.loadModels();
    this.$('task').onchange=e=>{owner.videoComposer.selectWorkflow(e.target.value);this.$('task').value='frames';};
    this.$('clear').onclick=()=>{this.items=[];this.renderHistory();this.$('result').pause();this.$('result').hidden=true;this.$('result').removeAttribute('src');this.preview();this.save();};
    this.page.querySelector('form').onsubmit=e=>{e.preventDefault();this.generate();};
    for(const id of ['prompt','width','height','length','steps','seed','audio-enabled','random'])for(const event of ['input','change'])this.$(id).addEventListener(event,()=>{this.save();this.render();});
    this.$('size-preset').onchange=()=>{
      const preset=FRAME_SIZE_PRESETS.find(p=>p.id===this.$('size-preset').value);
      if(preset){this.$('width').value=preset.width;this.$('height').value=preset.height;}
      this.save();this.render();
    };
    for(const id of ['first','last']){
      const button=this.page.querySelector(`[data-frame="${id}"]`);button.onclick=()=>this.$(id).click();
      this.$(id).onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)this.upload(id,file);};
      button.ondragover=e=>{e.preventDefault();e.stopPropagation();};button.ondrop=e=>{e.preventDefault();e.stopPropagation();if(e.dataTransfer?.files?.[0])this.upload(id,e.dataTransfer.files[0]);};
      button.onfocus=()=>this.pasteTarget=id;
    }
    this.$('swap').onclick=()=>{if(this.busy())return;[this.assets.first,this.assets.last]=[this.assets.last,this.assets.first];this.save();this.render();this.$('result').pause();this.$('result').hidden=true;this.preview();};
    this.$('remove-last').onclick=()=>{if(this.busy())return;delete this.assets.last;this.save();this.render();this.$('result').pause();this.$('result').hidden=true;this.preview();};
    this.$('audio-file-button').onclick=()=>this.$('audio-file').click();this.$('audio-file').onchange=e=>{const file=e.target.files?.[0];e.target.value='';if(file)this.upload('audio',file);};
    this.$('cancel').onclick=()=>this.cancel();
    this.page.addEventListener('keydown',e=>{if(e.key==='Escape')for(const d of this.page.querySelectorAll('details'))if(d.open){d.open=false;d.querySelector('summary').focus({preventScroll:true});e.stopPropagation();}});
    this.page.addEventListener('toggle',e=>{if(e.target.tagName==='DETAILS'&&e.target.open)for(const d of this.page.querySelectorAll('details'))if(d!==e.target)d.open=false;},true);
    this.api.addEventListener?.('progress',e=>{const d=e.detail;if(!this.job||d.prompt_id!==this.job.id)return;this.$('bar').value=100*d.value/d.max;this.$('progress-title').textContent=`Generating video · Step ${d.value} of ${d.max}`;this.$('progress-detail').textContent=this.elapsed(d.value,d.max);});
    this.api.addEventListener?.('executing',e=>{const d=e.detail;if(!this.job||d.prompt_id!==this.job.id||!d.node)return;this.$('bar').removeAttribute('value');this.$('progress-title').textContent=({text:'Loading text encoder',endpoints:'Reading first and last frames',audio_ref:'Loading audio reference',audio_guide:'Encoding audio reference',model:'Loading H3',turbo:'Preparing Turbo adapter',sample:'Generating video',decode:'Decoding video',decode_audio:'Decoding audio',save:'Saving video'})[d.node]||'Preparing video';});
    this.render();this.renderHistory();this.preview();
  }
  $(id){return this.page.querySelector('#zf-'+id);}
  config(){return {first:this.assets.first,last:this.assets.last,audio:this.assets.audio,audioEnabled:this.$('audio-enabled').checked,prompt:this.$('prompt').value,width:Number(this.$('width').value),height:Number(this.$('height').value),sizePreset:this.$('size-preset').value,frames:Number(this.$('length').value),steps:Number(this.$('steps').value),seed:Number(this.$('seed').value),random:this.$('random').checked};}
  save(){const c=this.config();try{localStorage.setItem(KEY,JSON.stringify({assets:this.assets,draft:{...c,length:c.frames},job:this.job,items:this.items}));}catch{this.message('Browser storage is full. Outputs still save in ComfyUI/output/zura/first_last.');}}
  busy(){return !!(this.job||this.submitting||this.uploading);}
  message(text){this.$('message').hidden=!text;this.$('message').textContent=text;}
  async fetch(path,body){return this.owner.fetch(path,body);}
  async loadModels(){
    if(this.loading)return;this.loading=true;this.modelError='';this.render();
    try{const types=['UNETLoader','CLIPLoader','VAELoader','LoraLoaderModelOnly','ModelAttentionBackend','MiniMaxH3ImageToVideo','MiniMaxH3AddGuide','LoadAudio','LoadImage','BasicGuider','BasicScheduler','KSamplerSelect','RandomNoise','SamplerCustomAdvanced','VAEDecode','VAEDecodeAudio','CreateVideo','SaveVideo'];const parts=await Promise.all(types.map(t=>this.fetch('/object_info/'+t)));this.availability=frameVideoAvailability(Object.assign({},...parts));this.$('setup').textContent=this.availability.ready?'All required models and nodes are installed.':'Missing: '+this.availability.missing.join(', ');}
    catch(e){this.modelError='Could not check H3 models. Open generation settings and refresh installed models.';this.message(e.message);}finally{this.loading=false;this.render();}
  }
  open(){this.$('task').value='frames';for(const option of this.$('task').querySelectorAll('option')){const input=this.owner.root.querySelector(`input[name="gs-workflow"][value="${option.value}"]`);option.disabled=!!input?.disabled;}if(!this.availability)this.loadModels();if(this.job)this.startPolling();}
  async upload(slot,file){
    if(this.busy())return;
    if(slot!=='audio'&&!/^image\/(png|jpeg|webp)$/.test(file.type)&&! /\.(png|jpe?g|webp)$/i.test(file.name)){this.message('Choose a PNG, JPG or WebP image.');return;}
    if(file.size>512*1024**2){this.message('Use a file smaller than 512 MB.');return;}
    this.uploading=true;this.message('Uploading '+file.name+'…');this.render();
    try{const data=new FormData();data.append('image',file);data.append('subfolder','zura_frames');data.append('overwrite','false');const response=await this.api.fetchApi('/upload/image',{method:'POST',body:data,timeoutMs:300000});if(!response.ok)throw new Error('Upload failed. Please choose the file again.');const uploaded=await response.json();this.assets[slot]={file:[uploaded.subfolder,uploaded.name].filter(Boolean).join('/'),filename:uploaded.name,subfolder:uploaded.subfolder||'',name:file.name};this.save();this.message('');if(slot!=='audio'){this.$('result').pause();this.$('result').hidden=true;this.preview(slot);}}
    catch(e){this.message(e.message);}finally{this.uploading=false;this.render();}
  }
  async paste(event){const item=Array.from(event.clipboardData?.items||[]).find(i=>i.kind==='file'&&i.type.startsWith('image/'));if(!item)return;event.preventDefault();event.stopPropagation();const file=item.getAsFile();if(file)await this.upload(this.pasteTarget||(!this.assets.first?'first':'last'),file);}
  preview(slot='first'){
    if(!this.$('result').hidden)return;const asset=this.assets[slot]||this.assets.first||this.assets.last;
    this.$('image-slot').hidden=!asset;this.$('empty').hidden=!!asset;if(asset){let image=this.$('image-slot').querySelector('img');if(!image){image=document.createElement('img');image.alt='Selected endpoint';this.$('image-slot').append(image);}image.src=view(this.api,asset,'input');}
  }
  render(){
    const busy=this.busy(),c=this.config();let error='';try{buildFrameVideoGraph(c);}catch(e){error=e.message;}
    for(const id of ['prompt','width','height','size-preset','length','steps','seed','audio-enabled','random','swap','remove-last','clear'])this.$(id).disabled=busy;
    for(const slot of ['first','last']){const button=this.page.querySelector(`[data-frame="${slot}"]`),asset=this.assets[slot];button.disabled=busy;let image=button.querySelector('img');if(asset){if(!image){image=document.createElement('img');image.alt='';button.prepend(image);}image.src=view(this.api,asset,'input');button.title=asset.name;}else image?.remove();button.classList.toggle('has-media',!!asset);}
    this.$('audio-file-button').hidden=!c.audioEnabled;this.$('audio-file-button').disabled=busy;this.$('audio-file-button').querySelector('span').textContent=this.assets.audio?.name||'Add audio reference';
    this.$('remove-last').hidden=!this.assets.last;this.$('swap').hidden=!this.assets.first||!this.assets.last;
    this.page.querySelector('[data-frame="last"] span').textContent=this.assets.last?'Last frame':'Last frame · optional';
    this.$('custom-size').hidden=c.sizePreset!=='custom';
    this.$('generate').disabled=busy||!this.availability?.ready||!!error;this.$('generate').textContent=busy?'Generating…':'Generate video';this.$('progress').hidden=!this.job&&!this.submitting;this.$('cancel').disabled=!this.job;
    this.$('size-label').textContent=`${c.width} × ${c.height}`;
    const setup=this.loading?'Checking installed H3 models…':this.modelError||(!this.availability?'Open this workflow to check installed H3 models.':!this.availability.ready?'H3 setup is incomplete. Open generation settings to see missing models.':'');
    this.$('note').textContent=error||setup||`${c.frames} frames at 24 fps · ${c.last?.file?'First + last frame':'First frame only'} · ${c.audioEnabled?'Follows your audio reference':'H3 generates audio'}`;
  }
  renderHistory(){this.$('takes').innerHTML=this.items.map((item,i)=>`<button type="button" data-take="${i}">${escape(item.config.prompt.slice(0,60))} · ${(item.config.frames/24).toFixed(2)}s</button>`).join('');this.$('takes').onclick=e=>{const button=e.target.closest('[data-take]');if(button)this.showResult(this.items[Number(button.dataset.take)].file);};if(this.items[0])this.showResult(this.items[0].file);}
  showResult(file){this.$('empty').hidden=true;this.$('image-slot').hidden=true;this.$('result').hidden=false;this.$('result').src=view(this.api,file);this.$('history').open=false;}
  elapsed(step,max){const elapsed=Math.floor((Date.now()-this.job.started)/1000);const sampleElapsed=this.sampleStarted?(Date.now()-this.sampleStarted)/1000:0;if(!this.sampleStarted&&step)this.sampleStarted=Date.now();return step>1&&sampleElapsed>0?`About ${Math.ceil(sampleElapsed/(step-1)*(max-step))}s left in sampling · ${elapsed}s elapsed`:`${elapsed}s elapsed`;}
  async generate(){
    if(this.busy())return;this.submitting=true;this.message('');this.render();
    try{if(!this.availability?.ready)throw new Error('Install the required H3 models and refresh.');const config=this.config();if(config.random)config.seed=crypto.getRandomValues(new Uint32Array(1))[0];const graph=buildFrameVideoGraph(config);const response=await this.fetch('/prompt',{prompt:graph,client_id:this.api.clientId,extra_data:{zura_first_last:true}});if(!response.prompt_id)throw new Error('ComfyUI did not confirm this run. Check the queue before retrying.');this.job={id:response.prompt_id,started:Date.now(),config};this.sampleStarted=null;this.save();this.startPolling();}
    catch(e){this.message(e.message);}finally{this.submitting=false;this.render();}
  }
  startPolling(){if(this.timer)return;this.timer=setInterval(()=>this.poll(),1500);this.poll();}
  async poll(){
    if(!this.job||this.polling)return;const job=this.job;this.polling=true;
    try{const history=await this.fetch('/history/'+encodeURIComponent(job.id)),entry=history[job.id];if(this.job!==job)return;
      if(entry?.status?.completed||entry?.status?.status_str==='error'){
        const files=entry.outputs?.save?.images||[];for(const file of files)this.items.unshift({file,config:job.config});this.items=this.items.slice(0,12);this.job=null;this.stopPolling();this.save();this.renderHistory();this.render();if(!files.length)this.message(entry.status.messages?.find(m=>m[0]==='execution_error')?.[1]?.exception_message||'Generation stopped. Your previous takes are safe.');
      }else{const queue=await this.fetch('/queue');if(this.job!==job)return;const running=queue.queue_running.some(r=>r[1]===job.id),pending=queue.queue_pending.some(r=>r[1]===job.id);if(!running&&!pending){this.job=null;this.stopPolling();this.save();this.message('This run is no longer in ComfyUI’s queue. It has not been resubmitted.');this.render();}else this.$('progress-detail').textContent=running?this.elapsed():'Waiting for other ComfyUI jobs';}
    }catch{this.message('Connection interrupted. Reconnecting to your saved run…');}finally{this.polling=false;}
  }
  async cancel(){if(!this.job)return;try{const id=this.job.id;await this.fetch('/queue',{delete:[id]});await this.fetch('/interrupt',{prompt_id:id});this.message('Cancellation requested.');await this.poll();}catch(e){this.message(e.message);}}
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  close(){this.save();this.stopPolling();}
  async graph(){try{const graph=buildFrameVideoGraph(this.job?.config||this.config()),original=(this.app.rootGraph||this.app.graph)?.serialize?.();if(!original||typeof this.app.loadApiJson!=='function')throw new Error('Update ComfyUI to open this editable graph.');try{await this.app.loadApiJson(graph,'Zura First and Last Frame · '+Date.now()+'.json');await import('./vendor/elk.bundled.js');await tidyArtistGraph(this.app,graph,'first_last',window.ELK);}catch(e){await this.app.loadGraphData(original);throw e;}this.studio.close();}catch(e){this.message(e.message);}}
}

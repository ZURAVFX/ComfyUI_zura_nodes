import {nativeSwitchGraph} from './switch_x_recipe.js';
import {workspaceStorage} from './studio_storage.js';
import {submitOwnedGraph,recoverOwnedSubmission,cancelOwnedJob} from './studio_owned_jobs.js';

const storageKey='zura-switch-x-native-v3';
const initial={source:'',matte:'',refs:[],prompt:'',method:'native',audioMode:'source',audioFile:'',whiteMeans:'keep',maskChannel:'luma',replacementMargin:8,structureStrength:.96,side:1024,steps:8,depthGuide:false,lossless:false};
const videoAccept='video/*,.mov,.mkv,.mxf,.avi';

export class SwitchXWorkspace {
  constructor(owner){
    this.owner=owner;
    this.api=owner.api;
    this.storage=workspaceStorage(owner);
    let saved={};
    try{
      const current=this.storage.getItem(storageKey);
      if(current)saved=JSON.parse(current);
      else{
        const previous=JSON.parse(this.storage.getItem('zura-switch-x-joint-v2')||this.storage.getItem('zura-switch-x-v1'));
        if(previous?.config)saved={config:{...previous.config,method:'native',side:1024,steps:8}};
      }
      saved??={};
    }catch{}
    const draft=saved.config||{};
    this.config=Object.fromEntries(Object.entries(initial).map(([key,value])=>[key,draft[key]??value]));
    this.config.pinnedFrames=draft.pinnedFrames||{};
    this.job=saved.job;
    this.pendingSubmission=saved.pendingSubmission;
    this.results=saved.results||{};
    this.result=this.results[this.config.method]||saved.result;
    const doc=owner.root.ownerDocument;
    this.page=doc.createElement('section');
    this.page.className='zs-switch-page';
    this.page.hidden=true;
    if(!doc.getElementById('zs-switch-styles')){
      const link=doc.createElement('link');link.rel='stylesheet';link.id='zs-switch-styles';
      link.href=new URL('./studio_switch_x.css',import.meta.url).href;doc.head.append(link);
    }
    this.page.innerHTML=`<div class="zs-switch-shell">
      <header class="zs-switch-heading"><h2>Zura SwitchX</h2><span>MiniMax H3 Ref2VA</span></header>
      <section class="zs-switch-player" aria-label="Shot viewer">
        <div class="zs-switch-monitor"><video controls playsinline data-preview hidden></video>
          <button type="button" data-empty class="zs-switch-empty"><span aria-hidden="true">+</span>Add source footage</button></div>
        <nav class="zs-switch-transport" aria-label="Compare shot"><div><button type="button" data-view-source>Source</button><button type="button" data-view-matte>Selection</button><button type="button" data-view-result>Result</button></div><small data-shot-meta></small></nav>
        <label class="zs-switch-scrub" data-selection-scrub hidden><span data-frame-label>Frame 1</span><input data-selection-frame type="range" min="0" value="0" step="1"></label>
      </section>
      <div class="zs-switch-composer"><fieldset>
        <div class="zs-switch-files">
          <label class="zs-switch-upload"><strong>Source footage</strong><small data-source-name></small><input type="file" data-source accept="${videoAccept}"></label>
          <label class="zs-switch-upload" data-mask-only><strong>Selection matte</strong><small data-matte-name></small><input type="file" data-matte accept="${videoAccept},image/png,image/tiff"></label>
          <label class="zs-switch-upload"><strong>Reference images</strong><small data-refs-name></small><input type="file" data-refs multiple accept="image/*"></label>
          <label class="zs-switch-upload" data-audio-upload><strong>Dialogue track</strong><small data-audio-name></small><input type="file" data-audioFile accept="audio/*,.wav,.aif,.aiff,.flac"></label>
        </div>
        <div class="zs-switch-matte-row" data-mask-only><label>White pixels<select data-whiteMeans><option value="keep">Keep and relight</option><option value="replace">Replace</option></select></label>
          <label>Matte channel<select data-maskChannel><option value="luma">Black and white</option><option value="alpha">Embedded alpha</option></select></label>
          <button type="button" data-use-review hidden>Use reviewed selection</button></div>
        <div class="zs-switch-tray" data-tray><div data-ref-strip class="zs-switch-ref-strip"></div><button type="button" data-clear hidden>Clear references</button></div>
        <label class="zs-switch-direction">Scene direction<textarea data-prompt rows="2" placeholder="Describe the new setting, lighting and action…"></textarea></label>
        <div class="zs-switch-tools"><label>Workflow<select data-method><option value="native">Native Ref2VA</option><option value="masked">Mask-guided Ref2VA</option></select></label>
          <label>Audio<select data-audioMode><option value="source">Source audio</option><option value="upload">Choose audio</option><option value="mute">Silent</option></select></label>
          <details><summary>Render settings</summary><div class="zs-switch-settings"><label>H3 long edge<select data-side><option>512</option><option>768</option><option>1024</option><option>1280</option></select></label>
          <label>Sampling<select data-steps><option value="8">8 steps · Turbo</option><option value="40">40 steps · Ref2VA</option></select></label>
          <label data-edit-margin>Replacement margin (px)<input data-replacementMargin type="number" min="0" max="128" step="1"></label><label data-mask-only>Source detail<input data-structureStrength type="range" min="0" max="1" step=".01"></label>
          <label data-mask-only><input type="checkbox" data-depthGuide> Source depth guidance</label>
          <label data-mask-only><input type="checkbox" data-lossless> Lossless RGB master</label></div></details></div></fieldset>
        <footer><div class="zs-switch-feedback" role="status" aria-live="polite"><strong data-progress-title></strong> <span data-progress-detail></span><span data-message></span><progress data-bar hidden></progress></div>
          <div class="zs-switch-actions"><a download data-master hidden>Save master</a><button type="button" data-cancel hidden>Cancel run</button><button type="button" class="gs-primary" data-run>Generate shot</button></div></footer>
      </div></div>`;
    owner.root.append(this.page);
    for(const key of ['method','prompt','audioMode','whiteMeans','maskChannel','replacementMargin','structureStrength','side','steps','depthGuide','lossless']){
      const el=this.$(key);
      if(el.type==='checkbox')el.checked=this.config[key];else el.value=this.config[key];
      el.oninput=()=>{this.config[key]=el.type==='checkbox'?el.checked:el.value;if(key==='method'){this.result=this.results[el.value]||null;this.view=this.result?'result':'source';}this.save();if(['method','audioMode','whiteMeans','maskChannel'].includes(key))this.render();};
    }
    for(const key of ['source','matte','refs','audioFile'])this.$(key).onchange=e=>void this.upload(key,[...e.target.files]);
    this.$('empty').onclick=()=>this.$('source').click();
    this.$('use-review').onclick=()=>void this.importReview();
    this.$('selection-frame').oninput=e=>{this.$('frame-label').textContent='Frame '+(Number(e.target.value)+1);};
    this.$('selection-frame').onchange=e=>{this.compareTime=Number(e.target.value)/(this.sourceMeta?.fps||24);this.render();};
    this.$('clear').onclick=()=>{this.config.refs=[];this.config.pinnedFrames={};this.save();this.render();};
    this.$('run').onclick=()=>void this.run();
    this.$('cancel').onclick=()=>void cancelOwnedJob(this).catch(e=>this.message(e.message));
    this.view=this.result?'result':'source';
    for(const kind of ['source','matte','result']){
      this.$('view-'+kind).onclick=()=>{
        const player=this.$('preview');
        if(!player.hidden&&player.readyState>=1)this.compareTime=player.currentTime;
        this.view=kind;this.render();
      };
    }
    this.$('preview').addEventListener('loadedmetadata',()=>{
      const player=this.$('preview');
      if(this.compareTime>0&&Number.isFinite(player.duration)){
        player.currentTime=Math.min(this.compareTime,Math.max(0,player.duration-.001));
      }
    });
    this.progressHandler=event=>{
      const e=event.detail;
      if(!this.job||e.prompt_id!==this.job.id)return;
      const label=this.job.stages?.[e.node]||'Rendering';
      this.$('progress-title').textContent=label;
      this.$('progress-detail').textContent=e.max?' · '+e.value+' / '+e.max:'';
      if(e.max){this.$('bar').max=e.max;this.$('bar').value=e.value;}
    };
    this.render();
  }
  $(name){return this.page.querySelector('[data-'+name+']');}
  fetch(path,body){return this.owner.fetch(path,body);}
  message(s){this.$('message').textContent=s;}
  save(){try{if(this.result)this.results[this.config.method]=this.result;this.storage.setItem(storageKey,JSON.stringify({config:this.config,job:this.job,pendingSubmission:this.pendingSubmission,results:this.results}));return true;}catch{return false;}}
  reset(){
    if(this.busy())return false;
    this.config={...initial,refs:[],pinnedFrames:{}};
    this.results={};this.result=null;this.view='source';this.sourceMeta=null;this.metaSource='';this.compareTime=0;
    for(const [key,value] of Object.entries(this.config)){
      const field=this.$(key);
      if(!field)continue;
      if(field.type==='file')field.value='';
      else if(field.type==='checkbox')field.checked=value;
      else if(field.matches('input,textarea,select'))field.value=value;
    }
    this.$('progress-title').textContent='';this.$('progress-detail').textContent='';
    this.message('');this.save();this.render();return true;
  }
  busy(){return !!(this.job||this.pendingSubmission||this.submitting||this.uploading);}
  render(){
    const busy=this.busy();
    this.page.querySelector('fieldset').disabled=busy;
    this.$('run').disabled=busy;
    this.$('cancel').hidden=!this.job;
    this.$('bar').hidden=!busy;
    const masked=this.config.method==='masked';
    this.$('empty').hidden=!!this.config.source||!!this.result;
    this.$('empty').disabled=busy;
    const current=this.owner.studio?.project;
    this.$('use-review').hidden=!(masked&&current?.review&&current?.approval&&current.config?.workflow_mode==='swap');
    if(this.config.source&&this.metaSource!==this.config.source)void this.refreshMeta();
    const meta=this.sourceMeta;
    this.$('shot-meta').textContent=meta?Math.round(meta.frames)+' frames · '+Number(meta.fps.toFixed(3))+' fps':'';
    this.$('selection-scrub').hidden=this.view!=='matte'||!this.config.source||!this.config.matte;
    const frame=Math.max(0,Math.min((meta?.frames||1)-1,Math.round((this.compareTime||0)*(meta?.fps||24))));
    this.$('selection-frame').max=Math.max(0,(meta?.frames||1)-1);this.$('selection-frame').value=frame;
    this.$('frame-label').textContent='Frame '+(frame+1);
    for(const el of this.page.querySelectorAll('[data-mask-only]'))el.hidden=!masked;
    this.$('edit-margin').hidden=!(masked&&this.config.whiteMeans==='replace');
    this.$('view-matte').hidden=!masked;
    this.$('audio-upload').hidden=this.config.audioMode!=='upload';
    this.$('audio-name').textContent=this.config.audioFile.split('/').pop()||'Choose file…';
    for(const key of ['source','matte'])this.$(key+'-name').textContent=this.config[key].split('/').pop()||'Choose file…';
    this.$('refs-name').textContent=this.config.refs.map(p=>p.split('/').pop()).join(', ')||'Choose images…';
    this.$('clear').hidden=!this.config.refs.length;
    this.$('tray').hidden=!this.config.refs.length;
    const fileUrl=file=>this.api.apiURL('/view?'+new URLSearchParams(file));
    const strip=this.$('ref-strip'),signature=JSON.stringify([this.config.refs,this.config.method]);
    if(strip.dataset.referenceSignature!==signature){
      strip.dataset.referenceSignature=signature;strip.replaceChildren();
      for(const [i,path] of this.config.refs.entries()){
        const parts=path.split('/'),filename=parts.pop();
        const img=strip.ownerDocument.createElement('img');
        img.src=fileUrl({filename,subfolder:parts.join('/'),type:'input'});
        img.alt='Picture '+(i+1)+' · '+filename;img.title=img.alt;
        const card=strip.ownerDocument.createElement('div');
        const title=strip.ownerDocument.createElement('span');
        title.textContent='Picture '+(i+1);
        const pin=strip.ownerDocument.createElement('input');
        pin.type='number';pin.min='0';pin.step='1';pin.placeholder='Scene reference';
        pin.title='Optional source frame to match. Frame 0 is the opening frame.';
        pin.setAttribute('aria-label','Pin picture '+(i+1)+' to source frame');
        pin.value=this.config.pinnedFrames?.[path]??'';
        pin.oninput=()=>{
          this.config.pinnedFrames??={};
          if(pin.value==='')delete this.config.pinnedFrames[path];
          else this.config.pinnedFrames[path]=Number(pin.value);
          this.save();
        };
        card.append(img,title);if(masked)card.append(pin);
        strip.append(card);
      }
    }
    strip.hidden=!this.config.refs.length;
    this.$('master').hidden=!this.result;
    if(this.result)this.$('master').href=fileUrl(this.result.master);
    for(const kind of ['source','matte','result']){
      const button=this.$('view-'+kind);
      button.disabled=!(kind==='result'?this.result:this.config[kind]);
      button.setAttribute('aria-pressed',String(this.view===kind));
    }
    let asset=this.result?.preview;
    if(this.view!=='result'){
      const pieces=(this.config[this.view]||'').split('/');
      const filename=pieces.pop();
      asset=filename?{filename,subfolder:pieces.join('/'),type:'input'}:null;
    }
    const selection=this.view==='matte'&&this.config.source&&this.config.matte;
    const still=selection||asset&&/\.(png|tiff?|webp|bmp|jpe?g)$/i.test(asset.filename);
    const player=this.$('preview'),url=selection?this.api.apiURL('/zura/studio/switch-x/selection?'+new URLSearchParams({
      source:this.config.source,matte:this.config.matte,whiteMeans:this.config.whiteMeans,maskChannel:this.config.maskChannel,frame
    })):asset?fileUrl(asset):null;
    player.hidden=!asset||!!still;
    if(!player.hidden&&player.getAttribute('src')!==url)player.src=url;
    else if(player.hidden&&player.hasAttribute('src'))player.removeAttribute('src');
    let picture=this.$('still');
    if(still){
      if(!picture){
        picture=strip.ownerDocument.createElement('img');
        picture.dataset.still='';picture.alt='Selection overlay on the source frame';picture.onerror=()=>this.message('Could not preview this matte. Check the channel, dimensions and frame timing.');picture.src=url;
        player.after(picture);
      }else if(picture.getAttribute('src')!==url)picture.src=url;
    }else picture?.remove();
  }
  async refreshMeta(){
    const source=this.config.source;this.metaSource=source;this.sourceMeta=null;
    try{
      const meta=await this.fetch('/zura/studio/switch-x/source',{source,side:this.config.side});
      if(source===this.config.source){this.sourceMeta=meta;this.render();}
    }catch(e){if(source===this.config.source)this.message(e.message);}
  }
  async importReview(){
    if(this.busy())return;
    const project=this.owner.studio?.project;
    if(!project?.id)return;
    this.uploading=true;this.render();
    try{
      const shot=await this.fetch('/zura/studio/switch-x/review',{project:project.id});
      Object.assign(this.config,{source:shot.source,matte:shot.matte,whiteMeans:shot.whiteMeans,maskChannel:'luma'});
      this.compareTime=0;this.view='matte';this.save();this.message('Using the approved Character Replacement clip and matte.');
    }catch(e){this.message(e.message);}finally{this.uploading=false;this.render();}
  }
  async upload(key,files){
    if(this.busy()||!files.length)return;
    if(key==='refs'&&files.length>4){this.message('Select up to four reference images.');return;}
    this.uploading=true;this.render();
    try{
      const paths=[];
      for(const file of files){
        this.message('Importing '+file.name+'…');
        const body=new FormData();
        body.append('image',file);body.append('subfolder','switch_x_inputs');body.append('overwrite','false');
        const res=await this.api.fetchApi('/upload/image',{method:'POST',body});
        if(!res.ok)throw Error('Could not import '+file.name);
        const data=await res.json();paths.push([data.subfolder,data.name].filter(Boolean).join('/'));
      }
      if(key==='refs'){
        this.config.pinnedFrames=Object.fromEntries(Object.entries(this.config.pinnedFrames||{}).filter(([path])=>paths.includes(path)));
      }
      this.config[key]=key==='refs'?paths:paths[0];if(key==='source'||key==='matte'){this.compareTime=0;this.view=key;}this.message('');this.save();
    }catch(e){this.message(e.message);}finally{this.$(key).value='';this.uploading=false;this.render();}
  }
  async buildGraph(){
    const source=await this.fetch('/zura/studio/switch-x/source',{source:this.config.source,side:this.config.side});
    if(this.config.method==='native')return nativeSwitchGraph(this.config,source);
    const selectedAudio=this.config.audioMode==='upload'?this.config.audioFile:
      this.config.audioMode==='mute'?'':source.hasAudio?this.config.source:'';
    if(this.config.audioMode==='upload'&&!selectedAudio)throw Error('Choose the dialogue recording.');
    const {graph}=await this.fetch('/zura/studio/switch-x/graph',{...this.config,selectedAudio});
    if(graph.finish?.class_type!=='ZuraSwitchXDeliver')throw Error('Restart ComfyUI to load the current Switch X backend.');
    return graph;
  }
  async run(){
    if(this.busy())return;
    if(!this.config.source||this.config.method==='masked'&&!this.config.matte||(!this.config.prompt.trim()&&!this.config.refs.length)){this.message('Add the footage and scene direction. Mask-guided Ref2VA also needs a keep matte.');return;}
    this.submitting=true;this.render();this.message('Checking the shot and audio…');
    try{
      const graph=await this.buildGraph();
      await submitOwnedGraph(this,graph,{...this.config},'auto',{zura_switch_x:true});
    }catch(e){this.message(e.status===404?'Restart ComfyUI to load the Zura SwitchX backend.':e.message);}
    finally{this.submitting=false;this.render();}
  }
  open(){this.api.addEventListener('progress',this.progressHandler);this.disposed=false;this.render();if(this.job||this.pendingSubmission)this.startPolling();}
  close(){this.api.removeEventListener('progress',this.progressHandler);this.disposed=true;this.stopPolling();this.$('preview').pause();}
  startPolling(){if(!this.timer)this.timer=setInterval(()=>void this.poll(),2000);}
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  async poll(){
    if(this.polling)return;
    if(!this.job){if(this.pendingSubmission)await recoverOwnedSubmission(this);else this.stopPolling();return;}
    this.polling=true;
    try{
      const job=this.job;
      const item=(await this.fetch('/history/'+job.id))[job.id];
      if(!item)return;
      const out=item.outputs?.finish;
      const native=item.outputs?.save?.images?.[0];
      if(out?.master?.[0]&&out?.videos?.[0]){
        this.result={master:out.master[0],preview:out.videos[0]};this.view='result';this.message('Shot ready.');
      }else if(native?.filename){
        this.result={master:{filename:native.filename,subfolder:native.subfolder||'',type:'output'},
          preview:native.preview||native};this.view='result';this.message('Shot ready.');
      }else{
        const err=item.status?.messages?.findLast(m=>m[0]==='execution_error');
        this.message(err?.[1]?.exception_message||'The render stopped before export.');
      }
      this.job=null;this.$('progress-title').textContent='';this.$('progress-detail').textContent='';
      this.stopPolling();this.save();this.render();
    }catch(e){this.message(e.message);}finally{this.polling=false;}
  }
}

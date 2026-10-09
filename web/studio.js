import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const ROOT = "/zura/studio";
const defaults = {engine:"local", background:"keep", scope:"person", prompt:"", start:0, duration:2, size:512, performer:-1, margin:8, pitch:false, seed:42, render_size:0, h3_preset:"take_fast", remove_text:false, resolution:1280, quality:"fast", audio_id:"", audio_start:0, length_mode:"custom"};
const icon = (name) => {
  const paths = {
    upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
    play:'<path d="m9 5 11 7-11 7V5Z"/>',
    frames:'<rect x="3" y="3" width="14" height="14" rx="2"/><path d="M8 21h11a2 2 0 0 0 2-2V8M7 8h6M7 12h3"/>',
    arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    download:'<path d="M12 3v13m-5-5 5 5 5-5M4 18v3h16v-3"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    close:'<path d="m6 6 12 12M6 18 18 6"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${paths[name] || paths.frames}</svg>`;
};
const escape = (text) => String(text ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function request(path, body, method="POST") {
  const response = await api.fetchApi(ROOT + path, body === undefined ? {} : {
    method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(body),
  });
  let data;
  try { data = await response.json(); } catch { throw new Error("ComfyUI is restarting. Wait a moment, then reopen Zura Studio."); }
  if (!response.ok) throw new Error(data.error || "This action could not complete. Try again when ComfyUI is ready.");
  return data;
}

class ArtistStudio {
  constructor() {
    this.project = null; this.source = null; this.character = null; this.audio = null; this.busy = false;
    this.config = {...defaults}; this.preview = "mask"; this.lastVideo = null;
    this.container = document.createElement("section");
    this.container.id = "genj-studio"; this.container.setAttribute("aria-label", "Zura Studio");
    this.container.innerHTML = `
      <header class="gs-top"><div class="gs-brand">${icon("frames")}<strong>Zura Studio</strong><span>Character replacement</span></div>
        <div class="gs-top-actions"><span id="gs-models" class="gs-status">Checking models</span><button id="gs-exit" class="gs-quiet" title="Open an editable copy of this stage. Animation uses the visible character look.">Graph view ${icon("arrow")}</button><button id="gs-close" class="gs-icon-button" title="Close Studio and show the current graph" aria-label="Close Studio">${icon("close")}</button></div></header>
      <div class="gs-workspace"><aside class="gs-controls">
        <div class="gs-control-heading"><h1>Create a shot</h1><button id="gs-new" class="gs-icon-button" title="New shot" aria-label="New shot">${icon("plus")}</button></div>
        <div class="gs-upload-group"><label class="gs-label" for="gs-source">Performance video</label>
          <label class="gs-upload" id="gs-source-drop" for="gs-source"><span class="gs-upload-symbol">${icon("upload")}</span><strong>Drop your video here</strong><span>or choose a file · MP4, MOV</span><span class="gs-filename"></span></label>
          <input class="gs-file" id="gs-source" type="file" accept="video/mp4,video/quicktime,video/webm,.mkv" aria-label="Performance video"/>
        </div>
        <div class="gs-upload-group"><label class="gs-label" for="gs-character">Replacement character</label>
          <label class="gs-upload gs-image-upload" id="gs-character-drop" for="gs-character"><img id="gs-character-image" alt="Replacement character" hidden/><span class="gs-upload-symbol">${icon("plus")}</span><strong>Choose a character image</strong><span>A clear face and the clothing you want</span><span class="gs-filename"></span></label>
          <input class="gs-file" id="gs-character" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Replacement character"/>
        </div>
        <div class="gs-upload-group"><label class="gs-label" for="gs-audio">Reference audio <small>Optional</small></label>
          <label class="gs-upload" id="gs-audio-drop" for="gs-audio"><strong>Choose a separate audio track</strong><span>WAV, MP3, M4A, FLAC</span><span class="gs-filename"></span></label>
          <input class="gs-file" id="gs-audio" type="file" accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg,.aac,.aiff" aria-label="Reference audio"/>
          <audio id="gs-reference-player" controls preload="metadata" hidden aria-label="Preview reference audio"></audio>
          <button id="gs-clear-audio" class="gs-quiet" hidden>Use video's audio instead</button>
          <p id="gs-audio-note" class="gs-note">Uses the video's audio by default. Silent videos work too.</p>
        </div>
        <fieldset><legend>Generate with</legend><div class="gs-segment">
          <label><input type="radio" name="gs-engine" value="local" checked/><span>LTX 2.5 <small>Local</small></span></label>
          <label><input type="radio" name="gs-engine" value="h3"/><span>MiniMax H3 <small>Local</small></span></label>
          <label><input type="radio" name="gs-engine" value="wan"/><span>Wan 2.2 <small>Local</small></span></label>
          <label><input type="radio" name="gs-engine" value="seedance"/><span>Seedance <small>Paid</small></span></label>
        </div></fieldset>
        <div class="gs-two"><label id="gs-quality-setting"><span class="gs-label">Resolution</span><select id="gs-resolution"><option value="512">512 px · small test</option><option value="768">768 px</option><option value="1280">720p · HD</option><option value="1920">1080p · Full HD</option></select></label>
          <div><label><span class="gs-label">Clip length</span><select id="gs-length_mode"><option value="original">Original clip length</option><option value="custom" selected>Custom length</option></select></label><label id="gs-duration-setting"><span class="gs-label">Seconds</span><input id="gs-duration" type="number" min="0.25" max="30" step="0.25" value="2"/></label></div></div>
        <p class="gs-note" id="gs-output-note">Keeps your video's shape. Renders the length you choose from the original footage.</p>
        <label id="gs-sampling-setting" hidden><span class="gs-label">Detail level</span><select id="gs-quality"><option value="fast">Fast · accelerated model</option><option value="detailed">Detailed · full sampling</option></select><small>Changes sampling effort, while resolution and clip length stay as selected.</small></label>
        <p id="gs-h3-setting" class="gs-note" hidden>H3 is experimental: the current method retains clothing but transfers motion poorly. Clips support up to 5 seconds.</p>
        <p id="gs-ltx-setting" class="gs-note">LTX speech timing is still experimental. Wan transferred the talking performance better in our current tests.</p>
        <div class="gs-two"><label><span class="gs-label">Replace</span><select id="gs-scope"><option value="person">Head and body</option><option value="head">Head only</option></select></label>
          <label><span class="gs-label">Background</span><select id="gs-background"><option value="keep">Keep original</option><option value="restyle">Restyle scene</option></select></label></div>
        <label class="gs-prompt"><span class="gs-label">Describe the look <small>Optional</small></span><textarea id="gs-prompt" rows="3" placeholder="For example, a red jacket with natural cinematic lighting"></textarea></label>
        <label class="gs-checkbox"><input id="gs-remove_text" type="checkbox"/><span>Remove on-screen text<small>Adds detected titles and subtitles to the removal mask. Check the orange coverage before continuing.</small></span></label>
        <details class="gs-advanced"><summary>More controls</summary><div class="gs-advanced-body">
          <label><span class="gs-label">Start (seconds)</span><input id="gs-start" type="number" min="0" max="86400" step="0.1" value="0"/></label>
          <label id="gs-audio-start-setting" hidden><span class="gs-label">Reference audio start (seconds)</span><input id="gs-audio_start" type="number" min="0" max="86400" step="0.1" value="0"/><small>Aligned to the start of your selected clip. Shorter tracks are padded with silence.</small></label>
          <div class="gs-two"><label><span class="gs-label">Performer</span><input id="gs-performer" type="number" min="-1" max="63" value="-1"/><small>-1 chooses automatically</small></label>
          <label><span class="gs-label">Mask margin (px)</span><input id="gs-margin" type="number" min="0" max="128" value="8"/></label></div>
          <label><span class="gs-label">Seed</span><input id="gs-seed" type="number" min="0" max="9007199254740991" value="42"/></label>
          <label class="gs-checkbox"><input id="gs-pitch" type="checkbox"/><span>Shift guidance vocals +3 semitones<small>The finished video keeps your original soundtrack.</small></span></label>
          <p class="gs-note">Wan handles camera cuts automatically. Use one continuous shot with LTX and H3.</p>
          <label><span class="gs-label">Open in graph view</span><select id="gs-graph-stage"><option value="auto">Current stage</option><option value="prepare">Prepare and review</option><option value="design">Character preview</option><option value="animate">Animation · use this look</option><option value="draft">Seedance draft · paid when queued</option><option value="final">Seedance final · paid when queued</option></select><small>Opens an editable copy in a new ComfyUI tab. Graph edits stay in that workflow. Opening a graph does not start a render.</small></label>
        </div></details>
        <div class="gs-action-area"><p id="gs-action-note">Add a video and character to get started.</p><button id="gs-primary" class="gs-primary" disabled>Prepare shot ${icon("arrow")}</button><button id="gs-redesign" class="gs-quiet" hidden>Try another character preview</button><button id="gs-cancel" class="gs-quiet gs-cancel" hidden>Stop this job</button></div>
      </aside>
      <main class="gs-main"><nav class="gs-steps" aria-label="Progress"><span data-step="0" class="active">Upload</span><i></i><span data-step="1">Review mask</span><i></i><span data-step="2">Create</span></nav>
        <div class="gs-preview-heading"><div><h2 id="gs-preview-title">Your performance, a new character</h2><p id="gs-preview-description">Upload the shot you want to transform. We’ll follow its motion and keep the original soundtrack.</p></div><div id="gs-preview-tabs" class="gs-tabs" hidden><button data-view="mask" class="active">Mask</button><button data-view="guide">Guidance</button><button data-view="source">Original</button></div></div>
        <div class="gs-canvas" id="gs-canvas"><div class="gs-empty" id="gs-empty">${icon("frames")}<h3>Start with your performance</h3><p>Your previews and finished takes appear here.</p></div><video id="gs-player" controls playsinline preload="metadata" hidden></video><img id="gs-opening" alt="Generated character preview in the original scene" hidden/><div id="gs-working" class="gs-working" hidden><div class="gs-loading-bar"></div><strong id="gs-working-title">Preparing your shot</strong><span id="gs-working-detail">Running in ComfyUI</span></div></div>
        <div id="gs-message" class="gs-message" role="status" aria-live="polite" hidden></div>
        <section class="gs-results" id="gs-results" hidden><div class="gs-section-heading"><h2>Your takes</h2><span>The original soundtrack is restored automatically.</span></div><div id="gs-takes"></div></section>
        <section class="gs-library"><div class="gs-section-heading"><h2>Recent shots</h2><button id="gs-refresh" class="gs-quiet">Refresh</button></div><div id="gs-library-list"><p class="gs-note">Your shots are saved on this computer. You can return to them later.</p></div></section>
      </main></div>`;
    this.bind();this.syncForm();
  }
  $(id) { return this.container.querySelector("#gs-" + id); }
  message(text, error=false) {
    const el=this.$("message"); el.hidden=!text; el.textContent=text || "";
    el.classList.toggle("is-error", error);
  }
  readConfig() {
    const c={...this.config};
    for (const key of ["scope","background","prompt","length_mode"]) c[key]=this.$(key).value;
    for (const key of ["start","duration","resolution","performer","margin","seed","audio_start"]) c[key]=Number(this.$(key).value);
    c.audio_id=this.audio?.id || "";
    if(c.length_mode==="original")c.start=0;
    c.engine=this.container.querySelector('input[name="gs-engine"]:checked').value;
    c.quality=this.$("quality").value;
    c.h3_preset=c.quality==="fast"?"take_fast":"take_quality";
    c.size=this.config.size ?? 512;c.render_size=0;
    if(c.engine==="h3" || c.engine==="wan")c.background="keep";
    c.pitch=this.$("pitch").checked; c.remove_text=this.$("remove_text").checked; return c;
  }
  bind() {
    this.$("exit").onclick=()=>this.graphView(); this.$("close").onclick=()=>this.close(); this.$("new").onclick=()=>this.reset();
    this.$("clear-audio").onclick=()=>this.perform(async()=>{
      const config={...this.readConfig(),audio_id:"",audio_start:0};
      if(this.project)this.project=await request(`/projects/${this.project.id}/config`,{config});
      this.audio=null;this.config=config;this.syncForm();this.render();
    });
    this.$("primary").onclick=()=>this.primary();
    this.$("redesign").onclick=()=>this.perform(async()=>{
      this.config={...this.readConfig(),seed:Math.floor(Math.random()*2**48)};this.syncForm();
      this.project=await request(`/projects/${this.project.id}/config`,{config:this.config});
      await this.run("design");
    });
    this.$("refresh").onclick=()=>this.loadLibrary();
    this.$("cancel").onclick=()=>this.perform(async()=>{
      this.project=await request(`/projects/${this.project.id}/cancel`,{});this.render();
    });
    for (const type of ["source","character","audio"]) {
      this.$(type).onchange=e=>this.upload(type,e.target.files[0]);
      const drop=this.$(type+"-drop");
      drop.ondragover=e=>{e.preventDefault();drop.classList.add("dragging");};
      drop.ondragleave=()=>drop.classList.remove("dragging");
      drop.ondrop=e=>{e.preventDefault();drop.classList.remove("dragging");this.upload(type,e.dataTransfer.files[0]);};
    }
    this.$("preview-tabs").querySelectorAll("button").forEach(button=>button.onclick=()=>{
      this.preview=button.dataset.view;this.render();
    });
    this.$("library-list").onclick=e=>{
      const button=e.target.closest("[data-project]");if(button)this.loadProject(button.dataset.project);
    };
    this.container.querySelectorAll("select,textarea,input:not([type=file])").forEach(input=>{
      if(input.id==="gs-graph-stage")return;
      input.addEventListener("change",()=>this.perform(async()=>{
        this.config=this.readConfig();
        if(this.project)this.project=await request(`/projects/${this.project.id}/config`,{config:this.config});
        this.render();
      }));
    });
  }
  async perform(fn) {
    if(this.busy)return;
    this.busy=true;this.message("");this.render();
    try { await fn(); } catch(e) { this.message(e.message,true); }
    finally { this.busy=false;this.render(); }
  }
  async upload(type,file) {
    if(!file || this.project?.phase==="working")return;
    await this.perform(async()=>{
      const form=new FormData();form.append("file",file);
      this.message("Uploading to your local ComfyUI…");
      const r=await api.fetchApi(`${ROOT}/upload?kind=${type==="source"?"video":type==="audio"?"audio":"image"}`,{method:"POST",body:form});
      const asset=await r.json();if(!r.ok)throw new Error(asset.error || "The upload could not complete.");
      asset.url=api.apiURL("/view?"+new URLSearchParams({filename:asset.file.split("/").pop(),subfolder:asset.file.split("/").slice(0,-1).join("/"),type:"input"}));
      if(type==="audio"){
        const config={...this.readConfig(),audio_id:asset.id,audio_start:0};
        if(this.project)this.project=await request(`/projects/${this.project.id}/config`,{config});
        this.audio=asset;this.config=config;this.syncForm();
      }else{
        this[type]=asset;this.project=null;localStorage.removeItem("genj-studio-project");this.lastVideo=null;
      }
      if(type==="source"){this.config.duration=Math.min(2,asset.duration);this.config.start=0;this.syncForm();}
      this.message("");this.render();
    });
  }
  async run(action) {
    const body={action,request_key:crypto.randomUUID(),client_id:api.clientId,
      auth_token_comfy_org:api.authToken,api_key_comfy_org:api.apiKey};
    this.project=await request(`/projects/${this.project.id}/action`,body);
    this.render();
  }
  async graphView() {
    if(!this.project && (!this.source || !this.character)){this.close();return;}
    await this.perform(async()=>{
      this.config=this.readConfig();
      if(!this.project){
        this.project=await request("/projects",{source:this.source.id,character:this.character.id,config:this.config});
        localStorage.setItem("genj-studio-project",this.project.id);
      }else if(this.project.phase!=="working"){
        this.project=await request(`/projects/${this.project.id}/config`,{config:this.config});
      }
      const stage=this.$("graph-stage").value;
      const exported=await request(`/projects/${this.project.id}/graph?stage=${encodeURIComponent(stage)}`);
      if(typeof app.loadApiJson!=="function")throw new Error("Update the ComfyUI frontend to open editable API graphs.");
      await app.loadApiJson(exported.graph,`${exported.name} · ${crypto.randomUUID().slice(0,8)}.json`);
      this.close();
    });
  }
  async primary() {
    await this.perform(async()=>{
      this.config=this.readConfig();
      if(this.project?.phase==="done"){
        this.config.seed=Math.floor(Math.random()*2**48);this.syncForm();
      }
      if(!this.project){
        this.project=await request("/projects",{source:this.source.id,character:this.character.id,config:this.config});
        localStorage.setItem("genj-studio-project",this.project.id);
      } else {
        this.project=await request(`/projects/${this.project.id}/config`,{config:this.config});
      }
      const p=this.project;
      if(!p.review || p.phase==="new" || p.prepared_key!==p.approval && p.phase!=="review")return this.run("prepare");
      if(p.phase==="review"){
        await this.run("approve");
        if(this.config.engine!=="seedance")await this.run("design");
        return;
      }
      if(this.config.engine!=="seedance")return this.run(p.opening_input?"animate":"design");
      return this.run(p.phase==="draft" && p.draft_task?"final":"draft");
    });
  }
  syncForm() {
    const resolution=String(this.config.resolution ?? defaults.resolution);
    for(const option of this.$("resolution").querySelectorAll("option[data-saved]"))option.remove();
    if(!Array.from(this.$("resolution").options).some(option=>option.value===resolution)){
      const option=document.createElement("option");option.value=resolution;
      option.textContent=resolution+" px · saved setting";option.dataset.saved="true";
      this.$("resolution").append(option);
    }
    for(const key of ["scope","background","prompt","start","duration","resolution","performer","margin","seed","quality","audio_start","length_mode"])this.$(key).value=this.config[key] ?? defaults[key];
    this.container.querySelector(`input[name="gs-engine"][value="${this.config.engine}"]`).checked=true;
    this.$("pitch").checked=this.config.pitch;
    this.$("remove_text").checked=!!this.config.remove_text;
    this.$("sampling-setting").hidden=!["h3","wan"].includes(this.config.engine);
  }
  reset() {
    if(this.project?.phase==="working"){this.message("Wait for this shot to finish, or stop its job first.",true);return;}
    this.project=null;this.source=null;this.character=null;this.audio=null;this.config={...defaults};this.lastVideo=null;
    localStorage.removeItem("genj-studio-project");this.syncForm();this.message("");this.render();
  }
  async loadProject(id) {
    await this.perform(async()=>{
      this.project=await request("/projects/"+id);
      this.source=this.project.source;this.character=this.project.character;this.audio=this.project.audio || null;this.config={...defaults,...this.project.config};
      if(this.project.config.resolution==null)this.config.resolution=this.project.config.render_size || this.project.config.size || 512;
      if(this.project.config.quality==null)this.config.quality=this.project.config.h3_preset?.endsWith("_quality")?"detailed":"fast";
      localStorage.setItem("genj-studio-project",id);this.syncForm();this.lastVideo=null;this.render();
    });
  }
  async loadLibrary() {
    try{
      const projects=await request("/projects");
      this.$("library-list").innerHTML=projects.length?projects.slice(0,12).map(p=>`<button class="gs-library-row" data-project="${escape(p.id)}"><span>${escape(p.name)}</span><small>${escape(({new:"Ready to prepare",review:"Mask ready",approved:"Ready to create",opening:"Character preview",working:"Rendering",draft:"Draft ready",done:"Finished",error:"Needs attention"})[p.phase] || p.phase)}</small>${icon("arrow")}</button>`).join(""):'<p class="gs-note">Your shots are saved on this computer. You can return to them later.</p>';
    }catch(e){this.message(e.message,true);}
  }
  render() {
    this.$("sampling-setting").hidden=!["h3","wan"].includes(this.config.engine);
    this.$("h3-setting").hidden=this.config.engine!=="h3";
    this.$("ltx-setting").hidden=this.config.engine!=="local";
    if(["h3","wan"].includes(this.config.engine))this.$("background").value="keep";
    this.$("output-note").textContent=this.config.engine==="seedance"?"The draft uses your selected resolution and clip length. Finishing an accepted draft is a separate paid 1080p step.":"Keeps your video's shape. Renders the length you choose from the original footage.";
    for(const option of this.$("resolution").options){
      option.disabled=this.config.engine==="seedance" && option.value==="768";
      if(option.value==="512")option.textContent=this.config.engine==="seedance"?"480p · small test":"512 px · small test";
    }
    this.updateModelStatus();
    this.$("audio-start-setting").hidden=!this.audio;
    const referencePlayer=this.$("reference-player");referencePlayer.hidden=!this.audio;
    if(this.audio && referencePlayer.getAttribute("src")!==this.audio.url)referencePlayer.src=this.audio.url;
    if(!this.audio && referencePlayer.hasAttribute("src")){referencePlayer.pause();referencePlayer.removeAttribute("src");referencePlayer.load();}
    this.$("clear-audio").hidden=!this.audio;
    this.$("clear-audio").disabled=this.busy || this.project?.phase==="working";
    this.$("exit").disabled=this.busy;
    this.$("audio-note").textContent=this.audio?(this.config.engine==="wan"?
      "Wan adds this soundtrack to the result. Its mouth motion follows the driving video; it cannot lip sync to a new audio track.":
      this.config.engine==="seedance"?"Embeds this track in the guidance clip and restores it in the result. Speech timing depends on the model.":
      "Feeds this track into generation and the final soundtrack. LTX and H3 support audio guidance; lip sync is experimental."):
      "Uses the video's audio by default. Silent videos work too.";
    const p=this.project,working=p?.phase==="working",phase=p?.phase || "new";
    this.$("duration-setting").hidden=this.config.length_mode==="original";
    const originalOption=this.$("length_mode").querySelector('option[value="original"]');
    originalOption.textContent="Original clip length"+(this.source?.duration?` · ${Number(this.source.duration).toFixed(2)}s`:"");
    for(const type of ["source","character","audio"]){
      const drop=this.$(type+"-drop"),asset=this[type];drop.classList.toggle("has-file",!!asset);
      drop.querySelector(".gs-filename").textContent=asset?.name || "";
      this.$(type).disabled=working || this.busy;
    }
    const char=this.$("character-image");char.hidden=!this.character;
    if(this.character && char.getAttribute("src")!==this.character.url)char.src=this.character.url;
    this.container.querySelectorAll("select,textarea,input:not([type=file])").forEach(el=>el.disabled=(el.id==="gs-graph-stage"?false:working) || this.busy);
    if(["h3","wan"].includes(this.config.engine))this.$("background").disabled=true;
    if(this.config.length_mode==="original"){this.$("start").value=0;this.$("start").disabled=true;}
    const btn=this.$("primary"),hasAssets=!!this.source && !!this.character;
    let label="Prepare shot",note="Add a video and character to get started.";
    if(hasAssets)note="We’ll find the performer and show you the mask before generation.";
    if(p?.phase==="review"){label=this.config.engine!=="seedance"?"Use this mask & create look":"Use this mask";note="Watch the full mask and guidance previews before continuing. The orange area will be replaced.";}
    else if(p?.approval && phase!=="new"){
      if(this.config.engine!=="seedance"){
        label=p.opening_input?(phase==="done"?"Generate another take":"Animate this look"):"Create character preview";
        note=p.opening_input?"Check the character, pose and background. Then animate this look locally.":"We’ll create the opening frame automatically from your character image.";
        if(this.config.engine==="h3" && p.opening_input)note="H3 uses this opening frame and your character image separately, with the approved mask and original performance.";
        if(this.config.engine==="wan" && p.opening_input)note="Wan uses your approved look, character reference, motion and mask. Preparation runs automatically.";
      }else{
        label=phase==="draft"&&p.draft_task?"Finish at 1080p · Paid":"Generate draft · Paid";
        note=phase==="draft"?"Watch the whole draft. Finishing at 1080p is a separate paid Comfy render.":"Uses your Comfy credits and uploads the character and guidance clip to Seedance.";
      }
    }
    if(working){label="Working on your shot";note="You can close this view and return later. The job is saved.";}
    if(this.busy && !working)label="Please wait";
    btn.innerHTML=escape(label)+icon(working?"frames":"arrow");btn.disabled=!hasAssets || working || this.busy;
    this.$("action-note").textContent=note;this.$("cancel").hidden=!working;this.$("cancel").disabled=this.busy;
    this.$("redesign").hidden=working || this.config.engine==="seedance" || !p?.opening_input;
    this.$("redesign").disabled=this.busy;
    this.$("working").hidden=!working;
    const stage=p?.actions?.at(-1)?.stage;
    this.$("working-title").textContent=({prepare:"Finding and tracking the performer",design:"Creating your character preview",video_text:"Preparing the video prompt",h3_references:"Preparing the character and performance references",wan_prepare:"Preparing Wan motion and character",wan:"Replacing the performer with Wan 2.2",background:"Replacing the performer",restyle:"Restyling your shot",h3:"Replacing the performer with MiniMax H3",draft:"Generating the Seedance draft",final:"Rendering the accepted take at 1080p"})[stage] || "Working on your shot";
    this.$("working-detail").textContent=p?.actions?.at(-1)?.state==="queued"?"Waiting in the ComfyUI queue":"Running in ComfyUI. Your shot is saved.";
    this.$("preview-tabs").hidden=!p?.review || phase==="opening" || phase==="done" || phase==="draft";
    this.$("preview-tabs").querySelectorAll("button").forEach(b=>b.classList.toggle("active",b.dataset.view===this.preview));
    let video=this.source?.url,opening=null,title="Your performance, a new character",description="Upload the shot you want to transform. We’ll follow its motion and keep the original soundtrack.";
    if(p?.review){video=({mask:p.mask_url,guide:p.guide_url,source:p.selected_url})[this.preview];title="Check the selection";description=this.config.remove_text?"Watch the full clip. The orange mask should cover the performer and all titles and subtitles you want removed.":"Watch the full clip. Make sure the orange mask covers the performer throughout the shot.";}
    if(phase==="opening"){opening=p.opening_url;video=null;title="Your character in the scene";description="Check the face, clothing, pose and background. This frame guides the local video.";}
    if((phase==="draft" || phase==="done") && p.results?.length){video=p.results.at(-1).url;title=phase==="draft"?"Review your draft":"Your finished take";description="The selected soundtrack is restored. Watch the entire take before keeping it.";}
    this.$("preview-title").textContent=title;this.$("preview-description").textContent=description;
    const player=this.$("player"),image=this.$("opening");player.hidden=!video;image.hidden=!opening;
    if(video && video!==this.lastVideo){player.src=video;player.load();this.lastVideo=video;}
    if(!video && this.lastVideo){player.pause();player.removeAttribute("src");player.load();this.lastVideo=null;}
    if(opening && image.getAttribute("src")!==opening)image.src=opening;
    this.$("empty").hidden=!!video || !!opening;
    const step=!p?.review?0:phase==="review"?1:2;
    this.container.querySelectorAll("[data-step]").forEach(e=>{e.classList.toggle("active",Number(e.dataset.step)===step);e.classList.toggle("complete",Number(e.dataset.step)<step);});
    if(p?.error)this.message(p.error,true);
    const results=p?.results || [];this.$("results").hidden=!results.length;
    const fingerprint=JSON.stringify(results);
    if(this.resultFingerprint!==fingerprint){
      this.resultFingerprint=fingerprint;
      this.$("takes").innerHTML=results.slice().reverse().map((item,i)=>`<article class="gs-take"><video src="${escape(item.url)}" controls playsinline preload="metadata"></video><div><span>${escape((({wan:"Wan 2.2",h3:"MiniMax H3",draft:"Seedance draft",final:"Seedance final",background:"LTX · original background",restyle:"LTX · scene restyle"})[item.stage] || "Take")+(item.resolution?` · ${item.resolution} px` : "")+(item.duration?` · ${item.duration}s` : ""))}</span><a href="${escape(item.url)}" download="zura-take-${results.length-i}.mp4">${icon("download")} Download</a></div></article>`).join("");
    }
  }
  async open() {
    if(!this.container.isConnected)document.body.appendChild(this.container);
    document.documentElement.classList.add("genj-open");this.render();
    try{
      this.modelStatus=await request("/status");this.updateModelStatus();
    }catch(e){this.message(e.message,true);}
    const saved=localStorage.getItem("genj-studio-project");
    if(saved && !this.project)await this.loadProject(saved);
    await this.loadLibrary();
    clearInterval(this.timer);this.timer=setInterval(()=>this.poll(),2000);
  }
  updateModelStatus() {
    if(!this.modelStatus)return;
    const engine=this.config.engine;
    const ready=engine==="seedance" || (this.modelStatus.engine_ready?.[engine] ?? (engine==="local" && this.modelStatus.ready));
    this.$("models").textContent=engine==="seedance"?"Uses Comfy credits":ready?(engine==="h3"?"H3 · experimental":engine==="wan"?"Wan models ready":"LTX models ready"):"Model setup needs attention";
    this.$("models").classList.toggle("needs-attention",!ready);
  }
  async poll() {
    const awaiting=this.project?.actions?.at(-1)?.state==="interrupted";
    if(!this.container.isConnected || this.busy || this.polling || !this.project || this.project.phase!=="working" && !awaiting)return;
    this.polling=true;
    try{
      const prior=this.project.phase;this.project=await request("/projects/"+this.project.id);this.render();
      if(prior!==this.project.phase)await this.loadLibrary();
    }catch(e){this.message("Connection interrupted. Your job is saved. Reopen this view when ComfyUI reconnects.",true);}
    finally{this.polling=false;}
  }
  close(){this.container.querySelectorAll("video,audio").forEach(media=>media.pause());this.container.remove();document.documentElement.classList.remove("genj-open");clearInterval(this.timer);}
}

app.registerExtension({
  name:"Zura.Artist.Studio",
  async setup(){
    const css=document.createElement("link");css.rel="stylesheet";css.href=new URL("./studio.css",import.meta.url).href;document.head.appendChild(css);
    const studio=new ArtistStudio();
    const button=document.createElement("button");button.id="genj-studio-launch";button.innerHTML=icon("frames")+"Zura Studio";button.title="Switch to Studio view";
    button.onclick=()=>studio.open();document.body.appendChild(button);
    const studioQuery=new URLSearchParams(location.search);
    if(studioQuery.get("zura")==="1" || studioQuery.get("genj")==="1")await studio.open();
  },
});

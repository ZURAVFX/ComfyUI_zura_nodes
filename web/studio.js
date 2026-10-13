import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { tidyArtistGraph, trimStageSignals } from "./artist_graph.js";
import { attachWanGraphControls } from "./wan_graph.js";
import { stageProgress } from "./studio_progress.js";
import { ContentDetection } from "./studio_content.js";
import { clipLength, recoverClipLength } from "./studio_length.js";

const ROOT = "/zura/studio";
const defaults = {engine:"local", background:"keep", scope:"person", prompt:"", start:0, duration:2, size:512, performer:-1, margin:20, pitch:false, seed:42, render_size:0, h3_preset:"take_fast", h3_steps:0, remove_text:false, resolution:1280, delivery_mode:"native", quality:"fast", audio_id:"", audio_start:0, length_mode:"custom", lip_sync:false, refine_lips:false, workflow_mode:"motion", edit_area:"mask", mask_method:"auto", mask_prompt:"person", mask_points:[],subject_mode:"auto",finished_frame_position:"first",finished_frame_number:1};
const icon = (name) => {
  const paths = {
    upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
    play:'<path d="m9 5 11 7-11 7V5Z"/>',
    frames:'<rect x="3" y="3" width="14" height="14" rx="2"/><path d="M8 21h11a2 2 0 0 0 2-2V8M7 8h6M7 12h3"/>',
    arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    download:'<path d="M12 3v13m-5-5 5 5 5-5M4 18v3h16v-3"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    reset:'<path d="M3 12a9 9 0 1 0 2.64-6.36L3 8m0-5v5h5"/>',
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

async function tidyWanStage(app, graph, stage) {
  await import("./vendor/elk.bundled.js");
  return tidyArtistGraph(app, graph, stage, window.ELK);
}

class ArtistStudio {
  constructor() {
    this.project = null; this.source = null; this.character = null; this.audio = null; this.busy = false;
    this.references=[];this.readyAsset=null;this.lookMode="build";
    this.config = {...defaults}; this.preview = "mask"; this.lastVideo = null; this.resetEpoch=0;this.resetting=false;
    this.contentDetection=new ContentDetection(body=>request("/content",body),()=>this.render());
    this.container = document.createElement("section");
    this.container.id = "genj-studio"; this.container.setAttribute("aria-label", "Zura Studio");
    this.container.innerHTML = `
      <header class="gs-top"><div class="gs-brand"><img class="gs-zura-mark" alt="" width="40" height="40"/><strong>Zura Studio</strong><span>Video transformations</span></div>
        <div class="gs-top-actions"><span id="gs-models" class="gs-status">Checking models</span><button id="gs-exit" class="gs-quiet" title="Open an editable copy of this stage. Animation uses the visible character look.">Graph view ${icon("arrow")}</button><button id="gs-close" class="gs-icon-button" title="Close Studio and show the current graph" aria-label="Close Studio">${icon("close")}</button></div></header>
      <nav class="gs-steps" aria-label="Shot stages"><button type="button" data-step="0" class="active"><strong>Source</strong><small>Add your video</small></button><i></i><button type="button" data-step="1"><strong>Look</strong><small>References & prompt</small></button><i></i><button type="button" data-step="2"><strong>Review</strong><small>Check and confirm</small></button><i></i><button type="button" data-step="3"><strong>Generate</strong><small>Create your video</small></button></nav>
      <div class="gs-workspace"><aside class="gs-controls">
        <div class="gs-control-heading"><h1>Create a shot</h1><button id="gs-new" class="gs-quiet gs-start-over" title="Clear this shot and return to Source. Saved shots and results stay available." aria-label="Start over">${icon("reset")} Start over</button></div>
        <fieldset class="gs-workflow-choice"><legend>Choose a task</legend><div class="gs-segment" role="group" aria-label="Edit mode">
          <label><input type="radio" name="gs-workflow" value="motion" checked/><span>Motion transfer</span></label>
          <label><input type="radio" name="gs-workflow" value="swap"/><span>Object swap</span></label>
          <label><input type="radio" name="gs-workflow" value="viewport"/><span>Viewport to final</span></label>
        </div></fieldset>
        <div class="gs-upload-group"><label class="gs-label" for="gs-source">Source video</label>
          <label class="gs-upload gs-source-upload" id="gs-source-drop" for="gs-source"><img id="gs-source-poster" alt="Loaded video thumbnail" hidden/><video id="gs-source-thumb" muted playsinline preload="auto" hidden aria-label="Loaded source video thumbnail"></video><span class="gs-upload-symbol">${icon("upload")}</span><strong>Drop your video here</strong><span id="gs-source-detail">MP4, MOV, WebM or MKV</span><span class="gs-filename"></span></label>
          <input class="gs-file" id="gs-source" type="file" accept="video/mp4,video/quicktime,video/webm,.mkv" aria-label="Source video"/>
          <span id="gs-content-badge" class="gs-content-badge" role="status" aria-live="polite" hidden></span>
        </div>
        <section class="gs-selection">
          <p id="gs-selection-note" class="gs-note">Rebuild the shot using source movement as a guide. The scene may change.</p>
          <details id="gs-selection-options" class="gs-advanced"><summary id="gs-selection-summary">Person · automatic</summary><div id="gs-mask-options"><label><span class="gs-label">Select an area</span><select id="gs-mask_method"><option value="auto">Person · automatic</option><option value="text">Describe a person or object</option><option value="points">Click to select</option></select></label>
            <label id="gs-auto-mask-setting"><span class="gs-label">Person area</span><select id="gs-scope"><option value="person">Head and body</option><option value="head">Head only</option></select></label>
            <label id="gs-mask-prompt-setting" hidden><span class="gs-label">Area to change</span><input id="gs-mask_prompt" type="text" maxlength="500" placeholder="Red coat, chair, sky…"/></label>
            <div id="gs-mask-points-setting" hidden><button id="gs-select-points" class="gs-quiet">Select on opening frame</button><span id="gs-mask-points-note" class="gs-note">Include the area you want to change. Exclude anything selected by mistake.</span></div>
          </div></details>
        </section>
        <section class="gs-look"><h2>Starting look</h2>
          <div class="gs-segment gs-look-choice" role="group" aria-label="How to create the starting look">
            <label><input type="radio" name="gs-look" value="build" checked/><span>Build from references</span></label>
            <label><input type="radio" name="gs-look" value="ready"/><span>Use finished frame</span></label>
          </div><p id="gs-look-note" class="gs-note">Add people, objects or scene references.</p>
          <div id="gs-ready-group" class="gs-upload-group" hidden>
            <label class="gs-upload gs-image-upload" id="gs-ready-drop" for="gs-ready"><img id="gs-ready-image" alt="Finished reference frame" hidden/><span class="gs-upload-symbol">${icon("plus")}</span><strong>Drop your finished frame</strong><span>Already composed for this shot</span><span class="gs-filename"></span></label>
            <input class="gs-file" id="gs-ready" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Finished reference frame"/>
            <label id="gs-frame-position-setting"><span class="gs-label">Frame position</span><select id="gs-finished_frame_position"><option value="first">First frame</option><option value="last">Last frame</option><option value="frame">Frame number</option></select></label>
            <label id="gs-frame-number-setting" hidden><span class="gs-label">Frame number</span><input id="gs-finished_frame_number" type="number" min="1" step="1" value="1"/></label>
            <p id="gs-frame-anchor-note" class="gs-note"></p>
          </div>
          <div class="gs-upload-group"><label class="gs-label" id="gs-character-label" for="gs-character">Reference images</label>
            <div id="gs-reference-gallery" class="gs-reference-gallery" aria-label="Loaded appearance references"></div>
            <label class="gs-upload gs-reference-upload" id="gs-character-drop" for="gs-character"><span class="gs-upload-symbol">${icon("plus")}</span><strong id="gs-reference-upload-label">Drop one or more images</strong><span class="gs-filename"></span></label>
            <input class="gs-file" id="gs-character" type="file" accept="image/png,image/jpeg,image/webp" multiple aria-label="Appearance reference images"/>
          </div>
        </section>
        <section class="gs-prompt-toggle" id="gs-model-prompt"><label for="gs-prompt" class="gs-label">Prompt <span class="gs-optional">Optional</span></label>
          <textarea id="gs-prompt" rows="3" aria-label="Prompt for the selected model" placeholder="Describe the shot, movement or details to keep"></textarea>
        </section>
      </aside><aside class="gs-settings"><h2>Shot settings</h2>
        <fieldset><legend>Generate with</legend><div class="gs-segment">
          <label><input type="radio" name="gs-engine" value="local" checked/><span>LTX 2.5 <small>Local</small></span></label>
          <label><input type="radio" name="gs-engine" value="h3"/><span>MiniMax H3 <small>Local</small></span></label>
          <label><input type="radio" name="gs-engine" value="wan"/><span>Wan 2.2 <small>Local</small></span></label>
          <label><input type="radio" name="gs-engine" value="seedance"/><span>Seedance <small>Paid</small></span></label>
        </div><p id="gs-engine-hint" class="gs-note"></p>
          <details class="gs-advanced gs-model-help"><summary>Model guide & setup</summary><div class="gs-advanced-body">
            <p class="gs-note"><strong>Wan 2.2:</strong> Start here to keep the original acting, gestures and camera cuts. It can also create a new speech performance from your audio. Longer clips can lose some detail between sections.</p>
            <p class="gs-note"><strong>MiniMax H3:</strong> A strong choice for expressive faces and replacement speech. It also follows the original performance. Start with a short shot and use 1080p Enhanced for the tested high-resolution option.</p>
            <p class="gs-note"><strong>LTX 2.5:</strong> Good for fast, short motion-guided whole-scene shots, with original or replacement audio. Start with five seconds or less. A new environment may lose the source camera move; masked speech remains experimental.</p>
            <p class="gs-note"><strong>Seedance:</strong> Optional paid generation. Check the displayed cost before rendering; it was not included in our local tests.</p>
            <p class="gs-note">Upload an existing voice track or use Create a voice track. The video model uses that audio to guide the face; voice cloning is a separate step.</p>
          <a href="https://github.com/ZURAVFX/ComfyUI_zura_nodes/blob/main/INSTALL_STUDIO.md" target="_blank" rel="noopener noreferrer">Installation guide</a>
          <details class="gs-advanced"><summary>Installed files & nodes</summary><div class="gs-advanced-body" id="gs-model-checklist"></div></details>
          </div></details>
        </fieldset>
        <div class="gs-two"><label id="gs-quality-setting"><span class="gs-label">Resolution</span><select id="gs-resolution"><option value="512">512 px · small test</option><option value="768">768 px</option><option value="1280">720p · HD</option><option value="1920">1080p · Full HD</option><option value="1920-enhanced">1080p · Enhanced after H3</option></select></label>
          <div><label><span class="gs-label">Clip length</span><select id="gs-length_mode"><option value="original">Original clip length</option><option value="custom" selected>Custom length</option></select></label><label id="gs-duration-setting"><span class="gs-label">Seconds</span><input id="gs-duration" type="number" min="0.25" max="30" step="0.25" value="2"/></label></div></div>
        <label id="gs-trim-start"><span class="gs-label">Start at <small>seconds</small></span><input id="gs-start" type="number" min="0" max="86400" step="0.1" value="0"/></label>
        <details class="gs-advanced"><summary>Output, speed and memory</summary><div class="gs-advanced-body"><p class="gs-note" id="gs-output-note"></p><div class="gs-note" id="gs-system-guidance" aria-live="polite"><p id="gs-hardware-note">Checking this system…</p><p id="gs-limit-note"></p><p id="gs-speed-note"></p><p id="gs-memory-note"></p><p>Measured on an RTX 4080 with 16 GB VRAM and 64 GB RAM. Other systems vary.</p></div></div></details>
        <label id="gs-sampling-setting" hidden><span id="gs-sampling-label" class="gs-label">Detail level</span><select id="gs-quality"><option value="fast">Fast · accelerated model</option><option value="detailed">Detailed · full sampling</option></select><small id="gs-quality-note">Changes sampling effort, while resolution and clip length stay as selected.</small></label>
        <label id="gs-h3-steps-setting" hidden><span class="gs-label">H3 sampling steps</span><input id="gs-h3_steps" type="number" min="4" max="80" step="1" value="8"/><small id="gs-h3-steps-note">8 recommended with Turbo. More steps take longer.</small></label>
        <p id="gs-h3-setting" class="gs-note" hidden></p><p id="gs-ltx-setting" class="gs-note" hidden></p>
        <label class="gs-checkbox"><input id="gs-remove_text" type="checkbox"/><span>Remove on-screen text</span></label>
        <details class="gs-advanced"><summary>More controls</summary><div class="gs-advanced-body">
          <label><span class="gs-label">Subject guidance</span><select id="gs-subject_mode"><option value="auto">Auto · detect from video</option><option value="people">People</option><option value="objects">Objects & scenery</option></select><small>Each model uses its own motion guidance.</small></label>
          <label id="gs-audio-start-setting" hidden><span class="gs-label">Reference audio start (seconds)</span><input id="gs-audio_start" type="number" min="0" max="86400" step="0.1" value="0"/><small>Aligned to the start of your selected clip. Shorter tracks are padded with silence.</small></label>
          <label id="gs-refine-lips-setting" class="gs-checkbox" hidden><input id="gs-refine_lips" type="checkbox"/><span>Refine lips after generation<small>Optional local mouth correction after the model's own speech method. It can soften detail or change the expression.</small></span></label>
          <div class="gs-two"><label><span class="gs-label">Performer</span><input id="gs-performer" type="number" min="-1" max="63" value="-1"/><small>-1 chooses automatically</small></label>
          <label><span class="gs-label">Room around the selection</span><input id="gs-margin" type="number" min="0" max="128" value="20"/><small>Leaves room for hair and clothing. Included in the mask preview.</small></label></div>
          <label><span class="gs-label">Seed</span><input id="gs-seed" type="number" min="0" max="9007199254740991" value="42"/></label>
          <label class="gs-checkbox"><input id="gs-pitch" type="checkbox"/><span>Shift guidance vocals +3 semitones<small>The finished video keeps your original soundtrack.</small></span></label>
          <p class="gs-note">Wan handles camera cuts automatically. Use one continuous shot with LTX and H3.</p>
          <label><span class="gs-label">Open in graph view</span><select id="gs-graph-stage"><option value="auto">Current stage</option><option value="prepare">Prepare and review</option><option value="design">Character preview</option><option value="animate">Animation · use this look</option><option value="h3">H3 base render</option><option value="h3_enhance">H3 1080p enhancement</option><option value="wan_speech">Wan speech performance</option><option value="draft">Seedance draft · paid when queued</option><option value="final">Seedance final · paid when queued</option></select><small>Opens an editable copy in a new ComfyUI tab. Graph edits stay in that workflow. Opening a graph does not start a render.</small></label>
        </div></details>
        <details class="gs-advanced" id="gs-audio-settings"><summary id="gs-audio-summary">Audio · original performance</summary><div class="gs-advanced-body gs-upload-group"><label><span class="gs-label">Audio and performance</span><select id="gs-audio-mode"><option value="original">Original audio + performance</option><option value="reference">Reference audio + new performance</option></select></label>
          <p id="gs-audio-note" class="gs-note">Follows the original facial performance and keeps the video's audio. Silent videos work too.</p>
          <div id="gs-reference-options" hidden><label class="gs-label" for="gs-audio">Reference audio</label>
          <label class="gs-upload" id="gs-audio-drop" for="gs-audio"><strong>Choose audio or a video with audio</strong><span>Your character voice, music or sound effects</span><span class="gs-filename"></span></label>
          <input class="gs-file" id="gs-audio" type="file" accept="audio/*,video/*,.wav,.mp3,.m4a,.flac,.ogg,.aac,.aiff,.mp4,.mov,.mkv,.webm" aria-label="Reference audio"/>
          <audio id="gs-reference-player" controls preload="metadata" hidden aria-label="Preview reference audio"></audio>
          <button id="gs-clear-audio" class="gs-quiet" hidden>Use original audio and performance</button>
          <label id="gs-speech-setting" class="gs-checkbox" hidden><input id="gs-lip_sync" type="checkbox"/><span>Create a new facial performance<small>Untick to use this track as music or sound design.</small></span></label>
          <details class="gs-advanced"><summary>Create a voice track</summary><div class="gs-advanced-body">
            <label><span class="gs-label">Voice</span><select id="gs-voice-mode"><option>Clone a voice</option><option>Text to speech</option></select></label>
            <div id="gs-voice-clone-fields"><label><span class="gs-label">Voice sample</span><input id="gs-voice-sample" type="file" accept="audio/*,video/*"/><small id="gs-voice-sample-name">One clear speaker. A video with audio works too.</small></label>
              <label><span class="gs-label">Words spoken in the sample</span><textarea id="gs-voice-transcript" rows="2"></textarea></label></div>
            <label><span class="gs-label">What should your character say?</span><textarea id="gs-voice-script" rows="3"></textarea></label>
            <button id="gs-create-voice" class="gs-quiet">Create and use this voice track</button>
            <p id="gs-voice-note" class="gs-note">Uses local Zura LongCat. Your sample and words stay on this computer.</p>
          </div></details></div>
        </div></details>
        <div class="gs-action-area"><button id="gs-primary" class="gs-primary" disabled>Prepare shot ${icon("arrow")}</button><p id="gs-action-note" aria-live="polite">Add a video and starting look.</p><button id="gs-redesign" class="gs-quiet" hidden>Try another starting look</button><button id="gs-starting-image" class="gs-quiet" hidden>Replace starting frame</button><input class="gs-file" id="gs-opening-file" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Starting image"/><button id="gs-cancel" class="gs-quiet gs-cancel" hidden>Stop this job</button></div>
      </aside>
      <main class="gs-main">
        <div class="gs-preview-heading"><div><h2 id="gs-preview-title">Your performance, a new character</h2><p id="gs-preview-description">Upload the shot you want to transform. We’ll follow its motion and keep the original soundtrack.</p></div><div id="gs-preview-tabs" class="gs-tabs" hidden><button data-view="mask" class="active">Mask</button><button data-view="guide">Guidance</button><button data-view="source">Original</button></div></div>
        <div class="gs-canvas" id="gs-canvas"><div class="gs-empty" id="gs-empty">${icon("frames")}<h3>Your shot starts here</h3><p>Add a video and a starting look in the controls.</p></div><video id="gs-player" controls playsinline preload="metadata" hidden></video><img id="gs-opening" alt="Starting frame for this shot" hidden/><div id="gs-working" class="gs-working" hidden><div class="gs-progress-heading"><strong id="gs-working-title">Preparing your shot</strong><div class="gs-progress-actions"><span id="gs-working-percent"></span><button id="gs-live-cancel" type="button" class="gs-stop">Cancel run</button></div></div><div id="gs-working-progress" class="gs-loading-bar is-indeterminate" role="progressbar" aria-label="Current stage progress" aria-valuemin="0" aria-valuemax="100"><div id="gs-working-fill"></div></div><div class="gs-progress-caption"><span id="gs-working-detail" role="status" aria-live="polite">Estimating time for this stage…</span><span id="gs-working-meta"></span></div></div></div>
        <div id="gs-message" class="gs-message" role="status" aria-live="polite" hidden></div>
        <section class="gs-results" id="gs-results" hidden><div class="gs-section-heading"><h2>Your takes</h2><span>Your selected soundtrack is restored automatically.</span></div><div id="gs-takes"></div></section>
        <section class="gs-library"><div class="gs-section-heading"><h2>Recent shots</h2><button id="gs-refresh" class="gs-quiet">Refresh</button></div><div id="gs-library-list"><p class="gs-note">Your shots are saved on this computer. You can return to them later.</p></div></section>
      </main></div>`;
    this.bind();this.syncForm();
  }
  $(id) { return this.container.querySelector("#gs-" + id); }
  hasLook(){return this.lookMode==="ready"?!!this.readyAsset:this.references.length>0;}
  referenceRoles(){return this.references.map(a=>a.role||"auto");}
  configBody(config){return {config,reference_roles:this.referenceRoles()};}
  projectBody(){return {source:this.source.id,character:this.character?.id,look_mode:this.lookMode,
    references:this.references.map(a=>a.id),reference_roles:this.references.map(a=>a.role||"auto"),starting_image:this.readyAsset?.id,config:this.config};}
  invalidateLook(){this.character=this.references[0] || this.readyAsset;this.project=null;localStorage.removeItem("genj-studio-project");}
  message(text, error=false) {
    const el=this.$("message"); el.hidden=!text; el.textContent=text || "";
    el.classList.toggle("is-error", error);
  }
  readConfig() {
    const c={...this.config};
    for (const key of ["scope","prompt","length_mode","mask_method","mask_prompt","subject_mode","finished_frame_position"]) c[key]=this.$(key).value;
    c.workflow_mode=this.container.querySelector('input[name="gs-workflow"]:checked').value;
    c.viewport_render=c.workflow_mode==="viewport";
    c.edit_area=c.workflow_mode==="swap"?"mask":"scene";
    for (const key of ["start","duration","performer","margin","seed","audio_start","finished_frame_number"]) c[key]=Number(this.$(key).value);
    const reference=this.$("audio-mode").value==="reference" && !!this.audio;
    c.audio_id=reference?this.audio.id:"";
    if(!reference)c.audio_start=0;
    if(c.length_mode==="original")c.start=0;
    c.engine=this.container.querySelector('input[name="gs-engine"]:checked').value;
    if(!["local","h3"].includes(c.engine) || c.engine==="local" && c.edit_area==="mask")c.finished_frame_position="first";
    let resolution=this.$("resolution").value;
    if(c.engine==="h3" && !["1280","1920","1920-enhanced"].includes(resolution)){
      resolution="1280";this.$("resolution").value=resolution;
    }else if(c.engine!=="h3" && resolution==="1920-enhanced"){
      resolution="1920";this.$("resolution").value=resolution;
    }
    c.resolution=resolution==="1920-enhanced"?1920:Number(resolution);
    c.delivery_mode=c.engine==="h3" && resolution==="1920-enhanced"?"enhanced1080":"native";
    c.quality=this.$("quality").value;
    c.h3_preset=c.quality==="fast"?"take_fast":"take_quality";
    c.h3_steps=Number(this.$("h3_steps")?.value ?? this.config.h3_steps ?? 0);
    c.size=this.config.size ?? 512;c.render_size=0;
    c.background=(c.engine==="local" || c.engine==="seedance") && c.edit_area==="scene"?"restyle":"keep";
    c.pitch=this.$("pitch").checked; c.remove_text=this.$("remove_text").checked;
    c.lip_sync=reference && this.$("lip_sync").checked;
    c.refine_lips=c.lip_sync && this.$("refine_lips").checked; return c;
  }
  bind() {
    this.container.querySelectorAll("[data-step]").forEach(button=>button.onclick=()=>{
      const targets=[this.$("source-drop"),this.container.querySelector(".gs-look"),this.$("canvas"),this.container.querySelector(".gs-settings")];
      const target=targets[Number(button.dataset.step)];target?.scrollIntoView({block:"nearest",behavior:"instant"});
      if(Number(button.dataset.step)===0)this.$("source").focus();
      if(Number(button.dataset.step)===1)this.$(this.lookMode==="ready"?"ready":"character").focus();
      if(Number(button.dataset.step)===3)this.$("primary").focus();
    });
    this.$("exit").onclick=()=>this.graphView(); this.$("close").onclick=()=>this.close(); this.$("new").onclick=()=>this.reset();
    this.$("clear-audio").onclick=()=>this.perform(async(epoch)=>{
      const config={...this.readConfig(),audio_id:"",audio_start:0,lip_sync:false,refine_lips:false};
      if(this.project){const id=this.project.id,updated=await request(`/projects/${id}/config`,this.configBody(config));if(epoch!==this.resetEpoch)return;if(this.project?.id===id)this.project=updated;}
      this.pendingReference=false;this.config=config;this.syncForm();this.render();
    });
    this.$("primary").onclick=()=>this.primary();
    this.$("starting-image").onclick=()=>this.$("opening-file").click();
    this.$("opening-file").onchange=e=>{
      const file=e.target.files[0];e.target.value="";this.upload("opening",file);
    };
    this.$("select-points").onclick=()=>this.perform(()=>this.selectMaskPoints());
    this.$("voice-mode").onchange=()=>{this.$("voice-clone-fields").hidden=this.$("voice-mode").value!=="Clone a voice";};
    this.$("voice-sample").onchange=e=>this.perform(async(epoch)=>{
      const file=e.target.files[0];if(!file)return;
      const form=new FormData();form.append("file",file);
      const r=await api.fetchApi(`${ROOT}/upload?kind=audio`,{method:"POST",body:form});
      if(epoch!==this.resetEpoch)return;
      const asset=await r.json();if(!r.ok)throw new Error(asset.error||"The voice sample could not upload.");
      if(epoch!==this.resetEpoch)return;
      this.voiceSample=asset;this.$("voice-sample-name").textContent=file.name;
    });
    this.$("create-voice").onclick=()=>this.perform(async(epoch)=>{
      if(this.project?.phase==="working"||this.voiceJob)throw new Error("Wait for the current job to finish first.");
      const key=crypto.randomUUID();
      const job=await request("/voice",{request_key:key,client_id:api.clientId,mode:this.$("voice-mode").value,
        script:this.$("voice-script").value,reference_transcript:this.$("voice-transcript").value,
        reference_id:this.voiceSample?.id,seed:this.readConfig().seed%4294967296});
      if(epoch!==this.resetEpoch)return;
      this.voiceJob=job;
      localStorage.setItem("zura-studio-voice-job",this.voiceJob.id);
      this.$("voice-note").textContent="Creating speech in ComfyUI. The track will be selected automatically.";
    });
    this.$("redesign").onclick=()=>this.perform(async(epoch)=>{
      this.config={...this.readConfig(),seed:Math.floor(Math.random()*2**48)};this.syncForm();
      const id=this.project.id,updated=await request(`/projects/${id}/config`,this.configBody(this.config));if(epoch!==this.resetEpoch)return;if(this.project?.id!==id)return;this.project=updated;
      await this.run("design");if(epoch!==this.resetEpoch)return;
    });
    this.$("refresh").onclick=()=>this.loadLibrary();
    this.$("cancel").onclick=()=>this.perform(async(epoch)=>{
      const id=this.project?.id;if(!id)return;
      const stopped=await request(`/projects/${id}/cancel`,{});if(epoch!==this.resetEpoch)return;if(this.project?.id===id)this.project=stopped;this.render();
    });
    this.$("live-cancel").onclick=()=>this.$("cancel").click();
    this.container.querySelectorAll('input[name="gs-look"]').forEach(input=>input.onchange=()=>{
      if(this.busy || this.project?.phase==="working")return;
      this.lookMode=input.value;this.invalidateLook();this.render();
    });
    this.$("reference-gallery").onclick=e=>{
      const button=e.target.closest("[data-remove-reference]");
      if(!button || this.busy || this.project?.phase==="working")return;
      this.references=this.references.filter(a=>a.id!==button.dataset.removeReference);
      this.invalidateLook();this.render();
    };
    this.$("reference-gallery").onchange=e=>{
      const select=e.target.closest("[data-reference-role]");if(!select || this.busy || this.project?.phase==="working")return;
      const reference=this.references.find(a=>a.id===select.dataset.referenceRole);if(!reference)return;
      reference.role=select.value;this.character=this.references[0] || this.readyAsset;
      this.perform(async(epoch)=>{if(this.project){const id=this.project.id,updated=await request(`/projects/${id}/config`,this.configBody(this.readConfig()));if(epoch!==this.resetEpoch)return;if(this.project?.id===id)this.project=updated;}this.render();});
    };
    for (const type of ["source","character","ready","audio"]) {
      this.$(type).onchange=e=>{const files=Array.from(e.target.files);e.target.value="";this.upload(type,type==="character"?files:files[0]);};
      const drop=this.$(type+"-drop");
      drop.ondragover=e=>{e.preventDefault();drop.classList.add("dragging");};
      drop.ondragleave=()=>drop.classList.remove("dragging");
      drop.ondrop=e=>{e.preventDefault();drop.classList.remove("dragging");this.upload(type,type==="character"?Array.from(e.dataTransfer.files):e.dataTransfer.files[0]);};
    }
    this.$("preview-tabs").querySelectorAll("button").forEach(button=>button.onclick=()=>{
      this.preview=button.dataset.view;this.render();
    });
    this.$("library-list").onclick=e=>{
      const button=e.target.closest("[data-project]");if(button)this.loadProject(button.dataset.project);
    };
    this.container.querySelectorAll("select,textarea,input:not([type=file])").forEach(input=>{
      if(input.name==="gs-look"||input.id==="gs-graph-stage"||input.id.startsWith("gs-voice-"))return;
      input.addEventListener("change",()=>this.perform(async(epoch)=>{
        if(input.id==="gs-audio-mode"){
          this.pendingReference=input.value==="reference" && !this.audio;
          this.$("lip_sync").checked=input.value==="reference" && !!this.audio;
          this.$("refine_lips").checked=false;
          if(input.value==="original")this.$("audio_start").value=0;
        }
        this.config=this.readConfig();
        if(["gs-engine","gs-workflow"].includes(input.name))this.syncForm();
        if(input.id==="gs-quality"){this.config.h3_steps=0;this.syncForm();}
        if(input.name==="gs-workflow" && this.config.workflow_mode==="viewport"){
          this.config.engine="h3";
          this.config.resolution=1280;
          this.config.delivery_mode="native";
          this.config.quality="fast";this.config.h3_preset="take_fast";this.config.h3_steps=0;
          this.syncForm();
        }
      if(input.name==="gs-workflow" && this.config.edit_area==="scene")this.config.mask_points=[];
        const pointStart=this.config.length_mode==="original"?0:this.config.start;
        const priorStart=this.project?.config?.length_mode==="original"?0:(this.project?.config?.start ?? this.pointFrameStart ?? pointStart);
        if(["gs-start","gs-length_mode"].includes(input.id) && pointStart!==priorStart)this.config.mask_points=[];
        if(this.project){const id=this.project.id,updated=await request(`/projects/${id}/config`,this.configBody(this.config));if(epoch!==this.resetEpoch)return;if(this.project?.id===id)this.project=updated;}
        this.render();
      }));
    });
  }
  async perform(fn) {
    if(this.busy||this.resetting)return;
    const epoch=this.resetEpoch;
    this.busy=true;this.message("");this.render();
    try { await fn(epoch); } catch(e) { if(epoch===this.resetEpoch)this.message(e.message,true); }
    finally { if(epoch===this.resetEpoch){this.busy=false;this.render();} }
  }
  async selectMaskPoints() {
    if(!this.source || this.project?.phase==="working")return;
    const epoch=this.resetEpoch;
    const video=document.createElement("video");
    video.preload="auto";video.muted=true;video.playsInline=true;video.crossOrigin="anonymous";
    const wait=(event,begin)=>new Promise((resolve,reject)=>{
      const cleanup=()=>{clearTimeout(timer);video.removeEventListener(event,ready);video.removeEventListener("error",failed);};
      const ready=()=>{cleanup();resolve();},failed=()=>{cleanup();reject(new Error("Could not read the opening frame. Re-upload the source video."));};
      const timer=setTimeout(()=>{cleanup();reject(new Error("The opening frame took too long to load. Try again."));},15000);
      video.addEventListener(event,ready,{once:true});video.addEventListener("error",failed,{once:true});begin?.();
    });
    const config=this.readConfig(),start=config.length_mode==="original"?0:config.start;
    try {
      await wait("loadeddata",()=>{video.src=this.source.url;video.load();});
      if(epoch!==this.resetEpoch)return;
      if(start>=video.duration)throw new Error("Choose a start inside your source clip before selecting points.");
      if(start>0)await wait("seeked",()=>{video.currentTime=start;});
      const dialog=document.createElement("dialog");dialog.className="gs-point-dialog";
      dialog.setAttribute("aria-labelledby","gs-point-title");
      dialog.innerHTML=`<h2 id="gs-point-title">Select the area to change</h2><p>Click inside the area to include it. Use Exclude for anything selected by mistake. Zura tracks this selection through the clip.</p><canvas aria-label="Opening frame. Click to place selection points."></canvas><div class="gs-point-tools"><button type="button" data-mode="include" aria-pressed="true">Include</button><button type="button" data-mode="exclude" aria-pressed="false">Exclude</button><button type="button" data-action="undo">Undo</button><button type="button" data-action="clear">Clear</button></div><p data-status role="status" aria-live="polite"></p><div class="gs-point-actions"><button type="button" data-action="cancel">Cancel</button><button type="button" data-action="save">Use these points</button></div>`;
      const canvas=dialog.querySelector("canvas"),context=canvas.getContext("2d");
      const scale=Math.min(1,1280/video.videoWidth);
      canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale));
      const frame=document.createElement("canvas");frame.width=canvas.width;frame.height=canvas.height;
      frame.getContext("2d").drawImage(video,0,0,frame.width,frame.height);
      let include=true,points=(config.mask_points||[]).map(p=>({...p}));
      const draw=()=>{
        context.drawImage(frame,0,0);
        for(const p of points){context.beginPath();context.arc(p.x*canvas.width,p.y*canvas.height,8,0,Math.PI*2);context.fillStyle=p.include?"#bfe586":"#ff8573";context.fill();context.strokeStyle="#111";context.lineWidth=2;context.stroke();}
        const positives=points.filter(p=>p.include).length;
        dialog.querySelector("[data-status]").textContent=`${positives} include, ${points.length-positives} exclude. ${points.length>=32?"Limit reached. Undo or clear a point.":"Up to 32 points."}`;
        dialog.querySelector('[data-action="save"]').disabled=!positives;
      };
      let press=null;
      canvas.addEventListener("pointerdown",event=>{
        if(event.button!==0 || event.isPrimary===false)return;
        press={id:event.pointerId,x:event.clientX,y:event.clientY};
      });
      canvas.addEventListener("pointermove",event=>{
        if(press?.id===event.pointerId && Math.hypot(event.clientX-press.x,event.clientY-press.y)>8)press=null;
      });
      canvas.addEventListener("pointercancel",()=>{press=null;});
      canvas.addEventListener("pointerleave",()=>{press=null;});
      canvas.addEventListener("pointerup",event=>{
        const down=press;press=null;
        if(!down || down.id!==event.pointerId || Math.hypot(event.clientX-down.x,event.clientY-down.y)>8)return;
        if(points.length>=32)return;
        const rect=canvas.getBoundingClientRect();
        points.push({x:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height)),include});draw();
      });
      dialog.querySelectorAll("[data-mode]").forEach(button=>button.onclick=()=>{
        include=button.dataset.mode==="include";
        dialog.querySelectorAll("[data-mode]").forEach(b=>b.setAttribute("aria-pressed",String((b.dataset.mode==="include")===include)));
      });
      dialog.querySelector('[data-action="undo"]').onclick=()=>{points.pop();draw();};
      dialog.querySelector('[data-action="clear"]').onclick=()=>{points=[];draw();};
      dialog.querySelector('[data-action="cancel"]').onclick=()=>dialog.close("cancel");
      dialog.querySelector('[data-action="save"]').onclick=()=>dialog.close("save");
      this.container.append(dialog);this.activeDialog=dialog;draw();
      const choice=await new Promise(resolve=>{dialog.addEventListener("close",()=>{resolve(dialog.returnValue);dialog.remove();if(this.activeDialog===dialog)this.activeDialog=null;},{once:true});dialog.showModal();});
      if(choice!=="save"||epoch!==this.resetEpoch)return;
      const next={...config,mask_method:"points",mask_points:points};
      if(this.project){const id=this.project.id,updated=await request(`/projects/${id}/config`,this.configBody(next));if(epoch!==this.resetEpoch)return;if(this.project?.id===id)this.project=updated;}
      this.config=next;this.pointFrameStart=start;this.preview="mask";this.syncForm();
    } finally {video.pause();video.removeAttribute("src");video.load();}
  }
  async upload(type,file) {
    const files=Array.isArray(file)?file:[file];
    if(!files.length || !files[0] || this.project?.phase==="working")return;
    await this.perform(async(epoch)=>{
      if(type==="opening" && !this.project)throw new Error("Prepare and review the shot before choosing a starting image.");
      if(type==="character" && this.references.length+files.length>9)throw new Error("Use up to nine reference images. Remove one before adding more.");
      for(const file of files){
      const form=new FormData();form.append("file",file);
      this.message("Uploading to your local ComfyUI…");
      const r=await api.fetchApi(`${ROOT}/upload?kind=${type==="source"?"video":type==="audio"?"audio":"image"}`,{method:"POST",body:form});
      if(epoch!==this.resetEpoch)return;
      const asset=await r.json();if(!r.ok)throw new Error(asset.error || "The upload could not complete.");
      if(epoch!==this.resetEpoch)return;
      asset.url=api.apiURL("/view?"+new URLSearchParams({filename:asset.file.split("/").pop(),subfolder:asset.file.split("/").slice(0,-1).join("/"),type:"input"}));
      if(type==="audio"){
        const config={...this.readConfig(),audio_id:asset.id,audio_start:0,lip_sync:true,refine_lips:false};
        if(this.project){const id=this.project.id,updated=await request(`/projects/${id}/config`,this.configBody(config));if(epoch!==this.resetEpoch)return;if(this.project?.id===id)this.project=updated;}
        this.audio=asset;this.pendingReference=false;this.config=config;this.syncForm();
      }else if(type==="opening"){
        if(this.project.phase==="review" && !this.project.approval)await this.run("approve");
        if(epoch!==this.resetEpoch)return;
        if(!this.project.approval)throw new Error("Review and approve the source mask before choosing a starting image.");
        const id=this.project.id,updated=await request(`/projects/${id}/opening`,{asset_id:asset.id});if(epoch!==this.resetEpoch)return;if(this.project?.id===id)this.project=updated;
        this.readyAsset=asset;this.lookMode="ready";this.syncForm();
      }else if(type==="character"){
        if(!this.references.some(a=>a.sha===asset.sha))this.references.push({...asset,role:"auto"});
        this.invalidateLook();
      }else if(type==="ready"){
        this.readyAsset=asset;this.invalidateLook();
      }else{
        this[type]=asset;this.project=null;localStorage.removeItem("genj-studio-project");this.lastVideo=null;
      }
      if(type==="source"){this.config.duration=Math.min(2,asset.duration);this.config.start=0;this.config.mask_points=[];this.pointFrameStart=0;this.syncForm();}
      }
      this.message("");this.render();
    });
  }
  async run(action) {
    const epoch=this.resetEpoch,id=this.project?.id;
    if(!id)return null;
    const body={action,request_key:crypto.randomUUID(),client_id:api.clientId,
      auth_token_comfy_org:api.authToken,api_key_comfy_org:api.apiKey};
    const updated=await request(`/projects/${id}/action`,body);
    if(epoch!==this.resetEpoch||this.project?.id!==id){
      if(updated?.phase==="working"){
        try{
          const stopped=await request(`/projects/${encodeURIComponent(id)}/cancel`,{});
          if(stopped?.phase==="working"&&this.resetEpoch===epoch+1)this.message("The previous shot was cleared, but ComfyUI still reports it as running. Check Recent shots before starting another run.",true);
        }catch{
          if(this.resetEpoch===epoch+1)this.message("The previous shot was cleared, but ComfyUI could not confirm it stopped. Check Recent shots before starting another run.",true);
        }
      }
      return null;
    }
    this.project=updated;
    this.render();
    return updated;
  }
  async graphView() {
    if(!this.project && (!this.source || !this.hasLook())){this.close();return;}
    await this.perform(async(epoch)=>{
      this.config=this.readConfig();
      if(!this.project){
        const created=await request("/projects",this.projectBody());if(epoch!==this.resetEpoch)return;this.project=created;
        localStorage.setItem("genj-studio-project",this.project.id);
      }else if(this.project.phase!=="working"){
        const id=this.project.id,updated=await request(`/projects/${id}/config`,this.configBody(this.config));if(epoch!==this.resetEpoch)return;if(this.project?.id!==id)return;this.project=updated;
      }
      const stage=this.$("graph-stage").value;
      const id=this.project.id,exported=await request(`/projects/${id}/graph?stage=${encodeURIComponent(stage)}`);if(epoch!==this.resetEpoch||this.project?.id!==id)return;
      if(typeof app.loadApiJson!=="function")throw new Error("Update the ComfyUI frontend to open editable API graphs.");
      await app.loadApiJson(exported.graph,`${exported.name} · ${crypto.randomUUID().slice(0,8)}.json`);
      try {
        await import("./vendor/elk.bundled.js");
        await tidyArtistGraph(app,exported.graph,exported.stage,window.ELK);
      } catch(e) {
        await app.loadApiJson(exported.graph,`${exported.name} · editable.json`);
        app.extensionManager?.toast?.add({severity:"warn",summary:"Zura graph view",detail:e.message+" The original editable graph has been restored.",life:10000});
      }
      attachWanGraphControls(app,{projectId:exported.project_id,stage:exported.stage,
        context:exported.context,progress:exported.progress,request,tidy:tidyWanStage});
      this.close();
    });
  }
  async primary() {
    if(this.busy || this.project?.phase==="working")return;
    const selectedConfig=this.readConfig();
    if(clipLength(selectedConfig,this.source?.duration).invalid){
      this.config=recoverClipLength(selectedConfig,this.source.duration);this.syncForm();this.render();
      this.$("duration").scrollIntoView({block:"nearest",behavior:"instant"});this.$("duration").focus();this.$("duration").select();
      this.message("Choose the clip length, then prepare your shot.");return;
    }
    await this.perform(async(epoch)=>{
      if(this.$("audio-mode").value==="reference" && !this.audio)throw new Error("Choose or create a reference audio track first.");
      this.config=this.readConfig();
      if(this.project?.phase==="done"){
        this.config.seed=Math.floor(Math.random()*2**48);this.syncForm();
      }
      if(!this.project){
        const created=await request("/projects",this.projectBody());if(epoch!==this.resetEpoch)return;this.project=created;
        localStorage.setItem("genj-studio-project",this.project.id);
      } else {
        const id=this.project.id,updated=await request(`/projects/${id}/config`,this.configBody(this.config));if(epoch!==this.resetEpoch||this.project?.id!==id)return;this.project=updated;
      }
      const p=this.project;
      if(!p.review || p.phase==="new" || p.prepared_key!==p.approval && p.phase!=="review")return this.run("prepare");
      if(p.phase==="review"){
        await this.run("approve");
        if(epoch!==this.resetEpoch)return;
        const directH3Viewport=this.config.workflow_mode==="viewport" && this.config.engine==="h3";
        if(directH3Viewport)return this.run("h3");
        if(this.config.engine!=="seedance" && this.lookMode!=="ready"){await this.run("design");if(epoch!==this.resetEpoch)return;}
        return;
      }
      if(this.config.engine!=="seedance"){
        if(this.config.workflow_mode==="viewport" && this.config.engine==="h3")return this.run("h3");
        if(this.lookMode==="ready" && !p.opening_input){
          const updated=await request(`/projects/${p.id}/opening`,{asset_id:this.readyAsset.id});if(epoch!==this.resetEpoch||this.project?.id!==p.id)return;this.project=updated;return;
        }
        return this.run(p.opening_input?"animate":"design");
      }
      return this.run(p.phase==="draft" && p.draft_task?"final":"draft");
    });
  }
  defaultReviewPreview(project,wholeScene) {
    if(!project?.review)return;
    const key=project.id+":"+(project.prepared_key || project.review);
    if(key===this.reviewPreviewKey)return;
    this.reviewPreviewKey=key;this.preview=wholeScene?"guide":"mask";
  }
  syncForm() {
    const resolution=this.config.engine==="h3" && this.config.delivery_mode==="enhanced1080"
      ?"1920-enhanced":String(this.config.resolution ?? defaults.resolution);
    for(const option of this.$("resolution").querySelectorAll("option[data-saved]"))option.remove();
    if(!Array.from(this.$("resolution").options).some(option=>option.value===resolution)){
      const option=document.createElement("option");option.value=resolution;
      option.textContent=resolution+" px · saved setting";option.dataset.saved="true";
      this.$("resolution").append(option);
    }
    for(const key of ["scope","prompt","start","duration","performer","margin","seed","quality","audio_start","length_mode","mask_method","mask_prompt","subject_mode","finished_frame_position","finished_frame_number"])this.$(key).value=this.config[key] ?? defaults[key];
    this.$("resolution").value=resolution;
    this.container.querySelector(`input[name="gs-engine"][value="${this.config.engine}"]`).checked=true;
    const workflow=this.config.workflow_mode || (this.config.edit_area==="scene"?"motion":"swap");
    this.container.querySelector(`input[name="gs-workflow"][value="${workflow}"]`).checked=true;
    this.$("model-prompt").open=!!this.config.prompt;
    this.$("pitch").checked=this.config.pitch;
    this.$("remove_text").checked=!!this.config.remove_text;
    this.$("lip_sync").checked=!!this.config.lip_sync;
    this.$("audio-mode").value=this.pendingReference || this.config.audio_id?"reference":"original";
    this.$("refine_lips").checked=!!this.config.refine_lips;
    this.$("h3_steps").value=this.config.h3_steps || (this.config.quality==="fast"?8:40);
    this.$("sampling-setting").hidden=!["h3","wan"].includes(this.config.engine);
    this.container.querySelectorAll('input[name="gs-look"]').forEach(input=>input.checked=input.value===this.lookMode);
  }
  async reset() {
    if(this.resetting)return false;
    const epoch=++this.resetEpoch,project=this.project;
    this.resetting=true;this.busy=true;this.message("");this.render();
    if(project?.phase==="working"){
      try{
        const stopped=await request(`/projects/${encodeURIComponent(project.id)}/cancel`,{});
        if(epoch!==this.resetEpoch)return false;
        if(stopped?.phase==="working")throw new Error("ComfyUI still reports this shot as running. Its files and settings have been kept; try Start over again in a moment.");
        if(this.project?.id===project.id)this.project=stopped;
      }catch(e){
        if(epoch===this.resetEpoch){this.resetting=false;this.busy=false;this.message(e.message||"The current shot could not be stopped, so it has been kept.",true);this.render();}
        return false;
      }
    }
    if(epoch!==this.resetEpoch)return false;
    this.project=null;this.source=null;this.character=null;this.audio=null;this.pendingReference=false;
    this.voiceJob=null;this.voiceSample=null;this.config={...defaults};this.preview="mask";
    this.references=[];this.readyAsset=null;this.lookMode="build";this.referenceFingerprint=null;this.resultFingerprint=null;this.reviewPreviewKey=null;this.pointFrameStart=0;
    this.voicePolling=false;this.polling=false;this.$("audio-settings").open=false;
    if(this.activeDialog?.open)this.activeDialog.close();this.activeDialog=null;
    for(const id of ["source","character","ready","audio","opening-file","voice-sample"]){const field=this.$(id);if(field)field.value="";}
    for(const id of ["source-poster","ready-image","opening"]){const image=this.$(id);image?.removeAttribute("src");}
    this.$("takes").innerHTML="";
    this.$("voice-script").value="";this.$("voice-transcript").value="";this.$("voice-mode").value="Clone a voice";
    this.$("voice-clone-fields").hidden=false;this.$("voice-sample-name").textContent="One clear speaker. A video with audio works too.";
    this.$("voice-note").textContent="Uses local Zura LongCat. Your sample and words stay on this computer.";
    for(const key of ["genj-studio-project","zura-studio-voice-job"]){try{localStorage.removeItem(key);}catch{}}
    this.syncForm();this.resetting=false;this.busy=false;this.message("");this.render();
    this.container.querySelector('[data-step="0"]')?.click();
    return true;
  }
  async loadProject(id) {
    await this.perform(async()=>{
      const epoch=this.resetEpoch,project=await request("/projects/"+id);
      if(epoch!==this.resetEpoch)return;
      this.project=project;
      this.source=this.project.source;this.character=this.project.character;this.audio=this.project.audio || this.project.reference_audio || null;this.pendingReference=false;this.config={...defaults,...this.project.config};
      this.references=this.project.references || [this.character];this.readyAsset=this.project.starting_asset || null;this.lookMode=this.project.look_mode || "build";
      if(!this.project.config.workflow_mode){
        this.config.workflow_mode=this.project.config.edit_area==="scene"||(!this.project.config.edit_area&&this.project.config.background==="restyle")?"motion":"swap";
      }
      if(this.config.workflow_mode==="viewport")this.config.edit_area="scene";
      if(this.project.config.resolution==null)this.config.resolution=this.project.config.render_size || this.project.config.size || 512;
      if(this.config.engine==="h3"){
        if(this.config.resolution!==1920)this.config.resolution=1280;
        this.config.delivery_mode=this.config.resolution===1920&&this.config.delivery_mode==="enhanced1080"?"enhanced1080":"native";
      }else this.config.delivery_mode="native";
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
    this.contentDetection.update(this.source,this.config);
    const content=this.contentDetection.badge(this.config.subject_mode),contentBadge=this.$("content-badge");
    contentBadge.hidden=!this.source;contentBadge.textContent=content.label;contentBadge.title=content.message;
    const workflow=this.config.workflow_mode || (this.config.edit_area==="scene"?"motion":"swap");
    const viewport=workflow==="viewport",wholeScene=this.config.edit_area==="scene",method=this.config.mask_method;
    const wanChoice=this.container.querySelector('input[name="gs-engine"][value="wan"]');
    wanChoice.disabled=viewport;
    wanChoice.closest("label").hidden=viewport && this.config.engine!=="wan";
    this.$("mask-options").hidden=wholeScene;
    this.$("selection-options").hidden=wholeScene;
    this.$("selection-summary").textContent=method==="text"?`Selection · ${this.config.mask_prompt || "describe an area"}`:method==="points"?"Selection · click to choose":"Person · automatic";
    this.$("auto-mask-setting").hidden=method!=="auto";
    this.$("mask-prompt-setting").hidden=method!=="text";
    this.$("mask-points-setting").hidden=method!=="points";
    this.$("selection-note").textContent=viewport?"Finish the full grey viewport scene. No mask is used.":wholeScene?"Rebuild the shot using source movement as a guide. The scene may change.":"Replace the selected area and preserve the rest. Review the selection before continuing.";
    this.$("ready-group").hidden=this.lookMode!=="ready";
    this.$("look-note").textContent=this.lookMode==="ready"?"Use an already-composed frame. No image generation.":viewport&&this.config.engine==="h3"?"H3 reads the blockout and your look references directly. You can skip a starting frame.":viewport?"Build one scene plate from your references. LTX and Wan use the first three for this plate.":"Combine up to three references into one starting frame.";
    this.$("character-label").textContent=this.lookMode==="ready"?"Appearance references · optional":"Reference images";
    this.$("reference-upload-label").textContent=this.references.length?"Add images":"Drop one or more images";
    const readyImage=this.$("ready-image");readyImage.hidden=!this.readyAsset;
    if(this.readyAsset && readyImage.getAttribute("src")!==this.readyAsset.url)readyImage.src=this.readyAsset.url;
    const referenceFingerprint=JSON.stringify(this.references.map(a=>[a.id,a.url,a.name,a.role,viewport]));
    if(referenceFingerprint!==this.referenceFingerprint){
      this.referenceFingerprint=referenceFingerprint;
      this.$("reference-gallery").innerHTML=this.references.map((a,i)=>`<figure><img src="${escape(a.url)}" alt="Reference ${i+1}: ${escape(a.name)}"/><figcaption>${i+1}. ${escape(a.name)}</figcaption>${viewport?`<label class="gs-reference-role-label"><span>Use as</span><select data-reference-role="${escape(a.id)}"><option value="auto" ${a.role==="auto"?"selected":""}>Auto</option><option value="environment" ${a.role==="environment"?"selected":""}>Environment</option><option value="character" ${a.role==="character"?"selected":""}>Character</option><option value="object" ${a.role==="object"?"selected":""}>Object</option><option value="detail" ${a.role==="detail"?"selected":""}>Detail</option><option value="style" ${a.role==="style"?"selected":""}>Style</option></select></label>`:""}<button class="gs-icon-button" data-remove-reference="${escape(a.id)}" aria-label="Remove reference ${i+1}">${icon("close")}</button></figure>`).join("");
    }
    this.$("select-points").disabled=!this.source || this.busy || this.project?.phase==="working";
    const points=this.config.mask_points||[];
    this.$("mask-points-note").textContent=points.length?`${points.filter(p=>p.include).length} include, ${points.filter(p=>!p.include).length} exclude. Tracked from the opening frame.`:"Include the area you want to change. Exclude anything selected by mistake.";
    this.$("create-voice").disabled=!!this.voiceJob||this.busy||this.project?.phase==="working";
    this.$("sampling-setting").hidden=!["h3","wan"].includes(this.config.engine);
    const h3Quality=this.config.engine==="h3";
    this.$("h3-steps-setting").hidden=!h3Quality;
    this.$("sampling-label").textContent=h3Quality?"H3 sampling mode":"Detail level";
    this.$("h3-steps-note").textContent=this.config.quality==="fast"?"8 steps recommended with Turbo. Custom counts are unbenchmarked.":"40 steps is the standard default. Lower counts run faster; check the result.";

    this.$("quality").querySelector('option[value="fast"]').textContent=h3Quality?"Fast · 8 steps (recommended)":"Fast · accelerated model";
    this.$("quality").querySelector('option[value="detailed"]').textContent=h3Quality?"Detailed · 40 steps":"Detailed · full sampling";
    this.$("quality-note").textContent=h3Quality&&this.config.quality==="detailed"?"Standard sampling can take tens of minutes with 16 GB VRAM. Set the step count below; more steps do not guarantee better quality.":"Fast is the tested starting point. Resolution and clip length stay as selected.";
    this.$("h3-setting").hidden=true;this.$("ltx-setting").hidden=true;
    this.$("engine-hint").textContent={
      wan:"Best for people and retaining the original acting.",
      h3:"Strong expressive faces and replacement speech.",
      local:"Start here for objects, environments and short scene changes. Review motion for drift.",
      seedance:"Paid generation using Comfy credits."
    }[this.config.engine] || "";
    if(viewport)this.$("engine-hint").textContent={
      local:"Experimental for blockouts: may retain crude shapes or warp. Use H3 for the best tested result.",
      h3:"Recommended for blockouts. Reads the video and up to nine look references directly; up to five seconds.",
      wan:"This saved shot used Wan, which is no longer available for viewport renders. Choose H3.",
      seedance:"Paid generation using Comfy credits."
    }[this.config.engine] || "";
    const unsupportedSubject=this.config.engine==="wan" && this.config.subject_mode==="objects";
    if(this.config.engine==="wan" && content.kind==="objects")this.$("engine-hint").textContent="Wan is people-focused. H3 or LTX may suit objects and scenery better. Choose People if detection missed someone.";
    this.$("output-note").textContent=this.config.engine==="seedance"?"The draft uses your selected resolution and clip length. Finishing an accepted draft is a separate paid 1080p step.":this.config.engine==="h3"&&this.config.delivery_mode==="enhanced1080"?"H3 creates motion at 720p, then enhances each frame to 1080p. The approved original or selected soundtrack is restored once.":this.config.engine==="h3"?"Native H3 renders at the selected size. Native 1080p is a separate, memory-intensive render.":"Keeps your video's shape. Renders the length you choose from the original footage.";
    for(const option of this.$("resolution").options){
      const h3=this.config.engine==="h3";
      option.hidden=h3&&["512","768"].includes(option.value);
      option.disabled=this.config.engine==="seedance" && option.value==="768";
      if(option.value==="512")option.textContent=this.config.engine==="seedance"?"480p · small test":"512 px · small test";
      if(option.value==="1280")option.textContent=h3?"720p · H3 base":"720p · HD";
      if(option.value==="1920")option.textContent=h3?"1080p · Native H3":"1080p · Full HD";
      if(option.value==="1920-enhanced"){
        option.hidden=!h3;option.textContent="1080p · Enhanced H3";
      }
    }
    const timedFrames=this.config.engine==="h3" || this.config.engine==="local" && wholeScene;
    const position=this.$("finished_frame_position");
    for(const option of position.options)option.disabled=!timedFrames && option.value!=="first";
    this.$("frame-number-setting").hidden=!timedFrames || this.config.finished_frame_position!=="frame";
    const frameRange=clipLength(this.config,this.source?.duration);
    if(Number.isFinite(frameRange.frames))this.$("finished_frame_number").max=String(frameRange.frames);
    else this.$("finished_frame_number").removeAttribute("max");
    this.$("frame-anchor-note").textContent=timedFrames?"Frame numbers start at 1 within the selected 24 fps output clip. The image guides that moment; the generated result may vary.":"This route uses the finished image as an appearance reference. Timed image anchors are available with H3 and whole-scene LTX.";
    this.updateModelStatus();
    const capacity=this.modelStatus?.hardware,guide=this.modelStatus?.model_guidance?.[this.config.engine];
    this.$("hardware-note").textContent=capacity?`${capacity.device}${capacity.vram_gib!=null?` · ${capacity.vram_gib} GB VRAM`:" · dedicated VRAM unavailable"}${capacity.ram_gib!=null?` · ${capacity.ram_gib} GB RAM`:""}`:"Checking this system…";
    if(guide){
      this.$("duration").max=String(guide.workflow_max_custom_seconds);
      const startSize=guide.start_resolution===1280?"720p":`${guide.start_resolution} px`;
      const workflowLimit=viewport?(this.config.engine==="h3"?5:this.config.engine==="local"?15:30):guide.workflow_max_custom_seconds;
      this.$("duration").max=String(viewport?workflowLimit:guide.workflow_max_custom_seconds);
      this.$("limit-note").textContent=`Start with ${guide.start_seconds} seconds at ${startSize}. ${this.config.engine==="wan"?"Custom clips: up to 30 seconds; original length uses sections.":`Clip limit: ${workflowLimit} seconds, including Original clip length.`} Tested: ${guide.tested}.`;
      this.$("speed-note").textContent=this.config.engine==="h3" && this.config.h3_steps && this.config.h3_steps!==(this.config.quality==="fast"?8:40)
        ?`Custom H3 sampling: ${this.config.h3_steps} steps. This count has no measured time or quality benchmark.`
        :guide.quality_guidance?.[this.config.quality]?.reference_speed || guide.reference_speed;
      this.$("memory-note").textContent=this.config.engine==="seedance"?"Generation runs with the paid provider; local VRAM does not set its limits.":"All three local models were tested on a 16 GB GPU with 64 GB RAM. Lower-memory systems are unqualified and may need shorter clips, lower resolution or slower offloading. VRAM alone cannot establish your maximum resolution. LTX's measured peak was about 15.6 GB; exact Wan/H3 peaks were not captured.";
    }else{
      this.$("limit-note").textContent="Workflow limits will appear when ComfyUI reports the selected model.";
      this.$("speed-note").textContent="Speed estimates are unavailable until the local status check completes.";
      this.$("memory-note").textContent="Start with a short test. An exact hardware limit needs a render on this system.";
    }
    const reference=this.$("audio-mode").value==="reference",activeReference=reference && !!this.audio;
    const speechGraphOption=this.$("graph-stage").querySelector('option[value="wan_speech"]');
    speechGraphOption.disabled=this.config.engine!=="wan" || !activeReference || !this.config.lip_sync;
    if(speechGraphOption.disabled && this.$("graph-stage").value==="wan_speech")this.$("graph-stage").value="auto";
    const h3GraphOption=this.$("graph-stage").querySelector('option[value="h3"]');
    h3GraphOption.disabled=this.config.engine!=="h3";
    const enhancementGraphOption=this.$("graph-stage").querySelector('option[value="h3_enhance"]');
    enhancementGraphOption.disabled=this.config.engine!=="h3" || this.config.delivery_mode!=="enhanced1080" || !this.project?.h3_enhancement_ready;
    if(enhancementGraphOption.disabled && this.$("graph-stage").value==="h3_enhance")this.$("graph-stage").value="auto";
    this.$("reference-options").hidden=!reference;
    this.$("audio-mode").disabled=this.busy || this.project?.phase==="working";
    const referenceOption=this.$("audio-mode").querySelector('option[value="reference"]');
    referenceOption.textContent=activeReference && !this.config.lip_sync?"Reference audio · soundtrack only":"Reference audio + new performance";
    this.$("audio-start-setting").hidden=!activeReference;
    const referencePlayer=this.$("reference-player");referencePlayer.hidden=!activeReference;
    if(activeReference && referencePlayer.getAttribute("src")!==this.audio.url)referencePlayer.src=this.audio.url;
    if(!activeReference && referencePlayer.hasAttribute("src")){referencePlayer.pause();referencePlayer.removeAttribute("src");referencePlayer.load();}
    this.$("clear-audio").hidden=!activeReference;
    this.$("clear-audio").disabled=this.busy || this.project?.phase==="working";
    this.$("exit").disabled=this.busy;
    this.$("new").disabled=this.resetting;
    this.$("new").innerHTML=icon(this.resetting?"frames":"reset")+(this.resetting?" Stopping…":" Start over");
    this.$("speech-setting").hidden=!activeReference;
    this.$("refine-lips-setting").hidden=!activeReference || !this.config.lip_sync || !["wan","h3","local"].includes(this.config.engine);
    this.$("audio-note").textContent=activeReference?(this.config.lip_sync?
      (this.config.engine==="wan"?("Creates a speech-driven facial performance, then Wan renders it with the original body motion."+(this.config.refine_lips?" Adds the optional lip refinement pass.":" Review timing, head turns and expression.")):
      ["h3","local"].includes(this.config.engine)?
      ((this.config.engine==="h3"?"MiniMax H3 uses its native audio guide to generate the performance.":"LTX generates video directly from the selected audio.")+
       (this.config.refine_lips?" Adds the optional lip refinement pass. Review mouth timing and detail.":" Review face quality, movement and speech timing.")):
      "Adds a local speech lip-sync finish to the generated character. Best with a visible human face."):
      (["h3","local"].includes(this.config.engine)?"Uses this track as music or sound design. The model can also react to the audio; review the movement.":"Uses this track as music or sound design. Mouth motion follows the performance video.")):
      reference?"Choose an audio file, extract audio from a video, or create a voice track below.":"Follows the original facial performance and keeps the video's audio. Silent videos work too.";
    const p=this.project,working=p?.phase==="working",phase=p?.phase || "new";
    this.$("duration-setting").hidden=this.config.length_mode==="original";
    const originalOption=this.$("length_mode").querySelector('option[value="original"]');
    originalOption.textContent="Use source"+(this.source?.duration?` (${Number(this.source.duration).toFixed(2)}s)`:"");
    this.$("audio-summary").textContent=this.config.audio_id?"Audio · replacement track":"Audio · original performance";
    for(const type of ["source","character","ready","audio"]){
      const drop=this.$(type+"-drop"),asset=type==="ready"?this.readyAsset:type==="character"?this.references[0]:this[type];drop.classList.toggle("has-file",!!asset);
      drop.querySelector(".gs-filename").textContent=type==="character"?"":asset?.name || "";
      this.$(type).disabled=working || this.busy;
    }
    this.$("reference-gallery").querySelectorAll("button").forEach(button=>button.disabled=working || this.busy);
    const poster=this.$("source-poster"),posterURL=this.source?.thumbnail_url;
    poster.hidden=!posterURL;if(posterURL && poster.getAttribute("src")!==posterURL)poster.src=posterURL;
    const thumbnail=this.$("source-thumb");thumbnail.hidden=!this.source || !!posterURL;
    if(this.source && !posterURL && thumbnail.getAttribute("src")!==this.source.url){
      thumbnail.src=this.source.url;thumbnail.muted=true;
      thumbnail.onloadedmetadata=()=>{if(thumbnail.duration>0)thumbnail.currentTime=Math.min(0.1,thumbnail.duration/2);};thumbnail.load();
    }else if(!this.source && thumbnail.getAttribute("src")){thumbnail.pause();thumbnail.removeAttribute("src");thumbnail.load();}
    this.$("source-detail").textContent=this.source?`${this.source.width} × ${this.source.height} · ${Number(this.source.duration).toFixed(2)}s · Click to replace`:"MP4, MOV, WebM or MKV";
    this.container.querySelectorAll("select,textarea,input:not([type=file])").forEach(el=>el.disabled=(el.id==="gs-graph-stage"?false:working) || this.busy);
    wanChoice.disabled=viewport || working || this.busy;
    if(this.config.length_mode==="original"){this.$("start").value=0;this.$("start").disabled=true;}
    const btn=this.$("primary"),hasAssets=!!this.source && this.hasLook();
    let label="Prepare shot",note="Add a video and starting look.";
    if(hasAssets)note=wholeScene?"We’ll prepare the complete scene and its motion guidance.":"We’ll track your selection and show the mask before generation.";
    if(p?.phase==="review"){label=this.lookMode==="ready"?"Use selection & starting frame":wholeScene?"Use whole scene & build look":"Use selection & build look";note="Check the selection throughout the clip before continuing.";}
    else if(p?.approval && phase!=="new"){
      if(this.config.engine!=="seedance"){
        label=p.opening_input?(phase==="done"?"Generate another take":"Animate this look"):(this.lookMode==="ready"?"Use starting frame":"Build starting frame");
        note=p.opening_input?"Check the look, pose, ground contact and camera framing. Then animate this look locally.":"We’ll create the opening frame automatically from your reference image.";
        if(this.config.engine==="h3" && p.opening_input)note="H3 uses this opening frame and your character image separately, with the approved mask and original performance.";
        if(this.config.engine==="wan" && p.opening_input)note="Wan uses your approved look, character reference, motion and mask. Preparation runs automatically.";
      }else{
        label=phase==="draft"&&p.draft_task?"Finish at 1080p · Paid":"Generate draft · Paid";
        note=phase==="draft"?"Watch the whole draft. Finishing at 1080p is a separate paid Comfy render.":"Uses your Comfy credits and uploads the character and guidance clip to Seedance.";
      }
    }
    if(working){label="Working on your shot";note="You can close this view and return later. The job is saved.";}
    if(reference && !this.audio && !working){label="Choose reference audio";note="Upload a track or create a voice below Audio and performance.";}
    if(this.busy && !working)label="Please wait";
    const sourceSeconds=Number(this.source?.duration), start=this.config.length_mode==="original"?0:Number(this.config.start);
    const selectedSeconds=this.config.length_mode==="original"?sourceSeconds:Math.min(Number(this.config.duration),sourceSeconds-start);
    const selectedFrames=Math.max(1,Math.floor(selectedSeconds*24+1e-6));
    const invalidH3Length=this.config.engine==="h3" && Number.isFinite(sourceSeconds) && sourceSeconds>0 && (selectedFrames<5 || selectedFrames>120);
    const invalidWanSpeechLength=this.config.engine==="wan" && activeReference && this.config.lip_sync && selectedFrames>720;
    const invalidLtxLength=this.config.engine==="local"&&wholeScene&&Number.isFinite(sourceSeconds)&&sourceSeconds>0&&selectedFrames>(viewport?360:120);
    const invalidLength=invalidH3Length || invalidWanSpeechLength || invalidLtxLength;
    const missingSelection=!wholeScene && (method==="text"?!this.config.mask_prompt.trim():method==="points"?!points.some(p=>p.include):false);
    if(missingSelection && !working && !this.busy){label=method==="text"?"Describe the area":"Select on opening frame";note=method==="text"?"Describe the area to change before preparing the shot.":"Add at least one include point on the opening frame.";}
    if(invalidLength && !working && !this.busy){label="Choose clip length";note=invalidH3Length?(viewport?"H3 viewport renders support 0.21 to 5 seconds. Choose a custom length.":"H3 currently supports 0.21 to 5 seconds. Choose a custom length, or switch to Wan."):invalidLtxLength?`LTX ${viewport?"viewport renders support up to 15 seconds":"whole-scene shots support up to 5 seconds"}. Choose a shorter length.`:"Wan replacement speech currently supports up to 30 seconds. Choose a custom length.";}
    const enhancementStatus=this.modelStatus?.h3_enhancement || {};
    const enhancementSetupCommand=enhancementStatus.setup_command || "Setup_H3_Enhancement_Windows.cmd";
    const enhancementUnavailable=this.config.engine==="h3"&&this.config.delivery_mode==="enhanced1080"&&this.modelStatus&&(!this.modelStatus.engine_ready?.h3||!enhancementStatus.ready);
    if(enhancementUnavailable&&!working&&!this.busy&&hasAssets){label=this.modelStatus.engine_ready?.h3?"1080p enhancement setup needed":"H3 model setup needs attention";note=!this.modelStatus.engine_ready?.h3?"Set up the H3 models before starting this shot.":!enhancementStatus.model_ready?`Run ${enhancementSetupCommand} and restart ComfyUI before starting H3 Enhanced 1080p.`:"Enable the required native VHS and upscale nodes before starting H3 Enhanced 1080p.";}
    const unsupportedViewport=viewport && this.config.engine==="wan";
    if(unsupportedViewport && !working){label="Choose H3 or LTX";note="Wan is available for motion transfer and object swaps. H3 is recommended for viewport renders.";}
    if(unsupportedSubject && !working){label="Choose H3 or LTX";note="This scene needs object or environment guidance. If a person was missed, choose People in More controls.";}
    this.$("trim-start").hidden=this.config.length_mode==="original";
    const recoverLength=invalidLength && !working && !this.busy;
    if(recoverLength){label="Choose clip length";this.$("action-note").classList.add("is-warning");}
    else this.$("action-note").classList.remove("is-warning");
    btn.innerHTML=escape(label)+icon(working?"frames":"arrow");btn.disabled=working || this.busy || (!recoverLength && (!hasAssets || missingSelection || (reference && !this.audio) || enhancementUnavailable || unsupportedViewport || unsupportedSubject));
    this.$("action-note").textContent=note;this.$("cancel").hidden=!working;this.$("cancel").disabled=this.busy;
    this.$("redesign").hidden=working || this.lookMode==="ready" || this.config.engine==="seedance" || !p?.opening_input;
    this.$("redesign").disabled=this.busy;
    this.$("starting-image").hidden=working || !p || this.config.engine==="seedance" || phase==="new";
    this.$("starting-image").disabled=this.busy;
    this.$("working").hidden=!working;
    this.$("live-cancel").disabled=!working || this.busy;
    const latestAction=p?.actions?.at(-1),stage=latestAction?.stage;
    const stageLabels={prepare:"Finding and tracking the performer",design:"Creating your character preview",video_text:"Preparing the video prompt",h3_references:"Preparing the character and performance references",wan_speech:"Creating your facial performance",wan_prepare:"Preparing Wan motion and character",wan:"Replacing the performer with Wan 2.2",background:"Replacing the performer",restyle:"Restyling your shot",h3:"Replacing the performer with MiniMax H3",h3_enhance:"Enhancing the H3 frames to 1080p",draft:"Generating the Seedance draft",final:"Rendering the accepted take at 1080p"};
    stageLabels.wan_cleanup=latestAction?.next_stage==="h3_enhance"?"Releasing H3 models before enhancement":"Preparing Wan";
    const progress=stageProgress(p?.progress,{state:latestAction?.state,label:stageLabels[stage]});
    this.$("working-title").textContent=progress.title;
    this.$("working-detail").textContent=progress.detail;
    this.$("working-meta").textContent=progress.meta;
    this.$("working-percent").textContent=progress.percent===null?"":`${Math.floor(progress.percent)}%`;
    const progressBar=this.$("working-progress");
    progressBar.classList.toggle("is-indeterminate",progress.percent===null);
    progressBar.setAttribute("aria-label",`${progress.title} · current stage`);
    if(progress.percent===null)progressBar.removeAttribute("aria-valuenow");
    else progressBar.setAttribute("aria-valuenow",String(progress.percent));
    this.$("working-fill").style.width=progress.percent===null?"":`${progress.percent}%`;
    this.defaultReviewPreview(p,wholeScene);
    this.$("preview-tabs").hidden=!p?.review || phase==="opening" || phase==="done" || phase==="draft";
    this.$("preview-tabs").querySelectorAll("button").forEach(b=>b.classList.toggle("active",b.dataset.view===this.preview));
    let video=this.source?.url,opening=null,title=this.source?"Your source video":"Create a new look",description=this.source?"Video loaded. Choose what changes and add your starting look.":"Start with footage or a viewport render.";
    if(p?.review){video=({mask:p.mask_url,guide:p.guide_url||p.selected_url,source:p.selected_url})[this.preview];title="Check the selection";description=wholeScene?"The whole frame is selected. Review the source movement and framing before creating the look.":this.config.remove_text?"Watch the full clip. The orange mask should cover the selected area and all titles and subtitles you want removed.":"Watch the full clip. Make sure the orange mask covers the selected area throughout the shot.";}
    if(p?.review && !wholeScene && p.tracking_coverage?.cut_reselection_requires_review)description+=" Check that the correct person or object stays selected after each camera cut.";
    if(p?.review && !wholeScene && p.tracking_coverage?.near_empty_frames)description+=" The selection is missing in part of the clip. Check whether the subject has left the picture or the mask needs correcting.";
    if(phase==="opening"){opening=p.opening_url;video=null;title=this.lookMode==="ready"?"Review your finished frame":"Review your starting frame";description="Check the appearance and framing before animation.";}
    if((phase==="draft" || phase==="done") && p.results?.length){video=p.results.at(-1).url;title=phase==="draft"?"Review your draft":"Your finished take";description="The selected soundtrack is restored. Watch the entire take before keeping it.";}
    this.$("preview-title").textContent=title;this.$("preview-description").textContent=description;
    const player=this.$("player"),image=this.$("opening");player.hidden=!video;image.hidden=!opening;
    if(video && video!==this.lastVideo){player.src=video;player.load();this.lastVideo=video;}
    if(!video && this.lastVideo){player.pause();player.removeAttribute("src");player.load();this.lastVideo=null;}
    if(opening && image.getAttribute("src")!==opening)image.src=opening;
    this.$("empty").hidden=!!video || !!opening;
    const step=!this.source?0:!this.hasLook()?1:!p?.review || phase==="review" || phase==="opening"?2:3;
    this.container.querySelectorAll("[data-step]").forEach(e=>{const current=Number(e.dataset.step)===step;e.classList.toggle("active",current);e.classList.toggle("complete",Number(e.dataset.step)<step);if(current)e.setAttribute("aria-current","step");else e.removeAttribute("aria-current");});
    if(p?.error)this.message(p.error,true);
    const results=p?.results || [];this.$("results").hidden=!results.length;
    const fingerprint=JSON.stringify(results);
    if(this.resultFingerprint!==fingerprint){
      this.resultFingerprint=fingerprint;
      this.$("takes").innerHTML=results.slice().reverse().map((item,i)=>{
        const label=item.label || ({wan:"Wan 2.2",h3:"MiniMax H3",h3_enhance:"Enhanced H3",draft:"Seedance draft",final:"Seedance final",background:"LTX · original background",restyle:"LTX · scene restyle"})[item.stage] || "Take";
        const raster=item.output_raster?.width&&item.output_raster?.height?`${item.output_raster.width} × ${item.output_raster.height}`:item.resolution?`${item.resolution}px`:"";
        return `<article class="gs-take"><video src="${escape(item.url)}" controls playsinline preload="metadata"></video><div><span>${escape(label+(raster?` · ${raster}`:"")+(item.duration?` · ${item.duration}s`:""))}</span><a href="${escape(item.url)}" download="zura-take-${results.length-i}.mp4">${icon("download")} Download</a></div></article>`;
      }).join("");
    }
  }
  async open() {
    if(!this.container.isConnected)document.body.appendChild(this.container);
    document.documentElement.classList.add("genj-open");this.render();
    try{
      this.modelStatus=await request("/status");this.syncForm();this.render();
    }catch(e){this.message(e.message,true);}
    const saved=localStorage.getItem("genj-studio-project");
    if(saved && !this.project)await this.loadProject(saved);
    await this.loadLibrary();
    clearInterval(this.timer);this.timer=setInterval(()=>this.poll(),2000);
  }
  updateModelStatus() {
    if(!this.modelStatus)return;
    const engine=this.config.engine;
    const speech=engine==="wan" && !!this.config.audio_id && !!this.config.lip_sync;
    const textCleanup=engine==="h3" && this.config.remove_text && this.config.edit_area!=="scene";
    const cleanupReady=!textCleanup || this.modelStatus.h3_text_cleanup?.ready!==false;
    const enhancementRequested=engine==="h3"&&this.config.delivery_mode==="enhanced1080";
    const route=engine==="local"&&this.config.edit_area==="scene"?"local_scene":engine;
    const baseReady=this.modelStatus.engine_ready?.[route] ?? (engine==="local" && this.modelStatus.ready);
    const enhancementReady=!enhancementRequested || this.modelStatus.h3_enhancement?.ready===true;
    const ready=(engine==="seedance" || baseReady) && enhancementReady && (!speech || this.modelStatus.wan_speech?.ready) && cleanupReady;
    const enhancementStatus=this.modelStatus.h3_enhancement || {};
    const enhancementSetupCommand=enhancementStatus.setup_command || "Setup_H3_Enhancement_Windows.cmd";
    this.$("models").textContent=engine==="seedance"?"Uses Comfy credits":ready?(engine==="h3"?(enhancementRequested?"H3 · Enhanced 1080p ready":"H3 · 720p ready; native 1080p unqualified"):engine==="wan"?(speech?"Wan + speech models ready":"Wan models ready"):route==="local_scene"?"LTX 2.5 · whole-scene models ready":"LTX · masked route experimental"):!cleanupReady?"Text cleanup setup needed":enhancementRequested&&!baseReady?"H3 model setup needs attention":enhancementRequested&&!enhancementStatus.ready?(!enhancementStatus.model_ready?`Run ${enhancementSetupCommand}`:"1080p enhancement nodes setup needed"):speech && !this.modelStatus.wan_speech?.ready?"Wan speech setup needed":"Model setup needs attention";
    this.$("models").classList.toggle("needs-attention",!ready);
    const files=this.modelStatus.model_files?.[route]||[];
    const missingNodes=this.modelStatus[route==="local_scene"?"missing_ltx_scene_nodes":engine==="local"?"missing_ltx_nodes":engine==="h3"?"missing_h3_nodes":"missing_wan_nodes"]||[];
    this.$("model-checklist").innerHTML=engine==="seedance"?'<p class="gs-note">Uses the paid provider. Check credits and cost before rendering.</p>':files.map(item=>`<p class="gs-note">${item.ready?"Ready":"Missing"}: <code>${escape(item.path||`models/${item.folder}/${item.filename}`)}</code></p>`).join("")+(missingNodes.length?`<p class="gs-note">Missing nodes: ${missingNodes.map(escape).join(", ")}. Install the matching packs listed in the setup guide, then restart ComfyUI.</p>`:"<p class=\"gs-note\">Required native node checks passed. Optional speech or enhancement has its own setup.</p>");
  }
  async poll() {
    if(this.container.isConnected&&!this.busy&&!this.voicePolling){
      const identity=this.voiceJob?.id||localStorage.getItem("zura-studio-voice-job");
      if(identity){
        const epoch=this.resetEpoch;this.voicePolling=true;
        try{
          const job=await request("/voice/"+identity);if(epoch!==this.resetEpoch)return;this.voiceJob=job;
          if(job.state==="complete"&&this.project?.phase!=="working"){
            const config={...this.readConfig(),audio_id:job.audio.id,audio_start:0,lip_sync:true,refine_lips:false};
            if(this.project){const id=this.project.id,updated=await request(`/projects/${id}/config`,this.configBody(config));if(epoch!==this.resetEpoch||this.project?.id!==id)return;this.project=updated;}
            this.audio=job.audio;this.pendingReference=false;this.config=config;this.voiceJob=null;localStorage.removeItem("zura-studio-voice-job");
            this.$("voice-note").textContent="Voice ready. It is selected as your reference audio.";this.syncForm();this.render();
          }else if(job.state==="error"){
            this.voiceJob=null;localStorage.removeItem("zura-studio-voice-job");this.message(job.error,true);this.render();
          }
        }catch(e){if(epoch===this.resetEpoch)this.message(e.message,true);}finally{if(epoch===this.resetEpoch)this.voicePolling=false;}
      }
    }
    const awaiting=this.project?.actions?.at(-1)?.state==="interrupted";
    if(!this.container.isConnected || this.busy || this.polling || !this.project || this.project.phase!=="working" && !awaiting)return;
    const epoch=this.resetEpoch,projectId=this.project.id;this.polling=true;
    try{
      const prior=this.project.phase,project=await request("/projects/"+projectId);if(epoch!==this.resetEpoch||this.project?.id!==projectId)return;this.project=project;this.render();
      if(prior!==this.project.phase)await this.loadLibrary();
    }catch(e){if(epoch===this.resetEpoch)this.message("Connection interrupted. Your job is saved. Reopen this view when ComfyUI reconnects.",true);}
    finally{if(epoch===this.resetEpoch)this.polling=false;}
  }
  close(){this.container.querySelectorAll("video,audio").forEach(media=>media.pause());this.container.remove();document.documentElement.classList.remove("genj-open");clearInterval(this.timer);}
}

app.registerExtension({
  name:"Zura.Artist.Studio",
  afterConfigureGraph(missingNodeTypes,configuredApp){
    attachWanGraphControls(configuredApp||app,{request,tidy:tidyWanStage});
  },
  beforeRegisterNodeDef(nodeType,nodeData){
    if(nodeData.name!=="ZuraStudioSignals")return;
    for(const hook of ["onConfigure","onGraphConfigured"]){
      const previous=nodeType.prototype[hook];
      nodeType.prototype[hook]=function(...args){const result=previous?.apply(this,args);trimStageSignals(this);return result;};
    }
  },
  async setup(){
    const css=document.createElement("link");css.rel="stylesheet";css.href=new URL("./studio.css",import.meta.url).href;document.head.appendChild(css);
    const studio=new ArtistStudio();
    studio.container.querySelector(".gs-zura-mark").src=new URL("./assets/zura-logo.png",import.meta.url).href;
    const button=document.createElement("button");button.id="genj-studio-launch";button.innerHTML=`<img class="gs-launch-logo" src="${new URL("./assets/zura-logo.png",import.meta.url).href}" alt="" width="24" height="24"/>Zura Studio`;button.title="Switch to Studio view";
    button.onclick=()=>studio.open();document.body.appendChild(button);
    const studioQuery=new URLSearchParams(location.search);
    attachWanGraphControls(app,{request,tidy:tidyWanStage});
    if(studioQuery.get("zura")==="1" || studioQuery.get("genj")==="1")await studio.open();
  },
});

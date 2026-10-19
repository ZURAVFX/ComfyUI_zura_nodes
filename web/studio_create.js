import {IMAGE_MODELS,IMAGE_SIZES,buildImageGraph,imageAvailability,imageDimensions} from "./image_recipes.js";

const escape=value=>String(value??"").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const KEY="zura-image-workspace-v1";
const read=()=>{try{return JSON.parse(localStorage.getItem(KEY))||{};}catch{return {};}};
const view=file=>"/view?"+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||"",type:"output"});

/** Independent image workspace; video recipes and their saved state stay intact. */
export class CreativeWorkspace {
  constructor(studio,api,app){
    this.studio=studio;this.api=api;this.app=app;this.root=studio.container;
    const saved=read();this.items=Array.isArray(saved.items)?saved.items.slice(0,30):[];
    this.job=saved.job||null;this.draft=saved.draft||{};this.models=[];this.submitting=false;this.uploading=false;this.references=Array.isArray(this.draft.references)?this.draft.references:[];
    const nav=document.createElement("nav");nav.className="zc-nav";nav.setAttribute("aria-label","Workspace");
    nav.innerHTML='<button type="button" data-space="home">Home</button><button type="button" data-space="image">Image</button><button type="button" data-space="video">Video</button>';
    this.root.querySelector(".gs-top").insertBefore(nav,this.root.querySelector(".gs-top-actions"));
    this.root.querySelector(".gs-brand>span").textContent="";
    const theme=document.createElement("button");theme.id="zc-theme";theme.type="button";theme.className="zc-theme-toggle";
    this.root.querySelector(".gs-top-actions").prepend(theme);
    let savedTheme;try{savedTheme=localStorage.getItem("zura-studio-theme");}catch{}
    this.setTheme(savedTheme==="light"?"light":"dark",false);
    theme.onclick=()=>this.setTheme(this.root.dataset.theme==="light"?"dark":"light");
    const home=document.createElement("section");home.className="zc-home";
    home.innerHTML=`<div class="zc-welcome"><h1>What will you create?</h1><p>A still worth keeping. A scene worth moving.</p><div class="zc-choices"><button type="button" data-space="image"><span class="zc-card-art zc-image-art" aria-hidden="true"><i></i><i></i><i></i></span><strong>Image <span>↗</span></strong><small>Describe it. Create it. Refine it.</small></button><button type="button" data-space="video"><span class="zc-card-art zc-video-art" aria-hidden="true"><i></i><i></i><i></i></span><strong>Video <span>↗</span></strong><small>New characters, worlds and camera angles.</small></button></div><p class="zc-private">Made on your machine. Your media stays here.</p></div>`;
    this.root.append(home);
    const page=document.createElement("section");page.className="zc-image-page";
    page.innerHTML=`<aside class="zc-image-settings"><button id="zc-settings-close" class="zc-mobile-tools" type="button">Done</button><h2>Make it yours.</h2><label for="zc-model">Model</label><select id="zc-model" disabled><option>Checking installed models…</option></select><p id="zc-model-hint" class="zc-hint"></p><span class="zc-field-label">Shape</span><div class="zc-shapes" role="group" aria-label="Image shape">${Object.keys(IMAGE_SIZES).map(s=>`<button type="button" data-shape="${s}"><span class="zc-shape-icon ${s}" aria-hidden="true"></span>${s[0].toUpperCase()+s.slice(1)}</button>`).join("")}</div><select id="zc-shape" hidden aria-hidden="true" tabindex="-1">${Object.keys(IMAGE_SIZES).map(s=>`<option value="${s}">${s}</option>`).join("")}</select><div class="zc-dimensions"><label for="zc-width">Width (px)<input id="zc-width" type="number" min="256" max="2048" step="16" value="1024"/></label><button id="zc-swap-size" type="button" aria-label="Swap width and height">Swap</button><label for="zc-height">Height (px)<input id="zc-height" type="number" min="256" max="2048" step="16" value="1024"/></label></div><p id="zc-size" class="zc-hint" aria-live="polite"></p><details class="zc-advanced"><summary>More control</summary><label for="zc-seed">Seed</label><input id="zc-seed" type="number" min="0" step="1" value="42"/><label class="zc-check"><input id="zc-random" type="checkbox" checked/> New variation each time</label></details><details class="zc-advanced"><summary>Models & setup</summary><div id="zc-setup"></div><button type="button" id="zc-refresh">Refresh models</button><p class="zc-hint">Tested at 1024px on a 16 GB RTX 4080 with ComfyUI offloading. Other hardware and apps affect speed.</p></details><p class="zc-local">Local generation · No API credits</p></aside><main class="zc-image-main"><div class="zc-image-scroll"><div class="zc-image-heading"><div><h2>From a thought to an image.</h2></div><div class="zc-image-tools"><button type="button" id="zc-settings-toggle" class="zc-mobile-tools" aria-expanded="false">Settings</button><button type="button" id="zc-new">New prompt</button><button type="button" id="zc-clear-history">Clear history</button><button type="button" id="zc-undo-history" hidden>Undo clear</button></div></div><div id="zc-gallery" class="zc-gallery"></div><div id="zc-image-empty" class="zc-image-empty"><svg class="zc-empty-symbol" aria-hidden="true" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="7" y="7" width="34" height="34" rx="6"/><circle cx="18" cy="18" r="3"/><path d="m8 33 10-9 8 7 7-5 8 7"/></svg><h3>Start with a little imagination.</h3><p>Describe a subject, a setting, or a feeling.</p><div class="zc-suggestions"><button type="button" data-suggestion="A cinematic photograph of a quiet coastal house at blue hour, warm light through the windows, soft mist, natural materials">A cinematic scene</button><button type="button" data-suggestion="Studio product photograph of a sculptural ceramic vase, pale lavender background, soft directional lighting, precise material detail">A product shot</button><button type="button" data-suggestion="An illustrated character sheet of an adventurous botanist wearing a moss green coat, expressive face, warm hand-painted textures, neutral background">A character idea</button></div></div></div><form class="zc-image-composer"><div id="zc-progress" class="zc-progress" hidden><div><strong id="zc-progress-title">Queued</strong><button id="zc-cancel" type="button">Cancel</button></div><progress id="zc-bar" max="100" aria-label="Image generation progress"></progress><small id="zc-progress-detail">Waiting for ComfyUI</small></div><p id="zc-message" role="status" aria-live="polite" hidden></p><section class="zc-references" id="zc-reference-drop" aria-label="Reference images"><div id="zc-reference-list" class="zc-reference-list"></div><div class="zc-reference-toolbar"><button id="zc-add-references" type="button">+ Reference images</button><button id="zc-clear-references" type="button" hidden>Remove all</button><span id="zc-reference-hint"></span></div><input id="zc-reference-files" type="file" accept="image/png,image/jpeg,image/webp" multiple hidden/></section><label for="zc-prompt">Your prompt</label><textarea id="zc-prompt" rows="3" placeholder="Describe the image you have in mind…" required maxlength="12000"></textarea><div class="zc-composer-bottom"><span id="zc-recipe-label">Local image generation</span><button id="zc-generate" type="submit" class="gs-primary" disabled>Generate image <span aria-hidden="true">↗</span></button></div></form></main>`;
    this.root.append(page);
    // One action, alongside the prompt, in both workspaces. Existing IDs and
    // handlers remain the source of truth for every approved video route.
    const composer=this.root.querySelector(".gs-composer");
    const timing=document.createElement("details");timing.className="zc-video-timing";
    timing.innerHTML='<summary>Trim footage</summary><div></div>';
    timing.querySelector("div").append(studio.$("trim-controls"),studio.$("trimmer"),studio.$("trim-precision"));
    composer.prepend(timing);
    composer.append(this.root.querySelector(".gs-action-area"));
    const settings=document.createElement("details");settings.className="zc-video-settings";
    settings.innerHTML='<summary>Generation settings <span>Model, quality & audio</span></summary>';
    settings.append(this.root.querySelector(".gs-settings"));
    this.root.querySelector(".gs-controls").append(settings);
    for(const button of this.root.querySelectorAll("[data-space]"))button.onclick=()=>this.show(button.dataset.space);
    this.$("prompt").value=this.draft.prompt||"";this.$("shape").value=IMAGE_SIZES[this.draft.shape]?this.draft.shape:"square";
    const initialSize=IMAGE_SIZES[this.$("shape").value];this.$("width").value=this.draft.width??initialSize[0];this.$("height").value=this.draft.height??initialSize[1];
    this.$("seed").value=Number.isSafeInteger(this.draft.seed)?this.draft.seed:42;
    this.$("random").checked=this.draft.random!==false;
    this.$("prompt").oninput=()=>{this.save();this.render();};
    this.$("model").onchange=()=>{this.save();this.render();};
    for(const id of ["width","height"])this.$(id).oninput=()=>{this.save();this.render();};
    this.$("swap-size").onclick=()=>{const w=this.$("width").value;this.$("width").value=this.$("height").value;this.$("height").value=w;this.save();this.render();};
    this.$("seed").onchange=()=>this.save();this.$("random").onchange=()=>this.save();
    for(const button of page.querySelectorAll("[data-shape]"))button.onclick=()=>{this.$("shape").value=button.dataset.shape;const size=IMAGE_SIZES[button.dataset.shape];this.$("width").value=size[0];this.$("height").value=size[1];this.save();this.render();};
    for(const button of page.querySelectorAll("[data-suggestion]"))button.onclick=()=>{this.$("prompt").value=button.dataset.suggestion;this.save();this.render();this.$("prompt").focus({preventScroll:true});};
    page.querySelector("form").onsubmit=e=>{e.preventDefault();this.generate();};
    const toggleSettings=open=>{page.classList.toggle("settings-open",open);this.$("settings-toggle").setAttribute("aria-expanded",String(open));};
    this.$("settings-toggle").onclick=()=>toggleSettings(!page.classList.contains("settings-open"));
    this.$("settings-close").onclick=()=>toggleSettings(false);
    this.$("clear-history").onclick=()=>{this.clearedItems=this.items;this.items=[];this.save();this.renderGallery();this.render();this.$("undo-history").hidden=!this.clearedItems.length;};
    this.$("undo-history").onclick=()=>{this.items=[...this.items,...(this.clearedItems||[])].slice(0,30);this.clearedItems=[];this.$("undo-history").hidden=true;this.save();this.renderGallery();this.render();};
    this.$("add-references").onclick=()=>this.$("reference-files").click();
    this.$("reference-files").onchange=e=>{const files=Array.from(e.target.files||[]);e.target.value="";this.uploadReferences(files);};
    const drop=this.$("reference-drop");
    drop.ondragover=e=>{e.preventDefault();e.stopPropagation();drop.classList.add("is-dragging");};
    drop.ondragleave=()=>drop.classList.remove("is-dragging");
    drop.ondrop=e=>{e.preventDefault();e.stopPropagation();drop.classList.remove("is-dragging");this.uploadReferences(Array.from(e.dataTransfer?.files||[]));};
    this.root.onpaste=e=>this.pasteReferences(e);
    this.$("reference-list").onclick=e=>{if(this.job||this.uploading)return;const remove=e.target.closest("[data-remove-ref]"),move=e.target.closest("[data-move-ref]");if(remove)this.references.splice(Number(remove.dataset.removeRef),1);if(move){const i=Number(move.dataset.moveRef);[this.references[i-1],this.references[i]]=[this.references[i],this.references[i-1]];}this.save();this.render();};
    this.$("clear-references").onclick=()=>{this.references=[];this.save();this.render();};
    this.$("refresh").onclick=()=>this.loadModels();this.$("cancel").onclick=()=>this.cancel();
    this.$("new").onclick=()=>{this.$("prompt").value="";this.save();this.render();this.$("prompt").focus({preventScroll:true});};
    this.$("gallery").onclick=e=>{const button=e.target.closest("[data-reuse]");if(button){const item=this.items[Number(button.dataset.reuse)];this.references=item.references||[];this.$("prompt").value=item.prompt;this.$("model").value=item.model;this.$("shape").value=item.shape;const size=imageDimensions(item);this.$("width").value=size[0];this.$("height").value=size[1];this.$("seed").value=item.seed;this.$("random").checked=false;this.save();this.render();}};
    this.root.querySelector("#gs-exit").onclick=()=>this.mode==="image"?this.graph():studio.graphView();
    this.api.addEventListener?.("progress",event=>{const d=event.detail;if(!this.job||d.prompt_id!==this.job.id)return;this.$("bar").value=100*d.value/d.max;this.$("progress-title").textContent=`Generating · Step ${d.value} of ${d.max}`;this.$("progress-detail").textContent=this.elapsed();});
    this.api.addEventListener?.("executing",event=>{const d=event.detail;if(!this.job||d.prompt_id!==this.job.id||!d.node)return;const names={text:"Loading text encoder",prompt:"Reading your prompt",model:"Loading image model",sample:"Generating image",decode:"Decoding image",save:"Saving image"};this.$("bar").removeAttribute("value");this.$("progress-title").textContent=names[d.node]||"Preparing image";});
    this.show("home");this.renderGallery();this.render();
  }
  setTheme(theme,persist=true){
    this.root.dataset.theme=theme;const light=theme==="light";
    this.$("theme").textContent=light?"Dark mode":"Light mode";
    this.$("theme").setAttribute("aria-label",light?"Switch to dark mode":"Switch to light mode");
    if(persist)try{localStorage.setItem("zura-studio-theme",theme);}catch{this.message("Theme changed for this session. Browser storage is unavailable.");}
  }
  $(id){return this.root.querySelector("#zc-"+id);}
  async fetch(path,body){const r=await this.api.fetchApi(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});let data;try{data=await r.json();}catch{if(r.ok)return {};throw new Error("ComfyUI is unavailable. Reconnect and try again.");}if(!r.ok)throw new Error(data.error?.message||data.error||"ComfyUI could not complete this request.");return data;}
  config(){return {model:this.$("model").value||this.draft.model||"flux3",prompt:this.$("prompt").value,shape:this.$("shape").value,references:this.references.map(r=>({...r})),width:Number(this.$("width").value),height:Number(this.$("height").value),seed:Number(this.$("seed").value),random:this.$("random").checked};}
  save(){this.draft=this.config();try{localStorage.setItem(KEY,JSON.stringify({draft:this.draft,items:this.items,job:this.job}));}catch{this.message("Browser storage is full. Your files still save in ComfyUI/output/zura_images.");}}
  message(text){this.$("message").textContent=text||"";this.$("message").hidden=!text;}
  show(mode){this.mode=mode;this.root.dataset.workspace=mode;for(const b of this.root.querySelectorAll(".zc-nav [data-space]"))b.setAttribute("aria-current",b.dataset.space===mode?"page":"false");if(mode!=="video")this.root.querySelectorAll("video,audio").forEach(m=>m.pause());if(mode==="image"&&!this.models.length)this.loadModels();if(this.job)this.startPolling();}
  async loadModels(){
    if(this.loading)return;this.loading=true;
    try{const types=[...new Set(IMAGE_MODELS.flatMap(m=>Object.values(buildImageGraph({model:m.id,prompt:"check"})).map(n=>n.class_type)))];types.push("ReferenceMultiLatent","LoadImage");const parts=await Promise.all(types.map(t=>this.fetch("/object_info/"+t)));this.models=imageAvailability(Object.assign({},...parts));const selected=this.draft.model;this.$("model").innerHTML=this.models.map(m=>`<option value="${m.id}" ${m.ready?"":"disabled"}>${escape(m.name)}${m.ready?"":" · Setup needed"}</option>`).join("");this.$("model").value=this.models.find(m=>m.id===selected&&m.ready)?.id||this.models.find(m=>m.ready)?.id||"flux3";this.$("setup").innerHTML=this.models.map(m=>`<div class="zc-model-setup"><strong>${escape(m.name)}</strong><p>${m.ready?"Installed · Native recipe tested on 16 GB":escape("Missing: "+m.missing.join(", "))}</p><a href="${m.url}" target="_blank" rel="noopener noreferrer">Model files & instructions ↗</a></div>`).join("");}
    catch(e){this.message(e.message);}finally{this.loading=false;this.render();}
  }
  render(){
    const c=this.config(),m=this.models.find(m=>m.id===c.model),busy=!!this.job||this.submitting||this.uploading;
    let size,error;try{size=imageDimensions(c);}catch(e){error=e.message;}
    this.$("generate").disabled=busy||!m?.ready||!c.prompt.trim()||!!error||this.references.length>(m?.maxReferences||0)||!!this.references.length&&!m?.referenceReady;this.$("generate").firstChild.textContent=busy?"Generating… ":"Generate image ";
    for(const id of ["model","seed","random","new","width","height","swap-size"])this.$(id).disabled=busy||(id==="model"&&!this.models.length);
    this.$("progress").hidden=!this.job&&!this.submitting;this.$("cancel").disabled=!this.job;
    this.$("clear-history").disabled=!this.items.length;
    const max=m?.maxReferences||0;
    this.$("add-references").disabled=busy||!max||!m?.referenceReady||this.references.length>=max;
    this.$("clear-references").hidden=!this.references.length;this.$("clear-references").disabled=busy;
    this.$("reference-hint").textContent=this.uploading?"Uploading references…":!max?"Text only. Choose Flux to use reference images.":!m?.referenceReady?"Update ComfyUI for reference image support.":`${this.references.length} / ${max} · Drop or paste images here (Ctrl+V)`+(this.references.length?" · Refer to Image 1, Image 2… in your prompt.":"")+(this.references.length>2?" · References resized to a 2 MP total.":"");
    if(this.references.length>max)this.$("reference-hint").textContent=`This model accepts ${max} references. Remove some or choose another model.`;
    const fingerprint=JSON.stringify([this.references,busy]);
    if(fingerprint!==this.referenceFingerprint){this.referenceFingerprint=fingerprint;this.$("reference-list").innerHTML=this.references.map((r,i)=>`<div class="zc-reference"><img src="${escape(this.api.apiURL('/view?'+new URLSearchParams({filename:r.filename,subfolder:r.subfolder||'',type:'input'})))}" alt="${escape(r.name||'Reference '+(i+1))}"/><span>Image ${i+1}</span><button type="button" data-remove-ref="${i}" aria-label="Remove reference ${i+1}" ${busy?'disabled':''}>×</button>${i?`<button type="button" class="zc-ref-move" data-move-ref="${i}" aria-label="Move reference ${i+1} earlier" ${busy?'disabled':''}>←</button>`:''}</div>`).join('');}
    this.$("model-hint").textContent=m?.hint||"Checking local model files.";
    this.$("size").textContent=error || size.join(" × ")+" px · "+(size[0]*size[1]/1e6).toFixed(2)+" MP"+(size[0]*size[1]>1048576?" · Above the tested 1 MP size; needs more memory.":" · Multiples of 16");
    for(const id of ["width","height"])this.$(id).setAttribute("aria-invalid",String(!!error));
    this.$("recipe-label").textContent=m?`${m.name} · ${m.steps} steps`:"Local image generation";
    for(const b of this.root.querySelectorAll("[data-shape]")){b.setAttribute("aria-pressed",String(!!size&&IMAGE_SIZES[b.dataset.shape].every((v,i)=>v===size[i])));b.disabled=busy;}
  }
  renderGallery(){
    this.$("image-empty").hidden=!!this.items.length;
    this.$("gallery").innerHTML=this.items.map((item,i)=>`<figure><a href="${escape(this.api.apiURL(view(item.file)))}" target="_blank" rel="noopener"><img src="${escape(this.api.apiURL(view(item.file)))}" alt="${escape(item.prompt)}" loading="lazy"/></a><figcaption><span>${escape(IMAGE_MODELS.find(m=>m.id===item.model)?.name||item.model)}${item.seconds?` · ${Math.round(item.seconds)}s`:""}</span><div><button type="button" data-reuse="${i}">Reuse prompt</button><a href="${escape(this.api.apiURL(view(item.file)))}" download="${escape(item.file.filename)}">Download</a></div></figcaption></figure>`).join("");
  }
  async pasteReferences(event){
    if(this.mode!=="image")return;
    const clipboard=event.clipboardData;
    let files=Array.from(clipboard?.items||[]).filter(item=>item.kind==="file"&&item.type.startsWith("image/")).map(item=>item.getAsFile()).filter(Boolean);
    if(!files.length)files=Array.from(clipboard?.files||[]).filter(file=>file.type.startsWith("image/"));
    if(!files.length)return; // Leave normal prompt text pasting to the browser.
    event.preventDefault();event.stopPropagation();
    if(this.job||this.submitting||this.uploading){this.message("Wait for the current upload or generation to finish, then paste your image again.");return;}
    files=files.map(file=>{
      const extension={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}[file.type];
      return extension&&!/\.(png|jpe?g|webp)$/i.test(file.name||"")?new File([file],`Pasted image.${extension}`,{type:file.type}):file;
    });
    await this.uploadReferences(files);
  }
  async uploadReferences(files){
    if(this.job||this.submitting||this.uploading||!files.length)return;
    const m=this.models.find(m=>m.id===this.config().model);
    if(!m?.maxReferences||!m.referenceReady){this.message("Choose Flux 3 or Flux 2 Klein with reference support installed.");return;}
    if(files.length+this.references.length>m.maxReferences){this.message(`Choose up to ${m.maxReferences-this.references.length} more images for ${m.name}. Nothing was discarded.`);return;}
    if(files.some(f=>!(/\.(png|jpe?g|webp)$/i.test(f.name))||f.size>64*1024*1024)){this.message("Use PNG, JPEG or WebP images under 64 MB each.");return;}
    this.uploading=true;this.message("");this.render();
    try{for(const file of files){
      const body=new FormData();body.append("image",file,crypto.randomUUID()+'.'+file.name.split('.').at(-1));body.append("subfolder","zura_images/references");body.append("type","input");
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),120000);
      try{const response=await this.api.fetchApi("/upload/image",{method:"POST",body,signal:controller.signal});if(!response.ok)throw new Error("Reference upload failed. You can retry the remaining images.");const asset=await response.json();if(!asset.name)throw new Error("ComfyUI did not return the uploaded image.");this.references.push({name:file.name,filename:asset.name,subfolder:asset.subfolder||"",file:(asset.subfolder?asset.subfolder+"/":"")+asset.name});this.save();this.render();}finally{clearTimeout(timer);}
    }}catch(e){this.message(e.name==="AbortError"?"Upload timed out. Try the remaining images again.":e.message);}finally{this.uploading=false;this.render();}
  }
  elapsed(){return Math.round((Date.now()-this.job.started)/1000)+"s elapsed · Saved locally";}
  async generate(){
    if(this.job||this.submitting||this.uploading)return;
    this.submitting=true;this.message("");this.render();
    try{const c=this.config();if(!this.models.find(m=>m.id===c.model)?.ready)throw new Error("Install this model first, then refresh models.");if(c.random)c.seed=crypto.getRandomValues(new Uint32Array(1))[0];const graph=buildImageGraph(c);this.$("bar").removeAttribute("value");this.$("progress-title").textContent="Submitting image";const result=await this.fetch("/prompt",{prompt:graph,client_id:this.api.clientId,extra_data:{zura_image:true}});if(!result.prompt_id)throw new Error("ComfyUI did not confirm this run. Check the queue before retrying.");this.job={id:result.prompt_id,started:Date.now(),config:c};this.$("progress-title").textContent="Queued";this.save();this.startPolling();}
    catch(e){this.message(e.message);}finally{this.submitting=false;this.render();}
  }
  startPolling(){if(this.timer)return;this.timer=setInterval(()=>this.poll(),1500);this.poll();}
  async poll(){
    if(!this.job||this.polling)return;this.polling=true;const job=this.job;
    try{const history=await this.fetch("/history/"+encodeURIComponent(job.id)),entry=history[job.id];if(this.job!==job)return;
      if(entry?.status?.completed||entry?.status?.status_str==="error"){
        const files=entry.outputs?.save?.images||[];
        const messages=entry.status.messages||[],start=messages.find(m=>m[0]==="execution_start")?.[1]?.timestamp,end=messages.find(m=>m[0]==="execution_success")?.[1]?.timestamp;
        for(const file of files)this.items.unshift({...job.config,file,seconds:start&&end?(end-start)/1000:null});this.items=this.items.slice(0,30);
        const error=messages.find(m=>m[0]==="execution_error")?.[1];this.message(files.length?"":error?.exception_message||"Generation stopped. Your previous images are safe.");this.job=null;this.stopPolling();this.save();this.renderGallery();this.render();
      }else{const queue=await this.fetch("/queue");if(this.job!==job)return;const running=queue.queue_running.some(r=>r[1]===job.id),pending=queue.queue_pending.some(r=>r[1]===job.id);if(!running&&!pending){this.job=null;this.stopPolling();this.save();this.message("This run is no longer in ComfyUI's queue. You can generate again.");this.render();}else this.$("progress-detail").textContent=running?this.elapsed():"Waiting for other ComfyUI jobs";}
    }catch(e){this.message("Connection interrupted. Reconnecting to your image run…");}finally{this.polling=false;}
  }
  async cancel(){if(!this.job)return;try{const id=this.job.id;await this.fetch("/queue",{delete:[id]});await this.fetch("/interrupt",{prompt_id:id});this.message("Cancellation requested.");await this.poll();}catch(e){this.message(e.message);}}
  stopPolling(){clearInterval(this.timer);this.timer=null;}
  close(){this.save();this.stopPolling();}
  async graph(){
    try{const graph=buildImageGraph(this.job?.config||this.config());if(typeof this.app.loadApiJson!=="function")throw new Error("Update ComfyUI to open this image graph.");const original=(this.app.rootGraph||this.app.graph)?.serialize?.();if(!original)throw new Error("Your current graph could not be backed up.");try{await this.app.loadApiJson(graph,"Zura Image · "+Date.now()+".json");}catch(e){await this.app.loadGraphData(original);throw e;}this.studio.close();}catch(e){this.message(e.message);}
  }
}

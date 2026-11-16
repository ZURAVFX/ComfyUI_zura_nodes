import {STUDIO_UI_VERSION} from './studio_host_version.js';

// The same Studio UI runs in ComfyUI and in the local AE window. The AE page
// must be served by the ComfyUI origin returned by the session handshake.
export const STUDIO_HOST_SCHEMA=1;
export {STUDIO_UI_VERSION};

const endpoint=/^\/(?:api\/)?(?:zura\/|genj\/|upload\/|prompt(?:$|\/)|queue(?:$|\/)|interrupt(?:$|\/)|history(?:$|\/)|object_info(?:$|\/)|view$|system_stats$|models(?:$|\/)|embeddings$)/;
export function verifiedLocalOrigin(value){
  const origin=new URL(value);
  if(origin.protocol!=='http:'||origin.hostname!=='127.0.0.1'||!origin.port||origin.origin!==value)throw new Error('Open Studio from the verified local ComfyUI server.');
  return origin;
}
function checkedPath(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||/[\\\x00-\x20\x7f]/.test(value))throw new Error('Studio can only use local ComfyUI paths.');
  const url=new URL(value,origin);
  if(url.origin!==origin.origin||!endpoint.test(url.pathname))throw new Error('Studio can only use local ComfyUI paths.');
  return url;
}

export function createLocalStudioAPI({origin,fetchImpl=globalThis.fetch,WebSocketImpl=globalThis.WebSocket,clientId=globalThis.crypto?.randomUUID?.(),setTimer=globalThis.setTimeout,clearTimer=globalThis.clearTimeout}={}){
  const local=verifiedLocalOrigin(origin),events=new EventTarget();
  if(!clientId)throw new Error('A local Studio client ID is required.');
  let socket=null,retry=null,closed=false,connected=false;
  const emit=(type,detail)=>events.dispatchEvent(new CustomEvent(type,{detail}));
  const api={clientId,authToken:null,apiKey:null,
    apiURL(path){return checkedPath(path,local).href;},
    async fetchApi(path,init={}){
      if(closed)throw Object.assign(new Error('Studio connection ended.'),{name:'AbortError'});
      const url=checkedPath(path,local);
      const response=await fetchImpl(url.href,{...init,redirect:'error',credentials:'same-origin'});
      if(response.redirected||response.url&&new URL(response.url).origin!==local.origin)throw new Error('ComfyUI redirected this local request.');
      return response;
    },
    addEventListener:(type,listener,options)=>events.addEventListener(type,listener,options),
    removeEventListener:(type,listener,options)=>events.removeEventListener(type,listener,options),
    start(){if(closed||connected)return;connected=true;connect();},
    dispose(){closed=true;connected=false;if(retry!==null)clearTimer(retry);retry=null;socket?.close();socket=null;},
  };
  function connect(){
    if(closed||!connected)return;
    const url=new URL(local.href);url.protocol='ws:';url.pathname='/ws';url.search=new URLSearchParams({clientId}).toString();
    const current=new WebSocketImpl(url.href);socket=current;
    current.binaryType='blob';
    current.onmessage=async event=>{
      if(closed||socket!==current)return;
      if(typeof event.data==='string'){
        let packet;try{packet=JSON.parse(event.data);}catch{return;}
        if(typeof packet?.type!=='string')return;
        emit(packet.type,packet.data);
        return;
      }
      // ComfyUI image previews are binary messages with a 4-byte type and a
      // 4-byte image format. Ownership is checked by the shared preview code.
      if(event.data instanceof Blob){
        const bytes=await event.data.arrayBuffer();if(socket!==current||bytes.byteLength<9)return;
        const view=new DataView(bytes),type=view.getUint32(0),format=view.getUint32(4);
        if(type===1&&[1,2].includes(format))emit('b_preview',new Blob([bytes.slice(8)],{type:format===1?'image/jpeg':'image/png'}));
      }
    };
    current.onclose=()=>{if(socket!==current||closed)return;socket=null;emit('status',{status:'disconnected'});retry=setTimer(()=>{retry=null;connect();},1500);};
    current.onerror=()=>{if(socket===current)current.close();};
  }
  return api;
}

export function requireSessionOrigin(session,origin){
  const local=verifiedLocalOrigin(origin);
  if(!session?.id||!session?.capability||session.comfyOrigin!==local.origin)throw new Error('The AE session does not match this local ComfyUI server.');
  if(session.modes?.registry!=='native_studio'||session.modes.source!==true||typeof session.modes.transfer!=='boolean')throw new Error('This AE session does not offer the native Studio source capability.');
  return session;
}

export async function verifyStudioHostManifest(url,origin,fetchImpl=globalThis.fetch){
  const local=verifiedLocalOrigin(origin),target=new URL(url);
  if(target.origin!==local.origin||!target.pathname.endsWith('/studio_host_manifest.json')||target.search||target.hash)throw new Error('The Studio manifest is outside this local server.');
  const response=await fetchImpl(target.href,{redirect:'error',credentials:'same-origin'});
  if(!response.ok||response.redirected||response.url&&new URL(response.url).origin!==local.origin)throw new Error('Could not verify the local Studio manifest.');
  const manifest=await response.json();
  if(manifest.hostSchema!==STUDIO_HOST_SCHEMA||manifest.uiVersion!==STUDIO_UI_VERSION||manifest.backendVersion!==STUDIO_UI_VERSION||
      !/^[a-f0-9]{64}$/.test(manifest.sourceSha256||'')||manifest.entries?.ae!=='studio_ae.html'||manifest.entries?.comfy!=='studio.js'||
      !['studio_ae.html','studio_ae_probe.js','studio_ae_entry.js','studio_host_version.js'].every(name=>/^[a-f0-9]{64}$/.test(manifest.entrySha256?.[name]||'')))throw new Error('Studio files do not match this host version.');
  return manifest;
}

export function unavailableGraphApp(){
  const fail=()=>{throw new Error('Open Studio in ComfyUI to use editable Graph view.');};
  return {rootGraph:{serialize:()=>({})},loadApiJson:fail,loadGraphData:async()=>{}};
}

export function createComfyGraphHost(app,{request,tidy,attach}){
  return {available:true,app,async openApiGraph(exported){
    if(typeof app.loadApiJson!=='function')throw new Error('Update the ComfyUI frontend to open editable API graphs.');
    const previous=(app.rootGraph||app.graph)?.serialize?.();
    if(!previous||typeof app.loadGraphData!=='function')throw new Error('Update ComfyUI to open Graph view without replacing your current workflow.');
    try{await app.loadApiJson(exported.graph,`${exported.name} · ${crypto.randomUUID().slice(0,8)}.json`);await tidy(app,exported.graph,exported.stage);}
    catch(error){await app.loadGraphData(previous);throw new Error('Could not arrange this stage into an artist graph. Your previous workflow has been restored. '+error.message);}
    attach(app,{projectId:exported.project_id,stage:exported.stage,context:exported.context,progress:exported.progress,request,tidy});
  }};
}

export const studioStylePaths=['./studio.css','./vendor/studio-components.css','./studio_components.css','./studio_create.css','./studio_composer.css','./studio_panorama.css','./studio_outpaint.css','./studio_ripple.css','./studio_alpha.css','./studio_director.css','./paintout_studio/studio_paintout.css','./paintout_studio/paintout_integrated.css','./studio_polish.css','./studio_image_area.css','./studio_comfylink.css','./studio_viewport_fit.css','./studio_ui_patterns.css'];
export function installStudioStyles(base=import.meta.url){
  for(const path of studioStylePaths){const href=new URL(path,base).href;if(document.querySelector(`link[data-zura-studio-style="${href}"]`))continue;const link=document.createElement('link');link.rel='stylesheet';link.href=href;link.dataset.zuraStudioStyle=href;document.head.append(link);}
  import('./vendor/studio-components.js').then(()=>{
    document.getElementById('genj-studio')?.classList.add('zc-components-ready');
    for(const tip of document.querySelectorAll('#genj-studio wa-tooltip'))document.getElementById(tip.getAttribute('for'))?.removeAttribute('title');
  }).catch(error=>console.warn('Zura tooltips unavailable; native hints remain.',error));
}

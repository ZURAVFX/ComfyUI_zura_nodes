import { app } from '../../scripts/app.js';
import { api } from '../../scripts/api.js';
import {mountStudio} from './studio_core.js';
import {installStudioStyles,createComfyGraphHost} from './studio_host_adapters.js';
import {takeStudioLaunch,createStudioSession,studioLaunchStorage,StudioAEBridge} from './studio_comfylink.js';
import {installDesktopHandoff} from './studio_desktop_handoff.js';
import {navigateStudioMode} from './studio_mode_adapters.js';
import {tidyArtistGraph,trimStageSignals,installArtistLinkRendering} from './artist_graph.js';
import {attachWanGraphControls} from './wan_graph.js';

const ROOT='/zura/studio';
async function request(path,body,method='POST'){
  const response=await api.fetchApi(ROOT+path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let data;
  try{data=await response.json();}catch{throw new Error('ComfyUI is restarting. Wait a moment, then reopen Zura Studio.');}
  if(!response.ok)throw new Error(data.error||'This action could not complete. Try again when ComfyUI is ready.');
  return data;
}
async function tidyWanStage(app,graph,stage){await import('./vendor/elk.bundled.js');return tidyArtistGraph(app,graph,stage,window.ELK);}
const comfyHost={kind:'comfy',api,graph:createComfyGraphHost(app,{request,tidy:tidyWanStage,attach:attachWanGraphControls})};

let registeredStudio;
function initialStudio(aeSession){return !aeSession&&registeredStudio&&!registeredStudio.aeSession?registeredStudio:mountStudio({host:comfyHost,session:aeSession,storage:aeSession?studioLaunchStorage(aeSession):undefined});}
export async function openZuraStudio(workspace){
  if(!registeredStudio){registeredStudio=mountStudio({host:comfyHost});registeredStudio.container.querySelector(".gs-zura-mark").src=new URL("./assets/zura-logo.png",import.meta.url).href;}
  const studio=registeredStudio;
  if(!studio.container.isConnected)await studio.open();
  if(workspace)await navigateStudioMode(studio.creative,workspace);
  return studio;
}

async function openDesktopAESession(credential,{isCurrent=()=>true}={}){
  let previous=registeredStudio;
  if(previous?.aeSession){await previous.aeBridge?.cancelAndLeave();previous=registeredStudio;if(!isCurrent())return false;}
  const session=await createStudioSession(api,credential);if(session.error)return false;
  if(!isCurrent()){try{await api.fetchApi('/zura/comfylink/v1/studio/sessions/'+encodeURIComponent(session.id)+'/leave',{method:'POST',headers:{'Content-Type':'application/json','X-ComfyLink-Studio-Session':session.capability},body:'{}'});}catch{}return false;}
  const wasOpen=!!previous?.container.isConnected,parent=previous?.container.parentNode,next=previous?.container.nextSibling;
  if(wasOpen){previous.container.querySelectorAll('video,audio').forEach(media=>media.pause());previous.container.remove();}
  const studio=mountStudio({host:comfyHost,session,storage:studioLaunchStorage(session)});registeredStudio=studio;
  studio.onClosed=()=>{
    if(registeredStudio&&registeredStudio!==studio)return;
    registeredStudio=previous||null;
    if(wasOpen&&parent){parent.insertBefore(previous.container,next?.parentNode===parent?next:null);document.documentElement.classList.add('genj-open');}
    else void openZuraStudio();
  };
  studio.creative.show('home');studio.aeBridge=new StudioAEBridge(studio,api,session,()=>studio.close());
  studio.container.querySelector('.gs-zura-mark').src=new URL('./assets/zura-logo.png',import.meta.url).href;
  try{
    let immediateError=null;const opening=studio.open().catch(error=>{immediateError=error;studio.aeBridge?.message('Studio could not finish opening. Leave AE mode to return.');});
    await Promise.resolve();if(immediateError||!studio.container.isConnected||!isCurrent())throw immediateError||Error('Desktop handoff ended');
    void opening;return true;
  }catch(error){studio.close();return false;}
}

app.registerExtension({
  name:"Zura.Artist.Studio",
  afterConfigureGraph(missingNodeTypes,configuredApp){
    installArtistLinkRendering(configuredApp||app);
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
    installArtistLinkRendering(app);
    installStudioStyles();
    const aeSession=await takeStudioLaunch(api);
    installDesktopHandoff(api,openDesktopAESession);
    const studio=initialStudio(aeSession);
    registeredStudio=studio;
    if(aeSession)studio.creative.show('home');
    if(aeSession){
      studio.onClosed=()=>{if(registeredStudio===studio){registeredStudio=null;void openZuraStudio();}};
      studio.aeBridge=new StudioAEBridge(studio,api,aeSession,()=>studio.close());
    }
    studio.container.querySelector(".gs-zura-mark").src=new URL("./assets/zura-logo.png",import.meta.url).href;
    const studioQuery=new URLSearchParams(location.search);
    attachWanGraphControls(app,{request,tidy:tidyWanStage});
    if(aeSession || studioQuery.get("zura")==="1" || studioQuery.get("genj")==="1" || studioQuery.get("paintout")==="1")await openZuraStudio(studioQuery.get("paintout")==="1"?'paintout':studioQuery.get("workspace")||undefined);
  },
});

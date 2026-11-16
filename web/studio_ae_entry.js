import {mountStudio} from './studio_core.js';
import {takeStudioLaunch,studioLaunchStorage,StudioAEBridge} from './studio_comfylink.js';
import {createLocalStudioAPI,requireSessionOrigin,verifyStudioHostManifest,unavailableGraphApp,installStudioStyles,STUDIO_HOST_SCHEMA,STUDIO_UI_VERSION,verifiedLocalOrigin} from './studio_host_adapters.js';

export const AE_STUDIO_HOST={schema:STUDIO_HOST_SCHEMA,uiVersion:STUDIO_UI_VERSION,entry:'studio_ae.html'};

export async function launchAEStudio({origin=globalThis.location?.origin,target=globalThis.document?.getElementById('studio-root'),hostBootstrap=null}={}){
  if(!target)throw new Error('The Studio window has no mount target.');
  const uiOrigin=verifiedLocalOrigin(origin).origin;
  if(hostBootstrap&&(hostBootstrap.hostSchema!==1||hostBootstrap.kind!=='comfylink-ae-proxy-v1'||hostBootstrap.uiOrigin!==uiOrigin||
      verifiedLocalOrigin(hostBootstrap.backendOrigin).origin!==hostBootstrap.backendOrigin||!/^[a-zA-Z0-9_-]{32,128}$/.test(hostBootstrap.nonce||'')))throw new Error('The AE Studio proxy host is invalid.');
  const backendOrigin=hostBootstrap?.backendOrigin||uiOrigin;
  const api=createLocalStudioAPI({origin});
  let studio=null,phase='manifest';
  try{
    await verifyStudioHostManifest(new URL('./studio_host_manifest.json',import.meta.url),origin);
    phase='session';
    const session=requireSessionOrigin(await takeStudioLaunch(api),backendOrigin);
    phase='mount';
    installStudioStyles();
    const host={kind:'ae',api,aeSession:session,uiOrigin,storage:studioLaunchStorage(session),graph:{available:false,app:unavailableGraphApp()}};
    studio=mountStudio({host,session,container:target});
    studio.creative.show('video');
    studio.aeBridge=new StudioAEBridge(studio,api,session,()=>studio.close());
    if(!session.modes.transfer){studio.aeBridge.send.disabled=true;studio.aeBridge.send.title='This AE session cannot receive a result.';}
    studio.container.querySelector('.gs-zura-mark').src=new URL('./assets/zura-logo.png',import.meta.url).href;
    const graphButton=studio.container.querySelector('#gs-exit');
    graphButton.disabled=true;graphButton.title='Open Studio in ComfyUI to use editable Graph view.';
    const closeButton=studio.container.querySelector('#gs-close');
    closeButton.title='Leave AE Studio';closeButton.setAttribute('aria-label','Leave AE Studio');
    closeButton.onclick=()=>studio.aeBridge.leave();
    const closed=studio.onClosed;
    studio.onClosed=()=>{closed?.();api.dispose();target.querySelector('[data-studio-status]')?.remove();const status=target.ownerDocument.createElement('p');status.dataset.studioStatus='';status.setAttribute('role','status');status.textContent='AE Studio closed. Return to After Effects to open another shot.';target.append(status);};
    api.start();
    phase='open';
    await studio.open();
    if(studio.container.isConnected)target.querySelector('[data-studio-status]')?.remove();
    return studio;
  }catch(error){
    try{studio?.close();}catch{}
    api.dispose();
    const status=target.querySelector('[data-studio-status]');
    if(status)status.textContent=error.message||'Could not open this AE session.';
    error.studioPhase=phase;
    throw error;
  }
}

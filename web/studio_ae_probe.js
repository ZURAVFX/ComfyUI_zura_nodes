// This script runs before any Studio module in the AE iframe. The CEP parent
// checks this report, its frame source, origin and nonce before allowing UI code.
export const AE_HOST_GLOBALS=['__adobe_cep__','cep','cep_node','require','process'];
export const probeGlobals=scope=>Object.fromEntries(AE_HOST_GLOBALS.map(name=>[name,name in scope]));

export function beginAEProbe({scope=globalThis,load=async hostBootstrap=>(await import('./studio_ae_entry.js')).launchAEStudio({hostBootstrap})}={}){
  const parent=scope.parent;
  const status=message=>{const element=scope.document?.querySelector?.('[data-studio-status]');if(element)element.textContent=message;};
  const safe=()=>!Object.values(probeGlobals(scope)).some(Boolean);
  let state='waiting',nonce=null,origin=null,bootstrap=null;
  const destination=value=>/^https?:\/\//.test(value||'')?value:'*';
  const local=value=>{try{const url=new URL(value);return url.protocol==='http:'&&url.hostname==='127.0.0.1'&&!!url.port&&url.origin===value;}catch{return false;}};
  const report=error=>{
    status('Could not open the AE shot in Zura Studio.');
    if(nonce&&origin&&parent!==scope){
      const code=['manifest','session','mount','open'].includes(error?.studioPhase)?error.studioPhase:'load';
      parent.postMessage({type:'zura-studio-mount-failed',hostSchema:1,nonce,code},destination(origin));
    }
  };
  const runLoad=value=>{try{void Promise.resolve(load(value)).then(()=>{
    if(nonce&&origin&&parent!==scope)parent.postMessage({type:'zura-studio-mount-ready',hostSchema:1,nonce},destination(origin));
  }).catch(report);}catch(error){report(error);}};
  if(parent===scope){
    if(safe())runLoad(null);else status('Studio cannot run with host scripting access in this window.');
    return ()=>{};
  }
  if(!parent){status('The AE Studio window could not verify its host.');return ()=>{};}
  const ready=()=>{if(state==='waiting')parent.postMessage({type:'zura-studio-probe-ready',hostSchema:1},'*');};
  const dispose=()=>scope.removeEventListener('message',onMessage);
  const onMessage=event=>{
    if(event.source!==parent||event.data?.hostSchema!==1)return;
    const data=event.data;
    if(state==='waiting'&&data.type==='zura-studio-probe-challenge'){
      if(typeof data.nonce!=='string'||!/^[a-zA-Z0-9_-]{32,128}$/.test(data.nonce))return;
      nonce=data.nonce;origin=event.origin;const globals=probeGlobals(scope);
      parent.postMessage({type:'zura-studio-probe-report',hostSchema:1,nonce,globals},destination(origin));
      if(Object.values(globals).some(Boolean)){state='blocked';status('Studio cannot run with host scripting access in this window.');dispose();}
      else state='reported';
      return;
    }
    if(state==='reported'&&data.type==='zura-studio-proxy-bootstrap'&&data.nonce===nonce&&event.origin===origin){
      if(data.kind!=='comfylink-ae-proxy-v1'||!local(data.uiOrigin)||!local(data.backendOrigin)||data.uiOrigin!==scope.location?.origin){
        state='blocked';status('The AE Studio proxy could not be verified.');dispose();return;
      }
      bootstrap={hostSchema:1,kind:data.kind,uiOrigin:data.uiOrigin,backendOrigin:data.backendOrigin,nonce};
      return;
    }
    if(state==='reported'&&data.type==='zura-studio-probe-allow'&&data.nonce===nonce&&event.origin===origin&&bootstrap){
      if(!safe()){state='blocked';status('Studio host scripting access changed. Open the shot again.');dispose();return;}
      state='loaded';dispose();runLoad(bootstrap);
    }
  };
  scope.addEventListener('message',onMessage);
  scope.addEventListener('load',()=>ready(),{once:true});
  ready();
  return dispose;
}

if(typeof window!=='undefined'&&document.getElementById('studio-root'))beginAEProbe({scope:window});

// Desktop discovery is only a hint. The native helper verifies the visible OS
// window challenge before the server sends a scoped token to one exact socket.
const ROOT='/zura/comfylink/v1/studio/desktop';
const installations=new WeakMap();
const hex=(value,length)=>typeof value==='string'&&new RegExp('^[a-f0-9]{'+length+'}$').test(value);
const validClient=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value);
const validBroker=value=>typeof value==='string'&&/^http:\/\/127\.0\.0\.1:\d+\/studio-bridge\/[a-f0-9]{32}$/.test(value);

export function installDesktopHandoff(api,onOpen,{window:win=globalThis.window,document:doc=globalThis.document,crypto:random=globalThis.crypto,fetch:fetcher=globalThis.fetch}={}){
  // Desktop 1.x injects __comfyDesktop2 into its Comfy view. Older Desktop
  // releases use electronAPI. Neither marker is treated as authorization.
  if(!(win?.__comfyDesktop2||win?.electronAPI)||!api?.addEventListener||installations.has(api))return installations.get(api)||null;
  let active=null,closed=false;
  const post=async(path,body)=>api.fetchApi(ROOT+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const restore=()=>{if(!active)return;clearTimeout(active.timer);if(doc.title===active.title)doc.title=active.previous;active=null;};
  const register=async()=>{if(closed||!validClient(api.clientId))return;try{await post('/register',{clientId:api.clientId});}catch{/* Retry on the next connection/status event. */}};
  const onStatus=()=>void register();
  const onChallenge=event=>{void(async()=>{
    const value=event.detail;if(closed||!value||!hex(value.requestId,32)||!hex(value.challenge,64)||!validClient(api.clientId))return;
    restore();const bytes=new Uint8Array(16);random.getRandomValues(bytes);const nonce=[...bytes].map(v=>v.toString(16).padStart(2,'0')).join('');
    const previous=doc.title,title=previous+' · ComfyLink '+nonce,record={requestId:value.requestId,challenge:value.challenge,clientId:api.clientId,nonce,previous,title,timer:null};
    active=record;doc.title=title;record.timer=setTimeout(()=>{if(active===record)restore();},30000);
    try{const response=await post('/respond',{requestId:record.requestId,challenge:record.challenge,clientId:record.clientId,windowNonce:record.nonce});if(!response.ok&&active===record)restore();}
    catch{if(active===record)restore();}
  })();};
  const onHandoff=event=>{void(async()=>{
    const value=event.detail,record=active;if(closed||!record||!value||value.requestId!==record.requestId||value.challenge!==record.challenge||value.windowNonce!==record.nonce||!validBroker(value.broker)||!hex(value.token,64))return;
    const credential={broker:value.broker,token:value.token};delete value.broker;delete value.token;
    let accepted=false;
    try{accepted=(await onOpen(credential,{isCurrent:()=>!closed&&active===record}))===true;}catch{/* The original Studio workspace stays available. */}
    if(!accepted){try{await fetcher(credential.broker+'/leave',{method:'POST',headers:{'Content-Type':'application/json','X-ComfyLink-Studio-Token':credential.token},body:'{}'});}catch{}}
    try{await post('/ack',{requestId:record.requestId,challenge:record.challenge,clientId:record.clientId,windowNonce:record.nonce,accepted});}catch{}
    credential.token='';credential.broker='';if(active===record)restore();
  })();};
  const onFinished=event=>{if(active&&event.detail?.requestId===active.requestId)restore();};
  api.addEventListener('status',onStatus);api.addEventListener('comfylink-desktop-challenge',onChallenge);api.addEventListener('comfylink-desktop-handoff',onHandoff);api.addEventListener('comfylink-desktop-finished',onFinished);
  const interval=setInterval(()=>void register(),20000);void register();
  const dispose=()=>{if(closed)return;closed=true;clearInterval(interval);restore();api.removeEventListener?.('status',onStatus);api.removeEventListener?.('comfylink-desktop-challenge',onChallenge);api.removeEventListener?.('comfylink-desktop-handoff',onHandoff);api.removeEventListener?.('comfylink-desktop-finished',onFinished);installations.delete(api);};
  installations.set(api,dispose);return dispose;
}

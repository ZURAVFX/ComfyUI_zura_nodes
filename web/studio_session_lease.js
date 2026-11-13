const ROOT='/zura/comfylink/v1/studio/sessions';
const ENDED='The AE session has ended. Your source and result are retained. Reopen Studio from After Effects';
const expiry=value=>typeof value==='string'?Date.parse(value):NaN;

/** Renews one connected AE session. It never stores authority or starts work. */
export class StudioSessionLease{
  constructor(bridge,{now=()=>Date.now(),setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id),intervalMs=300000,retryMs=30000}={}){
    this.bridge=bridge;this.now=now;this.setTimer=setTimer;this.clearTimer=clearTimer;this.intervalMs=intervalMs;this.retryMs=retryMs;this.closed=false;this.timer=null;this.pending=null;this.controller=null;
    this.maximum=expiry(bridge.session.lease?.maxExpiresAt);
  }
  start(){
    const b=this.bridge;
    if(this.closed||b.closed||b.session.error||b.session.lease?.renewable!==true||!b.session.capability)return false;
    if(!Number.isFinite(this.maximum)||this.maximum>this.now()+28801000||!Number.isFinite(expiry(b.session.expiresAt))||Math.min(this.maximum,expiry(b.session.expiresAt))<=this.now()){this.ended();return false;}
    this.schedule();return true;
  }
  schedule(delay=this.intervalMs){
    if(this.closed)return;
    if(this.timer!==null)this.clearTimer(this.timer);
    const remaining=Math.min(this.maximum,expiry(this.bridge.session.expiresAt))-this.now();
    if(remaining<=0){this.ended();return;}
    this.timer=this.setTimer(()=>{this.timer=null;void this.renewNow();},Math.min(delay,Math.max(1000,remaining-30000)));
    this.timer?.unref?.();
  }
  ended(){if(this.closed)return;this.bridge.message?.(ENDED);this.dispose();}
  renewNow(){
    if(this.pending)return this.pending;
    const b=this.bridge;
    if(this.closed||b.closed||b.root?.isConnected===false||!b.session.capability){this.dispose();return Promise.resolve(false);}
    if(this.now()>=Math.min(this.maximum,expiry(b.session.expiresAt))){this.ended();return Promise.resolve(false);}
    this.controller=new AbortController();
    const active=this.controller;
    const task=(async()=>{
      try{
        const response=await b.api.fetchApi(ROOT+'/'+encodeURIComponent(b.session.id)+'/renew',{method:'POST',headers:{'Content-Type':'application/json','X-ComfyLink-Studio-Session':b.session.capability},body:'{}',signal:active.signal});
        if(this.closed||b.closed||this.controller!==active)return false;
        if([401,403,404,410].includes(response.status)){this.ended();return false;}
        if(!response.ok)throw Error('renewal unavailable');
        const data=await response.json();
        if(this.closed||b.closed||this.controller!==active)return false;
        const next=expiry(data.expiresAt),maximum=expiry(data.maxExpiresAt),now=this.now();
        if(data.ok!==true||!Number.isFinite(next)||!Number.isFinite(maximum)||next<=now||next>now+1805000||maximum>this.maximum+1000||next>maximum)throw Error('invalid renewal');
        this.maximum=Math.min(this.maximum,maximum);b.session.expiresAt=data.expiresAt;b.session.lease.maxExpiresAt=new Date(this.maximum).toISOString();this.schedule();return true;
      }catch(error){
        if(!this.closed&&!b.closed&&error.name!=='AbortError'){
          if(this.now()>=Math.min(this.maximum,expiry(b.session.expiresAt)))this.ended();else this.schedule(this.retryMs);
        }
        return false;
      }finally{if(this.controller===active)this.controller=null;}
    })();
    const pending=task.finally(()=>{if(this.pending===pending)this.pending=null;});this.pending=pending;return pending;
  }
  dispose(){if(this.closed)return;this.closed=true;if(this.timer!==null)this.clearTimer(this.timer);this.timer=null;this.controller?.abort();this.controller=null;}
}

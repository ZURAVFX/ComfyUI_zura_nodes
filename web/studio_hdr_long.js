// Long HDR is opt-in and remains gated until its visual and end-to-end checks.
const definitiveClientError=error=>error.status>=400&&error.status<500&&error.status!==408&&error.status!==429;
export class HDRLongJobClient {
  constructor(api,onUpdate,storageKey='zura-hdr-long'){this.api=api;this.onUpdate=onUpdate;this.storageKey=storageKey;this.id=null;this.requestId=null;this.busy=false;this.timer=null;this.cancelPending=false;this.closed=false;this.pollPromise=null;this.recoveryPromise=null;}
  publish(job){this.onUpdate(job);if(['complete','failed','cancelled'].includes(job.state)){this.finish();return true;}return false;}
  schedule(method){if(this.closed||!this.busy)return;clearTimeout(this.timer);this.timer=setTimeout(()=>{this.timer=null;this[method]();},2000);}
  remember(kind,value){try{localStorage.setItem(this.storageKey+'-'+kind,value);}catch{}}
  async request(path,body){
    const response=await this.api.fetchApi(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok){const error=new Error(data.error?.message||data.error||'HDR request failed.');error.status=response.status;throw error;}
    return data;
  }
  async start(body){
    if(this.busy)return;
    this.closed=false;this.busy=true;this.onUpdate({state:'preparing'});
    try{
      this.requestId=crypto.randomUUID().replaceAll('-','');
      this.remember('request',this.requestId);
      const job=await this.request('/zura/studio/hdr/jobs',{...body,request_id:this.requestId});
      if(!job.id)throw new Error('The HDR conversion was not accepted.');
      this.id=job.id;this.remember('job',this.id);
      if(!this.publish(job))this.poll();
    }catch(error){
      if(definitiveClientError(error)){this.onUpdate({state:'failed',error:error.message});this.finish();}
      else if(this.requestId){this.onUpdate({state:'reconnecting'});this.recover();}
      else{this.onUpdate({state:'failed',error:'Could not create a secure HDR request ID.'});this.finish();}
    }
  }
  reconnect(id){if(this.busy||!id)return;this.closed=false;this.busy=true;this.id=id;this.onUpdate({state:'reconnecting'});this.poll();}
  reconnectRequest(id){if(this.busy||!id)return;this.closed=false;this.busy=true;this.requestId=id;this.onUpdate({state:'reconnecting'});this.recover();}
  resume(){this.closed=false;if(this.id)return this.poll();if(this.requestId)return this.recover();}
  recover(){
    if(this.closed||!this.requestId||this.id)return Promise.resolve();
    if(this.recoveryPromise)return this.recoveryPromise;
    clearTimeout(this.timer);this.timer=null;
    this.recoveryPromise=this.observeRequest();return this.recoveryPromise;
  }
  async observeRequest(){
    const identity=this.requestId;
    try{
      const job=await this.request('/zura/studio/hdr/requests/'+encodeURIComponent(identity));
      if(identity!==this.requestId)return;
      if(job.id){this.id=job.id;this.remember('job',this.id);if(!this.publish(job))this.poll();return;}
      this.onUpdate({state:'reconnecting'});this.schedule('recover');
    }catch(error){
      if(identity!==this.requestId)return;
      if(definitiveClientError(error)){this.onUpdate({state:'unknown',error:error.message});this.finish();return;}
      this.onUpdate({state:'reconnecting'});this.schedule('recover');
    }finally{this.recoveryPromise=null;}
  }
  poll(){
    if(this.closed||!this.id)return Promise.resolve();
    if(this.pollPromise)return this.pollPromise;
    clearTimeout(this.timer);this.timer=null;
    this.pollPromise=this.observeJob();return this.pollPromise;
  }
  async observeJob(){
    const identity=this.id;
    try{
      const job=await this.request('/zura/studio/hdr/jobs/'+encodeURIComponent(identity));
      if(identity!==this.id)return;
      if(this.publish(job))return;
      this.schedule('poll');
    }catch(error){
      if(identity!==this.id)return;
      if(definitiveClientError(error)){this.onUpdate({state:'failed',error:error.message});this.finish();return;}
      this.onUpdate({state:'reconnecting'});this.schedule('poll');
    }finally{this.pollPromise=null;}
  }
  async cancel(){
    if(!this.id||this.cancelPending)return;
    this.cancelPending=true;this.onUpdate({state:'cancelling'});
    try{await this.request('/zura/studio/hdr/jobs/'+encodeURIComponent(this.id)+'/cancel',{});}
    catch(error){this.cancelPending=false;this.onUpdate({state:'cancel-error',error:error.message});}
  }
  finish(){clearTimeout(this.timer);this.timer=null;this.id=null;this.requestId=null;this.busy=false;this.cancelPending=false;try{localStorage.removeItem(this.storageKey+'-job');localStorage.removeItem(this.storageKey+'-request');}catch{}}
  close(){this.closed=true;clearTimeout(this.timer);this.timer=null;}
}

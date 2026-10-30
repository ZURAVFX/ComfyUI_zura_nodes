// Long HDR is opt-in and remains gated until its visual and end-to-end checks.
const definitiveClientError=error=>error.status>=400&&error.status<500&&error.status!==408&&error.status!==429;
export class HDRLongJobClient {
  constructor(api,onUpdate){this.api=api;this.onUpdate=onUpdate;this.id=null;this.requestId=null;this.busy=false;this.timer=null;this.cancelPending=false;}
  async request(path,body){
    const response=await this.api.fetchApi(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok){const error=new Error(data.error?.message||data.error||'HDR request failed.');error.status=response.status;throw error;}
    return data;
  }
  async start(body){
    if(this.busy)return;
    this.busy=true;this.onUpdate({state:'preparing'});
    try{
      this.requestId=crypto.randomUUID().replaceAll('-','');
      try{localStorage.setItem('zura-hdr-long-request',this.requestId);}catch{}
      const job=await this.request('/zura/studio/hdr/jobs',{...body,request_id:this.requestId});
      if(!job.id)throw new Error('The HDR conversion was not accepted.');
      this.id=job.id;try{localStorage.setItem('zura-hdr-long-job',this.id);}catch{}
      this.onUpdate(job);this.poll();
    }catch(error){
      if(definitiveClientError(error)){this.onUpdate({state:'failed',error:error.message});this.finish();}
      else if(this.requestId){this.onUpdate({state:'reconnecting'});this.recover();}
      else{this.onUpdate({state:'failed',error:'Could not create a secure HDR request ID.'});this.finish();}
    }
  }
  reconnect(id){if(this.busy||!id)return;this.busy=true;this.id=id;this.onUpdate({state:'reconnecting'});this.poll();}
  reconnectRequest(id){if(this.busy||!id)return;this.busy=true;this.requestId=id;this.onUpdate({state:'reconnecting'});this.recover();}
  async recover(){
    if(!this.requestId||this.id)return;
    const identity=this.requestId;
    try{
      const job=await this.request('/zura/studio/hdr/requests/'+encodeURIComponent(identity));
      if(identity!==this.requestId)return;
      if(job.id){this.id=job.id;try{localStorage.setItem('zura-hdr-long-job',this.id);}catch{}this.onUpdate(job);this.poll();return;}
      this.onUpdate({state:'reconnecting'});this.timer=setTimeout(()=>this.recover(),2000);
    }catch(error){
      if(identity!==this.requestId)return;
      if(definitiveClientError(error)){this.onUpdate({state:'unknown',error:error.message});this.finish();return;}
      this.onUpdate({state:'reconnecting'});this.timer=setTimeout(()=>this.recover(),2000);
    }
  }
  async poll(){
    if(!this.id)return;
    const identity=this.id;
    try{
      const job=await this.request('/zura/studio/hdr/jobs/'+encodeURIComponent(identity));
      if(identity!==this.id)return;
      this.onUpdate(job);
      if(['complete','failed','cancelled'].includes(job.state)){this.finish();return;}
      this.timer=setTimeout(()=>this.poll(),2000);
    }catch(error){
      if(identity!==this.id)return;
      if(definitiveClientError(error)){this.onUpdate({state:'failed',error:error.message});this.finish();return;}
      this.onUpdate({state:'reconnecting'});this.timer=setTimeout(()=>this.poll(),2000);
    }
  }
  async cancel(){
    if(!this.id||this.cancelPending)return;
    this.cancelPending=true;this.onUpdate({state:'cancelling'});
    try{await this.request('/zura/studio/hdr/jobs/'+encodeURIComponent(this.id)+'/cancel',{});}
    catch(error){this.cancelPending=false;this.onUpdate({state:'cancel-error',error:error.message});}
  }
  finish(){clearTimeout(this.timer);this.timer=null;this.id=null;this.requestId=null;this.busy=false;this.cancelPending=false;try{localStorage.removeItem('zura-hdr-long-job');localStorage.removeItem('zura-hdr-long-request');}catch{}}
  close(){clearTimeout(this.timer);this.timer=null;}
}

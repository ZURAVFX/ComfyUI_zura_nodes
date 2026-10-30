// Long HDR is opt-in and remains gated until its visual and end-to-end checks.
export class HDRLongJobClient {
  constructor(api,onUpdate){this.api=api;this.onUpdate=onUpdate;this.id=null;this.busy=false;this.timer=null;this.cancelPending=false;}
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
      const job=await this.request('/zura/studio/hdr/jobs',body);
      if(!job.id)throw new Error('The HDR conversion was not accepted.');
      this.id=job.id;try{localStorage.setItem('zura-hdr-long-job',this.id);}catch{}
      this.onUpdate(job);this.poll();
    }catch(error){
      this.busy=false;
      this.onUpdate(error.status?{state:'failed',error:error.message}:
        {state:'unknown',error:'The submission status is unknown. Check the ComfyUI queue before starting another conversion.'});
    }
  }
  reconnect(id){if(this.busy||!id)return;this.busy=true;this.id=id;this.onUpdate({state:'reconnecting'});this.poll();}
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
      if(error.status>=400 && error.status<500){this.onUpdate({state:'failed',error:error.message});this.finish();return;}
      this.onUpdate({state:'reconnecting'});this.timer=setTimeout(()=>this.poll(),2000);
    }
  }
  async cancel(){
    if(!this.id||this.cancelPending)return;
    this.cancelPending=true;this.onUpdate({state:'cancelling'});
    try{await this.request('/zura/studio/hdr/jobs/'+encodeURIComponent(this.id)+'/cancel',{});}
    catch(error){this.cancelPending=false;this.onUpdate({state:'cancel-error',error:error.message});}
  }
  finish(){clearTimeout(this.timer);this.timer=null;this.id=null;this.busy=false;this.cancelPending=false;try{localStorage.removeItem('zura-hdr-long-job');}catch{}}
  close(){clearTimeout(this.timer);this.timer=null;}
}

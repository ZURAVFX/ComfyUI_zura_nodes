import {HDRLongJobClient} from './studio_hdr_long.js';

// A generation's SDR master is retained. HDR is an explicit additional model
// pass, shown in the same workspace rather than silently tagging SDR as HDR.
export class LTXHDRDelivery {
  constructor(api,{key,onUpdate,onComplete,onSetup=()=>{}}){
    this.key=key;this.onUpdate=onUpdate;this.onComplete=onComplete;this.onSetup=onSetup;this.busy=false;
    this.client=new HDRLongJobClient(api,job=>this.update(job),key);
    try{this.take=JSON.parse(localStorage.getItem(key+'-take'))||null;}catch{}
  }
  async preflight(config){
    if(config.engine!=='ltx'||!config.hdrOutput||config.hdrOutput==='sdr')return;
    const query=new URLSearchParams({mode:'sdr',output:config.hdrOutput,long:'1',width:config.width,height:config.height});
    const info=await this.client.request('/zura/studio/hdr/readiness?'+query);
    this.onSetup(info);
    if(!info.longPreview)throw new Error('HDR delivery is disabled on this ComfyUI server. Choose SDR output.');
    if(!info.ready){
      const missing=[...(info.files||[]).filter(file=>!file.ready).map(file=>file.filename),...(info.missingNodes||[])];
      throw new Error('HDR setup is incomplete'+(missing.length?': '+missing.join(', '):'. Refresh model setup.')+'.');
    }
  }
  async start(take){
    if(this.busy)return;
    this.take=take;this.busy=true;this.cancelRequested=false;
    try{localStorage.setItem(this.key+'-take',JSON.stringify(take));}catch{}
    await this.client.start({mode:'sdr',source_kind:'output',output_ref:take.file,start_frame:0,
      frame_count:take.config.frames,colour_space:'srgb_display',output:take.config.hdrOutput,
      section_frames:121,seed:take.config.seed,client_id:this.client.api.clientId||'zura-ltx-delivery'});
  }
  resume(){
    if(!this.take)return;
    if(this.client.busy){this.client.resume();return;}
    let id,request;try{id=localStorage.getItem(this.key+'-job');request=localStorage.getItem(this.key+'-request');}catch{}
    if(id||request){this.busy=true;if(id)this.client.reconnect(id);else this.client.reconnectRequest(request);}
  }
  update(job){
    this.activePrompt=job.active_prompt_id||null;
    if(this.cancelRequested&&this.client.id&&!this.client.cancelPending){this.cancelRequested=false;queueMicrotask(()=>this.client.cancel());}
    const terminal=['complete','failed','cancelled','unknown'].includes(job.state);
    this.busy=!terminal;
    if(job.state==='complete'){
      const files=job.result?.files||[],preview=job.result?.preview;
      if(preview&&files.length)this.onComplete({...this.take,file:preview,hdrFiles:files});
      else job={...job,state:'failed',error:'HDR delivery finished without the requested files. Your SDR take is retained.'};
    }
    this.onUpdate(job);
    if(terminal){this.take=null;this.cancelRequested=false;try{localStorage.removeItem(this.key+'-take');}catch{}}
  }
  cancel(){if(!this.client.id){this.cancelRequested=true;this.onUpdate({state:'cancelling'});return;}this.cancelRequested=false;return this.client.cancel();}
  close(){this.client.close();}
}

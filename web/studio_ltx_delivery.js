import {normaliseEXRStorage} from './studio_exr_precision.js';
import {normalStudioStorage} from './studio_storage.js';
import {HDRLongJobClient} from './studio_hdr_long.js';

// A generation's SDR master is retained. HDR is an explicit additional model
// pass, shown in the same workspace rather than silently tagging SDR as HDR.
export class LTXHDRDelivery {
  constructor(api,{key,onUpdate,onComplete,onSetup=()=>{},storage=normalStudioStorage()}){this.storage=storage;
    this.key=key;this.onUpdate=onUpdate;this.onComplete=onComplete;this.onSetup=onSetup;this.busy=false;
    this.client=new HDRLongJobClient(api,job=>this.update(job),key,this.storage);
    try{this.take=JSON.parse(this.storage.getItem(key+'-take'))||null;}catch{}
  }
  async preflight(config){
    if(!config.hdrOutput||config.hdrOutput==='sdr')return;
    const query=new URLSearchParams({mode:'sdr',output:config.hdrOutput,long:'1',width:config.width,height:config.height});
    if(config.single_frame===true)query.set('single_frame','1');
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
    if(take.kind==='alpha_extract'&&!take.alpha_ref)throw new Error('This result needs its retained FLOAT alpha master.');
    take={...take,config:{...take.config,exr_storage:normaliseEXRStorage(take.config.exr_storage)}};this.take=take;this.busy=true;this.cancelRequested=false;
    try{this.storage.setItem(this.key+'-take',JSON.stringify(take));}catch{}
    await this.client.start({...(take.config.ae_frame_contract?{ae_frame_contract:take.config.ae_frame_contract}:{}),mode:'sdr',source_kind:take.kind==='image'?'output_image':'output',output_ref:take.file,start_frame:0,
      frame_count:take.config.frames,colour_space:take.config.hdrSourceColour||'srgb_display',output:take.config.hdrOutput,exr_storage:take.config.exr_storage,
      ...(take.kind==='image'?{sequence_fps:take.config.fps||24}:{}),
      ...(take.alpha_ref?{alpha_ref:take.alpha_ref}:{}),
      section_frames:121,seed:take.config.seed,client_id:this.client.api.clientId||'zura-ltx-delivery'});
  }
  resume(){
    if(!this.take)return;
    if(this.client.busy){this.client.resume();return;}
    let id,request;try{id=this.storage.getItem(this.key+'-job');request=this.storage.getItem(this.key+'-request');}catch{}
    if(id||request){this.busy=true;if(id)this.client.reconnect(id);else this.client.reconnectRequest(request);}
  }
  update(job){
    this.activePrompt=job.active_prompt_id||null;
    if(this.cancelRequested&&this.client.id&&!this.client.cancelPending){this.cancelRequested=false;queueMicrotask(()=>this.client.cancel());}
    const terminal=['complete','failed','cancelled','unknown'].includes(job.state);
    this.busy=!terminal;
    if(job.state==='complete'){
      const files=job.result?.files||[],preview=job.result?.preview;
      const output=this.take?.config?.hdrOutput,hasEXR=files.some(file=>file.type==='output'&&/\.(zip|exr)$/i.test(file.filename||'')),hasVideo=files.some(file=>file.type==='output'&&/\.(mp4|mov)$/i.test(file.filename||''));
      const complete=output==='acescg_exr'?hasEXR:output==='hlg_video'?hasVideo:output==='hlg_and_exr'?hasEXR&&hasVideo:false;
      if(preview?.type==='output'&&complete)this.onComplete({...this.take,file:preview,hdrFiles:files,exr_storage:normaliseEXRStorage(job.result?.exr_storage||job.exr_storage||this.take?.config?.exr_storage),...(job.result?.alphaAssociation==='straight'?{alphaAssociation:'straight'}:{})});
      else job={...job,state:'failed',error:'HDR delivery finished without the requested files. Your SDR take is retained.'};
    }
    this.onUpdate(job);
    if(terminal){this.take=null;this.cancelRequested=false;try{this.storage.removeItem(this.key+'-take');}catch{}}
  }
  cancel(){if(!this.client.id){this.cancelRequested=true;this.onUpdate({state:'cancelling'});return;}this.cancelRequested=false;return this.client.cancel();}
  close(){this.client.close();}
}

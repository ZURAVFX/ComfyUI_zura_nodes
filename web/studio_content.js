export class ContentDetection {
  constructor(fetchContent,onChange,{delay=450,setTimer=setTimeout,clearTimer=clearTimeout}={}) {
    this.fetchContent=fetchContent;this.onChange=onChange;this.delay=delay;
    this.setTimer=setTimer;this.clearTimer=clearTimer;this.key=null;this.timer=null;
    this.result=null;this.pending=false;
  }
  update(source,config) {
    const mode=config.subject_mode||"auto",start=config.length_mode==="original"?0:Number(config.start)||0;
    const duration=config.length_mode==="original"?Number(source?.duration):Number(config.duration);
    const payload={asset_id:source?.id,start,duration,viewport:config.workflow_mode==="viewport"};
    const key=JSON.stringify([payload,mode]);
    if(key===this.key)return;
    this.key=key;if(this.timer!==null)this.clearTimer(this.timer);this.timer=null;
    this.result=null;this.pending=false;
    if(!source?.id || mode!=="auto")return;
    this.pending=true;
    this.timer=this.setTimer(async()=>{
      this.timer=null;
      try {
        const result=await this.fetchContent(payload);
        if(this.key!==key)return;
        this.result={kind:result.status,message:result.reason};
      }catch {
        if(this.key!==key)return;
        this.result={kind:"unknown",message:"Choose People or Objects & scenery under More controls if needed."};
      }
      this.pending=false;this.onChange();
    },this.delay);
  }
  badge(mode="auto") {
    if(mode==="people")return {kind:"people",label:"People · selected",message:"Using your subject choice."};
    if(mode==="objects")return {kind:"objects",label:"Objects & scenery · selected",message:"Using your subject choice."};
    if(this.pending)return {kind:"unknown",label:"Checking subject…",message:"Checking sampled source frames. You can keep editing."};
    return {kind:this.result?.kind||"unknown",label:({people:"People detected",objects:"No people detected"})[this.result?.kind]||"Check subject",message:this.result?.message||"Choose the subject under More controls if needed."};
  }
}

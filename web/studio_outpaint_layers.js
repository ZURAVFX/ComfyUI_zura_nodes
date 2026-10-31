// Export compositing layers from a completed native-HDR render. This never
// queues inference or changes the finished video and its normal downloads.
export class OutpaintLayers {
  constructor(host,{fetch,apiURL,onChange=()=>{}}){
    this.fetch=fetch;this.apiURL=apiURL;this.onChange=onChange;this.closed=false;this.disposed=false;this.resultId=null;this.state=null;this.polling=false;this.starting=false;this.cancelPending=false;this.requestVersion=0;
    this.root=document.createElement('div');this.root.className='zo-layers';this.root.hidden=true;this.root.setAttribute('aria-label','HDR compositing layers');
    this.root.innerHTML='<div><button type="button" data-layers-start>Border layers · EXR</button><a data-layers-download download hidden>Download border layers</a><button type="button" data-layers-cancel hidden>Cancel export</button></div><small>Original plate + generated border and mattes for manual level matching.</small><div class="zo-progress" data-layers-progress hidden><progress aria-label="Border layer export progress" max="1"></progress><output role="status" aria-live="polite"></output></div>';
    host.append(this.root);this.$('start').onclick=()=>this.start();this.$('cancel').onclick=()=>this.cancel();
  }
  $(name){return this.root.querySelector(`[data-layers-${name}]`);}
  get busy(){return this.starting||this.cancelPending||['running','queued','cancelling'].includes(this.state?.state);}
  endpoint(){return '/zura/studio/outpaint/jobs/'+encodeURIComponent(this.resultId)+'/layers';}
  setResult(result){
    const valid=result?.kind==='render'&&result.state==='complete'&&result.hdr===true&&result.hdr_files?.exr&&typeof result.id==='string'&&result.id;
    if(this.busy)return false;
    const id=valid?result.id:null;
    if(id!==this.resultId){clearTimeout(this.timer);this.resultId=id;this.state=null;this.cancelPending=false;}
    this.render();return true;
  }
  render(){
    this.root.hidden=!this.resultId;
    const done=this.state?.state==='complete',artifact=this.state?.artifact;
    const downloadable=done&&artifact?.type==='output'&&artifact.subfolder?.replaceAll('\\','/')==='genj/hdr'&&typeof artifact.filename==='string'&&!/[\\/]/.test(artifact.filename)&&artifact.filename.endsWith('_layers.zip');
    this.$('start').hidden=!!downloadable;this.$('start').disabled=this.busy;this.$('start').textContent=['failed','cancelled'].includes(this.state?.state)?'Retry border layers':'Border layers · EXR';
    this.$('download').hidden=!downloadable;
    if(downloadable)this.$('download').href=this.apiURL('/view?'+new URLSearchParams({filename:artifact.filename,subfolder:artifact.subfolder,type:artifact.type}));
    else this.$('download').removeAttribute('href');
    this.$('cancel').hidden=!this.busy;this.$('cancel').disabled=this.cancelPending||this.starting||this.state?.state==='cancelling';
    const progress=this.$('progress'),bar=progress.querySelector('progress'),label=progress.querySelector('output');
    progress.hidden=!this.busy&&!this.state?.error&&!['cancelled','complete'].includes(this.state?.state);
    const completed=Number(this.state?.completed),total=Number(this.state?.total);
    if(Number.isFinite(completed)&&Number.isFinite(total)&&total>0){bar.max=total;bar.value=Math.max(0,Math.min(total,completed));}else bar.removeAttribute('value');
    bar.hidden=!this.busy;
    label.textContent=this.cancelPending||this.state?.state==='cancelling'?'Cancelling border export…':this.starting?'Preparing border layers…':this.state?.error||({complete:downloadable?'Border layers ready.':'The layer archive is unavailable. Try exporting again.',cancelled:'Border export cancelled.'})[this.state?.state]||(total>0?`Exporting border layers · ${Math.max(0,completed||0)} / ${total} frames`:'Preparing border layers…');
    this.onChange();
  }
  async start(){
    if(this.disposed||!this.resultId||this.busy)return;
    const id=this.resultId;this.requestVersion++;this.starting=true;this.state=null;this.render();
    try{const state=await this.fetch(this.endpoint(),{});if(this.disposed||this.resultId!==id)return;this.state=state;}
    catch(error){if(!this.disposed&&this.resultId===id)this.state={state:'failed',error:error.message||'Could not export border layers. Try again.'};}
    finally{this.starting=false;if(!this.disposed){this.render();if(this.busy&&!this.closed)this.schedule(0);}}
  }
  schedule(delay=1000){clearTimeout(this.timer);if(!this.closed&&!this.disposed&&this.busy)this.timer=setTimeout(()=>this.poll(),delay);}
  async poll(){
    if(this.closed||this.disposed||!this.resultId||!this.busy||this.polling||this.starting)return;
    const id=this.resultId,version=this.requestVersion;this.polling=true;
    try{const state=await this.fetch(this.endpoint());if(!this.disposed&&this.resultId===id&&this.requestVersion===version){this.state=state;this.cancelPending=false;}}
    catch(error){if(!this.disposed&&this.resultId===id&&this.requestVersion===version)this.state={...this.state,error:'Connection interrupted. Reconnecting to the border export…'};}
    finally{this.polling=false;if(!this.disposed){this.render();this.schedule();}}
  }
  async cancel(){
    if(!this.resultId||!this.busy||this.starting||this.cancelPending)return;
    const id=this.resultId;this.requestVersion++;this.cancelPending=true;this.render();
    try{const state=await this.fetch(this.endpoint()+'/cancel',{});if(!this.disposed&&this.resultId===id){this.state=state;this.cancelPending=state.state==='cancelling';}}
    catch(error){if(!this.disposed&&this.resultId===id){this.cancelPending=false;this.state={...this.state,error:'Could not cancel the border export. Try again.'};}}
    finally{if(!this.disposed){this.render();this.schedule(0);}}
  }
  resume(){this.closed=false;if(this.busy)this.schedule(0);}
  close(){this.closed=true;clearTimeout(this.timer);}
  dispose(){this.close();this.disposed=true;this.root.remove();}
}

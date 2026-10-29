// Bounded LTX HDR post-passes use explicitly selected source assets.
export class HDRSourceTool {
  constructor(host,api,getSource){
    this.api=api;this.getSource=getSource;this.job=null;this.busy=false;this.timer=null;
    this.root=document.createElement('details');this.root.className='gs-hdr-tool';
    this.root.innerHTML=`<summary>HDR tools · LTX 2.5</summary><div class="gs-hdr-content">
      <label>Conversion<select data-hdr="mode"><option value="sdr">SDR to HDR</option><option value="native">HDR to HDR · preview</option></select></label>
      <p>Convert a short selection. HLG is 10-bit; EXR is ACEScg. The preview is tone-mapped for an SDR screen.</p>
      <label>Convert<select data-hdr="source-kind"><option value="upload">Source footage</option><option value="result">Latest LTX result</option></select></label>
      <div class="gs-hdr-fields"><label>First frame<input data-hdr="start" type="number" min="0" step="1" value="0"/></label><label>Number of frames<input data-hdr="count" type="number" min="1" max="121" step="1" value="25"/></label></div>
      <label>Source colour<select data-hdr="colour"><option value="auto">Read source tags</option><option value="rec709_oetf">Rec.709</option><option value="rec709_gamma24">Rec.709 gamma 2.4</option><option value="srgb_display">sRGB</option></select></label>
      <label>Deliver<select data-hdr="output"><option value="hlg_and_exr">HLG video + EXR sequence</option><option value="hlg_video">HLG video</option><option value="acescg_exr">EXR sequence</option></select></label>
      <p data-hdr="limits">Up to 121 frames per run. Large frame selections may need to be shorter.</p>
      <div class="gs-hdr-actions"><button data-hdr="start-job" type="button">Convert source</button><button data-hdr="cancel" type="button" hidden>Cancel</button></div>
      <p data-hdr="status" role="status" aria-live="polite"></p><progress data-hdr="progress" max="100" hidden></progress>
      <div data-hdr="result" hidden><video data-hdr="preview" controls playsinline></video><p>SDR preview only</p><a data-hdr="hlg" download hidden>Download HLG video</a> <a data-hdr="exr" download hidden>Download EXR sequence</a></div>
    </div>`;
    host.append(this.root);this.$('start-job').onclick=()=>this.start();this.$('cancel').onclick=()=>this.cancel();
    this.$('mode').onchange=()=>this.updateMode();this.updateMode();
    this.onProgress=event=>{const p=event.detail;if(!this.job||p.prompt_id!==this.job)return;const bar=this.$('progress');bar.hidden=false;if(p.max>0)bar.value=100*p.value/p.max;this.status(`Generating · step ${p.value} of ${p.max}`);};
    api.addEventListener?.('progress',this.onProgress);
    try{this.job=localStorage.getItem('zura-hdr-active-job');}catch{}
    if(this.job){this.busy=true;this.root.open=true;this.$('start-job').disabled=true;this.$('cancel').hidden=false;this.$('progress').hidden=false;this.$('progress').removeAttribute('value');this.status('Reconnecting to your HDR conversion…');this.poll();}
  }
  $(id){return this.root.querySelector(`[data-hdr="${id}"]`);}
  status(text){this.$('status').textContent=text;}
  updateMode(){
    const native=this.$('mode').value==='native';
    this.$('colour').innerHTML=native?'<option value="auto">Read source tags</option><option value="hlg_rec2020">HLG · Rec.2020</option>':'<option value="auto">Read source tags</option><option value="rec709_oetf">Rec.709</option><option value="rec709_gamma24">Rec.709 gamma 2.4</option><option value="srgb_display">sRGB</option>';
    this.$('limits').textContent=native?'Preview: HLG video input only; PQ and EXR input are not yet supported. 1–121 frames, even dimensions between 32 and 2048 px; large selections need fewer frames. Requires the LTX 2.5 Refine Details LoRA. The model may alter motion or appearance.':'Up to 121 frames per run. Large frame selections may need to be shorter.';
    this.$('start-job').textContent=native?'Process HDR video':'Convert source';
  }
  async request(path,body){const response=await this.api.fetchApi(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let data;try{data=await response.json();}catch{throw new Error('ComfyUI could not respond.');}if(!response.ok)throw new Error(data.error?.message||data.error||'Could not complete the request.');return data;}
  async start(){
    if(this.busy)return;
    const asset=this.getSource(),sourceKind=this.$('source-kind').value;
    if(asset?.busy){this.status('Wait for the current Studio job to finish.');return;}
    if(sourceKind==='upload'&&!asset?.id){this.status('Add a source video first.');return;}
    if(sourceKind==='result'&&!asset?.projectId){this.status('Generate an LTX video first.');return;}
    const start=Number(this.$('start').value),count=Number(this.$('count').value);
    if(!Number.isInteger(start)||start<0||!Number.isInteger(count)||count<1||count>121){this.status('Choose a valid first frame and 1–121 frames.');return;}
    this.busy=true;this.$('start-job').disabled=true;this.$('result').hidden=true;this.$('progress').hidden=false;this.$('progress').removeAttribute('value');this.status('Checking source and model…');
    try{
      const route=this.$('mode').value==='native'?'/zura/studio/hdr/native-graph':'/zura/studio/hdr/graph';
      const prepared=await this.request(route,{source_kind:sourceKind,source_id:asset?.id,project_id:asset?.projectId,start_frame:start,frame_count:count,colour_space:this.$('colour').value,output:this.$('output').value});
      const queued=await this.request('/prompt',{prompt:prepared.graph,client_id:this.api.clientId||'zura-hdr'});
      if(!queued.prompt_id)throw new Error('ComfyUI did not accept the HDR conversion.');
      this.job=queued.prompt_id;try{localStorage.setItem('zura-hdr-active-job',this.job);}catch{}this.$('cancel').hidden=false;this.status('Queued · preparing LTX 2.5…');this.poll();
    }catch(error){this.status(error.message);this.finish();}
  }
  url(file){return this.api.apiURL('/view?'+new URLSearchParams({filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'}));}
  async poll(){
    if(!this.job)return;
    try{
      const history=await this.request('/history/'+encodeURIComponent(this.job)),item=history[this.job];
      if(!item){
        const queue=await this.request('/queue');
        const pending=[...(queue.queue_pending||[]),...(queue.queue_running||[])];
        if(!pending.some(entry=>entry[1]===this.job)){
          const again=await this.request('/history/'+encodeURIComponent(this.job));
          if(!again[this.job])throw new Error('This conversion is no longer in the ComfyUI queue. Start it again.');
        }
        this.timer=setTimeout(()=>this.poll(),2000);return;
      }
      if(item.status?.status_str==='error')throw new Error('HDR conversion failed. Check ComfyUI’s job details.');
      const outputs=item.outputs||{},preview=outputs.zura_hdr_save_preview?.images?.[0];
      const hlg=outputs.zura_hdr_save_video?.images?.[0],exr=outputs.zura_hdr_archive?.files?.[0];
      if(!preview || (!hlg&&!exr))throw new Error('HDR conversion finished without the requested files.');
      this.$('preview').src=this.url(preview);for(const [name,file] of [['hlg',hlg],['exr',exr]]){this.$(name).hidden=!file;if(file)this.$(name).href=this.url(file);}
      this.$('result').hidden=false;this.status('HDR conversion complete.');this.finish();
    }catch(error){this.status(error.message);this.finish();}
  }
  async cancel(){if(!this.job)return;try{await this.request('/queue',{delete:[this.job]});await this.request('/interrupt',{prompt_id:this.job});this.status('Cancellation requested.');this.finish();}catch(error){this.status(error.message);}}
  finish(){clearTimeout(this.timer);this.timer=null;this.job=null;try{localStorage.removeItem('zura-hdr-active-job');}catch{}this.busy=false;this.$('start-job').disabled=false;this.$('cancel').hidden=true;this.$('progress').hidden=true;}
  close(){clearTimeout(this.timer);this.api.removeEventListener?.('progress',this.onProgress);this.$('preview').pause?.();this.root.remove();}
}

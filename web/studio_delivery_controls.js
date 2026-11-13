import {workspaceStorage} from './studio_storage.js';
import {activeStudioMode,studioModeAdapter} from './studio_mode_adapters.js';
import {LTXHDRDelivery} from './studio_ltx_delivery.js';

const KEY='zura-studio-colour-delivery-v1',RECORDS='zura-studio-hdr-deliveries-v1';
const HDR_SPACES=new Set(['acescg','acescct','linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3']);
const SDR_SPACES=new Set(['srgb_display','rec709_oetf','rec709_gamma24']);
const FORMATS=new Set(['hlg_video','hlg_and_exr','acescg_exr']);
const fileKey=file=>file?.filename?`${file.type||'output'}:${file.subfolder||''}/${file.filename}`:'';
const read=(storage,key,fallback)=>{try{return JSON.parse(storage.getItem(key))||fallback;}catch{return fallback;}};
const isFile=file=>file?.type==='output'&&typeof file.filename==='string';
const hdrSpace=value=>typeof value==='string'&&(HDR_SPACES.has(value.toLowerCase())||/acescg|acescct|linear|rec\.?2020|2084|hlg|\bpq\b/i.test(value));
const activeJob=w=>!!(w?.busy===true||w?.job||w?.pendingSubmission||w?.submitting||w?.uploading||w?.picking||w?.exporting||w?.toolJob||w?.project?.phase==='working'||w?.hdrOutput?.busy||w?.hdrDelivery?.busy);

export function studioInputDescription(source){
  let value=source?.colour?.encoding||source?.resolved_colour||source?.colour_space||source?.native_hdr?.colour_space||source?.native_hdr_video?.colour_space||'';
  if(['','auto','unknown'].includes(value))value=({'arib-std-b67':'hlg_rec2020',smpte2084:'pq_rec2020',bt709:'rec709_oetf','iec61966-2-1':'srgb_display'})[source?.transfer]||value;
  const working=source?.colour?.ocioWorkingSpace||'';
  const space=HDR_SPACES.has(value)?value:SDR_SPACES.has(value)?value:value==='auto'&&(source?.native_hdr||source?.native_hdr_video)?'auto':'';
  const hdr=!!(hdrSpace(value)||hdrSpace(working)||source?.native_hdr||source?.native_hdr_video||source?.colour?.sceneLinear===true);
  return {input:hdr?'hdr':'sdr',space:space||(!hdr?'srgb_display':''),detected:!!value||!!working};
}

export function studioHDRDescriptor(raw,record){
  if(record?.state!=='complete')return null;
  const files=record.take?.hdrFiles||[],master=files.find(f=>/\.(zip|exr)$/i.test(f.filename||''))||files.find(f=>/\.(mov|mp4)$/i.test(f.filename||''));
  if(!isFile(master))return null;
  return {kind:/\.(zip|exr)$/i.test(master.filename)?'hdr_sequence':'video',master,
    preview:record.take.original?.preview||raw.preview||raw.original||raw.master,colour:/\.(zip|exr)$/i.test(master.filename)?{encoding:'acescg',sceneLinear:true}:{encoding:'hlg_rec2020',sceneLinear:false},
    ...(record.take.alphaAssociation==='straight'?{alpha:'straight'}:{}),
    ...(record.take.config?.ae_frame_contract?{fps:record.take.config.ae_frame_contract.frameRate.numerator/record.take.config.ae_frame_contract.frameRate.denominator}:{})};
}

/** One visible delivery choice. Generated SDR and converted HDR remain separate masters. */
export class StudioDeliveryControls {
  constructor(root,api,owner,settings){
    this.root=root;this.api=api;this.owner=owner;this.settings=settings;this.storage=workspaceStorage(owner);
    const saved=read(this.storage,KEY,{});this.output=saved.output==='hdr'?'hdr':'sdr';this.inputOverrides=saved.inputs||{};this.hdrFormat=FORMATS.has(saved.hdrFormat)?saved.hdrFormat:'hlg_and_exr';
    this.records=read(this.storage,RECORDS,{});this.bound=new WeakSet();this.configured=new WeakSet();this.readingOutput=false;this.closed=false;
    const doc=root.ownerDocument,style=doc.createElement('link');style.rel='stylesheet';style.href=new URL('./studio_delivery_controls.css',import.meta.url).href;doc.head.append(style);
    this.element=doc.createElement('section');this.element.className='zc-delivery-controls';this.element.setAttribute('aria-label','Input and output colour');
    this.element.innerHTML='<label>Input:<select data-delivery-input aria-label="Input range"><option value="sdr">SDR</option><option value="hdr">HDR</option></select></label><label>Output:<select data-delivery-output aria-label="Output range"><option value="sdr">SDR</option><option value="hdr">HDR</option></select></label><details data-delivery-space-wrap hidden><summary>Source colour</summary><label>Colour space<select data-delivery-space aria-label="Actual source colour space"><option value="">Choose source colour space</option><option value="srgb_display">sRGB</option><option value="rec709_oetf">Rec.709</option><option value="rec709_gamma24">Rec.709 gamma 2.4</option><option value="acescg">ACEScg</option><option value="acescct">ACEScct</option><option value="linear_rec709">Linear Rec.709</option><option value="hlg_rec2020">Rec.2020 HLG</option><option value="pq_rec2020">Rec.2020 PQ</option></select></label></details><span data-delivery-display></span><span data-delivery-status role="status" aria-live="polite"></span><button type="button" data-delivery-cancel hidden>Cancel HDR</button><span data-delivery-files></span>';
    root.querySelector('.gs-top').after(this.element);this.$=key=>this.element.querySelector('[data-delivery-'+key+']');this.displayHost=this.$('display');
    const p3=doc.createElement('option');p3.value='pq_display_p3';p3.textContent='Display P3 PQ';this.$('space').append(p3);
    this.$('space-wrap').querySelector('summary').textContent='Advanced';this.sourceSpaceRow=this.$('space').closest('label');
    this.advancedPanel=doc.createElement('div');this.advancedPanel.className='zc-delivery-advanced-panel';this.$('space-wrap').append(this.advancedPanel);this.advancedPanel.append(this.sourceSpaceRow);
    this.$('input').onchange=()=>this.changeInput(this.$('input').value);
    this.$('space').onchange=()=>this.changeInput(this.$('input').value,this.$('space').value);
    this.$('output').value=this.output;this.$('output').onchange=()=>{this.output=this.$('output').value;this.save();this.sync();if(this.output==='hdr')void this.convertCurrent();};
    this.$('cancel').onclick=()=>this.cancel();
    this.delivery=new LTXHDRDelivery(api,{storage:this.storage,key:'zura-shared-hdr-delivery',onUpdate:job=>this.onUpdate(job),onComplete:take=>this.onComplete(take)});
    const show=owner.show;owner.show=(...args)=>{const result=show.apply(owner,args);this.sync();return result;};
    const close=owner.close;if(typeof close==='function')owner.close=(...args)=>{this.close();return close.apply(owner,args);};
    queueMicrotask(()=>{if(!this.closed){this.sync();this.delivery.resume();}});
  }
  save(){try{this.storage.setItem(KEY,JSON.stringify({output:this.output,hdrFormat:this.hdrFormat,inputs:this.inputOverrides}));this.storage.setItem(RECORDS,JSON.stringify(Object.fromEntries(Object.entries(this.records).slice(-40))));}catch{}}
  setHDRFormat(value){if(!FORMATS.has(value))return;this.hdrFormat=value;this.save();this.sync();}
  mountAdvanced(exrLabel,formatLabel,note){this.advancedPanel.append(exrLabel,formatLabel);if(note)this.advancedPanel.append(note);this.hasExportAdvanced=true;this.$('space-wrap').hidden=false;}
  workspace(mode=activeStudioMode(this.owner)){return studioModeAdapter(mode)?.resolveWorkspace(this.owner);}
  source(w){
    const ae=this.owner.studio?.aeBridge?.source;if(ae)return ae;
    if(w===this.owner)return w.references?.[0]||null;
    if(w&&w===this.owner.studio?.hdrTool){
      const kind=w.$('source-kind').value;
      const selected=w.outputRef||w.output;
      if(kind==='output'&&selected){const native=w.$('mode').value==='native';return {...w.sourceInfo,file:selected,colour_space:native?(w.$('colour')?.value||'auto'):'srgb_display',...(native?{native_hdr:{colour_space:w.$('colour')?.value||'auto'}}:{})};}
      if(kind==='sequence')return w.sequenceAsset||null;
      if(kind==='own')return w.ownAsset||null;
      if(kind==='upload')return w.getSource?.()||null;
    }
    const source=w?.sourceInfo||w?.source||w?.sequenceAsset||w?.getSource?.()||w?.state?.sourceInfo||w?.state?.source||w?.assets?.first||w?.assets?.images?.[0]||w?.project?.source||null;
    return source?.processingView?.originalSource||source;
  }
  sourceKey(w){const s=this.source(w);return typeof s==='string'?s:s?.manifest?.relativePath||s?.studioAsset?.id||s?.id||s?.path||(typeof s?.file==='string'?s.file:fileKey(s?.file))||fileKey(s)||'';}
  input(w){const detected=studioInputDescription(this.source(w)),override=this.inputOverrides[this.sourceKey(w)],declared=w?.state?.sourceColour;if(!detected.detected&&(HDR_SPACES.has(declared)||SDR_SPACES.has(declared))){detected.input=HDR_SPACES.has(declared)?'hdr':'sdr';detected.space=declared;}return override?{...detected,...override}:detected;}
  changeInput(input,space){
    const mode=activeStudioMode(this.owner),w=this.workspace(mode),key=this.sourceKey(w);if(!key||activeJob(w)||this.isBusyFor(mode))return;
    if(this.owner.studio?.aeBridge?.source)return this.message('Input colour follows the After Effects source interpretation');
    const prior=this.input(w);space=space??(input===prior.input?prior.space:input==='sdr'?'srgb_display':'');
    this.inputOverrides[key]={input,space};this.save();
    if(w?.state&&space){w.state.sourceColour=space;w.state.sourceColourConfirmed=true;}
    const select=w?.$?.('colour');if(select&&space)select.value=space;
    w?.save?.();this.sync();
  }
  configure(w,config,mode){
    const input=this.input(w);
    const inferenceView=mode!=='hdr'&&(this.owner.studio?.aeBridge?.source?.processingInput?.precision?.sourceBitDepth===8||config.processingView?.kind==='sdr8_inference'||mode==='image'&&w?.references?.[0]?.processingView?.kind==='sdr8_inference');
    const result={...config,studioDelivery:{schemaVersion:1,input:input.input,inputColourSpace:input.space,output:this.output,hdrFormat:this.hdrFormat,...(inferenceView?{processingColourSpace:'srgb_display'}:{})},exr_storage:this.settings.exrStorage(this.hdrFormat)};
    if(!inferenceView&&input.space&&'sourceColour' in result)result.sourceColour=input.space;
    if(mode==='frames')result.hdrOutput=this.output==='hdr'||input.input==='hdr'?this.hdrFormat:'sdr';
    // Remove retains its original mask/clean-frame repair. SDR-to-HDR is a
    // separate delivery after the complete SDR repair, rather than a tag.
    if((mode==='paintout'&&!this.owner.plate?.propagation()||mode==='watermark')&&(input.input==='sdr'||inferenceView))Object.assign(result,{colourPipeline:'sdr_sdr',processingSpace:'SDR (sRGB)',outputMode:'SDR video'});
    if((mode==='paintout'&&!this.owner.plate?.propagation()||mode==='watermark')&&input.input==='hdr'&&!inferenceView)Object.assign(result,{colourPipeline:'hdr_hdr',processingSpace:'HDR (ACEScct)',outputMode:'EXR + HLG video',exrPrecision:result.exr_storage==='float32'?'float32':'float16'});
    return result;
  }
  bindConfig(target,mode,workspace=target){
    if(!target||this.configured.has(target)||typeof target.config!=='function')return;
    const original=target.config;target.config=(...args)=>this.configure(workspace,original.apply(target,args),mode);this.configured.add(target);
  }
  raw(mode){const adapter=studioModeAdapter(mode);if(!adapter)return null;this.readingOutput=true;try{return adapter.getSelectedOutput(this.owner);}finally{this.readingOutput=false;}}
  resultKey(mode,raw,format=this.hdrFormat){return raw?.master?`${mode}:${fileKey(raw.master)}:${format}`:'';}
  recordFor(mode,raw){const exact=this.records[this.resultKey(mode,raw)];if(exact)return exact;const prefix=`${mode}:${fileKey(raw?.master)}:`;return Object.entries(this.records).find(([key,record])=>key.startsWith(prefix)&&record.state==='complete')?.[1];}
  alreadyHDR(raw){return raw?.kind==='hdr_sequence'||hdrSpace(raw?.colour?.encoding)||raw?.colour?.sceneLinear===true||hdrSpace(raw?.colour?.ocioWorkingSpace);}
  isBusyFor(mode){return this.activeMode===mode&&!!(this.preparing||this.delivery?.busy);}
  outputFor(mode,raw){
    if(this.readingOutput||!raw)return raw;
    if(this.output==='sdr'){
      if(this.alreadyHDR(raw)){
        const w=this.workspace(mode),preview=raw.preview||w?.selectedResult?.file||w?.selectedResult||w?.result?.file||w?.completedResult?.preview;
        if(isFile(preview)&&!/\.(zip|exr)$/i.test(preview.filename))return {kind:/\.(png|jpe?g|webp)$/i.test(preview.filename)?'image':'video',master:preview,colour:{encoding:'unknown',sceneLinear:false}};
      }
      return raw;
    }
    if(this.alreadyHDR(raw))return raw;
    return studioHDRDescriptor(raw,this.recordFor(mode,raw));
  }
  bind(w,mode){
    if(!w)return;this.bindConfig(w,mode);
    if(this.bound.has(w))return;this.bound.add(w);
    if(mode==='hdr'&&typeof w.start==='function'){
      const start=w.start;w.start=(...args)=>this.output==='hdr'?start.apply(w,args):this.message('Choose HDR output to convert this source');
    }
    for(const method of ['render','paint'])if(typeof w[method]==='function'){
      const original=w[method];w[method]=(...args)=>{const value=original.apply(w,args);this.sync();return value;};
    }
    for(const method of ['generate','onGenerate','run'])if(typeof w[method]==='function'){
      const original=w[method];w[method]=(...args)=>{
        const current=this.input(w);
        if(this.isBusyFor(mode))return w.message?.('Wait for HDR delivery or cancel it before generating again.');
        const inferenceView=mode!=='hdr'&&this.owner.studio?.aeBridge?.source?.processingInput?.precision?.sourceBitDepth===8;
        if(current.input==='hdr'&&!current.space&&!inferenceView&&!(method==='run'&&['prepare','approve'].includes(args[0])))return w.message?.('Choose the actual HDR source colour space before generating.');
        if(method==='onGenerate'&&this.prepareInferenceView){
          return Promise.resolve(this.prepareInferenceView(w,mode,args[0]||{})).then(config=>{if(config)args[0]=this.configure(w,config,mode);return original.apply(w,args);}).catch(error=>w.message?.(error.message));
        }
        return original.apply(w,args);
      };
    }
    if(typeof w.poll==='function'){
      const original=w.poll;w.poll=async(...args)=>{
        const selectedMode=w===this.owner.studio?(w.project?.config?.workflow_mode||w.config?.workflow_mode||mode):mode;
        const currentMode=selectedMode==='motion'?'swap':selectedMode;
        const before=w.job||w.project?.phase==='working',config=w.job?.config||w.config,old=this.raw(currentMode);
        const value=await original.apply(w,args);
        const raw=this.raw(currentMode);
        if(before&&!w.job&&w.project?.phase!=='working'&&raw&&fileKey(raw.master)!==fileKey(old?.master))void this.completed(currentMode,w,raw,typeof config==='object'?config:{});
        return value;
      };
    }
  }
  nativeDelivery(mode,w){return mode==='hdr'||w?.hdrOutput?.busy||w?.hdrDelivery?.busy||w?.hdrSubmitting||w===this.owner.studio&&(this.owner.videoComposer?.ltxOutput?.delivery?.busy||this.owner.videoComposer?.ltxOutput?.submitting);}
  async completed(mode,w,raw,config){
    const intent=config.studioDelivery||{output:this.output,hdrFormat:this.hdrFormat};
    if(intent.output!=='hdr'||this.nativeDelivery(mode,w)||this.alreadyHDR(raw))return;
    return this.convert(mode,w,raw,{...config,...(intent.hdrFormat?{hdrOutput:intent.hdrFormat}:{})});
  }
  async convertCurrent(){const mode=activeStudioMode(this.owner),w=this.workspace(mode),raw=this.raw(mode);if(raw&&!activeJob(w)&&!this.nativeDelivery(mode,w))return this.convert(mode,w,raw,typeof w.config==='function'?w.config():w.config||{});}
  async convert(mode,w,raw,config={}){
    if(this.closed||this.preparing||this.delivery.busy||this.alreadyHDR(raw))return;
    const alphaRef=raw.alpha_ref||(raw.kind==='alpha_extract'?raw.master:null),rgbMaster=raw.kind==='alpha_extract'?raw.original:raw.master;
    if(mode==='alpha'&&!alphaRef)return this.message('This take has no retained FLOAT alpha master. Regenerate its alpha to create HDR with the original precision.');
    const image=raw.kind==='image';if(!image&&!/\.(mp4|mov|mkv|webm)$/i.test(rgbMaster?.filename||''))return this.message('This master needs a native HDR delivery route. Your original is retained.');
    let format=FORMATS.has(config.hdrOutput)?config.hdrOutput:this.hdrFormat;
    if(alphaRef&&format==='hlg_video')format='hlg_and_exr';
    const key=this.resultKey(mode,raw,format);
    if(this.records[key]?.state==='complete')return this.sync();
    if(['unknown','preparing'].includes(this.records[key]?.state))return this.message('Check the saved HDR job before starting another conversion. Your original master is retained.');
    this.activeMode=mode;this.preparing=true;this.preparationCancelled=false;this.message('Checking HDR delivery…');this.sync();
    try{
      const clock=config.ae_frame_contract?.frameRate;
      const info=await this.delivery.client.request('/zura/studio/hdr/source-info',{source_kind:image?'output_image':'output',output_ref:rgbMaster,...(image?{sequence_fps:clock?clock.numerator/clock.denominator:24,...(config.ae_frame_contract?{ae_frame_contract:config.ae_frame_contract}:{})}:{})});
      if(info.hasAlpha&&format==='hlg_video')format='hlg_and_exr';
      const original=mode==='alpha'&&isFile(w.result?.preview)?{...raw,preview:w.result.preview}:raw;
      const take={studioMode:mode,resultKey:key,kind:image?'image':'video',file:rgbMaster,original,...(alphaRef?{alpha_ref:alphaRef}:{}),
        config:{...config,engine:config.engine||'studio',frames:info.frames,width:info.width,height:info.height,fps:info.fps,...(image?{single_frame:true}:{}),hdrSourceColour:info.transfer==='bt709'?'rec709_oetf':'srgb_display',hdrOutput:format,exr_storage:alphaRef||info.hasAlpha?'float32':this.settings.exrStorage(format)}};
      await this.delivery.preflight(take.config);
      if(this.closed||this.preparationCancelled){this.records[key]={state:'cancelled',take};this.save();this.message('HDR conversion cancelled. Your original master is retained.');return;}
      this.records[key]={state:'preparing',take};this.save();await this.delivery.start(take);
    }catch(error){this.records[key]={state:'failed',error:error.message,original:raw};this.save();this.message(error.message+' Your original master is retained.');}
    finally{this.preparing=false;this.sync();}
  }
  message(text){this.$('status').textContent=text||'';}
  cancel(){if(this.preparing&&!this.delivery.busy){this.preparationCancelled=true;this.message('Cancelling HDR preparation…');return;}return this.delivery.cancel();}
  onUpdate(job){
    const take=this.delivery.take;this.activeMode=take?.studioMode||this.activeMode;
    if(take&&['failed','cancelled','unknown'].includes(job.state)){this.records[take.resultKey]={state:job.state,take,error:job.error};this.save();}
    this.message(({preparing:'Preparing HDR conversion…',queued:'HDR conversion queued',rendering:'Converting to HDR…',saving:'Saving HDR masters…',reconnecting:'Reconnecting to HDR conversion…',cancelling:'Cancelling HDR conversion…',complete:'HDR masters ready',cancelled:'HDR conversion cancelled. Your original master is retained.'})[job.state]||job.error||'Preparing HDR delivery…');this.sync();
  }
  onComplete(take){this.records[take.resultKey]={state:'complete',take};this.save();this.message(take.alphaAssociation==='straight'?'HDR with alpha ready · FLOAT EXR · Preview is SDR':'HDR masters ready · Preview is SDR');this.sync();this.owner.studio?.aeBridge?.updateMeta?.();}
  sync(){
    if(this.closed||this.syncing)return;this.syncing=true;
    try{
      const mode=activeStudioMode(this.owner),w=this.workspace(mode);this.bind(w,mode);
      if(w===this.owner.studio&&w.config){w.config.ltx_output=this.output==='hdr'||this.input(w).input==='hdr'?this.hdrFormat:'sdr';w.config.studioDelivery={schemaVersion:1,output:this.output,hdrFormat:this.hdrFormat};}
      if(mode==='frames'){
        const control=w?.$?.('output-control');if(control)control.hidden=true;
      }
      // Preserve the native bindings while the global controls own their UI.
      if(w===this.owner.studio&&this.owner.videoComposer?.ltxOutput?.control)this.owner.videoComposer.ltxOutput.control.hidden=true;
      if(w?.sourceColourControl)w.sourceColourControl.hidden=true;
      if((mode==='paintout'&&!this.owner.plate?.propagation())||mode==='watermark')for(const id of ['colour','processing','output','pipeline','source-colour-confirm']){const control=w?.$?.(id);if(control)control.closest('label')?.setAttribute('hidden','');}
      if(mode==='outpaint'){const control=w?.$?.('hdr-output');if(control)control.closest('label')?.setAttribute('hidden','');}
      if(mode==='outpaint'){const control=w?.$?.('delivery');if(control){control.value=this.output==='hdr'?this.hdrFormat:'sdr';control.closest('label')?.setAttribute('hidden','');}}
      if(mode==='hdr'){
        for(const id of ['colour','output','mode']){const control=w?.$?.(id);if(control)control.closest('label')?.setAttribute('hidden','');}
        const output=w?.$?.('output');if(output)output.value=this.hdrFormat;
        const nativeMode=w?.$?.('mode'),wanted=this.input(w).input==='hdr'?'native':'sdr';
        if(nativeMode&&this.sourceKey(w)&&nativeMode.value!==wanted){nativeMode.value=wanted;w.sourceModeManual=true;w.updateMode?.();}
      }
      if(this.owner.plate&&this.owner.paintout){this.bindConfig(this.owner.plate,'paintout',this.owner.paintout);if(this.owner.plate.runner)this.bind(this.owner.plate.runner,'paintout');}
      const input=this.input(w),busy=activeJob(w)||this.isBusyFor(mode);
      const aeSource=!!this.owner.studio?.aeBridge?.source;
      this.$('input').value=input.input;this.$('input').disabled=!this.sourceKey(w)||busy||aeSource;this.$('input').title=aeSource?'Verified After Effects source interpretation':input.detected?'Detected from source metadata':'SDR is assumed until source metadata or an override is available';
      this.$('output').value=this.output;this.$('output').disabled=busy;
      this.$('space').value=input.space||'';this.$('space').disabled=busy||aeSource;this.sourceSpaceRow.hidden=!this.sourceKey(w)||aeSource;this.$('space-wrap').hidden=!this.hasExportAdvanced&&this.sourceSpaceRow.hidden;this.$('space-wrap').classList.toggle('needs-choice',input.input==='hdr'&&!input.space);
      if(input.input==='hdr'&&!input.space&&!busy&&!aeSource)this.message('Choose the actual HDR source colour space');
      this.$('cancel').hidden=!this.isBusyFor(mode);this.$('files').replaceChildren();
      const raw=this.raw(mode),record=raw&&this.recordFor(mode,raw);
      const availableFiles=record?.state==='complete'?record.take.hdrFiles||[]:this.alreadyHDR(raw)&&isFile(raw?.master)?[raw.master]:[];
      if(this.output==='hdr')for(const file of availableFiles){const a=this.root.ownerDocument.createElement('a');a.textContent=/\.(zip|exr)$/i.test(file.filename)?'EXR':'HDR video';a.href=this.api.apiURL('/view?'+new URLSearchParams(file));a.download=file.filename;this.$('files').append(a);}
    }finally{this.syncing=false;}
  }
  close(){this.closed=true;this.delivery.close();this.save();}
}

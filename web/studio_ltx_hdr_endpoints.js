// Native HDR assets retain their uploaded EXR identity. The PNG is display-only.
export const isHDREndpoint=asset=>asset?.asset_kind==='hdr_endpoint';
export const hasHDREndpoint=config=>isHDREndpoint(config.first)||isHDREndpoint(config.last);
export class LTXHDREndpoints{
  constructor(api,request){this.api=api;this.request=request;this.info=null;}
  async refresh(output='hlg_and_exr'){
    try{this.info=await this.request('/zura/studio/ltx/hdr-endpoints/readiness?'+new URLSearchParams({output}));}
    catch{this.info={enabled:false,ready:false};}
    return this.info;
  }
  validate(c){
    if(c.engine!=='ltx')throw new Error('EXR endpoints need LTX 2.5. Select LTX or remove the EXR images.');
    if(!this.info?.enabled)throw new Error('Native HDR endpoints are not enabled on this server.');
    if(!isHDREndpoint(c.first))throw new Error('Add an EXR first frame for native HDR generation.');
    if(c.last&&!isHDREndpoint(c.last))throw new Error('Use an EXR last frame, or remove it for first-frame-only HDR.');
    if(!['hlg_video','hlg_and_exr','acescg_exr'].includes(c.hdrOutput))throw new Error('Choose an HDR output for these EXR frames.');
    if(!String(c.prompt||'').trim())throw new Error('Describe the video you want to generate.');
    if(![c.width,c.height].every(n=>Number.isInteger(n)&&n>=512&&n<=2048&&n%64===0))throw new Error('Native HDR uses 512–2048 pixels per side, in multiples of 64.');
    if(!Number.isInteger(c.frames)||c.frames<9||c.frames>361||(c.frames-1)%8)throw new Error('LTX needs 8n + 1 frames, from 9 to 361.');
    const budget=this.info.limits?.maxPixelFrames||40000000;
    if(c.width*c.height*c.frames>budget){const limit=Math.min(361,1+8*Math.floor((Math.floor(budget/(c.width*c.height))-1)/8));throw new Error(`This HDR selection exceeds the software memory budget. At this size choose up to ${limit} frames (${(limit/24).toFixed(2)}s), or reduce resolution.`);}
    if(c.audioEnabled&&!c.audio?.file)throw new Error('Add an audio reference, or switch Audio reference off.');
  }
  async upload(file){
    if(!this.info?.enabled)await this.refresh();
    if(!this.info?.enabled)throw new Error('Native HDR endpoints are not enabled on this server.');
    const data=new FormData();data.append('frames',file);
    const response=await this.api.fetchApi('/zura/studio/hdr/exr-sequence',{method:'POST',body:data,timeoutMs:300000});
    const asset=await response.json();if(!response.ok)throw new Error(asset.error||'EXR upload failed.');
    const endpoint=await this.request('/zura/studio/ltx/hdr-endpoints/preview',{asset_id:asset.id,colour_space:'auto'});
    return {...endpoint,filename:endpoint.preview.filename,subfolder:endpoint.preview.subfolder,
      file:[endpoint.preview.subfolder,endpoint.preview.filename].filter(Boolean).join('/'),name:file.name};
  }
  async graph(c){
    await this.refresh(c.hdrOutput);this.validate(c);
    if(!this.info.ready)throw new Error('Native HDR setup is incomplete: '+[...(this.info.files||[]).filter(f=>!f.ready).map(f=>f.filename),...(this.info.missingNodes||[])].join(', '));
    const result=await this.request('/zura/studio/ltx/hdr-endpoints/graph',{
      first_id:c.first.id,last_id:c.last?.id,first_colour:c.first.colour_space,last_colour:c.last?.colour_space,
      width:c.width,height:c.height,frames:c.frames,prompt:c.prompt,seed:c.seed,output:c.hdrOutput,
      audio_enabled:c.audioEnabled,audio_file:c.audio?.file,audio_start:c.audioStart||0,custom_loras:c.custom_loras||[]});
    return result.graph;
  }
}

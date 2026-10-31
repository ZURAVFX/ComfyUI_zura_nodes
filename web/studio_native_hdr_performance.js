// The original HDR image or video frame is generation data. Its PNG is only a display proxy.
export const nativePerformanceOpening=studio=>(studio.lookMode==='ready'?studio.readyAsset?.native_hdr:null)||studio.project?.opening_input?.native_hdr;

export function preferredHDRFile(files){
  const valid=(files||[]).filter(file=>file?.type==='output'&&typeof file.filename==='string');
  return valid.find(file=>/\.mp4$/i.test(file.filename))||valid.find(file=>/\.zip$/i.test(file.filename))||null;
}

export function validateNativePerformance(config){
  if(config.engine!=='local'||config.workflow_mode!=='motion'||config.edit_area!=='scene'||config.viewport_render)
    throw new Error('Choose LTX whole-scene performance to use an HDR starting frame.');
  if(!['hlg_video','hlg_and_exr','acescg_exr'].includes(config.ltx_output))
    throw new Error('Choose an HDR output for your HDR starting frame.');
}

async function json(api,path,options){
  const response=await api.fetchApi(path,options),body=await response.json();
  if(!response.ok)throw new Error(body.error||'Native HDR preparation failed.');
  return body;
}

export async function uploadNativePerformanceOpening(api,file,config,enabled,signal){
  if(!enabled)throw new Error('Native HDR performance is an opt-in development preview and is not enabled on this server.');
  validateNativePerformance({...config,ltx_output:config.ltx_output==='sdr'||!config.ltx_output?'hlg_and_exr':config.ltx_output});
  const data=new FormData();data.append('frames',file);
  const asset=await json(api,'/zura/studio/hdr/exr-sequence',{method:'POST',body:data,signal,timeoutMs:300000});
  return json(api,'/zura/studio/ltx/hdr-performance/opening',{method:'POST',
    body:JSON.stringify({asset_id:asset.id,colour_space:'auto'}),headers:{'Content-Type':'application/json'},signal,timeoutMs:300000});
}

export function nativePerformanceReadiness(api,output){
  return json(api,'/zura/studio/ltx/hdr-performance/readiness?'+new URLSearchParams({output}));
}

export function mainNativeLTXTake(project,result){
  if(!project?.id||result?.stage!=='restyle'||result.native_hdr!==true||!result.asset?.filename||result.asset.type!=='output'
    ||!['hlg_video','hlg_and_exr','acescg_exr'].includes(result.hdr_output)
    ||!Array.isArray(result.hdr_files)||!result.hdr_files.length
    ||result.hdr_files.some(file=>file.type!=='output'||!file.filename))return null;
  return {projectId:project.id,resultKey:`${project.id}:${result.action_id||result.asset.filename}`,
    file:result.asset,hdrFiles:result.hdr_files,nativeHDR:true};
}

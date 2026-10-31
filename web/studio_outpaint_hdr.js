// Only the actual, inspected SDR render may be sent to the HDR converter.
// Review overlays and the SDR preview of a native HDR result are never inputs.
export function outpaintHDRTake(state, output, seed=42){
  if(state?.kind!=='render'||state.state!=='complete'||state.hdr!==false||
     !['hlg_video','hlg_and_exr','acescg_exr'].includes(output))return null;
  const file=state.artifact, raster=state.output_raster;
  if(file?.type!=='output'||file.subfolder?.replaceAll('\\','/')!=='genj/outpaint'||
     typeof file.filename!=='string'||!file.filename.toLowerCase().endsWith('.mp4')||
     /[\\/]/.test(file.filename)||file.filename==='..'||
     !raster||![raster.width,raster.height,raster.frames].every(v=>Number.isInteger(v)&&v>0)||
     raster.fps!==24||typeof raster.has_audio!=='boolean')return null;
  return {resultKey:state.id,file,sdrFile:file,
    config:{engine:'ltx',hdrOutput:output,frames:raster.frames,width:raster.width,
      height:raster.height,seed},hasAudio:raster.has_audio};
}

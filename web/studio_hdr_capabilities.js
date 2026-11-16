import {hasHDREndpoint} from './studio_ltx_hdr_endpoints.js';
import {nativePerformanceOpening} from './studio_native_hdr_performance.js';

const spaces=new Set(['acescg','acescct','linear_rec709','scene_linear_rec709','hlg_rec2020','pq_rec2020','pq_display_p3']);
const hdr=source=>!!source&&(spaces.has(source.resolved_colour)||spaces.has(source.colour_space)||spaces.has(source.colour?.encoding)||source.colour?.sceneLinear===true||!!source.native_hdr||!!source.native_hdr_video||source.asset_kind==='hdr_sequence'||source.asset_kind==='hdr_endpoint');
const engine=(w,c)=>c.engine||w?.state?.engine||w?.$?.('engine')?.value;

/** A route is native only when its actual HDR graph/input path is selected. */
export function nativeHDRRoute(owner,mode,w,config={}){
  if(mode==='hdr')return 'hdr-tool';
  const propagation=owner?.plate?.propagation?.()===true;
  if((mode==='paintout'&&!propagation||mode==='watermark')&&
      (config.colourPipeline==='hdr_hdr'||w?.state?.colourPipeline==='hdr_hdr'||hdr(w?.sourceInfo)||spaces.has(config.sourceColour)||spaces.has(w?.state?.sourceColour)))return 'ltx-hdr-repair';
  if(mode==='frames'&&engine(w,config)==='ltx'&&hasHDREndpoint({first:config.first||w?.assets?.first,last:config.last||w?.assets?.last}))return 'ltx-hdr-endpoints';
  if((mode==='swap'||mode==='motion')&&w===owner?.studio&&
      (config.engine||w.config?.engine)==='local'&&(config.edit_area||w.config?.edit_area)==='scene'&&nativePerformanceOpening(w))return 'ltx-hdr-performance';
  if(mode==='outpaint'&&w?.isHDRSource&&
      (w.mode==='black'?w.capabilities?.hdr_black_experiment:w.capabilities?.hdr_expand_experiment))return 'ltx-hdr-frame-extension';
  return null;
}

/** Prefer the retained native asset over AE's separate SDR inference copy. */
export function preferNativeHDRSource(owner,mode,source){
  if(owner?.outputSettings?.delivery?.output!=='hdr'||!hdr(source?.studioAsset))return false;
  if(mode==='watermark'||mode==='paintout'&&owner.plate?.propagation?.()!==true)return true;
  if(mode==='frames')return owner.frames?.$?.('engine')?.value==='ltx'&&owner.frames?.nativeHDR?.info?.enabled===true;
  if(mode==='swap')return source.studioAsset.native_hdr_video&&owner.studio?.config?.engine==='local'&&owner.studio?.config?.edit_area==='scene'&&owner.studio?.modelStatus?.native_hdr_performance===true;
  return false;
}

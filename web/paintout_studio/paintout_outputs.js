import {deliveryVideoColour} from '../studio_delivery_formats.js';
const valid=file=>file?.type==='output'&&typeof file.filename==='string';
const key=file=>valid(file)?`${file.subfolder||''}/${file.filename}`:'';
const archive=file=>/\.(exr|zip)$/i.test(file?.filename||'');
const video=file=>/\.(mp4|mov|mkv|webm)$/i.test(file?.filename||'');
export const paintoutPreviewFile=(file,preview)=>/preview/i.test(file?.filename||'')||!!key(preview)&&key(file)===key(preview);

/** Only returned assets can acquire a role; never derive a companion path. */
export function paintoutOutputRoles(result={},options={}){
  const auxiliaries=(result.exports||result.zura_exports||[]).filter(item=>['exr','image'].includes(item?.role)&&valid(item.file)).map(item=>item.file);
  const files=[...(result.files||[]),...(result.hdrFiles||[]),...auxiliaries,result.preview,result.sdrMaster,result.hdrMaster,result.master,result.file].flatMap(file=>[file,file?.preview]).filter(valid);
  const unique=[...new Map(files.map(file=>[key(file),file])).values()];
  const preview=valid(result.preview)?result.preview:unique.find(file=>paintoutPreviewFile(file))||null;
  const masters=unique.filter(file=>!paintoutPreviewFile(file,preview));
  const hdrFiles=new Set((result.hdrFiles||[]).filter(valid).map(key));
  const hdrMovieMode=/HLG|ProRes/i.test(options.outputMode||result.config?.outputMode||'');
  const hdrVideo=file=>video(file)&&!/(?:^|[_ -])SDR(?:[_ .-]|$)/i.test(file.filename)&&(/HLG/i.test(file.filename)||hdrMovieMode&&/\.mov$/i.test(file.filename)||hdrFiles.has(key(file))||key(file)===key(result.hdrMaster));
  const archiveMaster=masters.find(archive)||null;
  const imageMaster=masters.find(file=>/\.(png|tiff?|jpe?g|webp)$/i.test(file.filename))||null;
  const hlgMaster=masters.find(hdrVideo)||null;
  const sdrCandidates=masters.filter(file=>video(file)&&!hdrVideo(file)&&!/(?:HLG|PQ|HDR)/i.test(file.filename));
  const sdrMaster=sdrCandidates.find(file=>key(file)===key(result.sdrMaster))||sdrCandidates.find(file=>/SDR_10bit/i.test(file.filename))||sdrCandidates.find(file=>key(file)===key(result.master))||sdrCandidates[0]||null;
  const mode=options.outputMode||result.config?.outputMode||(archiveMaster||hlgMaster?'EXR + HLG video':'SDR video'),format=options.hdrFormat;
  const hdrMaster=format==='hlg_video'||mode==='HLG video'?hlgMaster:format==='acescg_exr'||mode==='EXR sequence'?archiveMaster:archiveMaster||hlgMaster;
  let master;
  if(options.output==='hdr')master=hdrMaster;
  else if(options.output==='sdr'||mode==='SDR video')master=sdrMaster||imageMaster;
  else if(mode==='HLG video')master=hlgMaster;
  else if(mode.includes('EXR'))master=archiveMaster||(mode.includes('HLG')?hlgMaster:mode.includes('SDR')?sdrMaster:null);
  else master=sdrMaster||hdrMaster;
  return {files:unique,preview,sdrMaster,hdrMaster,archiveMaster,hlgMaster,master:master||null};
}

export function paintoutOutputDescriptor(result,options={}){
  if(!result)return null;
  const roles=paintoutOutputRoles(result,options),master=roles.master;
  if(!master)return null;
  const hdr=key(master)===key(roles.archiveMaster)||key(master)===key(roles.hlgMaster);
  const {preview,...metadata}=roles;
  const sdrColour=result.colour&&['unknown','srgb_display','rec709_oetf','rec709_gamma24'].includes(result.colour.encoding)&&result.colour.sceneLinear!==true?result.colour:null;
  return {...metadata,...(preview?{preview}:{}),kind:/\.(exr|png|tiff?|jpe?g|webp)$/i.test(master.filename)?'image':archive(master)?'hdr_sequence':'video',master,
    ...(hdr?{colour:archive(master)?{encoding:'acescg',sceneLinear:true}:deliveryVideoColour(master,result)}:sdrColour?{colour:sdrColour}:{}),
    ...(result.alpha?{alpha:result.alpha}:{})};
}

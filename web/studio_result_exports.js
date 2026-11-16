import {paintoutOutputRoles} from './paintout_studio/paintout_outputs.js';

const roles=new Set(['mask','mask_sequence','exr','image']);
const folder=file=>String(file.subfolder||'').replaceAll('\\','/');
const fileKey=file=>`${file.type}:${folder(file)}/${file.filename}`;
const valid=file=>file?.type==='output'&&typeof file.filename==='string'&&!!file.filename&&!/[\\/\0]/.test(file.filename)&&typeof(file.subfolder||'')==='string'&&!/[:\0]/.test(folder(file))&&!folder(file).startsWith('/')&&!folder(file).split('/').some(part=>part==='.'||part==='..');

/** Auxiliaries are returned records, never candidates for the result master. */
export function captureResultExports(output,previous=[]){
  const values=[...(Array.isArray(previous)?previous:[]),...(Array.isArray(output?.zura_exports)?output.zura_exports:[])];
  return [...new Map(values.filter(item=>roles.has(item?.role)&&valid(item.file)).map(item=>[item.role+':'+fileKey(item.file),{role:item.role,file:{filename:item.file.filename,subfolder:folder(item.file),type:'output'}}])).values()];
}

export function paintoutExportLinks(result){
  if(!result||result.preview_only)return [];
  const actual=paintoutOutputRoles(result),movie=[actual.master,actual.hlgMaster,actual.sdrMaster].find(file=>valid(file)&&/\.(mov|mp4|mkv|webm)$/i.test(file.filename));
  const entries=[];
  if(movie)entries.push({role:'video',file:movie,label:/\.mov$/i.test(movie.filename)?'Save ProRes MOV':'Save video',title:'Save the finished video master. The viewport uses its playback preview.'});
  const returned=captureResultExports({zura_exports:result.exports||result.zura_exports});
  if(actual.archiveMaster&&!returned.some(item=>item.role==='exr'))returned.push({role:'exr',file:actual.archiveMaster});
  const names={mask:'Save mask MOV',mask_sequence:'Save mask frames',exr:'Save EXR',image:'Save image'};
  const tips={mask:'The final compositing mask: white is the generated repair, black is the original plate. Includes expansion, feathering and protected areas.',mask_sequence:'Lossless 16-bit PNG frames of the final compositing mask.',exr:'Save the returned EXR master or frame archive.',image:'Save the returned single-frame image.'};
  for(const role of ['mask','mask_sequence','exr','image'])for(const item of returned.filter(item=>item.role===role))entries.push({...item,label:names[role],title:tips[role]});
  return [...new Map(entries.map(item=>[fileKey(item.file),item])).values()];
}

export function installResultExportStyles(doc){
  if(doc.getElementById('zura-result-export-styles'))return;
  const link=doc.createElement('link');link.id='zura-result-export-styles';link.rel='stylesheet';link.href=new URL('./studio_result_exports.css',import.meta.url).href;doc.head.append(link);
}
export function createResultExportRow(doc){
  installResultExportStyles(doc);const row=doc.createElement('div');row.className='zc-result-exports';row.hidden=true;row.setAttribute('role','group');row.setAttribute('aria-label','Save result files');return row;
}
export function renderPaintoutResultExports(row,api,result){
  if(!row)return;const entries=paintoutExportLinks(result);row.hidden=!entries.length;
  const signature=JSON.stringify(entries);if(row.dataset.exportSignature===signature)return;row.dataset.exportSignature=signature;row.replaceChildren();
  for(const item of entries){const link=row.ownerDocument.createElement('a');link.dataset.resultExport=item.role;link.textContent=item.label;link.title=item.title;link.href=api.apiURL('/view?'+new URLSearchParams({filename:item.file.filename,subfolder:folder(item.file),type:'output'}));link.download=item.file.filename;row.append(link);}
}

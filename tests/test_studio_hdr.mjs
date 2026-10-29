import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {HDRSourceTool} from '../web/studio_hdr.js';
const {document,window}=parseHTML('<html><body><div id="host"></div></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const o of this.querySelectorAll('option'))o.selected=o.value===String(value);}});
globalThis.document=document;
const calls=[];
const outputs={
  zura_hdr_save_preview:{images:[{filename:'preview.mp4',subfolder:'genj/hdr',type:'output'}]},
  zura_hdr_save_video:{images:[{filename:'hdr.mp4',subfolder:'genj/hdr',type:'output'}]},
  zura_hdr_archive:{files:[{filename:'sequence.zip',subfolder:'genj/hdr',type:'output'}]}
};
const api={apiURL:p=>p,clientId:'test',addEventListener(){},removeEventListener(){},async fetchApi(path,options){
  calls.push([path,options?.body&&JSON.parse(options.body)]);
  const data=path==='/zura/studio/hdr/graph'||path==='/zura/studio/hdr/native-graph'?{graph:{verified:true}}:path==='/prompt'?{prompt_id:'job-1'}:path==='/history/job-1'?{'job-1':{status:{status_str:'success'},outputs}}:{};
  return {ok:true,async json(){return data;}};
}};
const tool=new HDRSourceTool(document.querySelector('#host'),api,()=>({id:'source-id',projectId:'project-id'}));
tool.$('count').value='10';tool.$('start').value='7';tool.$('output').value='hlg_and_exr';
await Promise.all([tool.start(),tool.start()]);await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(calls.filter(c=>c[0]==='/prompt').length,1,'Repeated click queues only once');
assert.equal(calls[0][1].start_frame,7);assert.equal(calls[0][1].frame_count,10);
assert.equal(tool.$('result').hidden,false);assert.match(tool.$('hlg').href,/hdr.mp4/);assert.match(tool.$('exr').href,/sequence.zip/);
assert.equal(tool.$('preview').src.includes('preview.mp4'),true);
tool.$('mode').value='native';tool.$('mode').onchange();
assert.match(tool.$('limits').textContent,/HLG video input only/);
assert.match(tool.$('limits').textContent,/PQ and EXR input/);
await tool.start();await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(calls.filter(c=>c[0]==='/zura/studio/hdr/native-graph').length,1,'HDR mode uses the separate native graph');
assert.equal(calls.filter(c=>c[0]==='/zura/studio/hdr/graph').length,1,'SDR conversion remains available');
tool.close();
console.log('LTX SDR-to-HDR source range, single submission, result preview and downloads pass.');

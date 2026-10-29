import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {HDRSourceTool} from '../web/studio_hdr.js';
const {document,window}=parseHTML('<html><body><div id="host"></div></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const o of this.querySelectorAll('option')){if(o.value===String(value))o.setAttribute('selected','');else o.removeAttribute('selected');}}});
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
tool.job='progress-job';
tool.onExecuting({detail:{prompt_id:'progress-job',node:'model'}});assert.equal(tool.$('status').textContent,'Loading LTX 2.5');assert.equal(tool.$('progress').hasAttribute('value'),false);
tool.onProgress({detail:{prompt_id:'other-job',node:'sample1',value:3,max:8}});assert.equal(tool.$('status').textContent,'Loading LTX 2.5');
tool.onProgress({detail:{prompt_id:'progress-job',node:'sample1',value:3,max:8}});assert.match(tool.$('status').textContent,/pass 1 of 2 · step 3 of 8/);assert.equal(Number(tool.$('progress').value),37.5);
tool.onExecuting({detail:{prompt_id:'progress-job',node:'decode'}});assert.equal(tool.$('status').textContent,'Decoding HDR video');assert.equal(tool.$('progress').hasAttribute('value'),false);tool.job=null;
tool.$('count').value='10';tool.$('start').value='7';tool.$('output').value='hlg_and_exr';
tool.loras.items=[{name:'style.safetensors',strength:.8,confirm_unknown:true}];
await Promise.all([tool.start(),tool.start()]);await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(calls.filter(c=>c[0]==='/prompt').length,1,'Repeated click queues only once');
assert.equal(calls[0][1].start_frame,7);assert.equal(calls[0][1].frame_count,10);
assert.deepEqual(calls[0][1].custom_loras,[{name:'style.safetensors',strength:.8,confirm_unknown:true}],'SDR and HDR preflight receives the selected adapters');
assert.equal(tool.$('result').hidden,false);assert.match(tool.$('hlg').href,/hdr.mp4/);assert.match(tool.$('exr').href,/sequence.zip/);
assert.equal(tool.$('preview').src.includes('preview.mp4'),true);
tool.$('mode').value='native';tool.$('mode').onchange();
assert.match(tool.$('limits').textContent,/HLG\/PQ video or EXR sequence/);
assert.ok(tool.$('colour').querySelector('option[value="pq_rec2020"]'));
await tool.start();await new Promise(resolve=>setTimeout(resolve,5));
assert.equal(calls.filter(c=>c[0]==='/zura/studio/hdr/native-graph').length,1,'HDR mode uses the separate native graph');
assert.equal(calls.filter(c=>c[0]==='/zura/studio/hdr/graph').length,1,'SDR conversion remains available');
tool.sequenceAsset={id:'exr-id',count:12,width:384,height:224};tool.$('source-kind').value='sequence';tool.$('source-kind').onchange();tool.$('sequence-fps').value='25';tool.$('colour').value='acescg';
await tool.start();await new Promise(resolve=>setTimeout(resolve,5));
const exr=calls.filter(c=>c[0]==='/zura/studio/hdr/native-graph').at(-1)[1];assert.equal(exr.source_id,'exr-id');assert.equal(exr.sequence_fps,25);assert.equal(exr.colour_space,'acescg');
assert.deepEqual(exr.custom_loras,[{name:'style.safetensors',strength:.8,confirm_unknown:true}]);
tool.close();
console.log('LTX SDR-to-HDR source range, single submission, result preview and downloads pass.');

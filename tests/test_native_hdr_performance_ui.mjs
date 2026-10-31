import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {MainLTXDelivery,mainLTXTake} from '../web/studio_main_ltx_delivery.js';
import {uploadNativePerformanceOpening,validateNativePerformance,mainNativeLTXTake,nativePerformanceOpening,preferredHDRFile} from '../web/studio_native_hdr_performance.js';

const {document,window}=parseHTML('<html><body><section class="gs-composer"><div id="tools"></div><div id="canvas"></div><button id="primary"></button><p id="action-note"></p></section></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(v){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(v));}});
globalThis.document=document;globalThis.window=window;
globalThis.localStorage={getItem:()=>null,setItem(){}};
const config={engine:'local',workflow_mode:'motion',edit_area:'scene',ltx_output:'hlg_and_exr'};
const calls=[];
const api={apiURL:p=>p,addEventListener(){},removeEventListener(){},async fetchApi(path,options){
  calls.push({path,options});
  const body=path.endsWith('exr-sequence')?{id:'exr-id'}:path.endsWith('/opening')?
    {id:'proxy-id',file:'genj_studio/proxy.png',native_hdr:{asset_id:'exr-id'}}:
    {enabled:true,ready:true,files:[{folder:'vae',filename:'ltx-2.5-video-vae-bf16.safetensors',ready:true}],missingNodes:[]};
  return {ok:true,json:async()=>body};
}};
const file=new File(['actual upload bytes'],'appearance.exr');
await assert.rejects(uploadNativePerformanceOpening(api,file,config,false),/not enabled/);
assert.equal(calls.length,0);
assert.throws(()=>validateNativePerformance({...config,engine:'h3'}),/LTX whole-scene/);
await assert.rejects(uploadNativePerformanceOpening(api,file,{...config,edit_area:'mask'},true),/LTX whole-scene/);
assert.equal(calls.length,0);
const uploaded=await uploadNativePerformanceOpening(api,file,{...config,ltx_output:'sdr'},true);
assert.equal(nativePerformanceOpening({readyAsset:uploaded,lookMode:'build',project:null}),undefined,'An unused finished frame does not affect a new ordinary build');
assert.equal(nativePerformanceOpening({readyAsset:uploaded,lookMode:'ready'}),uploaded.native_hdr);
assert.equal(preferredHDRFile([{filename:'frames.zip',type:'output'},{filename:'master.mp4',type:'output'}]).filename,'master.mp4');
assert.equal(preferredHDRFile([{filename:'frames.zip',type:'output'}]).filename,'frames.zip');
assert.equal(preferredHDRFile([]),null);
assert.equal(calls[0].path,'/zura/studio/hdr/exr-sequence');
assert.equal(calls[0].options.body.get('frames').name,'appearance.exr');
assert.deepEqual(JSON.parse(calls[1].options.body),{asset_id:'exr-id',colour_space:'auto'});
assert.equal(uploaded.native_hdr.asset_id,'exr-id');
calls.length=0;
const result={stage:'restyle',action_id:'native-decode',native_hdr:true,hdr_output:'hlg_and_exr',
  asset:{filename:'viewing-preview.mp4',subfolder:'genj/hdr',type:'output'},
  hdr_files:[{filename:'master.mp4',subfolder:'genj/hdr',type:'output'},
    {filename:'frames.zip',subfolder:'genj/hdr',type:'output'}]};
const s={config,readyAsset:uploaded,source:{width:512,height:512},container:document.body,
  project:{id:'project',phase:'done',opening_input:uploaded,results:[result]},$:id=>document.getElementById(id),
  message(){},render(){},modelDownloads:{context:{files:[{folder:'vae',filename:'ltx-2.5-video-vae-conv-bf16.safetensors'}]},setContext(c){this.context=c;}}};
const ui=new MainLTXDelivery(s,api,document.getElementById('tools'));
assert.equal(mainLTXTake(s.project,result),null,'Native outputs never start SDR-to-HDR conversion');
assert.equal(mainNativeLTXTake(s.project,{...result,hdr_files:[{filename:'bad',type:'input'}]}),null);
await ui.beforeAction('animate');
assert.equal(calls.length,1);assert.match(calls[0].path,/hdr-performance\/readiness/);
ui.sync('video');ui.sync('video');
assert.equal(calls.length,1,'Viewing a completed native result never submits another model pass');
assert.equal(ui.result(s.project).file.filename,'viewing-preview.mp4');
assert.equal(ui.downloads.querySelectorAll('a').length,2);
assert.match(ui.downloads.textContent,/native HDR/);
assert.equal(ui.select.querySelector('option[value="sdr"]').disabled,true);
assert.deepEqual(s.modelDownloads.context.files.map(f=>f.filename),['ltx-2.5-video-vae-bf16.safetensors']);
ui.close();ui.open();ui.sync('video');
assert.equal(calls.length,1,'Reopening retains native output without conversion');
const savedProject=s.project;s.project=null;s.lookMode='build';s.config={engine:'h3',workflow_mode:'motion',ltx_output:'sdr'};
await ui.beforeAction('animate');
assert.equal(calls.length,1,'An inactive EXR cannot force native preflight for a new ordinary build');
s.project=savedProject;s.config=config;s.lookMode='ready';
ui.close();
console.log('PASS native HDR performance: EXR upload ownership, route validation, graph setup, native download handoff and no duplicate HDR pass.');

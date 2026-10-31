import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {MainLTXDelivery,mainLTXTake} from '../web/studio_main_ltx_delivery.js';

const {document,window}=parseHTML('<html><body><section><div id="canvas"></div><div class="gs-composer"><div id="tools"></div><button id="primary"></button><p id="action-note"></p></div></section></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(v){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(v));}});
globalThis.document=document;globalThis.window=window;
const stored=new Map();globalThis.localStorage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,String(v)),removeItem:k=>stored.delete(k)};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const master={filename:'source_sdr.mp4',subfolder:'zura/ltx25/test',type:'output'};
const preview={filename:'hdr_sdr_preview.mp4',subfolder:'genj/hdr',type:'output'};
const hdr={...preview,filename:'hdr_master.mp4'},exr={...preview,filename:'hdr.zip'};
const calls=[];let ready=true,state='rendering';
const api={clientId:'main-hdr',apiURL:p=>p,addEventListener(){},removeEventListener(){},async fetchApi(path,options){
  calls.push({path,body:options?.body&&JSON.parse(options.body)});
  const data=path.includes('/readiness?')?{ready,longPreview:true,files:ready?[]:[{filename:'missing-lora.safetensors',ready:false}]}:
    path.endsWith('/hdr-source-opening')?{id:'project',phase:'opening',approval:'reviewed',config:{finished_frame_position:'first',finished_frame_number:1},starting_asset:{native_hdr:{source_id:'s'}},opening_input:{native_hdr:{source_id:'s'}},results:[]}:
    path==='/zura/studio/hdr/jobs'?{id:'job',state:'rendering',active_prompt_id:'owned',completed:0,total:2}:
    path.endsWith('/cancel')?{id:'job',state:'cancelling'}:
    {id:'job',state,active_prompt_id:'owned',completed:0,total:2,...(state==='complete'?{result:{preview,files:[hdr,exr]}}:{})};
  return {ok:true,status:200,json:async()=>data};
}};
let ui;
const s={container:document.querySelector('section'),config:{engine:'local',workflow_mode:'motion',ltx_output:'sdr',resolution:512},
  source:{width:1920,height:1080},project:{id:'project',phase:'opening',results:[]},$:id=>document.getElementById(id),
  message(message){this.lastMessage=message;},render(){ui?.sync('video');}};
ui=new MainLTXDelivery(s,api,document.getElementById('tools'));
ui.sync('image');assert.equal(ui.control.hidden,true);ui.sync('video');assert.equal(ui.control.hidden,false);
await ui.beforeAction('animate');assert.equal(calls.length,0,'SDR does not run an HDR preflight');
s.config.ltx_output='hlg_and_exr';await ui.beforeAction('design');assert.equal(calls.length,0,'Image generation does not run HDR setup');
s.config.engine='h3';await ui.beforeAction('animate');ui.sync('video');assert.equal(calls.length,0);assert.equal(ui.control.hidden,true,'H3 has no HDR output selector');
s.config.engine='local';ready=false;await assert.rejects(ui.beforeAction('animate'),/missing-lora/);
s.source.native_hdr_video={asset_id:'a'.repeat(32)};
await assert.rejects(ui.beforeAction('animate'),/finished HDR EXR or use the HDR source frame/,'HDR video must not silently use the SDR appearance route');
delete s.source.native_hdr_video;
assert.equal(calls.filter(c=>c.path==='/zura/studio/hdr/jobs').length,0,'Missing HDR setup blocks generation before any delivery submission');
s.modelDownloads={context:{route:'local',files:[{folder:'diffusion_models',filename:'base.safetensors',ready:true}],missingNodes:['LTXBaseNode']},setContext(info){this.context=info;}};
ui.sync('video');ui.sync('video');
assert.equal(s.modelDownloads.context.route,'ltx_performance_hdr');
assert.deepEqual(s.modelDownloads.context.files.map(file=>file.filename),['base.safetensors','missing-lora.safetensors'],'HDR setup augments the generation dependencies without duplicating files');
assert.deepEqual(s.modelDownloads.context.missingNodes,['LTXBaseNode']);
ready=true;await ui.beforeAction('animate');assert.match(calls.at(-1).path,/width=512&height=288/);
const item={stage:'restyle',asset:master,hdr_output:'hlg_and_exr',action_id:'decode',seed:789,output_raster:{width:512,height:288,frames:9,fps:24}};
assert.equal(mainLTXTake(s.project,{...item,stage:'h3'}),null);
assert.equal(mainLTXTake(s.project,{...item,asset:{...master,type:'input'}}),null);
s.project.results=[item];s.project.phase='done';ui.sync('video');ui.sync('video');await settle();
assert.equal(calls.filter(c=>c.path==='/zura/studio/hdr/jobs').length,1);
const request=calls.find(c=>c.path==='/zura/studio/hdr/jobs').body;
assert.equal(request.frame_count,9,'Delivery uses the verified rendered frame count');assert.equal(request.seed,789);
assert.deepEqual(request.output_ref,master);assert.equal(ui.progress.hidden,false);assert.equal(s.$('primary').disabled,true);
ui.sample({prompt_id:'other',node:'hdr_sample',value:3,max:8});assert.doesNotMatch(ui.detail.textContent,/step 3/);
ui.sample({prompt_id:'owned',node:'hdr_sample',value:3,max:8});assert.match(ui.detail.textContent,/Section 1 of 2.*step 3 of 8/);
ui.update({state:'rendering',active_prompt_id:'owned',completed:0,total:2});assert.match(ui.detail.textContent,/step 3 of 8/,'Status polling retains current sampler progress');
ui.update({state:'cancel-error',active_prompt_id:'owned',error:'Cancellation could not be confirmed'});
assert.match(ui.detail.textContent,/Cancellation could not be confirmed/,'An uncertain cancellation stays visible instead of reverting to Preparing');
state='complete';await ui.delivery.client.poll();
assert.equal(ui.result(s.project).file.filename,preview.filename);assert.equal(s.project.results[0].asset.filename,master.filename,'The SDR result is untouched');
assert.equal(ui.downloads.querySelectorAll('a').length,2);assert.equal(ui.progress.hidden,true);
assert.match(ui.downloads.textContent,/on-screen preview is SDR/);
ui.close();ui.open();ui.sync('video');await settle();
assert.equal(calls.filter(c=>c.path==='/zura/studio/hdr/jobs').length,1,'Reopening does not regenerate HDR');
ui.close();s.project=null;s.source.native_hdr_video={asset_id:'a'.repeat(32)};s.syncForm=()=>{};s.resetEpoch=4;s.modelStatus={native_hdr_performance:true};s.config.edit_area='scene';
ui.sync('image');assert.equal(ui.sourceFrame.hidden,false,'Source-frame choice is available before the project exists');
s.config.finished_frame_position='last';s.config.finished_frame_number=17;
const beforeChoice=calls.length;await ui.useSourceFrame();assert.equal(s.config.finished_frame_position,'first');assert.equal(s.config.finished_frame_number,1);assert.equal(s.hdrSourceLook,true);assert.equal(calls.length,beforeChoice,'Choosing the source frame does not generate or skip the review');
s.project={id:'project',phase:'approved',approval:'reviewed',results:[]};
ui.sync('image');assert.equal(ui.sourceFrame.hidden,false,'An approved HDR source can provide its own opening frame');
s.config.finished_frame_position='frame';s.config.finished_frame_number=17;await ui.useSourceFrame();assert.equal(s.config.finished_frame_position,'first');assert.equal(s.config.finished_frame_number,1);assert.equal(s.project.opening_input.native_hdr.source_id,'s');assert.equal(s.lookMode,'ready');
assert.ok(calls.some(call=>call.path.endsWith('/hdr-source-opening')));assert.match(s.lastMessage,/Review the HDR source frame/);
ui.close();
console.log('PASS main LTX HDR delivery: scoped selector, early setup, actual raster, one conversion, owned progress, retained SDR and result downloads.');

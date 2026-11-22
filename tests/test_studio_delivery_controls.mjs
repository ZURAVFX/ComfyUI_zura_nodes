import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioDeliveryControls,studioInputDescription} from '../web/studio_delivery_controls.js';
import {StudioOutputSettings} from '../web/studio_output_settings.js';
import {memoryStorage} from '../web/studio_storage.js';
import {hdrDeliveryProgress} from '../web/studio_ltx_delivery.js';

const {document,window}=parseHTML('<html><head></head><body></body></html>');
Object.assign(globalThis,{document,window});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
assert.equal(studioInputDescription({precision:{sourceBitDepth:32},colour:{encoding:'unknown',sceneLinear:false,ocioWorkingSpace:'Output - sRGB'}}).input,'sdr','FLOAT is precision, not a claim that footage is HDR');
assert.equal(studioInputDescription({native_hdr:{file:'retained.exr'},colour:{encoding:'srgb_display',sceneLinear:false}}).input,'sdr','Explicit SDR colour is retained even when its original is stored as FLOAT EXR');
assert.deepEqual(studioInputDescription({resolved_colour:'hlg_rec2020'}),{input:'hdr',space:'hlg_rec2020',detected:true});
const explicitHalf=Object.assign(Object.create(StudioOutputSettings.prototype),{precision:{value:()=> 'half'},delivery:{aeTransfer:'float32'}});
assert.equal(explicitHalf.exrStorage('acescg_exr'),'float32','AE32 overrides a saved HALF preference for this transfer only');
explicitHalf.delivery.aeTransfer=null;
assert.equal(explicitHalf.exrStorage('acescg_exr'),'half','Leaving AE restores the saved preference');

const preview={filename:'hdr-preview.mp4',subfolder:'hdr',type:'output'},zip={filename:'hdr.zip',subfolder:'hdr',type:'output'},video={filename:'hdr.mp4',subfolder:'hdr',type:'output'};
function fixture(storage=memoryStorage()){
  const root=document.createElement('main');root.innerHTML='<header class="gs-top"><div class="gs-top-actions"></div></header>';document.body.append(root);
  const calls=[],c={root,storage,mode:'image',references:[{file:'input.png',width:512,height:512}],items:[],selectedImage:0,
    studio:{config:{engine:'h3',workflow_mode:'swap'}},show(mode){this.mode=mode;},config(){return {width:512,height:512,model:'klein9b'};},render(){},close(){},message(value){this.lastMessage=value;},generate(){this.generated=(this.generated||0)+1;},
    async poll(){if(this.job){this.items.unshift({file:this.pendingFile});this.job=null;}}};
  let state='rendering',alphaDelivery=false,imageHasAlpha=false;
  const api={clientId:'test',apiURL:path=>path,async fetchApi(path,options){const body=options?.body?JSON.parse(options.body):undefined;calls.push({path,body});
    if(path==='/zura/studio/hdr/jobs')alphaDelivery=!!body?.alpha_ref||imageHasAlpha;
    const result=path.includes('/readiness?')?{ready:true,longPreview:true,files:[]}:
      path.endsWith('/source-info')?{frames:body.source_kind==='output_image'?1:9,width:512,height:512,fps:25,...(imageHasAlpha?{hasAlpha:true}:{})}:
      path==='/zura/studio/hdr/jobs'?{id:'conversion',state:'rendering'}:
      path.endsWith('/cancel')?{id:'conversion',state:'cancelling'}:
      path.endsWith('/jobs/conversion')?{id:'conversion',state,...(state==='complete'?{result:{preview,files:[zip,video],exr_storage:'float32',...(alphaDelivery?{alphaAssociation:'straight',layout:'RGBA'}:{})}}:{})}:{};
    return {ok:true,json:async()=>result};}};
  c.studio.creative=c;
  // Physical export verification is exercised by test_studio_image_delivery;
  // these controller-transition fixtures supply its successful interface.
  const settings={exrStorage:()=> 'float32',verifyHDRStill:async()=>({filename:'verified.exr',subfolder:'ZURA STUDIO/image-exports/fixture',type:'output'})},controls=new StudioDeliveryControls(root,api,c,settings);c.outputSettings={delivery:controls};
  return {c,root,calls,api,controls,transparent(){imageHasAlpha=true;},complete(){state='complete';},close(){controls.close();root.remove();}};
}
{
  const f=fixture();await Promise.resolve();
  f.controls.setAETransfer('float32');
  assert.equal(f.controls.output,'hdr','32-bit AE transfer requires HDR output');
  assert.equal(f.controls.hdrFormat,'acescg_exr','32-bit AE transfer requires EXR, not an SDR or HLG-only movie');
  assert.equal(f.controls.$('output').disabled,true);
  const raw={kind:'image',master:{filename:'same.png',subfolder:'images',type:'output'}};
  f.controls.records[f.controls.resultKey('image',raw)]={state:'complete',take:{hdrFiles:[zip],config:{exr_storage:'half'}}};
  assert.equal(f.controls.outputFor('image',raw),null,'A saved HALF archive cannot satisfy AE32 FLOAT delivery');
  f.controls.setHDRFormat('hlg_video');assert.equal(f.controls.hdrFormat,'acescg_exr','HDR master cannot be changed to HLG-only');
  f.controls.setAETransfer('sdr8');assert.equal(f.controls.output,'sdr','8-bit transfer from a 32-bpc project remains SDR');
  f.controls.setAETransfer('prores12');assert.equal(f.controls.output,'sdr','12-bit transfer uses the SDR model path');
  f.controls.endAETransfer();assert.equal(f.controls.output,'sdr');assert.equal(f.controls.$('output').disabled,false);
  f.close();
}
{
 const f=fixture();await Promise.resolve();const controls=f.controls;
 controls.delivery.take={studioMode:'image',resultKey:'progress-test'};controls.delivery.busy=true;
 for(const [state,phase] of [['preparing',0],['rendering',1],['staging',1],['exporting',2],['reconnecting',0],['cancelling',0]]){controls.delivery.update({id:'progress',state,completed:1,total:3});assert.equal(controls.progressHost.hidden,false);assert.equal(controls.progressHost.querySelectorAll('li')[phase].getAttribute('aria-current'),'step');}
 controls.delivery.update({id:'progress',state:'rendering',completed:1,total:3});assert.match(controls.progressHost.textContent,/1 of 3 sections converted/);assert.equal(controls.progressHost.querySelector('progress').value,1);assert.equal(controls.progressHost.querySelector('progress').max,3);
 f.c.show('video');assert.equal(controls.progressHost.querySelector('[data-delivery-progress-cancel]').hidden,false,'Active HDR cancellation remains available after a mode change');assert.equal(controls.progressHost.hidden,false);
 controls.delivery.update({id:'progress',state:'exporting',completed:3,total:3});assert.equal(controls.progressHost.querySelector('progress').hasAttribute('value'),false,'Export has no invented percentage');assert.match(controls.progressHost.textContent,/Encoding HDR video and writing EXR masters/);
 controls.delivery.update({id:'progress',state:'failed',error:'Encoder stopped'});assert.match(controls.progressHost.textContent,/Encoder stopped/);assert.equal(controls.progressHost.querySelector('progress').hidden,true);assert.equal(controls.$('cancel').hidden,true);
 controls.delivery.update({id:'progress',state:'cancelled'});
 assert.equal(controls.progressHost.hidden,true);assert.equal(controls.progressHost.hasAttribute('open'),false);
 assert.equal(controls.progressToggle.hidden,true);assert.equal(controls.progressTimer,null);
 assert.match(controls.cancellationNotice.textContent,/original master is retained/);assert.equal(controls.$('status').textContent,'');
 controls.delivery.update({id:'second',state:'queued'});
 assert.equal(controls.progressHost.hasAttribute('open'),true,'A later conversion opens its own dialog');
 controls.progressHost.querySelector('[data-delivery-dismiss]').click();
 assert.equal(controls.progressHost.hidden,true);assert.equal(controls.progressToggle.hidden,false);
 controls.progressToggle.click();assert.equal(controls.progressHost.hidden,false);
 controls.delivery.update({id:'progress',state:'complete',result:{files:[]}});assert.equal(controls.progressHost.dataset.state,'failed','Incomplete masters never show Ready');
 assert.equal(hdrDeliveryProgress({state:'rendering'}).value,null);assert.equal(hdrDeliveryProgress({state:'rendering',completed:2,total:2}).complete,false,'Completed sections are not completed delivery');f.close();
}
{
 const f=fixture();await Promise.resolve();const controls=f.controls;
 const original={kind:'video',master:{filename:'deliver.mov',type:'output'}};
 let release;
 controls.delivery.client.request=()=>new Promise(resolve=>{release=resolve;});
 const converting=controls.convert('paintout',f.c,original,{});
 assert.equal(controls.progressHost.hidden,false);
 controls.progressHost.querySelector('[data-delivery-progress-cancel]').click();
 assert.equal(controls.progressHost.querySelector('[data-delivery-progress-cancel]').disabled,true);
 release({frames:17,width:512,height:320,fps:24});
 await converting;
 assert.equal(controls.progressHost.hidden,true);
 assert.equal(controls.progressTimer,null);
 assert.equal(controls.delivery.busy,false);
 assert.equal(f.calls.filter(call=>call.path==='/zura/studio/hdr/jobs').length,0);
 assert.match(controls.cancellationNotice.textContent,/original master is retained/);
 f.close();
}
{
  const f=fixture();await Promise.resolve();
  const page=document.createElement('section');page.innerHTML='<div class="zs-switch-tools"></div>';f.c.root.append(page);
  const master={filename:'switch.mov',subfolder:'switch_x',type:'output'};
  const workspace={page,config:{},async poll(){this.result={master,preview};this.job=null;}};
  f.c.switchX=workspace;f.c.show('switch_x');
  assert.equal(f.controls.outputChoice.parentElement,page.firstElementChild);
  assert.equal(f.controls.outputChoice.hidden,false);
  f.controls.output='hdr';f.controls.sync();
  workspace.job={id:'switch-shot',config:f.controls.configure(workspace,workspace.config,'switch_x')};
  await workspace.poll();
  for(let i=0;i<20&&!f.controls.delivery.client.id;i++)await new Promise(resolve=>setTimeout(resolve,0));
  const jobs=f.calls.filter(call=>call.path==='/zura/studio/hdr/jobs');
  assert.equal(jobs.length,1);assert.deepEqual(jobs[0].body.output_ref,master);
  f.complete();await f.controls.delivery.client.poll();
  assert.equal(f.controls.outputFor('switch_x',f.controls.raw('switch_x')).master.filename,'hdr.zip');
  f.controls.output='sdr';assert.deepEqual(f.controls.outputFor('switch_x',f.controls.raw('switch_x')).master,master);
  f.close();
}
{
  const f=fixture();await Promise.resolve();f.controls.output='hdr';f.controls.save();
  const original={filename:'generated.png',type:'output',subfolder:'images'};
  f.c.job={id:'image-job',config:f.c.config()};f.c.pendingFile=original;
  await f.c.poll();for(let i=0;i<20&&!f.controls.delivery.client.id;i++)await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(f.calls.filter(call=>call.path==='/zura/studio/hdr/jobs').length,1,'A finished non-LTX generation starts exactly one real HDR post-pass');
  const body=f.calls.find(call=>call.path==='/zura/studio/hdr/jobs').body;
  assert.equal(body.source_kind,'output_image');assert.equal(body.frame_count,1);assert.equal(body.sequence_fps,25);assert.equal(body.exr_storage,'float32');
  assert.ok(f.calls.some(call=>call.path.includes('/readiness?')&&new URLSearchParams(call.path.split('?')[1]).get('single_frame')==='1'),'Still preflight reports its one-frame physical budget');
  assert.deepEqual(f.c.items[0].file,original,'The original image is retained');
  const raw={kind:'image',master:original};assert.equal(f.controls.outputFor('image',raw),null,'An unfinished conversion is never called HDR');
  assert.equal(f.controls.isBusyFor('image'),true);f.c.generate();assert.equal(f.c.generated,undefined,'Generation cannot overlap its own HDR delivery');
  f.complete();await f.controls.delivery.client.poll();
  const selected=f.controls.outputFor('image',raw);assert.equal(selected.master.filename,'hdr.zip');assert.equal(selected.colour.encoding,'acescg');assert.deepEqual(selected.preview,original);
  assert.equal(f.controls.isBusyFor('image'),false);f.close();
}
{
  const f=fixture();await Promise.resolve();
  const videoWorkspace={owner:f.c,items:[],selectedResult:null,config(){return {engine:'wan',frames:17,width:512,height:512};},render(){},async poll(){if(this.job){this.selectedResult={filename:'new-video.mp4',type:'output'};this.items.unshift({file:this.selectedResult,config:this.job.config});this.job=null;}}};
  f.c.referencesVideo=videoWorkspace;f.c.show('references');f.controls.output='hdr';f.controls.sync();videoWorkspace.job={id:'video-job',config:videoWorkspace.config()};
  await videoWorkspace.poll();for(let i=0;i<20&&!f.controls.delivery.client.id;i++)await new Promise(resolve=>setTimeout(resolve,0));
  const body=f.calls.find(call=>call.path==='/zura/studio/hdr/jobs')?.body;
  assert.equal(body.source_kind,'output');assert.equal(body.frame_count,9,'HDR delivery uses the decoded master count, not latent model padding');
  f.controls.delivery.update({state:'cancelled'});f.close();
}
{
  const f=fixture();await Promise.resolve();
  f.controls.changeInput('hdr');assert.equal(f.controls.input(f.c).space,'');assert.doesNotThrow(()=>f.c.render());
  f.c.generate();assert.equal(f.c.generated,undefined);assert.match(f.c.lastMessage,/actual HDR source/);
  f.controls.changeInput('hdr','acescg');f.c.generate();assert.equal(f.c.generated,1);
  f.c.studio.aeBridge={source:{manifest:{relativePath:'ae/source'},precision:{sourceBitDepth:32},colour:{encoding:'unknown',sceneLinear:true,ocioWorkingSpace:'ACEScg'},processingInput:{precision:{sourceBitDepth:8}}}};
  const configured=f.controls.configure(f.c,{sourceColour:'srgb_display'},'image');
  assert.equal(configured.sourceColour,'srgb_display','The SDR inference copy must not be reinterpreted as original HDR beauty');
  assert.equal(configured.studioDelivery.input,'hdr');assert.equal(configured.studioDelivery.processingColourSpace,'srgb_display');
  f.controls.changeInput('sdr');assert.match(f.controls.$('status').textContent,/After Effects/);f.close();
}
{
  const store=memoryStorage(),f=fixture(store);await Promise.resolve();f.controls.output='hdr';f.controls.save();f.close();
  const next=fixture(store);await Promise.resolve();assert.equal(next.controls.$('output').value,'hdr','Output choice survives reopening within its own workspace store');
  await next.controls.convert('alpha',next.c,{kind:'alpha_extract',master:{filename:'manifest.json',type:'output'}},{});
  assert.equal(next.calls.filter(call=>call.path==='/zura/studio/hdr/jobs').length,0,'Transparent extraction never enters an RGB-only conversion');
  assert.match(next.controls.$('status').textContent,/native HDR|FLOAT alpha/);next.close();
}
{
  const f=fixture();await Promise.resolve();f.controls.output='hdr';f.controls.hdrFormat='hlg_video';f.controls.settings.exrStorage=()=> 'half';
  const raw={kind:'video',master:{filename:'alpha.mov',type:'output'},alpha_ref:{filename:'alpha_manifest.json',subfolder:'genj/alpha/take',type:'output'}};
  await f.controls.convert('alpha',f.c,raw,{});
  const body=f.calls.find(call=>call.path==='/zura/studio/hdr/jobs').body;
  assert.deepEqual(body.alpha_ref,raw.alpha_ref);assert.equal(body.exr_storage,'float32');assert.equal(body.output,'hlg_and_exr','HDR alpha always has a genuine transparent EXR master');
  f.complete();await f.controls.delivery.client.poll();const result=f.controls.outputFor('alpha',raw);assert.equal(result.alpha,'straight');assert.equal(result.master.filename,'hdr.zip');f.close();
}
{
  const f=fixture();await Promise.resolve();f.controls.output='hdr';f.transparent();
  const raw={kind:'image',master:{filename:'transparent.png',type:'output'}};f.c.items=[{file:raw.master}];await f.controls.convert('image',f.c,raw,{});
  const body=f.calls.find(call=>call.path==='/zura/studio/hdr/jobs').body;assert.equal(body.source_kind,'output_image');assert.equal(body.exr_storage,'float32');
  f.complete();await f.controls.delivery.client.poll();assert.equal(f.controls.outputFor('image',raw).alpha,'straight');f.close();
}
{
  const f=fixture();await Promise.resolve();f.controls.output='hdr';
  let release;f.controls.delivery.preflight=()=>new Promise(resolve=>release=resolve);
  const raw={kind:'image',master:{filename:'cancel.png',type:'output'}};f.c.items=[{file:raw.master}];const converting=f.controls.convert('image',f.c,raw,{});
  while(!release)await new Promise(resolve=>setTimeout(resolve,0));f.controls.cancel();release();await converting;
  assert.equal(f.calls.filter(call=>call.path==='/zura/studio/hdr/jobs').length,0,'Cancelling preflight prevents any conversion submission');f.close();
}
{
  const f=fixture();await Promise.resolve();f.controls.output='hdr';f.c.mode='alpha';
  f.c.alpha={result:{native_hdr:{filename:'native_alpha.zip',subfolder:'genj/hdr',type:'output'},alpha:{filename:'transparent.mov',type:'output'},preview:{filename:'checkerboard.mp4',type:'output'}}};
  f.controls.sync();assert.equal(f.controls.$('files').textContent,'EXR','A verified original-HDR Alpha master is downloadable without another conversion');
  assert.equal(f.calls.filter(call=>call.path==='/zura/studio/hdr/jobs').length,0);
  const raw=f.controls.raw('alpha');f.controls.output='sdr';assert.equal(f.controls.outputFor('alpha',raw).master.filename,'transparent.mov','SDR output uses transparent media rather than the checkerboard UI preview');f.close();
}
{
  const f=fixture();await Promise.resolve();const controls=f.controls,input=controls.$('input'),output=controls.$('output');
  assert.equal(controls.root.querySelector('.zc-source-options-panel'),null);assert.equal(controls.root.querySelector('.zc-source-options'),null);assert.equal(output.closest('.zc-delivery-controls'),controls.element);
  assert.equal(controls.element.querySelector('[data-delivery-input]'),null,'Top bar exposes only output choice');
  controls.sync();assert.equal(controls.$('input'),input,'Live synchronisation retains relocated input identity');
  f.c.studio.aeSession={id:'pending'};controls.sync();assert.equal(input.disabled,true,'AE input is locked before source preparation finishes');assert.equal(controls.$('space').disabled,true);f.close();
}
console.log('Shared delivery: persistent SDR/HDR controls, real non-LTX post-pass, retained SDR, N1 cadence, truthful masters, explicit source space, AE inference view and cancellation passed');

{
 const f=fixture();const page=document.createElement('section');page.innerHTML='<div class="zh-footer"></div><select data-source-kind><option value="upload">Source</option></select><label><select data-mode><option value="sdr">SDR</option></select></label><label><select data-output><option value="hlg_and_exr">HDR</option></select></label>';f.root.append(page);
 let started=0;const tool={root:page,longUpdate(){},start(){started++;},getSource:()=>null,$:key=>page.querySelector('[data-'+key+']')};f.c.studio.hdrTool=tool;
 f.c.show('hdr');assert.equal(f.controls.output,'hdr','Entering Convert to HDR selects HDR without a separate toggle');
 assert.equal(f.controls.$('output').disabled,true);assert.equal(f.controls.outputChoice.parentElement,page.querySelector('.zh-footer'),'Output belongs to generation controls');
 f.controls.output='sdr';tool.start();assert.equal(started,1,'Convert starts even if a stale global preference was SDR');assert.equal(f.controls.output,'hdr');f.close();
}

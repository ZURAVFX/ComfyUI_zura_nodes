import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioDeliveryControls,studioInputDescription} from '../web/studio_delivery_controls.js';
import {memoryStorage} from '../web/studio_storage.js';

const {document,window}=parseHTML('<html><head></head><body></body></html>');
Object.assign(globalThis,{document,window});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
assert.equal(studioInputDescription({precision:{sourceBitDepth:32},colour:{encoding:'unknown',sceneLinear:false,ocioWorkingSpace:'Output - sRGB'}}).input,'sdr','FLOAT is precision, not a claim that footage is HDR');
assert.deepEqual(studioInputDescription({resolved_colour:'hlg_rec2020'}),{input:'hdr',space:'hlg_rec2020',detected:true});

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
  const settings={exrStorage:()=> 'float32'},controls=new StudioDeliveryControls(root,api,c,settings);c.outputSettings={delivery:controls};
  return {c,root,calls,api,controls,transparent(){imageHasAlpha=true;},complete(){state='complete';},close(){controls.close();root.remove();}};
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
  const raw={kind:'image',master:{filename:'transparent.png',type:'output'}};await f.controls.convert('image',f.c,raw,{});
  const body=f.calls.find(call=>call.path==='/zura/studio/hdr/jobs').body;assert.equal(body.source_kind,'output_image');assert.equal(body.exr_storage,'float32');
  f.complete();await f.controls.delivery.client.poll();assert.equal(f.controls.outputFor('image',raw).alpha,'straight');f.close();
}
{
  const f=fixture();await Promise.resolve();f.controls.output='hdr';
  let release;f.controls.delivery.preflight=()=>new Promise(resolve=>release=resolve);
  const converting=f.controls.convert('image',f.c,{kind:'image',master:{filename:'cancel.png',type:'output'}},{});
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
console.log('Shared delivery: persistent SDR/HDR controls, real non-LTX post-pass, retained SDR, N1 cadence, truthful masters, explicit source space, AE inference view and cancellation passed');

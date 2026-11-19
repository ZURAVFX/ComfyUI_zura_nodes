import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioOutputSettings} from '../web/studio_output_settings.js';
import {memoryStorage} from '../web/studio_storage.js';
import {HDRIBuilder} from '../web/studio_hdri.js';

// Real delivery/settings controllers with an isolated API and DOM. The API
// fixture represents already verified server assets; it never runs a model,
// touches the workstation's engine, or claims pixel/codec qualification.
const file=(filename,subfolder='genj/studio_images')=>({filename,subfolder,type:'output'});
const strict=value=>({filename:value.filename,subfolder:value.subfolder||'',type:value.type});
const master=file('master.exr','ZURA STUDIO/image-layers/'+'a'.repeat(32));
const preview=file('preview.png',master.subfolder);
const hdrMaster=file('image_HDR.exr','genj/hdr/'+'b'.repeat(32));
const hdrPreview=file('image_HDR_preview.png',hdrMaster.subfolder);

function item(model='flux3'){
  return {model,prompt:'Keep the current source and edit the object',file:{...preview},preview:{...preview},master:{...master,role:'composite_master',sha256:'c'.repeat(64)},
    width:512,height:512,colour:{encoding:'srgb_display',sceneLinear:false},hasAlpha:false,
    image_layers:{schemaVersion:1,id:'stack',source:{filename:'source.png',subfolder:'fixtures',type:'input'},width:512,height:512,layers:[{id:'edit',file:file('edit.png'),opacity:1}]}};
}

function dom(){
  const {document,window}=parseHTML('<!doctype html><html><head></head><body></body></html>');
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
  const formPrototype=Object.getPrototypeOf(document.createElement('form'));
  if(!Object.getOwnPropertyDescriptor(formPrototype,'elements'))Object.defineProperty(formPrototype,'elements',{configurable:true,get(){
    if(this.localName!=='form')return undefined;
    const fields=[...this.querySelectorAll('input,select,textarea,button')],result={length:fields.length};
    for(const [index,field]of fields.entries()){result[index]=field;for(const key of [field.getAttribute('name'),field.id])if(key&&!Object.hasOwn(result,key))result[key]=field;}
    result.item=index=>fields[index]||null;result.namedItem=name=>result[name]||null;return result;
  }});
  const dialogPrototype=Object.getPrototypeOf(document.createElement('dialog'));
  if(!dialogPrototype.close)dialogPrototype.close=function(){this.removeAttribute('open');};
  if(!dialogPrototype.showModal)dialogPrototype.showModal=function(){this.setAttribute('open','');};
  Object.assign(globalThis,{document,window});
  return {document,window};
}

async function settle(turns=8){for(let i=0;i<turns;i++)await new Promise(resolve=>setTimeout(resolve,0));}

async function fixture({storage=memoryStorage(),selected=item()}={}){
  const {document,window}=dom(),root=document.createElement('main');root.id='genj-studio';
  root.innerHTML='<header class="gs-top"><div class="gs-top-actions"></div></header><section class="zc-image-page"><form class="zc-image-composer"><div class="zc-composer-bottom"><button type="submit" id="zc-generate" class="gs-primary">Generate image</button></div></form><div id="zc-gallery"></div><div id="zc-message"></div></section><section class="gs-workspace"><form class="gs-composer"><div class="zc-prompt-tools"></div></form></section>';
  document.body.append(root);
  const calls=[],downloads=[],owner={root,storage,mode:'image',imageOperation:'edit',imageIntent:'standard',references:[{filename:'source.png',subfolder:'fixtures',type:'input',file:'fixtures/source.png',width:512,height:512}],items:[selected],selectedImage:0,
    studio:{config:{engine:'h3',workflow_mode:'motion'}},imageLayers:{busy:false},show(mode){this.mode=mode;},config(){return {width:512,height:512,model:this.items[this.selectedImage]?.model||'flux3',operation:this.imageOperation};},
    $(key){return root.querySelector('#zc-'+key);},render(){},renderGallery(){},save(){},close(){},message(value){this.lastMessage=value;},generate(){this.generated=(this.generated||0)+1;},async poll(){}};
  owner.studio.creative=owner;
  let state='rendering',exportResponse=null,exportGate=null,readinessGate=null,hdrCounter=0;
  const api={clientId:'isolated-image-delivery',apiURL:path=>path,async fetchApi(path,options){
    const body=options?.body?JSON.parse(options.body):undefined;calls.push({path,body});
    let result={};
    if(path==='/zura/studio/output-settings')result={folder:'C:/fixture/Deliveries'};
    else if(path==='/zura/studio/image-export'){
      if(exportGate)return exportGate(path,body);
      const format=body.format,suffix=({png8:'.png',png16:'.png',tiff16:'.tiff',exr_float:'.exr',hdr_exr:'.exr'})[format]||'.invalid';
      const hdr=format==='hdr_exr';
      result=exportResponse||{schemaVersion:1,file:file('image'+suffix,'ZURA STUDIO/image-exports/'+'d'.repeat(32)),format,width:512,height:512,
        colour:{encoding:hdr?'acescg':'srgb_display',sceneLinear:hdr},dynamicRange:hdr?'HDR':'SDR',hasAlpha:false,
        sampleType:format==='png8'?'uint8':format==='exr_float'||hdr?'float32':'uint16',storageBitDepth:format==='png8'?8:format==='exr_float'||hdr?32:16,bitDepth:format==='png8'?8:format==='exr_float'||hdr?32:16,sourceBitDepth:32,sha256:'e'.repeat(64),...(hdr?{verifiedHDR:true,hdrJobId:body.jobId,jobId:body.jobId,sourceSha256:'f'.repeat(64),exrStorage:'float32'}:{})};
    }else if(path==='/zura/studio/save-output')result={saved:['C:/fixture/Deliveries/Images/'+body.assets[0].filename]};
    else if(path.startsWith('/zura/studio/hdr/readiness?')){if(readinessGate)return readinessGate(path,body);result={ready:true,longPreview:true,files:[]};}
    else if(path==='/zura/studio/hdr/source-info')result={frames:1,width:512,height:512,fps:24,hasAlpha:false};
    else if(path==='/zura/studio/hdr/jobs')result={id:'converted-'+(++hdrCounter),state:'rendering'};
    else if(/\/hdr\/jobs\/converted-\d+\/cancel$/.test(path))result={id:path.split('/').at(-2),state:'cancelling'};
    else if(/\/hdr\/jobs\/converted-\d+$/.test(path))result={id:path.split('/').at(-1),state,...(state==='complete'?{result:{preview:hdrPreview,files:[hdrMaster],colour:{encoding:'acescg',sceneLinear:true},exr_storage:'float32'}}:{})};
    return {ok:true,json:async()=>result};
  }};
  owner.api=api;
  const createElement=document.createElement.bind(document);
  document.createElement=(tag,...args)=>{const node=createElement(tag,...args);if(String(tag).toLowerCase()==='a')node.click=()=>downloads.push({href:node.getAttribute('href'),filename:node.getAttribute('download')});return node;};
  const settings=new StudioOutputSettings(root,api,owner);owner.outputSettings=settings;
  await settle();
  return {root,document,window,owner,settings,controls:settings.delivery,calls,downloads,
    setState(value){state=value;},setExportResponse(value){exportResponse=value;},deferExport(handler){exportGate=handler;},deferPreflight(handler){readinessGate=handler;},
    jobs:()=>calls.filter(call=>call.path==='/zura/studio/hdr/jobs'),exports:()=>calls.filter(call=>call.path==='/zura/studio/image-export'),
    close(){settings.delivery.close();root.remove();}};
}

{
  const f=await fixture();
  try{
    assert.equal(f.settings.imageFormat,'png8','Normal SDR downloads default to ordinary PNG storage, not the FLOAT master');
    const before=structuredClone(f.owner.items[0]),resolved=await f.settings.resolveImageItem(f.owner.items[0]);
    assert.deepEqual(f.exports().at(-1).body,{asset:strict(master),format:'png8'});
    assert.equal(resolved.filename,'image.png');assert.equal(resolved.type,'output');
    assert.deepEqual(f.owner.items[0],before,'An export never replaces the SDR master, preview, layer receipt or source lineage');
    const button=f.document.createElement('button');button.textContent='Save image';
    await f.settings.saveImageItem(f.owner.items[0],button);
    const saved=f.calls.findLast(call=>call.path==='/zura/studio/save-output');
    assert.equal(saved.body.assets[0].filename,'image.png','Save must copy the requested SDR export rather than internal master.exr');
    assert.equal(button.disabled,false);
    await f.settings.downloadImageItem(f.owner.items[0],button);
    assert.equal(f.downloads.at(-1).filename,'image.png');assert.match(f.downloads.at(-1).href,/filename=image\.png/);
    for(const [format,suffix]of [['png16','.png'],['tiff16','.tiff'],['exr_float','.exr']]){
      f.settings.imageFormat=format;const result=await f.settings.resolveImageItem(f.owner.items[0]);
      assert.equal(f.exports().at(-1).body.format,format);assert.ok(result.filename.endsWith(suffix));
    }
    assert.equal(f.jobs().length,0,'SDR storage choice alone never starts HDR reconstruction');
  }finally{f.close();}
}

{
  const windows={model:'ph3edit',file:file('result.png','ZURA STUDIO\\images'),master:file('result.png','ZURA STUDIO\\images'),width:512,height:512,colour:{encoding:'srgb_display',sceneLinear:false}};
  const f=await fixture({selected:windows});
  try{
    const before=structuredClone(windows);
    await f.settings.resolveImageItem(windows);
    assert.equal(f.exports().at(-1).body.asset.subfolder,'ZURA STUDIO/images','A real Windows SaveImage subfolder is normalised only in the export request');
    f.controls.output='hdr';f.settings.imageCommitted(windows);await settle();
    const source=f.calls.findLast(call=>call.path==='/zura/studio/hdr/source-info');
    assert.equal(source.body.output_ref.subfolder,'ZURA STUDIO/images','HDR source inspection uses the same canonical relative folder');
    assert.equal(f.jobs().length,1);assert.deepEqual(windows,before,'Request normalisation never rewrites the producer-owned item metadata');
  }finally{f.close();}
}

{
  const f=await fixture();
  try{
    const selected=f.owner.items[0],before=structuredClone(selected);
    f.controls.output='hdr';f.controls.hdrFormat='acescg_exr';f.controls.sync();
    f.owner.render();f.owner.render();f.controls.sync();await settle();
    assert.equal(f.jobs().length,0,'History display and ordinary rendering do not automatically start model work');
    f.settings.imageCommitted(selected);await settle();
    assert.equal(f.jobs().length,1,'A newly committed HDR-selected still starts one real HDR service request');
    const request=f.jobs()[0].body;
    assert.equal(request.source_kind,'output_image');assert.deepEqual(request.output_ref,strict(master));
    assert.equal(request.frame_count,1);assert.equal(request.sequence_fps,24);assert.equal(request.mode,'sdr');
    assert.ok(f.calls.some(call=>call.path.includes('/hdr/readiness?')&&new URLSearchParams(call.path.split('?')[1]).get('single_frame')==='1'));
    f.settings.imageCommitted(selected);await settle();assert.equal(f.jobs().length,1,'The same immutable result cannot submit a duplicate HDR job');
    const writes=f.calls.filter(call=>call.path==='/zura/studio/save-output').length;
    await assert.rejects(()=>f.settings.resolveImageItem(selected),/HDR|not ready|conversion/i);
    await assert.rejects(()=>f.settings.saveImageItem(selected,f.document.createElement('button')),/HDR|not ready|conversion/i);
    assert.equal(f.calls.filter(call=>call.path==='/zura/studio/save-output').length,writes,'Pending HDR never silently exports the SDR original');
    const panel=f.controls.progressHost;
    assert.equal(panel.hidden,false);assert.notEqual(panel.getAttribute('aria-modal'),'true','Progress is modeless and cannot block other navigation');
    assert.equal(panel.querySelector('progress').hasAttribute('value'),false,'No unmeasured fake percentage is shown while HDR is running');
    f.owner.show('references');assert.equal(panel.hidden,false,'Progress stays visible when its owning result is in another mode');
    f.owner.show('image');
    f.setState('complete');await f.controls.delivery.client.poll();await settle();
    const hdr=await f.settings.resolveImageItem(selected);
    assert.ok(/\.exr$/.test(hdr.filename),'A completed image HDR delivery resolves to a genuine EXR, never its PNG preview');
    const verification=f.exports().find(call=>call.body.format==='hdr_exr');
    assert.ok(verification,'A completed job still verifies the physical HDR image before enabling exports');
    assert.ok(verification.body.jobId,'The physical HDR verification is bound to its actual completed job');
    assert.deepEqual(verification.body.source,strict(master),'The verified HDR job must identify the original SDR master, not its display preview');
    assert.deepEqual(selected,before,'The completed HDR delivery is additional media, never a retagged SDR master');
    assert.equal(f.jobs().length,1);
  }finally{f.close();}
}

{
  const f=await fixture();
  try{
    f.controls.output='hdr';f.controls.hdrFormat='acescg_exr';f.settings.imageCommitted(f.owner.items[0]);await settle();
    let release;
    f.deferExport((path,body)=>body.format==='hdr_exr'?new Promise(resolve=>{release=resolve;}):Promise.reject(Error('Only physical HDR verification was expected')));
    f.setState('complete');await f.controls.delivery.client.poll();await settle(2);
    assert.equal(typeof release,'function','HDR completion starts a physical output verification');
    await assert.rejects(()=>f.settings.resolveImageItem(f.owner.items[0]),/HDR|not ready|verif|conversion/i);
    release({ok:true,json:async()=>({schemaVersion:1,file:hdrMaster,format:'hdr_exr',width:512,height:512,colour:{encoding:'srgb_display',sceneLinear:false},dynamicRange:'SDR',hasAlpha:false,sampleType:'uint8',bitDepth:8,sourceBitDepth:8,sha256:'e'.repeat(64)})});
    await settle();
    await assert.rejects(()=>f.settings.resolveImageItem(f.owner.items[0]),/HDR|not ready|verif|conversion|failed/i);
    assert.equal(f.controls.progressHost.dataset.state,'failed','Physical HDR verification failure cannot leave the progress panel labelled Ready');
    assert.equal(f.calls.filter(call=>call.path==='/zura/studio/save-output').length,0,'A PNG-like SDR verification response can never promote a master to HDR');
  }finally{f.close();}
}

{
  const storage=memoryStorage(),first=await fixture({storage});
  let release,firstClosed=false;
  try{
    first.controls.output='hdr';first.controls.hdrFormat='acescg_exr';first.settings.imageCommitted(first.owner.items[0]);await settle();
    first.deferExport(()=>new Promise(resolve=>{release=resolve;}));first.setState('complete');await first.controls.delivery.client.poll();await settle(2);
    assert.equal(typeof release,'function');
    const raw=first.controls.raw('image');assert.equal(first.controls.recordFor('image',raw).state,'verifying');
    first.close();firstClosed=true;
    const next=await fixture({storage});
    try{
      await settle();
      assert.equal(next.jobs().length,0,'Reopening a physically unverified completed HDR result must not resubmit the model');
      const verification=next.exports().find(call=>call.body.format==='hdr_exr');
      assert.ok(verification,'The reopened record resumes physical file verification');
      assert.ok(verification.body.jobId);assert.equal(next.controls.recordFor('image',next.controls.raw('image')).state,'complete');
      assert.ok((await next.settings.resolveImageItem(next.owner.items[0])).filename.endsWith('.exr'));
      const recordKey=next.controls.resultKey('image',next.controls.raw('image'));
      const saved=JSON.parse(storage.getItem('zura-studio-hdr-deliveries-v1'))[recordKey];
      assert.equal(saved.state,'complete');
      release({ok:false,status:400,json:async()=>({error:'Old verifier failed after this window closed'})});
      await settle();
      const after=JSON.parse(storage.getItem('zura-studio-hdr-deliveries-v1'))[recordKey];
      assert.deepEqual(after,saved,'A late failure from the closed old verifier cannot overwrite a reopened successful record');
    }finally{next.close();}
  }finally{if(!firstClosed)first.close();}
}

for(const state of ['failed','cancelled']){
  const f=await fixture();
  try{
    f.controls.output='hdr';f.controls.hdrFormat='acescg_exr';f.settings.imageCommitted(f.owner.items[0]);await settle();
    f.setState(state);await f.controls.delivery.client.poll();await settle();
    await assert.rejects(()=>f.settings.resolveImageItem(f.owner.items[0]),/HDR|not ready|conversion|cancel|failed/i);
    assert.equal(f.calls.filter(call=>call.path==='/zura/studio/save-output').length,0);
    f.settings.imageCommitted(f.owner.items[0]);await settle();assert.equal(f.jobs().length,1,'A repeated commit callback cannot silently retry '+state+' model work');
    assert.ok(f.owner.items[0].master.filename.endsWith('.exr'));
  }finally{f.close();}
}

for(const model of ['flux3','qwen2511','ph3edit','chatgpt','gemini']){
  const f=await fixture({selected:item(model)});
  try{
    f.controls.output='hdr';f.controls.hdrFormat='acescg_exr';f.settings.imageCommitted(f.owner.items[0]);await settle();
    assert.equal(f.jobs().length,1,model+' uses the same one-frame HDR post-pass after a committed result');
    assert.equal(f.jobs()[0].body.frame_count,1);
  }finally{f.close();}
}

{
  const legacy={model:'flux3',file:preview,master,colour:{encoding:'srgb_display',sceneLinear:false},width:512,height:512};
  const f=await fixture({selected:legacy});
  try{
    f.controls.output='hdr';
    const raw=f.controls.raw('image');assert.equal(raw.kind,'hdr_sequence','This reproduces the legacy extension-only descriptor');
    assert.equal(f.controls.alreadyHDR(raw),false,'Explicit SDR colour metadata takes precedence over an EXR-derived kind');
    assert.equal(f.controls.outputFor('image',raw),null,'A float SDR EXR is not a ready HDR export');
    await assert.rejects(()=>f.settings.resolveImageItem(legacy),/HDR|not ready|conversion|verif/i);
    f.settings.imageCommitted(legacy);await settle();
    assert.equal(f.jobs().length,1,'A legacy SDR float master still needs one-frame HDR reconstruction');
    assert.equal(f.jobs()[0].body.source_kind,'output_image');assert.equal(f.jobs()[0].body.frame_count,1);
  }finally{f.close();}
}

for(const [encoding,sceneLinear,expected]of [['acescg',true,'hdr'],['srgb_display',false,'sdr']]){
  const f=await fixture();
  try{
    f.owner.references=[{file:'prepared.png',filename:'prepared.png',subfolder:'model-view',type:'input',width:512,height:512,
      resolved_colour:'srgb_display',colour:{encoding:'srgb_display',sceneLinear:false},precision:{storageBitDepth:8,sampleType:'uint8'},
      processingView:{kind:'sdr8_inference',originalSource:{file:'original.exr',filename:'original.exr',type:'input',width:512,height:512,
        resolved_colour:encoding,colour:{encoding,sceneLinear},precision:{storageBitDepth:32,sampleType:'float32'}}}}];
    assert.equal(f.controls.input(f.owner).input,expected,'Input range follows the retained original '+encoding+' rather than its PNG model view or FLOAT storage alone');
  }finally{f.close();}
}

{
  // Match HDRIBuilder.import(): the item initially contains only its SDR
  // preview and a retained native-source ID, never a fabricated ACES master.
  const native={model:'HDRI preview',prompt:'Imported environment.exr',file:{...hdrPreview},hdri_source_id:'a'.repeat(32),source_hdr:true};
  const f=await fixture({selected:native});
  try{
    const originalPreview=structuredClone(native.file),nativeFile=file('environment_123456abcdef.exr','ZURA STUDIO/hdri');
    f.owner.imageIntent='hdri';
    f.owner.fetch=async(path,body)=>{
      f.calls.push({path,body});
      assert.equal(path,'/zura/studio/hdri/export');
      return {schemaVersion:1,file:nativeFile,source_id:native.hdri_source_id,source_sha256:'1'.repeat(64),source_hdr:true,
        colour:{encoding:'linear_rec709',sceneLinear:true},sampleType:'float32',bitDepth:32,hasAlpha:false,sha256:'2'.repeat(64)};
    };
    const builder=Object.assign(Object.create(HDRIBuilder.prototype),{owner:f.owner,serial:0,state:{color_space:'auto',export_space:'linear_rec709',yaw:0,exposure:0,lights:[]},closed:false,loading:false,editor:{snapshot:()=>JSON.stringify({stickers:[]})}});
    f.owner.hdri=builder;f.controls.output='hdr';
    assert.equal(typeof builder.outputDescriptor,'function','The real native HDRI producer exposes a verified descriptor path');
    f.settings.imageCommitted(native);await settle();
    assert.equal(f.jobs().length,0,'A retained native HDRI source must not be reconstructed through LTX');
    const resolved=await f.settings.resolveImageItem(native);
    assert.deepEqual(resolved,nativeFile);
    assert.ok(f.calls.some(call=>call.path==='/zura/studio/hdri/export'&&call.body.source_id===native.hdri_source_id),'Save resolves the actual owned HDRI source, not the preview');
    assert.equal(native.nativeHDRIOutput.colour.encoding,'linear_rec709','Native HDRI primaries are retained rather than fabricated as ACEScg');
    assert.deepEqual(native.file,originalPreview);assert.equal(native.master,undefined,'The separate native output never replaces the SDR preview item');
    await f.settings.saveImageItem(native,f.document.createElement('button'));
    assert.deepEqual(f.calls.findLast(call=>call.path==='/zura/studio/save-output').body.assets,[nativeFile]);
    await f.settings.downloadImageItem(native,f.document.createElement('button'));
    assert.equal(f.downloads.at(-1).filename,nativeFile.filename);assert.equal(f.jobs().length,0);
  }finally{f.close();}
}

{
  const generated={model:'flux3',image_intent:'hdri',file:file('panorama.png'),colour:{encoding:'srgb_display',sceneLinear:false},width:512,height:512};
  const f=await fixture({selected:generated});
  try{
    f.owner.imageIntent='hdri';f.controls.output='hdr';f.settings.imageCommitted(generated);await settle();
    assert.equal(f.jobs().length,1,'An SDR-generated panorama still needs the explicitly selected HDR post-pass');
    assert.equal(f.jobs()[0].body.frame_count,1);
  }finally{f.close();}
}

for(const change of ['source','selection','master','mode-only']){
  const f=await fixture();
  try{
    let release;
    const selected=f.owner.items[0],before=structuredClone(selected);
    f.deferPreflight(()=>new Promise(resolve=>{release=resolve;}));
    f.controls.output='hdr';f.settings.imageCommitted(selected);await settle(2);
    assert.equal(typeof release,'function','The real HDR readiness request is held before submission');assert.equal(f.jobs().length,0);
    if(change==='source')f.owner.references=[{file:'changed-main-source.png',width:512,height:512}];
    else if(change==='selection'){f.owner.items.push(item('new-history-selection'));f.owner.selectedImage=1;}
    else if(change==='master')selected.master={...selected.master,filename:'new-composite.exr'};
    else f.owner.show('video');
    release({ok:true,json:async()=>({ready:true,longPreview:true,files:[]})});await settle();
    assert.equal(f.jobs().length,change==='mode-only'?1:0,change==='mode-only'?'Mode navigation alone cannot cancel preparation owned by the same image and source':'Changed '+change+' cannot submit a stale HDR job after preflight');
    if(change==='mode-only')assert.equal(f.controls.progressHost.hidden,false,'The valid image job retains visible owned progress across modes');
    if(change==='master')assert.equal(selected.master.filename,'new-composite.exr','Stale preparation cannot overwrite the newly committed master');
    else assert.deepEqual(selected,before,'Preparation never mutates the retained SDR original');
  }finally{f.close();}
}

for(const change of ['selection','source','output','close']){
  const f=await fixture();
  try{
    f.controls.output='hdr';f.settings.imageCommitted(f.owner.items[0]);
    if(change==='selection'){f.owner.items.push(item('other'));f.owner.selectedImage=1;}
    else if(change==='source')f.owner.references=[{file:'different.png',width:512,height:512}];
    else if(change==='output')f.controls.output='sdr';
    else f.controls.close();
    await settle();assert.equal(f.jobs().length,0,'A queued '+change+' commit cannot start work against a stale result');
  }finally{f.close();}
}

{
  const f=await fixture();
  try{
    const before=structuredClone(f.owner.items[0]);
    f.setExportResponse({schemaVersion:1,file:file('wrong.exr'),format:'png8',width:512,height:512,colour:{encoding:'acescg',sceneLinear:true},dynamicRange:'HDR',hasAlpha:false,sampleType:'float32',bitDepth:32,sha256:'e'.repeat(64)});
    await assert.rejects(()=>f.settings.resolveImageItem(f.owner.items[0]),/verif|format|SDR/i);
    assert.deepEqual(f.owner.items[0],before);assert.equal(f.downloads.length,0);
  }finally{f.close();}
}

{
  const f=await fixture();
  try{
    let release;
    f.deferExport(()=>new Promise(resolve=>{release=resolve;}));
    const selected=f.owner.items[0],pending=f.settings.downloadImageItem(selected,f.document.createElement('button'));
    await settle(2);assert.equal(typeof release,'function');f.owner.items.push(item('other'));f.owner.selectedImage=1;
    release({ok:true,json:async()=>({schemaVersion:1,file:file('late.png','ZURA STUDIO/image-exports/'+'d'.repeat(32)),format:'png8',width:512,height:512,colour:{encoding:'srgb_display',sceneLinear:false},dynamicRange:'SDR',hasAlpha:false,sampleType:'uint8',storageBitDepth:8,bitDepth:8,sourceBitDepth:32,sha256:'e'.repeat(64)})});
    await assert.rejects(()=>pending,/changed|selected|current|again/i);
    assert.equal(f.downloads.length,0,'A late prepared export cannot download the wrong selected item');
  }finally{f.close();}
}

{
  const f=await fixture();
  try{
    const choice=f.controls.outputChoice;
    assert.equal(choice.parentElement,f.root.querySelector('.zc-composer-bottom'),'Image uses its actual composer rather than a nonexistent video-tools selector');
    assert.equal(choice.hidden,false);
    const modes=[['paint_vfx','paint_vfx','.zvfx-settings'],['director','director','.zdir-composer-row'],['frames','frames','.zf-composer .zc-prompt-tools'],['references','referencesVideo','.zf-composer .zc-prompt-tools'],['paintout','paintout','.zpx-properties'],['watermark','watermark','.zf-composer .zc-prompt-tools'],['outpaint','outpaint','.zo-action .zc-prompt-tools'],['ripple','ripple','.zru-tools'],['camera','panorama','.zpc-composer .zc-prompt-tools'],['alpha','alpha','.zc-prompt-tools']];
    for(const [mode,member,selector]of modes){
      const page=f.document.createElement('section'),parts=selector.split(' ');let host=page;
      for(const part of parts){const node=f.document.createElement('div');node.className=part.slice(1);host.append(node);host=node;}
      f.root.append(page);f.owner[member]={page,state:{},config(){return {};},render(){},$:()=>null};f.owner.mode=mode==='camera'?'panorama':mode;
      f.controls.sync();assert.equal(choice.parentElement===host,true,mode+' keeps the same visible Output choice beside its generation controls');assert.equal(choice.hidden,false);assert.equal(f.root.querySelectorAll('[data-delivery-output]').length,1);
    }
    for(const mode of ['motion','viewport']){f.owner.mode='video';f.owner.studio.config.workflow_mode=mode;f.controls.sync();assert.equal(choice.parentElement,f.root.querySelector('.gs-composer .zc-prompt-tools'));assert.equal(choice.hidden,false);}
    f.owner.mode='ripple';f.owner.ripple.intent='relight';f.controls.sync();assert.equal(choice.parentElement,f.owner.ripple.page.querySelector('.zru-tools'));assert.equal(choice.hidden,false,'Standalone relight retains its output choice');
    const hdrPage=f.document.createElement('section');hdrPage.innerHTML='<div class="zh-footer"></div><select data-field="source-kind"><option value="upload">Source</option></select><label><select data-field="mode"><option value="sdr">SDR</option></select></label><label><select data-field="output"><option value="acescg_exr">EXR</option></select></label>';
    f.root.append(hdrPage);f.owner.studio.hdrTool={root:hdrPage,$:key=>hdrPage.querySelector('[data-field="'+key+'"]'),getSource:()=>null};f.owner.mode='hdr';f.controls.sync();
    assert.equal(choice.parentElement,hdrPage.querySelector('.zh-footer'));assert.equal(choice.hidden,false,'The native HDR workflow still presents the same truthful output choice');
    f.owner.mode='image';f.root.querySelector('.zc-image-composer').remove();f.controls.sync();
    assert.equal(choice.parentElement,f.controls.element,'An unavailable host falls back to the visible shared strip instead of losing the control');assert.equal(choice.hidden,false);
  }finally{f.close();}
}

console.log('Image delivery controllers: explicit SDR formats, immutable masters, one-frame HDR commits, verified completed exports, no SDR fallback, stale-result fences and per-mode Output mounting pass.');

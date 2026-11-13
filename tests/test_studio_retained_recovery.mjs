import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioAEBridge} from '../web/studio_comfylink.js';

const source={width:512,height:512,frameCount:1,precision:{sourceBitDepth:32},
  manifest:{frameRate:{numerator:30000,denominator:1001},frames:[{}]},
  processingInput:{precision:{sourceBitDepth:8},stills:{first:{file:'source.png',width:512,height:512}}}};
const candidate={id:'a'.repeat(64),kind:'image',master:{filename:'klein9b_00009_.png',subfolder:'zura_images',type:'output'},
  width:512,height:512,frameRate:{numerator:30000,denominator:1001},sourceManifestSha256:'b'.repeat(64),imageSha256:'c'.repeat(64)};
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
async function settled(bridge){for(let i=0;i<30&&bridge.recoveryLoading;i++)await tick();}
function fixture({lookup,check}={}){
  const {document}=parseHTML('<html><body><main><header class="gs-top"></header></main></body></html>');
  const controls=new Map(),calls=[],container=document.querySelector('main'),studio={container};
  const c={studio,mode:'home',items:[],references:[],selectedImage:-1,normalDraft:'Kept',
    outputSettings:{exrLabel:()=>'',preferSourcePrecision(){}},
    $(id){if(!controls.has(id))controls.set(id,{value:'',checked:false});return controls.get(id);},
    show(id){this.mode=id;},async setImageOperation(){},clearImageResult(){this.selectedImage=-1;},
    config(){return {model:'klein9b',prompt:'Keep my new instruction',references:this.references};},
    save(){this.saved=(this.saved||0)+1;},renderGallery(){this.preview=this.items[this.selectedImage]?.file;},
    render(){studio.aeBridge?.modeChanged();},syncForm(){},
    activateImageResult(index){this.selectedImage=index;this.save();this.renderGallery();this.render();},
    generate(){throw Error('Recovery must never queue generation');}};
  c.$('prompt').value='Keep my new instruction';studio.creative=c;
  const api={fetchApi:async(path,options)=>{
    const body=options?.body?JSON.parse(options.body):undefined;calls.push({path,body});
    if(path.endsWith('/source'))return {ok:true,json:async()=>structuredClone(source)};
    if(path.endsWith('/retained-images')){
      const data=body.candidateId?(check?await check(body):{result:candidate}):(lookup?await lookup(body):{results:[candidate]});
      return {ok:true,json:async()=>structuredClone(data)};
    }
    if(path.endsWith('/result'))return {ok:true,json:async()=>({status:'sent'})};
    if(path.endsWith('/leave'))return {ok:true,json:async()=>({status:'left'})};
    throw Error('Unexpected request '+path);
  }};
  const bridge=new StudioAEBridge(studio,api,{id:'d'.repeat(32),capability:'e'.repeat(64)},()=>{});
  studio.aeBridge=bridge;
  return {bridge,c,calls};
}

{
  const {bridge,c,calls}=fixture();
  try{
    c.mode='image';await bridge.loadSource();await settled(bridge);
    assert.equal(bridge.recoveryButton.textContent,'Use saved result');assert.equal(bridge.recoveryButton.hidden,false);
    assert.equal(c.items.length,0,'Lookup never selects or transfers an image automatically');
    assert.ok(calls.every(call=>!call.path.endsWith('/result')&&!call.path.endsWith('/prompt')));
    await bridge.useSavedResult();
    assert.equal(c.items.length,1);assert.deepEqual(c.preview,candidate.master);assert.equal(c.selectedImage,0);
    assert.equal(c.items[0].ae_frame_contract.sessionId,bridge.session.id,'The restored preview belongs to the current verified source session');
    assert.equal(c.$('prompt').value,'Keep my new instruction');assert.equal(c.normalDraft,'Kept');
    assert.equal(bridge.recoveryButton.hidden,true);assert.match(bridge.status.textContent,/Review it/);
    assert.ok(calls.every(call=>!call.path.endsWith('/result')&&!call.path.endsWith('/prompt')));
    await bridge.sendResult();
    assert.deepEqual(calls.find(call=>call.path.endsWith('/result')).body,{kind:'image',master:candidate.master});
    assert.equal(bridge.status.textContent,'Sent to After Effects');
    assert.ok(calls.every(call=>!call.path.endsWith('/prompt')));
  }finally{bridge.dispose();}
}
{
  const {bridge,c}=fixture({lookup:async()=>({results:[]})});
  try{c.mode='image';await bridge.loadSource();await settled(bridge);assert.equal(bridge.recoveryButton.hidden,true);assert.equal(bridge.status.textContent,'AE source ready');await bridge.useSavedResult();assert.equal(c.items.length,0);}finally{bridge.dispose();}
}
{
  let release;const wait=new Promise(resolve=>release=resolve);
  const {bridge,c}=fixture({check:()=>wait});
  try{
    c.mode='image';await bridge.loadSource();await settled(bridge);
    const pending=bridge.useSavedResult();await tick();
    const newer={file:{filename:'new-result.png',subfolder:'zura_images',type:'output'}};
    c.items=[newer];c.selectedImage=0;release({result:candidate});await pending;
    assert.equal(c.items[0],newer,'An in-flight recovery cannot replace a newly completed result');
  }finally{bridge.dispose();}
}
{
  let release;const wait=new Promise(resolve=>release=resolve);
  const {bridge,c}=fixture({lookup:()=>wait});
  c.mode='image';await bridge.loadSource();bridge.dispose();release({results:[candidate]});await settled(bridge);
  assert.equal(c.items.length,0);assert.equal(bridge.recoveryCandidates.length,0,'A departed session cannot offer late results');
}
{
  const {bridge,c}=fixture({check:async()=>({result:{...candidate,imageSha256:'f'.repeat(64)}})});
  try{c.mode='image';await bridge.loadSource();await settled(bridge);await bridge.useSavedResult();assert.equal(c.items.length,0);assert.match(bridge.status.textContent,/No matching saved result/);}finally{bridge.dispose();}
}
{
  let release,count=0;const wait=new Promise(resolve=>release=resolve);
  const {bridge,c}=fixture({lookup:()=>++count===1?wait:{results:[candidate]}});
  try{
    c.mode='image';await bridge.loadSource();await bridge.loadSource(true);
    release({results:[candidate]});await settled(bridge);
    assert.equal(count,2,'An explicit source reload supersedes an in-flight lookup without losing recovery');
    assert.equal(bridge.recoveryButton.hidden,false);
  }finally{bridge.dispose();}
}
console.log('Saved-result recovery verifies the same AE source, restores a reviewable image, preserves drafts and never regenerates or transfers automatically');

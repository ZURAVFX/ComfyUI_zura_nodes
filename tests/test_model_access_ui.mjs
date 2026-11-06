import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {ModelAccess,importModelFile} from '../web/studio_model_access.js';
import {StudioModelDownloads} from '../web/studio_model_download.js';
const {document,window}=parseHTML('<html><head></head><body><div id="access"></div><details id="models"></details></body></html>');
Object.assign(globalThis,{document,window});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
const calls=[];let retried=0,state={connected:false};
const access=new ModelAccess(document.querySelector('#access'),async(path,body)=>{calls.push({path,body});if(body?.token)state={connected:true,name:'artist',remembered:body.remember};else if(body?.disconnect)state={connected:false};return state;},()=>retried++);
const file={folder:'vae',filename:'model.safetensors',size_bytes:32,installed:false,gated:true,model_card:'https://huggingface.co/Example/gated',repo:'Example/gated',browser_url:'https://huggingface.co/Example/gated/resolve/main/model.safetensors?download=true'};
access.setFiles([file]);assert.equal(access.root.hidden,false);assert.equal(calls.length,0,'Opening Studio never sends credentials or starts auth/downloads');
assert.equal(access.$('terms').querySelector('a').href,'https://huggingface.co/Example/gated');
access.$('token').value='hf_FixtureOnly';access.$('remember').checked=true;await access.connect();
assert.deepEqual(calls[0],{path:'/model-access',body:{token:'hf_FixtureOnly',remember:true}});
assert.equal(retried,1,'Connecting retries the requested missing files once');assert.equal(access.$('token').value,'');assert.match(access.$('status').textContent,/Connected as artist/);
assert.equal(access.$('form').hidden,true);await access.disconnect();assert.equal(access.$('form').hidden,false);
const bad=new ModelAccess(document.querySelector('#access'),async()=>{throw Error('Bad hf_SecretFixture');},()=>assert.fail('Cannot retry before a successful connection'));
bad.$('token').value='hf_SecretFixture';await bad.connect();assert.equal(bad.$('token').value,'');assert.doesNotMatch(bad.root.textContent,/SecretFixture/);assert.equal(bad.$('connect').disabled,false);
access.setFiles([{...file,repo:undefined}],{auth_required:true,access_repo:'Example/gated'});
assert.equal(access.$('terms').querySelectorAll('a').length,1,'Paintout model-card metadata produces the same terms link');

let authorised=false,downloads=0;const pack={id:'ltx25_core',name:'LTX',files:[file],remaining_bytes:32};
const installer=new StudioModelDownloads(document.querySelector('#models'),async(path,body)=>{
 if(path==='/model-access'){if(body?.action==='check_files')return {allowed:authorised,auth_required:!authorised,access_repo:'Example/gated',access_reason:'connect'};if(body?.token)authorised=true;return {connected:authorised,name:authorised?'artist':''};}
 if(path==='/model-downloads'&&body){downloads++;return {id:'fixture'};}
 if(path==='/model-downloads/fixture'){if(authorised){file.installed=true;pack.remaining_bytes=0;return {phase:'done',total_bytes:32,done_bytes:32};}return {phase:'failed',auth_required:true,access_repo:'Example/gated',access_reason:'connect',error:'Access required'};}
 if(path==='/model-downloads')return {models:[pack]};
 throw Error(path);
});
await installer.load();installer.select.value=pack.id;await installer.start(pack.id);
assert.equal(downloads,0,'Gated access is checked before any model download');assert.equal(installer.panel.open,true);assert.equal(installer.access.root.open,true);assert.ok(installer.access.blocked);
const other=document.createElement('option');other.value='other-package';installer.select.append(other);
installer.select.value='other-package';installer.select.onchange();
assert.equal(installer.retryRequest,null,'Changing package cancels the old gated download intent');
installer.access.request=async()=>({connected:true});await installer.access.onTermsReturn();
assert.equal(downloads,0,'Returning from terms cannot start a package the user has left');
installer.access.request=installer.request;installer.select.value=pack.id;installer.select.onchange();await installer.start(pack.id);
installer.access.$('token').value='hf_FixtureOnly';await installer.access.connect();
assert.equal(downloads,1);assert.equal(installer.progress.textContent,'Download complete.');assert.equal(installer.accessFailure,null);installer.dispose();

const create=document.createElement.bind(document);let xhrBody,importProgress;
document.createElement=tag=>{const node=create(tag);if(tag==='input')node.click=()=>{Object.defineProperty(node,'files',{value:[{name:'download (1).safetensors',size:32}]});node.onchange();};return node;};
globalThis.XMLHttpRequest=class{
 constructor(){this.upload={};}
 open(method,url){assert.equal(method,'POST');assert.match(url,/model_id=ltx25_core/);assert.match(url,/filename=model.safetensors/);}
 setRequestHeader(){}
 send(body){xhrBody=body;this.upload.onprogress({loaded:32,total:32});this.status=200;this.responseText='{"id":"imported"}';this.onload();}
};
const result=await importModelFile('/zura/studio/model-downloads','ltx25_core',file,(done,total)=>importProgress=[done,total]);
assert.equal(result.id,'imported');assert.equal(xhrBody.name,'download (1).safetensors','Browser download names need not match; content is verified by the server');assert.deepEqual(importProgress,[32,32]);
document.createElement=tag=>{const node=create(tag);if(tag==='input')node.click=()=>node.oncancel();return node;};
assert.deepEqual(await importModelFile('/zura/studio/model-downloads','ltx25_core',file),{cancelled:true});
document.createElement=create;
console.log('Shared access, gated failure/reconnect/retry, secret clearing and streamed browser import UI passed.');

// Browser-led connection uses a public device flow; no credential reaches the UI.
const nativeTimeout=globalThis.setTimeout,nativeClear=globalThis.clearTimeout;
let scheduled,opened=0,resumed=0;
globalThis.setTimeout=callback=>{scheduled=callback;return 1;};globalThis.clearTimeout=()=>{scheduled=null;};
window.open=()=>{opened++;return {opener:{},location:{},close(){}};};
const browserCalls=[];
const browserAccess=new ModelAccess(document.querySelector('#access'),async(path,body)=>{
 browserCalls.push(body);
 if(body.action==='browser_start')return {id:'device-session',url:'https://huggingface.co/oauth/device',code:'TEST-CODE',interval:5};
 if(body.action==='browser_poll')return {phase:'connected',connected:true,name:'artist'};
 if(body.action==='browser_cancel')return {phase:'cancelled'};
},()=>resumed++);
await browserAccess.startBrowser();assert.equal(opened,1);assert.equal(browserAccess.$('cancel').hidden,false);
assert.match(browserAccess.$('code').textContent,/TEST-CODE/);assert.equal(typeof scheduled,'function');
await browserAccess.pollBrowser();assert.equal(resumed,1);assert.equal(browserAccess.$('browser').hidden,true);assert.equal(scheduled,null);
assert.deepEqual(browserCalls[1],{action:'browser_poll',id:'device-session'});
let termsPrevented=false;
browserAccess.setFiles([file],{access_repo:'Example/gated',access_reason:'terms'});
browserAccess.request=async()=>({connected:true,name:'artist'});
browserAccess.$('terms').querySelector('a').onclick({preventDefault(){termsPrevented=true;}});
assert.equal(termsPrevented,true,'A working popup does not also open a duplicate tab');
await browserAccess.onTermsReturn();assert.equal(resumed,2,'Returning from model terms resumes the requested download');
browserAccess.request=async(path,body)=>body.action==='browser_start'?{id:'device-session',url:'https://huggingface.co/oauth/device'}:{phase:'cancelled'};
// A blocked popup still offers the secure link; cancellation stops polling.
window.open=()=>null;await browserAccess.startBrowser();assert.equal(browserAccess.$('resume').hidden,false);
await browserAccess.cancelBrowser();assert.equal(scheduled,null);assert.equal(browserAccess.login,null);
let resolveStart;
const interrupted=new ModelAccess(document.querySelector('#access'),async(path,body)=>body.action==='browser_start'?await new Promise(resolve=>resolveStart=resolve):{phase:'cancelled'});
const starting=interrupted.startBrowser();interrupted.dispose();resolveStart({id:'late',url:'https://huggingface.co/oauth/device'});await starting;
assert.equal(interrupted.login,null);assert.equal(scheduled,null,'Closing a workspace cannot leave browser sign-in polling');
globalThis.setTimeout=nativeTimeout;globalThis.clearTimeout=nativeClear;
console.log('Browser sign-in, blocked-popup fallback, automatic retry and cancellation races passed.');

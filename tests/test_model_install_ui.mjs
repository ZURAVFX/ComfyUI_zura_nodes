import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioModelDownloads} from '../web/studio_model_download.js';
import {ModelStorage} from '../web/studio_model_storage.js';
const {document}=parseHTML('<html><body><form><details id="models"></details></form></body></html>');
globalThis.document=document;
Object.defineProperty(document.defaultView.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const o of this.querySelectorAll('option'))o.toggleAttribute('selected',o.value===value);}});
const file=(name,size)=>({folder:'vae',filename:name,size_bytes:size,installed:false,repo:'test/models'});
const a=file('shared.safetensors',100),b=file('needed.safetensors',200),extra=file('unused.safetensors',9999);
const packs=[{id:'h3_reference_core',name:'Core',remaining_bytes:10099,files:[a,extra]},{id:'h3_first_last',name:'Endpoint',remaining_bytes:300,files:[a,b]}];
const posts=[];let refreshed=0;
const setup=new StudioModelDownloads(document.querySelector('#models'),async(path,body)=>{
 if(path==='/model-downloads'&&!body)return {models:packs};
 if(path==='/model-downloads'&&body){posts.push(body);return {id:'single-job'};}
 if(path==='/model-downloads/single-job'){a.installed=b.installed=true;return {phase:'done',total_bytes:300,done_bytes:300};}
 throw Error(path);
},()=>refreshed++);
setup.mountQuick(document.querySelector('form'));setup.packages=packs;
setup.setContext({route:'h3_first_last',files:[{...a,ready:false},{...b,ready:false}],missingNodes:[]});
assert.equal(setup.workflowPlan().bytes,300,'No unused bundle files are charged to this workflow');
assert.equal(setup.workflowPlan().packs.length,1,'A single covering package is preferred');
assert.match(setup.quick.textContent,/2 missing files/);
assert.equal(setup.quick.querySelector('[data-quick-install]').disabled,false);
await setup.quick.querySelector('[data-quick-install]').onclick();
assert.equal(posts.length,1,'One click submits one server job');
assert.deepEqual(posts[0],{model_ids:['h3_first_last'],file_keys:['vae/shared.safetensors','vae/needed.safetensors']});
assert.equal(refreshed,1);assert.equal(setup.progress.textContent,'Download complete.');
setup.setContext({route:'h3_first_last',files:[{folder:'vae',filename:'manual-model.safetensors',ready:false}],missingNodes:[]});
assert.equal(setup.quick.querySelector('[data-quick-install]').disabled,true,'An unlisted file has no automatic download');
assert.equal(setup.quick.querySelector('[data-quick-refresh]').hidden,false,'Users can recheck setup after installing an unlisted file');
await setup.quick.querySelector('[data-quick-refresh]').onclick();
assert.equal(refreshed,2,'Check setup refreshes workflow readiness after manual installation');
setup.dispose();
const requests=[];let updates=0;
let folders=['/external/models'],target=folders[0];
const storage=new ModelStorage(document.body,async(path,body)=>{requests.push([path,body]);if(body){folders=body.folders;target=body.download_to;}return {folders,external:target,default:'/comfy/models',download_to:target||'/comfy/models'};},()=>updates++);
assert.equal(requests.length,0,'Storage discovery is passive until opened');
await storage.load();assert.equal(storage.$('target').value,'/external/models');
storage.$('path').value='/shared/models';await storage.$('save').onclick();
assert.deepEqual(requests.at(-1),['/model-folders',{folders:['/external/models','/shared/models'],download_to:'/shared/models'}]);assert.equal(updates,1);
storage.$('target').value='/external/models';await storage.$('target').onchange();
assert.deepEqual(requests.at(-1),['/model-folders',{folders:['/external/models','/shared/models'],download_to:'/external/models'}]);assert.equal(updates,2);
storage.$('target').value='';await storage.$('target').onchange();
assert.equal(requests.at(-1)[1].download_to,'');assert.equal(storage.folders.length,2,'Choosing the normal destination keeps external search folders');
await storage.$('folders').querySelector('button').onclick();
assert.deepEqual(requests.at(-1)[1],{folders:['/shared/models'],download_to:''});
assert.equal(storage.$('save').disabled,false);

// Opening the storage panel can overlap a save or another refresh. A stale
// response must never put the previously selected download folder back.
let resolveOldLoad;
const delayedStorage=new ModelStorage(document.body,async(path,body)=>{
 if(!body)return await new Promise(resolve=>{resolveOldLoad=resolve;});
 return {folders:body.folders,external:body.download_to,default:'/comfy/models'};
});
const oldLoad=delayedStorage.load();
await delayedStorage.save(['/new/models'],'/new/models');
resolveOldLoad({folders:['/old/models'],external:'/old/models',default:'/comfy/models'});
await oldLoad;
assert.equal(delayedStorage.$('target').value,'/new/models','An older load cannot overwrite a saved destination');

const refreshFailure=new ModelStorage(document.body,async(path,body)=>({folders:body.folders,external:body.download_to,default:'/comfy/models'}),async()=>{throw Error('offline');});
refreshFailure.loaded=true;refreshFailure.$('path').value='/saved/models';
await refreshFailure.add();
assert.equal(refreshFailure.target,'/saved/models');
assert.equal(refreshFailure.$('path').value,'','A saved folder is not reported as a failed save when the status refresh fails');
assert.match(refreshFailure.$('status').textContent,/Folder saved.*Check setup/);
console.log('One-click exact-file workflow install, shared-file deduplication, storage choice and readiness refresh passed.');

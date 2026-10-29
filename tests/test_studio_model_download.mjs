import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioModelDownloads} from '../web/studio_model_download.js';

const {document,window}=parseHTML('<html><body><details id="setup"></details></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value ?? this.querySelector('option')?.value ?? '';},set(value){for(const option of this.querySelectorAll('option'))option.selected=option.value===String(value);}});
globalThis.document=document;
const paths=[];
const pack={id:'wan_animate_2',name:'Wan Animate 2',note:'Separate nodes required.',remaining_bytes:1000000000,
  files:[{repo:'Comfy-Org/Wan-Animate-2',filename:'model.safetensors',size_bytes:1000000000,installed:false}]};
const availablePackages=['ltx25_text_encoder','ltx25_outpaint','ltx25_in_outpaint','ltx_control','h3_int8_vae','h3_control','h3_crossview'];
const ltxPackages=[...availablePackages,'ltx25_layout'].map(id=>({...pack,id,name:id}));
const request=async(path,body)=>{paths.push([path,body]);if(path==='/model-downloads' && !body)return {models:[pack,...ltxPackages]};if(path==='/model-downloads' && body)return {id:'job'};if(path==='/model-downloads/job'){pack.remaining_bytes=0;pack.files[0].installed=true;return {phase:'done',done_bytes:1000000000,total_bytes:1000000000};}throw Error(path);};
let refreshed=false;const component=new StudioModelDownloads(document.querySelector('#setup'),request,()=>{refreshed=true;});
await component.load();
assert.deepEqual([...component.select.querySelectorAll('option')].map(o=>o.value),['wan_animate_2',...availablePackages],'the rejected LTX viewport package remains hidden');
assert.equal(paths.length,1,'Listing must not start a download');
assert.match(component.files.textContent,/1.00 GB to download/);
assert.match(component.files.textContent,/Separate nodes required/);
assert.equal(component.files.querySelector('a').href,'https://huggingface.co/Comfy-Org/Wan-Animate-2');
await component.start('wan_animate_2');
assert.ok(refreshed);assert.equal(component.progress.textContent,'Download complete.');
assert.equal(paths.filter(([path,body])=>path==='/model-downloads' && body).length,1);
component.dispose();
console.log('Video package sizes, source licences, explicit download and completion refresh pass.');

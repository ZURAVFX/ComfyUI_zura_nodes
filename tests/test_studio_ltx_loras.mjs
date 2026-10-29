import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {LTXLoras} from '../web/studio_ltx_loras.js';
const {document,window}=parseHTML('<html><body><div id="host"></div></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option')){if(option.value===String(value))option.setAttribute('selected','');else option.removeAttribute('selected');}}});
let busy=false;
const requests=[];
const control=new LTXLoras(document.querySelector('#host'),async(path,body)=>{requests.push({path,body});if(path.endsWith('/apply'))return {graph:{...body.graph,patched:true}};return {loras:[
  {name:'ltx.safetensors',usable:true,metadata_family:'ltx25'},
  {name:'unknown.safetensors',usable:true,metadata_family:null},
  {name:'h3.safetensors',usable:true,metadata_family:'h3'},
  {name:'ltx-ic-lora.safetensors',usable:true,metadata_family:'ltx25'}
]};},()=>busy);
await control.load();const select=control.root.querySelector('[data-picker]');
assert.equal(select.querySelector('option[value="h3.safetensors"]').disabled,true);
assert.equal(select.querySelector('option[value="ltx-ic-lora.safetensors"]').disabled,true);
select.value='unknown.safetensors';control.root.querySelector('[data-custom-lora-add]').click();
assert.deepEqual(control.value(),[{name:'unknown.safetensors',strength:1,confirm_unknown:false}]);
const confirm=control.root.querySelector('input[data-field="confirm"]');assert.ok(confirm);
confirm.checked=true;confirm.dispatchEvent(new window.Event('change',{bubbles:true}));assert.equal(control.value()[0].confirm_unknown,true);
const strength=control.root.querySelector('input[data-field="strength"]');strength.value='.7';strength.dispatchEvent(new window.Event('change',{bubbles:true}));assert.equal(control.value()[0].strength,.7);
const patched=await control.patch({model:{class_type:'UNETLoader',inputs:{}}});assert.equal(patched.patched,true);assert.equal(requests.at(-1).body.family,'ltx25');assert.equal(requests.at(-1).body.loras[0].strength,.7);
busy=true;control.setBusy(true);assert.equal(control.root.querySelector('[data-custom-lora-add]').disabled,true);
busy=false;control.setBusy(false);control.root.querySelector('[data-remove="0"]').click();assert.deepEqual(control.value(),[]);
console.log('Standalone LTX LoRA control filters incompatible guides and requires confirmation for unknown metadata.');

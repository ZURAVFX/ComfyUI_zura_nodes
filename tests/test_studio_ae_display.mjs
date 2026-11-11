import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {AEFloatDisplay} from '../web/studio_ae_display.js';

const {document,window}=parseHTML('<html><body><main id="studio"></main></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{
  configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},
  set(value){for(const option of this.querySelectorAll('option'))option.selected=option.value===String(value);},
});
const calls=[],revoked=[];let sequence=0;
URL.createObjectURL=()=>`blob:preview-${++sequence}`;URL.revokeObjectURL=url=>revoked.push(url);
const config={config:'ocio://studio-config-latest',configs:[{name:'ocio://studio-config-latest',label:'Studio'}],
  displays:[{name:'sRGB - Display',views:['Un-tone-mapped','Raw']},{name:'P3',views:['Standard']}],display:'sRGB - Display',view:'Un-tone-mapped'};
const bridge={closed:false,studio:{container:document.getElementById('studio')},session:{id:'a'.repeat(32),capability:'b'.repeat(64),context:{source:{frameCount:3}}},
  api:{fetchApi:async(path,options)=>{calls.push({path,options});return path.includes('/display-config')?{ok:true,json:async()=>config}:{ok:true,blob:async()=>new Blob(['preview'],{type:'image/png'})};}}};
const view=new AEFloatDisplay(bridge);await view.open();
assert.equal(view.selectDisplay.value,'sRGB - Display');assert.equal(view.selectView.value,'Un-tone-mapped');
assert.equal(view.slider.max,'2');assert.equal(view.image.hidden,false);assert.equal(view.image.src,'blob:preview-1');
const first=calls.find(item=>item.path?.includes('/display-frame'));const query=new URL(first.path,'http://127.0.0.1').searchParams;
assert.equal(query.get('index'),'0');assert.equal(query.get('display'),'sRGB - Display');assert.equal(query.get('view'),'Un-tone-mapped');
assert.equal(first.options.headers['X-ComfyLink-Studio-Session'],bridge.session.capability);
assert.equal(first.path.includes(bridge.session.capability),false,'capability must not be in the URL');
view.selectView.value='Raw';await view.render();assert.equal(new URL(calls.at(-1).path,'http://127.0.0.1').searchParams.get('view'),'Raw');
assert.deepEqual(revoked,['blob:preview-1']);
bridge.api.fetchApi=async()=>({ok:false});await view.render();
assert.equal(view.image.hidden,true,'a failed new transform must not show an old image under the new labels');
assert.match(view.status.textContent,/not available/);
view.close();assert.deepEqual(revoked,['blob:preview-1','blob:preview-2']);
assert.equal(document.querySelector('.zc-display'),null);assert.equal(calls.some(item=>item.path?.includes('/result')),false);
console.log('Scoped AE FLOAT display preview: sRGB default, view selection, capability header and cleanup passed');

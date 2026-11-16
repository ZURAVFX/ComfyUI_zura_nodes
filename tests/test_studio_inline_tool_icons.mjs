import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {ImageEditArea,imageAreaSourceKey} from '../web/studio_image_area.js';
import {PlateSurface} from '../web/studio_plate_surface.js';

const {document,window}=parseHTML('<html><body><main id="studio"><div class="zc-image-tools"><button id="toggle"></button><button id="compare"></button></div><div class="zc-image-scroll"><div id="source"></div><div id="zc-gallery"></div><div id="zc-image-empty"></div></div><div id="zc-reference-list"><div class="zc-edit-main"><button>Main image</button><details class="zi-references"><summary>References</summary></details></div></div></main></body></html>');
globalThis.document=document;globalThis.window=window;
if(!globalThis.crypto?.randomUUID)globalThis.crypto={randomUUID:()=>String(Math.random())};
const root=document.querySelector('main'),main={filename:'original.png',subfolder:'zura_images/references',file:'zura_images/references/original.png',width:1920,height:1080};
const calls=[];let reply=null,area;
const owner={root,mode:'image',imageOperation:'edit',editMainMissing:false,references:[main],items:[],selectedImage:-1,draft:{},
  editInputs:{source:document.querySelector('#source'),toggle:document.querySelector('#toggle'),showSource:false},
  imageComparison:{button:document.querySelector('#compare'),host:document.createElement('div'),active:false},
  api:{apiURL:value=>value,fetchApi:async(url,options)=>{calls.push({url,options});return reply?reply():{ok:true,json:async()=>({name:'painted.png',subfolder:'zura_images/edit_areas'})};}},
  $(id){return root.querySelector('#zc-'+id);},save(){this.saved=area?.config();},render(){area?.sync();},message(value){this.messageText=value;}};
area=new ImageEditArea(owner);

const rail=document.createElement('div');rail.className='zpx-rail';root.append(rail);rail.append(area.tools);
const controls=[...area.tools.querySelectorAll('button,input')],context={$:key=>key==='brushes'?rail:null};
PlateSurface.prototype.syncImageTools.call(context);
assert.equal(area.tools.querySelectorAll('.zia-tool-group').length,3);assert.equal(area.tools.querySelectorAll('button').length,7);
for(const original of controls)assert.ok(area.tools.contains(original),'Original nodes and listeners must survive grouping');
for(const button of area.tools.querySelectorAll('button')){assert.ok(button.querySelector('svg'));assert.ok(button.getAttribute('aria-label'));assert.ok(button.title);}
assert.equal(area.tools.querySelector('[data-area-tool=brush]').getAttribute('aria-pressed'),'true');
const invoked=[];area.setTool=tool=>invoked.push(tool);for(const button of area.tools.querySelectorAll('[data-area-tool]'))button.click();assert.deepEqual(invoked,['draw','brush','protect','pan']);
area.viewer={undo(){invoked.push('undo');},clear(){invoked.push('clear');},fit(){invoked.push('fit');},setDrawColor(colour){invoked.push(colour);}};area.scheduleSave=()=>{};area.refreshTools=()=>{};
for(const button of area.tools.querySelectorAll('[data-area-action]'))button.click();assert.deepEqual(invoked.slice(-3),['undo','clear','fit']);
area.colour.value='#abcdef';area.colour.oninput();assert.equal(invoked.at(-1),'#abcdef');
PlateSurface.prototype.syncImageTools.call(context);assert.equal(area.tools.querySelectorAll('.zia-tool-group').length,3,'Repeated renders do not nest groups or duplicate controls');
area.host.querySelector('.zia-toolbar').prepend(area.tools);assert.equal(area.tools.querySelectorAll('button').length,7,'Leaving inline mode restores the entire grouped toolbar');
console.log('Inline image tool presentation: original nodes/callbacks, seven labelled icons, active selection, colour, grouped settings/history, idempotence and restored toolbar pass.');

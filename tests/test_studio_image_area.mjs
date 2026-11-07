import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {ImageEditArea,imageAreaSourceKey} from '../web/studio_image_area.js';

const {document,window}=parseHTML('<html><body><main id="studio"><div class="zc-image-tools"><button id="toggle"></button><button id="compare"></button></div><div class="zc-image-scroll"><div id="source"></div><div id="zc-gallery"></div><div id="zc-image-empty"></div></div></main></body></html>');
globalThis.document=document;globalThis.window=window;
if(!globalThis.crypto?.randomUUID)globalThis.crypto={randomUUID:()=>String(Math.random())};
const root=document.querySelector('main'),main={filename:'original.png',subfolder:'zura_images/references',file:'zura_images/references/original.png',width:1920,height:1080};
const calls=[];let reply=null,area;
const owner={root,mode:'image',imageOperation:'edit',editMainMissing:false,references:[main],draft:{},
  editInputs:{source:document.querySelector('#source'),toggle:document.querySelector('#toggle'),showSource:false},
  imageComparison:{button:document.querySelector('#compare'),host:document.createElement('div'),active:false},
  api:{apiURL:value=>value,fetchApi:async(url,options)=>{calls.push({url,options});return reply?reply():{ok:true,json:async()=>({name:'painted.png',subfolder:'zura_images/edit_areas'})};}},
  $(id){return root.querySelector('#zc-'+id);},save(){this.saved=area?.config();},render(){area?.sync();},message(value){this.messageText=value;}};
area=new ImageEditArea(owner);
let disposed=0;
const viewer=()=>({maskPresent:false,history:[1],root:document.createElement('div'),
  maskCanvas:{toBlob(callback){callback(new Blob(['mask'],{type:'image/png'}));}},
  measureMask(){return this.maskPresent;},setBrushSize(){},setTool(){},fit(){},undo(){this.history.pop();},clear(){this.maskPresent=false;area.changed();},dispose(){disposed++;}});
area.loadViewer=async()=>{area.viewer=viewer();area.loading.hidden=true;area.refreshTools();};

assert.equal(imageAreaSourceKey(main),'zura_images/references/original.png');
assert.equal(imageAreaSourceKey({subfolder:'folder',filename:'plate.png'}),'folder/plate.png');
area.sync();assert.equal(area.button.hidden,false);assert.equal(area.config(),null,'Whole-image editing is the default');
area.button.click();assert.equal(area.host.hidden,false);assert.equal(area.state.enabled,true);assert.equal(owner.editInputs.source.hidden,true);
await assert.rejects(()=>area.prepare(),/Paint an edit area or choose Whole image/);
assert.deepEqual(await area.flush(),area.config(),'Flushing an empty optional selection does not block navigation');

area.viewer.maskPresent=true;area.changed();clearTimeout(area.saveTimer);
assert.equal(owner.saved.mask,null,'A dirty selection never persists an older mask');
owner.submitting=true;
const first=await area.prepare();owner.submitting=false;
assert.equal(first.source_key,main.file);assert.equal(first.mask.file,'zura_images/edit_areas/painted.png');
assert.equal(calls.at(-1).url,'/upload/image');assert.equal(calls.at(-1).options.body.get('subfolder'),'zura_images/edit_areas');
first.mask.file='modified-in-caller';assert.equal(area.config().mask.file,'zura_images/edit_areas/painted.png','Prepared job owns an immutable snapshot');

area.setParameter('context',999,512);area.setParameter('feather',-4,128);
assert.equal(area.config().context,512);assert.equal(area.config().feather,0);
const saved=area.config();area.useWholeImage();assert.equal(area.config(),null);
area.restore(saved);area.sync();assert.equal(area.config().mask.file,saved.mask.file,'A handoff can restore the saved source-bound selection');
owner.imageOperation='create';assert.equal(area.config(),null,'Creation cannot consume an edit mask');owner.imageOperation='edit';area.sync();

// A late upload from a replaced main image must never attach to the new image.
area.button.click();area.viewer.maskPresent=true;area.changed();clearTimeout(area.saveTimer);
let release,started;const startedPromise=new Promise(resolve=>started=resolve);
reply=()=>{started();return new Promise(resolve=>release=resolve);};
const pending=area.flush();await startedPromise;
owner.references=[{...main,filename:'different.png',file:'zura_images/references/different.png'}];area.sync();
release({ok:true,json:async()=>({name:'late.png',subfolder:'zura_images/edit_areas'})});
await assert.rejects(pending,/changed while it was saving/);
assert.equal(area.state.source_key,owner.references[0].file);assert.equal(area.state.mask,null);assert.equal(area.config(),null);

// Closing retains the dirty canvas until the background upload has completed.
reply=()=>({ok:true,json:async()=>({name:'saved-on-close.png',subfolder:'zura_images/edit_areas'})});
area.button.click();area.viewer.maskPresent=true;area.changed();clearTimeout(area.saveTimer);
const before=disposed;area.close();await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(area.state.mask.filename,'saved-on-close.png');assert.ok(disposed>before);area.open();assert.equal(area.closed,false);
area.reset();clearTimeout(area.saveTimer);
console.log('Image edit area: optional selection, upload ownership, handoff, stale-source protection and close flush pass.');

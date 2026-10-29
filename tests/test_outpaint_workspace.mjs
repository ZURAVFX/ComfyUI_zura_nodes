import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {OutpaintWorkspace} from '../web/studio_outpaint.js';

const {document,window}=parseHTML('<html><body><div id="genj-studio"></div></body></html>');
globalThis.document=document;
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},set(value){for(const option of this.querySelectorAll('option'))option.selected=option.value===String(value);}});
for(const name of ['load','pause','play'])window.HTMLElement.prototype[name]=()=>{};
const calls=[];
const owner={root:document.querySelector('#genj-studio'),api:{apiURL:u=>u,addEventListener(){},removeEventListener(){}},show(){},
  async fetch(path,body){calls.push([path,body]);if(path==='/zura/studio/outpaint/review')return {id:'review',kind:'review',state:'queued'};
    if(path.endsWith('/review/approve'))return {id:'review',approved:true};
    if(path.endsWith('/review/render'))return {id:'render',kind:'render',state:'queued'};
    if(path.endsWith('/jobs/review'))return {id:'review',kind:'review',state:'complete',url:'/view?review=1'};
    if(path.endsWith('/jobs/render'))return {id:'render',kind:'render',state:'complete',url:'/view?render=1'};throw Error(path);}};
const ui=new OutpaintWorkspace(owner);
ui.source={id:'a'.repeat(32),width:768,height:432,duration:4};ui.reframe();ui.invalidate();ui.paint();
assert.equal(ui.$('review').disabled,false);assert.equal(ui.$('generate').hidden,true);
await ui.reviewSelection();await new Promise(r=>setTimeout(r,0));
assert.equal(ui.review.id,'review');assert.equal(ui.$('generate').hidden,false);assert.equal(ui.result.hidden,false);
await ui.generate();await new Promise(r=>setTimeout(r,0));
assert.equal(ui.review,null);assert.equal(ui.result.hidden,false);
assert.deepEqual(calls.slice(0,4).map(c=>c[0]),['/zura/studio/outpaint/review','/zura/studio/outpaint/jobs/review','/zura/studio/outpaint/jobs/review/approve','/zura/studio/outpaint/jobs/review/render']);
ui.review={id:'old'};ui.invalidate();assert.equal(ui.review,null,'changing source geometry invalidates review');
ui.$('mode').value='black';ui.reframe();assert.equal(Number(ui.$('width').value),768);assert.equal(Number(ui.$('height').value),432);
ui.dispose();console.log('Outpaint prototype requires review and approval before rendering, and invalidates stale selection.');

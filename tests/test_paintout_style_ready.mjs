import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';
import {PlateWorkspace} from '../web/studio_plate.js';
import {PaintoutStyleGate,paintoutStylesReady,stylesheetReady} from '../web/paintout_studio/style_ready.js';

const {document,window}=parseHTML('<html><head></head><body><main id="genj-studio" data-workspace="paintout"><div class="gs-workspace"></div></main></body></html>');
let styled=false;const frames=[];
window.requestAnimationFrame=callback=>frames.push(callback);
window.HTMLElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:styled?960:88,height:540,right:styled?960:88,bottom:540});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(value){this.toggleAttribute('checked',!!value);}});
window.HTMLElement.prototype.pause=()=>{};window.HTMLElement.prototype.load=()=>{};
window.HTMLCanvasElement.prototype.getContext=()=>new Proxy({},{get:()=>()=>{}});
const storage={getItem:()=>null,setItem(){},removeItem(){}};
Object.assign(globalThis,{document,window,innerWidth:1396,innerHeight:1046,localStorage:storage,ResizeObserver:class{observe(){}disconnect(){}}});
const owner={root:document.querySelector('main'),studio:{close(){}},app:{},storage,mode:'paintout',videoComposer:{syncWorkflow(){}},rippleImage:{request:null,importing:false},items:[],selectedImage:-1,references:[],models:[],
  api:{apiURL:path=>path,addEventListener(){},removeEventListener(){},fetchApi:async()=>({ok:true,json:async()=>({})})},
  fetch:async()=>({}),$(id){return document.querySelector('#zc-'+id)||{value:'',disabled:false};}};
const workspace=new PaintoutWorkspace(owner,{paintoutOnly:true});owner.paintout=workspace;workspace.modelInfo={};
const plate=new PlateWorkspace(owner);owner.plate=plate;plate.attach(workspace);
const gate=plate.surface.presentation;
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const links=doc=>[...doc.querySelectorAll('link[rel="stylesheet"]')];
const loaded=link=>link.dispatchEvent(new window.Event('load'));
try{
  assert.equal(workspace.page.style.visibility,'hidden','Real surface construction hides both new and legacy controls synchronously');
  assert.equal(workspace.editor.viewer.cssWidth,88,'The narrow pre-CSS measurement is reproduced internally');
  assert.ok(workspace.page.querySelector('.zplate-surface'));
  assert.equal(gate.status.isConnected,true);assert.equal(gate.status.hidden,false);
  const pending=links(document).find(link=>link.href.endsWith('/studio_plate_surface.css'));assert.ok(pending);
  for(const link of links(document))if(link!==pending)loaded(link);
  await settle();
  assert.equal(workspace.page.style.visibility,'hidden','Loading every other sheet cannot expose the incomplete surface');
  assert.equal(frames.length,0,'Layout flush is not scheduled until the last critical stylesheet loads');
  styled=true;loaded(pending);await settle();
  assert.equal(workspace.page.style.visibility,'hidden','The last load event still does not reveal before a layout frame');
  assert.equal(frames.length,1);frames.shift()();
  assert.equal(await plate.surface.presentationReady,true);
  assert.equal(workspace.editor.viewer.cssWidth,960,'The real canvas resize is repeated with final styled geometry before first reveal');
  assert.equal(workspace.page.style.visibility,'');assert.equal(gate.status.isConnected,false);
  assert.equal(workspace.page.hasAttribute('aria-busy'),false);
  const count=links(document).length;await paintoutStylesReady(document);assert.equal(links(document).length,count,'Warm entry reuses styles instead of appending duplicate links');
}finally{workspace.close();}

// Failure is visible and retryable without rebuilding the workspace or waiting
// for any media/model request. Successful sheets stay cached across the retry.
const failedDOM=parseHTML('<html><head></head><body><section><div>Editor controls</div></section></body></html>');
const page=failedDOM.document.querySelector('section');let measurements=0;
const retryGate=new PaintoutStyleGate(page,{beforeReveal:()=>measurements++});
const first=retryGate.show();const firstLinks=links(failedDOM.document);const bad=firstLinks.find(link=>link.href.endsWith('/studio_plate_surface.css'));
for(const link of firstLinks)if(link!==bad)loaded(link);
bad.dispatchEvent(new window.Event('error'));assert.equal(await first,false);
assert.equal(page.style.visibility,'hidden');assert.equal(retryGate.status.getAttribute('role'),'alert');assert.equal(retryGate.retry.hidden,false);assert.equal(measurements,0);
const retry=retryGate.show(),newLinks=links(failedDOM.document),replacement=newLinks.find(link=>link.href.endsWith('/studio_plate_surface.css'));
assert.notEqual(replacement,bad);assert.equal(newLinks.length,firstLinks.length,'Only the failed sheet is replaced');
page.hidden=true;loaded(replacement);await settle();assert.equal(frames.length,1);frames.shift()();assert.equal(await retry,true);
assert.equal(page.hidden,true,'A completed background load never navigates back to the editor');assert.equal(measurements,1);

const timeoutDOM=parseHTML('<html><head></head><body></body></html>');
await Promise.all([assert.rejects(stylesheetReady('https://fixture.invalid/never.css',timeoutDOM.document,{timeout:1}),/stylesheet/),new Promise(resolve=>setTimeout(resolve,5))]);
assert.equal(links(timeoutDOM.document).length,0,'A stalled load has a bounded failure and can be retried');
console.log('Paintout first-load presentation: delayed critical CSS, pre-reveal canvas geometry, warm cache, retryable failure, timeout and navigation preservation pass.');

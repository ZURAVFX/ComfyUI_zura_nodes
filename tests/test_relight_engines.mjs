import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {RippleWorkspace} from '../web/studio_ripple.js';
import {installRelightEngines} from '../web/studio_relight.js';
import {buildRippleStudioGraph} from '../web/studio_ripple_recipes.js';
const {document,window}=parseHTML('<html><head></head><body><main id="genj-studio"></main></body></html>');
for(const method of ['pause','play','load'])window.HTMLElement.prototype[method]=()=>{};
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(value){for(const option of this.querySelectorAll('option'))option.toggleAttribute('selected',option.value===String(value));}});
const memory=new Map();Object.assign(globalThis,{document,window,localStorage:{getItem:key=>memory.get(key)||null,setItem:(key,value)=>memory.set(key,value),removeItem:key=>memory.delete(key)}});
const asset={id:'shot-1',file:'shot.mp4',name:'Shot',width:1920,height:1080,duration:4};
const info={path:'C:/shots/shot.mp4',name:'Shot',kind:'video',width:1920,height:1080,frames:120,fps:30,resolved_colour:'srgb_display',media_url:'/source.mp4'};
const calls=[];let imports=0;
const owner={root:document.querySelector('main'),app:{},mode:'video',rippleWorkspaces:new Map(),api:{apiURL:path=>path,addEventListener(){},removeEventListener(){},async fetchApi(path,options){calls.push(path);if(path.includes('import-frame'))return{ok:true,json:async()=>({frame:Number(options.body.get('frame')),file:'C:/edits/light-'+(++imports)+'.png',colour_space:'srgb_display'})};return{ok:true,blob:async()=>new Blob(['image'],{type:'image/png'})};}},
 async fetch(path,body){calls.push(path);if(path.includes('/assets/'))return info;if(path==='/zura/paintout/editor/project')return{id:'project'};if(path.startsWith('/zura/paintout/info'))return info;if(path==='/zura/paintout/export-frame')return{url:'/lighting-export'};return{};},
 show(mode){this.mode=mode;for(const w of this.rippleWorkspaces.values())w.page.hidden=mode!=='ripple'||w!==this.ripple;},
 ensureRippleWorkspace(intent){intent=intent||this.ripple?.intent||'edit';if(!this.rippleWorkspaces.has(intent))this.rippleWorkspaces.set(intent,new RippleWorkspace(this,{intent}));this.ripple=this.rippleWorkspaces.get(intent);return this.ripple;},videoComposer:{syncWorkflow(){}},
 studio:{source:asset,readyAsset:{id:'light-1',url:'/lighting.png'},config:{workflow_mode:'relight',start:.5,duration:1.5,length_mode:'custom',image_prompt:'Warm afternoon light'},syncForm(){},render(){},invalidateLook(){this.project=null;},async upload(kind,file){assert.equal(kind,'ready');assert.ok(file instanceof File);this.readyAsset={id:'returned-light',url:'/returned.png'};}}};
installRelightEngines(owner);
const original=owner.ensureRippleWorkspace('edit');original.setSource(info);original.addAnchor(0);original.selected().file='C:/other.png';original.save();
await owner.selectRelightEngine('ltx');const lighting=owner.ripple;
assert.notEqual(lighting,original);assert.equal(lighting.intent,'relight');assert.equal(lighting.page.querySelector('h2').textContent,'Relight');assert.doesNotMatch(lighting.page.textContent,/Ripple/);
assert.deepEqual([...lighting.$('engine').querySelectorAll('option')].map(o=>o.value),['wan21','h3','ltx']);
assert.equal(lighting.config().sequenceFps,30);assert.equal(lighting.config().startFrame,15);assert.equal(lighting.config().frameCount,45);assert.equal(lighting.$('prompt').value,'Warm afternoon light');assert.equal(lighting.anchors().length,1);
lighting.$('engine').value='h3';lighting.$('engine').onchange();lighting.addAnchor(30);lighting.selected().file='C:/second-light.png';lighting.state.prompt='Cool blue evening';lighting.$('prompt').value=lighting.state.prompt;lighting.save();
const before=structuredClone(lighting.anchors());
await owner.selectRelightEngine('wan21');assert.equal(owner.mode,'video');assert.equal(owner.studio.source.id,'shot-1');assert.equal(owner.studio.readyAsset.id,'returned-light');assert.equal(owner.studio.config.image_prompt,'Cool blue evening');
await owner.selectRelightEngine('ltx');assert.equal(owner.ripple,lighting);assert.deepEqual(lighting.anchors(),before);assert.equal(lighting.config().anchors.length,1);assert.equal(lighting.config().anchors[0].frame,30,'LTX uses the selected lighting reference without discarding other edits');
lighting.$('engine').value='h3';lighting.$('engine').onchange();assert.equal(lighting.config().anchors.length,2);
for(const engine of ['h3','ltx']){lighting.state.engine=engine;const graph=buildRippleStudioGraph(lighting.config());assert.ok(Object.values(graph).some(n=>n.inputs.output_name==='ZURA STUDIO/relight'||n.inputs.filename_prefix==='ZURA STUDIO/relight'));}
assert.equal(original.anchors()[0].file,'C:/other.png');assert.ok(memory.has('zura-relight-workspace-v1'));assert.ok(memory.has('zura-ripple-workspace-v1'));
const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);assert.equal(new Set(ids).size,ids.length,'Separate drafts keep unique labelled controls');
const restored=new RippleWorkspace(owner,{intent:'relight'});assert.deepEqual(restored.anchors(),lighting.anchors());restored.dispose();
assert.ok(!calls.includes('/prompt'),'Switching models never generates anything');
lighting.state.engine='ltx';lighting.reset();assert.equal(lighting.state.engine,'ltx');assert.equal(original.anchors()[0].file,'C:/other.png');for(const w of owner.rippleWorkspaces.values())w.dispose();
console.log('Relight engine switching preserves source, FPS, trim, prompts and lighting frames; native Ripple graphs and independent drafts pass.');

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PaintoutWorkspace} from '../web/paintout_studio/studio_paintout.js';
import {PaintoutEditor} from '../web/paintout_studio/paintout_editor.js';
assert.ok(fs.existsSync(new URL('../web/vendor/elk.bundled.js',import.meta.url)), 'The native graph layout dependency exists at the integrated workspace import path');

const messages=[],events=[];
function workspace(source=''){
 const w=Object.create(PaintoutWorkspace.prototype),fields=new Map();
 Object.assign(w,{state:{source,anchors:[]},busy:()=>false,render(){},save(){},renderAnchors(){},changed(){},preview(){},message:text=>messages.push(text),requestError:e=>e.message,$:id=>{if(!fields.has(id))fields.set(id,{hidden:false,value:'',removeAttribute(){}});return fields.get(id);},pick:async kind=>{events.push('pick:'+kind);return [];}});
 const editor=Object.create(PaintoutEditor.prototype);
 Object.assign(editor,{w,viewer:{setTool:tool=>events.push('tool:'+tool)},setStage:async stage=>events.push('stage:'+stage),flushManual:async()=>events.push('flush'),ensureProject:async()=>{events.push('ensure');if(!w.state.source)throw Error('Add footage first.');},projectData:()=>({})});w.editor=editor;
 return w;
}
for(const kind of ['footage','sequence']){
 const w=workspace();messages.length=0;events.length=0;
 await w.pickSource(kind);
 assert.deepEqual(events,['flush','pick:'+kind],'An empty workspace reaches the picker without requiring an editor project');
 assert.deepEqual(messages,[]);assert.equal(w.picking,false);assert.equal(w.state.source,'');
}
const w=workspace();w.pick=async()=>['plate.mp4'];w.info=async()=>({frames:120,width:1920,height:1080});
await w.pickSource('footage');assert.equal(w.state.source,'plate.mp4');assert.equal(w.state.frameCount,81);assert.equal(w.state.editorProject,null);assert.equal(w.state.activeMaskSegment,null);assert.equal(w.state.maskSegmentDraft,null);assert.equal(w.state.editorStage,'mask');assert.deepEqual(events.slice(-2),['tool:include','stage:mask']);assert.deepEqual(messages,[]);
// Replacing footage must still save the old project before opening the picker.
const previous=workspace('old.mp4');events.length=0;
previous.fetch=async()=>({revision:2});previous.editor.project='old';previous.editor.projectSource='old.mp4';
await previous.pickSource('footage');assert.deepEqual(events,['flush','ensure','pick:footage']);assert.equal(previous.state.source,'old.mp4','Cancelling preserves the existing source');
previous.editor.flushManual=async()=>{throw Error('Could not save mask');};events.length=0;messages.length=0;
await previous.pickSource('footage');assert.deepEqual(events,[]);assert.deepEqual(messages,['Could not save mask'],'Failed saves still prevent replacement');

const {document}=parseHTML('<html><head></head><body></body></html>');let extension;const opened=[];
const code=fs.readFileSync(new URL('../web/studio_launchers.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replaceAll('import.meta.url',JSON.stringify(new URL('../web/studio_launchers.js',import.meta.url).href));
vm.runInNewContext(code,{document,URL,console,app:{registerExtension:e=>extension=e},openZuraStudio:()=>opened.push('zura'),openPaintout:()=>opened.push('paintout')});
extension.setup();extension.setup();assert.equal(document.querySelectorAll('#zura-studio-shortcuts').length,1,'Setup is idempotent');
const buttons=[...document.querySelectorAll('#zura-studio-shortcuts button')];assert.deepEqual(buttons.map(b=>b.textContent),['Zura Studio','Paintout Studio']);
for(const button of buttons)await button.onclick();assert.deepEqual(opened,['zura','paintout']);
assert.equal(document.querySelectorAll('link[href$="studio_launchers.css"]').length,1);
console.log('PASS: first footage/sequence import, cancellation, prior-project save and visible Studio shortcuts.');

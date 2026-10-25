import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';

const {document,window}=parseHTML('<html><head></head><body></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{
  configurable:true,get(){return this.querySelector('option[selected]')?.value ?? this.querySelector('option')?.value ?? '';},
  set(value){for(const option of this.querySelectorAll('option'))option.selected=option.value===String(value);},
});
let registrations=0,extension;
const context={document,app:{registerExtension(ext){registrations++;extension=ext;}},api:{apiURL:x=>x},URLSearchParams};
const source=fs.readFileSync(new URL('../web/paintout.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
vm.createContext(context);vm.runInContext(source,context);vm.runInContext(source,context);
assert.equal(registrations,1,'Duplicate legacy/integrated frontend imports must not add two panels.');
class Picker {
  constructor(){
    this.widgets=Object.entries({plate_path:'example.mov',mask_path:'mask.mp4',sequence_fps:25}).map(([name,value])=>({name,value,type:'number'}));
    this.properties={};this.graph={setDirtyCanvas(){}};this.onNodeCreated();
  }
  addDOMWidget(name,type,element){this.widgets.push({name,type,element});document.body.append(element);}
}
await extension.beforeRegisterNodeDef(Picker,{name:'ZuraPaintoutCrop'});
const node=new Picker();
const panel=()=>document.querySelector('.zp-panel');
const mode=()=>panel().querySelector('[aria-label="Footage input type"]');
const fps=()=>panel().querySelector('[aria-label="Sequence frame rate (fps)"]');
assert.equal(fps(),null);assert.match(panel().textContent,/read automatically/);
assert.equal(node.widgets.find(w=>w.name==='sequence_fps').type,'converted-widget');
mode().value='sequence';mode().onchange();
assert.equal(node.widgets.find(w=>w.name==='plate_path').value,'');
assert.ok(fps());assert.match(panel().textContent,/Choose sequence folder/);
fps().value='30';fps().onchange();
assert.equal(node.widgets.find(w=>w.name==='sequence_fps').value,30);
fps().value='0';fps().onchange();
assert.equal(node.widgets.find(w=>w.name==='sequence_fps').value,30);
mode().value='video';mode().onchange();assert.equal(fps(),null);
assert.equal(node.properties.zuraInputModes.plate_path,'video');
console.log('Paintout picker: modes, frame-rate binding, invalid values and duplicate-load guard passed.');

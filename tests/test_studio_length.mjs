import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {clipLength,recoverClipLength} from '../web/studio_length.js';
const original={engine:'h3',length_mode:'original',duration:2,start:0,edit_area:'scene',workflow_mode:'viewport'};
assert.equal(clipLength(original,15).invalid,true);
assert.equal(recoverClipLength(original,15).duration,5);
assert.equal(recoverClipLength({...original,engine:'local'},20).duration,15);
assert.equal(recoverClipLength({...original,engine:'local',workflow_mode:'motion'},20).duration,5);
assert.equal(recoverClipLength({...original,engine:'wan',audio_id:'speech',lip_sync:true},45).duration,30);
assert.equal(clipLength({...original,length_mode:'custom',duration:5},15).invalid,false);
// Execute the actual CTA handler without browser APIs or any Comfy queue.
const source=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').split('app.registerExtension({')[0];
const context={app:{registerExtension(){}},clipLength,recoverClipLength};
vm.createContext(context);vm.runInContext(source+'\nthis.Studio=ArtistStudio;',context);
const studio=Object.create(context.Studio.prototype),events=[];
Object.assign(studio,{busy:false,project:null,source:{duration:15},references:[],readConfig:()=>original,
  syncForm:()=>events.push('sync'),render:()=>events.push('render'),message:text=>events.push(text),
  $:()=>({scrollIntoView:()=>events.push('scroll'),focus:()=>events.push('focus'),select:()=>events.push('select')}),
  perform:()=>{throw new Error('Recovery must not create a project or queue a render');}});
await studio.primaryRecipe();
assert.equal(studio.config.length_mode,'custom');assert.equal(studio.config.duration,5);
assert.ok(events.includes('focus'));assert.ok(events.includes('select'));
studio.busy=true;events.length=0;await studio.primaryRecipe();assert.equal(events.length,0);
console.log('Invalid source length recovers to editable bounded custom length, even without a look, and never queues generation.');

context.Event=class{constructor(type,options){this.type=type;this.bubbles=options.bubbles;}};
const select={value:"custom",dispatchEvent:event=>events.push(event)};
studio.busy=false;studio.project=null;studio.$=()=>select;events.length=0;
studio.chooseClipLength("original");assert.equal(select.value,"original");assert.equal(events[0].type,"change");assert.equal(events[0].bubbles,true);
assert.equal(events.length,1);studio.chooseClipLength("original");assert.equal(events.length,1,"Already-selected button does not reconfigure the shot");
studio.project={phase:"working"};studio.chooseClipLength("custom");assert.equal(select.value,"original","A running render cannot change its interval");
studio.project=null;studio.chooseClipLength("custom");assert.equal(select.value,"custom");
studio.chooseClipLength("bad");assert.equal(select.value,"custom");
console.log("Visible Source/Custom buttons use the existing configuration change path and respect active runs.");

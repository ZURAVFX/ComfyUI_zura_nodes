import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {installPopoverDismissal} from '../web/studio_popovers.js';

const {document,window}=parseHTML(`<html><body><section id="studio">
  <details class="zc-tool-popup"><summary>Clip length</summary><div><input id="seconds"/></div></details>
  <details class="zc-tool-popup"><summary>Resolution</summary><div><input/></div></details>
  <div class="zc-viewer-tools"><details><summary>History</summary><div>Past shots</div></details></div>
  <div class="zf-heading"><details><summary>Frame history</summary><div>Past shots</div></details></div>
  <details class="zc-advanced"><summary>Persistent settings</summary><input/></details>
  <button id="canvas">Empty canvas</button>
</section><button id="outside">Outside Studio</button></body></html>`);
const root=document.querySelector('#studio');
const [length,resolution,history,frameHistory,persistent]=root.querySelectorAll('details');
const pointer=target=>{const event=new window.Event('pointerdown',{bubbles:true,cancelable:true});target.dispatchEvent(event);return event;};
let focused=null;for(const summary of root.querySelectorAll('summary'))summary.focus=()=>{focused=summary;};
let dispose=installPopoverDismissal(root);
length.open=true;persistent.open=true;
assert.equal(pointer(root.querySelector('#seconds')).defaultPrevented,false);
assert.equal(length.open,true,'Editing a field inside the popup keeps it open');
pointer(length.querySelector('summary'));
assert.equal(length.open,true,'The trigger remains available for native toggling');
let canvasClicks=0;root.querySelector('#canvas').addEventListener('pointerdown',()=>canvasClicks++);
pointer(root.querySelector('#canvas'));
assert.equal(length.open,false,'Clicking empty canvas dismisses the floating panel');
assert.equal(canvasClicks,1,'Light-dismiss never consumes the target action');
assert.equal(persistent.open,true,'Non-floating settings disclosures stay open');
length.open=true;resolution.open=true;
pointer(resolution.querySelector('input'));
assert.equal(length.open,false,'Another popup closes the previous one');
assert.equal(resolution.open,true);
pointer(document.querySelector('#outside'));
assert.equal(resolution.open,false,'A click outside Studio also dismisses its popup');
history.open=true;frameHistory.open=true;
const escape=new window.Event('keydown',{bubbles:true,cancelable:true});escape.key='Escape';
frameHistory.querySelector('summary').dispatchEvent(escape);
assert.equal(history.open,false);assert.equal(frameHistory.open,false);
assert.equal(focused,frameHistory.querySelector('summary'),'Escape returns keyboard focus to the popup trigger');
assert.equal(escape.defaultPrevented,true);
dispose();length.open=true;pointer(root.querySelector('#canvas'));
assert.equal(length.open,true,'Closing the workspace removes document listeners');
let lookups=0;const query=root.querySelectorAll.bind(root);root.querySelectorAll=selector=>{lookups++;return query(selector);};
const stale=installPopoverDismissal(root);dispose=installPopoverDismissal(root);stale();lookups=0;
pointer(root.querySelector('#canvas'));
assert.equal(lookups,1,'Repeated installation replaces rather than accumulates document listeners');
assert.equal(length.open,false);dispose();
console.log('Studio floating popover dismissal checks passed');

const menu=document.createElement('details');menu.className='zc-tool-popup';menu.innerHTML='<summary>Workflow</summary><div class="zc-workflow-menu"><button>A</button><button hidden>Hidden</button><button disabled>Unavailable</button><button>B</button></div>';root.append(menu);
const cleanup=installPopoverDismissal(root);let menuFocus;
for(const button of menu.querySelectorAll('button'))button.focus=()=>menuFocus=button.textContent;
const key=(target,value)=>{const event=new window.Event('keydown',{bubbles:true,cancelable:true});event.key=value;target.dispatchEvent(event);return event;};
length.open=true;menu.open=true;menu.dispatchEvent(new window.Event('toggle',{bubbles:true}));assert.equal(length.open,false,'Opening from a keyboard closes other floating menus');
key(menu.querySelector('summary'),'ArrowDown');assert.equal(menuFocus,'A');
key(menu.querySelector('button'),'ArrowDown');assert.equal(menuFocus,'B','Keyboard navigation skips unavailable or hidden choices');
key(menu.querySelector('button'),'End');assert.equal(menuFocus,'B');key(menu.querySelector('button'),'Home');assert.equal(menuFocus,'A');
cleanup();console.log('Workflow menu keyboard navigation and exclusive opening passed.');

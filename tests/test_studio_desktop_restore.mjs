import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {runStudioVMInContext} from './studio_vm_fixture.mjs';

const {document,window}=parseHTML('<html><body><div id="previous"><div id="gs-canvas"></div></div></body></html>');
const previous={container:document.getElementById('previous'),aeSession:null};let release=0;
const context={document,window,console,ContentDetection:class{},api:{fetchApi:async()=>{release++;return {ok:true};}},
 createStudioSession:async()=>({id:'a'.repeat(32),capability:'b'.repeat(64)}),studioLaunchStorage:()=>({}),
 StudioAEBridge:class{constructor(studio,api,session,onLeave){this.onLeave=onLeave;}dispose(){}message(){}},
 setTimeout,clearTimeout,setInterval,clearInterval,URL};
vm.createContext(context);
let source=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'').split('app.registerExtension({')[0];
runStudioVMInContext(source+`\nconst realClose=ArtistStudio.prototype.close;
class FakeStudio {constructor(options){this.aeSession=options.aeSession;this.container=document.createElement('section');this.container.innerHTML='<header class="gs-top"><img class="gs-zura-mark"></header><div id="gs-canvas"></div>';this.creative={show(){},open(){},close(){}};} $(name){return this.container.querySelector('#gs-'+name);} async open(){document.body.appendChild(this.container);} }
FakeStudio.prototype.close=realClose;ArtistStudio=FakeStudio;
this.testOpen=openDesktopAESession;this.setPrevious=value=>{registeredStudio=value;};this.current=()=>registeredStudio;`,context);
context.setPrevious(previous);
const credential={broker:'http://127.0.0.1:8199/studio-bridge/'+'d'.repeat(32),token:'c'.repeat(64)};
assert.equal(await context.testOpen(credential),true);const active=context.current();
assert.equal(previous.container.isConnected,false);assert.equal(active.container.isConnected,true);assert.ok(active.aeBridge);
active.close();assert.equal(context.current(),previous);assert.equal(previous.container.isConnected,true);
const before=previous.container.outerHTML;
assert.equal(await context.testOpen(credential,{isCurrent:()=>false}),false);assert.equal(release,1);
assert.equal(context.current(),previous);assert.equal(previous.container.outerHTML,before);
console.log('Desktop AE handoff parks and restores the normal Studio workspace and rejects late sessions');

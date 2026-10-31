import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the actual public entry without booting Comfy's frontend runtime.
const code=fs.readFileSync(new URL('../web/studio.js',import.meta.url),'utf8');
const start=code.indexOf('export async function openZuraStudio(');
const entry=code.slice(start,code.indexOf('\n}',start)+2).replace('export ','');
let opens=0;const modes=[];
const studio={container:{isConnected:false},async open(){opens++;this.container.isConnected=true;},creative:{show:mode=>modes.push(mode)}};
const context=vm.createContext({registeredStudio:studio});vm.runInContext(entry,context);
assert.equal(await context.openZuraStudio('paintout'),studio);
assert.deepEqual(modes,['paintout']);assert.equal(opens,1);
await context.openZuraStudio();assert.equal(opens,1,'Opening the connected shell must not reload the active project');
await context.openZuraStudio({command:'zura.studio.open'});
await context.openZuraStudio('unknown');assert.deepEqual(modes,['paintout'],'Command arguments cannot hide every workspace');
studio.container.isConnected=false;await context.openZuraStudio('paintout');assert.equal(opens,2);

let extension;const calls=[];
const paintoutEntry=fs.readFileSync(new URL('../web/paintout_studio/paintout_app.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace('export function','function');
vm.runInNewContext(paintoutEntry,{app:{registerExtension:value=>extension=value},openZuraStudio:mode=>calls.push(mode)});
extension.commands[0].function();assert.deepEqual(calls,['paintout'],'The Paintout command enters the main shell');
console.log('PASS unified shell entry, retained active project, close/reopen and safe Comfy command arguments.');

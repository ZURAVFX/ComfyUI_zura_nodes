import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {OutpaintLayers} from '../web/studio_outpaint_layers.js';
import {OutpaintWorkspace} from '../web/studio_outpaint.js';

const {document,window}=parseHTML('<html><body><div id="host"></div><div id="genj-studio"></div></body></html>');
globalThis.document=document;
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return this.querySelector('option[selected]')?.value??this.querySelector('option')?.value??'';},
  set(value){for(const option of this.querySelectorAll('option'))option.selected=option.value===String(value);}});
for(const name of ['load','pause','play'])window.HTMLElement.prototype[name]=()=>{};
const requests=[];let response={state:'running',completed:2,total:25},pending;
const fetch=async(path,body)=>{requests.push({path,body});return pending?await pending:response;};
const layers=new OutpaintLayers(document.querySelector('#host'),{fetch,apiURL:path=>'http://local'+path});
const result={id:'native-hdr',kind:'render',state:'complete',hdr:true,hdr_files:{exr:{filename:'frames.zip'}}};
for(const invalid of [{...result,kind:'review'},{...result,hdr:false},{...result,hdr_files:{}}]){
  layers.setResult(invalid);assert.equal(layers.root.hidden,true);
}
layers.setResult(result);assert.equal(layers.root.hidden,false);
assert.match(layers.root.textContent,/Original plate \+ generated border/);
let release;pending=new Promise(resolve=>{release=resolve;});
const first=layers.start();await layers.start();assert.equal(requests.length,1,'Double clicks cannot submit twice');
assert.equal(layers.busy,true);assert.equal(layers.$('start').disabled,true);
layers.close();release(response);await first;pending=null;
assert.match(layers.$('progress').textContent,/2 \/ 25 frames/);
assert.equal(layers.setResult(null),false,'An active export cannot lose its handle');
await layers.poll();assert.equal(requests.length,1,'Closed workspaces do not poll');
layers.resume();clearTimeout(layers.timer);
pending=new Promise(resolve=>{release=resolve;});const polling=layers.poll();await layers.poll();
assert.equal(requests.length,2,'Only one polling request may run at once');
response={state:'complete',completed:25,total:25,artifact:{type:'output',subfolder:'genj/hdr',filename:'hdr_outpaint_layers_native-hdr_layers.zip'}};
release(response);await polling;pending=null;
assert.equal(layers.busy,false);assert.equal(layers.$('download').hidden,false);
assert.match(layers.$('download').href,/\/view\?filename=hdr_outpaint_layers_native-hdr_layers.zip/);
assert.equal(requests.filter(r=>r.body).length,1,'Reopening resumes polling without resubmitting');
layers.setResult(null);assert.equal(layers.root.hidden,true);assert.equal(layers.$('download').hasAttribute('href'),false);
layers.setResult(result);response={state:'failed',error:'Disk full'};await layers.start();
assert.match(layers.$('progress').textContent,/Disk full/);assert.equal(layers.$('start').textContent,'Retry border layers');
layers.close();response={state:'running',completed:3,total:25};await layers.start();
response={state:'cancelled',completed:3,total:25};await layers.cancel();
assert.equal(requests.at(-1).path,'/zura/studio/outpaint/jobs/native-hdr/layers/cancel');
assert.equal(layers.busy,false);assert.match(layers.$('progress').textContent,/cancelled/);
layers.closed=false;layers.state={state:'running',completed:3,total:25};
pending=new Promise(resolve=>{release=resolve;});const stalePoll=layers.poll();pending=null;
await layers.cancel();release({state:'running',completed:4,total:25});await stalePoll;
assert.equal(layers.state.state,'cancelled','An older polling response cannot revive a cancelled export');
layers.state={state:'complete',artifact:{type:'output',subfolder:'genj/hdr',filename:'../bad_layers.zip'}};layers.render();
assert.equal(layers.$('download').hidden,true,'Unsafe artifact paths cannot become download links');
layers.dispose();

const owner={root:document.querySelector('#genj-studio'),api:{clientId:'test',apiURL:u=>u,addEventListener(){},removeEventListener(){}},show(){},fetch};
const ui=new OutpaintWorkspace(owner);ui.source={id:'source',file:'input.mov',width:640,height:360,duration:2};
ui.result.src='/finished.mp4';ui.$('download').href='/finished-hlg.mp4';ui.$('download').hidden=false;
ui.layers.setResult(result);ui.layers.close();response={state:'running',completed:4,total:25};await ui.layers.start();
assert.equal(ui.job,null,'Layer export never creates an inference job');
assert.equal(ui.$('width').disabled,true);assert.equal(ui.$('source').disabled,true);
assert.equal(ui.result.src,'/finished.mp4');assert.equal(ui.$('download').href,'/finished-hlg.mp4');
assert.equal(ui.invalidate(),false,'Geometry cannot invalidate an active export');
response={state:'cancelled',completed:4,total:25};await ui.layers.cancel();
assert.equal(ui.$('width').disabled,false);assert.equal(ui.invalidate(),true);
assert.equal(ui.layers.root.hidden,true);ui.dispose();
console.log('Native HDR border export eligibility, progress, cancellation, lifecycle and workspace guards pass.');

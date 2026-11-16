import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {StudioImageAreaDisplayBinding} from '../web/studio_display_binding.js';
import {createDisplayTransformStore} from '../web/studio_display_state.js';

const {document}=parseHTML('<html><body><main id="studio"><section id="area"><div id="viewer"></div></section></main></body></html>');
const store=createDisplayTransformStore({getItem:()=>null,setItem:()=>{}});
const first={config:'adobe-ae://fixture',display:'ACES',view:'P3D65 Rec.709 Limited'};
const second={config:'adobe-ae://fixture',display:'ACES',view:'Rec.709'};
store.registerCatalogue([first,second]);store.choose(first);
let requests=[],shown=[],cleared=0,serial=0;
URL.createObjectURL=()=>`blob:display-${++serial}`;URL.revokeObjectURL=()=>{};
const root=document.getElementById('studio'),host=document.getElementById('area');
const viewer={root:document.getElementById('viewer'),displaySourceURL:'/view?filename=source.png&type=input',
  async setColourDisplayImage(blobURL){shown.push(blobURL);return true;},clearColourDisplay(){cleared++;}};
const area={host,viewer,source:()=>({filename:'source.png',subfolder:'AE/shot',type:'input',colour_space:'srgb_display'})};
const settings={root,displayStore:store,owner:{imageArea:area},status:{textContent:''},
  api:{fetchApi:async(path,options)=>{requests.push({path,body:JSON.parse(options.body)});return {ok:true,blob:async()=>new Blob(['preview'])};}},
  response:async response=>{if(!response.ok)throw Error('Display transform unavailable');}};
const binding=new StudioImageAreaDisplayBinding(settings,area,viewer);
const flush=async()=>{await new Promise(resolve=>setTimeout(resolve,10));await new Promise(resolve=>setImmediate(resolve));};
await flush();
assert.equal(requests.length,1,'The ordinary dropdown applies to the Image Edit paint canvas');
assert.deepEqual(requests[0].body,{source:{file:{filename:'source.png',subfolder:'AE/shot',type:'input'}},frame:0,
  colour_space:'srgb_display',config:first.config,display:first.display,view:first.view});
assert.equal(shown.length,1);
store.choose(null);binding.refresh();assert.equal(shown.length,1);assert.ok(cleared>0,'None removes the display-only overlay');
store.choose(second);binding.refresh();await flush();assert.equal(requests.at(-1).body.view,second.view);
binding.close();assert.equal(viewer.onDisplaySourceChange,null);
console.log('Image Edit canvas uses the global display transform, None clears it, and source pixels remain separate');

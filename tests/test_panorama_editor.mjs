import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {openPanoramaEditor} from '../web/studio_panorama_editor.js';
const {document,window}=parseHTML('<html><body><main id="artist-workflow"></main></body></html>');
Object.assign(globalThis,{document,window,MutationObserver:window.MutationObserver});
const originalState=JSON.stringify({version:2,camera:{yaw:0}}),edited=JSON.stringify({version:2,camera:{yaw:22}});
let native,graphCleared=0;
class Graph{
  add(n){n.graph=this;}
  clear(){graphCleared++;}
}
const app={graph:new Graph(),nodeOutputs:{existing:{images:['retained']}},ui:{settings:{getSettingValue:()=>true}},
  createNode(type){
    if(type==='ZuraPanoramaLoadGeometry')return {widgets:[{name:'cache_key'}],connect(){return {};}};
    native={id:'old',inputs:[{name:'world'}],widgets:[{name:'state_json'}]};
    native.widgets.push({name:'Open Studio Editor',callback:async()=>{
      const backdrop=document.createElement('div');backdrop.className='pano-studio-backdrop';document.body.append(backdrop);
      backdrop.innerHTML='<div class="pano-studio-main"><div class="pano-studio-tabs"><button data-value="camera"></button></div><div data-head="camera"><button data-part="name"></button></div><span class="pano-studio-tl-frame">0 / 48</span></div>';
      return {session:{state:{camera:{}},applyInspector(){}},stage:()=>({settle(){},redraw(){}}),close(){native.widgets[0].value=edited;backdrop.remove();}};
    }});
    return native;
  }};
let applied=null,cancelled=0;
const args={app,state:originalState,geometryKey:'cached-key',output:{pano_timeline_frames:[48]},onApply:state=>{applied=state;},onCancel:()=>cancelled++};
const first=await openPanoramaEditor(args);
assert.equal(native.graph===app.graph,false,'Native camera nodes must not replace the artist graph');
assert.equal(document.querySelector('[data-apply]').textContent,'Apply camera');
assert.equal(document.querySelector('[data-key-camera]').textContent,'Set camera keyframe');
assert.ok(document.querySelector('.zc-camera-only'));
document.querySelector('[data-cancel]').click();
assert.equal(applied,null);assert.equal(cancelled,1);assert.equal(native.widgets[0].value,originalState);
assert.deepEqual(app.nodeOutputs,{existing:{images:['retained']}});
assert.equal(document.querySelector('.zc-panorama-actions'),null);
assert.equal(document.querySelector('.zc-camera-toolbar'),null);
assert.equal(document.querySelector('#artist-workflow')!==null,true);
first.cancel();assert.equal(cancelled,1,'Cancelling twice is harmless');
await openPanoramaEditor(args);
document.querySelector('[data-apply]').click();await Promise.resolve();
assert.equal(applied,edited,'Apply flushes the actual native editor state');
assert.equal(graphCleared,2);
assert.deepEqual(app.nodeOutputs,{existing:{images:['retained']}});
applied=null;await openPanoramaEditor(args);
document.querySelector('.pano-studio-backdrop').remove();
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(applied,null,'Native close without Apply must never change the project');
assert.equal(cancelled,2);
console.log('Panorama popout Apply/Cancel, native-close rollback and artist-graph isolation pass.');

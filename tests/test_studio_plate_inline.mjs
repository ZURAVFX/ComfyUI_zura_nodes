import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {PlateInlineEditor} from '../web/studio_plate_inline.js';
import {BrushSizeControl} from '../web/studio_brush_size.js';
import {PlateWorkspace} from '../web/studio_plate.js';

const {document}=parseHTML('<html><head></head><body><div id="root"><div class="zpx-header"></div><div data-plate-view></div><div data-plate-brushes></div><div data-plate-account></div><div data-plate-image-settings-body></div><div data-plate-layers><div id="old-layers"></div></div><div class="zpx-stage"></div><div id="workspace"><div class="zf-viewer"></div><div class="zf-composer"></div></div><div id="image-home"><div class="zc-image-composer"></div><div id="source"></div><div id="gallery"></div><div id="comparison"></div><div id="area"><div id="tools"><button data-area-tool="draw">Draw</button><button data-area-tool="brush">Area</button><button data-area-tool="protect">Erase</button><button data-area-tool="pan">Pan</button><label class="zia-brush"><input type="range" value="96"><output>96 px</output></label><label><input type="color" value="#000000"></label></div></div><div id="image-layers"></div><div id="zc-progress"></div><div class="zc-image-settings"></div></div></div></body></html>');
const q=selector=>document.querySelector(selector),events=[];
const area={host:q('#area'),tools:q('#tools'),brush:q('input[type=range]'),brushOutput:q('output'),colour:q('input[type=color]'),brushSize:96,editing:true,
  setPaintAPlateMode:on=>events.push(['mode',on]),setTool:tool=>events.push(['tool',tool]),applyBrushSize(){events.push(['size',this.brushSize]);},scheduleSave(){},refreshTools(){},viewer:{image:{},resize(){events.push(['resize']);},redo(){events.push(['redo']);}}};
area.colour.oninput=()=>events.push(['colour',area.colour.value]);
area.brush.addEventListener('input',()=>{area.brushSize=Number(area.brush.value);area.applyBrushSize();});
area.brushControl=new BrushSizeControl(area.brush);
area.paintPalette=document.createElement('div');area.paintPalette.className='pap-swatches';const red=document.createElement('button');red.setAttribute('aria-label','Red paint');red.onclick=()=>{area.colour.value='#d32f2f';area.colour.oninput();};area.paintPalette.append(red);area.host.append(area.paintPalette);

const owner={root:q('#root'),imageArea:area,editInputs:{source:q('#source')},imageComparison:{host:q('#comparison')},imageLayers:{host:q('#image-layers')},$:key=>q('#'+(key==='progress'?'zc-progress':key))};
const workspace={page:q('#workspace'),editor:{layersPanel:q('#old-layers')}};
const surface={root:q('#root'),o:owner,w:workspace,plate:{action:'paint'},$:key=>q('[data-plate-'+key+']')};
const original=new Map([area.host,area.tools,owner.editInputs.source,owner.imageLayers.host,owner.$('gallery')].map(node=>[node,node.parentElement]));
const editor=new PlateInlineEditor(surface),record=editor.mount();
assert.equal(editor.mount(),record,'Repeated sync retains one inline editor');
assert.equal(q('.zf-viewer').hidden,true,'Source video is hidden while the image canvas owns the view');
assert.equal(area.host.parentElement,record.host);assert.equal(area.tools.parentElement,surface.$('brushes'));
assert.equal(owner.imageLayers.host.parentElement,surface.$('layers'));
area.tools.querySelector('[data-area-tool=light]').onclick();assert.deepEqual(events.at(-1),['tool','light']);
area.tools.querySelector('[data-area-action=redo]').onclick();assert.deepEqual(events.at(-1),['redo']);
area.tools.querySelector('.pap-swatches button[aria-label="Red paint"]').onclick();assert.deepEqual(events.at(-1),['colour','#d32f2f']);
editor.brushNumber.value='144';editor.brushNumber.oninput();assert.equal(area.brushSize,144);
assert.equal(record.host.classList.contains('is-painting'),true);
const resizeCount=events.filter(([event])=>event==='resize').length;editor.sync();editor.sync();
assert.equal(events.filter(([event])=>event==='resize').length,resizeCount,'Routine UI updates must not reset the active canvas');
area.viewer.image=null;editor.sync();assert.equal(q('.zf-viewer').hidden,false,'A failed or pending frame load keeps the shot visible');assert.equal(record.host.hidden,true);
area.viewer.image={};editor.sync();assert.equal(q('.zf-viewer').hidden,true,'The paint canvas takes over only after its image exists');
area.editing=false;editor.sync();assert.equal(record.host.classList.contains('is-painting'),false);
editor.restore();assert.equal(q('.zf-viewer').hidden,false);assert.equal(q('.zplate-inline-image'),null);
for(const [node,parent]of original)assert.equal(node.parentElement,parent,'Unmount restores every real controller node');
assert.deepEqual(events.at(-1),['mode',false]);
editor.mount();editor.restore();assert.equal(q('.zplate-inline-image'),null,'Reopening does not leave a second viewer');
console.log('Add canvas: one DOM owner, Paint/Light tools, swatches, numeric size and complete restore pass.');

{
  const request={},calls=[],messages=[],plate={action:'paint',propagation(){return this.action!=='remove';},owner:{rippleImage:{request,async useResult(){calls.push('accept image');await Promise.resolve();this.request=null;}}},primary:{busy:()=>false,message:message=>messages.push(message)},active:()=>true,async generate(){calls.push('render video');}};
  const running=PlateWorkspace.prototype.usePaintResult.call(plate,request);
  await PlateWorkspace.prototype.usePaintResult.call(plate,request);await running;
  assert.deepEqual(calls,['accept image'],'Saving a frame edit commits the frame without auto-starting video generation');
  assert.deepEqual(messages,['Frame edit saved. Review the frame, add another edit, or choose Generate video.']);
  plate.action='replace';plate.owner.rippleImage.request=request;
  await PlateWorkspace.prototype.usePaintResult.call(plate,request);
  assert.deepEqual(calls,['accept image','accept image'],'Replace mode uses the same explicit frame-save flow as Add mode');
}

{
  const calls=[],plate={inline:{},primary:{message(){},render(){calls.push('render shot');}},owner:{rippleImage:{imageBusy:()=>false,importing:false,leave:()=>new Promise(()=>{}),clear(){calls.push('clear handoff');}},show:mode=>calls.push(mode)},exitInlineImage(){this.inline=null;calls.push('restore canvas');}};
  await PlateWorkspace.prototype.backToShot.call(plate,5);
  assert.equal(plate.inline,null);assert.deepEqual(calls,['clear handoff','restore canvas','paintout','render shot'],'A stuck frame editor cannot trap Back to shot');
}

import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {VideoComposer, VIDEO_WORKFLOWS} from '../web/studio_composer.js';
import {installStudioRestartNavigation, resetStudioWorkspace, studioWorkspaceBusy} from '../web/studio_restart.js';

const {document}=parseHTML('<!doctype html><html><head></head><body></body></html>');
Object.defineProperty(document.defaultView.HTMLSelectElement.prototype,'value',{
  configurable:true,
  get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},
  set(value){this.querySelectorAll('option').forEach(option=>option.toggleAttribute('selected',option.value===String(value)));},
});
Object.assign(globalThis,{document,window:document.defaultView});
const root=document.createElement('div');root.id='genj-studio';document.body.append(root);
const video=document.createElement('section');video.innerHTML='<div class="model"></div><div class="gs-preview-heading"></div>';root.append(video);
const page=document.createElement('section');page.innerHTML='<header class="zru-heading"></header><div class="zru-tools"><label class="zru-model"><select><option>H3</option><option>LTX</option></select></label></div>';root.append(page);
const task=document.createElement('details');
task.innerHTML=`<summary><span data-workflow-label></span></summary><select>${VIDEO_WORKFLOWS.map(([id,label])=>`<option value="${id}">${label}</option>`).join('')}</select><div>${VIDEO_WORKFLOWS.map(([id,label])=>`<button data-workflow="${id}">${label}</button>`).join('')}</div>`;
let showCalls=[];
const workspace={mode:'video',ripple:{page,async reset(){this.resets=(this.resets||0)+1;return this.resetResult??true;},busy(){return !!this.job;}},show(mode){this.mode=mode;showCalls.push(mode);}};
const studio={container:root,config:{workflow_mode:'motion'},creative:workspace,$(){return null;},render(){}};workspace.studio=studio;workspace.root=root;
const composer=Object.assign(Object.create(VideoComposer.prototype),{root,workspace,studio,task,model:video.querySelector('.model')});
assert.equal(VIDEO_WORKFLOWS.filter(([id])=>id==='ripple').length,1,'Ripple appears exactly once in the mode picker');
composer.selectWorkflow('ripple');assert.equal(workspace.mode,'ripple');
composer.mountWorkflow('ripple');
assert.equal(page.querySelector('.zru-model').nextElementSibling,task,'Mode selector stays immediately after the model');
assert.equal(task.querySelector('select').value,'ripple');
assert.equal(task.querySelector('[data-workflow-label]').textContent,'Ripple editing');
assert.equal(task.querySelector('[data-workflow="ripple"]').getAttribute('aria-checked'),'true');
composer.selectWorkflow('objects');assert.equal(workspace.mode,'ripple','Legacy object mode opens dedicated Ripple');
workspace.mode='video';composer.mountWorkflow('video');assert.equal(video.querySelector('.model').nextElementSibling,task,'The same mode picker returns to the video composer');
workspace.mode='ripple';assert.equal(studioWorkspaceBusy(workspace),false);
workspace.ripple.job={id:'run'};assert.equal(studioWorkspaceBusy(workspace),true,'An active Ripple run guards reset');
workspace.ripple.job=null;assert.equal(await resetStudioWorkspace(workspace),true);assert.equal(workspace.ripple.resets,1);assert.equal(showCalls.at(-1),'ripple');
workspace.ripple.resetResult=false;assert.equal(await resetStudioWorkspace(workspace),false,'A rejected reset is not reported as successful');
const controller=installStudioRestartNavigation(studio);controller.sync();
assert.equal(controller.button.parentElement.parentElement,page.querySelector('.zru-heading'),'Start over is placed in the Ripple workspace heading');
controller.dispose();
console.log('Ripple navigation and guarded restart work with the shared video workflow picker.');

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
task.innerHTML=`<summary><span class="zc-mode-current-icon"></span><span data-workflow-label></span></summary><select>${VIDEO_WORKFLOWS.map(([id,label])=>`<option value="${id}">${label}</option>`).join('')}</select><div>${VIDEO_WORKFLOWS.map(([id,label])=>`<button data-workflow="${id}">${label}</button>`).join('')}</div>`;
const header=document.createElement('header');header.className='gs-top';root.prepend(header);const host=document.createElement('div');host.className='zc-mode-host';header.append(host);host.append(task);
let showCalls=[];
const workspace={mode:'video',ripple:{page,async reset(){this.resets=(this.resets||0)+1;return this.resetResult??true;},busy(){return !!this.job;}},show(mode){this.mode=mode;showCalls.push(mode);}};
const studio={container:root,config:{workflow_mode:'motion'},creative:workspace,$(){return null;},render(){}};workspace.studio=studio;workspace.root=root;
const composer=Object.assign(Object.create(VideoComposer.prototype),{root,workspace,studio,task,model:video.querySelector('.model')});
assert.equal(VIDEO_WORKFLOWS.filter(([id])=>id==='ripple').length,1,'Ripple appears exactly once in the mode picker');
assert.equal(VIDEO_WORKFLOWS.some(([id])=>id==='inpaint'),false,'The duplicate Inpaint preview is not offered as a second edited-frame workflow');
composer.selectWorkflow('ripple');assert.equal(workspace.mode,'ripple');
composer.mountWorkflow('ripple');
assert.equal(task.parentElement,host,'Mode selector stays in workspace navigation');
assert.equal(task.querySelector('select').value,'ripple');
assert.equal(task.querySelector('[data-workflow-label]').textContent,'Ripple editing');
assert.equal(task.querySelector('[data-workflow="ripple"]').getAttribute('aria-checked'),'true');
composer.selectWorkflow('objects');assert.equal(workspace.mode,'ripple','Legacy object mode opens dedicated Ripple');
const legacyDraft={mode:'inpaint',source:'legacy-shot.mp4',anchors:[{frame:12,file:'legacy-edit.png'}]};
workspace.paintout={state:legacyDraft};
workspace.ripple.source={path:'ripple-shot.mp4'};workspace.ripple.anchors=[{frame:24,file:'ripple-edit.png'}];
const retained=JSON.stringify({legacyDraft,source:workspace.ripple.source,anchors:workspace.ripple.anchors});
workspace.mode='paintout';composer.syncWorkflow();
assert.equal(task.querySelector('select').value,'paintout','A restored legacy Inpaint draft retains a valid mode selector');
assert.equal(task.querySelector('[data-workflow-label]').textContent,'Paintout / clean plate');
assert.equal(task.querySelector('[data-workflow="paintout"]').getAttribute('aria-checked'),'true');
composer.selectWorkflow('inpaint');assert.equal(workspace.mode,'ripple','Legacy Inpaint navigation opens the shared edited-frame timeline');
assert.equal(JSON.stringify({legacyDraft,source:workspace.ripple.source,anchors:workspace.ripple.anchors}),retained,'Opening the consolidated route does not rewrite either saved project');
workspace.mode='video';composer.mountWorkflow('video');assert.equal(task.parentElement,host,'The same mode picker stays in navigation when changing modes');
workspace.mode='ripple';assert.equal(studioWorkspaceBusy(workspace),false);
workspace.ripple.job={id:'run'};assert.equal(studioWorkspaceBusy(workspace),true,'An active Ripple run guards reset');
workspace.ripple.job=null;assert.equal(await resetStudioWorkspace(workspace),true);assert.equal(workspace.ripple.resets,1);assert.equal(showCalls.at(-1),'ripple');
workspace.ripple.resetResult=false;assert.equal(await resetStudioWorkspace(workspace),false,'A rejected reset is not reported as successful');
const controller=installStudioRestartNavigation(studio);controller.sync();
assert.equal(controller.button.parentElement.parentElement,page.querySelector('.zru-heading'),'Start over is placed in the Ripple workspace heading');
controller.dispose();
console.log('Ripple navigation and guarded restart work with the shared video workflow picker.');

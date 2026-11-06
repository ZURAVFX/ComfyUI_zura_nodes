import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {VideoComposer} from '../web/studio_composer.js';

const {document,window}=parseHTML(`<html><body><div id="studio"><input name="gs-look" value="ready" type="radio"/><details id="models"><summary></summary><select><option value="flux3">Flux 3</option><option value="klein9b">Klein</option><option value="qwen2511">Qwen</option></select><span data-opening-model-label></span><button data-opening-model="flux3"></button><button data-opening-model="klein9b"></button><button data-opening-model="qwen2511"></button><p data-opening-status></p><button data-use-finished-image></button></details></div></body></html>`);
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||'';},set(v){for(const option of this.querySelectorAll('option'))option.selected=option.value===v;}});
const composer=Object.create(VideoComposer.prototype);
composer.root=document.querySelector('#studio');composer.imageModel=document.querySelector('#models');
composer.studio={config:{opening_model:'klein9b'},lookMode:'build',modelStatus:{opening_models:{klein9b:{ready:true},qwen2511:{ready:false}}}};
composer.syncOpeningModel(false);
assert.equal(composer.imageModel.querySelector('[data-opening-model-label]').textContent,'FLUX Klein 9B');
assert.equal(composer.imageModel.querySelector('[data-opening-model="qwen2511"]').disabled,false,'Missing models remain selectable so their installation can be offered');
assert.equal(composer.imageModel.querySelector('[data-opening-model="klein9b"]').disabled,false);
assert.equal(composer.imageModel.querySelector('[data-opening-status]').hidden,false);
composer.studio.modelStatus.opening_models.qwen2511.ready=true;
composer.studio.config.opening_model='qwen2511';composer.syncOpeningModel(false);
assert.equal(composer.imageModel.querySelector('[data-opening-model-label]').textContent,'Qwen Image Edit 2511');
assert.equal(composer.imageModel.querySelector('[data-opening-model="qwen2511"]').getAttribute('aria-checked'),'true');
assert.equal(composer.imageModel.querySelector('[data-opening-status]').hidden,true);
composer.studio.lookMode='ready';composer.syncOpeningModel(false);
assert.equal(composer.imageModel.querySelector('[data-opening-model-label]').textContent,'Finished image');
assert.equal(composer.imageModel.querySelector('[data-use-finished-image]').getAttribute('aria-checked'),'true');
assert.equal(composer.imageModel.querySelector('[data-opening-model="qwen2511"]').getAttribute('aria-checked'),'false');
composer.imageModel.open=true;composer.syncOpeningModel(true);
assert.equal(composer.imageModel.open,false,'Rendering closes the model picker');
for(const button of composer.imageModel.querySelectorAll('button'))assert.equal(button.disabled,true);
console.log('Starting image generator menu preserves selected model, finished-image choice, independent readiness and render locking.');

composer.studio.modelStatus.opening_models.flux3={ready:true};composer.studio.config.opening_model='flux3';composer.studio.lookMode='build';composer.syncOpeningModel(false);
assert.equal(composer.imageModel.querySelector('[data-opening-model-label]').textContent,'Flux 3 Klein');assert.equal(composer.imageModel.querySelector('[data-opening-model="flux3"]').disabled,false);
delete composer.studio.modelStatus.opening_models.flux3;composer.syncOpeningModel(false);assert.equal(composer.imageModel.querySelector('[data-opening-model="flux3"]').disabled,true,'Older backends must restart before a newly added recipe can be selected');

for(const provider of ['chatgpt','gemini']){
  const option=document.createElement('option');option.value=provider;composer.imageModel.querySelector('select').append(option);
  const button=document.createElement('button');button.dataset.openingModel=provider;composer.imageModel.append(button);
  composer.studio.modelStatus.opening_models[provider]={ready:true,provider};
  composer.studio.config.opening_model=provider;composer.syncOpeningModel(false);
  assert.match(composer.imageModel.querySelector('[data-opening-model-label]').textContent,/browser sign-in/);
  assert.equal(button.disabled,false,'Browser images do not depend on local diffusion model readiness');
  assert.equal(button.getAttribute('aria-checked'),'true');
  assert.match(button.title,/no API credits/);
}
console.log('ChatGPT and Gemini starting-frame choices retain browser labels and independent availability.');

{
  const option=document.createElement('option');option.value='ph3';composer.imageModel.querySelector('select').append(option);
  const button=document.createElement('button');button.dataset.openingModel='ph3';composer.imageModel.append(button);
  composer.studio.modelStatus.opening_models.ph3={ready:true,max_references:7};
  composer.studio.config.opening_model='ph3';composer.studio.lookMode='build';composer.syncOpeningModel(false);
  assert.equal(composer.imageModel.querySelector('[data-opening-model-label]').textContent,'P-H3 Image');
  assert.equal(button.disabled,false);
  assert.equal(button.getAttribute('aria-checked'),'true');
  composer.studio.config.workflow_mode='camera';composer.syncOpeningModel(false);
  assert.equal(composer.imageModel.querySelector('[data-opening-model-label]').textContent,'Flux 3 Klein');
  assert.equal(button.hidden,true,'Camera does not promise unsupported local starting-image recipes');
  composer.studio.config.workflow_mode='relight';composer.syncOpeningModel(false);
  assert.equal(button.hidden,false,'P-H3 remains available in supported video workflows');
}

composer.studio.modelStatus.opening_models.qwen2511.ready=false;composer.syncOpeningModel(false);assert.equal(composer.imageModel.querySelector('[data-opening-model="qwen2511"] [data-setup-needed]').hidden,false);

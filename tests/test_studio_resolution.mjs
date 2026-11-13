import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {editableDimension,VideoResolutionControl,megapixelSlider} from '../web/studio_resolution.js';
import {ENDPOINT_RECIPES,endpointPresetSize} from '../web/video_recipe_catalog.js';
const {document,window}=parseHTML('<html><body><section id="panel"></section><select id="native"><option value="1280">720p</option><option value="1920">1080p</option></select><input id="number" value="640"/></body></html>');
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value||'';},set(v){for(const o of this.querySelectorAll('option'))o.toggleAttribute('selected',o.value===String(v));}});
Object.assign(globalThis,{document,window});
let commits=0,selected=0;
const number=document.querySelector('#number');number.select=()=>selected++;
editableDimension(number,()=>commits++);
number.dispatchEvent(new window.Event('focus'));assert.equal(selected,1,'Focusing selects the complete number');
number.value='';number.dispatchEvent(new window.Event('input',{bubbles:true}));assert.equal(number.value,'','Clearing is allowed while typing');assert.equal(commits,0);
number.value='12';number.dispatchEvent(new window.Event('input',{bubbles:true}));assert.equal(number.value,'12','Partial values do not snap while typing');
number.value='721';assert.equal(number.commitDimension(),true);assert.equal(number.value,'736');assert.equal(commits,1);
number.value='1e3';assert.equal(number.commitDimension(),false);assert.equal(commits,1);
const studio={config:{workflow_mode:'relight',engine:'h3',opening_model:'klein9b',resolution:1280},modelStatus:{opening_max_pixels:4e6},source:{width:1920,height:1080},composerStage:()=>stage,$:()=>document.querySelector('#native')};
let stage='image';const panel=document.querySelector('#panel'),control=new VideoResolutionControl(studio,panel);control.sync();
const field=id=>panel.querySelector('#zvr-'+id);
assert.deepEqual([studio.config.opening_width,studio.config.opening_height],[1920,1088],'Starting edits stretch up to the model grid without reducing the source');
assert.equal(field('shape').value,'source_size');assert.equal(field('mp-setting').hidden,true);assert.match(field('hint').textContent,/restored to 1920 × 1080/);
studio.source={width:3840,height:2160};control.sync();assert.deepEqual([studio.config.opening_width,studio.config.opening_height],[3840,2160],'A supported 4K source keeps its exact raster');
studio.source={width:1921,height:1081};control.sync();assert.deepEqual([studio.config.opening_width,studio.config.opening_height],[1936,1088],'Every source axis only moves outwards to the nearest grid');
assert.equal(Number(field('mp').max),8.35);assert.match(field('hint').textContent,/restored to 1921 × 1081/);
studio.modelStatus={opening_models:{klein9b:{raster_limits:{size_step:16,max_dimension:8192,max_pixels:8_388_608}}}};control.sync();
const imageWidth=studio.config.opening_width;stage='video';control.sync();assert.match(field('dimensions').textContent,/1280 × 720/,'Existing relight default matches its graph');
field('shape').value='portrait';field('shape').onchange();assert.ok(studio.config.relight_height>studio.config.relight_width);assert.equal(studio.config.opening_width,imageWidth,'Image and video sizes stay independent');
field('shape').value='custom';field('shape').onchange();field('width').value='720';field('height').value='1280';field('width').commitDimension();assert.equal(studio.config.relight_width,720);assert.equal(studio.config.relight_height,1280);
studio.source={width:1920,height:1088};control.sync();field('shape').value='source_size';field('shape').onchange();
assert.equal(studio.config.relight_width,1920);assert.equal(studio.config.relight_height,1088);assert.match(field('hint').textContent,/Output matches the source/);assert.equal(field('mp-setting').hidden,true);
studio.source={width:1920,height:1080};control.sync();assert.equal(studio.config.relight_width,1920);assert.equal(studio.config.relight_height,1088);assert.match(field('hint').textContent,/Generated at 1920 × 1088/);assert.match(field('dimensions').textContent,/1920 × 1080/);
studio.source={width:3840,height:2160};control.sync();assert.deepEqual([studio.config.relight_width,studio.config.relight_height],[1920,1088]);assert.match(field('hint').textContent,/without reducing the source/,'A capped video model refuses a source rather than silently shrinking it');
field('shape').value='source';field('shape').onchange();assert.equal(field('mp-setting').hidden,false,'Source proportions still offers a megapixel slider');
studio.busy=true;control.sync();assert.equal(field('mp').disabled,true);assert.equal(field('width').disabled,true);
studio.busy=false;studio.config.workflow_mode='camera';studio.config.camera_width=768;studio.config.camera_height=448;studio.source={width:1080,height:1920};stage='image';control.sync();
assert.equal(field('shape').disabled,false);assert.equal(field('mp').disabled,false);
field('shape').value='source_size';field('shape').onchange();
assert.deepEqual([studio.config.camera_width,studio.config.camera_height],[768,448]);
assert.match(field('hint').textContent,/without reducing the source/,'Camera input must not silently downscale a portrait source');
studio.config.workflow_mode='relight';studio.config.relight_engine='wan21';studio.modelStatus.wan21_relight_max_pixels=8_388_608;studio.source={width:3840,height:2160};stage='video';control.sync();assert.equal(Number(field('mp').max),8.35);field('shape').value='source_size';field('shape').onchange();assert.equal(studio.config.relight_width,3840);assert.equal(studio.config.relight_height,2160);assert.match(field('hint').textContent,/more memory/);studio.config.workflow_mode='camera';studio.source={width:1080,height:1920};stage='image';control.sync();
const cameraSize=[studio.config.camera_width,studio.config.camera_height];stage='video';control.sync();
assert.deepEqual([studio.config.camera_width,studio.config.camera_height],cameraSize);assert.match(field('dimensions').textContent,new RegExp(`${cameraSize[0]} × ${cameraSize[1]}`));
field('shape').value='custom';field('shape').onchange();field('width').value='448';field('height').value='768';field('width').commitDimension();
assert.deepEqual([studio.config.camera_width,studio.config.camera_height],[448,768]);stage='image';control.sync();assert.match(field('dimensions').textContent,/448 × 768/);
for(const recipe of ENDPOINT_RECIPES)for(const shape of ['landscape','portrait','square','standard','vertical'])for(let i=5;i<=20;i++){
  const size=endpointPresetSize(recipe.id,shape,i/20);
  assert.equal(size.width%recipe.dimensionStep,0);assert.equal(size.height%recipe.dimensionStep,0);assert.ok(size.width*size.height<=recipe.maxPixels);assert.ok(size.width>0&&size.height>0);
}
console.log('Resolution: live MP sizing, model grids and budgets, independent relight stages, whole-number selection and deferred validation pass.');

const sliderSource=document.createElement('select');document.body.append(sliderSource);
assert.ok(Number(megapixelSlider(sliderSource).max)>=4,'The shared megapixel slider must not silently fall back to a 1 MP maximum');
for(const recipe of ENDPOINT_RECIPES){
  const size=endpointPresetSize(recipe.id,'landscape',4);
  assert.ok(size.width>=2560&&size.height>=1408,recipe.id+' exposes at least a 2K landscape processing size');
}

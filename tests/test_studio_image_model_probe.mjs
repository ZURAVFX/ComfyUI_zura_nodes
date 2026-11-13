import assert from 'node:assert/strict';
import {CreativeWorkspace} from '../web/studio_create.js';
import {IMAGE_MODELS,buildImageGraph,imageDimensions} from '../web/image_recipes.js';
import {studioModeAdapter} from '../web/studio_mode_adapters.js';

// Exercise the real loadModels and config methods. A reference-only unit fixture
// misses the separate model-discovery graph which must also carry a raster.
const info={};
for(const model of IMAGE_MODELS)for(const node of Object.values(buildImageGraph({model:model.id,prompt:'Probe fixture',references:model.minReferences?[{file:'fixture.png',width:1024,height:1024}]:[]})))info[node.class_type]={input:{required:{}}};
info.UNETLoader.input.required.unet_name=[IMAGE_MODELS.map(model=>model.model)];
info.CLIPLoader.input.required={clip_name:[IMAGE_MODELS.flatMap(model=>[model.text,model.upsampler].filter(Boolean))],type:[IMAGE_MODELS.map(model=>model.type)]};
info.VAELoader.input.required.vae_name=[IMAGE_MODELS.map(model=>model.vae)];
for(const type of ['LoraLoaderModelOnly','LoraLoaderBypassModelOnly'])info[type].input.required.lora_name=[IMAGE_MODELS.map(model=>model.lora).filter(Boolean)];
const controls=new Map(),messages=[],requests=[];
const c=Object.create(CreativeWorkspace.prototype);
Object.assign(c,{mode:'image',imageOperation:'edit',imageIntent:'standard',models:[],draft:{model:'klein9b'},references:[],imageLoras:[],studio:{},
  $(id){if(!controls.has(id))controls.set(id,{value:'',checked:false,innerHTML:'',querySelectorAll:()=>[],querySelector:()=>null});return controls.get(id);},
  async fetch(path){requests.push(path);return path.startsWith('/object_info/')?{[path.split('/').at(-1)]:info[path.split('/').at(-1)]}:{models:[]};},
  message(text){messages.push(text);},render(){},save(){this.draft=this.config();},show(id){this.mode=id;},clearImageResult(){this.items=[];},
});
for(const [id,value] of [['prompt','Change the wall to red'],['shape','auto'],['width','512'],['height','512'],['seed','42']])c.$(id).value=value;
await c.loadModels();
assert.deepEqual(messages,[],'Real model discovery must not fail a synthetic edit reference with missing dimensions');
assert.equal(c.models.length,IMAGE_MODELS.length);
assert.ok(c.models.every(model=>model.ready),'Installed node fixtures are fully discoverable');
assert.ok(requests.some(path=>path.startsWith('/object_info/')),'Discovery reaches the node endpoint');

const source={width:512,height:512,frameCount:1,precision:{sourceBitDepth:32},manifest:{frames:[{}],frameRate:{numerator:24,denominator:1}},
  processingInput:{precision:{sourceBitDepth:8},stills:{first:{file:'ae-derived.png'}}}};
await studioModeAdapter('image').acceptInput(c,source);
for(const model of ['qwen2511','klein9b','flux3edit']){
  c.$('model').value=model;
  const config=c.config();
  assert.deepEqual([config.references[0].width,config.references[0].height],[512,512],'Real config retains the broker source raster');
  assert.deepEqual(imageDimensions(config),[512,512]);
  const graph=buildImageGraph(config);
  assert.ok(graph.save,`${model} builds a complete edit graph after actual discovery and source acceptance`);
}
assert.equal(c.references[0].file,'ae-derived.png');
assert.equal(source.processingInput.stills.first.width,undefined);
console.log('Real image model discovery, AE source acceptance, config and Qwen/Klein/Flux edit graph consumers pass.');

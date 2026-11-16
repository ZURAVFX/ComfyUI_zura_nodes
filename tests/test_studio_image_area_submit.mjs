import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {CreativeWorkspace} from '../web/studio_create.js';
import {ImageEditArea} from '../web/studio_image_area.js';
import {IMAGE_MODELS,buildImageGraph} from '../web/image_recipes.js';
import {IMAGE_AREA_NODE_TYPES,smartCropCapabilities} from '../web/studio_image_area_graph.js';

const {document}=parseHTML('<html><body><main><div class="zc-image-tools"></div><div id="zc-source"></div><div id="zc-gallery"></div><div id="zc-image-empty"></div><div id="zc-reference-list"></div><input id="zc-width" value="1280"><input id="zc-height" value="720"><progress id="zc-bar"></progress><span id="zc-progress-title"></span><span id="zc-progress-detail"></span></main></body></html>');
globalThis.document=document;
const source={filename:'main.png',subfolder:'zura_images/references',file:'zura_images/references/main.png',width:1280,height:720};
const requests=[],info=Object.fromEntries(IMAGE_AREA_NODE_TYPES.map(type=>[type,{input:{required:{},optional:{}}}]));
info.SmartImageCrop.input.optional.context_padding=['INT'];
info.SmartImageStitcher.input.optional.feather_mode=[['Auto','Pixels']];
const owner={root:document.querySelector('main'),mode:'image',imageOperation:'edit',editMainMissing:false,references:[source],draft:{},items:[],selectedImage:-1,
  editInputs:{source:document.querySelector('#zc-source'),showSource:false},
  selectedModel:'qwen2511',models:['qwen2511','flux3edit'].map(id=>({...IMAGE_MODELS.find(model=>model.id===id),ready:true})),
  imageAreaCapabilities:smartCropCapabilities(info),browserConnection:{connected:()=>true},
  api:{clientId:'fixture',apiURL:path=>path,async fetchApi(path,options){requests.push({path,options});
    if(path==='/upload/image')return {ok:true,json:async()=>({name:'area.png',subfolder:'zura_images/edit_areas'})};
    if(path==='/prompt')return {ok:true,json:async()=>({prompt_id:'image-run'})};
    if(path==='/history/image-run')return {ok:true,json:async()=>({'image-run':{status:{completed:true,status_str:'success',messages:[]},outputs:{save:{images:[{filename:'generated.png',subfolder:'zura_images',type:'output'}]}}}})};
    throw Error(`Unexpected request: ${path}`);
  }},
  $(id){return this.root.querySelector('#zc-'+id);},
  fetch:CreativeWorkspace.prototype.fetch,imageGraph:CreativeWorkspace.prototype.imageGraph,
  config(){return {model:this.selectedModel,operation:'edit',prompt:'Change the selected lettering',shape:'auto',processingResolution:'auto',deliveryResolution:'original',width:1280,height:720,seed:17,random:false,references:this.references.map(ref=>({...ref})),loras:[],edit_area:this.imageArea.config()};},
  save(){return true;},render(){},startPolling(){},stopPolling(){},message(value){this.messageText=value;},
  imageLayers:{accept:async(config,file)=>({...config,file})},
  activateImageResult(index){this.selectedImage=index;},
};
owner.imageArea=new ImageEditArea(owner);
owner.imageArea.restore({enabled:true,source_key:source.file,context:64,feather:16});
owner.imageArea.viewer={maskPresent:true,sketchPresent:false,history:[],root:document.createElement('div'),width:1280,height:720,
  maskCanvas:{width:1280,height:720,toBlob(callback){callback(new Blob(['nonempty painted area'],{type:'image/png'}));}},
  measureMask(){return true;},measureSketch(){return false;},dispose(){},setTool(){}};
owner.imageArea.changed({kind:'area'});clearTimeout(owner.imageArea.saveTimer);
await CreativeWorkspace.prototype.generate.call(owner);
assert.equal(owner.messageText,'','A valid painted edit has no preflight error');
assert.equal(requests.filter(request=>request.path==='/upload/image').length,1,'One nonempty area is uploaded');
const prompts=requests.filter(request=>request.path==='/prompt');
assert.equal(prompts.length,1,'Generate submits one owned ComfyUI prompt');
const submitted=JSON.parse(prompts[0].options.body).prompt;
assert.equal(submitted.reference_1.inputs.image,source.file,'The original source remains Image 1');
assert.equal(submitted.zura_area_mask_image.inputs.image,'zura_images/edit_areas/area.png','The uploaded area reaches the graph');
assert.deepEqual(submitted.zura_area_crop.inputs.mask,['zura_area_mask',0]);
assert.deepEqual(submitted.sample.inputs.latent_image,buildImageGraph({...owner.config(),edit_area:{enabled:false}}).sample.inputs.latent_image,'The actual sampler keeps Qwen’s native latent');
assert.equal(submitted.zura_area_masked_latent,undefined,'Paint Area does not replace the model latent');
assert.deepEqual(submitted.zura_area_composite.inputs.mask,['zura_area_mask',1],'The final composite confines the visible edit to the painted area');
assert.deepEqual(submitted.save.inputs.images,['zura_area_composite',0],'The model output, not the source, is saved');
assert.equal(owner.job.id,'image-run');
await CreativeWorkspace.prototype.poll.call(owner);
assert.equal(owner.items[0].file.filename,'generated.png');
assert.equal(owner.selectedImage,0,'Completed output becomes the selected result');
owner.selectedModel='flux3edit';
await CreativeWorkspace.prototype.generate.call(owner);
const fluxPrompt=requests.filter(request=>request.path==='/prompt').at(-1);
const fluxGraph=JSON.parse(fluxPrompt.options.body).prompt;
assert.equal(requests.filter(request=>request.path==='/prompt').length,2,'A second edit submits one new prompt');
assert.deepEqual(fluxGraph.sample.inputs.latent_image,buildImageGraph({...owner.config(),edit_area:{enabled:false}}).sample.inputs.latent_image,'Flux 3 sampling keeps its native latent');
assert.deepEqual(fluxGraph.zura_area_composite.inputs.mask,['zura_area_mask',1],'Flux 3 also composites only the painted area');
assert.deepEqual(fluxGraph.prompt_images.inputs['images.image0'],['source_size',0],'Flux 3 image-aware prompt receives the selected crop');
assert.deepEqual(fluxGraph.save.inputs.images,['zura_area_composite',0]);
assert.equal(owner.job.id,'image-run');
console.log('Painted Image Edit submits Qwen and Flux 3 model graphs and selects completed output.');

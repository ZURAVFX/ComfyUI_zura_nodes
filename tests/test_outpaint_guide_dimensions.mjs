import assert from 'node:assert/strict';
import {OutpaintFirstFrame} from '../web/studio_outpaint_first_frame.js';
import {IMAGE_MODELS,buildImageGraph,imageDimensions} from '../web/image_recipes.js';
import {aeIntermediateImage} from '../web/studio_image_handoff_contract.js';

for(const ae of [false,true]){
 const fields=Object.fromEntries(['shape','width','height','prompt','random'].map(key=>[key,{value:'',checked:false}]));
 const base=Object.freeze({sessionId:'a'.repeat(32),frameCount:9,width:1920,height:1080,frameRate:Object.freeze({numerator:24,denominator:1})});
 const owner={mode:'outpaint',models:[{id:'klein9b'}],items:[],selectedImage:-1,...(ae?{aeFrameBase:base}:{}),
  config:()=>({operation:'create',shape:'auto',references:[]}),$:key=>fields[key],show(mode){this.mode=mode;},async setImageOperation(operation){this.operation=operation;},save(){},render(){},renderGallery(){}};
 const selection={source:'video',start:0,duration:9/24,mode:'black',width:1920,height:1080,left:0,top:0,right:0,bottom:0};
 const workspace={owner,source:{id:'video'},config:()=>({...selection}),dimensions:()=>({width:1920,height:1080}),hdrBusy:()=>false,paint(){},message(message){this.status=message;},$:()=>({value:'Continue the office walls'}),async fetch(){return{file:'guides/black-1920x1080.png',width:1920,height:1080};}};
 const guide=Object.assign(Object.create(OutpaintFirstFrame.prototype),{workspace,owner,transferRevision:0,syncImageUI(){}});
 await guide.generate();assert.equal(owner.operation,'edit');assert.equal(fields.shape.value,'auto');assert.equal(guide.request.width,1920);assert.equal(guide.request.height,1080);assert.equal(workspace.submitting,false);
 assert.equal(owner.references[0].height,1080);
 for(const model of IMAGE_MODELS.filter(m=>m.edit)){
  const config={model:model.id,operation:'edit',prompt:fields.prompt.value,shape:fields.shape.value,width:Number(fields.width.value),height:Number(fields.height.value),references:owner.references,seed:42};
  const graph=buildImageGraph(config);assert.ok(graph.save,model.id);assert.equal(graph.reference_1.inputs.image,'guides/black-1920x1080.png');assert.deepEqual(imageDimensions(config),[1920,1088]);
  if(model.provider)assert.equal(graph.browser_image.inputs.size,'Auto');
  else{assert.equal(graph.source_size.class_type,'ImageScale');assert.equal(graph.source_size.inputs.width,1920);assert.equal(graph.source_size.inputs.height,1088);assert.equal(graph.output_size.inputs.height,1080);}
 }
 if(ae){assert.equal(owner.aeFrameBase,base);assert.equal(base.frameCount,9);const descriptor=aeIntermediateImage(owner);assert.equal(descriptor.width,1920);assert.equal(descriptor.height,1080);assert.equal(descriptor.sourceFrame,0);assert.equal(descriptor.parentFrameCount,9);}
}
console.log('1920x1080 black outpaint guides build every local/browser image-edit recipe with Auto alignment and retain exact guide raster and AE parentN9');

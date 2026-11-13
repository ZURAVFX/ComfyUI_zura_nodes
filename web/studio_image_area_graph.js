// Optional source-space edit area. Crop and stitch are Hallett's native nodes;
// the small Zura nodes only validate the artist mask and returned crop.
export const IMAGE_AREA_NODE_TYPES=[
  'LoadImage','GetImageSize','ImageScale','ImageScaleToTotalPixels','ResizeAndPadImage','ImageCompositeMasked',
  'SmartImageCrop','SmartImageStitcher','ZuraImageEditMask','ZuraImageEditCropResult','ZuraImageEditResolution',
  'VAEEncode','SetLatentNoiseMask','MaskToImage','ImageToMask',
];

export function imageAreaSourceKey(reference){return typeof reference?.file==='string'?reference.file:'';}

export function smartCropCapabilities(info={}){
  const missing=IMAGE_AREA_NODE_TYPES.filter(name=>!info?.[name]);
  const inputs=name=>({...info?.[name]?.input?.required,...info?.[name]?.input?.optional});
  const crop=inputs('SmartImageCrop'),stitch=inputs('SmartImageStitcher');
  return {available:!missing.length,missing,schema:{
    contextPadding:Object.hasOwn(crop,'context_padding'),
    maxMegapixels:Object.hasOwn(crop,'max_megapixels'),
    featherMode:Object.hasOwn(stitch,'feather_mode'),
  }};
}

const node=(class_type,title,inputs)=>({class_type,_meta:{title},inputs});

/** Wrap a complete image-edit graph while preserving its native model path. */
export function applyImageEditArea(graph,{edit_area,smart_crop_schema,recipe,shape,width,height,references,retain_layer_context=false}){
  if(!edit_area?.enabled)return graph;
  if(!recipe?.edit)throw new Error('Choose Edit image to paint an edit area.');
  const source=imageAreaSourceKey(references?.[0]);
  const mask=edit_area.mask?.file;
  if(!source||edit_area.source_key!==source)throw new Error('The edit area belongs to a different main image. Paint it again.');
  if(typeof mask!=='string'||!mask||mask.includes('..'))throw new Error('Paint and save an edit area before applying the edit.');
  if(!graph.reference_1||!graph.save?.inputs?.images)throw new Error('This image model cannot use an edit area yet.');
  const context=Number(edit_area.context??64),feather=Number(edit_area.feather??16);
  if(!Number.isInteger(context)||context<0||context>4096||!Number.isInteger(feather)||feather<0||feather>256)throw new Error('Choose a valid context and feather size for the edit area.');
  const schema=smart_crop_schema||{contextPadding:true,featherMode:true,maxMegapixels:true};
  const step=recipe.sizeStep||16;
  const megapixels=width*height/(1024*1024);
  if(shape!=='auto'&&megapixels>16)throw new Error('The edit area supports up to 16 MP of AI processing. Choose a smaller processing size.');

  // Rewrite only consumers of Image 1. Keep the original LoadImage for the
  // crop and final source-sized composite; all other references stay intact.
  const replace=value=>{
    if(Array.isArray(value))return value.length===2&&value[0]==='reference_1'&&value[1]===0?['zura_area_working',0]:value.map(replace);
    if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,replace(item)]));
    return value;
  };
  for(const entry of Object.values(graph))entry.inputs=replace(entry.inputs);
  const dimensions=['zura_area_size',0],heightDimensions=['zura_area_size',1];
  // Every model's output canvas and native scheduler must use the actual crop
  // dimensions rather than the full-source dimensions entered in the UI.
  for(const entry of Object.values(graph)){
    for(const key of ['width','custom_width'])if(Object.hasOwn(entry.inputs,key))entry.inputs[key]=dimensions;
    for(const key of ['height','custom_height'])if(Object.hasOwn(entry.inputs,key))entry.inputs[key]=heightDimensions;
    // A painted crop changes the actual source raster. Retarget only the
    // primary source-size stretch so it still removes grid rounding before the
    // final stitcher restores the full original image.
    if(entry.class_type==='ImageScale'&&entry.inputs.image?.[0]==='zura_area_working'){
      entry.inputs.width=dimensions;
      entry.inputs.height=heightDimensions;
      entry.inputs.crop='disabled';
    }
  }
  if(recipe.provider)graph.browser_image.inputs.size='Custom';
  const generated=graph.save.inputs.images;
  graph.zura_area_mask_image=node('LoadImage','Load painted edit area',{image:mask});
  graph.zura_area_mask=node('ZuraImageEditMask','Prepare edit area',{image:['reference_1',0],painted_mask:['zura_area_mask_image',0],feather_pixels:feather,...(edit_area.guide?.file?{drawing_region:edit_area.drawing_region!==false}:{})});
  const crop={image:['reference_1',0],mask:['zura_area_mask',0],resolution_mode:'Automatic',max_resolution:8192,min_resolution:256,manual_width:1024,manual_height:1024,mask_grow_pixels:schema.contextPadding?0:context,patch_mask_holes:false,no_mask_mode:'Bypass',force_divisibility:step};
  if(schema.contextPadding)crop.context_padding=context;
  graph.zura_area_crop=node('SmartImageCrop','Crop selected area with context',crop);
  // Auto preserves larger native crops and gives small crops a 1 MP quality
  // floor. Explicit sizes remain approximate MP targets at the crop's aspect.
  let guideCrop=['zura_area_crop',0];
  if(edit_area.guide?.file){
    const guide=edit_area.guide.file;if(typeof guide!=='string'||!guide||guide.includes('..'))throw Error('Choose a valid drawing guide.');
    graph.zura_drawing=node('LoadImage','Load the drawn guide',{image:guide});
    // The brush uses a bounded preview raster. Restore it to source coordinates
    // before cropping: context padding and mask bounds must mean the same pixels.
    graph.zura_area_source_size=node('GetImageSize','Original source dimensions',{image:['reference_1',0]});
    graph.zura_drawing_source=node('ImageScale','Align drawing with original source',{image:['zura_drawing',0],upscale_method:'bilinear',width:['zura_area_source_size',0],height:['zura_area_source_size',1],crop:'disabled'});
    graph.zura_drawing_crop=node('SmartImageCrop','Use the same edit area for the drawing',{...crop,image:['zura_drawing_source',0]});guideCrop=['zura_drawing_crop',0];
  }
  graph.zura_area_target=node('ZuraImageEditResolution','Keep the crop within model size limits',{image:['zura_area_crop',0],megapixels:shape==='auto'?0:Math.max(.01,megapixels),resolution_steps:step});
  graph.zura_area_working=node('ImageScaleToTotalPixels','Set edit processing size',{image:guideCrop,upscale_method:'lanczos',megapixels:['zura_area_target',0],resolution_steps:step});
  graph.zura_area_size=node('GetImageSize','Edit processing dimensions',{image:['zura_area_working',0]});
  if(!recipe.provider){
    const sample=graph.sample,vae=graph.decode?.inputs?.vae;
    if(!sample?.inputs?.latent_image||!vae)throw Error('This model cannot constrain a painted edit yet. Choose a supported local image editor.');
    graph.zura_area_clean=node('ImageScale','Clean source at edit processing size',{image:['zura_area_crop',0],upscale_method:'lanczos',width:dimensions,height:heightDimensions,crop:'disabled'});
    graph.zura_area_latent=node('VAEEncode','Encode clean source for local editing',{pixels:['zura_area_clean',0],vae});
    graph.zura_area_mask_pixels=node('MaskToImage','Selected crop mask',{mask:['zura_area_crop',1]});
    graph.zura_area_mask_size=node('ImageScale','Align selection with sampling raster',{image:['zura_area_mask_pixels',0],upscale_method:'nearest-exact',width:dimensions,height:heightDimensions,crop:'disabled'});
    graph.zura_area_noise_mask=node('ImageToMask','Sampling area',{image:['zura_area_mask_size',0],channel:'red'});
    graph.zura_area_masked_latent=node('SetLatentNoiseMask','Sample only inside the selected area',{samples:['zura_area_latent',0],mask:['zura_area_noise_mask',0]});
    sample.inputs.latent_image=['zura_area_masked_latent',0];
  }
  graph.zura_area_result=node('ZuraImageEditCropResult','Check edited crop',{image:generated,reference:['zura_area_working',0]});
  const stitch={original_image:['reference_1',0],processed_image:['zura_area_result',0],stitcher_info:['zura_area_crop',2],feather_pixels:0,blend_mode:'Mask Feather',resize_full_image_output:'Restore Original Size',enable_color_match:false,color_match_amount:0,mask:['zura_area_crop',1]};
  // Paint/Replace applies its editable layer mask after this image is imported.
  // Retain the generated context crop here so expanding that mask can reveal
  // real generated pixels. Standalone edits still protect all unpainted pixels.
  if(retain_layer_context===true){stitch.blend_mode='Hard Paste';delete stitch.mask;}
  if(schema.featherMode)stitch.feather_mode='Pixels';
  graph.zura_area_stitch=node('SmartImageStitcher','Stitch edited crop',stitch);
  if(retain_layer_context===true)graph.save.inputs.images=['zura_area_stitch',0];
  else{
    graph.zura_area_composite=node('ImageCompositeMasked','Preserve unpainted image',{destination:['reference_1',0],source:['zura_area_stitch',0],mask:['zura_area_mask',1],x:0,y:0,resize_source:false});
    graph.save.inputs.images=['zura_area_composite',0];
  }
  return graph;
}
